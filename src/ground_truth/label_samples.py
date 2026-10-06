"""
Automated ground-truth bias labels, one per sample, under three fairness
definitions (the ones config.FAIRNESS_DEFINITION can give the model).

Every non-reference group (race vs White, sex vs Male) gets one term per
definition, named like the regression terms (C(race)[T.Asian], C(sex)[T.Female]):

  LR  fit the full-dataset logistic regression
      (denied ~ race + sex + dti + ltv + income + loan_amount + property_value)
      on the sample; BIAS if the term is significant & adverse
      (p < alpha, coef > 0), FAVORED if significant & coef < 0
  DI  four-fifths rule on approval rates (test_disparate_impact.py);
      BIAS if approval_rate / reference approval_rate < 0.8
  DP  equal denial rates (test_demographic_parity.py), tested with Fisher's
      exact test against the reference group (exact, so it holds for small
      groups); BIAS if p < alpha and the denial rate is higher, FAVORED if lower

and per definition derive (no suffix = LR, _di / _dp otherwise):

  bias_any         any term labeled BIAS
  bias_sex_female  the Female term is labeled BIAS
  n_bias_terms     number of BIAS terms

This is independent of any model output — it is the label model conclusions
are compared against. Samples are drawn stratified by race in fixed
proportions, so every race category is present in each sample and none is
pooled. Samples where the LR fit fails get no LR term labels and are flagged
method="failed"; DI and DP need no fit and are labeled for every sample.

Outputs:
  results/ground_truth/sample_labels.csv       one row per sample
  results/ground_truth/sample_term_labels.csv  one row per sample x definition x term
"""

import argparse
import glob
import os
import sys
import warnings

import numpy as np
import pandas as pd
from scipy.stats import fisher_exact

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import PATH_TO_SAMPLES, PATH_TO_GROUND_TRUTH
from data_prep import load_and_clean
from model import REFERENCES, run_regression, extract_ground_truth_labels
from test_demographic_parity import demographic_parity
from test_disparate_impact import disparate_impact, THRESHOLD as DI_THRESHOLD

SEX_TERM = "C(sex)[T.Female]"

# sample_labels.csv column suffix per definition (LR keeps the original names)
DEFINITION_SUFFIX = {"LR": "", "DI": "_di", "DP": "_dp"}

TERM_COLUMNS = [
    "definition",
    "term",
    "log_odds",
    "odds_ratio",
    "p_value",
    "group_rate",
    "ratio",
    "ground_truth_label",
    "method",
]


def term_name(attr, group):
    return f"C({attr})[T.{group}]"


def fit_labels(df, alpha):
    """Term labels from the sample's logit, or None if it cannot be fit."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            model = run_regression(df)
        except Exception:
            return None
    if not model.mle_retvals.get("converged", False):
        return None
    return extract_ground_truth_labels(model, alpha=alpha)


def di_labels(df, threshold=DI_THRESHOLD):
    """Four-fifths rule per group: group_rate is the approval rate, ratio
    the impact ratio vs the reference group."""
    rows = []
    for attr, ref in REFERENCES.items():
        impact = disparate_impact(df, attr, ref, threshold)
        for r in impact[impact["group"] != ref].itertuples():
            rows.append(
                {
                    "term": term_name(attr, r.group),
                    "group_rate": r.selection_rate,
                    "ratio": r.impact_ratio,
                    "ground_truth_label": "BIAS" if r.adverse_impact else "NO_BIAS",
                }
            )
    return pd.DataFrame(rows)


def dp_labels(df, alpha):
    """Denial rate per group vs the reference group, Fisher's exact test:
    group_rate is the denial rate, ratio the parity ratio."""
    rows = []
    for attr, ref in REFERENCES.items():
        parity = demographic_parity(df, attr, ref)
        denials = df.groupby(attr)["denied"].sum()
        n_ref, d_ref = parity.loc[parity["group"] == ref, "n"].iloc[0], denials[ref]
        for r in parity[parity["group"] != ref].itertuples():
            d = denials[r.group]
            _, p = fisher_exact([[d, r.n - d], [d_ref, n_ref - d_ref]])
            sig = p < alpha
            higher = r.parity_diff > 0
            rows.append(
                {
                    "term": term_name(attr, r.group),
                    "p_value": p,
                    "group_rate": r.denial_rate,
                    "ratio": r.parity_ratio,
                    "ground_truth_label": (
                        "BIAS" if sig and higher else "FAVORED" if sig else "NO_BIAS"
                    ),
                }
            )
    return pd.DataFrame(rows)


def summarize(labels, suffix):
    is_bias = labels["ground_truth_label"] == "BIAS"
    return {
        f"bias_any{suffix}": bool(is_bias.any()),
        f"bias_sex_female{suffix}": bool((is_bias & (labels["term"] == SEX_TERM)).any()),
        f"n_bias_terms{suffix}": int(is_bias.sum()),
    }


def label_one_sample(csv_path, alpha=0.05):
    df = load_and_clean(csv_path)
    lr = fit_labels(df, alpha)

    if lr is None:
        lr = pd.DataFrame(columns=TERM_COLUMNS)
        method = "failed"
    else:
        method = "logit"
    lr = lr.copy()
    lr["method"] = method

    di = di_labels(df)
    di["method"] = "rates"
    dp = dp_labels(df, alpha)
    dp["method"] = "fisher"

    sex = lr[lr["term"] == SEX_TERM]
    summary = {
        "n_rows": len(df),
        "method": method,
        "p_sex_female": sex["p_value"].iloc[0] if not sex.empty else np.nan,
        "or_sex_female": sex["odds_ratio"].iloc[0] if not sex.empty else np.nan,
    }

    frames = []
    for definition, labels in [("LR", lr), ("DI", di), ("DP", dp)]:
        summary.update(summarize(labels, DEFINITION_SUFFIX[definition]))
        labels = labels.assign(definition=definition)
        frames.append(labels.reindex(columns=TERM_COLUMNS))
    return summary, pd.concat(frames, ignore_index=True)


def label_samples(samples_dir=PATH_TO_SAMPLES, alpha=0.05, out_suffix=""):
    csv_paths = sorted(glob.glob(os.path.join(samples_dir, "sample_*.csv")))
    if not csv_paths:
        raise FileNotFoundError(f"No sample_*.csv files in {samples_dir}")

    os.makedirs(PATH_TO_GROUND_TRUTH, exist_ok=True)

    summaries, term_frames = [], []
    for k, path in enumerate(csv_paths):
        sample_id = os.path.splitext(os.path.basename(path))[0]
        summary, labels = label_one_sample(path, alpha=alpha)
        summary["sample_id"] = sample_id
        summaries.append(summary)
        labels.insert(0, "sample_id", sample_id)
        term_frames.append(labels)
        if (k + 1) % 50 == 0 or k + 1 == len(csv_paths):
            print(f"  labeled {k + 1}/{len(csv_paths)} samples")

    front = ["sample_id", "n_rows", "method", "bias_any", "bias_sex_female"]
    summary_df = pd.DataFrame(summaries)
    summary_df = summary_df[front + [c for c in summary_df.columns if c not in front]]
    term_df = pd.concat(term_frames, ignore_index=True)

    summary_path = os.path.join(PATH_TO_GROUND_TRUTH, f"sample_labels{out_suffix}.csv")
    term_path = os.path.join(
        PATH_TO_GROUND_TRUTH, f"sample_term_labels{out_suffix}.csv"
    )
    summary_df.to_csv(summary_path, index=False)
    term_df.to_csv(term_path, index=False)

    print(f"\nLabels written to {summary_path}")
    print(f"Per-term detail written to {term_path}")
    print("\nLabel distribution:")
    print(
        summary_df[
            [f"{col}{suffix}" for suffix in DEFINITION_SUFFIX.values()
             for col in ("bias_any", "bias_sex_female")]
        ]
        .mean()
        .rename("fraction_true")
        .to_string()
    )
    print(f"\nRegression failures: {(summary_df['method'] != 'logit').sum()}")
    return summary_df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples-dir", default=PATH_TO_SAMPLES)
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--out-suffix", default="", help="suffix for output filenames")
    args = parser.parse_args()

    label_samples(args.samples_dir, args.alpha, args.out_suffix)
