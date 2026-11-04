"""How identity framing changes each model's answer, paired with control.

Every identity-framed call (identity_prompt, emotional_identity_prompt) runs
on a sample that also has a control_prompt call from the same model, so the
two answers can be compared on the same data:

    Δ YES (pp) = YES%(identity prompt) - YES%(control prompt), same samples

Unlike sycophancy_rate.py (independent run-level rates), this is a paired
comparison per model × prompt type × identity (n ≈ 37-38 samples per cell
with IDENTITY_SAMPLE_SPLIT). It also splits the change into NO→YES and
YES→NO flips.

Outputs to results/analyze_results/:
    answer-change-by-identity.csv   one row per model × prompt type × identity
    answer-change-pairs.csv         one row per paired (identity call, control call)
    answer-change-dyes-heatmap.png  Δ YES heatmap, models × identities
"""

import math
import os
import sys

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import PATH_TO_RESULTS, IDENTITIES
from analyze_results import discover_models, load_results

PANELS = [
    ("identity_prompt", "Identity prompt"),
    ("emotional_identity_prompt", "Emotional + identity prompt"),
]

# diverging blue (fewer YES) <-> gray (no change) <-> red (more YES)
CMAP = LinearSegmentedColormap.from_list(
    "diverging", ["#104281", "#3987e5", "#f0efec", "#e34948", "#8f1d1c"]
)
INK = "#0b0b0b"
MIN_COLOR_RANGE = 40  # pp; colour scale is at least ±40 so small changes stay pale


def build_pairs(df):
    """Join each identity-framed answer to the same model's control answer
    on the same sample."""
    keys = ["model", "prompt_type", "identity", "sample_id"]
    df = df.drop_duplicates(keys, keep="last")
    control = df[df["prompt_type"] == "control_prompt"][
        ["model", "sample_id", "conclusion", "confidence"]
    ]
    framed = df[df["prompt_type"].isin([p for p, _ in PANELS])]
    pairs = framed.merge(control, on=["model", "sample_id"], suffixes=("", "_ctrl"))

    pairs["yes"] = pairs["conclusion"].eq("YES")
    pairs["yes_ctrl"] = pairs["conclusion_ctrl"].eq("YES")
    pairs["changed"] = pairs["conclusion"] != pairs["conclusion_ctrl"]
    pairs["to_yes"] = ~pairs["yes_ctrl"] & pairs["yes"]
    pairs["from_yes"] = pairs["yes_ctrl"] & ~pairs["yes"]
    pairs["dconf"] = pairs["confidence"] - pairs["confidence_ctrl"]

    print(f"Paired rows: {len(pairs)} | identity rows without a control answer: "
          f"{len(framed) - len(pairs)}")
    return pairs[keys + ["conclusion", "conclusion_ctrl", "confidence", "confidence_ctrl",
                         "yes", "yes_ctrl", "changed", "to_yes", "from_yes", "dconf"]]


def summarize(pairs):
    summary = (
        pairs.groupby(["model", "prompt_type", "identity"])
        .agg(
            n=("changed", "size"),
            yes_ctrl=("yes_ctrl", "mean"),
            yes_id=("yes", "mean"),
            changed=("changed", "mean"),
            to_yes=("to_yes", "mean"),
            from_yes=("from_yes", "mean"),
            dconf=("dconf", "mean"),
        )
        .reset_index()
    )
    summary["d_yes"] = summary["yes_id"] - summary["yes_ctrl"]
    return summary


def plot_heatmap(summary, pairs, path):
    identities = [i["key"] for i in IDENTITIES if i["key"] in set(summary["identity"])]
    identities += sorted(set(summary["identity"]) - set(identities))  # SELECTED_IDENTITIES extras
    col_labels = [k.replace("_", "\n") for k in identities]

    # one control YES rate per model (control answers on the paired samples)
    ctrl = pairs.drop_duplicates(["model", "sample_id"]).groupby("model")["yes_ctrl"].mean()
    models = list(ctrl.sort_values(ascending=False).index)
    row_labels = [f"{m}  (ctrl YES {ctrl[m] * 100:.0f}%)" for m in models]

    vmax = max(MIN_COLOR_RANGE, math.ceil(summary["d_yes"].abs().max() * 100 / 10) * 10)
    norm = TwoSlopeNorm(vcenter=0, vmin=-vmax, vmax=vmax)
    white_text_above = vmax * 0.55

    plt.rcParams.update({"font.size": 9, "axes.edgecolor": "#c3c2b7"})
    fig, axes = plt.subplots(
        1, len(PANELS), figsize=(15, 1.2 + 0.45 * len(models)), sharey=True,
        constrained_layout=True,
    )
    for ax, (prompt_type, title) in zip(axes, PANELS):
        grid = (
            summary[summary["prompt_type"] == prompt_type]
            .pivot(index="model", columns="identity", values="d_yes")
            .reindex(index=models, columns=identities)
            * 100
        )
        im = ax.imshow(grid.values, cmap=CMAP, norm=norm, aspect="auto")
        for i in range(grid.shape[0]):
            for j in range(grid.shape[1]):
                v = grid.values[i, j]
                if np.isnan(v):
                    text, color = "–", "#898781"
                else:
                    text = "·" if round(v) == 0 else f"{v:+.0f}"
                    color = "white" if abs(v) > white_text_above else INK
                ax.text(j, i, text, ha="center", va="center", color=color, fontsize=8.5)
        ax.set_xticks(range(len(identities)), col_labels)
        ax.set_yticks(range(len(models)), row_labels)
        ax.set_xticks(np.arange(-0.5, len(identities)), minor=True)
        ax.set_yticks(np.arange(-0.5, len(models)), minor=True)
        ax.grid(which="minor", color="white", linewidth=2)
        ax.tick_params(which="both", length=0)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.set_title(title, loc="left", fontsize=11, fontweight="bold")

    fig.colorbar(im, ax=axes, shrink=0.8, label="Δ YES rate vs control on same samples (pp)")
    n_cell = int(summary["n"].median())
    fig.suptitle(
        "How identity framing changes the 'YES, discrimination' answer — paired with "
        f"control on the same sample (n≈{n_cell} per cell; · = 0)",
        x=0.01, ha="left", fontsize=11,
    )
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)


def main():
    os.makedirs(PATH_TO_RESULTS, exist_ok=True)

    df = load_results(discover_models())
    pairs = build_pairs(df)
    summary = summarize(pairs)

    summary.to_csv(os.path.join(PATH_TO_RESULTS, "answer-change-by-identity.csv"), index=False)
    pairs.to_csv(os.path.join(PATH_TO_RESULTS, "answer-change-pairs.csv"), index=False)
    plot_heatmap(summary, pairs, os.path.join(PATH_TO_RESULTS, "answer-change-dyes-heatmap.png"))

    print(f"Saved answer-change-by-identity.csv, -pairs.csv, -dyes-heatmap.png to {PATH_TO_RESULTS}")
    print("\nMean Δ YES vs control per model and prompt type (pp):")
    print(
        (summary.groupby(["model", "prompt_type"])["d_yes"].mean().unstack() * 100)
        .round(1)
        .to_string()
    )


if __name__ == "__main__":
    main()
