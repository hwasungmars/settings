# Personal Assistant & Research Plugin (`assistant`)

Bundles personal-assistant workflows spanning the `email` plugin (Gmail MCP server), `calendar` plugin (`gcalendar` CLI), and the frontier AI `research` skill for arXiv/Hugging Face paper curation.

```text
assistant/
├── plugin.json
└── skills/
    ├── assistant/                           # Briefing, weekly review, scheduling, invitations, deadlines
    │   ├── SKILL.md
    │   ├── scripts/find_slots.py            # Deterministic calendar slot calculator
    │   └── references/calendar-preferences.md
    └── research/                            # Frontier AI paper triage (LLM post-training, RL, inference)
        ├── SKILL.md
        ├── scripts/fetch_papers.py          # Dual-source arXiv & Hugging Face paper fetcher
        └── references/
            ├── breakthrough_rubric.md       # 3-tier mathematical & algorithmic evaluation standard
            └── preferences.md               # User technical domains & focus areas
```

Requires both the `email` and `calendar` plugins to be enabled.
