"""Test 3 of 4: chi-square test of independence (group x denied).

Asks whether the loan decision depends on a sensitive attribute at all --
the significance test behind the parity gaps that test_demographic_parity.py
describes. A small p-value means demographic parity is violated.

No financial controls are involved; test_logit_population.py is the
controlled version of the same question.

Run standalone:  python test_chi_square.py [--alpha 0.05]
Output:          results/ground_truth/chi_square_tests.csv
"""

import argparse
import os
import sys

import pandas as pd
from scipy.stats import chi2_contingency

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import PATH_TO_GROUND_TRUTH
from data_prep import load_population
from model import REFERENCES, ALPHA

OUTPUT_CSV = os.path.join(PATH_TO_GROUND_TRUTH, "chi_square_tests.csv")


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


def run(df=None, alpha=ALPHA, attributes=tuple(REFERENCES)):
    """Run the test and write chi_square_tests.csv. Reuses `df` if given."""
    if df is None:
        df = load_population()

    chi = pd.DataFrame([chi_square_test(df, attr, alpha) for attr in attributes])

    print("\nChi-square tests of independence (decision vs attribute):")
    print(chi.to_string(index=False))

    os.makedirs(PATH_TO_GROUND_TRUTH, exist_ok=True)
    chi.to_csv(OUTPUT_CSV, index=False)
    print(f"\nWritten to {OUTPUT_CSV}")
    return chi


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alpha", type=float, default=ALPHA)
    args = parser.parse_args()

    run(alpha=args.alpha)
