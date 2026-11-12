"""All models side by side, one panel per prompt: YES / NO answer counts and
the YES / NO share as 100% bars.

Identity prompts pool every identity (as in analyze_results.py). Models keep
the same row in every panel and both figures, sorted by mean YES rate over
the four prompts (highest on top).

--data-dir DIR (repeatable) reads result files from several folders, e.g. the
main runs plus data/call_models/1111_commercial_small. --n-samples N keeps only
the first N sample ids (sorted) for every model, so models run on all 300 and
models from a small run are compared on the same samples. --out-sub names the
output subfolder (default all_models).

Outputs to results/analyze_results/<out-sub>/:
    yes-no-by-prompt.csv              model x prompt: n, YES, NO, other, shares
    yes-no-counts-by-prompt.png/.pdf  YES and NO counts per model, per prompt
    yes-no-percent-by-prompt.png/.pdf YES / NO share (100% bars) per model, per prompt
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
from analyze_results import discover_models, load_results

OUT_DIR = os.path.join(PATH_TO_RESULTS, "all_models") + os.sep

PROMPTS = [  # (prompt_type, panel title)
    ("control_prompt", "Control"),
    ("emotional_prompt", "Emotional"),
    ("identity_prompt", "Identity"),
    ("emotional_identity_prompt", "Emotional + identity"),
]

INK, MUTED, GRID = "#0b0b0b", "#898781", "#e1e0d9"
SECONDARY = "#52514e"
YES_COLOR, NO_COLOR = "#b8302f", "#d3d1ca"


def yes_no_table(df):
    rows = []
    for (model, prompt_type), g in df.groupby(["model", "prompt_type"]):
        n_yes = int((g["conclusion"] == "YES").sum())
        n_no = int((g["conclusion"] == "NO").sum())
        rows.append({
            "model": model, "prompt_type": prompt_type, "n": len(g),
            "n_yes": n_yes, "n_no": n_no, "n_other": len(g) - n_yes - n_no,
            "yes_pct": 100 * n_yes / len(g), "no_pct": 100 * n_no / len(g),
        })
    return pd.DataFrame(rows)


def model_order(table):
    """Highest mean YES rate first."""
    return table.groupby("model")["yes_pct"].mean().sort_values(ascending=False).index.tolist()


def style_axis(ax):
    ax.tick_params(length=0, labelsize=8, colors=SECONDARY)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_axisbelow(True)
    ax.grid(axis="x", color=GRID, linewidth=0.6)


def panels(table, models):
    fig, axes = plt.subplots(1, len(PROMPTS), figsize=(16, 0.42 * len(models) + 2), sharey=True)
    y = np.arange(len(models))
    for ax, (prompt_type, title) in zip(axes, PROMPTS):
        t = table[table["prompt_type"] == prompt_type].set_index("model").reindex(models)
        ax.set_title(title, fontsize=10, color=INK, loc="left")
        style_axis(ax)
        yield ax, y, t
    axes[0].set_yticks(y, models, fontsize=8.5, color=INK)
    axes[0].invert_yaxis()
    fig.legend(handles=[Patch(color=YES_COLOR, label="YES (says discrimination)"),
                        Patch(color=NO_COLOR, label="NO")],
               loc="upper center", bbox_to_anchor=(0.5, 0.965), ncol=2, frameon=False, fontsize=8.5)
    panels.fig = fig


def save(fig, name, title):
    fig.suptitle(title, fontsize=11, color=INK, x=0.01, ha="left", y=0.99)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(OUT_DIR, f"{name}.{ext}"), dpi=300, facecolor="white")
    plt.close(fig)


def plot_counts(table, models):
    h = 0.38
    xmax = table["n"].max()
    for ax, y, t in panels(table, models):
        for offset, col, color in ((-h / 2, "n_yes", YES_COLOR), (h / 2, "n_no", NO_COLOR)):
            values = t[col].fillna(0).astype(int)
            ax.barh(y + offset, values, h * 0.92, color=color)
            for yi, v in zip(y + offset, values):
                ax.text(v + xmax * 0.01, yi, str(v), va="center", fontsize=6.5, color=SECONDARY)
        ax.set_xlim(0, xmax * 1.15)
        ax.set_xlabel("answers", fontsize=8, color=SECONDARY)
    save(panels.fig, "yes-no-counts-by-prompt",
         "YES and NO answers per model, by prompt (all models, same order in every panel)")


def plot_percent(table, models):
    for ax, y, t in panels(table, models):
        yes, no = t["yes_pct"].fillna(0), t["no_pct"].fillna(0)
        ax.barh(y, yes, 0.7, color=YES_COLOR)
        ax.barh(y, no, 0.7, left=yes, color=NO_COLOR)
        for yi, v, n in zip(y, yes, t["n"]):
            inside = v >= 12
            ax.text(v - 1.5 if inside else v + 1.5, yi, f"{v:.0f}%", va="center",
                    ha="right" if inside else "left", fontsize=7,
                    color="white" if inside else INK)
            ax.text(101, yi, f"n={int(n) if pd.notna(n) else 0}", va="center", fontsize=6.5, color=MUTED)
        ax.set_xlim(0, 112)
        ax.set_xticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
    save(panels.fig, "yes-no-percent-by-prompt",
         "Share of YES vs NO per model, by prompt (100% bars; label = YES %)")


def load_all(data_dirs, n_samples=None):
    """Rows from every folder; a model found in two folders keeps the first."""
    frames, seen = [], set()
    for d in data_dirs:
        models = [m for m in discover_models(d) if m not in seen]
        if not models:
            continue
        seen.update(models)
        frames.append(load_results(models, d))
    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(["model", "prompt_type", "identity", "sample_id"], keep="last")
    if n_samples:
        keep = sorted(df["sample_id"].dropna().unique())[:n_samples]
        df = df[df["sample_id"].isin(keep)]
    return df


def main():
    global OUT_DIR
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", action="append", default=None,
                        help="results folder; repeat for several (default: data/call_models/)")
    parser.add_argument("--n-samples", type=int, default=None,
                        help="keep only the first N sample ids for every model")
    parser.add_argument("--out-sub", default="all_models", help="output subfolder of results/analyze_results/")
    args = parser.parse_args()
    OUT_DIR = os.path.join(PATH_TO_RESULTS, args.out_sub) + os.sep
    os.makedirs(OUT_DIR, exist_ok=True)
    df = load_all(args.data_dir or [PATH_TO_MODEL_RESULTS], args.n_samples)
    table = yes_no_table(df)
    table.to_csv(os.path.join(OUT_DIR, "yes-no-by-prompt.csv"), index=False)
    models = model_order(table)
    plot_counts(table, models)
    plot_percent(table, models)
    wide = table.pivot(index="model", columns="prompt_type", values="yes_pct").reindex(models)
    print(wide[[p for p, _ in PROMPTS]].round(1).to_string())
    print(f"\nSaved yes-no-by-prompt.csv, yes-no-counts-by-prompt, yes-no-percent-by-prompt to {OUT_DIR}")


if __name__ == "__main__":
    main()
