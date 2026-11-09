"""What the ground truth looks like on its own, before any model answer.

Reads only the ground-truth CSVs (population tests + label_samples.py output)
and draws five figures:

    gt-overview-population-vs-samples  LR: each sample's log-odds per term,
                                       coloured by its label, vs the
                                       population log-odds
    gt-overview-label-rates            % of samples BIAS / FAVORED / NO_BIAS
                                       per term, one panel per definition,
                                       with the population label
    gt-overview-barcode                every sample's label per term, same
                                       sample-id order in each definition
    gt-overview-p-values               per-sample p-values (LR, DP) vs alpha:
                                       how many labels sit near the cut-off
    gt-overview-identity-truth         share of the samples each identity sees
                                       that are biased against it (what the
                                       identity prompts are scored on)

plus gt-overview-summary.csv (label counts per definition x term).

Outputs go to results/ground_truth/ (each figure as .png and .pdf).

Run:  cd src/ground_truth && python plot_ground_truth.py
"""

import os
import sys

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Patch, Rectangle
from scipy.stats import fisher_exact

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "analyze_results"))
from config import PATH_TO_GROUND_TRUTH, IDENTITIES, identity_sample_ids
from model import ALPHA
from compare_to_ground_truth import load_term_bias_wide, identity_bias_series

SAMPLE_LABELS = os.path.join(PATH_TO_GROUND_TRUTH, "sample_labels_l2.csv")
TERM_LABELS = os.path.join(PATH_TO_GROUND_TRUTH, "sample_term_labels_l2.csv")
POP_LR = os.path.join(PATH_TO_GROUND_TRUTH, "ground_truth_labels.csv")
POP_DI = os.path.join(PATH_TO_GROUND_TRUTH, "disparate_impact.csv")
POP_DP = os.path.join(PATH_TO_GROUND_TRUTH, "demographic_parity.csv")

DEFINITIONS = [
    ("LR", "LR: logistic regression, p < 0.05 & adverse"),
    ("DI", "DI: four-fifths rule on approval rates"),
    ("DP", "DP: denial rate vs reference, Fisher p < 0.05"),
]
TERMS = [  # (term, short label)
    ("C(race)[T.Black or African American]", "Black"),
    ("C(race)[T.Hispanic or Latino]", "Hispanic"),
    ("C(race)[T.Asian]", "Asian"),
    ("C(race)[T.Other]", "Other race"),
    ("C(sex)[T.Female]", "Female"),
    ("C(sex)[T.Joint]", "Joint"),
]
TERM_LABEL = dict(TERMS)
TERM_ORDER = [t for t, _ in TERMS]

INK, MUTED, GRID, SURFACE = "#0b0b0b", "#898781", "#e1e0d9", "#ffffff"
SECONDARY = "#52514e"
# label colours: red = adverse, blue = favoured, light grey = no finding
LABEL_COLOR = {"BIAS": "#b8302f", "FAVORED": "#2a78d6", "NO_BIAS": "#e8e7e2"}
LABEL_TEXT = {"BIAS": "BIAS (adverse)", "FAVORED": "FAVORED", "NO_BIAS": "no significant finding"}
SEQUENTIAL = LinearSegmentedColormap.from_list("seq", ["#f6f5f2", "#ef8a89", "#b8302f", "#6e1716"])


def style_axis(ax):
    ax.tick_params(length=0, labelsize=8, colors=SECONDARY)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_axisbelow(True)


def save(fig, name):
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(PATH_TO_GROUND_TRUTH, f"{name}.{ext}"), dpi=300, facecolor="white")
    plt.close(fig)


def label_legend(fig, labels=("BIAS", "FAVORED", "NO_BIAS")):
    handles = [Patch(facecolor=LABEL_COLOR[l], label=LABEL_TEXT[l]) for l in labels]
    fig.legend(handles=handles, loc="outside lower center", ncol=len(handles), fontsize=8.5, frameon=False)


def population_labels():
    """definition -> term -> population label, from the full-population tests."""
    lr = pd.read_csv(POP_LR).set_index("term")["ground_truth_label"].to_dict()

    di_table = pd.read_csv(POP_DI)
    di_table = di_table[di_table["group"] != di_table["reference"]]
    di = {f"C({r.attribute})[T.{r.group}]": "BIAS" if r.adverse_impact else "NO_BIAS"
          for r in di_table.itertuples()}

    # demographic_parity.csv has n and denial rate only; recover the counts
    # and run the same Fisher test label_samples.py uses per sample
    dp_table = pd.read_csv(POP_DP)
    dp = {}
    for r in dp_table[dp_table["group"] != dp_table["reference"]].itertuples():
        ref = dp_table[(dp_table["attribute"] == r.attribute) & (dp_table["group"] == r.reference)].iloc[0]
        d, d_ref = round(r.n * r.denial_rate), round(ref["n"] * ref["denial_rate"])
        _, p = fisher_exact([[d, r.n - d], [d_ref, ref["n"] - d_ref]])
        dp[f"C({r.attribute})[T.{r.group}]"] = (
            "BIAS" if p < ALPHA and r.parity_diff > 0 else "FAVORED" if p < ALPHA else "NO_BIAS")
    return {"LR": lr, "DI": di, "DP": dp}


def label_counts(terms):
    counts = (terms.groupby(["definition", "term"])["ground_truth_label"].value_counts()
              .unstack(fill_value=0).reindex(columns=["BIAS", "FAVORED", "NO_BIAS"], fill_value=0))
    return counts


def plot_population_vs_samples(terms, pop):
    lr = terms[terms["definition"] == "LR"]
    pop_lr = pd.read_csv(POP_LR).set_index("term")
    rng = np.random.default_rng(0)
    fig, ax = plt.subplots(figsize=(10, 5.2), constrained_layout=True)
    ax.axvline(0, color=MUTED, lw=1, ls="--", zorder=1)
    for yi, term in enumerate(TERM_ORDER):
        g = lr[lr["term"] == term]
        jitter = rng.uniform(-0.28, 0.28, len(g))
        # draw NO_BIAS first so coloured dots sit on top
        for label in ["NO_BIAS", "FAVORED", "BIAS"]:
            m = (g["ground_truth_label"] == label).to_numpy()
            color = "#c9c7c0" if label == "NO_BIAS" else LABEL_COLOR[label]
            ax.scatter(g["log_odds"].to_numpy()[m], yi + jitter[m], s=9, color=color,
                       edgecolor="none", alpha=0.85, zorder=2)
        b = pop_lr.loc[term, "log_odds"]
        ax.plot([b, b], [yi - 0.4, yi + 0.4], color=INK, lw=2.4, zorder=4)
        n_bias = int((g["ground_truth_label"] == "BIAS").sum())
        n_fav = int((g["ground_truth_label"] == "FAVORED").sum())
        ax.text(1.01, yi, f"OR {pop_lr.loc[term, 'odds_ratio']:.2f} ({pop['LR'][term]})\n"
                          f"BIAS {n_bias}/300 · FAVORED {n_fav}/300",
                transform=ax.get_yaxis_transform(), va="center", ha="left", fontsize=7.5, color=SECONDARY)
    ax.set_yticks(range(len(TERMS)), [TERM_LABEL[t] for t in TERM_ORDER])
    ax.set_ylim(len(TERMS) - 0.5, -0.5)
    ax.set_xlim(-2.5, 2.5)
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.set_xlabel("log-odds of denial vs reference (White / Male), controls held fixed   "
                  "← less likely denied | more likely denied →", fontsize=8)
    ax.text(1.01, -0.75, "population (88k rows)\nper-sample label count",
            transform=ax.get_yaxis_transform(), ha="left", va="center", fontsize=7, color=MUTED)
    style_axis(ax)
    handles = [Patch(facecolor=LABEL_COLOR["BIAS"], label="sample labeled BIAS"),
               Patch(facecolor=LABEL_COLOR["FAVORED"], label="sample labeled FAVORED"),
               Patch(facecolor="#c9c7c0", label="sample: not significant"),
               plt.Line2D([], [], color=INK, lw=2.4, label="population log-odds")]
    fig.legend(handles=handles, loc="outside lower center", ncol=4, fontsize=8.5, frameon=False)
    fig.suptitle("LR ground truth: one dot per sample (2000 rows each). The population effect is real, "
                 "but a single sample\nonly reaches significance some of the time — "
                 "a sample's label is partly a draw. Dots beyond ±2.5 are cut off.",
                 x=0.01, ha="left", fontsize=10)
    save(fig, "gt-overview-population-vs-samples")


def plot_label_rates(counts, pop):
    fig, axes = plt.subplots(1, 3, figsize=(14, 3.8), sharey=True, constrained_layout=True)
    y = np.arange(len(TERMS))
    for ax, (definition, title) in zip(axes, DEFINITIONS):
        c = counts.loc[definition].reindex(TERM_ORDER) / 300 * 100
        left = np.zeros(len(TERMS))
        for label in ["BIAS", "FAVORED", "NO_BIAS"]:
            ax.barh(y, c[label], left=left, height=0.62, color=LABEL_COLOR[label],
                    edgecolor=SURFACE, linewidth=2)
            left += c[label].to_numpy()
        for yi, term in enumerate(TERM_ORDER):
            if c.loc[term, "BIAS"] >= 6:
                ax.text(c.loc[term, "BIAS"] / 2, yi, f"{c.loc[term, 'BIAS']:.0f}%",
                        ha="center", va="center", fontsize=7.5, color="white")
            ax.text(1.02, yi, pop[definition].get(term, "—"), transform=ax.get_yaxis_transform(),
                    ha="left", va="center", fontsize=7.5, color=SECONDARY)
        ax.text(1.02, -0.85, "population", transform=ax.get_yaxis_transform(),
                ha="left", va="center", fontsize=7, color=MUTED)
        ax.set_title(title, loc="left", fontsize=9.5, fontweight="bold")
        ax.set_xlim(0, 100)
        ax.set_xticks([0, 25, 50, 75, 100])
        ax.set_xlabel("% of 300 samples", fontsize=8)
        style_axis(ax)
    axes[0].set_yticks(y, [TERM_LABEL[t] for t in TERM_ORDER])
    axes[0].set_ylim(len(TERMS) - 0.5, -1.3)
    label_legend(fig)
    fig.suptitle("How often each term is labeled in a sample, under each fairness definition. "
                 "Same data, very different truths:\nDI almost never fires, DP fires for most samples, "
                 "LR sits in between.",
                 x=0.01, ha="left", fontsize=10)
    save(fig, "gt-overview-label-rates")


def plot_barcode(terms, samples):
    # plain sample_id order, the same in every panel (no sorting by label)
    order = sorted(samples["sample_id"])
    code = {"NO_BIAS": 0, "FAVORED": 1, "BIAS": 2}
    cmap = plt.matplotlib.colors.ListedColormap(
        [LABEL_COLOR["NO_BIAS"], LABEL_COLOR["FAVORED"], LABEL_COLOR["BIAS"]])

    any_cols = {"LR": "bias_any", "DI": "bias_any_di", "DP": "bias_any_dp"}
    fig, axes = plt.subplots(4, 1, figsize=(14, 8.4), constrained_layout=True,
                             gridspec_kw={"height_ratios": [6, 6, 6, 3]})
    for ax, (definition, title) in zip(axes, DEFINITIONS):
        wide = (terms[terms["definition"] == definition]
                .pivot(index="term", columns="sample_id", values="ground_truth_label")
                .reindex(index=TERM_ORDER, columns=order).replace(code).astype(float))
        ax.imshow(wide.values, aspect="auto", cmap=cmap, vmin=0, vmax=2, interpolation="nearest")
        n_any = int(samples[any_cols[definition]].sum())
        ax.set_title(f"{title}   —   bias_any in {n_any}/300 samples",
                     loc="left", fontsize=9.5, fontweight="bold")
        ax.set_yticks(range(len(TERMS)), [TERM_LABEL[t] for t in TERM_ORDER])
        ax.set_xticks([])
        style_axis(ax)

    # bottom strip: bias_any per definition, same sample order
    any_matrix = samples.set_index("sample_id").loc[order, list(any_cols.values())].T.astype(float)
    axes[3].imshow(any_matrix.values * 2, aspect="auto", cmap=cmap, vmin=0, vmax=2, interpolation="nearest")
    axes[3].set_yticks(range(3), [f"bias_any ({d})" for d in any_cols])
    axes[3].set_xlabel("300 samples, sample_0000 → sample_0299 (same order in every panel)", fontsize=8)
    axes[3].set_xticks([])
    style_axis(axes[3])

    lr, di, dp = (samples[c] for c in any_cols.values())
    label_legend(fig)
    fig.suptitle(
        "Every sample's label, term by term. Each column is one sample, in sample-id order, aligned across panels.\n"
        f"bias_any agreement: LR ∧ DP {int((lr & dp).sum())}, DP only {int((dp & ~lr).sum())}, "
        f"LR only {int((lr & ~dp).sum())}, neither {int((~lr & ~dp).sum())}; "
        f"the {int(di.sum())} DI samples are all inside LR ∧ DP.",
        x=0.01, ha="left", fontsize=10)
    save(fig, "gt-overview-barcode")


def plot_p_values(terms):
    bins = np.logspace(-8, 0, 33)
    fig, axes = plt.subplots(len(TERMS), 2, figsize=(11, 8.5), sharex=True, constrained_layout=True)
    for col, definition in enumerate(["LR", "DP"]):
        g_def = terms[terms["definition"] == definition]
        for row, term in enumerate(TERM_ORDER):
            ax = axes[row, col]
            g = g_def[g_def["term"] == term]
            p = g["p_value"].clip(lower=1e-8)
            # stack histogram by label so colour shows the direction too
            stacks = [p[g["ground_truth_label"] == l] for l in ["BIAS", "FAVORED", "NO_BIAS"]]
            ax.hist(stacks, bins=bins, stacked=True, edgecolor=SURFACE, linewidth=0.5,
                    color=[LABEL_COLOR["BIAS"], LABEL_COLOR["FAVORED"], "#c9c7c0"])
            ax.axvline(ALPHA, color=INK, lw=1.2)
            near = ((g["p_value"] > 0.01) & (g["p_value"] < 0.10)).mean() * 100
            ax.text(0.01, 0.92, f"{TERM_LABEL[term]}   ·   {near:.0f}% of samples have 0.01 < p < 0.10",
                    transform=ax.transAxes, ha="left", va="top", fontsize=7.5, color=SECONDARY)
            ax.set_xscale("log")
            ax.set_yticks([])
            ax.grid(axis="x", color=GRID, lw=0.6)
            style_axis(ax)
        axes[0, col].set_title(f"{definition} p-values", loc="left", fontsize=9.5, fontweight="bold")
        axes[-1, col].set_xlabel("p-value (log scale; < 1e-8 shown at 1e-8). Line = α 0.05", fontsize=8)
    label_legend(fig)
    fig.suptitle("How close each sample's label is to the 0.05 cut-off. Mass piled against the line "
                 "= labels that a slightly\ndifferent sample would flip. (DI has no p-value: it is a "
                 "fixed 0.8 ratio threshold.)", x=0.01, ha="left", fontsize=10)
    save(fig, "gt-overview-p-values")


def identity_truth(term_labels, sample_ids):
    rows = []
    for definition, _ in DEFINITIONS:
        bias_wide = load_term_bias_wide(term_labels, definition=definition)
        for identity in IDENTITIES:
            truth = identity_bias_series(bias_wide, identity)
            seen = identity_sample_ids(sample_ids, identity)
            rows.append({
                "definition": definition,
                "identity": identity["key"],
                "n_seen": len(seen),
                "n_biased_seen": int(truth.reindex(seen).sum()),
                "n_biased_all": int(truth.sum()),
            })
    return pd.DataFrame(rows)


def plot_identity_truth(ident):
    keys = [i["key"] for i in IDENTITIES]
    fig, ax = plt.subplots(figsize=(12, 3.4), constrained_layout=True)
    for yi, (definition, title) in enumerate(DEFINITIONS):
        t = ident[ident["definition"] == definition].set_index("identity")
        for xi, key in enumerate(keys):
            r = t.loc[key]
            rate = r["n_biased_seen"] / r["n_seen"]
            ax.add_patch(Rectangle((xi - 0.5, yi - 0.5), 1, 1, facecolor=SEQUENTIAL(rate),
                                   edgecolor=SURFACE, linewidth=2))
            dark = rate > 0.45
            ax.text(xi, yi - 0.12, f"{int(r['n_biased_seen'])}/{int(r['n_seen'])}", ha="center",
                    va="center", fontsize=8.5, color="white" if dark else INK)
            ax.text(xi, yi + 0.24, f"all 300: {r['n_biased_all'] / 3:.0f}%", ha="center", va="center",
                    fontsize=6.5, color="white" if dark else SECONDARY)
    ax.set_xlim(-0.5, len(keys) - 0.5)
    ax.set_ylim(len(DEFINITIONS) - 0.5, -0.5)
    ax.set_xticks(range(len(keys)), [k.replace("_", "\n") for k in keys])
    ax.xaxis.tick_top()
    ax.set_yticks(range(len(DEFINITIONS)), [d for d, _ in DEFINITIONS])
    style_axis(ax)
    sm = plt.cm.ScalarMappable(cmap=SEQUENTIAL, norm=plt.Normalize(0, 100))
    cbar = fig.colorbar(sm, ax=ax, location="right", shrink=0.8, aspect=15, pad=0.01)
    cbar.set_label("% of the identity's samples biased", fontsize=8)
    cbar.ax.tick_params(labelsize=7, length=0)
    cbar.outline.set_visible(False)
    fig.suptitle("Truth for the identity prompts: biased against that identity's own race (if not White) "
                 "or Female (if female).\nCell: biased / samples that identity is shown (round-robin split); "
                 "small text: rate over all 300 samples. White male can never be biased.",
                 x=0.01, ha="left", fontsize=10)
    save(fig, "gt-overview-identity-truth")


def main():
    samples = pd.read_csv(SAMPLE_LABELS)
    terms = pd.read_csv(TERM_LABELS)
    pop = population_labels()

    counts = label_counts(terms)
    summary = counts.reset_index()
    summary["population_label"] = [pop[d].get(t, "") for d, t in zip(summary["definition"], summary["term"])]
    summary.to_csv(os.path.join(PATH_TO_GROUND_TRUTH, "gt-overview-summary.csv"), index=False)

    plot_population_vs_samples(terms, pop)
    plot_label_rates(counts, pop)
    plot_barcode(terms, samples)
    plot_p_values(terms)
    ident = identity_truth(terms, samples["sample_id"].tolist())
    plot_identity_truth(ident)

    print("Label counts per definition x term (of 300 samples):")
    print(summary.to_string(index=False))
    print("\nbias_any:", {c: int(samples[c].sum()) for c in ["bias_any", "bias_any_di", "bias_any_dp"]})
    print("\nIdentity truth (biased / seen):")
    print(ident.pivot(index="identity", columns="definition", values="n_biased_seen").to_string())
    print(f"\nSaved gt-overview-* (.png, .pdf) and gt-overview-summary.csv to {PATH_TO_GROUND_TRUTH}")


if __name__ == "__main__":
    main()
