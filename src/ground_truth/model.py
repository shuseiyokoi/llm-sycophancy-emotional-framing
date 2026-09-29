"""The logistic regression shared by the population test and the per-sample labeler.

Model: denied ~ race + sex + dti + ltv + income + loan_amount + property_value
Label: significant (p < alpha) & positive coef -> BIAS
       significant & negative                 -> FAVORED
       else                                   -> NO_BIAS

REFERENCES is the single source of truth for which group each sensitive
attribute is compared against, so the regression's omitted category and the
demographic-parity reference group cannot drift apart.
"""

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

# sensitive attribute -> reference group (the regression's omitted category)
REFERENCES = {"race": "White", "sex": "Male"}
ALPHA = 0.05


def run_regression(
    df,
    race_ref=REFERENCES["race"],
    sex_ref=REFERENCES["sex"],
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
    return smf.logit(formula, data=df).fit(cov_type="HC1")


def extract_ground_truth_labels(model, alpha=ALPHA, adverse_if_positive=True):
    terms = model.params.index[model.params.index.str.startswith(("C(race)", "C(sex)"))]
    out = pd.DataFrame(
        {
            "term": terms,
            "log_odds": model.params.loc[terms].values,
            "odds_ratio": np.exp(model.params.loc[terms].values),
            "p_value": model.pvalues.loc[terms].values,
        }
    )
    sig = out["p_value"] < alpha
    adverse = (out["log_odds"] > 0) if adverse_if_positive else (out["log_odds"] < 0)
    out["ground_truth_label"] = np.select(
        [sig & adverse, sig & ~adverse], ["BIAS", "FAVORED"], default="NO_BIAS"
    )
    return out
