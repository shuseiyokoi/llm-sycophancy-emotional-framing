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

**Local open-weight models** (served with llama.cpp, OpenAI-compatible API)
- Qwen2.5-7B-Instruct
- Qwen3-8B
- Llama-3.1-8B-Instruct
- Llama-3.2-3B-Instruct
- Gemma-2-9B-it
- Gemma-3-12B-it

Which models and prompt types run is controlled in [`src/config.py`](src/config.py) (`GPT_MODELS`, `CLAUDE_MODELS`, `GEMINI_MODELS`, `QWEN_MODELS`, `LLAMA_MODELS`, `GEMMA_MODELS`, `PROMPT_TYPES`, `NUM_ITERATIONS`).

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


## How to run

### 1. Set up a virtual environment
From root repo

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Create data and results directories (Optional)
From root repo

```sh
mkdir data
mkdir results
```

### 3. Populate API keys in .env
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

### 4. Gather data from HMDA and summarize

```sh
python gather_data.py
```

1. Retrieve HMDA loan application data from the API `load_data.py`
2. Filter the dataset to selected decision outcomes `preprocess_data.py`
3. Summarize the preprocessed data by race, sex, and ethnicity `summarize_data.py`
4. Create 3 files in data directory
  - `hmda_CA_2024.csv`
  - `preprocessed_data.csv`
  - `summary.txt`

### 5. Call Large Language Models 

> [!WARNING]
> Skip, if you have data already. Set `NUM_ITERATIONS` in `src/config.py` before running — each iteration is one API call per model and prompt type.

**Cloud models** (from `src/`)

```sh
python call_chatGPT.py
python call_claude.py
python call_gemini.py
```

**Local Qwen** (no API key needed)

Terminal 1 — start the llama.cpp server (expects the GGUF model path set in `src/local_qwen/Makefile`):

```sh
cd src/local_qwen
make serve
```

Terminal 2 — run the calls against the local server:

```sh
cd src
python call_qwen.py
```

Each script loops over its models in `config.py` and all `PROMPT_TYPES`, and appends one JSON line per run to `data/results_{prompt_type}_{model}.jsonl`.

### 6. Analyze Results

```sh
python analyze_results.py
```

Or interactively with the notebook `src/analyze_results.ipynb`.

Models are auto-discovered from the `results_*.jsonl` files in `data/`, so this works regardless of which models are active in `config.py`. It prints a coverage table (usable responses per model and prompt — rows that came back as API errors or non-JSON are skipped and counted), then saves to `results/`:

- `conclusion-count-by-prompt-{model}.png`
- `percentages-by-prompt-{model}.png` (with per-bar sample sizes)
- `confidence-by-prompt-{model}.png`
- `confidence-by-model-and-conclusion.png`
- `tableresults.csv` — conclusion counts per model and prompt
- `stats_vs_control.csv` — chi-square / Fisher exact tests of each prompt type against the control prompt, per model

> [!NOTE]
> `main.py` (the old `--gather-data` / `--call-models` / `--analyze` entry point) is currently out of sync with `config.py` and the per-script workflow above is the supported way to run the pipeline.
