# Personal Assistant Plugin (`assistant`)

Orchestrator plugin providing executive personal-assistant workflows that bridge your three core capability plugins:
- `email` (Gmail MCP server)
- `calendar` (`gcalendar` CLI)
- `research` (arXiv & Hugging Face paper intelligence)

```text
assistant/
├── plugin.json
└── skills/
    └── assistant/                           # Briefing, weekly review, scheduling, invitations, deadlines
        ├── SKILL.md
        ├── scripts/find_slots.py            # Deterministic calendar slot calculator
        └── references/calendar-preferences.md
```

Requires the `email`, `calendar`, and `research` plugins to be enabled.
