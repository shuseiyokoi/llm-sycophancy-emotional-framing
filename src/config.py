PATH_TO_DATA = "../data/"
PATH_TO_RESULTS = "../results/"
NUM_ITERATIONS = 300

GPT_MODELS = ["gpt-3.5-turbo", "gpt-4o-mini"]

CLAUDE_MODELS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-5-20250929",
]  # claude-sonnet-4-20250514 gives non json responses
GEMINI_MODELS = ["gemini-2.5-flash-lite", "gemini-2.5-pro"]

QWEN_MODELS = [
    "qwen2.5-7b-instruct",
    "qwen3-8b",
]

LLAMA_MODELS = [
    "llama-3.1-8b-instruct",
    "llama-3.2-3b-instruct",
]

GEMMA_MODELS = [
    "gemma-2-9b-it",
    "gemma-3-12b-it",
]

# All models served locally with llama.cpp (see call_qwen.py / local_qwen)
LOCAL_MODELS = QWEN_MODELS + LLAMA_MODELS + GEMMA_MODELS

# prompt_jobs_config.py

PROMPT_TYPES = [
    "control_prompt",
    "emotional_identity_prompt",
    "emotional_prompt",
    "emotional_extreme_prompt",
    "emotional_suicidal_prompt",
    "identity_prompt",
    "identity_hypothetical_prompt",
]
