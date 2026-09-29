"""Test 2 of 4: disparate impact (four-fifths rule) on favorable outcomes.

Compares the proportion of *favorable* outcomes -- a loan originated or
approved -- for each protected group against the reference group:

    selection_rate  P(approved | group) = 1 - P(denied | group)
    impact_diff     selection_rate - reference group's selection_rate
    impact_ratio    selection_rate / reference group's selection_rate
    adverse_impact  impact_ratio < THRESHOLD (0.8, the EEOC four-fifths rule)

Note this is NOT the reciprocal of test_demographic_parity.py's
`parity_ratio`, which is a ratio of *denial* rates. Because approval is
1 - denial, a group denied at 2.4x the reference rate can still be approved
at 0.92x it. Both are reported because the 80% rule is conventionally
defined on the favorable outcome, and it is far less sensitive than the
denial-rate view whenever approval is the common outcome.

Run standalone:  python test_disparate_impact.py [--threshold 0.8]
Output:          results/ground_truth/disparate_impact.csv
"""

import argparse
import os
import sys

import pandas as pd

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import PATH_TO_GROUND_TRUTH
from data_prep import load_population
from model import REFERENCES

OUTPUT_CSV = os.path.join(PATH_TO_GROUND_TRUTH, "disparate_impact.csv")

# EEOC Uniform Guidelines four-fifths rule: a selection rate below 80% of the
# most-favored group's rate is evidence of adverse impact.
THRESHOLD = 0.8


def disparate_impact(df, attr, reference, threshold=THRESHOLD):
    """Selection rate, impact difference and impact ratio per group of `attr`."""
    rates = (
        df.groupby(attr)["denied"]
        .agg(n="size", denial_rate="mean")
        .reset_index()
        .rename(columns={attr: "group"})
    )
    rates["selection_rate"] = 1 - rates["denial_rate"]
    ref_rate = rates.loc[rates["group"] == reference, "selection_rate"].iloc[0]
    rates.insert(0, "attribute", attr)
    rates["reference"] = reference
    rates["impact_diff"] = rates["selection_rate"] - ref_rate
    rates["impact_ratio"] = rates["selection_rate"] / ref_rate
    rates["adverse_impact"] = rates["impact_ratio"] < threshold
    return rates[
        [
            "attribute",
            "group",
            "n",
            "selection_rate",
            "reference",
            "impact_diff",
            "impact_ratio",
            "adverse_impact",
        ]
    ]


def run(df=None, references=REFERENCES, threshold=THRESHOLD):
    """Run the test and write disparate_impact.csv. Reuses `df` if given."""
    if df is None:
        df = load_population()

    impact = pd.concat(
        [
            disparate_impact(df, attr, ref, threshold)
            for attr, ref in references.items()
        ],
        ignore_index=True,
    )

    print(
        f"\nDisparate impact (approval rate per group, four-fifths threshold {threshold}):"
    )
    print(impact.to_string(index=False))

    flagged = impact.loc[impact["adverse_impact"], "group"].tolist()
    print(
        f"\nAdverse impact under the {threshold:.0%} rule: "
        + (", ".join(flagged) if flagged else "none")
    )

    os.makedirs(PATH_TO_GROUND_TRUTH, exist_ok=True)
    impact.to_csv(OUTPUT_CSV, index=False)
    print(f"\nWritten to {OUTPUT_CSV}")
    return impact


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--threshold",
        type=float,
        default=THRESHOLD,
        help="impact ratio below which adverse impact is flagged",
    )
    args = parser.parse_args()

    run(threshold=args.threshold)
