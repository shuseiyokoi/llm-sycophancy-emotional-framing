"""
Run the local open-weight models in config.LOCAL_MODELS through vLLM.

For each model this starts `vllm serve` (OpenAI-compatible API on
localhost:PORT), sends every pending (prompt, identity, sample) with
CONCURRENCY requests in flight, then stops the server. Server output goes to
results/logs/vllm_<model>.log. Tune MAX_MODEL_LEN, GPU_MEM_UTIL,
MAX_NUM_SEQS, TENSOR_PARALLEL and CONCURRENCY via env vars (see run_qwen.job).

    python call_qwen.py           # all prompt types, all samples
    python call_qwen.py --smoke   # control_prompt, 1 sample per model
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

from openai import OpenAI

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import (
    ROOT_DIR,
    PATH_TO_MODEL_RESULTS,
    LOCAL_MODELS,
    PROMPT_TYPES,
    prompt_identity_pairs,
    prompt_identity_label,
    identity_sample_ids,
)
from prompts import list_sample_ids
from sample_runner import run_sample_set, completed_sample_ids

VLLM = os.getenv("VLLM", "vllm")
PORT = int(os.getenv("QWEN_PORT", "8080"))
BASE_URL = f"http://localhost:{PORT}/v1"

# server/load knobs, overridable from the job script per GPU
MAX_MODEL_LEN = os.getenv("MAX_MODEL_LEN", "120000")  # raw-mode prompts run up to ~111.6k tokens + completion
GPU_MEM_UTIL = os.getenv("GPU_MEM_UTIL", "0.90")
MAX_NUM_SEQS = os.getenv("MAX_NUM_SEQS", "16")
TENSOR_PARALLEL = os.getenv("TENSOR_PARALLEL", "1")
CONCURRENCY = int(os.getenv("CONCURRENCY", "16"))  # in-flight requests per (model, prompt, identity)
LOAD_TIMEOUT_S = 15 * 60  # first run downloads weights and captures CUDA graphs

PATH_TO_LOGS = os.path.join(ROOT_DIR, "results", "logs")

# vLLM structured output: constrain every local model to the prompt's STRICT
# JSON format (same fields the cloud models are asked for). Restricts only
# the output shape, not the decision; fixes llama-3.1's markdown answers and
# gemma's out-of-range confidence. Disable with GUIDED_JSON=0.
GUIDED_JSON = os.getenv("GUIDED_JSON", "1") == "1"
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "conclusion": {"type": "string", "enum": ["YES", "NO"]},
        "confidence": {"type": "integer", "minimum": 0, "maximum": 10},
        "evidence": {"type": "string", "maxLength": 1500},
    },
    "required": ["conclusion", "confidence", "evidence"],
    "additionalProperties": False,
}
RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {"name": "analysis", "schema": RESPONSE_SCHEMA, "strict": True},
}

# HF repo, extra `vllm serve` flags, and extra request fields for each model in
# config.LOCAL_MODELS. Weights are pulled into $HF_HOME on first use; the
# Llama and Gemma repos are gated, so accept their licences on HF and set HF_TOKEN.
LOCAL_SERVER_CONFIG = {
    "qwen2.5-7b-instruct": {
        "repo": "Qwen/Qwen2.5-7B-Instruct",
        # native context is 32768; scale RoPE via YaRN so the model attends
        # sanely out to MAX_MODEL_LEN (raw-mode prompts run ~111.6k)
        # transformers >=5 reads `rope_parameters` (with rope_theta inside);
        # older versions read `rope_scaling` -- send both so the override
        # applies either way and vLLM derives max_model_len = 4 * 32768
        "extra_args": [
            "--hf-overrides",
            json.dumps({
                # vLLM >=0.31 no longer multiplies by `factor` for YaRN; it
                # expects max_position_embeddings to already be the scaled
                # value (32768 * 4)
                "max_position_embeddings": 131072,
                "rope_scaling": {
                    "rope_type": "yarn",
                    "factor": 4.0,
                    "original_max_position_embeddings": 32768,
                },
                "rope_parameters": {
                    "rope_type": "yarn",
                    "rope_theta": 1000000.0,
                    "factor": 4.0,
                    "original_max_position_embeddings": 32768,
                },
            }),
        ],
    },
    # "qwen3-8b": {
    #     "repo": "Qwen/Qwen3-8B",
    #     "extra_args": [],
    #     # disable thinking so the output is only the strict JSON answer
    #     "request_extra": {"chat_template_kwargs": {"enable_thinking": False}},
    # },
    "llama-3.1-8b-instruct": {
        "repo": "meta-llama/Llama-3.1-8B-Instruct",
        "extra_args": [],
    },
    "llama-3.2-3b-instruct": {
        "repo": "meta-llama/Llama-3.2-3B-Instruct",
        "extra_args": [],
    },
    "gemma-3-12b-it": {
        "repo": "google/gemma-3-12b-it",
        # text-only prompts: don't reserve memory for image inputs
        "extra_args": ["--limit-mm-per-prompt", json.dumps({"image": 0})],
    },
}


def server_is_up():
    try:
        with urllib.request.urlopen(f"http://localhost:{PORT}/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def start_server(model_name):
    if server_is_up():
        raise RuntimeError(
            f"A server is already running on port {PORT}. Stop it first so "
            "results are labeled with the model this script loads."
        )

    server_config = LOCAL_SERVER_CONFIG[model_name]
    os.makedirs(PATH_TO_LOGS, exist_ok=True)
    log_path = os.path.join(PATH_TO_LOGS, f"vllm_{model_name}.log")
    log_file = open(log_path, "w")

    proc = subprocess.Popen(
        [
            VLLM, "serve", server_config["repo"],
            "--port", str(PORT),
            "--served-model-name", model_name,
            "--max-model-len", MAX_MODEL_LEN,
            "--gpu-memory-utilization", GPU_MEM_UTIL,
            "--max-num-seqs", MAX_NUM_SEQS,
            "--tensor-parallel-size", TENSOR_PARALLEL,
            *server_config["extra_args"],
        ],
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    proc.log_file = log_file

    deadline = time.time() + LOAD_TIMEOUT_S
    while time.time() < deadline:
        if server_is_up():
            print(f"vLLM server is up with {model_name} (log: {log_path})")
            return proc
        if proc.poll() is not None:
            log_file.close()
            raise RuntimeError(
                f"vllm serve exited while loading {model_name} "
                f"(exit code {proc.returncode}); see {log_path}"
            )
        time.sleep(5)

    stop_server(proc)
    raise RuntimeError(
        f"Server for {model_name} was not healthy after {LOAD_TIMEOUT_S // 60} "
        f"minutes; see {log_path}"
    )


def stop_server(proc):
    proc.terminate()
    try:
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
    if hasattr(proc, "log_file"):
        proc.log_file.close()


def call_qwen(prompt_types=PROMPT_TYPES, sample_ids=None, output_prefix="sample_results"):
    os.makedirs(PATH_TO_MODEL_RESULTS, exist_ok=True)

    if sample_ids is None:
        sample_ids = list_sample_ids()

    client = OpenAI(base_url=BASE_URL, api_key="local")

    for model_name in LOCAL_MODELS:
        # resume support: skip (model, prompt, identity) pairs whose output
        # file already covers every sample; run_sample_set fills in partial ones
        pending = []
        for prompt_type, identity in prompt_identity_pairs(prompt_types):
            label = prompt_identity_label(prompt_type, identity)
            output_file = f"{PATH_TO_MODEL_RESULTS}{output_prefix}_{label}_{model_name}.jsonl"
            done = completed_sample_ids(output_file)
            if all(s in done for s in identity_sample_ids(sample_ids, identity)):
                print(f"Skipping {model_name} | {label}: all samples recorded")
            else:
                pending.append((prompt_type, identity, label, output_file))

        if not pending:
            print(f"Skipping {model_name}: all prompt types complete")
            continue

        proc = start_server(model_name)
        request_extra = LOCAL_SERVER_CONFIG[model_name].get("request_extra")

        def send_fn(prompt_text):
            kwargs = {}
            if GUIDED_JSON:
                kwargs["response_format"] = RESPONSE_FORMAT
            t0 = time.perf_counter()
            completion = client.chat.completions.create(
                model=model_name,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt_text}],
                extra_body=request_extra,
                **kwargs,
            )
            # token usage is recorded in each output row (see token_report.py)
            usage = completion.usage
            return completion.choices[0].message.content, {
                "prompt_tokens": usage.prompt_tokens if usage else None,
                "completion_tokens": usage.completion_tokens if usage else None,
                "total_tokens": usage.total_tokens if usage else None,
                "latency_s": round(time.perf_counter() - t0, 3),
            }

        try:
            for prompt_type, identity, label, output_file in pending:
                print(f"\nStarting: {model_name} | {label}")
                run_sample_set(
                    send_fn,
                    model_name,
                    prompt_type,
                    output_file,
                    sample_ids=sample_ids,
                    sleep_s=0,
                    identity=identity,
                    workers=CONCURRENCY,
                )
                print(f"Finished: {model_name} | {label}")
        finally:
            stop_server(proc)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="quick test: control_prompt only, 1 sample per model, writes to smoke_*.jsonl",
    )
    args = parser.parse_args()

    if args.smoke:
        call_qwen(
            prompt_types=["control_prompt"],
            sample_ids=list_sample_ids()[:1],
            output_prefix="smoke",
        )
    else:
        call_qwen()
