import os

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SRC_DIR)


PATH_TO_DATA = os.path.join(ROOT_DIR, "data", "gather_data") + os.sep
PATH_TO_SAMPLES = os.path.join(ROOT_DIR, "data", "gather_data", "samples") + os.sep
PATH_TO_MODEL_RESULTS = os.path.join(ROOT_DIR, "data", "call_models") + os.sep
PATH_TO_RESULTS = os.path.join(ROOT_DIR, "results", "analyze_results") + os.sep
PATH_TO_GROUND_TRUTH = os.path.join(ROOT_DIR, "results", "ground_truth") + os.sep

N_SAMPLES = 10  # samples per model/prompt setup; scale down via cost estimate
SAMPLE_SIZE = 2000  # rows (X) per sample; see results/ground_truth/calibration
SAMPLE_SEED = 42  # base RNG seed; sample i uses SAMPLE_SEED + i

STRATIFY_BY = "race"
STRATA_ALLOCATION = "proportional"  # sample race mix = population race mix

USE_SUMMARY = False  # True: embed per-sample summary.txt in prompts.
# False: embed the sample's raw CSV rows instead.

GPT_MODELS = [
    "gpt-5-nano",
    "gpt-4o-mini",
]  # gpt-3.5-turbo swapped for gpt-5-nano: its 16K context can't fit raw-mode prompts (~82K tokens/call)

CLAUDE_MODELS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-5-20250929",
]  # claude-sonnet-4-20250514 gives non json responses

GEMINI_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-pro-preview",
]  # gemini-2.5-flash-lite / gemini-2.5-pro retired for new users; API pointed to these replacements

QWEN_MODELS = [
    "qwen2.5-7b-instruct",  # swapped for qwen3-8b: 128K native context vs qwen3-8b's 32K (needs YaRN to reach raw-mode's ~82K tokens/call)
    #    "qwen3-8b",
]

LLAMA_MODELS = [
    "llama-3.1-8b-instruct",
    "llama-3.2-3b-instruct",
]

GEMMA_MODELS = [
    #    "gemma-2-9b-it",  # dropped: hard 8,192-token context limit, cannot fit raw-mode prompts (~82K tokens/call) at any server setting
    "gemma-3-12b-it",
]

# All models served locally with vLLM (see call_models/call_qwen.py)
LOCAL_MODELS = QWEN_MODELS + LLAMA_MODELS + GEMMA_MODELS

# prompt_jobs_config.py
PROMPT_TYPES = [
    "control_prompt",
    "emotional_identity_prompt",
    "emotional_prompt",
    "identity_prompt",
]

FAIRNESS_DEFINITION = "none"  # "none" | "DI" | "DP" | "LR"
assert FAIRNESS_DEFINITION in ("none", "DI", "DP", "LR"), FAIRNESS_DEFINITION

IDENTITY_PROMPT_TYPES = [
    "emotional_identity_prompt",
    "identity_prompt",
]

IDENTITY_RACES = [
    "White",
    "Black or African American",
    "Hispanic or Latino",
    "Asian",
    # "Other",  # must match the cleaned data's label exactly
]
IDENTITY_SEXES = ["Female", "Male"]

_RACE_KEYS = {
    "White": "white",
    "Black or African American": "black",
    "Hispanic or Latino": "hispanic",
    "Asian": "asian",
    "Other": "other",
}
_SEX_KEYS = {"Female": "female", "Male": "male"}


def make_identity(race, sex):
    return {
        "key": f"{_RACE_KEYS[race]}_{_SEX_KEYS[sex]}",
        "race": race,
        "sex": sex,
    }


IDENTITIES = [
    make_identity(race, sex) for race in IDENTITY_RACES for sex in IDENTITY_SEXES
]

SELECTED_IDENTITIES = []


def all_known_identities():
    """IDENTITIES plus any SELECTED_IDENTITIES entries not already in it
    (e.g. a race outside IDENTITY_RACES). Downstream analysis scripts use
    this — not IDENTITIES directly — to look up an identity's race/sex from
    its key, so a SELECTED_IDENTITIES run with such an identity still
    resolves correctly."""
    seen = {identity["key"] for identity in IDENTITIES}
    extra = [
        identity for identity in SELECTED_IDENTITIES if identity["key"] not in seen
    ]
    return IDENTITIES + extra


def prompt_identity_pairs(prompt_types=None):
    """(prompt_type, identity) pairs to run: one pair per selected identity
    for prompt types in IDENTITY_PROMPT_TYPES, else a single (prompt_type,
    None) pair. Callers loop this instead of PROMPT_TYPES directly so the
    identity axis is expanded consistently everywhere. Uses SELECTED_IDENTITIES
    when non-empty, else every identity in IDENTITIES."""
    if prompt_types is None:
        prompt_types = PROMPT_TYPES
    identities = SELECTED_IDENTITIES or IDENTITIES
    pairs = []
    for prompt_type in prompt_types:
        if prompt_type in IDENTITY_PROMPT_TYPES:
            pairs.extend((prompt_type, identity) for identity in identities)
        else:
            pairs.append((prompt_type, None))
    return pairs


def prompt_identity_label(prompt_type, identity):
    """Filename/log label for a (prompt_type, identity) pair, prefixed with
    the fairness definition unless it is "none" (e.g. di_identity_prompt_asian_female).
    The prefix goes in front so a "none" label is never a prefix of a DI/DP/LR one."""
    label = f"{prompt_type}_{identity['key']}" if identity else prompt_type
    if FAIRNESS_DEFINITION != "none":
        label = f"{FAIRNESS_DEFINITION.lower()}_{label}"
    return label
