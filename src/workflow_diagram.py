"""Emit the pipeline workflow diagram as Mermaid, ready to paste into Notion.

Notion: paste the fenced output into a page and it becomes a Mermaid code
block (toggle "Preview" to render). Or make a code block, set the language to
Mermaid, and paste the bare output.

    python workflow_diagram.py                # bare Mermaid to stdout
    python workflow_diagram.py --fenced       # wrapped in a ```mermaid fence
    python workflow_diagram.py --copy         # straight to clipboard (macOS)
    python workflow_diagram.py --plain        # drop styling, if Notion chokes
    python workflow_diagram.py --out d.mmd    # write to a file
"""

import argparse
import subprocess
import sys

DIAGRAM = """flowchart TD
    API([FFIEC HMDA Data Browser API])

    subgraph S1["1. Gather - src/gather_data/"]
        L["load_data.py<br/>GET view/csv, CA 2024"]
        P["preprocess_data.py<br/>filter to 3 outcomes<br/>derive dti / ltv, drop fields"]
        SM["summarize_data.py<br/>group by race / sex / ethnicity"]
    end

    subgraph S2["2. Sample - main.py --sample-data"]
        SD["sample_datasets.py<br/>N_SAMPLES draws of SAMPLE_SIZE rows<br/>no replacement, seed = SAMPLE_SEED + i"]
    end

    subgraph S3["3. Ground truth - src/ground_truth/"]
        LS["label_samples.py<br/>per-sample logit, collapse rare races<br/>method=failed if non-convergent"]
        RR["run_regression.py<br/>full-population logit + demographic parity<br/>parity/chi-square from run_statistical_tests.py"]
    end

    subgraph S4["4. Call models - src/call_models/"]
        PI["config.prompt_identity_pairs<br/>expands prompt_type x identity"]
        PR["prompts.py<br/>template + user_statement + data<br/>raw CSV rows, or summary if USE_SUMMARY"]
        SR["sample_runner.py<br/>loop samples, parse JSON, resume"]
        CLOUD["call_chatGPT.py<br/>call_claude.py<br/>call_gemini.py"]
        LOCAL["call_qwen.py<br/>local_qwen/Makefile: make serve"]
        RP["repair_raw_text.py<br/>re-parse failed rows"]
        BM["benchmark_local_model.py<br/>latency / tokens / JSON validity"]
    end

    subgraph S5["5. Analyze - src/analyze_results/"]
        AR["analyze_results.py<br/>counts, percentages, confidence<br/>chi-square + Fisher vs control"]
        SY["sycophancy_rate.py<br/>yes-rate delta vs control"]
        CG["compare_to_ground_truth.py<br/>accuracy / TPR / FPR, pairwise flips"]
    end

    RAW[("hmda_CA_2024.csv")]
    PRE[("preprocessed_data.csv<br/>53,202 rows")]
    SUM[("summary.txt")]
    SAMP[("samples/sample_000i.csv<br/>manifest.csv")]
    GT[("sample_labels.csv<br/>sample_term_labels.csv")]
    GTF[("ground_truth_labels.csv<br/>demographic_parity.csv<br/>chi_square_tests.csv")]
    JSONL[("sample_results_PROMPT_IDENTITY_MODEL.jsonl")]
    BR[("results/benchmark/*.summary.json")]
    R1[("tableresults.csv<br/>stats_vs_control.csv<br/>identity_breakdown.csv<br/>plots.png")]
    R2[("sycophancy-rate.csv<br/>heatmap + ranked bars")]
    R3[("gt_metrics_by_model_prompt.csv<br/>gt_flips_vs_control.csv")]

    API --> L --> RAW --> P --> PRE
    PRE --> SM --> SUM
    PRE --> SD --> SAMP
    SAMP --> LS --> GT
    PRE --> RR --> GTF

    SAMP --> PR
    SUM -.->|USE_SUMMARY=True| PR
    PI --> PR --> SR
    SR --> CLOUD --> JSONL
    SR --> LOCAL --> JSONL
    JSONL --> RP -.->|rewrites| JSONL
    SR -.->|discovery only| BM --> BR

    JSONL --> AR --> R1
    JSONL --> SY --> R2
    JSONL --> CG
    GT --> CG --> R3
"""

STYLE = """
    classDef ext fill:#e8e8f5,stroke:#5b5bd6
    classDef data fill:#f4f4f8,stroke:#8a8aa3
    classDef out fill:#e6f4ec,stroke:#2f8f5b
    class API ext
    class RAW,PRE,SUM,SAMP,GT,JSONL data
    class GTF,BR,R1,R2,R3 out
"""


def build(plain=False, fenced=False):
    text = DIAGRAM if plain else DIAGRAM + STYLE
    text = text.strip()
    return f"```mermaid\n{text}\n```" if fenced else text


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fenced", action="store_true", help="wrap in a ```mermaid fence")
    ap.add_argument("--plain", action="store_true", help="omit classDef styling")
    ap.add_argument("--copy", action="store_true", help="copy to clipboard (macOS pbcopy)")
    ap.add_argument("--out", metavar="PATH", help="write to a file instead of stdout")
    args = ap.parse_args()

    text = build(plain=args.plain, fenced=args.fenced)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"wrote {args.out}", file=sys.stderr)
    elif args.copy:
        subprocess.run("pbcopy", input=text, text=True, check=True)
        print("copied to clipboard", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
