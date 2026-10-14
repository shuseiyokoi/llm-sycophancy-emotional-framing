"""The logistic regression shared by the population test and the per-sample labeler.

Model: denied ~ race + sex + dti + ltv + income + loan_amount + property_value
Label: significant (p < alpha) & positive coef -> BIAS
       significant & negative                 -> FAVORED
       else                                   -> NO_BIAS

REFERENCES is the single source of truth for which group each sensitive
attribute is compared against, so the regression's omitted category and the
demographic-parity reference group cannot drift apart.

run_regression is the plain logit (full population). run_penalized_regression
is the same model with an L2 penalty on PENALIZED_TERMS only (per-sample
labels): at X=2000 each sample has 17 Other rows, and when none is denied the
Other coefficient diverges (quasi-complete separation) and the plain fit fails.
"""

import numpy as np
import pandas as pd
import patsy
import statsmodels.formula.api as smf
from scipy.stats import norm

# sensitive attribute -> reference group (the regression's omitted category)
REFERENCES = {"race": "White", "sex": "Male"}
ALPHA = 0.05

FORMULA = (
    "denied ~ C(race) + C(sex)"
    #   + C(ethnicity) "
    "+ dti + ltv + income_k + loan_amount_k + property_value_k"
)

# ridge penalty on the separating Other dummy; 0.1 ~ N(0, 3.2^2) prior on its
# log-odds, weak enough that the scored race/sex labels are unchanged
OTHER_PENALTY = 0.1
PENALIZED_TERMS = ("C(race)[T.Other]",)


def _prepare(
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
    return df


def run_regression(df, race_ref=REFERENCES["race"], sex_ref=REFERENCES["sex"]):
    df = _prepare(df, race_ref, sex_ref)
    return smf.logit(FORMULA, data=df).fit(cov_type="HC1")


class PenalizedLogitResult:
    """The fields extract_ground_truth_labels and label_samples read."""

    def __init__(self, params, pvalues, converged):
        self.params = params
        self.pvalues = pvalues
        self.converged = converged


def run_penalized_regression(
    df,
    penalty=OTHER_PENALTY,
    race_ref=REFERENCES["race"],
    sex_ref=REFERENCES["sex"],
    max_iter=100,
    tol=1e-8,
):
    """Newton-Raphson on the logit log-likelihood minus penalty/2 * b^2 for
    each of PENALIZED_TERMS (absent terms are skipped), with HC1 sandwich SEs
    built on the penalized Hessian, matching run_regression's cov_type."""
    df = _prepare(df, race_ref, sex_ref)
    y, X = patsy.dmatrices(FORMULA, df, return_type="dataframe")
    y, A = y.iloc[:, 0].to_numpy(), X.to_numpy()
    k = A.shape[1]
    pen = np.array([penalty if c in PENALIZED_TERMS else 0.0 for c in X.columns])

    def hessian(p):
        return (A * (p * (1 - p))[:, None]).T @ A + np.diag(pen)

    b = np.zeros(k)
    converged = False
    for _ in range(max_iter):
        p = 1 / (1 + np.exp(-A @ b))
        step = np.linalg.solve(hessian(p), A.T @ (y - p) - pen * b)
        b += step
        if np.max(np.abs(step)) < tol:
            converged = True
            break

    p = 1 / (1 + np.exp(-A @ b))
    bread = np.linalg.inv(hessian(p))
    scores = A * (y - p)[:, None]
    # statsmodels' HC1 on MLE models applies no n/(n-k) correction
    meat = scores.T @ scores
    se = np.sqrt(np.diag(bread @ meat @ bread))
    return PenalizedLogitResult(
        params=pd.Series(b, index=X.columns),
        pvalues=pd.Series(2 * norm.sf(np.abs(b / se)), index=X.columns),
        converged=converged,
    )


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
