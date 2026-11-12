"""TP / FN / FP / TN counts for every model, one panel per prompt.

Truth is the same as ground_truth_plots.py: control / emotional prompts are
scored against bias_any, identity prompts against that identity's own terms
(identities pooled). Only YES / NO answers count.

    TP = biased & YES     FN = biased & NO
    FP = not biased & YES TN = not biased & NO

Bars are stacked FN | FP | TP | TN, errors first: FN solid red, FP solid dark
grey, correct answers in light greys, so the solid length is the error count.
Models are sorted by total mistakes (FN + FP over all four prompts), most on top.

--data-dir / --n-samples / --out-sub as in all_models_by_prompt.py.

Writes results/analyze_results/<out-sub>/
    tp-fn-fp-tn-by-prompt.csv
    tp-fn-fp-tn-by-prompt.png/.pdf
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import PATH_TO_RESULTS, PATH_TO_MODEL_RESULTS
from all_models_by_prompt import load_all, PROMPTS
from ground_truth_plots import attach_truth

CELLS = ["FN", "FP", "TP", "TN"]  # stacking order: errors first
# errors (FN, FP) are the solid colors; correct answers (TP, TN) stay in greys
COLORS = {"TP": "#bdbbb3", "FN": "#b8302f", "FP": "#52514e", "TN": "#e6e5df"}
TEXT_ON = {"TP": "#0b0b0b", "FN": "white", "FP": "white", "TN": "#0b0b0b"}
LABELS = ["FN: biased, said NO (missed bias)", "FP: not biased, said YES (false alarm)",
          "TP: biased, said YES (correct)", "TN: not biased, said NO (correct)"]
INK, MUTED, GRID, SECONDARY = "#0b0b0b", "#898781", "#e1e0d9", "#52514e"


def confusion(df):
    rows = []
    for (model, prompt_type), g in df.groupby(["model", "prompt_type"]):
        t, y = g["truth"], g["yes"]
        tp, fn = int((t & y).sum()), int((t & ~y).sum())
        fp, tn = int((~t & y).sum()), int((~t & ~y).sum())
        rows.append({
            "model": model, "prompt_type": prompt_type, "n": len(g), "n_biased": tp + fn,
            "TP": tp, "FN": fn, "FP": fp, "TN": tn,
            "recall": tp / (tp + fn) if tp + fn else np.nan,
            "precision": tp / (tp + fp) if tp + fp else np.nan,
            "f1": 2 * tp / (2 * tp + fp + fn) if tp + fn else np.nan,
        })
    return pd.DataFrame(rows)


def plot(table, out_dir):
    errors = (table["FN"] + table["FP"]).groupby(table["model"]).sum()
    models = errors.sort_values(ascending=False, kind="stable").index.tolist()
    y = np.arange(len(models))
    fig, axes = plt.subplots(1, len(PROMPTS), figsize=(16, 0.42 * len(models) + 2.2), sharey=True)
    for ax, (prompt_type, title) in zip(axes, PROMPTS):
        t = table[table["prompt_type"] == prompt_type].set_index("model").reindex(models).fillna(0)
        left = np.zeros(len(models))
        for cell in CELLS:
            v = t[cell].to_numpy()
            ax.barh(y, v, 0.72, left=left, color=COLORS[cell], edgecolor="white", linewidth=0.8)
            for yi, l, w in zip(y, left, v):
                if w >= 2:
                    ax.text(l + w / 2, yi, str(int(w)), ha="center", va="center",
                            fontsize=6.5, color=TEXT_ON[cell])
            left += v
        biased = int(t["n_biased"].max())
        ax.set_title(f"{title}  —  {biased} of {int(t['n'].max())} biased",
                     fontsize=10, color=INK, loc="left")
        ax.set_xlim(0, table["n"].max() * 1.02)
        ax.set_xlabel("samples", fontsize=8, color=SECONDARY)
        ax.tick_params(length=0, labelsize=8, colors=SECONDARY)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.set_axisbelow(True)
        ax.grid(axis="x", color=GRID, linewidth=0.6)
    axes[0].set_yticks(y, models, fontsize=8.5, color=INK)
    axes[0].invert_yaxis()
    fig.legend(handles=[Patch(color=COLORS[c], label=l) for c, l in zip(CELLS, LABELS)],
               loc="upper center", bbox_to_anchor=(0.5, 0.96), ncol=4, frameon=False, fontsize=8.5)
    fig.suptitle("Mistakes (FN + FP) per model, by prompt, most mistakes on top. Truth: control / emotional = any race or "
                 "sex term biased; identity prompts = that identity's own terms",
                 fontsize=10.5, color=INK, x=0.01, ha="left", y=0.99)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(out_dir, f"tp-fn-fp-tn-by-prompt.{ext}"), dpi=300, facecolor="white")
    plt.close(fig)
    return models


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", action="append", default=None)
    parser.add_argument("--n-samples", type=int, default=None)
    parser.add_argument("--out-sub", default="all_models")
    args = parser.parse_args()
    out_dir = os.path.join(PATH_TO_RESULTS, args.out_sub)
    os.makedirs(out_dir, exist_ok=True)
    df = attach_truth(load_all(args.data_dir or [PATH_TO_MODEL_RESULTS], args.n_samples))
    table = confusion(df)
    table.to_csv(os.path.join(out_dir, "tp-fn-fp-tn-by-prompt.csv"), index=False)
    models = plot(table, out_dir)
    wide = table.assign(cell=table[CELLS].astype(str).agg("/".join, axis=1))
    print("FN/FP/TP/TN")
    print(wide.pivot(index="model", columns="prompt_type", values="cell")
          .reindex(models)[[p for p, _ in PROMPTS]].to_string())
    print(f"\nSaved tp-fn-fp-tn-by-prompt.csv, .png, .pdf to {out_dir}")


if __name__ == "__main__":
    main()
