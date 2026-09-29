"""Test 4 of 4: logistic regression on the full population (HC1 robust SEs).

    denied ~ race + sex + dti + ltv + income + loan_amount + property_value

The controlled version of the parity question: once debt-to-income, LTV,
income, loan amount and property value are held fixed, does race or sex still
move the odds of denial? A significant, adverse coefficient labels that group
BIAS; significant and protective labels it FAVORED.

This is the population-level label. label_samples.py fits the same model
per sample -- those are the labels model answers are scored against.

Run standalone:  python test_logit_population.py [--alpha 0.05]
Outputs (results/ground_truth/):
    ground_truth_labels.csv          BIAS / FAVORED / NO_BIAS per sensitive group
    full_regression_coefficients.csv every coefficient + p-value
    regression_summary.txt           the statsmodels summary table
"""

import argparse
import os
import sys

import pandas as pd

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import PATH_TO_GROUND_TRUTH
from data_prep import load_population
from model import run_regression, extract_ground_truth_labels, ALPHA

LABELS_CSV = os.path.join(PATH_TO_GROUND_TRUTH, "ground_truth_labels.csv")
COEFFICIENTS_CSV = os.path.join(
    PATH_TO_GROUND_TRUTH, "full_regression_coefficients.csv"
)
SUMMARY_TXT = os.path.join(PATH_TO_GROUND_TRUTH, "regression_summary.txt")


def run(df=None, alpha=ALPHA):
    """Fit the population logit and write its three outputs. Reuses `df` if given."""
    if df is None:
        df = load_population()

    lpm = run_regression(df)
    print(lpm.summary())

    os.makedirs(PATH_TO_GROUND_TRUTH, exist_ok=True)
    with open(SUMMARY_TXT, "w") as f:
        f.write(lpm.summary().as_text())

    pd.DataFrame({"lpm_coef": lpm.params, "lpm_p": lpm.pvalues}).rename_axis(
        "term"
    ).reset_index().to_csv(COEFFICIENTS_CSV, index=False)

    labels = extract_ground_truth_labels(lpm, alpha=alpha)
    labels.to_csv(LABELS_CSV, index=False)

    print(f"\nGround truth labels written to {LABELS_CSV}")
    print(labels.to_string(index=False))
    return labels


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alpha", type=float, default=ALPHA)
    args = parser.parse_args()

    run(alpha=args.alpha)
