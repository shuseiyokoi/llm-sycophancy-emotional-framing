"""Test 1 of 4: demographic parity (denial rate per group).

Demographic parity holds when the denial rate is the same for every group of
a sensitive attribute. Per group we report

    denial_rate   P(denied | group)
    parity_diff   denial_rate - reference group's denial_rate
    parity_ratio  denial_rate / reference group's denial_rate (80%-rule style)

This is the descriptive half; test_chi_square.py is the significance test for
the same question, and test_logit_population.py asks it again with financial
controls held fixed. test_disparate_impact.py reports the same comparison on
the favorable outcome (approval) instead, under the four-fifths rule.

Run standalone:  python test_demographic_parity.py
Output:          results/ground_truth/demographic_parity.csv
"""

import argparse
import os
import sys

import pandas as pd

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import PATH_TO_GROUND_TRUTH
from data_prep import load_population
from model import REFERENCES

OUTPUT_CSV = os.path.join(PATH_TO_GROUND_TRUTH, "demographic_parity.csv")


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


def run(df=None, references=REFERENCES):
    """Run the test and write demographic_parity.csv. Reuses `df` if given."""
    if df is None:
        df = load_population()

    parity = pd.concat(
        [demographic_parity(df, attr, ref) for attr, ref in references.items()],
        ignore_index=True,
    )

    print("\nDemographic parity (denial rate per group):")
    print(parity.to_string(index=False))

    os.makedirs(PATH_TO_GROUND_TRUTH, exist_ok=True)
    parity.to_csv(OUTPUT_CSV, index=False)
    print(f"\nWritten to {OUTPUT_CSV}")
    return parity


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()
