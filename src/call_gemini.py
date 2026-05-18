from dotenv import load_dotenv
from google import genai
import json
import time

from config import PATH_TO_DATA, GEMINI_MODEL, NUM_ITERATIONS
from prompts import (
    get_control_prompt_embedded,
    get_emotional_prompt_embedded,
    get_identity_prompt_embedded,
    get_emotional_identity_prompt_embedded,
)


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
        start = raw_text.find("{")
        end = raw_text.rfind("}")

        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(raw_text[start : end + 1])
            except json.JSONDecodeError:
                return {"raw_text": raw_text}

        return {"raw_text": raw_text}


def run_prompt_set(client, prompt_text, output_file, prompt_name):
    for i in range(NUM_ITERATIONS):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt_text,
            )

            raw_text = response.text.strip()
            parsed_response = parse_json_response(raw_text)

            result = {
                "run": i + 1,
                "model": GEMINI_MODEL,
                "prompt_type": prompt_name,
                "response": parsed_response,
            }

        except Exception as e:
            result = {
                "run": i + 1,
                "model": GEMINI_MODEL,
                "prompt_type": prompt_name,
                "response": {"error": str(e)},
            }

        with open(output_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")

        print(f"{prompt_name} | Run {i + 1}: {result['response']}")

        time.sleep(1)


def call_gemini():
    load_dotenv()

    client = genai.Client()

    prompt_jobs = {
        "control_prompt": {
            "prompt": get_control_prompt_embedded(),
            "output": f"{PATH_TO_DATA}results_control_prompt_gemini.jsonl",
        },
        "emotional_prompt": {
            "prompt": get_emotional_prompt_embedded(),
            "output": f"{PATH_TO_DATA}results_emotional_prompt_gemini.jsonl",
        },
        "identity_prompt": {
            "prompt": get_identity_prompt_embedded(),
            "output": f"{PATH_TO_DATA}results_identity_prompt_gemini.jsonl",
        },
        "emotional_identity_prompt": {
            "prompt": get_emotional_identity_prompt_embedded(),
            "output": f"{PATH_TO_DATA}results_emotional_identity_prompt_gemini.jsonl",
        },
    }

    for prompt_name, job in prompt_jobs.items():
        print(f"\nStarting: {prompt_name}")

        run_prompt_set(
            client=client,
            prompt_text=job["prompt"],
            output_file=job["output"],
            prompt_name=prompt_name,
        )

        print(f"Finished: {prompt_name}")


if __name__ == "__main__":
    call_gemini()
