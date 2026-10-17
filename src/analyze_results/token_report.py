"""Token usage summary for local vLLM runs.

call_qwen.py stores each call's token usage in the result row ("usage":
prompt/completion/total tokens and latency_s). This totals it per model x
prompt type x identity. Rows without "usage" (runs made before tracking was
added) are counted in n_rows but not n_with_usage.

    python token_report.py                  # sample_results_* files
    python token_report.py --prefix smoke   # smoke_* files

Outputs to results/token_usage/:
    token_usage_by_prompt.csv
    token_usage_by_model.csv
"""

import argparse
import glob
import json
import os
import sys

import pandas as pd

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import ROOT_DIR, PATH_TO_MODEL_RESULTS, LOCAL_MODELS

TOKEN_COLS = ["prompt_tokens", "completion_tokens", "total_tokens"]
GROUP_COLS = ["model", "fairness_definition", "prompt_type", "identity"]


def load_rows(prefix):
    rows = []
    for model_name in LOCAL_MODELS:
        for path in sorted(glob.glob(f"{PATH_TO_MODEL_RESULTS}{prefix}_*_{model_name}.jsonl")):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    usage = row.get("usage") or {}
                    rows.append({
                        "model": row["model"],
                        "fairness_definition": row.get("fairness_definition", "none"),
                        "prompt_type": row["prompt_type"],
                        "identity": row.get("identity") or "",
                        "has_usage": bool(usage),
                        "latency_s": usage.get("latency_s"),
                        **{c: usage.get(c) for c in TOKEN_COLS},
                    })
    return pd.DataFrame(rows)


def summarize(df, by):
    g = df.groupby(by)
    out = g.agg(n_rows=("has_usage", "size"), n_with_usage=("has_usage", "sum"))
    for c in TOKEN_COLS:
        out[f"sum_{c}"] = g[c].sum(min_count=1)
        out[f"mean_{c}"] = g[c].mean().round(1)
        out[f"max_{c}"] = g[c].max()
    out["mean_latency_s"] = g["latency_s"].mean().round(2)
    return out.reset_index()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", default="sample_results", help="output file prefix (e.g. smoke)")
    parser.add_argument("--out", default=os.path.join(ROOT_DIR, "results", "token_usage"))
    args = parser.parse_args()

    df = load_rows(args.prefix)
    if df.empty:
        print(f"No {args.prefix}_*.jsonl files found for {LOCAL_MODELS}")
        return

    by_prompt = summarize(df, GROUP_COLS)
    by_model = summarize(df, ["model"])
    total = summarize(df.assign(model="TOTAL"), ["model"])
    by_model = pd.concat([by_model, total], ignore_index=True)

    os.makedirs(args.out, exist_ok=True)
    by_prompt.to_csv(os.path.join(args.out, "token_usage_by_prompt.csv"), index=False)
    by_model.to_csv(os.path.join(args.out, "token_usage_by_model.csv"), index=False)

    cols = ["model", "n_rows", "n_with_usage", "sum_prompt_tokens",
            "sum_completion_tokens", "sum_total_tokens", "mean_total_tokens", "mean_latency_s"]
    print(by_model[cols].to_string(index=False))
    print(f"\nWrote {args.out}/token_usage_by_prompt.csv and token_usage_by_model.csv")


if __name__ == "__main__":
    main()
