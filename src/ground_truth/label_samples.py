"""
Automated ground-truth bias labels, one per sample.

For every sample CSV in data/gather_data/samples/, fit the same logistic
regression used for the full-dataset ground truth
(denied ~ race + sex + dti + ltv + income + loan_amount + property_value)
on that sample's raw rows and derive:

  bias_any         any sensitive term significant & adverse (p < alpha, coef > 0)
  bias_sex_female  the Female sex term is significant & adverse

This is independent of any model output — it is the label model conclusions
are compared against. Rare race categories are collapsed into one bucket
before fitting to avoid perfect separation; samples where the fit still fails
get no term labels and are flagged method="failed".

Outputs:
  results/ground_truth/sample_labels.csv       one row per sample
  results/ground_truth/sample_term_labels.csv  one row per sample x term
"""

import argparse
import glob
import os
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import PATH_TO_SAMPLES, PATH_TO_GROUND_TRUTH
from ground_truth.run_regression import (
    load_and_clean,
    run_regression,
    extract_ground_truth_labels,
)

SEX_TERM = "C(sex)[T.Female]"

MIN_CATEGORY_ROWS = 25  # race categories smaller than this are pooled


def collapse_rare_races(df, min_rows=MIN_CATEGORY_ROWS):
    counts = df["race"].value_counts()
    rare = counts[counts < min_rows].index
    if len(rare) > 0:
        df = df.copy()
        df["race"] = df["race"].where(
            ~df["race"].isin(rare), "Other or multiple minority races"
        )
    return df


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


def label_one_sample(csv_path, alpha=0.05):
    df = collapse_rare_races(load_and_clean(csv_path))
    labels = fit_labels(df, alpha)

    if labels is None:
        labels = pd.DataFrame(
            columns=["term", "log_odds", "odds_ratio", "p_value", "ground_truth_label"]
        )
        method = "failed"
    else:
        method = "logit"
    labels = labels.copy()
    labels["method"] = method

    is_bias = labels["ground_truth_label"] == "BIAS"
    sex = labels[labels["term"] == SEX_TERM]

    summary = {
        "n_rows": len(df),
        "method": method,
        "bias_any": bool(is_bias.any()),
        "bias_sex_female": bool((sex["ground_truth_label"] == "BIAS").any()),
        "p_sex_female": sex["p_value"].iloc[0] if not sex.empty else np.nan,
        "or_sex_female": sex["odds_ratio"].iloc[0] if not sex.empty else np.nan,
        "n_bias_terms": int(is_bias.sum()),
    }
    return summary, labels


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

    front = ["sample_id", "n_rows", "method"]
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
        summary_df[["bias_any", "bias_sex_female"]]
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
