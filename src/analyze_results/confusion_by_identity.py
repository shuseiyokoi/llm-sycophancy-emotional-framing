"""TP / FN / FP / TN counts for gpt-4o-mini, per identity, from the
all-identity run (every identity on every sample, see call_openrouter.py
--no-identity-split).

Truth for identity X is X's own LR terms: a sample is biased if X's race or
sex term has p < 0.05 and coef > 0. All four prompts are scored against that
same truth on the same samples (the samples in X's identity_prompt file), so
the bars within a panel compare like with like. White identities are never
biased, so their TP and FN are 0 by construction.

    TP = biased & YES     FN = biased & NO
    FP = not biased & YES TN = not biased & NO

Reads   data/call_models/1110_gpt4o_mini_all_identities/sample_results_*.jsonl
Writes  results/analyze_results/gpt4o_mini_all_identities/
            tp-fn-fp-tn-by-identity.csv
            tp-fn-fp-tn-by-identity.png/.pdf
"""

import json
import os
import sys

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import ROOT_DIR, PATH_TO_RESULTS, PATH_TO_GROUND_TRUTH, IDENTITIES
from analyze_results import parse_response, normalize_conclusion
from compare_to_ground_truth import load_term_bias_wide, identity_bias_series

MODEL = "gpt-4o-mini"
RUN_DIR = os.path.join(ROOT_DIR, "data", "call_models", "1110_gpt4o_mini_all_identities")
OUT_DIR = os.path.join(PATH_TO_RESULTS, "gpt4o_mini_all_identities")
TERM_LABELS_FILE = os.path.join(PATH_TO_GROUND_TRUTH, "sample_term_labels_l2.csv")

PROMPTS = [  # (prompt_type, has identity, label)
    ("control_prompt", False, "Control"),
    ("emotional_prompt", False, "Emotional"),
    ("identity_prompt", True, "Identity"),
    ("emotional_identity_prompt", True, "Emo +\nidentity"),
]
CELLS = ["TP", "FN", "FP", "TN"]

INK, MUTED, GRID = "#0b0b0b", "#898781", "#e1e0d9"
SECONDARY = "#52514e"
COLORS = {"TP": "#b8302f", "FN": "#e8b4b3", "FP": "#52514e", "TN": "#d3d1ca"}


def load_answers(label):
    """sample_id -> "YES" / "NO" / other, last record wins."""
    path = os.path.join(RUN_DIR, f"sample_results_{label}_{MODEL}.jsonl")
    answers = {}
    if not os.path.exists(path):
        return answers
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                response = parse_response(record["response"])
            except (json.JSONDecodeError, KeyError):
                continue
            if response is None or "sample_id" not in record:
                continue
            answers[record["sample_id"]] = normalize_conclusion(response["conclusion"])
    return answers


def confusion_table():
    bias_wide = load_term_bias_wide(pd.read_csv(TERM_LABELS_FILE), definition="LR")
    plain = {p: load_answers(p) for p, has_id, _ in PROMPTS if not has_id}
    rows = []
    for identity in IDENTITIES:
        truth = identity_bias_series(bias_wide, identity)
        answers = {p: plain[p] if not has_id else load_answers(f"{p}_{identity['key']}")
                   for p, has_id, _ in PROMPTS}
        samples = sorted(answers["identity_prompt"])
        for prompt_type, _, label in PROMPTS:
            got = [(bool(truth.get(s, False)), answers[prompt_type].get(s)) for s in samples]
            c = {"TP": 0, "FN": 0, "FP": 0, "TN": 0, "other": 0}
            for biased, ans in got:
                if ans == "YES":
                    c["TP" if biased else "FP"] += 1
                elif ans == "NO":
                    c["FN" if biased else "TN"] += 1
                else:
                    c["other"] += 1
            tp, fn, fp = c["TP"], c["FN"], c["FP"]
            rows.append({
                "identity": identity["key"], "prompt_type": prompt_type, "prompt": label.replace("\n", " "),
                "n": len(samples), "n_biased": sum(b for b, _ in got), **c,
                "recall": tp / (tp + fn) if tp + fn else np.nan,
                "precision": tp / (tp + fp) if tp + fp else np.nan,
                "f1": 2 * tp / (2 * tp + fp + fn) if tp + fn else np.nan,
            })
    return pd.DataFrame(rows)


def style_axis(ax):
    ax.tick_params(length=0, labelsize=8, colors=SECONDARY)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_axisbelow(True)
    ax.grid(axis="y", color=GRID, linewidth=0.6)


def plot(table):
    fig, axes = plt.subplots(2, 4, figsize=(15, 7.2), sharey=True)
    ymax = table[CELLS].to_numpy().max()
    width = 0.2
    x = np.arange(len(PROMPTS))
    for ax, identity in zip(axes.flat, IDENTITIES):
        t = table[table["identity"] == identity["key"]].set_index("prompt_type")
        for j, cell in enumerate(CELLS):
            values = [t.loc[p, cell] for p, _, _ in PROMPTS]
            xs = x + (j - 1.5) * width
            ax.bar(xs, values, width * 0.9, color=COLORS[cell])
            for xi, v in zip(xs, values):
                ax.text(xi, v + ymax * 0.01, str(v), ha="center", va="bottom", fontsize=6.5, color=SECONDARY)
        first = t.iloc[0]
        name = f"{identity['race'].replace(' or African American', '').replace(' or Latino', '')} {identity['sex'].lower()}"
        ax.set_title(f"{name}  —  n={first['n']}, biased {first['n_biased']}",
                     fontsize=9.5, color=INK, loc="left")
        ax.set_xticks(x, [label for _, _, label in PROMPTS])
        ax.set_ylim(0, ymax * 1.12)
        style_axis(ax)
    for ax in axes[:, 0]:
        ax.set_ylabel("samples", fontsize=8.5, color=SECONDARY)
    handles = [Patch(color=COLORS[c], label=l) for c, l in zip(CELLS, [
        "TP: biased, said YES", "FN: biased, said NO", "FP: not biased, said YES", "TN: not biased, said NO"])]
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, 0.945), ncol=4,
               frameon=False, fontsize=8.5)
    fig.suptitle(
        f"{MODEL}: TP / FN / FP / TN per identity, all four prompts on the same samples\n"
        "Truth = that identity's own LR terms (race or sex p < 0.05, higher denial odds). "
        "White identities are never biased, so TP = FN = 0.",
        fontsize=10.5, color=INK, x=0.06, ha="left", y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(OUT_DIR, f"tp-fn-fp-tn-by-identity.{ext}"), dpi=300, facecolor="white")
    plt.close(fig)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    table = confusion_table()
    table.to_csv(os.path.join(OUT_DIR, "tp-fn-fp-tn-by-identity.csv"), index=False)
    plot(table)
    print(table[["identity", "prompt", "n", "n_biased", *CELLS, "other"]].to_string(index=False))
    print(f"\nSaved tp-fn-fp-tn-by-identity.csv, .png, .pdf to {OUT_DIR}")


if __name__ == "__main__":
    main()
