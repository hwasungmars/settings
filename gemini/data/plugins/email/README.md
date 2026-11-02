# Email Plugin (`email`)

A self-contained Antigravity **Plugin** bundling the `email` skill, inbox triage rules, and the zero-dependency Python 3 `email` Model Context Protocol (MCP) server for sorting, categorising, labelling, replying to, sending and following up on emails from your Gmail inbox using Google Cloud OAuth 2.0.

## Plugin Layout

```text
email/
├── plugin.json                            # Plugin manifest
├── mcp_config.json                        # Registers the `email` MCP server
├── rules/
│   └── AGENTS.md                          # Always-on Gmail triage rules when plugin is enabled
├── skills/
│   └── email/
│       ├── SKILL.md                       # Classification checklist, triage & reply workflow
│       └── references/
│           ├── preferences.md             # User's standing keep/archive decisions & reply style
│           └── setup-oauth.md             # Step-by-step OAuth & MCP setup guide
├── mcp_server/
│   └── gmail_mcp_server.py                # Zero-dependency Python 3 MCP server
└── tests/
    └── test_mcp_server.py                 # Automated unit & protocol tests
```

## OAuth Files (`~/vaults/personal/! PRIVATE/`)

- **App Credentials**: `~/vaults/personal/! PRIVATE/gmail-credentials.json`
- **OAuth Session Token**: `~/vaults/personal/! PRIVATE/gmail-token.json`

OAuth files are kept **only** in the vault above — never inside this plugin directory.

## Tools

| Tool | Purpose |
| :--- | :--- |
| `gmail_auth_status`, `gmail_authenticate` | Check / perform OAuth sign-in |
| `gmail_list_labels`, `gmail_ensure_labels` | Inspect / create triage labels |
| `gmail_fetch_inbox`, `gmail_get_message` | Read inbox summaries and full messages (incl. `Message-ID` / `References`) |
| `gmail_batch_triage`, `gmail_unsubscribe` | Label, mark read, archive, unsubscribe (never deletes) |
| `gmail_reply` | Reply by message ID; recipients and threading headers derived from the real parent (`preview` / `draft` / `send`) |
| `gmail_create_draft`, `gmail_send_draft`, `gmail_send_message` | Draft and send new mail; send drafts as edited in Gmail |

Environment: `GMAIL_SELF_ADDRESSES` and `GMAIL_SELF_DOMAINS` (in `mcp_config.json`) list the user's own
addresses/domains so they are never added as reply recipients.

After changing `mcp_server/gmail_mcp_server.py`, **reload the plugin** so Antigravity restarts the server.

Run tests: `python3 tests/test_mcp_server.py`
