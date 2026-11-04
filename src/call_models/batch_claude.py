"""Claude through the Anthropic Message Batches API (half price, results usually within 1h, max 24h).

Same prompts as the other runners, one request per (model, prompt label, sample).
Results are written as normal sample_results_*.jsonl (or smoke_*.jsonl) rows,
plus a "usage" dict with cost computed from config.CLAUDE_BATCH_PRICES.

    python batch_claude.py submit --smoke   # SMOKE_N_PER_PROMPT request(s) per prompt label -> smoke_*.jsonl
    python batch_claude.py submit           # every sample not yet recorded -> sample_results_*.jsonl
    python batch_claude.py status           # processing status + request counts per batch
    python batch_claude.py collect --wait   # write finished batches' results (poll until all ended)

submit counts the tokens of one prompt first (free endpoint), prints the cost
estimate, and asks before sending. State (batch id -> request mapping) lives in
data/call_models/batches/claude_batches.json. Errored/expired requests are
written as {"error": ...} rows, which resume skips, so submitting again retries them.
"""

import argparse
import json
import os
import sys
import time

import anthropic
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import (
    PATH_TO_MODEL_RESULTS,
    CLAUDE_BATCH_PRICES,
    SMOKE_N_PER_PROMPT,
    FAIRNESS_DEFINITION,
    prompt_identity_pairs,
    prompt_identity_label,
    identity_sample_ids,
)
from prompts import list_sample_ids, get_sample_prompt
from sample_runner import completed_sample_ids, parse_json_response

BATCH_DIR = f"{PATH_TO_MODEL_RESULTS}batches{os.sep}"
STATE_FILE = f"{BATCH_DIR}claude_batches.json"
CHUNK_SIZE = 250  # ~300 KB per prompt -> ~75 MB per batch (API limit 256 MB)
MAX_TOKENS = 16000  # Haiku 5.5 thinks by default (except the -nothink variant), and thinking counts toward max_tokens
GUESS_OUTPUT_TOKENS = 2000  # for the pre-submit estimate only (thinking + JSON answer)

# result-file model name -> (API model id, extra request params)
MODEL_VARIANTS = {
    "claude-haiku-5-5-nothink": ("claude-haiku-5-5", {"thinking": {"type": "disabled"}}),
    "claude-haiku-5-5-thinking": ("claude-haiku-5-5", {"thinking": {"type": "adaptive", "display": "summarized"}}),
}

# reasoning summaries (thinking text) go here, one file per answer file, joinable on sample_id;
# only written when the API returns thinking text (display: "summarized")
REASONING_DIR = f"{PATH_TO_MODEL_RESULTS}reasoning{os.sep}"


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"batches": {}}


def save_state(state):
    os.makedirs(BATCH_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def prices(model_name, input_tokens):
    p = CLAUDE_BATCH_PRICES[model_name]
    return p["over"] if input_tokens >= p["threshold"] else p["under"]


def submit(client, models, smoke=False, yes=False):
    state = load_state()
    prefix = "smoke" if smoke else "sample_results"

    # requests already sent in a batch that hasn't been collected yet
    in_flight = set()
    for b in state["batches"].values():
        if b["status"] != "collected":
            in_flight.update(tuple(r) for r in b["requests"].values())

    all_ids = list_sample_ids()
    for model_name in models:
        todo = []  # (prefix, label, prompt_type, identity, sample_id)
        for prompt_type, identity in prompt_identity_pairs():
            label = prompt_identity_label(prompt_type, identity)
            done = completed_sample_ids(f"{PATH_TO_MODEL_RESULTS}{prefix}_{label}_{model_name}.jsonl")
            sample_ids = identity_sample_ids(all_ids, identity)
            if smoke:
                sample_ids = sample_ids[:SMOKE_N_PER_PROMPT]
            for sample_id in sample_ids:
                if sample_id not in done and (prefix, label, sample_id) not in in_flight:
                    todo.append((prefix, label, prompt_type, identity, sample_id))

        if not todo:
            print(f"{model_name}: nothing to submit")
            continue

        api_model, extra_params = MODEL_VARIANTS.get(model_name, (model_name, {}))

        # count one prompt's tokens (free) to pick the price tier before spending anything
        _, _, prompt_type, identity, sample_id = todo[0]
        n_in = client.messages.count_tokens(
            model=api_model,
            messages=[{"role": "user", "content": get_sample_prompt(prompt_type, sample_id, identity)}],
        ).input_tokens
        in_price, out_price = prices(model_name, n_in)
        est = len(todo) * (n_in * in_price + GUESS_OUTPUT_TOKENS * out_price) / 1e6
        threshold = CLAUDE_BATCH_PRICES[model_name]["threshold"]
        print(f"{model_name}: {len(todo)} requests | prompt ~{n_in:,} tokens "
              f"({'OVER' if n_in >= threshold else 'under'} the {threshold // 1000}K price tier) | est ${est:.2f}")
        if not yes and input("Submit? [y/N] ").strip().lower() != "y":
            print("Cancelled")
            continue

        for k in range(0, len(todo), CHUNK_SIZE):
            chunk = todo[k : k + CHUNK_SIZE]
            requests, mapping = [], {}
            for i, (pfx, label, prompt_type, identity, sample_id) in enumerate(chunk):
                custom_id = f"r{i:04d}"  # API allows only [a-zA-Z0-9_-]{1,64}
                mapping[custom_id] = [pfx, label, sample_id]
                requests.append({
                    "custom_id": custom_id,
                    "params": {
                        "model": api_model,
                        "max_tokens": MAX_TOKENS,
                        "messages": [{"role": "user", "content": get_sample_prompt(prompt_type, sample_id, identity)}],
                        **extra_params,
                    },
                })
            batch = client.messages.batches.create(requests=requests)
            state["batches"][batch.id] = {"model": model_name, "status": batch.processing_status,
                                          "requests": mapping}
            save_state(state)
            print(f"  submitted {batch.id}: {len(chunk)} requests ({batch.processing_status})", flush=True)


def refresh(client, state):
    for batch_id, b in state["batches"].items():
        if b["status"] != "collected":
            batch = client.messages.batches.retrieve(batch_id)
            b["status"] = batch.processing_status
            c = batch.request_counts
            b["counts"] = {"processing": c.processing, "succeeded": c.succeeded, "errored": c.errored,
                           "canceled": c.canceled, "expired": c.expired}
    save_state(state)


def status(client):
    state = load_state()
    refresh(client, state)
    for batch_id, b in state["batches"].items():
        print(f"{batch_id} ({b['model']}, {len(b['requests'])} requests): {b['status']} {b.get('counts', '')}")


def label_fields(label):
    for prompt_type, identity in prompt_identity_pairs():
        if prompt_identity_label(prompt_type, identity) == label:
            return prompt_type, (identity["key"] if identity else None)
    raise ValueError(f"unknown label {label}")


def write_row(model_name, prefix, label, sample_id, response, usage=None):
    prompt_type, identity_key = label_fields(label)
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
    with open(f"{PATH_TO_MODEL_RESULTS}{prefix}_{label}_{model_name}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_reasoning(model_name, prefix, label, sample_id, response, thinking):
    prompt_type, identity_key = label_fields(label)
    row = {
        "sample_id": sample_id,
        "model": model_name,
        "prompt_type": prompt_type,
        "identity": identity_key,
        "conclusion": response.get("conclusion"),
        "confidence": response.get("confidence"),
        "evidence": response.get("evidence"),
        "thinking": thinking,
    }
    os.makedirs(REASONING_DIR, exist_ok=True)
    with open(f"{REASONING_DIR}{prefix}_{label}_{model_name}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def collect(client):
    """Write rows for ended batches; returns True when every batch is collected."""
    state = load_state()
    refresh(client, state)
    for batch_id, b in state["batches"].items():
        if b["status"] != "ended":
            continue
        model_name = b["model"]
        n_ok = n_err = 0
        cost = 0.0
        for result in client.messages.batches.results(batch_id):
            prefix, label, sample_id = b["requests"][result.custom_id]
            if result.result.type != "succeeded":
                error = getattr(result.result, "error", None) or result.result.type
                write_row(model_name, prefix, label, sample_id, {"error": str(error)})
                n_err += 1
                continue
            msg = result.result.message
            u = msg.usage
            in_price, out_price = prices(model_name, u.input_tokens)
            usage = {
                "prompt_tokens": u.input_tokens,
                "completion_tokens": u.output_tokens,  # includes thinking tokens
                "total_tokens": u.input_tokens + u.output_tokens,
                "stop_reason": msg.stop_reason,
                "cost": round((u.input_tokens * in_price + u.output_tokens * out_price) / 1e6, 6),
            }
            cost += usage["cost"]
            if msg.stop_reason == "refusal":
                response = {"refusal": str(getattr(msg.stop_details, "category", None))}
            else:
                text = "".join(blk.text for blk in msg.content if blk.type == "text")
                response = parse_json_response(text.strip())
            write_row(model_name, prefix, label, sample_id, response, usage)
            thinking = "".join(blk.thinking for blk in msg.content if blk.type == "thinking")
            if thinking.strip():
                write_reasoning(model_name, prefix, label, sample_id, response, thinking)
            n_ok += 1
        b["status"] = "collected"
        b["cost"] = round(cost, 4)
        save_state(state)
        print(f"[collect] {batch_id}: {n_ok} rows written, {n_err} errors, cost ${cost:.4f}", flush=True)

    total = sum(b.get("cost", 0) for b in state["batches"].values())
    pending = [k for k, b in state["batches"].items() if b["status"] != "collected"]
    print(f"[collect] collected cost so far ${total:.4f} | batches still running: {len(pending)}", flush=True)
    return not pending


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["submit", "status", "collect"])
    parser.add_argument("--smoke", action="store_true", help="SMOKE_N_PER_PROMPT request(s) per prompt label")
    parser.add_argument("--models", nargs="+", default=list(CLAUDE_BATCH_PRICES), help="Claude model ids")
    parser.add_argument("--yes", action="store_true", help="submit without asking")
    parser.add_argument("--wait", action="store_true", help="collect: poll every 60s until all batches end")
    args = parser.parse_args()

    load_dotenv()
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise ValueError("ANTHROPIC_API_KEY is not set")
    client = anthropic.Anthropic()

    if args.command == "submit":
        submit(client, args.models, smoke=args.smoke, yes=args.yes)
    elif args.command == "status":
        status(client)
    else:
        while not collect(client) and args.wait:
            time.sleep(60)
