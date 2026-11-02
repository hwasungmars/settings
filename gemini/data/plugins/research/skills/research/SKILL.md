---
name: research
description: >-
  Fetch, triage, filter, and analyse recent arXiv papers in LLM post-training, reinforcement learning (RL),
  and inference optimisation. Distinguishes top 1% algorithmic breakthroughs from incremental noise,
  evaluating mathematical innovations, stability proofs, and efficiency speedups.
  Use when the user asks to research or triage recent papers, check arXiv or Hugging Face Daily Papers for breakthroughs,
  or perform a technical literature review.
---

# Research & Paper Intelligence Skill (`research`)

A specialised skill to filter the firehose of arXiv papers down to true **top 1% algorithmic breakthroughs** in LLM post-training, reinforcement learning, and inference optimisation.

## Guiding Principle: High Signal, Rigorous Verification

Most AI newsletters and social feeds suffer from either extreme noise or severe lag. This skill applies a dual-source retrieval strategy (Hugging Face Daily Papers + targeted arXiv API queries) and a rigorous evaluation rubric ([`breakthrough_rubric.md`](./references/breakthrough_rubric.md)) to separate genuine mathematical and algorithmic contributions from prompt wrappers and benchmark churn.

---

## Workflow

### 1. Check Standing Preferences

Before triaging, review the user's standing preferences in [`preferences.md`](./references/preferences.md) to ensure alignment on active domains and priority filters.

### 2. Fetch Candidate Papers

Execute the dual-source fetch script over the desired review window (default: past 7 days):

```bash
# Standard 7-day review:
python3 ~/.gemini/config/plugins/research/skills/research/scripts/fetch_papers.py --days 7 --min-upvotes 0 --format json

# Or backtest a specific historical date window:
python3 ~/.gemini/config/plugins/research/skills/research/scripts/fetch_papers.py --start-date 2026-09-17 --end-date 2026-09-24 --format json

# Or evaluate a specific arXiv ID directly:
python3 ~/.gemini/config/plugins/research/skills/research/scripts/fetch_papers.py --id 2609.20807
```

**Supported Options**:
- `--days <N>`: Time window relative to end date (default: 7).
- `--start-date <YYYY-MM-DD>` & `--end-date <YYYY-MM-DD>`: Explicit date range.
- `--min-upvotes <N>`: Minimum Hugging Face community upvotes (default: 0).
- `--domain <all|post_training|reinforcement_learning|inference_optimisation>`: Restrict to a single domain.
- `--format <markdown|json|summary>`: Output formatting (default: markdown).
- `--limit <N>`: Maximum candidate count to evaluate (default: 30).

### 3. Screen Against the 3-Tier Rubric

Evaluate candidate papers against the criteria in [`breakthrough_rubric.md`](./references/breakthrough_rubric.md):

*   **Tier 1: Top 1% Algorithmic Breakthroughs**:
    *   Introduces a fundamentally new formulation or mathematical stabilisation solving a systemic failure mode.
    *   *Verification requirement*: Before confirming a Tier 1 rating, verify the core mathematics and findings via web search or paper inspection. **Do not hallucinate equations or empirical metrics from abstracts.**
*   **Tier 2: Solid Applied & Systems Contributions**:
    *   Valuable engineering implementations: KV cache management, speculative decoding draft heads, chunked prefill schedules, or low-bit quantisation kernels.
*   **Tier 3: Incremental Noise (Screened Out)**:
    *   Narrow benchmark optimisation, synthetic prompt mixtures, un-tuned baselines. Relegate or omit.

### 4. Present the Triage Briefing

Present a high-density, structured report:

1. **Executive Summary**: 1–2 sentences summarising candidate volume and overall paper velocity.
2. **Tier 1: Algorithmic Breakthroughs (Must-Read)**:
   - **Title & Links**: arXiv link, authors, date, community metrics.
   - **The Bottleneck**: The specific failure mode or limitation being solved.
   - **The Algorithmic Innovation**: The concrete mathematical modification or formulation.
   - **Empirical Validation**: Wall-clock gains, stability proofs, or scaling curves verified against the text.
   - **Why It Matters**: Practical implications for training or serving infrastructure.
3. **Tier 2: Notable Systems & Practical Contributions**:
   - Concise bullet points highlighting solid engineering and applied results.
4. **Noise Filtered**: Summary of how many incremental papers were screened out.
