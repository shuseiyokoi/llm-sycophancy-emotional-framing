"""
Ground truth bias labeling via linear probability model (OLS, HC1 SEs) on HMDA loan-level data.

Model: denied ~ race + sex + dti + ltv + income + loan_amount + property_value
Label: significant (p < alpha) & positive coef -> BIAS; significant & negative -> FAVORED; else NO_BIAS
"""

import sys
import os
import pandas as pd
import numpy as np
import statsmodels.formula.api as smf

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import PATH_TO_DATA, PATH_TO_GROUND_TRUTH


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


def run_regression(
    df,
    race_ref="White",
    sex_ref="Male",
    # eth_ref="Not Hispanic or Latino"
):
    df = df.copy()
    for col, ref in [
        ("race", race_ref),
        ("sex", sex_ref),
        #  ("ethnicity", eth_ref)
    ]:
        cats = [ref] + [c for c in sorted(df[col].unique()) if c != ref]
        df[col] = pd.Categorical(df[col], categories=cats)

    df["income_k"] = df["income"]  # HMDA income is already in $1000s
    df["loan_amount_k"] = df["loan_amount"] / 1e3
    df["property_value_k"] = df["property_value"] / 1e3

    formula = (
        "denied ~ C(race) + C(sex)"
        #   + C(ethnicity) "
        "+ dti + ltv + income_k + loan_amount_k + property_value_k"
    )
    return smf.ols(formula, data=df).fit(cov_type="HC1")


def extract_ground_truth_labels(lpm, alpha=0.05, adverse_if_positive=True):
    terms = lpm.params.index[lpm.params.index.str.startswith(("C(race)", "C(sex)"))]
    out = pd.DataFrame(
        {
            "term": terms,
            "effect": lpm.params.loc[terms].values,
            "p_value": lpm.pvalues.loc[terms].values,
        }
    )
    sig = out["p_value"] < alpha
    adverse = (out["effect"] > 0) if adverse_if_positive else (out["effect"] < 0)
    out["ground_truth_label"] = np.select(
        [sig & adverse, sig & ~adverse], ["BIAS", "FAVORED"], default="NO_BIAS"
    )
    return out


def main():
    data_path = os.path.join(PATH_TO_DATA, "preprocessed_data.csv")
    results_path = os.path.join(PATH_TO_GROUND_TRUTH, "ground_truth_labels.csv")
    os.makedirs(PATH_TO_GROUND_TRUTH, exist_ok=True)

    df = load_and_clean(data_path)
    print(f"Rows after cleaning: {len(df):,}")

    lpm = run_regression(df)
    print(lpm.summary())

    with open(os.path.join(PATH_TO_GROUND_TRUTH, "regression_summary.txt"), "w") as f:
        f.write(lpm.summary().as_text())

    pd.DataFrame({"lpm_coef": lpm.params, "lpm_p": lpm.pvalues}).rename_axis(
        "term"
    ).reset_index().to_csv(
        os.path.join(PATH_TO_GROUND_TRUTH, "full_regression_coefficients.csv"),
        index=False,
    )

    labels = extract_ground_truth_labels(lpm)
    labels.to_csv(results_path, index=False)
    print(f"\nGround truth labels written to {results_path}")
    print(labels.to_string(index=False))


if __name__ == "__main__":
    main()
