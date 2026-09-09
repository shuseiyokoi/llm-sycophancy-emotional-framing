# Pipeline: HMDA API to printed results

Five stages. Each lives in one folder under `src/`, writes to one folder under `data/` or `results/`, and is runnable standalone or via `src/main.py`.

```mermaid
flowchart TD
    API([FFIEC HMDA Data Browser API]):::ext

    subgraph S1["1. Gather · src/gather_data/ · main.py --gather-data"]
        L[load_data.py<br/>GET view/csv, CA 2024]
        P[preprocess_data.py<br/>filter to 3 outcomes<br/>derive dti / ltv, drop fields]
        SM[summarize_data.py<br/>group by race / sex / ethnicity]
    end

    subgraph S2["2. Sample · main.py --sample-data"]
        SD[sample_datasets.py<br/>N_SAMPLES draws of SAMPLE_SIZE rows<br/>no replacement, seed = SAMPLE_SEED + i]
    end

    subgraph S3["3. Ground truth · src/ground_truth/"]
        LS[label_samples.py --label-samples<br/>per-sample logit, collapse rare races<br/>Fisher fallback if non-convergent]
        RR[run_regression.py / run_statistical_tests.py<br/>full-population logit + chi-square]
    end

    subgraph S4["4. Call models · src/call_models/ · main.py --call-models"]
        PR[prompts.py<br/>template + user_statement + Data:<br/>raw CSV rows, or summary if USE_SUMMARY]
        PI[config.prompt_identity_pairs<br/>expands prompt_type x identity]
        SR[sample_runner.py<br/>loop samples, parse JSON, resume]
        CLOUD[call_chatGPT.py<br/>call_claude.py<br/>call_gemini.py]
        LOCAL[call_qwen.py<br/>via local_qwen/Makefile: make serve]
        RP[repair_raw_text.py<br/>re-parse failed rows]
        BM[benchmark_local_model.py<br/>latency / tokens / JSON validity]
    end

    subgraph S5["5. Analyze · src/analyze_results/"]
        AR[analyze_results.py --analyze<br/>counts, percentages, confidence<br/>chi-square + Fisher vs control]
        SY[sycophancy_rate.py<br/>yes-rate delta vs control]
        CG[compare_to_ground_truth.py --compare<br/>accuracy / TPR / FPR, pairwise flips]
    end

    RAW[(hmda_CA_2024.csv)]:::data
    PRE[(preprocessed_data.csv<br/>53,202 rows)]:::data
    SUM[(summary.txt)]:::data
    SAMP[(samples/sample_000i.csv<br/>+ _summary.txt, manifest.csv)]:::data
    GT[(sample_labels.csv<br/>sample_term_labels.csv)]:::data
    GTF[(ground_truth_labels.csv<br/>chi_square_tests.csv<br/>statistical_tests_summary.txt)]:::out
    JSONL[(call_models/<br/>sample_results_PROMPT_IDENTITY_MODEL.jsonl)]:::data
    BR[(results/benchmark/*.summary.json)]:::out
    R1[(tableresults.csv<br/>stats_vs_control.csv<br/>identity_breakdown.csv<br/>*.png)]:::out
    R2[(sycophancy-rate.csv<br/>heatmap + ranked bars)]:::out
    R3[(gt_metrics_by_model_prompt.csv<br/>gt_flips_vs_control.csv)]:::out

    API --> L --> RAW --> P --> PRE
    PRE --> SM --> SUM
    PRE --> SD --> SAMP
    SAMP --> LS --> GT
    PRE --> RR --> GTF

    SAMP --> PR
    SUM -.USE_SUMMARY=True.-> PR
    PI --> PR --> SR
    SR --> CLOUD --> JSONL
    SR --> LOCAL --> JSONL
    JSONL --> RP -.rewrites.-> JSONL
    SR -.discovery only.-> BM --> BR

    JSONL --> AR --> R1
    JSONL --> SY --> R2
    JSONL --> CG
    GT --> CG --> R3

    classDef ext fill:#e8e8f5,stroke:#5b5bd6,stroke-width:1px
    classDef data fill:#f4f4f8,stroke:#8a8aa3,stroke-width:1px
    classDef out fill:#e6f4ec,stroke:#2f8f5b,stroke-width:1px
```

## Run order

```sh
cd src
python main.py --gather-data      # 1. API -> preprocessed_data.csv + summary.txt
python main.py --sample-data      # 2. -> data/gather_data/samples/
python main.py --label-samples    # 3. -> results/ground_truth/sample_labels.csv

cd call_models                    # 4. one call per (model x prompt x identity x sample)
python call_chatGPT.py            #    cloud
python call_claude.py
python call_gemini.py
cd ../local_qwen && make serve    #    local: terminal 1
cd ../call_models && python call_qwen.py   #      terminal 2

cd ../                            # 5.
python main.py --analyze          #    -> results/analyze_results/*.png + .csv
python main.py --compare          #    -> gt_metrics_*.csv, gt_flips_*.csv
```

## What controls the shape of a run

All in `src/config.py`:

| Knob | Effect |
|---|---|
| `N_SAMPLES`, `SAMPLE_SIZE`, `SAMPLE_SEED` | how many datasets, how many rows each, reproducibility |
| `USE_SUMMARY` | prompt embeds raw CSV rows (`False`, current) or the aggregate table (`True`) |
| `PROMPT_TYPES`, `IDENTITY_PROMPT_TYPES` | the 7 framings, and which 3 take a persona |
| `IDENTITIES`, `SELECTED_IDENTITIES` | the persona cross product (race x ethnicity x sex x age) |
| `GPT_/CLAUDE_/GEMINI_/QWEN_/LLAMA_/GEMMA_MODELS` | which models run |

Calls per model = `(non-identity prompts + identity prompts x identities) x N_SAMPLES`. The 8/31 run: `(4 + 3 x 16) x 3 = 156`.

## Notes

- **Resume is built in.** `sample_runner.completed_sample_ids()` reads the existing `.jsonl` and skips finished samples, so a crashed run restarts where it stopped.
- **Two ground-truth paths.** `label_samples.py` labels each *sample* (feeds `--compare`); `run_regression.py` / `run_statistical_tests.py` label the *full population* (standalone reporting). Only the first is wired into scoring.
- **Model discovery is filename-driven.** `analyze_results.py` and `compare_to_ground_truth.py` glob `sample_results_*.jsonl` rather than reading `config.py`, so they work on archived runs whose models are no longer in the config.
