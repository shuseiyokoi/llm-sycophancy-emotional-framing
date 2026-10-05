"""
Shared loop for the per-sample design: one API call per (model, prompt, sample).

Each provider script supplies a `send_fn(prompt_text) -> raw response text`;
this module handles sample iteration, JSON parsing, resume, and output rows.

Output rows (jsonl): {"sample_id", "model", "prompt_type", "response"}.
"""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from prompts import list_sample_ids, get_sample_prompt


def parse_json_response(raw_text):
    raw_text = raw_text.strip()

    if raw_text.startswith("```json"):
        raw_text = raw_text[len("```json") :].strip()
    elif raw_text.startswith("```"):
        raw_text = raw_text[3:].strip()

    if raw_text.endswith("```"):
        raw_text = raw_text[:-3].strip()

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        # some models append prose after the JSON object;
        # fall back to parsing the first JSON object in the text
        try:
            start = raw_text.index("{")
            obj, _ = json.JSONDecoder().raw_decode(raw_text[start:])
            return obj
        except (ValueError, json.JSONDecodeError):
            return {"raw_text": raw_text}


def completed_sample_ids(output_file):
    """Sample ids already recorded in the output file (for resume)."""
    done = set()
    try:
        with open(output_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    done.add(json.loads(line)["sample_id"])
                except (json.JSONDecodeError, KeyError):
                    continue
    except FileNotFoundError:
        pass
    return done


def call_and_parse(send_fn, prompt_name, sample_id, identity):
    """One model call -> parsed response; errors are recorded, never raised."""
    try:
        raw_text = send_fn(get_sample_prompt(prompt_name, sample_id, identity))
        return parse_json_response(raw_text.strip())
    except Exception as e:
        return {"error": str(e)}


def run_sample_set(
    send_fn,
    model_name,
    prompt_name,
    output_file,
    sample_ids=None,
    sleep_s=1.0,
    identity=None,
    workers=1,
):
    """`identity` (an entry from config.IDENTITIES) is required when
    prompt_name is one of config.IDENTITY_PROMPT_TYPES; get_sample_prompt
    raises otherwise.

    workers > 1 sends that many requests concurrently (for a local vLLM
    server); rows are still written one at a time from this thread, in
    completion order, and `sleep_s` is ignored."""
    if sample_ids is None:
        sample_ids = list_sample_ids()

    label = f"{prompt_name} | {identity['key']}" if identity else prompt_name

    done = completed_sample_ids(output_file)
    pending = [s for s in sample_ids if s not in done]
    if done:
        print(f"{model_name} | {label}: resuming, {len(done)} samples already recorded")
    if not pending:
        print(f"{model_name} | {label}: all {len(sample_ids)} samples complete")
        return

    def record(sample_id, parsed_response):
        result = {
            "sample_id": sample_id,
            "model": model_name,
            "prompt_type": prompt_name,
            "identity": identity["key"] if identity else None,
            "response": parsed_response,
        }

        with open(output_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")

        print(f"{model_name} | {label} | {sample_id}: {parsed_response}")

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(call_and_parse, send_fn, prompt_name, s, identity): s
                for s in pending
            }
            for future in as_completed(futures):
                record(futures[future], future.result())
        return

    for sample_id in pending:
        record(sample_id, call_and_parse(send_fn, prompt_name, sample_id, identity))

        if sleep_s:
            time.sleep(sleep_s)
