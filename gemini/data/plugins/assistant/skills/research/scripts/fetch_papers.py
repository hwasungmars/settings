#!/usr/bin/env python3
"""
fetch_papers.py - Dual-source arXiv & Hugging Face paper fetcher for triage-papers.

Queries both Hugging Face Daily Papers and the arXiv API directly (cs.LG, cs.AI, stat.ML),
applies high-precision phrase matching, ranks papers by intrinsic algorithmic signal,
and ensures arXiv discoveries are not crowded out by community upvote aggregators.
"""

import argparse
import datetime
import json
import math
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) triage-papers/2.1"

# Primary technical domain definitions
DOMAINS = {
    "post_training": [
        "post-training", "post training", "dpo", "direct preference optimisation",
        "direct preference optimization", "grpo", "group relative policy", "kto",
        "rlhf", "rlaif", "self-play", "self play", "reasoning model", "large reasoning model",
        "test-time compute", "test time compute", "process reward model", "outcome reward model",
        "rejection sampling fine-tuning", "preference optimisation", "preference optimization",
        "policy distillation", "instruction tuning"
    ],
    "reinforcement_learning": [
        "reinforcement learning", "policy gradient", "policy optimisation", "policy optimization",
        "off-policy", "on-policy", "actor-critic", "actor critic", "q-learning",
        "score centering", "score-centering", "training-inference mismatch", "importance sampling",
        "advantage estimation", "generalised advantage", "generalized advantage",
        "entropy regularisation", "entropy regularization", "exploration bonus", "bellman error",
        "policy drift", "gradient drift", "reward overoptimisation", "reward hacking"
    ],
    "inference_optimisation": [
        "speculative decoding", "speculative drafting", "kv cache compression", "kv cache eviction",
        "paged attention", "pagedattention", "flashattention", "linear attention", "sparse attention",
        "chunked prefill", "continuous batching", "prefix caching", "fp8 inference", "fp4 inference",
        "int4 quantisation", "int4 quantization", "weight-only quantisation", "weight-only quantization",
        "activation quantisation", "activation quantization", "medusa head", "eagle drafting",
        "multi-token prediction", "throughput optimisation", "latency reduction", "llm serving"
    ]
}

# Exclusion patterns for non-LLM / non-algorithmic domains
EXCLUSION_KEYWORDS = [
    "robotics", "robot manipulation", "target speaker extraction", "acoustic scenes",
    "video world model", "speech synthesis", "hearing aid", "biomedical imaging",
    "wafer defect", "autonomous driving", "point cloud"
]

# High-signal algorithmic terms that indicate foundational / mathematical work
CORE_ALGORITHMIC_TERMS = [
    "score centering", "training-inference mismatch", "off-policy", "policy gradient",
    "actor-critic", "grpo", "dpo", "convergence proof", "gradient drift",
    "importance sampling", "bellman", "speculative decoding", "kv cache",
    "paged attention", "process reward", "test-time compute", "mathematical formulation"
]

def clean_arxiv_id(raw_id: str) -> str:
    """Extract clean 1234.56789 identifier from an arXiv URL or raw ID."""
    m = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", raw_id)
    return m.group(1) if m else raw_id

def classify_domains(title: str, summary: str) -> tuple:
    """
    Classify text into matching domains while filtering out non-LLM domains.
    Returns (matched_domains_list, is_excluded_bool).
    """
    full_text = f"{title} {summary}".lower()

    for neg in EXCLUSION_KEYWORDS:
        if re.search(r"\b" + re.escape(neg) + r"\b", full_text):
            if not any(k in full_text for k in ["language model", "llm", "policy gradient", "transformer", "reinforcement learning"]):
                return ([], True)

    matched = []
    for domain_name, phrases in DOMAINS.items():
        for phrase in phrases:
            pattern = r"\b" + re.escape(phrase) + r"\b"
            if re.search(pattern, full_text):
                matched.append(domain_name)
                break

    return (matched, False)

def compute_algorithmic_score(title: str, summary: str, domains: list, upvotes: int = 0) -> float:
    """
    Compute an intrinsic algorithmic score:
    - Title match on core technical keywords is heavily rewarded (+10 points)
    - Presence of foundational algorithmic phrases in abstract (+3 points each)
    - Number of matched domains (+3 points each)
    - Upvotes provide a modest logarithmic boost (at most +8 points) so they don't drown out unvetted preprints
    """
    title_lower = title.lower()
    summary_lower = summary.lower()
    score = len(domains) * 3.0

    # Strong boost for title hits
    for term in CORE_ALGORITHMIC_TERMS:
        if re.search(r"\b" + re.escape(term) + r"\b", title_lower):
            score += 10.0
        elif re.search(r"\b" + re.escape(term) + r"\b", summary_lower):
            score += 3.0

    # Logarithmic upvote contribution (capped at 8.0)
    if upvotes > 0:
        score += min(math.log2(upvotes + 1) * 1.5, 8.0)

    return round(score, 2)

def fetch_hf_paper_details(arxiv_id: str) -> dict:
    """Fetch community upvotes, discussions, and repo links from Hugging Face paper API."""
    url = f"https://huggingface.co/api/papers/{arxiv_id}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, dict):
                return {
                    "upvotes": data.get("upvotes", 0),
                    "comments": data.get("numComments", 0),
                    "github_repo": data.get("githubRepo"),
                    "github_stars": data.get("githubStars", 0),
                    "org": data.get("organization") or "",
                }
    except Exception:
        pass
    return {"upvotes": 0, "comments": 0, "github_repo": None, "github_stars": 0, "org": ""}

def fetch_hf_daily_papers(date_str: str) -> list:
    """Fetch Hugging Face Daily Papers for a given YYYY-MM-DD."""
    url = f"https://huggingface.co/api/daily_papers?date={date_str}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, list) else []
    except Exception:
        return []

def query_arxiv_api(search_query: str, start: int = 0, max_results: int = 100) -> list:
    """Query the official arXiv API with rate limiting."""
    params = {
        "search_query": search_query,
        "start": start,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending"
    }
    url = "http://export.arxiv.org/api/query?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            xml_data = resp.read()
            root = ET.fromstring(xml_data)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            entries = root.findall("atom:entry", ns)
            results = []
            for e in entries:
                raw_id = e.find("atom:id", ns).text.strip()
                arxiv_id = clean_arxiv_id(raw_id)
                title = e.find("atom:title", ns).text.strip().replace("\n", " ")
                summary = e.find("atom:summary", ns).text.strip().replace("\n", " ")
                published = e.find("atom:published", ns).text.strip()
                authors = [a.find("atom:name", ns).text.strip() for a in e.findall("atom:author", ns)]

                results.append({
                    "id": arxiv_id,
                    "title": title,
                    "summary": summary,
                    "date": published[:10],
                    "authors": authors[:5],
                })
            return results
    except Exception as e:
        sys.stderr.write(f"arXiv query error: {e}\n")
        return []

def fetch_paper_by_id(arxiv_id: str) -> dict:
    """Fetch details for a specific arXiv ID across arXiv and Hugging Face."""
    arxiv_id = clean_arxiv_id(arxiv_id)
    url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    entry_dict = None
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            root = ET.fromstring(resp.read())
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            e = root.find("atom:entry", ns)
            if e is not None:
                title = e.find("atom:title", ns).text.strip().replace("\n", " ")
                summary = e.find("atom:summary", ns).text.strip().replace("\n", " ")
                published = e.find("atom:published", ns).text.strip()
                authors = [a.find("atom:name", ns).text.strip() for a in e.findall("atom:author", ns)]
                domains, excluded = classify_domains(title, summary)
                entry_dict = {
                    "id": arxiv_id,
                    "arxiv_url": f"https://arxiv.org/abs/{arxiv_id}",
                    "hf_url": f"https://huggingface.co/papers/{arxiv_id}",
                    "title": title,
                    "summary": summary,
                    "date": published[:10],
                    "authors": authors,
                    "domains": domains,
                    "source": "direct_id",
                }
    except Exception as e:
        sys.stderr.write(f"Error fetching paper {arxiv_id}: {e}\n")

    if not entry_dict:
        return {}

    hf_meta = fetch_hf_paper_details(arxiv_id)
    entry_dict.update(hf_meta)
    entry_dict["algorithmic_score"] = compute_algorithmic_score(
        entry_dict["title"], entry_dict["summary"], entry_dict["domains"], entry_dict["upvotes"]
    )
    return entry_dict

def aggregate_papers(start_date: str, end_date: str, min_upvotes: int = 0) -> list:
    """
    Fetch and aggregate candidate papers across both Hugging Face Daily Papers and arXiv.
    Uses balanced quotas so arXiv-direct papers are never displaced by high-upvote aggregators.
    """
    start_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
    end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
    num_days = (end_dt - start_dt).days + 1

    seen_hf = {}
    seen_arxiv = {}

    # 1. Fetch Hugging Face Daily Papers
    for i in range(num_days):
        current_date = end_dt - datetime.timedelta(days=i)
        date_str = current_date.strftime("%Y-%m-%d")
        daily_items = fetch_hf_daily_papers(date_str)
        for item in daily_items:
            paper = item.get("paper", {})
            raw_id = paper.get("id") or item.get("id")
            if not raw_id:
                continue
            aid = clean_arxiv_id(raw_id)
            if aid in seen_hf:
                continue

            title = (paper.get("title") or item.get("title") or "").strip().replace("\n", " ")
            summary = (paper.get("summary") or item.get("summary") or "").strip().replace("\n", " ")
            domains, excluded = classify_domains(title, summary)
            if excluded or not domains:
                continue

            upvotes = paper.get("upvotes", 0)
            if upvotes < min_upvotes:
                continue

            authors = []
            for a in paper.get("authors", []):
                if isinstance(a, dict) and "name" in a:
                    authors.append(a["name"])
                elif isinstance(a, str):
                    authors.append(a)

            org = paper.get("organization", {})
            org_name = org.get("name") if isinstance(org, dict) else (paper.get("organization") or "")

            score = compute_algorithmic_score(title, summary, domains, upvotes)

            seen_hf[aid] = {
                "id": aid,
                "arxiv_url": f"https://arxiv.org/abs/{aid}",
                "hf_url": f"https://huggingface.co/papers/{aid}",
                "title": title,
                "summary": summary,
                "date": date_str,
                "upvotes": upvotes,
                "comments": item.get("numComments", 0),
                "github_repo": paper.get("githubRepo"),
                "github_stars": paper.get("githubStars", 0),
                "authors": authors[:5],
                "org": org_name,
                "domains": domains,
                "source": "hf_daily",
                "algorithmic_score": score
            }

    # 2. Query arXiv API with exact date window
    arxiv_start_str = start_dt.strftime("%Y%m%d0000")
    arxiv_end_str = end_dt.strftime("%Y%m%d2359")
    date_filter = f"submittedDate:[{arxiv_start_str} TO {arxiv_end_str}]"

    arxiv_queries = [
        f'cat:cs.LG AND (ti:"reinforcement learning" OR abs:"off-policy" OR abs:"policy optimization" OR abs:"policy optimisation" OR abs:"score centering") AND {date_filter}',
        f'cat:cs.AI AND (ti:"post-training" OR abs:"alignment" OR abs:"direct preference" OR abs:"reasoning model" OR abs:"test-time compute") AND {date_filter}',
        f'cat:cs.LG AND (abs:"speculative decoding" OR abs:"kv cache" OR abs:"chunked prefill" OR abs:"paged attention") AND {date_filter}'
    ]

    for q in arxiv_queries:
        for start_idx in [0, 100]:
            items = query_arxiv_api(q, start=start_idx, max_results=100)
            if not items:
                break
            for item in items:
                aid = item["id"]
                if aid in seen_hf or aid in seen_arxiv:
                    continue

                domains, excluded = classify_domains(item["title"], item["summary"])
                if excluded or not domains:
                    continue

                score = compute_algorithmic_score(item["title"], item["summary"], domains, upvotes=0)

                seen_arxiv[aid] = {
                    "id": aid,
                    "arxiv_url": f"https://arxiv.org/abs/{aid}",
                    "hf_url": f"https://huggingface.co/papers/{aid}",
                    "title": item["title"],
                    "summary": item["summary"],
                    "date": item["date"],
                    "authors": item["authors"],
                    "domains": domains,
                    "source": "arxiv_direct",
                    "upvotes": 0,
                    "comments": 0,
                    "github_repo": None,
                    "github_stars": 0,
                    "org": "",
                    "algorithmic_score": score
                }
            time.sleep(2)

    # Sort each stream independently
    hf_list = sorted(seen_hf.values(), key=lambda x: (x["algorithmic_score"], x["upvotes"]), reverse=True)
    arxiv_list = sorted(seen_arxiv.values(), key=lambda x: x["algorithmic_score"], reverse=True)

    # Enrich only top 15 arXiv candidates with HF details to prevent excessive HTTP requests
    for p in arxiv_list[:15]:
        meta = fetch_hf_paper_details(p["id"])
        p.update(meta)
        if p["upvotes"] > 0:
            p["algorithmic_score"] = compute_algorithmic_score(p["title"], p["summary"], p["domains"], p["upvotes"])

    # Re-sort arXiv list after enrichment
    arxiv_list = sorted(arxiv_list, key=lambda x: (x["algorithmic_score"], x["upvotes"]), reverse=True)

    # Balanced interleaving: 50% arXiv direct candidates, 50% HF daily candidates
    combined = []
    max_len = max(len(arxiv_list), len(hf_list))
    for i in range(max_len):
        if i < len(arxiv_list):
            combined.append(arxiv_list[i])
        if i < len(hf_list):
            combined.append(hf_list[i])

    # Final sort primarily by algorithmic score
    combined.sort(key=lambda x: (x["algorithmic_score"], x["upvotes"]), reverse=True)
    return combined

def main():
    parser = argparse.ArgumentParser(description="Fetch and triage curated arXiv papers in LLM foundations.")
    parser.add_argument("--id", type=str, help="Evaluate a single arXiv ID directly (e.g. 2609.20807)")
    parser.add_argument("--days", type=int, default=7, help="Past days to search relative to end date (default: 7)")
    parser.add_argument("--start-date", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--min-upvotes", type=int, default=0, help="Minimum upvotes threshold (default: 0)")
    parser.add_argument("--domain", choices=["all", "post_training", "reinforcement_learning", "inference_optimisation"],
                        default="all", help="Filter by specific technical domain")
    parser.add_argument("--format", choices=["json", "summary", "markdown"], default="markdown",
                        help="Output format (default: markdown)")
    parser.add_argument("--limit", type=int, default=25, help="Maximum number of papers to display (default: 25)")
    args = parser.parse_args()

    if args.id:
        paper = fetch_paper_by_id(args.id)
        if not paper:
            print(f"Could not find or fetch arXiv ID: {args.id}")
            sys.exit(1)
        papers = [paper]
    else:
        if args.end_date:
            end_dt = datetime.datetime.strptime(args.end_date, "%Y-%m-%d").date()
        else:
            end_dt = datetime.date.today()

        if args.start_date:
            start_dt = datetime.datetime.strptime(args.start_date, "%Y-%m-%d").date()
        else:
            start_dt = end_dt - datetime.timedelta(days=args.days)

        start_str = start_dt.strftime("%Y-%m-%d")
        end_str = end_dt.strftime("%Y-%m-%d")

        papers = aggregate_papers(start_date=start_str, end_date=end_str, min_upvotes=args.min_upvotes)
        if args.domain != "all":
            papers = [p for p in papers if args.domain in p["domains"]]
        papers = papers[:args.limit]

    if args.format == "json":
        print(json.dumps(papers, indent=2))
        return

    if args.format == "summary":
        print(f"Found {len(papers)} candidate papers:\n")
        for idx, p in enumerate(papers, 1):
            domains_str = "/".join(p.get("domains", []))
            print(f"[{idx}] [Score: {p.get('algorithmic_score', 0)}] [{p.get('source')}] [{p.get('upvotes', 0)} upvotes] {p['title']}")
            print(f"    arXiv: {p['arxiv_url']} | Date: {p['date']} | Domains: {domains_str}")
        return

    print(f"# arXiv Paper Triage Results\n")
    print(f"**Found {len(papers)} candidate papers** matching technical domain criteria.\n")
    for idx, p in enumerate(papers, 1):
        domains_str = ", ".join(d.replace("_", " ").title() for d in p.get("domains", []))
        org_str = f" ({p['org']})" if p.get("org") else ""
        source_badge = f"[{p.get('source', 'direct')}]"
        print(f"### {idx}. [{p['title']}]({p['arxiv_url']}) {source_badge}")
        print(f"- **arXiv ID**: `{p['id']}` | **Date**: {p['date']} | **Score**: {p.get('algorithmic_score', 0)} | **Upvotes**: {p.get('upvotes', 0)} | **Comments**: {p.get('comments', 0)}{org_str}")
        print(f"- **Domains**: {domains_str}")
        if p.get("authors"):
            print(f"- **Authors**: {', '.join(p['authors'])}")
        if p.get("github_repo"):
            stars_str = f" ({p['github_stars']} stars)" if p.get("github_stars") else ""
            print(f"- **Code**: [{p['github_repo']}]({p['github_repo']}){stars_str}")
        print(f"- **Abstract Snippet**: {p['summary'][:320]}...\n")

if __name__ == "__main__":
    main()
