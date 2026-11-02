# Algorithmic Breakthrough Evaluation Rubric

This rubric defines the criteria for triaging candidate papers into **Tier 1 (Top 1% Algorithmic Breakthroughs)**, **Tier 2 (Solid Applied & Systems Contributions)**, and **Tier 3 (Incremental Noise / Filtered)**.

---

## Technical Scope

The `triage-papers` skill evaluates papers within three primary domains:

1. **LLM Post-Training**: Alignment algorithms, reasoning distillation, test-time compute scaling, self-play, process/outcome reward modelling (PRM/ORM), credit assignment, and loss formulations.
2. **Reinforcement Learning (RL)**: Policy gradients, actor-critic stabilisation, off-policy correction, sample efficiency, reward hacking mitigation, value function estimation, and exploration strategies.
3. **Inference Optimisation**: Speculative decoding/drafting, KV cache compression/retention, memory hierarchy IO reformulations, non-autoregressive generation, linear/sub-quadratic attention, kernel optimisations, and low-bit quantisation.

---

## The Three Tiers

### Tier 1: Top 1% Algorithmic Breakthroughs (Must-Read)

To qualify as Tier 1, a paper must satisfy at least **one** of the following criteria:

*   **Algorithmic / Mathematical Reformulation**: Introduces a fundamentally new formulation that solves a known systemic barrier.
    *   *Exemplar*: DeepSeek's *GRPO* (Group Relative Policy Optimisation) — eliminates the memory-heavy critic model in RLHF by estimating advantages directly from group score normalisation.
    *   *Exemplar*: *DPO* (Direct Preference Optimisation, Rafailov et al.) — analytically reparameterises the reward model directly into the policy loss, removing the need for an external reward network.
    *   *Exemplar*: *FlashAttention* (Dao et al.) — re-architects the GPU SRAM memory hierarchy and tile computation to reduce memory access IO complexity from quadratic to linear with respect to sequence length.
*   **Theoretical Resolution of Instability / Mode Collapse**: Identifies a fundamental mathematical failure mode in current training (e.g. reward overoptimisation, off-policy gradient drift, policy collapse, length bias) and provides an analytically grounded correction that scales across model sizes.
*   **Order-of-Magnitude Scaling or Efficiency Shift**: Redefines the asymptotic complexity or memory/compute boundary without sacrificing generation fidelity or stability.

### Tier 2: Solid Applied & Systems Contributions (High-Value Practical)

Valuable engineering, empirical scaling, or systems implementations that improve practical throughput, alignment quality, or serving efficiency without introducing a new mathematical paradigm:

*   **Clever Systems & Runtime Techniques**: Innovative KV cache paging, chunked prefill schedules, multi-token prediction heads, or hardware-aware kernel architectures.
*   **Empirical / Recipe Discoveries**: Thorough, large-scale studies isolating what actually drives post-training gains (e.g. data curation recipes, reward model ensemble weighting, curriculum design).
*   **Quantisation & Compression Innovations**: Novel scale/zero-point distribution handling (e.g. FP4/FP8 mixed-precision schemes, activation outlier preservation) that retain >99% perplexity.

### Tier 3: Incremental Noise (Filtered / Relegated)

Papers that should be screened out:

*   **Superficial Benchmark Chasing**: Applying vanilla DPO/PPO to a newly created niche synthetic dataset and claiming SOTA by narrow margins.
*   **Heuristic Hyperparameter Twiddling**: Introducing multi-term arbitrary loss multipliers without theoretical grounding or validation on external models.
*   **Re-packaged Prompt Engineering / Agent Wrappers**: Labelled as "post-training" but merely performing multi-agent debate or chain-of-thought prompting without model parameter updates.
*   **Weak Baselines**: Comparing a modified algorithm against un-tuned or strawman baselines.

---

## Strict Verification & Anti-Hallucination Protocol

> [!IMPORTANT]
> **No Abstract Extrapolation**: An abstract describes intent and marketing claims, not verified mathematical proof. 
> Before categorising any paper as a **Tier 1 Breakthrough**:
> 1. You **must** verify the core method by inspecting the actual paper text (via web search, arXiv HTML, or reading excerpts).
> 2. You **must not** invent mathematical equations, parameter notations, or empirical percentage gains that are not explicitly documented in the retrieved source.
> 3. State clearly what is empirically established versus what remains an author conjecture.
