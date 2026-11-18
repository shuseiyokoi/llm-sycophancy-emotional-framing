"""YES / NO share per model, by prompt, with a ground-truth row on top of each
panel (the same layout as yes-no-percent-by-prompt from all_models_by_prompt.py,
which this script leaves untouched).

Ground truth (LR, L2 labels; the same as compare_to_ground_truth.py):
  Control, Emotional          share of the 300 samples with bias_any
                              (any race or sex term significant and adverse)
  Identity, Emotional + id.   share of samples where the asked-about identity's
                              own race or sex term is biased, pooled over the
                              8 identity slices (White identities are never biased)

Outputs to results/analyze_results/all_models/:
    yes-no-vs-gt-by-prompt.csv                model x prompt table plus "Ground truth" rows
    yes-no-percent-vs-gt-by-prompt.png/.pdf   100% bars with the GT row on top
"""

import os
import sys

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import PATH_TO_GROUND_TRUTH, IDENTITIES, IDENTITY_PROMPT_TYPES, identity_sample_ids
from analyze_results import discover_models, load_results
from compare_to_ground_truth import load_term_bias_wide, identity_bias_series
from all_models_by_prompt import (
    OUT_DIR, PROMPTS, INK, MUTED, GRID, YES_COLOR, NO_COLOR,
    yes_no_table, model_order, style_axis,
)

GT_COLOR = "#3d3c39"
GT_LABEL = "Ground truth"
LABELS_FILE = os.path.join(PATH_TO_GROUND_TRUTH, "sample_labels_l2.csv")
TERM_LABELS_FILE = os.path.join(PATH_TO_GROUND_TRUTH, "sample_term_labels_l2.csv")


def gt_table():
    """One row per prompt: n samples, n biased, % biased."""
    labels = pd.read_csv(LABELS_FILE)
    bias_wide = load_term_bias_wide(pd.read_csv(TERM_LABELS_FILE), definition="LR")
    sample_ids = labels["sample_id"].tolist()

    n_any = int(labels["bias_any"].sum())
    per_identity = []  # (identity key, biased, slice size)
    for identity in IDENTITIES:
        truth = identity_bias_series(bias_wide, identity)
        slice_ids = identity_sample_ids(sample_ids, identity)
        per_identity.append((identity["key"], int(truth.reindex(slice_ids).fillna(False).astype(bool).sum()),
                             len(slice_ids)))
    n_identity = sum(b for _, b, _ in per_identity)
    n_identity_samples = sum(n for _, _, n in per_identity)

    rows = []
    for prompt_type, _ in PROMPTS:
        if prompt_type in IDENTITY_PROMPT_TYPES:
            n, n_yes = n_identity_samples, n_identity
        else:
            n, n_yes = len(sample_ids), n_any
        rows.append({
            "model": GT_LABEL, "prompt_type": prompt_type, "n": n,
            "n_yes": n_yes, "n_no": n - n_yes, "n_other": 0,
            "yes_pct": 100 * n_yes / n, "no_pct": 100 * (n - n_yes) / n,
        })
    return pd.DataFrame(rows), per_identity


def footnote(gt, per_identity):
    """Why the ground truth is 45% in Control / Emotional but 14% in the identity panels."""
    g = gt.set_index("prompt_type")
    any_row, id_row = g.loc["control_prompt"], g.loc["identity_prompt"]
    breakdown = ", ".join(f"{key.replace('_', ' ')} {b}/{n}" for key, b, n in per_identity)
    return (
        f"Why ground truth is {any_row['yes_pct']:.0f}% in Control / Emotional but {id_row['yes_pct']:.0f}% "
        "in the identity panels (same 300 samples, different question):\n"
        f"  Control / Emotional ask about discrimination in general, so a sample counts if ANY group's term is biased "
        f"({any_row['n_yes']}/{any_row['n']}; mostly race: Black, Hispanic, Asian, Other; sex is almost never biased).\n"
        "  Identity prompts ask about one identity on its own 37-38 samples, so a sample counts only if THAT "
        "identity's race or sex term is biased. White male is the reference group (never biased); White female can only\n"
        "  be biased via the Female term (1/300 samples overall), and a Black-only bias does not count for an Asian "
        f"applicant. Per identity: {breakdown} = {id_row['n_yes']}/{id_row['n']}."
    )


def plot(table, gt, models, note):
    rows = [GT_LABEL] + models
    y = np.arange(len(rows))
    fig, axes = plt.subplots(1, len(PROMPTS), figsize=(16, 0.42 * len(rows) + 3), sharey=True)
    for ax, (prompt_type, title) in zip(axes, PROMPTS):
        t = table[table["prompt_type"] == prompt_type].set_index("model").reindex(models)
        g = gt[gt["prompt_type"] == prompt_type].iloc[0]
        ax.set_title(title, fontsize=10, color=INK, loc="left")
        style_axis(ax)

        yes = np.concatenate([[g["yes_pct"]], t["yes_pct"].fillna(0).to_numpy()])
        no = np.concatenate([[g["no_pct"]], t["no_pct"].fillna(0).to_numpy()])
        n = np.concatenate([[g["n"]], t["n"].fillna(0).to_numpy()])
        colors = [GT_COLOR] + [YES_COLOR] * len(models)
        ax.barh(y, yes, 0.7, color=colors)
        ax.barh(y, no, 0.7, left=yes, color=NO_COLOR)

        ax.axvline(g["yes_pct"], ymin=0, ymax=1, color=GT_COLOR, linewidth=0.8,
                   linestyle=(0, (3, 3)), alpha=0.55, zorder=3)
        ax.axhline(0.5, color=MUTED, linewidth=0.8)

        for yi, v, ni in zip(y, yes, n):
            inside = v >= 12
            ax.text(v - 1.5 if inside else v + 1.5, yi, f"{v:.0f}%", va="center",
                    ha="right" if inside else "left", fontsize=7,
                    color="white" if inside else INK, fontweight="bold" if yi == 0 else "normal")
            ax.text(101, yi, f"n={int(ni)}", va="center", fontsize=6.5, color=MUTED)
        ax.set_xlim(0, 112)
        ax.set_xticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])

    axes[0].set_yticks(y, rows, fontsize=8.5, color=INK)
    axes[0].get_yticklabels()[0].set_fontweight("bold")
    axes[0].invert_yaxis()
    fig.legend(handles=[Patch(color=GT_COLOR, label="Ground truth: biased"),
                        Patch(color=YES_COLOR, label="YES (says discrimination)"),
                        Patch(color=NO_COLOR, label="NO / not biased")],
               loc="upper center", bbox_to_anchor=(0.5, 0.955), ncol=3, frameon=False, fontsize=8.5)
    fig.suptitle(
        "Share of YES per model vs ground-truth bias rate, by prompt (dashed line = ground truth)\n"
        "Ground truth: Control / Emotional = any race or sex term biased; "
        "Identity prompts = the asked-about identity's own term biased (pooled over identities)",
        fontsize=10.5, color=INK, x=0.01, ha="left", y=0.995)
    fig.text(0.01, 0.005, note, fontsize=7.5, color=MUTED, ha="left", va="bottom", linespacing=1.5)
    fig.tight_layout(rect=(0, 0.075, 1, 0.93))
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(OUT_DIR, f"yes-no-percent-vs-gt-by-prompt.{ext}"), dpi=300, facecolor="white")
    plt.close(fig)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    table = yes_no_table(load_results(discover_models()))
    gt, per_identity = gt_table()
    models = model_order(table)
    pd.concat([gt, table]).to_csv(os.path.join(OUT_DIR, "yes-no-vs-gt-by-prompt.csv"), index=False)
    note = footnote(gt, per_identity)
    plot(table, gt, models, note)
    print(note)
    print(gt[["prompt_type", "n", "n_yes", "yes_pct"]].round(1).to_string(index=False))
    print(f"\nSaved yes-no-vs-gt-by-prompt.csv, yes-no-percent-vs-gt-by-prompt.png/.pdf to {OUT_DIR}")


if __name__ == "__main__":
    main()
