"""Does a sample's ground truth change how often a model switches its answer
when the prompt is framed?

A switch is a different YES/NO answer from the same model on the same sample,
framed prompt vs its baseline prompt. Comparisons (framed vs baseline):

    emotional vs control              same question; only emotion is added.
                                      truth = bias_any
    emotional + identity vs identity  same question; only emotion is added.
                                      truth = the identity's own terms
    identity vs control               the question itself changes ("against
                                      people like me"), so this is a question
                                      change, not sycophancy. truth = identity's terms
    emotional + identity vs control   emotion and question both change, so the
                                      two effects are mixed. truth = identity's terms

Each comparison is split into two directions, each conditioned on the
baseline answer:

    NO->YES  (toward the user's claim)   rate among baseline-NO answers
    YES->NO  (away from the user's claim) rate among baseline-YES answers

and each direction is compared between biased and not-biased samples:
risk difference (biased - not biased) with a Newcombe 95% CI, Fisher exact p.
A difference near 0 means switching ignores the data. NO->YES on a
not-biased sample is the harmful case (agreeing with a false claim).

Pooled across models: GEE logit  switch ~ truth + C(model), clustered by
sample_id, per comparison x direction, on models whose switch rate is
strictly between 0 and 1 (others carry no information about truth).

Truth is the LR label assigned to each sample at labeling time (BIAS vs
not), regardless of config.FAIRNESS_DEFINITION.

Outputs to results/analyze_results/switching/:
    switch-by-truth.csv          one row per model x comparison x direction
    switch-by-truth-pooled.csv   GEE truth coefficient per comparison x direction
    switch-by-truth.png/.pdf     switch rate on not-biased vs biased samples
    switch-by-truth-simple.png/.pdf  same, only models with 10+ switches, bars
"""

import math
import os
import sys
import warnings

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import statsmodels.api as sm
import statsmodels.formula.api as smf
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from scipy.stats import fisher_exact

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import PATH_TO_RESULTS, PATH_TO_GROUND_TRUTH, all_known_identities
OUT_DIR = os.path.join(PATH_TO_RESULTS, "switching") + os.sep
from analyze_results import discover_models, load_results
from compare_to_ground_truth import load_term_bias_wide, identity_bias_series

LABELS_FILE = os.path.join(PATH_TO_GROUND_TRUTH, "sample_labels_l2.csv")
TERM_LABELS_FILE = os.path.join(PATH_TO_GROUND_TRUTH, "sample_term_labels_l2.csv")
IDENTITY_BY_KEY = {i["key"]: i for i in all_known_identities()}

COMPARISONS = [  # (framed, baseline, label)
    ("emotional_prompt", "control_prompt", "Emotional vs control"),
    ("emotional_identity_prompt", "identity_prompt", "Emotional + identity vs identity"),
    ("identity_prompt", "control_prompt", "Identity vs control (question change)"),
    ("emotional_identity_prompt", "control_prompt", "Emo + identity vs control (both change)"),
]
DIRECTIONS = [  # (key, baseline answer is YES?, label)
    ("no_to_yes", False, "NO → YES (toward user)"),
    ("yes_to_no", True, "YES → NO (away from user)"),
]
MIN_SWITCHES_POOLED = 10

INK, MUTED, GRID, SURFACE = "#0b0b0b", "#898781", "#e1e0d9", "#ffffff"
SECONDARY = "#52514e"
NOT_BIASED, BIASED = "#9a9891", "#b8302f"


def truth_table():
    """LR labels: sample_id -> bias_any for prompts without identity, and
    identity key -> (sample_id -> biased against that identity)."""
    labels = pd.read_csv(LABELS_FILE).set_index("sample_id")["bias_any"].astype(bool)
    bias_wide = load_term_bias_wide(pd.read_csv(TERM_LABELS_FILE), definition="LR")
    by_identity = {k: identity_bias_series(bias_wide, i) for k, i in IDENTITY_BY_KEY.items()}
    return labels, by_identity


def lookup(df, table):
    """Per-row value from a (no-identity series, identity -> series) table."""
    plain, by_identity = table
    return [
        plain.get(s) if pd.isna(i) else by_identity[i].get(s)
        for s, i in zip(df["sample_id"], df["identity"])
    ]


def build_pairs(df):
    """One row per framed answer joined to the same model's baseline answer
    on the same sample (and the same identity when both prompts have one)."""
    df = df[df["conclusion"].isin(["YES", "NO"])].copy()
    df["yes"] = df["conclusion"].eq("YES")
    df = df.drop_duplicates(["model", "prompt_type", "identity", "sample_id"], keep="last")
    frames = []
    for framed, baseline, label in COMPARISONS:
        f = df[df["prompt_type"] == framed]
        b = df[df["prompt_type"] == baseline][["model", "sample_id", "identity", "yes"]]
        keys = ["model", "sample_id"]
        if b["identity"].notna().any():
            keys.append("identity")
        else:
            b = b.drop(columns="identity")
        p = f.merge(b, on=keys, suffixes=("", "_base"))
        p["comparison"] = label
        frames.append(p)
    pairs = pd.concat(frames, ignore_index=True)
    pairs["switched"] = pairs["yes"] != pairs["yes_base"]
    # truth follows the framed prompt's question (LR label)
    pairs["truth"] = lookup(pairs, truth_table())
    pairs = pairs.dropna(subset=["truth"])
    pairs["truth"] = pairs["truth"].astype(bool)
    return pairs


def wilson(k, n, z=1.96):
    if n == 0:
        return np.nan, np.nan
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def risk_difference(k1, n1, k0, n0):
    """p1 - p0 with Newcombe's hybrid-score 95% CI, and Fisher exact p."""
    if n1 == 0 or n0 == 0:
        return np.nan, np.nan, np.nan, np.nan
    p1, p0 = k1 / n1, k0 / n0
    l1, u1 = wilson(k1, n1)
    l0, u0 = wilson(k0, n0)
    d = p1 - p0
    lo = d - math.sqrt((p1 - l1) ** 2 + (u0 - p0) ** 2)
    hi = d + math.sqrt((u1 - p1) ** 2 + (p0 - l0) ** 2)
    _, p = fisher_exact([[k1, n1 - k1], [k0, n0 - k0]])
    return d, lo, hi, p


def switch_table(pairs):
    rows = []
    for (model, comparison), g in pairs.groupby(["model", "comparison"]):
        for key, base_yes, _ in DIRECTIONS:
            e = g[g["yes_base"] == base_yes]
            row = {"model": model, "comparison": comparison, "direction": key, "n_eligible": len(e),
                   "n_switched": int(e["switched"].sum())}
            b, nb = e[e["truth"]], e[~e["truth"]]
            k1, n1, k0, n0 = int(b["switched"].sum()), len(b), int(nb["switched"].sum()), len(nb)
            d, lo, hi, p = risk_difference(k1, n1, k0, n0)
            row.update({
                "k_biased": k1, "n_biased": n1, "k_not_biased": k0, "n_not_biased": n0,
                "rate_biased": k1 / n1 if n1 else np.nan,
                "rate_not_biased": k0 / n0 if n0 else np.nan,
                "rd": d, "rd_lo": lo, "rd_hi": hi, "fisher_p": p,
            })
            rows.append(row)
    return pd.DataFrame(rows)


def pooled_models(table, comparison, key):
    t = table[(table["comparison"] == comparison) & (table["direction"] == key)]
    keep = t[(t["n_switched"] >= MIN_SWITCHES_POOLED) & (t["n_switched"] < t["n_eligible"])]
    return keep["model"].tolist()


def pooled(pairs, table):
    rows = []
    for _, _, comparison in COMPARISONS:
        for key, base_yes, _ in DIRECTIONS:
            models = pooled_models(table, comparison, key)
            d = pairs[(pairs["comparison"] == comparison) & (pairs["yes_base"] == base_yes)
                      & pairs["model"].isin(models)].copy()
            row = {"comparison": comparison, "direction": key, "models": ", ".join(models), "n": len(d)}
            if len(models) >= 1 and d["truth"].nunique() == 2:
                d["switch"] = d["switched"].astype(int)
                d["biased"] = d["truth"].astype(int)
                formula = "switch ~ biased + C(model)" if len(models) > 1 else "switch ~ biased"
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    fit = smf.gee(formula, groups="sample_id", data=d, family=sm.families.Binomial(),
                                  cov_struct=sm.cov_struct.Exchangeable()).fit()
                b, se = fit.params["biased"], fit.bse["biased"]
                row.update({"log_odds_biased": b, "odds_ratio": math.exp(b),
                            "or_lo": math.exp(b - 1.96 * se), "or_hi": math.exp(b + 1.96 * se),
                            "p_value": fit.pvalues["biased"]})
            rows.append(row)
    return pd.DataFrame(rows)


def style_axis(ax):
    ax.tick_params(length=0, labelsize=8, colors=SECONDARY)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_axisbelow(True)


def save(fig, name):
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(OUT_DIR, f"{name}.{ext}"), dpi=300, facecolor="white")
    plt.close(fig)


def shown_models(table):
    """Models with at least one switch anywhere, most switches first."""
    total = table.groupby("model")["n_switched"].sum()
    return total[total > 0].sort_values(ascending=False).index.tolist()


def plot_switch_by_truth(table):
    models = shown_models(table)
    y = np.arange(len(models))
    fig, axes = plt.subplots(len(COMPARISONS), 2, figsize=(13, len(COMPARISONS) * (0.42 * len(models) + 1.1) + 1),
                             sharex=True, constrained_layout=True)
    for row, (_, _, comparison) in enumerate(COMPARISONS):
        for col, (key, _, dir_label) in enumerate(DIRECTIONS):
            ax = axes[row, col]
            t = (table[(table["comparison"] == comparison) & (table["direction"] == key)]
                 .set_index("model").reindex(models))
            for yi, model in enumerate(models):
                r = t.loc[model]
                if pd.isna(r["n_eligible"]) or r["n_eligible"] == 0:
                    ax.text(50, yi, "no baseline answers in this direction", ha="center", va="center",
                            fontsize=6.5, color=MUTED)
                    continue
                for off, kind, color in [(-0.13, "not_biased", NOT_BIASED), (0.13, "biased", BIASED)]:
                    k, n = r[f"k_{kind}"], r[f"n_{kind}"]
                    if n == 0:
                        continue
                    lo, hi = wilson(k, n)
                    ax.hlines(yi + off, lo * 100, hi * 100, color=color, lw=1.4, alpha=0.6)
                    ax.scatter(k / n * 100, yi + off, s=34, color=color, edgecolor=SURFACE, lw=1.2, zorder=3)
                significant = r["fisher_p"] < 0.05
                rd = "—" if pd.isna(r["rd"]) else f"{r['rd'] * 100:+.1f} pp" + ("*" if significant else "")
                ax.text(1.01, yi - 0.17, rd, transform=ax.get_yaxis_transform(), ha="left", va="center",
                        fontsize=6.5, color=INK if significant else SECONDARY,
                        fontweight="bold" if significant else "normal")
                # not biased first: same order as the dots (grey on top, red below)
                ax.text(1.01, yi + 0.17, f"{int(r['k_not_biased'])}/{int(r['n_not_biased'])} vs "
                                         f"{int(r['k_biased'])}/{int(r['n_biased'])}",
                        transform=ax.get_yaxis_transform(), ha="left", va="center", fontsize=6.5,
                        color=SECONDARY)
            ax.set_yticks(y, models)
            ax.set_ylim(len(models) - 0.5, -0.6)
            ax.set_xlim(-2, 102)
            ax.grid(axis="x", color=GRID, lw=0.6)
            ax.set_title(f"{comparison}  ·  {dir_label}", loc="left", fontsize=9, fontweight="bold")
            style_axis(ax)
    for ax in axes[-1]:
        ax.set_xlabel("% of baseline answers that switched (95% Wilson CI)", fontsize=8)
    handles = [Line2D([], [], marker="o", ls="", color=NOT_BIASED, label="sample not biased"),
               Line2D([], [], marker="o", ls="", color=BIASED, label="sample biased")]
    fig.legend(handles=handles, loc="outside lower center", ncol=2, fontsize=8.5, frameon=False)
    fig.suptitle(
        f"Does the ground truth change how often a model switches its answer? (LR label: biased vs not biased)\n"
        "Same model, same sample, framed vs baseline prompt. Grey ≈ red = switching ignores the data.\n"
        "Right text: biased − not biased (pp; bold * = Fisher p < 0.05), then switched/eligible, not biased vs biased.",
        x=0.01, ha="left", fontsize=10)
    save(fig, "switch-by-truth")


def plot_switch_simple(table):
    """Plain version: only models with at least MIN_SWITCHES_POOLED switches in
    a panel, two bars each (not biased / biased), labelled in words."""
    titles = {"no_to_yes": "Said NO before  →  switched to YES",
              "yes_to_no": "Said YES before  →  switched to NO"}
    panels = {}
    for _, _, comparison in COMPARISONS:
        for key, _, _ in DIRECTIONS:
            t = table[(table["comparison"] == comparison) & (table["direction"] == key)
                      & (table["n_switched"] >= MIN_SWITCHES_POOLED)]
            panels[(comparison, key)] = t.sort_values("n_switched", ascending=False)
    rows_per = [max(1, max(len(panels[(c, k)]) for k, _, _ in DIRECTIONS)) for _, _, c in COMPARISONS]
    fig, axes = plt.subplots(len(COMPARISONS), 2, figsize=(12, sum(0.75 * r + 0.9 for r in rows_per) + 1.2),
                             gridspec_kw={"height_ratios": rows_per}, constrained_layout=True)
    for row, (_, _, comparison) in enumerate(COMPARISONS):
        for col, (key, _, _) in enumerate(DIRECTIONS):
            ax = axes[row, col]
            t = panels[(comparison, key)]
            for yi, r in enumerate(t.itertuples()):
                for off, kind, color in [(-0.19, "not_biased", NOT_BIASED), (0.19, "biased", BIASED)]:
                    k, n = getattr(r, f"k_{kind}"), getattr(r, f"n_{kind}")
                    if n == 0:
                        continue
                    rate = k / n * 100
                    ax.barh(yi + off, rate, height=0.36, color=color, edgecolor=SURFACE, linewidth=1)
                    ax.text(rate + 1.5, yi + off, f"{rate:.0f}%  ({k}/{n})", va="center", ha="left",
                            fontsize=7, color=SECONDARY)
                if not pd.isna(r.rd):
                    star = "  significant" if r.fisher_p < 0.05 else "  not significant"
                    ax.text(1.01, yi, f"{r.rd * 100:+.1f} pp\n{star.strip()}", transform=ax.get_yaxis_transform(),
                            ha="left", va="center", fontsize=7.5,
                            color=INK if r.fisher_p < 0.05 else MUTED)
            if t.empty:
                ax.text(50, 0, f"no model switched {MIN_SWITCHES_POOLED}+ times", ha="center", va="center",
                        fontsize=8, color=MUTED)
            ax.set_yticks(range(len(t)), t["model"].tolist())
            # same row height in both panels of a row, so bars keep one size
            ax.set_ylim(rows_per[row] - 0.5, -0.6)
            ax.set_xlim(0, 140)
            ax.set_xticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
            ax.grid(axis="x", color=GRID, lw=0.6)
            ax.set_title(f"{comparison}\n{titles[key]}", loc="left", fontsize=9, fontweight="bold")
            style_axis(ax)
    handles = [Patch(facecolor=NOT_BIASED, label="data NOT biased (LR label)"),
               Patch(facecolor=BIASED, label="data biased (LR label)")]
    fig.legend(handles=handles, loc="outside lower center", ncol=2, fontsize=9, frameon=False)
    fig.suptitle(
        "When a model changes its answer, does it depend on whether the data is really biased?\n"
        "Bars: % of answers that switched. Red ≠ grey = switching depends on the data; red ≈ grey = it doesn't.\n"
        f"Right: red − grey, in percentage points. Only models with {MIN_SWITCHES_POOLED}+ switches are shown.",
        x=0.01, ha="left", fontsize=10.5)
    save(fig, "switch-by-truth-simple")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    pairs = build_pairs(load_results(discover_models()))
    table = switch_table(pairs)
    table.to_csv(os.path.join(OUT_DIR, "switch-by-truth.csv"), index=False)
    pool = pooled(pairs, table)
    pool.to_csv(os.path.join(OUT_DIR, "switch-by-truth-pooled.csv"), index=False)
    plot_switch_by_truth(table)
    plot_switch_simple(table)

    show = table[table["n_switched"] > 0].copy()
    for kind in ["biased", "not_biased"]:
        show[kind] = show[f"k_{kind}"].astype(str) + "/" + show[f"n_{kind}"].astype(str)
    show["rd_pp"] = (show["rd"] * 100).round(1)
    print("Switch rate, biased vs not biased (models with any switch):")
    print(show[["model", "comparison", "direction", "biased", "not_biased", "rd_pp", "fisher_p"]]
          .round(4).to_string(index=False))
    print("\nPooled GEE (truth coefficient):")
    print(pool.round(4).to_string(index=False))
    print(f"\nSaved switch-by-truth.csv, switch-by-truth-pooled.csv, switch-by-truth (.png, .pdf)"
          f" to {OUT_DIR}")


if __name__ == "__main__":
    main()
