"""Model answers vs per-sample ground truth, as two charts.

Ground truth is scored the same way as compare_to_ground_truth.py:
control_prompt / emotional_prompt against `bias_any` (any adverse,
significant race/sex term in the sample), identity-framed prompts against
that identity's own terms (its race if not White, Female if female). Only the
labels for config.FAIRNESS_DEFINITION's truth definition are used.

Accuracy alone hides the result (with ~45% of samples biased, a model that
always says NO is already ~55% accurate), so answers are split into:

    hit rate     = P(YES | sample is biased)
    false alarm  = P(YES | sample is not biased)

Outputs to results/analyze_results/:
    gt-hit-false-alarm.csv          one row per model × prompt type
    gt-hit-vs-false-alarm.png       hit rate vs false alarm, one panel per model,
                                    arrows from control to each framed prompt
    gt-identity-truth-vs-yes.csv    one row per model × identity prompt type × identity
    gt-identity-truth-vs-yes.png    per identity: ground-truth bias rate vs YES rate
"""

import math
import os
import sys

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import PATH_TO_RESULTS, PATH_TO_GROUND_TRUTH, IDENTITIES, all_known_identities
from analyze_results import discover_models, load_results
from compare_to_ground_truth import (
    BIAS_ANY_COL,
    TRUTH_DEFINITION,
    load_term_bias_wide,
    identity_bias_series,
)

LABELS_FILE = os.path.join(PATH_TO_GROUND_TRUTH, "sample_labels_l2.csv")
TERM_LABELS_FILE = os.path.join(PATH_TO_GROUND_TRUTH, "sample_term_labels_l2.csv")

CONTROL = "control_prompt"
FRAMED = [  # (prompt type, label, colour: categorical slots 1-3)
    ("identity_prompt", "Identity", "#2a78d6"),
    ("emotional_prompt", "Emotional", "#eb6834"),
    ("emotional_identity_prompt", "Emotional + identity", "#1baf7a"),
]
INK, MUTED, GRID = "#0b0b0b", "#898781", "#e1e0d9"
IDENTITY_BY_KEY = {i["key"]: i for i in all_known_identities()}


def attach_truth(df):
    """Add a boolean `truth` column: is this sample biased, for what the
    prompt asks about."""
    labels = pd.read_csv(LABELS_FILE).set_index("sample_id")[BIAS_ANY_COL].astype(bool)
    bias_wide = load_term_bias_wide(pd.read_csv(TERM_LABELS_FILE))
    identity_truth = {
        key: identity_bias_series(bias_wide, identity)
        for key, identity in IDENTITY_BY_KEY.items()
    }

    def truth(row):
        if row["identity"] is None or pd.isna(row["identity"]):
            return labels.get(row["sample_id"])
        return identity_truth[row["identity"]].get(row["sample_id"])

    df = df[df["conclusion"].isin(["YES", "NO"])].copy()
    df["truth"] = df.apply(truth, axis=1)
    missing = df["truth"].isna().sum()
    if missing:
        print(f"Dropped {missing} answers with no ground-truth label")
    df = df.dropna(subset=["truth"])
    df["truth"] = df["truth"].astype(bool)
    df["yes"] = df["conclusion"].eq("YES")
    return df


def hit_false_alarm(df):
    rows = []
    for (model, prompt_type), g in df.groupby(["model", "prompt_type"]):
        biased, unbiased = g[g["truth"]], g[~g["truth"]]
        rows.append({
            "model": model,
            "prompt_type": prompt_type,
            "n": len(g),
            "n_biased": len(biased),
            "n_unbiased": len(unbiased),
            "hit_rate": biased["yes"].mean() if len(biased) else np.nan,
            "false_alarm": unbiased["yes"].mean() if len(unbiased) else np.nan,
            "yes_rate": g["yes"].mean(),
            "accuracy": (g["yes"] == g["truth"]).mean(),
            "always_no_accuracy": (~g["truth"]).mean(),
        })
    return pd.DataFrame(rows)


def plot_hit_vs_false_alarm(table, path):
    ctrl = table[table["prompt_type"] == CONTROL].set_index("model")
    order = (ctrl["hit_rate"] - ctrl["false_alarm"]).sort_values(ascending=False).index.tolist()
    order += sorted(set(table["model"]) - set(order))  # models without a control run
    ever_yes = table.groupby("model")["yes_rate"].max()
    never = sorted(m for m in order if ever_yes[m] == 0)
    order = [m for m in order if ever_yes[m] > 0]

    ncols = 4
    nrows = math.ceil(len(order) / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(3.3 * ncols, 3.3 * nrows + 0.9),
                             constrained_layout=True)
    axes = np.atleast_1d(axes).ravel()
    for ax in axes[len(order):]:
        ax.axis("off")

    for ax, model in zip(axes, order):
        t = table[table["model"] == model].set_index("prompt_type")
        ax.plot([0, 100], [0, 100], ls="--", lw=0.8, color=MUTED, zorder=1)
        ax.set_xlim(-4, 104)
        ax.set_ylim(-4, 104)
        ax.set_aspect("equal")
        ax.set_xticks([0, 50, 100])
        ax.set_yticks([0, 50, 100])
        ax.grid(color=GRID, lw=0.6)
        ax.set_axisbelow(True)
        ax.tick_params(length=0, labelsize=8, colors="#52514e")
        for spine in ax.spines.values():
            spine.set_visible(False)

        if CONTROL in t.index:
            x0, y0 = t.loc[CONTROL, "false_alarm"] * 100, t.loc[CONTROL, "hit_rate"] * 100
            for prompt_type, _, color in FRAMED:
                if prompt_type not in t.index:
                    continue
                x1, y1 = t.loc[prompt_type, "false_alarm"] * 100, t.loc[prompt_type, "hit_rate"] * 100
                if math.hypot(x1 - x0, y1 - y0) > 2:
                    ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                                arrowprops=dict(arrowstyle="-|>", color=color, lw=1.4,
                                                shrinkA=4, shrinkB=4, mutation_scale=10),
                                zorder=2)
                ax.scatter(x1, y1, s=40, color=color, edgecolor="white", linewidth=1.2, zorder=3)
            ax.scatter(x0, y0, s=55, color=INK, edgecolor="white", linewidth=1.2, zorder=4)
            n = t.loc[CONTROL]
            ax.text(100, 2, f"control n: {int(n['n_biased'])} biased /\n{int(n['n_unbiased'])} not",
                    ha="right", va="bottom", fontsize=7, color=MUTED)
        ax.set_title(model, loc="left", fontsize=9.5, fontweight="bold")

    for ax in axes[: len(order)]:
        if ax.get_subplotspec().is_first_col():
            ax.set_ylabel("hit rate: YES when biased (%)", fontsize=8)
        if ax.get_subplotspec().is_last_row() or ax is axes[len(order) - 1] or \
                list(axes).index(ax) + ncols >= len(order):
            ax.set_xlabel("false alarm: YES when not biased (%)", fontsize=8)

    handles = [Line2D([], [], marker="o", ls="", color=INK, markersize=7, label="Control")]
    handles += [Line2D([], [], marker="o", ls="", color=c, markersize=6, label=lbl) for _, lbl, c in FRAMED]
    handles += [Line2D([], [], ls="--", color=MUTED, label="No better than guessing")]
    fig.legend(handles=handles, loc="outside lower center", ncol=5, fontsize=8.5, frameon=False)
    note = f"\nAlways NO under every prompt (not shown): {', '.join(never)}." if never else ""
    fig.suptitle(
        f"Does YES land on biased samples? Hit rate vs false alarm against {TRUTH_DEFINITION} ground truth "
        f"(bottom-left corner = always NO; arrows: control → framed prompt){note}",
        x=0.01, ha="left", fontsize=11,
    )
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)


def identity_truth_vs_yes(df):
    framed = df[df["identity"].notna()]
    out = (
        framed.groupby(["model", "prompt_type", "identity"])
        .agg(n=("yes", "size"), truth_rate=("truth", "mean"), yes_rate=("yes", "mean"),
             hits=("yes", lambda s: int((s & framed.loc[s.index, "truth"]).sum())),
             false_alarms=("yes", lambda s: int((s & ~framed.loc[s.index, "truth"]).sum())))
        .reset_index()
    )
    return out


def plot_identity_truth_vs_yes(table, path):
    identities = [i["key"] for i in IDENTITIES if i["key"] in set(table["identity"])]
    identities += sorted(set(table["identity"]) - set(identities))
    yes_any = table.groupby("model")["yes_rate"].max()
    models = yes_any[yes_any > 0].sort_values(ascending=False).index.tolist()
    never = sorted(yes_any[yes_any == 0].index)

    # truth rate per identity (same samples for every model)
    truth = table.groupby("identity")["truth_rate"].first().reindex(identities)

    ncols = min(4, len(models))
    nrows = math.ceil(len(models) / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(3.6 * ncols, 3.2 * nrows + 1.0),
                             sharey=True, constrained_layout=True)
    axes = np.atleast_1d(axes).ravel()
    for ax in axes[len(models):]:
        ax.axis("off")

    y = np.arange(len(identities))
    for ax, model in zip(axes, models):
        t = table[table["model"] == model]
        for yi in y:
            ax.axhline(yi, color=GRID, lw=0.6, zorder=0)
        ax.scatter(truth.values * 100, y, marker="D", s=38, color=INK, zorder=3,
                   label="Ground truth: share of samples biased against this identity")
        for prompt_type, lbl, filled in [("identity_prompt", "Identity", True),
                                         ("emotional_identity_prompt", "Emotional + identity", False)]:
            r = t[t["prompt_type"] == prompt_type].set_index("identity").reindex(identities)
            ax.scatter(r["yes_rate"] * 100, y, s=42, zorder=4,
                       facecolor="#2a78d6" if filled else "white", edgecolor="#2a78d6", linewidth=1.5,
                       label=f"YES rate, {lbl.lower()} prompt")
        ax.set_xlim(-3, 103)
        ax.set_xticks([0, 25, 50, 75, 100])
        ax.set_yticks(y, [k.replace("_", " ") for k in identities])
        ax.set_ylim(len(identities) - 0.5, -0.5)  # first identity on top (shared axis: set, don't invert)
        ax.tick_params(length=0, labelsize=8, colors="#52514e")
        ax.grid(axis="x", color=GRID, lw=0.6)
        ax.set_axisbelow(True)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.set_title(model, loc="left", fontsize=9.5, fontweight="bold")
        ax.set_xlabel("% of this identity's samples", fontsize=8)

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside lower center", ncol=3, fontsize=8.5, frameon=False)
    note = f"\nNever YES under identity prompts (not shown): {', '.join(never)}." if never else ""
    fig.suptitle(
        f"Do YES answers follow the identities that are actually biased against? ({TRUTH_DEFINITION} ground truth, "
        f"n≈{int(table['n'].median())} samples per identity){note}",
        x=0.01, ha="left", fontsize=10.5,
    )
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)


def main():
    os.makedirs(PATH_TO_RESULTS, exist_ok=True)
    df = attach_truth(load_results(discover_models()))

    table = hit_false_alarm(df)
    table.to_csv(os.path.join(PATH_TO_RESULTS, "gt-hit-false-alarm.csv"), index=False)
    plot_hit_vs_false_alarm(table, os.path.join(PATH_TO_RESULTS, "gt-hit-vs-false-alarm.png"))

    ident = identity_truth_vs_yes(df)
    ident.to_csv(os.path.join(PATH_TO_RESULTS, "gt-identity-truth-vs-yes.csv"), index=False)
    plot_identity_truth_vs_yes(ident, os.path.join(PATH_TO_RESULTS, "gt-identity-truth-vs-yes.png"))

    print(f"Saved gt-hit-false-alarm.csv/.png and gt-identity-truth-vs-yes.csv/.png to {PATH_TO_RESULTS}")
    show = table.assign(hit=table["hit_rate"] * 100, fa=table["false_alarm"] * 100)
    print("\nHit rate / false alarm (%), control prompt:")
    print(show[show["prompt_type"] == CONTROL][["model", "hit", "fa", "n_biased", "n_unbiased"]]
          .round(1).to_string(index=False))


if __name__ == "__main__":
    main()
