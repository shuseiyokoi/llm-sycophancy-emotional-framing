"""Run every full-population ground-truth test in order.

Each test is also runnable on its own (python test_chi_square.py, etc.);
this loads and cleans the population once and hands the same frame to all
four, which is the only thing running them together saves.

label_samples.py is deliberately not called here -- it reads the per-sample
CSVs rather than the population file, and stays on its own
`python main.py --label-samples` flag.

Run:  python run_all.py     (or: cd src && python main.py --ground-truth)
"""

import argparse
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from data_prep import load_population
from model import ALPHA
import test_demographic_parity
import test_disparate_impact
import test_chi_square
import test_logit_population


def run_ground_truth(alpha=ALPHA):
    df = load_population()

    test_demographic_parity.run(df)
    test_disparate_impact.run(df)
    test_chi_square.run(df, alpha=alpha)
    test_logit_population.run(df, alpha=alpha)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--alpha", type=float, default=ALPHA, help="significance level for both tests"
    )
    args = parser.parse_args()

    run_ground_truth(args.alpha)
