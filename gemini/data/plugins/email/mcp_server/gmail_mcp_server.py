#!/usr/bin/env python3
"""
Email (Gmail triage) MCP Server for Antigravity (`email` plugin).

A zero-dependency Python 3 Model Context Protocol (MCP) server over stdio
that connects to the official Gmail REST API using Google Cloud OAuth 2.0.

Features:
- Check OAuth authentication status (`gmail_auth_status`)
- Run local browser OAuth 2.0 login flow (`gmail_authenticate` or `--auth` CLI flag)
- List labels and create missing triage labels (`gmail_list_labels`, `gmail_ensure_labels`)
- Fetch compact inbox summaries for fast triage (`gmail_fetch_inbox`)
- Read full message content when needed (`gmail_get_message`)
- Batch-apply labels, mark read, or archive safely (`gmail_batch_triage`)
- Unsubscribe from mailing lists (`gmail_unsubscribe`)
- Reply with headers derived from the real parent message (`gmail_reply`)
- Create and send drafts (`gmail_create_draft`, `gmail_send_draft`) or send new mail (`gmail_send_message`)

Safety guardrail: This server never deletes or trashes messages.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
from email.message import EmailMessage
import email.utils
import html
import http.server
import json
import os
import re
import secrets
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

_TOKEN_LOCK = threading.Lock()

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
]


def _resolve_private_dir() -> Path:
    for candidate in (
        Path.home() / "vaults" / "personal" / "! PRIVATE",
        Path.home() / "vaults" / "home" / "! PRIVATE",
        Path.home() / "obsidian-home" / "! PRIVATE",
    ):
        if candidate.exists():
            return candidate
    return Path.home() / "vaults" / "personal" / "! PRIVATE"


PRIVATE_DIR = _resolve_private_dir()
DEFAULT_CREDENTIALS_PATH = PRIVATE_DIR / "gmail-credentials.json"
DEFAULT_TOKEN_PATH = PRIVATE_DIR / "gmail-token.json"

_env_creds = os.environ.get("GMAIL_CREDENTIALS_PATH")
CREDENTIALS_PATH = (
    Path(_env_creds).expanduser()
    if _env_creds and Path(_env_creds).expanduser().exists()
    else DEFAULT_CREDENTIALS_PATH
)
_env_token = os.environ.get("GMAIL_TOKEN_PATH")
TOKEN_PATH = (
    Path(_env_token).expanduser()
    if _env_token and Path(_env_token).expanduser().exists()
    else DEFAULT_TOKEN_PATH
)

DEFAULT_TRIAGE_LABELS = [
    "Triage/Needs Reply",
    "Triage/FYI",
    "Triage/Receipts",
    "Triage/Newsletters",
    "Triage/Replied",
    "Triage/Waiting",
]


def log_err(msg: str) -> None:
    """Log diagnostic messages to stderr so stdout remains pure MCP JSON-RPC."""
    sys.stderr.write(f"[email-mcp] {msg}\n")
    sys.stderr.flush()


class GmailAuthError(Exception):
    """Raised when OAuth credentials or tokens are missing or invalid."""


def _load_client_config() -> dict[str, Any]:
    if not CREDENTIALS_PATH.exists():
        raise GmailAuthError(
            f"OAuth client file not found at {CREDENTIALS_PATH}. "
            "Download a Desktop App OAuth 2.0 JSON file from Google Cloud Console "
            f"and save it to {CREDENTIALS_PATH}."
        )
    with CREDENTIALS_PATH.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    client_info = raw.get("installed") or raw.get("web")
    if not client_info or "client_id" not in client_info or "client_secret" not in client_info:
        raise GmailAuthError(
            f"Invalid credentials file at {CREDENTIALS_PATH}: "
            "expected 'installed' or 'web' OAuth client configuration."
        )
    return client_info


def _save_token(token_data: dict[str, Any]) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TOKEN_PATH.open("w", encoding="utf-8") as f:
        json.dump(token_data, f, indent=2)
    os.chmod(TOKEN_PATH, 0o600)


def _refresh_access_token(
    client_info: dict[str, Any], token_data: dict[str, Any]
) -> dict[str, Any]:
    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        raise GmailAuthError(
            "Saved token does not contain a refresh_token. Please re-authenticate."
        )

    payload = urllib.parse.urlencode(
        {
            "client_id": client_info["client_id"],
            "client_secret": client_info["client_secret"],
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        OAUTH_TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            refreshed = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise GmailAuthError(f"Failed to refresh OAuth token ({e.code}): {err_body}") from e

    token_data["access_token"] = refreshed["access_token"]
    if "expires_in" in refreshed:
        token_data["expires_in"] = refreshed["expires_in"]
    if "refresh_token" in refreshed:
        token_data["refresh_token"] = refreshed["refresh_token"]
    _save_token(token_data)
    return token_data


def run_oauth_flow(port: int = 0, timeout_sec: int = 180) -> dict[str, Any]:
    """Run loopback OAuth 2.0 flow in the user's browser and store token.json."""
    client_info = _load_client_config()
    try:
        urllib.request.urlopen(
            "https://accounts.google.com/.well-known/openid-configuration",
            timeout=3,
        ).close()
    except Exception as exc:
        raise GmailAuthError(f"Network access required for OAuth flow: {exc}") from exc

    state_secret = secrets.token_urlsafe(16)
    auth_result: dict[str, str | None] = {"code": None, "error": None}

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            _ = (format, args)

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            if params.get("state", [None])[0] != state_secret:
                auth_result["error"] = "OAuth state mismatch"
            elif "error" in params:
                auth_result["error"] = params["error"][0]
            elif "code" in params:
                auth_result["code"] = params["code"][0]
            else:
                auth_result["error"] = "Missing authorisation code"

            body = (
                b"<html><body style='font-family:sans-serif;padding:2rem;'>"
                b"<h2>Email MCP Authentication Complete</h2>"
                b"<p>You can close this tab and return to Antigravity.</p>"
                b"</body></html>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = http.server.HTTPServer(("127.0.0.1", port), CallbackHandler)
    server.timeout = timeout_sec
    bound_port = server.server_port
    redirect_uri = f"http://127.0.0.1:{bound_port}"

    auth_params = urllib.parse.urlencode(
        {
            "client_id": client_info["client_id"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state_secret,
        }
    )
    auth_url = f"{OAUTH_AUTH_URL}?{auth_params}"
    log_err(f"Opening browser for Google OAuth sign-in: {auth_url}")
    webbrowser.open(auth_url)

    server.handle_request()
    server.server_close()

    oauth_error = auth_result.get("error")
    if oauth_error:
        raise GmailAuthError(f"OAuth authorisation failed: {oauth_error}")
    oauth_code = auth_result.get("code")
    if not oauth_code:
        raise GmailAuthError("OAuth login timed out waiting for browser callback.")

    token_payload = urllib.parse.urlencode(
        {
            "code": oauth_code,
            "client_id": client_info["client_id"],
            "client_secret": client_info["client_secret"],
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        OAUTH_TOKEN_URL,
        data=token_payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        token_data = json.loads(resp.read().decode("utf-8"))

    _save_token(token_data)
    return token_data


def _gmail_request(
    method: str,
    endpoint: str,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Perform an authenticated Gmail API request with automatic 401 token refresh."""
    client_info = _load_client_config()
    if not TOKEN_PATH.exists():
        raise GmailAuthError(
            f"OAuth token not found at {TOKEN_PATH}. "
            "Run the `gmail_authenticate` tool or "
            "`python3 ~/.gemini/config/plugins/email/mcp_server/"
            "gmail_mcp_server.py --auth` first."
        )
    with TOKEN_PATH.open("r", encoding="utf-8") as f:
        token_data = json.load(f)

    url = f"{GMAIL_API_BASE}/{endpoint.lstrip('/')}"
    if params:
        query_items: list[tuple[str, str]] = []
        for k, v in params.items():
            if v is None:
                continue
            if isinstance(v, list):
                for item in v:
                    query_items.append((k, str(item)))
            else:
                query_items.append((k, str(v)))
        if query_items:
            url = f"{url}?{urllib.parse.urlencode(query_items)}"

    data_bytes = json.dumps(body).encode("utf-8") if body is not None else None

    for attempt in range(2):
        headers = {
            "Authorization": f"Bearer {token_data.get('access_token', '')}",
            "Accept": "application/json",
        }
        if data_bytes is not None:
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                raw_resp = resp.read().decode("utf-8")
                return json.loads(raw_resp) if raw_resp.strip() else {}
        except urllib.error.HTTPError as e:
            if e.code == 401 and attempt == 0:
                token_data = _refresh_access_token(client_info, token_data)
                continue
            err_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Gmail API error ({e.code} on {endpoint}): {err_body}") from e

    raise RuntimeError("Unexpected authentication retry failure.")


def _decode_base64url(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="replace")


def _extract_plain_body(payload: dict[str, Any]) -> str:
    """Recursively extract plain text (or stripped HTML fallback) from a Gmail message payload."""
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data")
    if mime_type == "text/plain" and body_data:
        return _decode_base64url(body_data)

    parts = payload.get("parts", [])
    for part in parts:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return _decode_base64url(part["body"]["data"])

    for part in parts:
        nested = _extract_plain_body(part)
        if nested:
            return nested

    if mime_type == "text/html" and body_data:
        raw_html = _decode_base64url(body_data)
        text = re.sub(
            r"<style[^>]*>.*?</style>",
            "",
            raw_html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        text = re.sub(
            r"<script[^>]*>.*?</script>",
            "",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        text = re.sub(r"<[^>]+>", " ", text)
        return html.unescape(re.sub(r"\s+", " ", text)).strip()

    return ""


def _get_label_maps() -> tuple[dict[str, str], dict[str, str], list[dict[str, Any]]]:
    """Return (name_lower_to_id, id_to_name, raw_labels)."""
    res = _gmail_request("GET", "labels")
    labels = res.get("labels", [])
    name_to_id: dict[str, str] = {}
    id_to_name: dict[str, str] = {}
    for lbl in labels:
        lid = lbl.get("id", "")
        lname = lbl.get("name", "")
        if lid and lname:
            name_to_id[lname.lower()] = lid
            id_to_name[lid] = lname
    return name_to_id, id_to_name, labels


# ---------------------------------------------------------------------------
# Tool Implementations
# ---------------------------------------------------------------------------


def tool_auth_status(_args: dict[str, Any]) -> dict[str, Any]:
    has_creds = CREDENTIALS_PATH.exists()
    has_token = TOKEN_PATH.exists()
    status: dict[str, Any] = {
        "credentials_path": str(CREDENTIALS_PATH),
        "credentials_found": has_creds,
        "token_path": str(TOKEN_PATH),
        "token_found": has_token,
        "authenticated": False,
    }
    if has_creds and has_token:
        try:
            profile = _gmail_request("GET", "profile")
            status["authenticated"] = True
            status["email_address"] = profile.get("emailAddress")
            status["messages_total"] = profile.get("messagesTotal")
            status["threads_total"] = profile.get("threadsTotal")
        except Exception as exc:
            status["error"] = str(exc)
    return status


def tool_authenticate(_args: dict[str, Any]) -> dict[str, Any]:
    run_oauth_flow()
    profile = _gmail_request("GET", "profile")
    return {
        "authenticated": True,
        "email_address": profile.get("emailAddress"),
        "token_path": str(TOKEN_PATH),
    }


def tool_list_labels(_args: dict[str, Any]) -> dict[str, Any]:
    _, _, labels = _get_label_maps()
    sorted_labels = sorted(
        [
            {
                "id": lbl.get("id"),
                "name": lbl.get("name"),
                "type": lbl.get("type"),
            }
            for lbl in labels
        ],
        key=lambda x: (x.get("type") != "user", (x.get("name") or "").lower()),
    )
    return {"count": len(sorted_labels), "labels": sorted_labels}


def tool_ensure_labels(args: dict[str, Any]) -> dict[str, Any]:
    label_names: list[str] = args.get("label_names") or DEFAULT_TRIAGE_LABELS
    name_to_id, _, _ = _get_label_maps()
    created: list[dict[str, str]] = []
    existing: list[dict[str, str]] = []

    for name in label_names:
        clean_name = name.strip()
        if not clean_name:
            continue
        if clean_name.lower() in name_to_id:
            existing.append({"name": clean_name, "id": name_to_id[clean_name.lower()]})
        else:
            new_lbl = _gmail_request(
                "POST",
                "labels",
                body={
                    "name": clean_name,
                    "labelListVisibility": "labelShow",
                    "messageListVisibility": "show",
                },
            )
            created.append(
                {
                    "name": new_lbl.get("name", clean_name),
                    "id": new_lbl.get("id", ""),
                }
            )
            name_to_id[clean_name.lower()] = new_lbl.get("id", "")

    return {"created": created, "existing": existing}


def _fetch_message_metadata(msg_id: str, id_to_name: dict[str, str]) -> dict[str, Any]:
    msg = _gmail_request(
        "GET",
        f"messages/{msg_id}",
        params={
            "format": "metadata",
            "metadataHeaders": [
                "From",
                "To",
                "Subject",
                "Date",
                "List-Unsubscribe",
            ],
        },
    )
    headers_list = msg.get("payload", {}).get("headers", [])
    headers = {h["name"].lower(): h["value"] for h in headers_list if "name" in h and "value" in h}
    label_ids = msg.get("labelIds", [])
    label_names = [id_to_name.get(lid, lid) for lid in label_ids]

    return {
        "id": msg.get("id"),
        "threadId": msg.get("threadId"),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "subject": headers.get("subject", "(No Subject)"),
        "date": headers.get("date", ""),
        "snippet": html.unescape(msg.get("snippet", "")),
        "labels": label_names,
        "is_unread": "UNREAD" in label_ids,
        "has_list_unsubscribe": "list-unsubscribe" in headers,
    }


def _group_messages_by_sender(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for m in messages:
        raw_from = (m.get("from") or "Unknown Sender").strip()
        email_match = re.search(r"<([^>]+)>", raw_from)
        sender_key = (email_match.group(1) if email_match else raw_from).lower().strip()

        if sender_key not in groups:
            groups[sender_key] = {
                "sender": raw_from,
                "sender_email": sender_key,
                "count": 0,
                "unread_count": 0,
                "read_count": 0,
                "has_list_unsubscribe": False,
                "categories": set(),
                "sample_subjects": [],
                "latest_date": m.get("date", ""),
                "message_ids": [],
            }
        g = groups[sender_key]
        g["count"] += 1
        if m.get("is_unread"):
            g["unread_count"] += 1
        else:
            g["read_count"] += 1
        if m.get("has_list_unsubscribe"):
            g["has_list_unsubscribe"] = True
        for lbl in m.get("labels", []):
            if lbl.startswith("CATEGORY_") or lbl.startswith("Triage/") or lbl == "IMPORTANT":
                g["categories"].add(lbl)
        subj = m.get("subject", "")
        if subj and subj not in g["sample_subjects"] and len(g["sample_subjects"]) < 3:
            g["sample_subjects"].append(subj)
        g["message_ids"].append(m.get("id"))

    sorted_groups = sorted(
        groups.values(),
        key=lambda x: (-x["count"], -x["read_count"], x["sender_email"]),
    )
    for g in sorted_groups:
        g["categories"] = sorted(g["categories"])
    return sorted_groups


def tool_fetch_inbox(args: dict[str, Any]) -> dict[str, Any]:
    query = args.get("query", "label:INBOX")
    max_results = min(max(int(args.get("max_results", 500)), 1), 500)
    page_token = args.get("page_token")

    _, id_to_name, _ = _get_label_maps()
    inbox_label = _gmail_request("GET", "labels/INBOX")

    stubs: list[dict[str, Any]] = []
    next_token: str | None = page_token
    while len(stubs) < max_results:
        batch_size = min(100, max_results - len(stubs))
        params: dict[str, Any] = {"q": query, "maxResults": batch_size}
        if next_token:
            params["pageToken"] = next_token
        list_res = _gmail_request("GET", "messages", params=params)
        page_stubs = list_res.get("messages", [])
        if not page_stubs:
            next_token = None
            break
        stubs.extend(page_stubs)
        next_token = list_res.get("nextPageToken")
        if not next_token:
            break

    msg_ids = [s["id"] for s in stubs]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_fetch_message_metadata, mid, id_to_name) for mid in msg_ids]
        messages_summary = [f.result() for f in futures]

    sender_groups = _group_messages_by_sender(messages_summary)

    return {
        "query": query,
        "inbox_messages_total": inbox_label.get("messagesTotal"),
        "inbox_messages_unread": inbox_label.get("messagesUnread"),
        "inbox_threads_total": inbox_label.get("threadsTotal"),
        "inbox_threads_unread": inbox_label.get("threadsUnread"),
        "returned_count": len(messages_summary),
        "grouped_by_sender": len(messages_summary) > 100,
        "sender_group_count": len(sender_groups),
        "sender_groups": sender_groups,
        "next_page_token": next_token,
        "messages": messages_summary,
    }


def _extract_html_raw(payload: dict[str, Any]) -> str:
    """Recursively extract raw HTML from a Gmail message payload."""
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data")
    if mime_type == "text/html" and body_data:
        return _decode_base64url(body_data)
    for part in payload.get("parts", []):
        nested = _extract_html_raw(part)
        if nested:
            return nested
    return ""


def _extract_unsubscribe_info(headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    """Extract List-Unsubscribe URLs/mailtos, RFC 8058 One-Click, and body unsubscribe links."""
    raw_hdr = headers.get("list-unsubscribe", "")
    raw_post = headers.get("list-unsubscribe-post", "")
    bracket_items = re.findall(r"<([^>]+)>", raw_hdr)
    if not bracket_items and raw_hdr.strip():
        bracket_items = [item.strip() for item in raw_hdr.split(",") if item.strip()]

    http_urls = [u for u in bracket_items if u.lower().startswith(("http://", "https://"))]
    mailto_urls = [u for u in bracket_items if u.lower().startswith("mailto:")]

    body_unsub_urls: list[str] = []
    raw_html = _extract_html_raw(payload)
    if raw_html:
        for match in re.finditer(
            r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            raw_html,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            href, anchor_text = match.group(1), match.group(2)
            if "unsub" in href.lower() or "unsub" in anchor_text.lower():
                clean_url = html.unescape(href)
                if clean_url not in body_unsub_urls:
                    body_unsub_urls.append(clean_url)

    return {
        "list_unsubscribe_header": raw_hdr,
        "list_unsubscribe_post_header": raw_post,
        "supports_one_click_post": "one-click" in raw_post.lower() and bool(http_urls),
        "header_http_urls": http_urls,
        "header_mailto_urls": mailto_urls,
        "body_unsubscribe_urls": body_unsub_urls,
    }


def tool_get_message(args: dict[str, Any]) -> dict[str, Any]:
    message_id = args.get("message_id")
    if not message_id:
        raise ValueError("'message_id' is required.")
    max_chars = int(args.get("max_body_chars", 4000))

    _, id_to_name, _ = _get_label_maps()
    msg = _gmail_request("GET", f"messages/{message_id}", params={"format": "full"})
    payload = msg.get("payload", {})
    headers_list = payload.get("headers", [])
    headers = {h["name"].lower(): h["value"] for h in headers_list if "name" in h and "value" in h}
    body_text = _extract_plain_body(payload)
    if len(body_text) > max_chars:
        body_text = body_text[:max_chars] + "\n...[truncated]..."

    label_ids = msg.get("labelIds", [])
    return {
        "id": msg.get("id"),
        "threadId": msg.get("threadId"),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "cc": headers.get("cc", ""),
        "reply_to": headers.get("reply-to", ""),
        "subject": headers.get("subject", "(No Subject)"),
        "date": headers.get("date", ""),
        "message_id_header": headers.get("message-id", ""),
        "references": headers.get("references", ""),
        "auto_submitted": headers.get("auto-submitted", ""),
        "labels": [id_to_name.get(lid, lid) for lid in label_ids],
        "unsubscribe": _extract_unsubscribe_info(headers, payload),
        "snippet": html.unescape(msg.get("snippet", "")),
        "body": body_text,
    }


def _unsubscribe_single(message_id: str) -> dict[str, Any]:
    """Unsubscribe from a single message ID via RFC 8058 POST or List-Unsubscribe URL."""
    msg = _gmail_request("GET", f"messages/{message_id}", params={"format": "full"})
    payload = msg.get("payload", {})
    headers_list = payload.get("headers", [])
    headers = {h["name"].lower(): h["value"] for h in headers_list if "name" in h and "value" in h}
    unsub = _extract_unsubscribe_info(headers, payload)

    target_url: str | None = None
    method = "GET"
    post_data: bytes | None = None

    if unsub["header_http_urls"]:
        target_url = unsub["header_http_urls"][0]
        if unsub["supports_one_click_post"]:
            method = "POST"
            post_data = b"List-Unsubscribe=One-Click"
    elif unsub["body_unsubscribe_urls"]:
        target_url = unsub["body_unsubscribe_urls"][0]

    if not target_url:
        return {
            "message_id": message_id,
            "unsubscribed": False,
            "reason": "No HTTP unsubscribe URL found in List-Unsubscribe header or message body.",
            "from": headers.get("from", ""),
            "subject": headers.get("subject", ""),
            "unsubscribe_info": unsub,
        }

    req_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) TriageGmailMCP/1.1",
    }
    if method == "POST":
        req_headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = urllib.request.Request(target_url, data=post_data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            status_code = resp.getcode()
            resp_snippet = resp.read(500).decode("utf-8", errors="replace")
        return {
            "message_id": message_id,
            "unsubscribed": 200 <= status_code < 400,
            "method_used": "RFC 8058 One-Click POST" if method == "POST" else "HTTP GET",
            "http_status": status_code,
            "url": target_url,
            "response_preview": re.sub(r"<[^>]+>", " ", resp_snippet).strip()[:200],
            "from": headers.get("from", ""),
            "subject": headers.get("subject", ""),
        }
    except urllib.error.HTTPError as exc:
        return {
            "message_id": message_id,
            "unsubscribed": False,
            "method_used": method,
            "http_status": exc.code,
            "url": target_url,
            "error": str(exc),
            "from": headers.get("from", ""),
            "subject": headers.get("subject", ""),
            "unsubscribe_info": unsub,
        }


def tool_unsubscribe(args: dict[str, Any]) -> dict[str, Any]:
    """Unsubscribe from one or more messages via RFC 8058 POST or List-Unsubscribe URL."""
    msg_ids: list[str] = []
    if args.get("message_id"):
        msg_ids.append(str(args["message_id"]))
    if args.get("message_ids"):
        for mid in args["message_ids"]:
            if mid and str(mid) not in msg_ids:
                msg_ids.append(str(mid))
    if not msg_ids:
        raise ValueError("Provide 'message_id' or 'message_ids'.")

    if len(msg_ids) == 1:
        return _unsubscribe_single(msg_ids[0])

    results = [_unsubscribe_single(mid) for mid in msg_ids]
    return {
        "total": len(results),
        "succeeded": sum(1 for r in results if r.get("unsubscribed")),
        "results": results,
    }


def tool_batch_triage(args: dict[str, Any]) -> dict[str, Any]:
    """
    Apply triage actions in batch using Gmail's messages/batchModify.
    Each item in `actions` specifies:
      - message_ids: list of Gmail message IDs
      - add_labels: list of label names to add (auto-created if missing)
      - remove_labels: list of label names to remove
      - archive: bool (removes 'INBOX' label)
      - mark_read: bool (removes 'UNREAD' label)
    """
    actions = args.get("actions", [])
    if not actions:
        raise ValueError("'actions' must be a non-empty list of triage operations.")

    name_to_id, _, _ = _get_label_maps()

    def resolve_label_id(label_name: str, create_if_missing: bool) -> str:
        clean = label_name.strip()
        if clean.upper() in ("INBOX", "UNREAD", "STARRED", "IMPORTANT"):
            return clean.upper()
        if clean.lower() in name_to_id:
            return name_to_id[clean.lower()]
        if not create_if_missing:
            raise ValueError(f"Label '{clean}' does not exist.")
        created = _gmail_request(
            "POST",
            "labels",
            body={
                "name": clean,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
        )
        new_id = created["id"]
        name_to_id[clean.lower()] = new_id
        return new_id

    results: list[dict[str, Any]] = []
    total_modified = 0

    for idx, action in enumerate(actions):
        msg_ids = [m for m in action.get("message_ids", []) if m]
        if not msg_ids:
            continue

        add_names = action.get("add_labels", []) or []
        raw_remove_names = action.get("remove_labels", []) or []
        do_unsubscribe = bool(action.get("unsubscribe", False)) or any(
            n.strip().upper() == "UNSUBSCRIBE" for n in raw_remove_names
        )
        remove_names = [n for n in raw_remove_names if n.strip().upper() != "UNSUBSCRIBE"]
        archive = bool(action.get("archive", False))
        mark_read = bool(action.get("mark_read", False))

        unsub_results: list[dict[str, Any]] = (
            [_unsubscribe_single(mid) for mid in msg_ids] if do_unsubscribe else []
        )

        # Safety guardrail: refuse any attempt to add TRASH or SPAM via triage
        for forbidden in ("TRASH", "SPAM"):
            if any(n.strip().upper() == forbidden for n in add_names):
                raise ValueError(
                    f"Safety guardrail: adding '{forbidden}' is blocked. "
                    "Use archive=true to remove from Inbox instead of trashing messages."
                )

        add_ids = [resolve_label_id(name, create_if_missing=True) for name in add_names]
        remove_ids = [
            resolve_label_id(name, create_if_missing=False)
            for name in remove_names
            if name.strip().lower() in name_to_id
            or name.strip().upper() in ("INBOX", "UNREAD", "STARRED", "IMPORTANT")
        ]

        if archive and "INBOX" not in remove_ids:
            remove_ids.append("INBOX")
        if mark_read and "UNREAD" not in remove_ids:
            remove_ids.append("UNREAD")

        body: dict[str, Any] = {"ids": msg_ids}
        if add_ids:
            body["addLabelIds"] = add_ids
        if remove_ids:
            body["removeLabelIds"] = remove_ids

        _gmail_request("POST", "messages/batchModify", body=body)
        total_modified += len(msg_ids)
        entry_detail: dict[str, Any] = {
            "action_index": idx,
            "modified_count": len(msg_ids),
            "added_labels": add_names,
            "removed_labels": remove_names,
            "archived": archive,
            "marked_read": mark_read,
        }
        if unsub_results:
            entry_detail["unsubscribe_results"] = unsub_results
        results.append(entry_detail)

    return {
        "total_messages_modified": total_modified,
        "batches_executed": len(results),
        "details": results,
    }


def _join_addrs(val: Any) -> str:
    """Normalise a string or list of addresses into a comma-separated header value."""
    if not val:
        return ""
    if isinstance(val, list):
        return ", ".join(str(v).strip() for v in val if str(v).strip())
    return str(val).strip()


def _build_raw_message(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
    in_reply_to: str = "",
    references: str = "",
) -> str:
    """Build an RFC 2822 message and return it Base64URL-encoded for the Gmail API."""
    msg = EmailMessage()
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    msg.set_content(body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


def _self_addresses() -> set[str]:
    """Return the user's own addresses (primary, send-as aliases, GMAIL_SELF_ADDRESSES env)."""
    addrs: set[str] = set()
    try:
        profile = _gmail_request("GET", "profile")
        if profile.get("emailAddress"):
            addrs.add(profile["emailAddress"].lower())
    except Exception as exc:  # pragma: no cover - network dependent
        log_err(f"Could not read profile for self addresses: {exc}")
    try:
        send_as = _gmail_request("GET", "settings/sendAs")
        for entry in send_as.get("sendAs", []):
            if entry.get("sendAsEmail"):
                addrs.add(entry["sendAsEmail"].lower())
    except Exception as exc:  # pragma: no cover - scope/network dependent
        log_err(f"Could not list send-as aliases: {exc}")
    for extra in os.environ.get("GMAIL_SELF_ADDRESSES", "").split(","):
        if extra.strip():
            addrs.add(extra.strip().lower())
    return addrs


def _resolve_reply_context(message_id: str, reply_all: bool = True) -> dict[str, Any]:
    """
    Derive recipients, subject and threading headers for a reply from the real
    headers of `message_id`, so nothing has to be typed or guessed by hand.
    """
    msg = _gmail_request(
        "GET",
        f"messages/{message_id}",
        params={
            "format": "metadata",
            "metadataHeaders": ["From", "To", "Cc", "Reply-To", "Subject", "Message-ID", "References"],
        },
    )
    headers = {
        h["name"].lower(): h["value"]
        for h in msg.get("payload", {}).get("headers", [])
        if "name" in h and "value" in h
    }
    me_exact = _self_addresses()
    me_domains = {
        d.strip().lower().lstrip("@")
        for d in os.environ.get("GMAIL_SELF_DOMAINS", "").split(",")
        if d.strip()
    }

    class _Me:
        def __contains__(self, addr: object) -> bool:
            a = str(addr).lower()
            return a in me_exact or a.rsplit("@", 1)[-1] in me_domains

    me = _Me()

    def fmt(name: str, addr: str) -> str:
        return email.utils.formataddr((name, addr)) if name else addr

    primary = email.utils.getaddresses([headers.get("reply-to") or headers.get("from", "")])
    to_list: list[str] = []
    seen: set[str] = set()
    for name, addr in primary:
        if addr and addr.lower() not in me and addr.lower() not in seen:
            to_list.append(fmt(name, addr))
            seen.add(addr.lower())

    cc_list: list[str] = []
    if reply_all:
        others = email.utils.getaddresses([headers.get("to", ""), headers.get("cc", "")])
        for name, addr in others:
            if addr and addr.lower() not in me and addr.lower() not in seen:
                cc_list.append(fmt(name, addr))
                seen.add(addr.lower())

    # If the parent was sent by the user, reply to the original recipients instead.
    if not to_list and cc_list:
        to_list, cc_list = cc_list[:1], cc_list[1:]
    if not to_list:
        raise ValueError(f"Could not determine any recipient for a reply to message {message_id}.")

    subject = headers.get("subject", "").strip()
    if not re.match(r"^\s*re\s*:", subject, flags=re.IGNORECASE):
        subject = f"Re: {subject}" if subject else "Re:"

    parent_mid = headers.get("message-id", "").strip()
    references = " ".join(x for x in [headers.get("references", "").strip(), parent_mid] if x)

    return {
        "thread_id": msg.get("threadId"),
        "to": ", ".join(to_list),
        "cc": ", ".join(cc_list),
        "subject": subject,
        "in_reply_to": parent_mid,
        "references": references,
    }


def tool_send_message(args: dict[str, Any]) -> dict[str, Any]:
    """
    Send a NEW email (or a message into a known thread) via the Gmail API.
    To reply to an existing message prefer `gmail_reply`, which derives the
    recipients and threading headers from the real parent message.
    Required args: to, subject, body. Optional: cc, bcc, thread_id.
    """
    to_str = _join_addrs(args.get("to"))
    if not to_str:
        raise ValueError("'to' recipient is required.")
    subject = str(args.get("subject", "")).strip()
    if not subject:
        raise ValueError("'subject' is required.")
    body = args.get("body", "")
    if not body:
        raise ValueError("'body' content is required.")
    if args.get("in_reply_to") or args.get("references"):
        raise ValueError(
            "Threading headers are not accepted here. Use `gmail_reply` with the parent "
            "message_id so In-Reply-To/References come from the real message."
        )
    cc_str = _join_addrs(args.get("cc"))
    bcc_str = _join_addrs(args.get("bcc"))
    thread_id = args.get("thread_id") or args.get("threadId")

    payload: dict[str, Any] = {
        "raw": _build_raw_message(to_str, subject, body, cc=cc_str, bcc=bcc_str)
    }
    if thread_id:
        payload["threadId"] = str(thread_id).strip()

    resp = _gmail_request("POST", "messages/send", body=payload)
    return {
        "status": "sent",
        "id": resp.get("id"),
        "threadId": resp.get("threadId"),
        "labelIds": resp.get("labelIds", []),
        "to": to_str,
        "cc": cc_str or None,
        "subject": subject,
    }


def tool_reply(args: dict[str, Any]) -> dict[str, Any]:
    """
    Reply to an existing message. Recipients (Reply All by default, minus the
    user's own addresses), subject and In-Reply-To/References are derived from
    the parent message's real headers.
    mode: "preview" (no change), "draft" (default; creates a Gmail draft), "send".
    """
    message_id = args.get("message_id")
    if not message_id:
        raise ValueError("'message_id' of the message being replied to is required.")
    body = args.get("body", "")
    if not body:
        raise ValueError("'body' content is required.")
    mode = str(args.get("mode", "draft")).lower()
    if mode not in ("preview", "draft", "send"):
        raise ValueError("'mode' must be one of: preview, draft, send.")

    ctx = _resolve_reply_context(str(message_id), reply_all=bool(args.get("reply_all", True)))
    extra_cc = _join_addrs(args.get("extra_cc"))
    if extra_cc:
        ctx["cc"] = ", ".join(x for x in [ctx["cc"], extra_cc] if x)
    exclude = {a.strip().lower() for a in (args.get("exclude") or []) if a.strip()}
    if exclude:
        def _filter(header: str) -> str:
            kept = [
                email.utils.formataddr((n, a)) if n else a
                for n, a in email.utils.getaddresses([header])
                if a and a.lower() not in exclude
            ]
            return ", ".join(kept)
        ctx["to"], ctx["cc"] = _filter(ctx["to"]), _filter(ctx["cc"])
        if not ctx["to"]:
            raise ValueError("Excluding those addresses leaves no 'To' recipient.")

    result: dict[str, Any] = {"mode": mode, "replying_to_message_id": message_id, **ctx, "body": body}
    if mode == "preview":
        result["status"] = "preview_only"
        return result

    raw = _build_raw_message(
        ctx["to"], ctx["subject"], body,
        cc=ctx["cc"], in_reply_to=ctx["in_reply_to"], references=ctx["references"],
    )
    message_payload = {"raw": raw, "threadId": ctx["thread_id"]}
    if mode == "draft":
        resp = _gmail_request("POST", "drafts", body={"message": message_payload})
        result.update({"status": "draft_created", "draft_id": resp.get("id")})
    else:
        resp = _gmail_request("POST", "messages/send", body=message_payload)
        result.update({"status": "sent", "id": resp.get("id")})
    return result


def tool_create_draft(args: dict[str, Any]) -> dict[str, Any]:
    """Create a Gmail draft for a NEW message (use `gmail_reply` for replies)."""
    to_str = _join_addrs(args.get("to"))
    subject = str(args.get("subject", "")).strip()
    body = args.get("body", "")
    if not to_str or not subject or not body:
        raise ValueError("'to', 'subject' and 'body' are required.")
    raw = _build_raw_message(
        to_str, subject, body, cc=_join_addrs(args.get("cc")), bcc=_join_addrs(args.get("bcc"))
    )
    resp = _gmail_request("POST", "drafts", body={"message": {"raw": raw}})
    return {"status": "draft_created", "draft_id": resp.get("id"), "to": to_str, "subject": subject}


def tool_send_draft(args: dict[str, Any]) -> dict[str, Any]:
    """Send an existing Gmail draft as-is (including any edits the user made in Gmail)."""
    draft_id = args.get("draft_id")
    if not draft_id:
        raise ValueError("'draft_id' is required.")
    resp = _gmail_request("POST", "drafts/send", body={"id": str(draft_id)})
    return {
        "status": "sent",
        "id": resp.get("id"),
        "threadId": resp.get("threadId"),
        "labelIds": resp.get("labelIds", []),
    }


# ---------------------------------------------------------------------------
# MCP Tool Registry & Stdio JSON-RPC 2.0 Loop
# ---------------------------------------------------------------------------

TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "name": "gmail_auth_status",
        "description": (
            "Check whether Gmail OAuth credentials and token files are configured "
            "and return the connected Gmail profile."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "gmail_authenticate",
        "description": (
            "Launch the local Google OAuth 2.0 browser sign-in flow and save the session token."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "gmail_list_labels",
        "description": "List all system and user Gmail labels in the account.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "gmail_ensure_labels",
        "description": (
            "Ensure standard inbox triage labels exist in Gmail, "
            "creating any missing labels automatically."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "label_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of label names to ensure exist (defaults to "
                        "Triage/Needs Reply, Triage/FYI, Triage/Receipts, Triage/Newsletters)."
                    ),
                }
            },
        },
    },
    {
        "name": "gmail_fetch_inbox",
        "description": (
            "Fetch a compact list of Gmail messages matching a search query "
            "(headers, snippet, labels, unread status) for inbox triage."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Gmail search query (default: 'label:INBOX'). "
                        "Examples: 'label:INBOX is:unread', 'label:INBOX newer_than:7d'."
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of messages to fetch (1-500, default: 500).",
                },
            },
        },
    },
    {
        "name": "gmail_get_message",
        "description": (
            "Fetch the full plain-text body and metadata of a specific Gmail message by ID."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "The Gmail message ID to inspect.",
                },
                "max_body_chars": {
                    "type": "integer",
                    "description": "Maximum number of body characters to return (default: 4000).",
                },
            },
            "required": ["message_id"],
        },
    },
    {
        "name": "gmail_batch_triage",
        "description": (
            "Execute confirmed inbox sorting actions in batch "
            "(add/remove labels, mark as read, or archive out of INBOX). "
            "Never deletes or trashes emails."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "actions": {
                    "type": "array",
                    "description": "List of batch triage operations to perform.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "message_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of Gmail message IDs for this group.",
                            },
                            "add_labels": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "Label names to apply (created automatically if missing)."
                                ),
                            },
                            "remove_labels": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Label names to remove.",
                            },
                            "archive": {
                                "type": "boolean",
                                "description": (
                                    "If true, removes the INBOX label so the message is archived."
                                ),
                            },
                            "mark_read": {
                                "type": "boolean",
                                "description": "If true, removes the UNREAD label.",
                            },
                        },
                        "required": ["message_ids"],
                    },
                }
            },
            "required": ["actions"],
        },
    },
    {
        "name": "gmail_unsubscribe",
        "description": (
            "Unsubscribe from one or more mailing lists or promotional senders "
            "using RFC 8058 One-Click List-Unsubscribe POST or the message's unsubscribe link."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "A single Gmail message ID to unsubscribe from.",
                },
                "message_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of Gmail message IDs to unsubscribe from in batch.",
                },
            },
        },
    },
    {
        "name": "gmail_send_message",
        "description": (
            "Send a NEW email via the Gmail API. For replies use `gmail_reply` instead "
            "(threading headers are rejected here). Supports to, cc, bcc, subject, body, thread_id."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {
                    "description": "Recipient email address or list of addresses.",
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                },
                "cc": {
                    "description": "Optional CC recipient email address or list of addresses.",
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                },
                "bcc": {
                    "description": "Optional BCC recipient email address or list of addresses.",
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                },
                "subject": {
                    "type": "string",
                    "description": "Subject of the email.",
                },
                "body": {
                    "type": "string",
                    "description": "Plain text body content of the email.",
                },
                "thread_id": {
                    "type": "string",
                    "description": "Optional Gmail thread ID to file the message under.",
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "gmail_reply",
        "description": (
            "Reply to an existing message by ID. Recipients (Reply All by default, excluding "
            "the user's own addresses), 'Re:' subject and In-Reply-To/References headers are "
            "derived from the real parent message. mode: 'preview' (no change), 'draft' "
            "(default, creates a Gmail draft) or 'send'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "Gmail message ID being replied to (normally the latest in the thread).",
                },
                "body": {"type": "string", "description": "Plain text reply body."},
                "mode": {
                    "type": "string",
                    "enum": ["preview", "draft", "send"],
                    "description": "preview = resolve recipients only; draft = create Gmail draft (default); send = send now.",
                },
                "reply_all": {
                    "type": "boolean",
                    "description": "Include all original To/Cc recipients (default: true).",
                },
                "extra_cc": {
                    "description": "Optional additional CC addresses.",
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                },
                "exclude": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional addresses to drop from the derived recipients.",
                },
            },
            "required": ["message_id", "body"],
        },
    },
    {
        "name": "gmail_create_draft",
        "description": "Create a Gmail draft for a NEW message (use `gmail_reply` with mode='draft' for replies).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {
                    "description": "Recipient address or list of addresses.",
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                },
                "cc": {
                    "description": "Optional CC addresses.",
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                },
                "bcc": {
                    "description": "Optional BCC addresses.",
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                },
                "subject": {"type": "string", "description": "Subject line."},
                "body": {"type": "string", "description": "Plain text body."},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "gmail_send_draft",
        "description": "Send an existing Gmail draft by draft ID, including any edits the user made in Gmail.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string", "description": "Draft ID returned by gmail_reply/gmail_create_draft."},
            },
            "required": ["draft_id"],
        },
    },
]

TOOL_HANDLERS = {
    "gmail_auth_status": tool_auth_status,
    "gmail_authenticate": tool_authenticate,
    "gmail_list_labels": tool_list_labels,
    "gmail_ensure_labels": tool_ensure_labels,
    "gmail_fetch_inbox": tool_fetch_inbox,
    "gmail_get_message": tool_get_message,
    "gmail_batch_triage": tool_batch_triage,
    "gmail_unsubscribe": tool_unsubscribe,
    "gmail_send_message": tool_send_message,
    "gmail_reply": tool_reply,
    "gmail_create_draft": tool_create_draft,
    "gmail_send_draft": tool_send_draft,
}


def handle_rpc_request(msg: dict[str, Any]) -> dict[str, Any] | None:
    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params") or {}

    if req_id is None:
        return None

    if method == "initialize":
        client_version = params.get("protocolVersion", "2024-11-05")
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": client_version,
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "email-mcp",
                    "version": "1.3.0",
                },
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS_SCHEMA},
        }

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments") or {}
        handler = TOOL_HANDLERS.get(tool_name)
        if not handler:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Unknown tool: {tool_name}",
                },
            }
        try:
            output = handler(tool_args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(output, indent=2, ensure_ascii=False),
                        }
                    ],
                    "isError": False,
                },
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"error": str(exc)}, indent=2),
                        }
                    ],
                    "isError": True,
                },
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def serve_stdio() -> None:
    """Run the MCP stdio JSON-RPC loop."""
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            log_err(f"Ignored invalid JSON line: {exc}")
            continue

        response = handle_rpc_request(msg)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="Email (Gmail triage) MCP Server")
    _ = parser.add_argument(
        "--auth",
        action="store_true",
        help="Run interactive browser OAuth 2.0 flow to generate token and exit.",
    )
    _ = parser.add_argument(
        "--status",
        action="store_true",
        help="Check OAuth status and print connected Gmail profile.",
    )
    _ = parser.add_argument(
        "--unsubscribe",
        nargs="+",
        metavar="MESSAGE_ID",
        help="Unsubscribe from the mailing list(s) of the specified Gmail message ID(s).",
    )
    args = parser.parse_args()

    if args.auth:
        res = tool_authenticate({})
        print(json.dumps(res, indent=2))
        return

    if args.status:
        res = tool_auth_status({})
        print(json.dumps(res, indent=2))
        return

    if args.unsubscribe:
        res = tool_unsubscribe({"message_ids": args.unsubscribe})
        print(json.dumps(res, indent=2))
        return

    serve_stdio()


if __name__ == "__main__":
    main()
