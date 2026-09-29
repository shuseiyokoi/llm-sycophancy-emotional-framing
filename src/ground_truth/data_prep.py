"""Shared loading and cleaning of the HMDA loan-level data.

Every ground-truth test starts from the same cleaned frame: the three
decision outcomes mapped to a binary `denied`, `dti` parsed out of HMDA's
bucketed strings, the financial controls coerced to numeric, and rows with
an unusable race/sex or a missing control dropped.

Imported by the per-test scripts in this folder and by
gather_data/sample_datasets.py.
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import PATH_TO_DATA

# the full-population input every test in this folder reads
POPULATION_CSV = os.path.join(PATH_TO_DATA, "preprocessed_data.csv")


def load_and_clean(path):
    df = pd.read_csv(path)

    rename_map = {
        "derived_race": "race",
        "derived_sex": "sex",
        # "derived_ethnicity": "ethnicity",
        "debt_to_income_ratio": "dti",
        "loan_to_value_ratio": "ltv",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    keep_actions = {
        "Loan originated": 0,
        "Application approved but not accepted": 0,
        "Application denied": 1,
    }
    df = df[df["action_taken"].isin(keep_actions)].copy()
    df["denied"] = df["action_taken"].map(keep_actions)

    def dti_to_numeric(val):
        if pd.isna(val):
            return np.nan
        s = str(val).strip().replace("%", "")
        if "-<" in s:
            low, high = s.split("-<")
            return (float(low) + float(high)) / 2
        if "-" in s and not s.startswith("-"):
            low, high = s.split("-")
            return (float(low) + float(high)) / 2
        if s.startswith("<"):
            return float(s[1:]) - 2.5
        if s.startswith(">"):
            return float(s[1:]) + 2.5
        try:
            return float(s)
        except ValueError:
            return np.nan

    df["dti"] = df["dti"].apply(dti_to_numeric)
    for col in ["ltv", "income", "loan_amount", "property_value"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    required = [
        "race",
        "sex",
        # "ethnicity",
        "dti",
        "ltv",
        "income",
        "loan_amount",
        "property_value",
        "denied",
    ]
    df = df.dropna(subset=required)

    df = df[~df["race"].isin(["Race Not Available", "Free Form Text Only"])]
    df = df[~df["sex"].isin(["Sex Not Available"])]
    # df = df[~df["ethnicity"].isin(["Ethnicity Not Available"])]
    return df


def load_population():
    """The cleaned full population, with a row count printed."""
    df = load_and_clean(POPULATION_CSV)
    print(f"Rows after cleaning: {len(df):,}")
    return df
