from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVER_PATH = PROJECT_ROOT / "mcp_server" / "gmail_mcp_server.py"

_SPEC = importlib.util.spec_from_file_location("gmail_mcp_server", SERVER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
srv = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(srv)


class TestGmailMcpServer(unittest.TestCase):
    def test_stdio_initialize_and_tools_list(self) -> None:
        requests = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            },
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
            },
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "gmail_auth_status", "arguments": {}},
            },
        ]
        stdin_payload = "\n".join(json.dumps(r) for r in requests) + "\n"
        proc = subprocess.run(
            [sys.executable, str(SERVER_PATH)],
            input=stdin_payload,
            text=True,
            capture_output=True,
            timeout=10,
            check=True,
        )
        lines = [json.loads(line) for line in proc.stdout.strip().splitlines()]
        self.assertEqual(len(lines), 3)

        # Verify initialize response
        self.assertEqual(lines[0]["id"], 1)
        self.assertEqual(lines[0]["result"]["serverInfo"]["name"], "email-mcp")

        # Verify tools/list response
        tools = lines[1]["result"]["tools"]
        tool_names = {t["name"] for t in tools}
        self.assertIn("gmail_auth_status", tool_names)
        self.assertIn("gmail_fetch_inbox", tool_names)
        self.assertIn("gmail_batch_triage", tool_names)
        for name in ("gmail_send_message", "gmail_reply", "gmail_create_draft", "gmail_send_draft"):
            self.assertIn(name, tool_names)

        # Verify tools/call gmail_auth_status response
        self.assertEqual(lines[2]["id"], 3)
        self.assertFalse(lines[2]["result"]["isError"])
        status_payload = json.loads(lines[2]["result"]["content"][0]["text"])
        self.assertIn("authenticated", status_payload)

    def test_batch_triage_blocks_trash_and_spam(self) -> None:
        with patch.object(
            srv,
            "_get_label_maps",
            return_value=({"triage/fyi": "Label_1"}, {"Label_1": "Triage/FYI"}, []),
        ):
            with self.assertRaises(ValueError) as ctx:
                srv.tool_batch_triage(
                    {
                        "actions": [
                            {
                                "message_ids": ["msg1"],
                                "add_labels": ["TRASH"],
                            }
                        ]
                    }
                )
            self.assertIn("Safety guardrail", str(ctx.exception))


    def test_send_message_payload(self) -> None:
        captured: list[tuple[str, str, Any]] = []

        def fake(method: str, endpoint: str, params: Any = None, body: Any = None) -> dict[str, Any]:
            captured.append((method, endpoint, body))
            return {"id": "sent_123", "threadId": "thread_abc", "labelIds": ["SENT"]}

        with patch.object(srv, "_gmail_request", side_effect=fake):
            res = srv.tool_send_message(
                {
                    "to": ["alice@example.com", "bob@example.com"],
                    "cc": "charlie@example.com",
                    "subject": "Test Subject",
                    "body": "Hello World",
                    "thread_id": "thread_abc",
                }
            )

        self.assertEqual(res["status"], "sent")
        method, endpoint, body = captured[0]
        self.assertEqual((method, endpoint), ("POST", "messages/send"))
        self.assertEqual(body["threadId"], "thread_abc")
        parsed = _decode(body["raw"])
        self.assertEqual(parsed["Subject"], "Test Subject")
        self.assertIn("bob@example.com", parsed["To"])
        self.assertEqual(parsed["Cc"], "charlie@example.com")
        self.assertIsNone(parsed["In-Reply-To"])
        self.assertEqual(parsed.get_content().strip(), "Hello World")

    def test_send_message_rejects_hand_typed_threading_headers(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            srv.tool_send_message(
                {"to": "a@example.com", "subject": "s", "body": "b", "in_reply_to": "<made-up@x>"}
            )
        self.assertIn("gmail_reply", str(ctx.exception))

    def _fake_thread_api(self, captured: list) -> Any:
        parent_headers = [
            {"name": "From", "value": "Ed Morgan <ed@builder.example>"},
            {"name": "To", "value": "Me <me@hwasung.xyz>, Joe <joe@example.com>"},
            {"name": "Cc", "value": "Alice <alice@example.com>, ME@HWASUNG.XYZ"},
            {"name": "Subject", "value": "Electrical Shut Down"},
            {"name": "Message-ID", "value": "<parent-123@builder.example>"},
            {"name": "References", "value": "<root-1@builder.example>"},
        ]

        def fake(method: str, endpoint: str, params: Any = None, body: Any = None) -> dict[str, Any]:
            captured.append((method, endpoint, body))
            if endpoint == "messages/parent1":
                return {"threadId": "thread_xyz", "payload": {"headers": parent_headers}}
            if endpoint == "profile":
                return {"emailAddress": "hwasungmars@gmail.com"}
            if endpoint == "settings/sendAs":
                return {"sendAs": [{"sendAsEmail": "me@hwasung.xyz"}]}
            if endpoint == "drafts":
                return {"id": "draft_9"}
            if endpoint == "messages/send":
                return {"id": "sent_9", "threadId": "thread_xyz"}
            raise AssertionError(f"unexpected endpoint {endpoint}")

        return fake

    def test_reply_derives_recipients_and_real_threading_headers(self) -> None:
        captured: list = []
        with patch.object(srv, "_gmail_request", side_effect=self._fake_thread_api(captured)):
            res = srv.tool_reply({"message_id": "parent1", "body": "Thanks Ed", "mode": "send"})

        self.assertEqual(res["status"], "sent")
        self.assertEqual(res["thread_id"], "thread_xyz")
        self.assertEqual(res["subject"], "Re: Electrical Shut Down")
        self.assertIn("ed@builder.example", res["to"])
        self.assertIn("joe@example.com", res["cc"])
        self.assertIn("alice@example.com", res["cc"])
        self.assertNotIn("hwasung.xyz", (res["to"] + res["cc"]).lower())

        _, endpoint, body = captured[-1]
        self.assertEqual(endpoint, "messages/send")
        self.assertEqual(body["threadId"], "thread_xyz")
        parsed = _decode(body["raw"])
        self.assertEqual(parsed["In-Reply-To"], "<parent-123@builder.example>")
        self.assertEqual(parsed["References"], "<root-1@builder.example> <parent-123@builder.example>")

    def test_reply_defaults_to_draft_and_preview_makes_no_writes(self) -> None:
        captured: list = []
        with patch.object(srv, "_gmail_request", side_effect=self._fake_thread_api(captured)):
            preview = srv.tool_reply({"message_id": "parent1", "body": "x", "mode": "preview"})
            self.assertEqual(preview["status"], "preview_only")
            self.assertFalse(any(m == "POST" for m, _, _ in captured))

            draft = srv.tool_reply({"message_id": "parent1", "body": "x"})
        self.assertEqual(draft["status"], "draft_created")
        self.assertEqual(draft["draft_id"], "draft_9")
        self.assertEqual(captured[-1][1], "drafts")
        self.assertEqual(captured[-1][2]["message"]["threadId"], "thread_xyz")

    def test_reply_exclude_drops_recipients(self) -> None:
        captured: list = []
        with patch.object(srv, "_gmail_request", side_effect=self._fake_thread_api(captured)):
            res = srv.tool_reply(
                {"message_id": "parent1", "body": "x", "mode": "preview", "exclude": ["alice@example.com"]}
            )
        self.assertNotIn("alice@example.com", res["cc"])
        self.assertIn("joe@example.com", res["cc"])

    def test_reply_excludes_self_domain_aliases(self) -> None:
        captured: list = []
        with patch.dict("os.environ", {"GMAIL_SELF_DOMAINS": "builder.example"}):
            with patch.object(srv, "_gmail_request", side_effect=self._fake_thread_api(captured)):
                res = srv.tool_reply({"message_id": "parent1", "body": "x", "mode": "preview"})
        # Ed's domain is treated as "self", so the reply falls back to the other recipients.
        self.assertNotIn("builder.example", res["to"] + res["cc"])
        self.assertIn("joe@example.com", res["to"])

    def test_send_draft(self) -> None:
        with patch.object(srv, "_gmail_request", return_value={"id": "m1", "threadId": "t1"}) as m:
            res = srv.tool_send_draft({"draft_id": "draft_9"})
        m.assert_called_once_with("POST", "drafts/send", body={"id": "draft_9"})
        self.assertEqual(res["status"], "sent")


def _decode(raw: str) -> Any:
    import base64
    import email
    import email.policy

    return email.message_from_bytes(base64.urlsafe_b64decode(raw), policy=email.policy.default)


if __name__ == "__main__":
    unittest.main()
