## Extended Research

This project started as a class project and is now being extended into a research project on LLM prompt sensitivity and fairness analysis.

The original class project is kept on the `main` branch.  
Ongoing research experiments are developed in the `research-extension` branch.


# Bias by Prompt LLM Fairness

The goal of this project is to investigate how a given persona or role affects LLM-based data analysis. [Martin Bertran (2026)](https://arxiv.org/pdf/2602.18710) pointed out that LLM-powered agentic data scientists can reach different conclusions depending on the prompt framing or assigned persona, even when they use the same dataset and analytical methods. Based on this study, I wonder whether a model generates different outputs when it is given a sensitive background context and is encouraged to respond with empathy.

## Introduction

This project investigates how sensitive framing affects large language model conclusions in data analysis. In particular, it examines whether emotionally framed statements about bias influence how LLMs interpret loan approval outcomes.

### Research Question

"How does emotional or bias-related framing in prompts affect LLM conclusions when analyzing loan approval data?"

## Data Source

This project uses publicly available HMDA loan application data.

- **Dataset:** 2024 California HMDA loan application data
- **Source:** FFIEC HMDA Data Browser API
- **Outcomes analyzed:**
  - Loan originated
  - Application approved but not accepted
  - Application denied

### Models Used

**Cloud APIs**
- OpenAI (GPT)
- Google (Gemini)
- Anthropic (Claude)

**Local open-weight models** (served with vLLM, OpenAI-compatible API)
- Qwen2.5-7B-Instruct
- Llama-3.1-8B-Instruct
- Llama-3.2-3B-Instruct
- Gemma-3-12B-it

Which models and prompt types run is controlled in [`src/config.py`](src/config.py) (`GPT_MODELS`, `CLAUDE_MODELS`, `GEMINI_MODELS`, `QWEN_MODELS`, `LLAMA_MODELS`, `GEMMA_MODELS`, `PROMPT_TYPES`, `NUM_ITERATIONS`). `FAIRNESS_DEFINITION` (`"none"`, `"DI"`, `"DP"` or `"LR"`) adds a second instruction telling the model which fairness definition to apply (disparate impact with the 4/5ths rule, demographic parity, or logistic regression); one definition per run.

## Analysis

**Chi-Square & Fisher Test**
For categorical variable testing 2 x 2 table for example

  
||NO|YES|
|---|---|---|
|Control|236|66|
|Emotional|300|0|

## Summary of the results 


- Haiku 4.5 : Changed answer 180 degree with emotional input
- Gemini 2.5: Guardrail triggered by “bias” ? → More safer Output
- GPT 3.5: Same output, but lower confidence level

### Percentages by Model-Prompt (n=300 each)
<img width="1200" height="600" title = "Percentages by Model-Prompt (n=300 each)" alt="percentages-by-model-and-prompt" src="https://github.com/user-attachments/assets/9e55ce10-3441-42a5-a541-af4a79930a69" />

### Confidence by Model-Prompt (n=300 each)
<img width="1200" height="600" title = "Confidence by Model-Prompt (n=300 each)" alt="confidence-by-model-and-prompt-small" src="https://github.com/user-attachments/assets/acefc6bb-ca47-4624-8766-8cff8ec86c24" />

### Chi-Square & Fisher Test

<img width="1016" height="337" alt="image (12)" src="https://github.com/user-attachments/assets/77876b4e-c171-4c4b-af4d-db0ccec44fec" />


## Project layout

The pipeline is split into 5 stages. Each stage lives in its own folder under
`src/` and writes its outputs to a designated folder under `data/` or `results/`:

| Stage | Code | Outputs |
|---|---|---|
| 1. Gather data | `src/gather_data/` | `data/gather_data/` |
| 2. Local model server | vLLM, started by `src/call_models/call_qwen.py` | `results/logs/` (server logs) |
| 3. Call models | `src/call_models/` | `data/call_models/` |
| 4. Analyze results | `src/analyze_results/` | `results/analyze_results/{all_models,per_model,vs_ground_truth,switching,gpt4o_mini_all_identities}/` |
| 5. Ground truth regression | `src/ground_truth/` | `results/ground_truth/` |

All paths are defined in `src/config.py` and anchored to the repo root, so every
script can be run from any directory.

## Sampling design (per-sample ground truth)

Instead of sending the same full-dataset summary `NUM_ITERATIONS` times, the
sampling design draws `N_SAMPLES` distinct datasets of `SAMPLE_SIZE` rows each
(`src/config.py`), gives every sample its own ground-truth bias label, and runs
each model x prompt condition once per sample. Because every prompt condition
sees exactly the same N samples, decision flips caused purely by prompt framing
can be measured pairwise (McNemar test), and model conclusions can be scored
against ground truth (accuracy / TPR / FPR).

```sh
cd src
python main.py --sample-data      # data/gather_data/samples/sample_*.{csv,txt} + manifest
python main.py --label-samples    # results/ground_truth/sample_labels.csv
python main.py --ground-truth     # full-population parity / chi-square / logit
# run the call scripts in src/call_models/ (outputs: data/call_models/sample_results_*.jsonl)
python main.py --compare          # results/analyze_results/vs_ground_truth/gt_metrics_*.csv, gt_flips_*.csv
```

Ground truth per sample is automated: the same logistic regression used on the
full dataset (`denied ~ race + sex + financial controls`) is fit on
the sample's raw rows; a sensitive term that is significant and adverse marks
the sample `BIAS`. The per-sample fit adds a weak L2 penalty (λ=0.1,
`model.OTHER_PENALTY`) on the `Other` race dummy only: each 2,000-row sample has
just 17 `Other` rows, and when none is denied the plain logit fails to converge
(quasi-complete separation — 59/300 samples before the fix, 0/300 after). The
penalty leaves the scored race/sex labels unchanged (1205/1205 on the samples
that already converged); the full-population logit stays unpenalized. General prompts are scored against `bias_any`; the
female-Latino identity prompts against `bias_latino_female`. `SAMPLE_SIZE=2000`
was calibrated (`results/ground_truth/calibration_label_rates.csv`) so that
`bias_any` is true for ~46% of samples — near-maximal label variance — while the
per-sample summary (~4k tokens) still fits the 8k context of the local models.

A `SAMPLE_SIZE=300` variant was simulated (3 samples, same seeds as production)
to check whether shrinking rows-per-sample would cut cost: it's ~6.6x cheaper
per call (~12,465 vs ~82,401 tokens) but produced **zero label variance**
(`bias_any` 0/3, one sample's regression didn't even converge), which breaks
the pairwise-flip / accuracy analysis this design depends on — see
`doc/Identity_Embedding_Run_Report.md` §6. At `N_SAMPLES=3`, raising the
sample count at `SAMPLE_SIZE=2000` is a better cost lever than shrinking rows.

### Prompt data mode: summary vs. raw rows

`USE_SUMMARY` in `src/config.py` controls what each sample embeds under the
`Data:` section of the prompt:

- `USE_SUMMARY = True` — the per-sample aggregate stats table
  (`sample_{id}_summary.txt`, grouped by race/sex/ethnicity), a few KB.
- `USE_SUMMARY = False` (**current default**) — the sample's raw
  `sample_{id}.csv` rows (all `SAMPLE_SIZE` of them) embedded verbatim.

`sample_datasets.py` only writes `_summary.txt` files when `USE_SUMMARY` is
`True`; the raw CSV is always written either way. Note that raw mode sends a
much larger prompt than the calibrated ~4k-token summary above, so it may not
fit the 8k context window of the local models — check `USE_SUMMARY` before
running `call_qwen.py` or other local-model calls.

## How to run

### 1. Set up a virtual environment
From root repo

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Populate API keys in .env
Only needed for the cloud models (skip for local Qwen).

```sh
cd src
touch .env
```
Add your own API keys
```.env
export OPENAI_API_KEY = ""
export GEMINI_API_KEY = ""
export ANTHROPIC_API_KEY = ""
```

### 3. Gather data from HMDA and summarize

```sh
cd src/gather_data
python gather_data.py
```

1. Retrieve HMDA loan application data from the API `load_data.py`
2. Filter the dataset to selected decision outcomes `preprocess_data.py`
3. Summarize the preprocessed data by race, sex, and ethnicity `summarize_data.py`
4. Create 3 files in `data/gather_data/`
  - `hmda_CA_2024.csv`
  - `preprocessed_data.csv`
  - `summary.txt`

### 4. Call Large Language Models 

> [!WARNING]
> Skip, if you have data already. Set `NUM_ITERATIONS` in `src/config.py` before running — each iteration is one API call per model and prompt type.

**Cloud models** (from `src/call_models/`)

```sh
cd src/call_models
python call_chatGPT.py
python call_claude.py
python call_gemini.py
```

**All identities on all samples (OpenRouter).** By default each identity runs on
1/8 of the samples (`IDENTITY_SAMPLE_SPLIT`). `--no-identity-split` runs every
identity on all 300 samples, and `--out-dir` writes the files to their own folder.
The gpt-4o-mini full run (16 identity files × 300 samples, ≈ $47) goes to
`data/call_models/1110_gpt4o_mini_all_identities/`. That folder was seeded with
the existing gpt-4o-mini files, so only the missing samples are called:

```sh
cd src/call_models
python call_openrouter.py --models openai/gpt-4o-mini --no-identity-split \
    --out-dir ../../data/call_models/1110_gpt4o_mini_all_identities --workers 8 --max-cost 55
```

**Local models** (vLLM; needs a CUDA GPU with compute capability ≥ 7.0, e.g. A100 / A40 / L40S)

`call_qwen.py` starts `vllm serve` for each model in `LOCAL_MODELS`, sends the
calls concurrently, and stops the server. Weights are pulled from Hugging Face
into `$HF_HOME` on first use (Llama 3.x and Gemma 3 are gated: accept their
licences and set `HF_TOKEN`). On Discovery, submit [`run_qwen.job`](run_qwen.job):

```sh
sbatch run_qwen.job
```

or run directly on a GPU node:

```sh
cd src/call_models
python call_qwen.py --smoke   # control_prompt, 1 sample per model
python call_qwen.py
```

Server settings (`MAX_MODEL_LEN`, `GPU_MEM_UTIL`, `MAX_NUM_SEQS`,
`TENSOR_PARALLEL`, `CONCURRENCY`) are env vars; see `run_qwen.job`.

Each local-model row also stores the call's token usage (`usage`: prompt /
completion / total tokens and `latency_s`). After a run, total it per model ×
prompt type with:

```sh
python src/analyze_results/token_report.py                  # or --prefix smoke
```

which writes `results/token_usage/token_usage_by_{prompt,model}.csv`.

Each script loops over its models in `config.py` and all `PROMPT_TYPES`, and appends one JSON line per run to `data/call_models/sample_results_[{definition}_]{prompt_type}[_{identity}]_{model}.jsonl`. The `{definition}_` prefix (`di_`, `dp_`, `lr_`) is present only when `FAIRNESS_DEFINITION` is not `"none"`.

### 5. Analyze Results

```sh
cd src/analyze_results
python analyze_results.py
```

Or interactively with the notebook `src/analyze_results/analyze_results.ipynb`.

Models are auto-discovered from the `sample_results_*.jsonl` files in `data/call_models/`, so this works regardless of which models are active in `config.py`. It prints a coverage table (usable responses per model and prompt — rows that came back as API errors or non-JSON are skipped and counted), then saves to `results/analyze_results/per_model/`:

- `conclusion-count-by-prompt-{model}.png`
- `percentages-by-prompt-{model}.png` (with per-bar sample sizes)
- `confidence-by-prompt-{model}.png`
- `confidence-by-model-and-conclusion.png`
- `tableresults.csv` — conclusion counts per model and prompt
- `stats_vs_control.csv` — chi-square / Fisher exact tests of each prompt type against the control prompt, per model

`python all_models_by_prompt.py` puts all models side by side, one panel per prompt (identity prompts pool all identities; models keep the same row everywhere, highest mean YES rate on top), and saves to `results/analyze_results/all_models/`:

- `yes-no-counts-by-prompt.png/.pdf`: YES and NO answer counts per model
- `yes-no-percent-by-prompt.png/.pdf`: YES / NO share as 100% bars, labeled with YES % and n
- `yes-no-by-prompt.csv`: per model × prompt, n, YES, NO, other, and the shares

`python answer_change.py` pairs every identity-framed answer with the same model's control answer on the same sample, and saves to `results/analyze_results/switching/`:

- `answer-change-dyes-heatmap.png` — Δ YES rate vs control (pp), models × identities, one panel per identity prompt type
- `answer-change-by-identity.csv` — per model × prompt type × identity: n, YES rates, Δ YES, share changed, NO→YES and YES→NO flips, Δ confidence
- `answer-change-pairs.csv` — one row per paired (identity call, control call)

`python ground_truth_plots.py` scores each answer against the per-sample ground truth (`results/ground_truth/sample_labels_l2.csv` / `sample_term_labels_l2.csv`; identity prompts against that identity's own race/sex terms) and saves to `results/analyze_results/vs_ground_truth/` (as do the `gt_*.csv` files from `compare_to_ground_truth.py`):

- `gt-hit-false-alarm.csv` — per model and prompt: hit rate (YES when biased), false alarm (YES when not biased), J = hit − false alarm with bootstrap 95% CI, precision, F1 and the F1 of always saying YES (`f1_always_yes`)
- `gt-yes-decomposition.png/.pdf` — YES rate per model × prompt, split into YES on biased vs not-biased samples, with the true biased share as a tick; right-hand text is recall | precision | F1, with the always-YES F1 in the header
- `gt-discrimination.png/.pdf` — J with 95% CI per model × prompt (0 = YES unrelated to truth)
- `gt-identity-truth-vs-yes.csv` — per model, identity prompt and identity: true biased rate vs YES rate, with Wilson 95% CI
- `gt-identity-gap-heatmap.png/.pdf` — YES rate minus true biased rate per model × identity; outlined cells are beyond sampling noise

`python switch_by_truth.py` asks whether a sample's ground truth changes how often a model switches its answer under framing (same model, same sample, framed vs baseline prompt). Comparisons: emotional vs control and emotional + identity vs identity (only emotion changes), plus identity vs control (the question changes, so this is not sycophancy) and emotional + identity vs control (emotion and question both change). Each is split into NO→YES (toward the user's claim) and YES→NO (away from it), and the switch rate is compared between biased and not-biased samples. It saves to `results/analyze_results/switching/` (as does `sycophancy_rate.py`):

- `switch-by-truth.csv`: per model × comparison × direction, switch counts on biased vs not-biased samples (LR labels), the risk difference with a Newcombe 95% CI, and the Fisher p-value
- `switch-by-truth-pooled.csv`: GEE logit `switch ~ biased + C(model)` clustered by sample, per comparison × direction (models with ≥10 switches and a switch rate below 100%)
- `switch-by-truth.png/.pdf`: switch rate on not-biased vs biased samples per model; grey ≈ red means switching ignores the data
- `switch-by-truth-simple.png/.pdf`: the same as plain bars, only models with 10+ switches in a panel, with the gap labeled significant / not significant

`python confusion_by_identity.py` reads the gpt-4o-mini all-identity run (`data/call_models/1110_gpt4o_mini_all_identities/`) and counts TP / FN / FP / TN per identity for all four prompts on the same samples, with truth = that identity's own LR race/sex terms (White identities are never biased, so their TP = FN = 0). It saves to `results/analyze_results/gpt4o_mini_all_identities/`:

- `tp-fn-fp-tn-by-identity.csv`: per identity × prompt, n, n biased, TP, FN, FP, TN, other, recall, precision, F1
- `tp-fn-fp-tn-by-identity.png/.pdf`: one panel per identity, four bars (TP, FN, FP, TN) per prompt

`python reasoning_to_markdown.py` turns the reasoning summaries in `data/call_models/reasoning/` (saved by `batch_claude.py` for variants that request them, e.g. `claude-haiku-5-5-thinking`) into one readable Markdown file per prompt in `results/reasoning/`, YES answers first.

### 6. Ground truth regression + demographic parity

One script per statistical test, each runnable on its own against all of
`data/gather_data/preprocessed_data.csv`:

```sh
cd src/ground_truth
python test_demographic_parity.py   # 1. denial rate per group
python test_disparate_impact.py     # 2. approval rate per group, four-fifths rule
python test_chi_square.py           # 3. is the decision independent of the attribute?
python test_logit_population.py     # 4. same question, financial controls held fixed
```

1. **Demographic parity** (`test_demographic_parity.py`) — whether the denial
   rate is the same for every group of a sensitive attribute (race, sex). Per
   group: denial rate, parity difference and parity ratio vs the reference
   group (White / Male).
2. **Disparate impact** (`test_disparate_impact.py`) — the same comparison on
   the *favorable* outcome: each group's approval rate as a fraction of the
   reference group's, flagged `adverse_impact` when that ratio falls below the
   EEOC four-fifths threshold (`--threshold`, default 0.8).
3. **Chi-square test of independence** (`test_chi_square.py`) — the significance
   test for the gaps above, one per attribute.
4. **Logistic regression** (`test_logit_population.py`)
   `denied ~ race + sex + financial controls` — the controlled bias label per
   sensitive group.

Tests 1 and 2 are not reciprocals of each other: approval is `1 - denial`, so a
group denied at 2.36× the reference rate is still approved at 0.92× it. The
four-fifths rule is conventionally defined on the favorable outcome, which makes
it far less sensitive than the denial-rate view whenever approval is the common
outcome — see the key result below.

To run all four off a single load of the data:

```sh
python run_all.py          # or, from src/:  python main.py --ground-truth
```

Shared code lives in `data_prep.py` (`load_and_clean`) and `model.py` (the logit,
the BIAS/FAVORED/NO_BIAS rule, and `REFERENCES` — the one place the White/Male
reference groups are defined). `label_samples.py` reuses both to fit the same
model per sample via `run_penalized_regression` (L2 penalty on the `Other` dummy
only, HC1 SEs; `method=logit_l2` in `sample_labels.csv`).

Saves to `results/ground_truth/`:

- `demographic_parity.csv` — n, denial rate, parity difference and parity ratio per attribute × group
- `disparate_impact.csv` — n, approval (selection) rate, impact difference, impact ratio and `adverse_impact` per attribute × group
- `chi_square_tests.csv` — chi-square statistic, dof, p-value and `parity_violated` per attribute
- `ground_truth_labels.csv` — BIAS / FAVORED / NO_BIAS label per sensitive group
- `full_regression_coefficients.csv`
- `regression_summary.txt`

`python plot_ground_truth.py` draws the per-sample ground truth on its own (no model answers) to `results/ground_truth/`:

- `gt-overview-population-vs-samples.png/.pdf`: LR log-odds per sample and term, coloured by label, against the population log-odds
- `gt-overview-label-rates.png/.pdf`: % of samples labeled BIAS / FAVORED / NO_BIAS per term under LR, DI and DP, with the population label
- `gt-overview-barcode.png/.pdf`: every sample's label per term, in the same sample order for each definition, plus bias_any agreement
- `gt-overview-p-values.png/.pdf`: per-sample LR and DP p-values against α, showing how many labels sit near the cut-off
- `gt-overview-identity-truth.png/.pdf`: per identity and definition, the share of that identity's samples that are biased against it
- `gt-overview-summary.csv`: label counts per definition × term, with the population label

Key result: demographic parity fails for both attributes (race χ² p ≈ 3e-105,
sex χ² p ≈ 5e-32). Black or African American applicants are denied at 2.36× the
White rate and Hispanic or Latino at 1.72×; race stays adverse after financial
controls (Black or African American OR ≈ 1.80, Hispanic or Latino OR ≈ 1.26).
Female vs Male denial rates are nearly equal (ratio 1.02) and with controls
female applicants have slightly *lower* denial odds (OR ≈ 0.90) — the sex
chi-square is driven by joint applications (ratio 0.74).

The four-fifths rule flags **nothing**, for any group. Because ~92% of
applications are approved, the worst impact ratio is Black or African American
at 0.92 — comfortably above 0.8 — even though the same group is denied at 2.36×
the White rate and the chi-square rejects independence at p ≈ 3e-105. This is a
known insensitivity of the 80% rule when the favorable outcome is the common
one, not a contradiction: `disparate_impact.csv` and `demographic_parity.csv`
are measuring the same gaps on different scales.

> [!NOTE]
> `src/main.py` is a thin dispatcher over the same stages: `python main.py --gather-data | --call-models | --analyze` (cloud models only; local models still run via `call_qwen.py`).
