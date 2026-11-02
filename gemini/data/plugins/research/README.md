# Research Plugin (`research`)

A self-contained Antigravity **Plugin** for tracking and evaluating frontier AI algorithmic breakthroughs in LLM post-training, reinforcement learning (RL), and inference optimisation.

## Plugin Layout

```text
research/
├── plugin.json                            # Plugin manifest
├── README.md                              # User-facing documentation
└── skills/
    └── research/
        ├── SKILL.md                       # Dual-source triage & 3-tier evaluation rubric
        ├── scripts/
        │   └── fetch_papers.py            # Dual-source arXiv API + Hugging Face Daily Papers fetcher
        └── references/
            ├── breakthrough_rubric.md     # 3-tier mathematical & algorithmic evaluation standard
            └── preferences.md             # User technical domains & priority focus areas
```

## Features

- **Dual-Source Retrieval**: Queries Hugging Face Daily Papers (community-curated) and arXiv REST API (targeted primary search).
- **Rigorous 3-Tier Rubric**: Separates genuine mathematical and algorithmic contributions from prompt wrappers, benchmark churn, and incremental noise.
- **Verification Rule**: Verifies claims and equations directly against the text before declaring Tier 1 status.
