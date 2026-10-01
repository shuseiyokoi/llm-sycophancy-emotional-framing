"""
Draw N samples of X loan-level rows and render a per-sample summary table.

Each sample i produces:
  data/gather_data/samples/sample_{i:04d}.csv          raw rows (ground truth input)
  data/gather_data/samples/sample_{i:04d}_summary.txt  summary table (model input)
plus a manifest.csv describing all samples, and population_by_{col}.csv
with the eligible population per stratum (rows, share, denial rate) and the
rows drawn from each stratum per sample.

Rows are drawn without replacement within a sample (seed = SAMPLE_SEED + i),
from the subset of preprocessed_data.csv that survives the ground-truth
cleaning step — so the model and the regression always see the same rows.
With STRATIFY_BY set, each stratum (e.g. race) is drawn separately with the
row counts given by STRATA_ALLOCATION, then the rows are shuffled together.
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import (
    PATH_TO_DATA,
    PATH_TO_SAMPLES,
    N_SAMPLES,
    SAMPLE_SIZE,
    SAMPLE_SEED,
    STRATA_ALLOCATION,
    STRATIFY_BY,
    USE_SUMMARY,
)
from summarize_data import build_summary

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "ground_truth"))
from data_prep import load_and_clean


def load_eligible_rows(data_path):
    """Rows of preprocessed_data.csv (original columns) that survive cleaning,
    plus the cleaned frame on the same index (its renamed columns, e.g. race,
    are what strata are defined on)."""
    raw = pd.read_csv(data_path, na_values=["NA", "None", "Exempt", "", " "])
    clean = load_and_clean(data_path)  # index is preserved through cleaning
    return raw.loc[clean.index], clean


def stratum_sizes(counts, sample_size, allocation):
    """Rows to draw from each stratum. counts: population rows per stratum."""
    if allocation == "equal":
        base, extra = divmod(sample_size, len(counts))
        # leftover rows go to the largest strata, one each
        sizes = pd.Series(base, index=counts.index)
        sizes[counts.sort_values(ascending=False).index[:extra]] += 1
    elif allocation == "proportional":
        # largest-remainder rounding so the sizes sum to sample_size exactly
        exact = counts / counts.sum() * sample_size
        sizes = exact.astype(int)
        short = sample_size - sizes.sum()
        sizes[(exact - sizes).sort_values(ascending=False).index[:short]] += 1
    else:
        raise ValueError(f"unknown STRATA_ALLOCATION {allocation!r}")

    too_small = sizes[sizes > counts]
    if not too_small.empty:
        raise ValueError(
            "strata too small for the requested allocation: "
            + ", ".join(f"{k} needs {sizes[k]}, has {counts[k]}" for k in too_small.index)
        )
    return sizes


def population_table(clean, col, sizes):
    """Eligible population per stratum of `col`, plus the rows drawn per sample."""
    grp = clean.groupby(col)
    pop = pd.DataFrame(
        {
            "population_rows": grp.size(),
            "population_denial_rate": grp["denied"].mean(),
        }
    )
    pop["population_share"] = pop["population_rows"] / pop["population_rows"].sum()
    if sizes is not None:
        pop["sample_rows"] = sizes
        pop["sample_share"] = pop["sample_rows"] / pop["sample_rows"].sum()
    pop = pop.sort_values("population_rows", ascending=False)
    pop.index.name = col
    return pop.reset_index()


def draw_sample(eligible, sample_size, seed, strata, sizes):
    """strata: per-row stratum labels aligned to eligible, or None."""
    if strata is None:
        return eligible.sample(n=sample_size, random_state=seed)
    rng = np.random.RandomState(seed)
    parts = [
        eligible[strata == stratum].sample(n=n, random_state=rng)
        for stratum, n in sizes.items()
    ]
    # shuffle so the prompt's raw rows are not grouped by stratum
    return pd.concat(parts).sample(frac=1, random_state=rng)


def sample_datasets(
    n_samples=N_SAMPLES,
    sample_size=SAMPLE_SIZE,
    seed=SAMPLE_SEED,
    stratify_by=STRATIFY_BY,
    allocation=STRATA_ALLOCATION,
):
    os.makedirs(PATH_TO_SAMPLES, exist_ok=True)

    eligible, clean = load_eligible_rows(f"{PATH_TO_DATA}preprocessed_data.csv")
    print(f"Eligible rows after cleaning: {len(eligible):,}")

    if sample_size > len(eligible):
        raise ValueError(
            f"sample_size {sample_size} exceeds eligible rows {len(eligible)}"
        )

    strata, sizes = None, None
    if stratify_by is not None:
        strata = clean[stratify_by]
        sizes = stratum_sizes(strata.value_counts(), sample_size, allocation)
        print(f"Stratified on {stratify_by} ({allocation}):")
        print(sizes.to_string())

    # population is reported by race even for a simple random draw
    pop_col = stratify_by or "race"
    pop = population_table(clean, pop_col, sizes)
    pop_path = os.path.join(PATH_TO_SAMPLES, f"population_by_{pop_col}.csv")
    pop.to_csv(pop_path, index=False)
    print(f"Population by {pop_col} written to {pop_path}")
    print(pop.to_string(index=False))

    manifest = []
    for i in range(n_samples):
        sample = draw_sample(eligible, sample_size, seed + i, strata, sizes)

        csv_path = os.path.join(PATH_TO_SAMPLES, f"sample_{i:04d}.csv")
        txt_path = os.path.join(PATH_TO_SAMPLES, f"sample_{i:04d}_summary.txt")

        sample.to_csv(csv_path, index=False)

        if USE_SUMMARY:
            summary_text = build_summary(sample).to_string(index=False)
            with open(txt_path, "w") as f:
                f.write(summary_text)
            summary_name = os.path.basename(txt_path)
            summary_chars = len(summary_text)
        else:
            summary_name = None
            summary_chars = None

        manifest.append(
            {
                "sample_id": f"sample_{i:04d}",
                "seed": seed + i,
                "n_rows": sample_size,
                "stratify_by": stratify_by,
                "allocation": allocation if stratify_by else None,
                "csv": os.path.basename(csv_path),
                "summary": summary_name,
                "summary_chars": summary_chars,
            }
        )

        if (i + 1) % 50 == 0 or i + 1 == n_samples:
            print(f"  wrote {i + 1}/{n_samples} samples")

    manifest_df = pd.DataFrame(manifest)
    manifest_df.to_csv(os.path.join(PATH_TO_SAMPLES, "manifest.csv"), index=False)
    print(f"Manifest written to {PATH_TO_SAMPLES}manifest.csv")
    return manifest_df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-samples", type=int, default=N_SAMPLES)
    parser.add_argument("--sample-size", type=int, default=SAMPLE_SIZE)
    parser.add_argument("--seed", type=int, default=SAMPLE_SEED)
    parser.add_argument(
        "--stratify-by", default=STRATIFY_BY, help='column to stratify on, or "none"'
    )
    parser.add_argument(
        "--allocation", default=STRATA_ALLOCATION, choices=["equal", "proportional"]
    )
    args = parser.parse_args()

    stratify_by = None if args.stratify_by in (None, "none") else args.stratify_by
    sample_datasets(
        args.n_samples, args.sample_size, args.seed, stratify_by, args.allocation
    )
