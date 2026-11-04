"""Turn the reasoning summaries saved by batch_claude.py into readable Markdown.

Reads data/call_models/reasoning/sample_results_*.jsonl (one file per answer
file) and writes one Markdown file per input to results/reasoning/, with YES
answers first, then NO, then anything else. Each call is a section with its
sample id, identity, confidence, the model's evidence and its reasoning.

    python reasoning_to_markdown.py
"""

import glob
import json
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import PATH_TO_MODEL_RESULTS, ROOT_DIR

REASONING_DIR = os.path.join(PATH_TO_MODEL_RESULTS, "reasoning")
OUT_DIR = os.path.join(ROOT_DIR, "results", "reasoning")

ORDER = {"YES": 0, "NO": 1}


def to_markdown(name, rows):
    rows = sorted(rows, key=lambda r: (ORDER.get(str(r.get("conclusion")), 2), r["sample_id"]))
    counts = {}
    for r in rows:
        counts[str(r.get("conclusion"))] = counts.get(str(r.get("conclusion")), 0) + 1
    first = rows[0]

    lines = [
        f"# {name}",
        "",
        f"- Model: `{first['model']}`",
        f"- Prompt: `{first['prompt_type']}`" + (f", identity `{first['identity']}`" if first["identity"] else ""),
        f"- Calls: {len(rows)} (" + ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: ORDER.get(kv[0], 2))) + ")",
        "- Reasoning is the API's summary of the model's thinking, not the raw chain.",
        "",
    ]
    current = None
    for r in rows:
        conclusion = str(r.get("conclusion"))
        if conclusion != current:
            current = conclusion
            lines += [f"## {conclusion} ({counts[conclusion]})", ""]
        lines += [
            f"### {r['sample_id']} — {conclusion}, confidence {r.get('confidence')}",
            "",
            f"**Evidence:** {r.get('evidence')}",
            "",
            "**Reasoning:**",
            "",
            r["thinking"].strip(),
            "",
            "---",
            "",
        ]
    return "\n".join(lines)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    paths = sorted(glob.glob(os.path.join(REASONING_DIR, "sample_results_*.jsonl")))
    for path in paths:
        with open(path, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        if not rows:
            continue
        name = os.path.basename(path)[len("sample_results_") : -len(".jsonl")]
        with open(os.path.join(OUT_DIR, f"{name}.md"), "w", encoding="utf-8") as f:
            f.write(to_markdown(name, rows))
    print(f"Wrote {len(paths)} Markdown files to {OUT_DIR}")


if __name__ == "__main__":
    main()
