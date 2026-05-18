from dotenv import load_dotenv
import os
from openai import OpenAI
import json

from config import (
    PATH_TO_DATA,
    GPT_MODEL,
    NUM_ITERATIONS,
)

from prompts import (
    CONTROL_PROMPT,
    EMOTIONAL_IDENTITY_PROMPT,
    EMOTIONAL_PROMPT,
    IDENTITY_PROMPT,
)


def clean_json_response(raw_text):
    raw_text = raw_text.strip()

    if raw_text.startswith("```json"):
        raw_text = raw_text[len("```json") :].strip()

    if raw_text.startswith("```"):
        raw_text = raw_text[len("```") :].strip()

    if raw_text.endswith("```"):
        raw_text = raw_text[:-3].strip()

    return raw_text


def run_prompt(client, file_id, prompt_text, output_filename):
    for i in range(NUM_ITERATIONS):
        response = client.responses.create(
            model=GPT_MODEL,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_file",
                            "file_id": file_id,
                        },
                        {
                            "type": "input_text",
                            "text": prompt_text,
                        },
                    ],
                }
            ],
        )

        raw_text = clean_json_response(response.output_text)

        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            parsed = {
                "error": "JSONDecodeError",
                "raw_response": raw_text,
            }

        result = {
            "run": i + 1,
            "model": GPT_MODEL,
            "response": parsed,
        }

        with open(
            f"{PATH_TO_DATA}/{output_filename}",
            "a",
            encoding="utf-8",
        ) as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")

        print(f"{output_filename} | Run {i + 1}: {parsed}")


def call_chatGPT():
    load_dotenv()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set")

    client = OpenAI(api_key=api_key)

    file = client.files.create(
        file=open(f"{PATH_TO_DATA}/summary.txt", "rb"),
        purpose="user_data",
    )

    prompt_jobs = {
        "control_prompt": {
            "prompt": CONTROL_PROMPT,
            "output": "results_control_prompt_ChatGPT.jsonl",
        },
        "emotional_prompt": {
            "prompt": EMOTIONAL_PROMPT,
            "output": "results_emotional_prompt_ChatGPT.jsonl",
        },
        "identity_prompt": {
            "prompt": IDENTITY_PROMPT,
            "output": "results_identity_prompt_ChatGPT.jsonl",
        },
        "emotional_identity_prompt": {
            "prompt": EMOTIONAL_IDENTITY_PROMPT,
            "output": "results_emotional_identity_prompt_ChatGPT.jsonl",
        },
    }

    for prompt_name, job in prompt_jobs.items():
        print(f"\nStarting: {prompt_name}")

        run_prompt(
            client=client,
            file_id=file.id,
            prompt_text=job["prompt"],
            output_filename=job["output"],
        )

        print(f"Finished: {prompt_name}")


if __name__ == "__main__":
    call_chatGPT()
