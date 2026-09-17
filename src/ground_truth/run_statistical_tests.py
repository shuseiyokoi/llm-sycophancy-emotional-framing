"""
Demographic parity, tested with a chi-square test of independence.

Demographic parity holds when the denial rate is the same for every group of
a sensitive attribute. Per group we report

    denial_rate   P(denied | group)
    parity_diff   denial_rate - reference group's denial_rate
    parity_ratio  denial_rate / reference group's denial_rate (80%-rule style)

and test each attribute as a whole with a chi-square test of independence
(group x denied).

These are plain functions on a cleaned loan-level frame — run_regression.py
calls them on the full preprocessed data and writes the results.
"""

import sys
import os
import pandas as pd
import numpy as np
import statsmodels.formula.api as smf

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import PATH_TO_DATA, PATH_TO_GROUND_TRUTH
from ground_truth.run_statistical_tests import run_demographic_parity
from ground_truth.run_regression import load_and_clean, run_regression


from scipy.stats import chi2_contingency

# sensitive attribute -> reference group (same references as the regression)
ATTRIBUTES = {"race": "White", "sex": "Male"}
ALPHA = 0.05


def demographic_parity(df, attr, reference):
    """Denial rate, parity difference and parity ratio per group of `attr`."""
    rates = (
        df.groupby(attr)["denied"]
        .agg(n="size", denial_rate="mean")
        .reset_index()
        .rename(columns={attr: "group"})
    )
    ref_rate = rates.loc[rates["group"] == reference, "denial_rate"].iloc[0]
    rates.insert(0, "attribute", attr)
    rates["reference"] = reference
    rates["parity_diff"] = rates["denial_rate"] - ref_rate
    rates["parity_ratio"] = rates["denial_rate"] / ref_rate
    return rates


def chi_square_test(df, attr, alpha=ALPHA):
    """Chi-square test of independence: does the decision depend on `attr`?"""
    table = pd.crosstab(df[attr], df["denied"])
    chi2, p, dof, _ = chi2_contingency(table.values)
    return {
        "attribute": attr,
        "n": int(table.values.sum()),
        "chi2": chi2,
        "dof": dof,
        "p_value": p,
        "parity_violated": p < alpha,
    }


def run_demographic_parity(df, attributes=ATTRIBUTES, alpha=ALPHA):
    """(per-group parity table, per-attribute chi-square table)."""
    parity = pd.concat(
        [demographic_parity(df, attr, ref) for attr, ref in attributes.items()],
        ignore_index=True,
    )
    chi = pd.DataFrame([chi_square_test(df, attr, alpha) for attr in attributes])
    return parity, chi


def main():
    data_path = os.path.join(PATH_TO_DATA, "preprocessed_data.csv")
    results_path = os.path.join(PATH_TO_GROUND_TRUTH, "ground_truth_labels.csv")
    os.makedirs(PATH_TO_GROUND_TRUTH, exist_ok=True)

    df = load_and_clean(data_path)
    print(f"Rows after cleaning: {len(df):,}")

    parity, chi = run_demographic_parity(df)
    print("\nDemographic parity (denial rate per group):")
    print(parity.to_string(index=False))
    print("\nChi-square tests of independence (decision vs attribute):")
    print(chi.to_string(index=False))
    parity.to_csv(
        os.path.join(PATH_TO_GROUND_TRUTH, "demographic_parity.csv"), index=False
    )
    chi.to_csv(os.path.join(PATH_TO_GROUND_TRUTH, "chi_square_tests.csv"), index=False)

    lpm = run_regression(df)
    print(lpm.summary())

    run_demographic_parity()
