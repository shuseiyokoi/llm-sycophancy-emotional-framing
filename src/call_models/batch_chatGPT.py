"""Full GPT run through the OpenAI Batch API (half price, results within 24h).

Same requests as call_chatGPT.py (Responses API, same input), sent as batch
jobs. Results are written as normal sample_results_*.jsonl rows, plus a
"usage" dict with cost computed from config.OPENAI_BATCH_PRICES.

    python batch_chatGPT.py prepare   # write request chunks for samples not yet recorded
    python batch_chatGPT.py submit    # upload chunks and create batch jobs (asks first)
    python batch_chatGPT.py status    # status + request counts per batch
    python batch_chatGPT.py collect   # write finished batches' results to sample_results_*.jsonl
    python batch_chatGPT.py run       # loop: keep one chunk per model queued, collect as they finish

State (chunk files -> batch ids) lives in data/call_models/batches/openai_batches.json.
Failed or expired requests are written as {"error": ...} rows, which resume
skips, so running prepare + submit again retries them.
"""

import argparse
import glob
import json
import os
import sys
import time

from dotenv import load_dotenv
from openai import OpenAI

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import (
    PATH_TO_MODEL_RESULTS,
    GPT_MODELS,
    OPENAI_BATCH_PRICES,
    FAIRNESS_DEFINITION,
    prompt_identity_pairs,
    prompt_identity_label,
    identity_sample_ids,
)
from prompts import list_sample_ids, get_sample_prompt
from sample_runner import completed_sample_ids, parse_json_response

BATCH_DIR = f"{PATH_TO_MODEL_RESULTS}batches{os.sep}"
STATE_FILE = f"{BATCH_DIR}openai_batches.json"
CHUNK_SIZE = 250  # ~74K tokens/request -> ~18.5M tokens/chunk; the org's batch
# queue holds 20M enqueued tokens per model, so one chunk per model at a time
MAX_SUBMIT_ATTEMPTS = 20  # per chunk, before `run` gives up resubmitting it
LIVE = ("validating", "in_progress", "finalizing")

# mean tokens per call measured in the OpenRouter smoke run (2026-11-02), for the
# pre-submit cost estimate only
SMOKE_MEAN_TOKENS = {"gpt-5-mini": (73807, 1165), "gpt-5-nano": (73807, 2727),
                     "gpt-4o-mini": (73807, 150)}  # 4o-mini: not smoke-tested; no reasoning, output guessed


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"chunks": {}}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def output_file_for(model_name, label):
    return f"{PATH_TO_MODEL_RESULTS}sample_results_{label}_{model_name}.jsonl"


def prepare():
    os.makedirs(BATCH_DIR, exist_ok=True)
    state = load_state()

    # samples already sent in a batch that hasn't been collected yet
    in_flight = set()
    for chunk in state["chunks"].values():
        if chunk.get("status") not in ("collected", "failed", "expired", "cancelled"):
            with open(chunk["path"], encoding="utf-8") as f:
                in_flight.update(json.loads(line)["custom_id"] for line in f)

    all_ids = list_sample_ids()
    for model_name in GPT_MODELS:
        requests = []
        for prompt_type, identity in prompt_identity_pairs():
            label = prompt_identity_label(prompt_type, identity)
            done = completed_sample_ids(output_file_for(model_name, label))
            for sample_id in identity_sample_ids(all_ids, identity):
                custom_id = f"{model_name}|{label}|{sample_id}"
                if sample_id in done or custom_id in in_flight:
                    continue
                requests.append({
                    "custom_id": custom_id,
                    "method": "POST",
                    "url": "/v1/responses",
                    "body": {
                        "model": model_name,
                        "input": [{"role": "user", "content": get_sample_prompt(prompt_type, sample_id, identity)}],
                    },
                })

        print(f"{model_name}: {len(requests)} pending requests")
        n_existing = len(glob.glob(f"{BATCH_DIR}{model_name}_*.jsonl"))
        for k in range(0, len(requests), CHUNK_SIZE):
            path = f"{BATCH_DIR}{model_name}_{n_existing + k // CHUNK_SIZE:03d}.jsonl"
            chunk = requests[k : k + CHUNK_SIZE]
            with open(path, "w", encoding="utf-8") as f:
                for r in chunk:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            state["chunks"][os.path.basename(path)] = {
                "path": path, "model": model_name, "n_requests": len(chunk), "status": "prepared",
            }
            print(f"  wrote {path} ({len(chunk)} requests, {os.path.getsize(path) / 1e6:.0f} MB)")

    save_state(state)


def estimated_cost(model_name, n_requests):
    in_tok, out_tok = SMOKE_MEAN_TOKENS[model_name]
    in_price, out_price = OPENAI_BATCH_PRICES[model_name]
    return n_requests * (in_tok * in_price + out_tok * out_price) / 1e6


def submit(client, yes=False):
    state = load_state()
    todo = [(name, c) for name, c in state["chunks"].items()
            if c["status"] in ("prepared", "failed")]
    if not todo:
        print("Nothing to submit (run prepare first)")
        return

    total = 0.0
    for name, c in todo:
        cost = estimated_cost(c["model"], c["n_requests"])
        total += cost
        print(f"  {name}: {c['n_requests']} requests, est ${cost:.2f}")
    print(f"Estimated batch cost: ${total:.2f}")
    if not yes and input("Submit? [y/N] ").strip().lower() != "y":
        print("Cancelled")
        return

    for name, _ in todo:
        submit_chunk(client, state, name)


def submit_chunk(client, state, name):
    c = state["chunks"][name]
    if not c.get("input_file_id"):
        with open(c["path"], "rb") as f:
            c["input_file_id"] = client.files.create(file=f, purpose="batch").id
    batch = client.batches.create(
        input_file_id=c["input_file_id"],
        endpoint="/v1/responses",
        completion_window="24h",
        metadata={"chunk": name},
    )
    c.update({"batch_id": batch.id, "status": batch.status, "errors": None,
              "attempts": c.get("attempts", 0) + 1})
    save_state(state)
    print(f"  submitted {name}: {batch.id} ({batch.status})", flush=True)


def run(client, yes=False, poll_s=300):
    """Keep one chunk per model in the queue; collect each as it finishes."""
    state = load_state()
    n = sum(c["n_requests"] for c in state["chunks"].values() if c["status"] != "collected")
    est = sum(estimated_cost(c["model"], c["n_requests"]) for c in state["chunks"].values()
              if c["status"] != "collected")
    print(f"{n} requests to run, estimated batch cost ${est:.2f}", flush=True)
    if not yes and input("Start? [y/N] ").strip().lower() != "y":
        print("Cancelled")
        return
    while True:
        collect(client)
        state = load_state()
        chunks = state["chunks"]
        for model_name in GPT_MODELS:
            mine = {k: c for k, c in chunks.items() if c["model"] == model_name}
            if any(c["status"] in LIVE for c in mine.values()):
                continue
            nxt = [k for k, c in sorted(mine.items())
                   if c["status"] in ("prepared", "failed") and c.get("attempts", 0) < MAX_SUBMIT_ATTEMPTS]
            if nxt:
                submit_chunk(client, state, nxt[0])
        summary = {}
        for c in chunks.values():
            summary[c["status"]] = summary.get(c["status"], 0) + 1
        spent = sum(c.get("cost", 0) for c in chunks.values())
        print(f"[run] chunks: {summary} | collected cost ${spent:.2f}", flush=True)
        if all(c["status"] == "collected" or
               (c["status"] == "failed" and c.get("attempts", 0) >= MAX_SUBMIT_ATTEMPTS)
               for c in chunks.values()):
            print("[run] DONE", flush=True)
            return
        time.sleep(poll_s)


def refresh(client, state):
    for c in state["chunks"].values():
        if c.get("batch_id") and c["status"] not in ("collected",):
            batch = client.batches.retrieve(c["batch_id"])
            c["status"] = batch.status
            c["output_file_id"] = batch.output_file_id
            c["error_file_id"] = batch.error_file_id
            counts = batch.request_counts
            c["counts"] = {"completed": counts.completed, "failed": counts.failed, "total": counts.total} if counts else None
            if batch.errors and batch.errors.data:
                c["errors"] = [e.message for e in batch.errors.data]
    save_state(state)


def status(client):
    state = load_state()
    refresh(client, state)
    for name, c in state["chunks"].items():
        line = f"{name}: {c['status']}"
        if c.get("counts"):
            line += f" | {c['counts']['completed']}/{c['counts']['total']} done, {c['counts']['failed']} failed"
        if c.get("errors"):
            line += f" | errors: {c['errors']}"
        print(line)


def response_text(body):
    """Concatenated output_text parts of a Responses API body (= response.output_text)."""
    parts = []
    for item in body.get("output", []):
        if item.get("type") == "message":
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    parts.append(content["text"])
    return "".join(parts)


def usage_with_cost(model_name, u):
    in_price, out_price = OPENAI_BATCH_PRICES[model_name]
    prompt_tokens = u.get("input_tokens") or 0
    completion_tokens = u.get("output_tokens") or 0
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": u.get("total_tokens"),
        "reasoning_tokens": (u.get("output_tokens_details") or {}).get("reasoning_tokens"),
        "cost": round((prompt_tokens * in_price + completion_tokens * out_price) / 1e6, 6),
    }


def write_row(custom_id, response, usage=None):
    model_name, label, sample_id = custom_id.split("|")
    prompt_type, identity_key = None, None
    for pt, identity in prompt_identity_pairs():
        if prompt_identity_label(pt, identity) == label:
            prompt_type, identity_key = pt, (identity["key"] if identity else None)
    row = {
        "sample_id": sample_id,
        "model": model_name,
        "prompt_type": prompt_type,
        "identity": identity_key,
        "fairness_definition": FAIRNESS_DEFINITION,
        "response": response,
    }
    if usage is not None:
        row["usage"] = usage
    with open(output_file_for(model_name, label), "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def collect(client):
    state = load_state()
    refresh(client, state)
    for name, c in state["chunks"].items():
        if c["status"] not in ("completed", "expired", "cancelled"):
            continue
        n_ok = n_err = 0
        cost = 0.0
        seen = set()
        for file_id in (c.get("output_file_id"), c.get("error_file_id")):
            if not file_id:
                continue
            for line in client.files.content(file_id).text.splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                custom_id = item["custom_id"]
                seen.add(custom_id)
                resp = item.get("response") or {}
                body = resp.get("body") or {}
                if item.get("error") or resp.get("status_code") != 200:
                    error = item.get("error") or body.get("error") or f"status {resp.get('status_code')}"
                    write_row(custom_id, {"error": str(error)})
                    n_err += 1
                    continue
                usage = usage_with_cost(c["model"], body.get("usage") or {})
                cost += usage["cost"]
                write_row(custom_id, parse_json_response(response_text(body).strip()), usage)
                n_ok += 1
        # requests with no output line at all (expired/cancelled batches) -> error rows
        with open(c["path"], encoding="utf-8") as f:
            for line in f:
                custom_id = json.loads(line)["custom_id"]
                if custom_id not in seen:
                    write_row(custom_id, {"error": f"no result (batch {c['status']})"})
                    n_err += 1
        c["status"] = "collected"
        c["cost"] = round(cost, 4)
        save_state(state)
        print(f"[collect] {name}: {n_ok} rows written, {n_err} errors, cost ${cost:.2f}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "submit", "status", "collect", "run"])
    parser.add_argument("--yes", action="store_true", help="submit without asking")
    args = parser.parse_args()

    load_dotenv()
    if args.command == "prepare":
        prepare()
    else:
        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY is not set")
        client = OpenAI()
        {"submit": lambda: submit(client, args.yes), "status": lambda: status(client),
         "collect": lambda: collect(client), "run": lambda: run(client, args.yes)}[args.command]()
