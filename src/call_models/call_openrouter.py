"""GPT / Gemini (and later Claude) through OpenRouter, with per-call cost tracking.

Each output row gets a "usage" dict (same token keys as call_qwen.py, plus
reasoning_tokens and cost in USD as billed by OpenRouter), so
analyze_results/token_report.py summarizes these runs too.

    python call_openrouter.py --smoke   # SMOKE_N_PER_PROMPT call(s) per prompt label -> smoke_*.jsonl
    python call_openrouter.py           # full run -> sample_results_*.jsonl
    python call_openrouter.py --models openai/gpt-5-nano --workers 8 --max-cost 10
                                        # full run for one model, 8 calls at a time, $10 cap

Prints each call's tokens and cost with running totals, and stops once the
run's billed cost passes OPENROUTER_MAX_COST_USD.
"""

import argparse
import os
import sys
import threading
import time

import requests
from dotenv import load_dotenv
from openai import OpenAI

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import (
    PATH_TO_MODEL_RESULTS,
    OPENROUTER_MODELS,
    SMOKE_N_PER_PROMPT,
    OPENROUTER_MAX_COST_USD,
    prompt_identity_pairs,
    prompt_identity_label,
)
from sample_runner import run_sample_set

BASE_URL = "https://openrouter.ai/api/v1"


class BudgetExceeded(BaseException):
    """BaseException so sample_runner's `except Exception` doesn't swallow it."""


def key_spend(api_key):
    """(usage USD so far, limit USD or None) for this API key."""
    r = requests.get(f"{BASE_URL}/key", headers={"Authorization": f"Bearer {api_key}"}, timeout=30)
    r.raise_for_status()
    data = r.json()["data"]
    return data.get("usage"), data.get("limit")


def call_openrouter(smoke=False, models=None, workers=1, max_cost=None):
    models = models or OPENROUTER_MODELS
    max_cost = OPENROUTER_MAX_COST_USD if max_cost is None else max_cost
    load_dotenv()

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is not set")

    os.makedirs(PATH_TO_MODEL_RESULTS, exist_ok=True)

    client = OpenAI(base_url=BASE_URL, api_key=api_key)

    spend_before, limit = key_spend(api_key)
    print(f"OpenRouter key: spent ${spend_before:.4f} so far, limit {limit}")
    print(f"Models: {models} | workers: {workers} | run budget: ${max_cost:.2f}")

    prefix = "smoke" if smoke else "sample_results"
    limit_n = SMOKE_N_PER_PROMPT if smoke else None
    totals = {"run": 0.0}
    lock = threading.Lock()

    try:
        for model_id in models:
            model_name = model_id.split("/", 1)[1].split(":")[0]  # ":batch" is billing, not a different model
            totals[model_name] = 0.0

            def send_fn(prompt_text):
                if totals["run"] >= max_cost:
                    raise BudgetExceeded(
                        f"run cost ${totals['run']:.4f} passed budget ${max_cost:.2f}"
                    )
                t0 = time.perf_counter()
                completion = client.chat.completions.create(
                    model=model_id,
                    messages=[{"role": "user", "content": prompt_text}],
                    extra_body={"usage": {"include": True}},
                )
                u = completion.usage.model_dump() if completion.usage else {}
                details = u.get("completion_tokens_details") or {}
                cost = u.get("cost") or 0.0
                usage = {
                    "prompt_tokens": u.get("prompt_tokens"),
                    "completion_tokens": u.get("completion_tokens"),
                    "total_tokens": u.get("total_tokens"),
                    "reasoning_tokens": details.get("reasoning_tokens"),
                    "cost": cost,
                    "latency_s": round(time.perf_counter() - t0, 3),
                }
                with lock:
                    totals[model_name] += cost
                    totals["run"] += cost
                    print(
                        f"  [cost] {model_name} | in={usage['prompt_tokens']:,} "
                        f"out={usage['completion_tokens']:,} (reasoning={usage['reasoning_tokens']}) "
                        f"| ${cost:.4f} | model total ${totals[model_name]:.4f} "
                        f"| run total ${totals['run']:.4f}"
                    )
                return completion.choices[0].message.content or "", usage

            for prompt_type, identity in prompt_identity_pairs():
                label = prompt_identity_label(prompt_type, identity)
                output_file = f"{PATH_TO_MODEL_RESULTS}{prefix}_{label}_{model_name}.jsonl"

                print(f"\nStarting: {model_name} | {label}")
                run_sample_set(
                    send_fn, model_name, prompt_type, output_file,
                    identity=identity, limit=limit_n,
                    sleep_s=0 if workers > 1 else 1.0, workers=workers,
                )
                print(f"Finished: {model_name} | {label}")

            print(f"\n[cost] {model_name} finished: ${totals[model_name]:.4f}")
    except BudgetExceeded as e:
        print(f"\n[cost] STOPPED: {e}")
    finally:
        print("\n[cost] Summary (summed usage.cost):")
        for name, cost in totals.items():
            if name != "run":
                print(f"  {name}: ${cost:.4f}")
        print(f"  run total: ${totals['run']:.4f}")
        spend_after, _ = key_spend(api_key)
        print(
            f"  key spend change: ${spend_after - spend_before:.4f} "
            "(OpenRouter's counter can lag by a minute or so)"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="SMOKE_N_PER_PROMPT call(s) per prompt label")
    parser.add_argument("--models", nargs="+", help="OpenRouter model ids (default: config.OPENROUTER_MODELS)")
    parser.add_argument("--workers", type=int, default=1, help="concurrent calls")
    parser.add_argument("--max-cost", type=float, help="run budget in USD (default: OPENROUTER_MAX_COST_USD)")
    args = parser.parse_args()
    call_openrouter(smoke=args.smoke, models=args.models, workers=args.workers, max_cost=args.max_cost)
