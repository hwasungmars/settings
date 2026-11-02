# Personal Assistant Plugin (`assistant`)

Workflows that span the `email` plugin (Gmail MCP server) and the `calendar` plugin (`gcalendar` CLI from the
Agent Marketplace). Kept separate so the Marketplace calendar plugin stays unmodified and can update cleanly.

```text
assistant/
├── plugin.json
└── skills/
    └── assistant/
        ├── SKILL.md                         # Briefing, weekly review, scheduling, invitations, deadlines
        └── references/
            └── calendar-preferences.md      # Working hours, protected time, meeting defaults
```

Requires both the `email` and `calendar` plugins to be enabled.
