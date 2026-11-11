"""Model answers vs per-sample ground truth, as four figures.

Ground truth is scored the same way as compare_to_ground_truth.py:
control_prompt / emotional_prompt against `bias_any` (any adverse,
significant race/sex term in the sample), identity-framed prompts against
that identity's own terms (its race if not White, Female if female). Only the
labels for config.FAIRNESS_DEFINITION's truth definition are used.

Because the two truths differ (~45% of samples biased for bias_any, ~14% for
identity terms), identity-prompt numbers are compared within their own
column, never against control.

Accuracy alone hides the result (a model that always says NO is already
55-86% accurate), so answers are split into:

    hit rate     = P(YES | sample is biased)
    false alarm  = P(YES | sample is not biased)
    J            = hit rate - false alarm   (0 = YES unrelated to truth)

Outputs to results/analyze_results/vs_ground_truth/ (each figure as .png and .pdf):
    gt-hit-false-alarm.csv           one row per model × prompt type, with
                                     bootstrap 95% CI on J
    gt-yes-decomposition             YES rate split into YES-on-biased and
                                     YES-on-not-biased, vs the true biased share
    gt-discrimination                J with 95% CI per model × prompt type
    gt-identity-truth-vs-yes.csv     one row per model × identity prompt type ×
                                     identity, with Wilson 95% CI on YES rate
    gt-identity-gap-heatmap          YES rate minus true biased rate, per
                                     model × identity
"""

import math
import os
import sys

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, to_rgb
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import PATH_TO_RESULTS, PATH_TO_GROUND_TRUTH, IDENTITIES, all_known_identities
OUT_DIR = os.path.join(PATH_TO_RESULTS, "vs_ground_truth") + os.sep
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
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#898781", "#e1e0d9", "#ffffff"
SECONDARY = "#52514e"
# column order for the multi-prompt figures: bias_any truth first, identity truth second
PROMPTS = [
    (CONTROL, "Control", INK),
    ("emotional_prompt", "Emotional", "#eb6834"),
    ("identity_prompt", "Identity", "#2a78d6"),
    ("emotional_identity_prompt", "Emotional + identity", "#1baf7a"),
]
IDENTITY_PROMPTS = {"identity_prompt", "emotional_identity_prompt"}
# diverging: blue (under-calls) <-> neutral grey <-> red (over-calls)
DIVERGING = LinearSegmentedColormap.from_list("gap", ["#184f95", "#6da7ec", "#f0efec", "#ef8a89", "#b8302f"])
IDENTITY_BY_KEY = {i["key"]: i for i in all_known_identities()}
RNG_SEED = 0
N_BOOT = 2000


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


def wilson(k, n, z=1.96):
    """Wilson 95% interval for k successes out of n."""
    if n == 0:
        return np.nan, np.nan
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def hit_false_alarm(df):
    rng = np.random.default_rng(RNG_SEED)
    rows = []
    for (model, prompt_type), g in df.groupby(["model", "prompt_type"]):
        biased, unbiased = g[g["truth"]], g[~g["truth"]]
        tp, fp = int(biased["yes"].sum()), int(unbiased["yes"].sum())
        hit = tp / len(biased) if len(biased) else np.nan
        fa = fp / len(unbiased) if len(unbiased) else np.nan
        # bootstrap stratified by truth: resampling Bernoulli answers within a
        # stratum is the same as drawing a binomial at the observed rate
        boot_j = (rng.binomial(len(biased), hit, N_BOOT) / len(biased)
                  - rng.binomial(len(unbiased), fa, N_BOOT) / len(unbiased))
        rows.append({
            "model": model,
            "prompt_type": prompt_type,
            "n": len(g),
            "n_biased": len(biased),
            "n_unbiased": len(unbiased),
            "tp": tp,
            "fp": fp,
            "hit_rate": hit,
            "false_alarm": fa,
            "j": hit - fa,
            "j_lo": np.percentile(boot_j, 2.5),
            "j_hi": np.percentile(boot_j, 97.5),
            "yes_rate": g["yes"].mean(),
            "accuracy": (g["yes"] == g["truth"]).mean(),
            "always_no_accuracy": (~g["truth"]).mean(),
            "precision": tp / (tp + fp) if tp + fp else np.nan,
            "f1": 2 * tp / (2 * tp + fp + (len(biased) - tp)) if len(biased) else np.nan,
            "f1_always_yes": 2 * len(biased) / (len(g) + len(biased)),
        })
    return pd.DataFrame(rows)


def model_order(table):
    """Models that ever say YES, best control J first; then the always-NO
    models. Same order in every figure."""
    ctrl = table[table["prompt_type"] == CONTROL].set_index("model")
    ever_yes = table.groupby("model")["yes_rate"].max()
    active = [m for m in ever_yes.index if ever_yes[m] > 0]
    active.sort(key=lambda m: (-ctrl["j"].get(m, -1), -ever_yes[m]))
    never = sorted(m for m in ever_yes.index if ever_yes[m] == 0)
    return active, never


def tint(color, amount):
    """Mix `color` toward white; amount=1 is the colour, 0 is white."""
    r, g, b = to_rgb(color)
    return (1 - amount * (1 - r), 1 - amount * (1 - g), 1 - amount * (1 - b))


def style_axis(ax):
    ax.tick_params(length=0, labelsize=8, colors=SECONDARY)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_axisbelow(True)


def grey_never_labels(ax, never):
    for label in ax.get_yticklabels():
        if label.get_text() in never:
            label.set_color(MUTED)


def save(fig, name):
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(OUT_DIR, f"{name}.{ext}"), dpi=300, facecolor="white")
    plt.close(fig)


def plot_yes_decomposition(table, active, never):
    models = active + never
    y = np.arange(len(models))
    fig, axes = plt.subplots(1, len(PROMPTS), figsize=(15, 0.36 * len(models) + 1.8),
                             sharey=True, constrained_layout=True)
    fig.get_layout_engine().set(wspace=0.06)
    for ax, (prompt_type, label, color) in zip(axes, PROMPTS):
        t = table[table["prompt_type"] == prompt_type].set_index("model").reindex(models)
        tp = t["tp"] / t["n"] * 100
        fp = t["fp"] / t["n"] * 100
        ax.barh(y, tp, height=0.62, color=color, edgecolor=SURFACE, linewidth=1)
        ax.barh(y, fp, left=tp, height=0.62, color=tint(color, 0.3), edgecolor=SURFACE, linewidth=1)
        truth_share = t["n_biased"] / t["n"] * 100
        ax.scatter(truth_share, y, marker="|", s=170, linewidths=1.8, color=INK, zorder=4)
        for yi, (_, r) in zip(y, t.iterrows()):
            if pd.isna(r["n"]):
                continue
            prec = "—" if pd.isna(r["precision"]) else f"{r['precision'] * 100:.0f}"
            ax.text(1.02, yi, f"{r['hit_rate'] * 100:.0f} | {prec} | {r['f1'] * 100:.0f}",
                    transform=ax.get_yaxis_transform(), va="center", ha="left", fontsize=7, color=SECONDARY)
        f1_base = t["f1_always_yes"].dropna().iloc[0] * 100
        ax.text(1.02, -1.0, f"recall | prec | F1\n(always-YES F1: {f1_base:.0f})",
                transform=ax.get_yaxis_transform(), va="center", ha="left", fontsize=7, color=MUTED)
        if never:
            ax.axhline(len(active) - 0.5, color=GRID, lw=1)
        truth_name = "identity's own terms" if prompt_type in IDENTITY_PROMPTS else "bias_any"
        ax.set_title(f"{label}\ntruth: {truth_name}", loc="left", fontsize=9.5, fontweight="bold")
        ax.set_xlim(0, 100)
        ax.set_xticks([0, 25, 50, 75, 100])
        ax.grid(axis="x", color=GRID, lw=0.6)
        ax.set_xlabel("% of all answers", fontsize=8)
        style_axis(ax)
    axes[0].set_yticks(y, models)
    axes[0].set_ylim(len(models) - 0.5, -1.4)
    grey_never_labels(axes[0], never)

    handles = [
        Patch(facecolor=MUTED, label="YES on a biased sample (hit)"),
        Patch(facecolor=tint(MUTED, 0.3), label="YES on a not-biased sample (false alarm)"),
        Line2D([], [], marker="|", ls="", color=INK, markersize=12, markeredgewidth=1.8,
               label="True share of biased samples"),
    ]
    fig.legend(handles=handles, loc="outside lower center", ncol=3, fontsize=8.5, frameon=False)
    fig.suptitle(
        f"How often each model says YES, and where those YES answers land ({TRUTH_DEFINITION} ground truth). "
        "Bar left of the tick = under-calls bias; right = over-calls.\n"
        "recall = % of biased samples called YES; prec = % of YES answers that were right; F1 combines both "
        "(always saying YES gets the F1 in the header). Grey names: always NO under every prompt.",
        x=0.01, ha="left", fontsize=10.5,
    )
    save(fig, "gt-yes-decomposition")


def plot_discrimination(table, active, never):
    models = active + never
    y = np.arange(len(models))
    offsets = np.linspace(-0.27, 0.27, len(PROMPTS))
    fig, ax = plt.subplots(figsize=(8, 0.42 * len(models) + 1.6), constrained_layout=True)
    for yi in y[::2]:
        ax.axhspan(yi - 0.5, yi + 0.5, color="#f6f5f2", lw=0, zorder=0)
    ax.axvline(0, color=MUTED, lw=1, ls="--", zorder=1)
    for off, (prompt_type, label, color) in zip(offsets, PROMPTS):
        t = table[table["prompt_type"] == prompt_type].set_index("model").reindex(models)
        yy = y + off
        ax.hlines(yy, t["j_lo"] * 100, t["j_hi"] * 100, color=color, lw=1.6, zorder=2)
        ax.scatter(t["j"] * 100, yy, s=36, color=color, edgecolor=SURFACE, linewidth=1.2,
                   zorder=3, label=label)
    if never:
        ax.axhline(len(active) - 0.5, color=GRID, lw=1)
    ax.set_yticks(y, models)
    ax.set_ylim(len(models) - 0.5, -0.5)
    grey_never_labels(ax, never)
    ax.set_xlim(-12, 52)
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.set_xlabel("J = hit rate − false-alarm rate (percentage points), 95% bootstrap CI", fontsize=8)
    ax.text(0.5, -0.45, "← YES unrelated to truth", fontsize=7, color=MUTED, ha="left", va="center")
    style_axis(ax)
    fig.legend(loc="outside lower center", ncol=4, fontsize=8.5, frameon=False)
    fig.suptitle(
        f"Does YES track the ground truth? ({TRUTH_DEFINITION})\n"
        "Control/Emotional use bias_any truth; Identity prompts use the identity's own\n"
        "terms — compare within a prompt type, not across.",
        x=0.01, ha="left", fontsize=10,
    )
    save(fig, "gt-discrimination")


def identity_truth_vs_yes(df):
    framed = df[df["identity"].notna()]
    out = (
        framed.groupby(["model", "prompt_type", "identity"])
        .agg(n=("yes", "size"), n_yes=("yes", "sum"), n_biased=("truth", "sum"),
             truth_rate=("truth", "mean"), yes_rate=("yes", "mean"),
             hits=("yes", lambda s: int((s & framed.loc[s.index, "truth"]).sum())),
             false_alarms=("yes", lambda s: int((s & ~framed.loc[s.index, "truth"]).sum())))
        .reset_index()
    )
    ci = [wilson(k, n) for k, n in zip(out["n_yes"], out["n"])]
    out["yes_lo"] = [lo for lo, _ in ci]
    out["yes_hi"] = [hi for _, hi in ci]
    return out


def plot_identity_gap(ident, active, df):
    identities = [i["key"] for i in IDENTITIES if i["key"] in set(ident["identity"])]
    identities += sorted(set(ident["identity"]) - set(identities))
    yes_any = ident.groupby("model")["yes_rate"].max()
    models = [m for m in active if yes_any.get(m, 0) > 0]
    never = sorted(m for m in yes_any.index if yes_any[m] == 0)

    # true biased count per identity, from the samples that identity actually saw
    seen = df[df["identity"].notna()].drop_duplicates(["identity", "sample_id"])
    truth_k = seen.groupby("identity")["truth"].sum().reindex(identities)
    truth_n = seen.groupby("identity")["truth"].size().reindex(identities)
    xlabels = [f"{k.replace('_', chr(10))}\n{int(truth_k[k])}/{int(truth_n[k])} biased" for k in identities]

    fig, axes = plt.subplots(1, 2, figsize=(14, 0.5 * len(models) + 2.6), sharey=True,
                             constrained_layout=True)
    for ax, prompt_type, title in [(axes[0], "identity_prompt", "Identity prompt"),
                                   (axes[1], "emotional_identity_prompt", "Emotional + identity prompt")]:
        t = ident[ident["prompt_type"] == prompt_type].set_index(["model", "identity"])
        for yi, model in enumerate(models):
            for xi, key in enumerate(identities):
                if (model, key) not in t.index:
                    continue
                r = t.loc[(model, key)]
                gap = (r["yes_rate"] - r["truth_rate"]) * 100
                within_noise = r["yes_lo"] <= r["truth_rate"] <= r["yes_hi"]
                color = DIVERGING((np.clip(gap, -30, 30) + 30) / 60)
                ax.add_patch(Rectangle((xi - 0.5, yi - 0.5), 1, 1, facecolor=color,
                                       edgecolor=SURFACE, linewidth=2))
                if not within_noise:
                    ax.add_patch(Rectangle((xi - 0.44, yi - 0.42), 0.88, 0.84, fill=False,
                                           edgecolor=INK, linewidth=1.3))
                strong = abs(gap) > 20
                ax.text(xi, yi - 0.12, f"{int(r['n_yes'])}/{int(r['n'])}", ha="center", va="center",
                        fontsize=7.5, color="white" if strong else INK)
                ax.text(xi, yi + 0.22, f"{int(r['hits'])} hit", ha="center", va="center",
                        fontsize=6.5, color="white" if strong else SECONDARY)
        ax.set_xlim(-0.5, len(identities) - 0.5)
        ax.set_ylim(len(models) - 0.5, -0.5)
        ax.set_xticks(range(len(identities)), xlabels)
        ax.xaxis.tick_top()
        ax.set_yticks(range(len(models)), models)
        ax.set_title(title, loc="left", fontsize=10, fontweight="bold")
        style_axis(ax)
        ax.tick_params(axis="x", labelsize=7.5)

    sm = plt.cm.ScalarMappable(cmap=DIVERGING, norm=plt.Normalize(-30, 30))
    cbar = fig.colorbar(sm, ax=axes, location="bottom", shrink=0.4, aspect=40, pad=0.02)
    cbar.set_label("YES rate − true biased rate (pp)   ← under-calls  |  over-calls →", fontsize=8)
    cbar.ax.tick_params(labelsize=7, length=0)
    cbar.outline.set_visible(False)
    note = f"\nNever YES under identity prompts (not shown): {', '.join(never)}." if never else ""
    fig.suptitle(
        f"Do YES answers follow the identities actually biased against? ({TRUTH_DEFINITION} truth: identity's own terms)\n"
        "Cell text: YES answers / answers, and how many YES landed on a biased sample.\n"
        f"Outlined cells: true rate outside the YES rate's Wilson 95% CI (gap beyond sampling noise). Colour clipped at ±30 pp.{note}",
        x=0.01, ha="left", fontsize=10,
    )
    save(fig, "gt-identity-gap-heatmap")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    df = attach_truth(load_results(discover_models()))

    table = hit_false_alarm(df)
    table.to_csv(os.path.join(OUT_DIR, "gt-hit-false-alarm.csv"), index=False)
    active, never = model_order(table)
    plot_yes_decomposition(table, active, never)
    plot_discrimination(table, active, never)

    ident = identity_truth_vs_yes(df)
    ident.to_csv(os.path.join(OUT_DIR, "gt-identity-truth-vs-yes.csv"), index=False)
    plot_identity_gap(ident, active, df)


    print(f"Saved gt-hit-false-alarm.csv, gt-identity-truth-vs-yes.csv and "
          f"gt-yes-decomposition / gt-discrimination / gt-identity-gap-heatmap "
          f"(.png, .pdf) to {OUT_DIR}")
    show = table.assign(hit=table["hit_rate"] * 100, fa=table["false_alarm"] * 100,
                        J=table["j"] * 100, J_lo=table["j_lo"] * 100, J_hi=table["j_hi"] * 100)
    print("\nHit rate / false alarm / J (%), control prompt:")
    print(show[show["prompt_type"] == CONTROL][["model", "hit", "fa", "J", "J_lo", "J_hi"]]
          .round(1).to_string(index=False))


if __name__ == "__main__":
    main()
