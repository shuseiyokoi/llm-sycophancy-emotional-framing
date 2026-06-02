# Fields

Class: DSCI590

# **HMDA Public LAR Data Processing Metadata**

## **1. Study Goal**

| **Item** | **Description** |
| --- | --- |
| Dataset | Public HMDA Loan/Application Register data |
| Main purpose | Analyze mortgage application decisions and test whether LLM-generated decisions differ under emotional or discrimination-related appeal prompts |
| Target variable | `action_taken` |
| Main outcome | Approval vs Denial |
| Main modeling population | Applications with `action_taken in [1, 2, 3]` |
| Excluded outcomes | Withdrawn, incomplete, purchased loans, and preapproval-only outcomes |

---

## **2. Target Variable Metadata**

| **Field** | **Decision** | **Processing** | **Reason** |
| --- | --- | --- | --- |
| `action_taken` | Keep | Keep only values `1`, `2`, and `3` | These represent clean final application outcomes: originated, approved but not accepted, and denied |
| `action_taken` | Transform | Convert to binary target | Values `1` and `2` are treated as approved; value `3` is treated as denied |

Recommended target encoding:

```python
df["target"] = df["action_taken"].apply(lambda x: 1 if x in [1, 2] else 0)
```

Meaning:

```
1 = Approved / originated
0 = Denied
```

---

# **3. Sample Filtering Metadata**

These fields are mainly used to define a clean study population.

| **Field** | **Decision** | **Processing** | **Reason** | Values |
| --- | --- | --- | --- | --- |
| `derived_loan_product_type` | Keep for filtering | Filter to conventional first-lien loans | This combines loan type and lien status. Using this field creates a cleaner sample of standard conventional first mortgages |   • Conventional:First Lien
  • FHA:First LienVA:First Lien
  • FSA/RHS:First Lien
  • Conventional:Subordinate Lien
  • FHA:Subordinate Lien
  • VA:Subordinate Lien
  • FSA/RHS:Subordinate Lien |
| `conforming_loan_limit` | Keep for filtering
[Methodology](https://github.com/cfpb/hmda-platform/wiki/Derived-Fields-Categorization-2018-Onward#conforming-loan-limit)(GitHub) | Filter to `C` | Keeps conforming loans only and removes nonconforming/jumbo loans, which may follow different underwriting standards |   • C (Conforming)
  • NC (Nonconforming)
  • U (Undetermined)
  • NA (Not Applicable) |
| `business_or_commercial_purpose` | Keep for filtering | Filter to `2` | Removes business or commercial-purpose loans because they are different from regular consumer mortgage applications |   • 1 - Primarily for a business or commercial purpose
  • 2 - Not primarily for a business or commercial purpose
  • 1111 - Exempt |
| `initially_payable_to_institution` | Keep for filtering | Filter to `1` | Keeps loans initially payable to the reporting institution, so the record more directly reflects that institution’s own credit decision |   • 1 - Initially payable to your institution
  • 2 - Not initially payable to your institution
  • 3 - Not applicable
  • 1111 - Exempt |
| `applicant_age/ageapplicant` | Keep | Remove `8888` and `9999` | Removes unavailable or invalid age categories |   • <25
  • 25-34
  • 35-44
  • 45-54
  • 55-64
  • 65-74
  • >74
  • 8888 |

Filter:

```python
df = df[
    (df["derived_loan_product_type"] == "Conventional:First Lien") &
    (df["conforming_loan_limit"] == "C") &
    (df["business_or_commercial_purpose"] == 2) &
    (df["initially_payable_to_institution"] == 1) &
    (df["action_taken"].isin([1, 2, 3])) &
    (~df["applicant_age"].isin(["8888", "9999"]))
]
```

Check exact string first:

```python
df["derived_loan_product_type"].value_counts()
```

---

# **4. Final Keep Feature Metadata**

These fields are kept for modeling, prompt construction, or fairness comparison.

| **Field** | **Category** | **[Decision]** | Value | **Keeping Reason** |
| --- | --- | --- | --- | --- |
| `loan_purpose` | Loan feature | Keep ? |   • 1 - Home purchase 45%
  • 2 - Home improvement
  • 31 - Refinancing
  • 32 - Cash-out refinancing 17%
  • 4 - Other purpose 13%
  • 5 - Not 
applicable | Loan purpose affects approval behavior because home purchase, refinance, cash-out refinance, and home improvement loans may have different risk patterns |
| `loan_amount` | Financial feature | Keep | numeric | Loan amount is directly related to underwriting, affordability, and risk |
| `combined_loan_to_value_ratio/loan_to_value_ratio` | Financial feature | Keep ?
Missing 33% | numeric | CLTV is an important underwriting variable because it measures loan size relative to property value |
| `debt_to_income_ratio` | Financial feature | Keep ?
Missing 35% | numeric | DTI is directly related to affordability and mortgage approval decisions |
| `property_value` | Financial feature | Keep ?
Missing 21% | numeric | Property value affects collateral and loan risk |
| `income` | Financial feature | Keep
Missing 14% | numeric | Income is directly related to borrower affordability |
| `applicant_credit_score_type` | Credit/process feature | Keep ?
 |   • 1 - Equifax Beacon 5.0 18%
  • 2 - Experian Fair Isaacmodel 17%
  • 9 - Not applicable 38% | This does not provide the actual credit score, but it controls for which credit scoring model was used |
| `occupancy_type` | Property feature | Keep ?
 |   • 1 - Principal residence 89%
  • 2 - Second residence 2%
  • 3 - Investment property 9% | Principal residence, second residence, and investment property can have different underwriting standards |
| `derived_ethnicity` | Demographic/fairness feature 
[Methodology](https://github.com/cfpb/hmda-platform/wiki/Derived-Fields-Categorization-2018-Onward#ethnicity)(GitHub) | Keep
 |   • Hispanic or Latino
  • Not Hispanic or LatinoJoint
  • Ethnicity Not Available
  • Free Form Text Only | Needed to test whether LLM responses differ by ethnicity-related information or appeal prompts |
| `derived_race` | Demographic/fairness feature
[Methodology](https://github.com/cfpb/hmda-platform/wiki/Derived-Fields-Categorization-2018-Onward#race)(GitHub) | Keep |   • American Indian or Alaska Native
  • Asian 15%
  • Black or African American
  • Native Hawaiian or Other Pacific Islander
  • White 44%
  • 2 or more minority races
  • Joint
  • Free Form Text Only
  • Race Not Available 33% | Needed to test whether LLM responses differ by race-related information or appeal prompts |
| `derived_sex` | Demographic/fairness feature
[Methodology](https://github.com/cfpb/hmda-platform/wiki/Derived-Fields-Categorization-2018-Onward#sex)(GitHub) | Keep |   • Male 30%
  • Female 19%
  • Joint 32%
  • Sex Not Available | Needed to test whether LLM responses differ by sex-related information or appeal prompts |
| `applicant_age/ageapplicant` | Demographic/fairness feature | Keep |   • <25
  • 25-34
  • 35-44
  • 45-54
  • 55-64
  • 65-74
  • >74
  ~~• 8888~~ | Needed to test whether LLM responses differ by age group or age-related appeal prompts |

---

# **5. Final Modeling / Prompt Feature Set**

After filtering, use these as the main feature set:

```
loan_purpose
loan_amount
combined_loan_to_value_ratio
debt_to_income_ratio
property_value
income
applicant_credit_score_type
occupancy_type
derived_ethnicity
derived_race
derived_sex
applicant_age
```

Target:

```
action_taken / target
```

Important note:

Demographic variables are kept because the study is about **LLM bias and prompt response differences**. They should be described as **fairness or prompt-condition variables**, not simply as ordinary creditworthiness variables.

---

# **6. Final Eliminated Feature Metadata**

## **A. Redundant Loan/Product Fields**

| **Field** | **Decision** | **Elimination Reason** |
| --- | --- | --- |
| `loan_type` | Eliminate | Redundant because `derived_loan_product_type` already captures conventional loan status. FHA, VA, and USDA loans also follow different program rules, so the sample is filtered to conventional first-lien loans |
| `lien_status` | Eliminate | Redundant because `derived_loan_product_type` already captures first-lien status |
| `derived_dwelling_category` | Eliminate | Low variation; most records are single-family site-built properties |

---

## **B. Non-Comparable Loan Product Fields**

| **Field** | **Decision** | **Elimination Reason** |
| --- | --- | --- |
| `reverse_mortgage` | Eliminate | Reverse mortgages are different from standard mortgage applications and most records are not reverse mortgages |
| `open-end_line_of_credit` | Eliminate | Open-end credit lines, such as HELOCs, are different from standard closed-end mortgages |
| `business_or_commercial_purpose` | Use for filtering, then eliminate | Used to keep only non-business-purpose loans; after filtering, it has no remaining useful variation |
| `conforming_loan_limit` | Use for filtering, then eliminate | Used to keep only conforming loans; after filtering, it has no remaining useful variation |
| `initially_payable_to_institution` | Use for filtering, then eliminate | Used to keep loans initially payable to the reporting institution; after filtering, it has no remaining useful variation |
| `derived_loan_product_type` | Use for filtering, then eliminate | Used to keep conventional first-lien loans; after filtering, it has no remaining useful variation |

---

## **C. Post-Decision or Data Leakage Fields**

| **Field** | **Decision** | **Elimination Reason** |
| --- | --- | --- |
| `denial_reason-1` | Eliminate | Directly leaks the outcome because it explains why a denied application was denied |
| `denial_reason-2` | Eliminate | High missingness and outcome leakage |
| `denial_reason-3` | Eliminate | High missingness and outcome leakage |
| `denial_reason-4` | Eliminate | High missingness and outcome leakage |
| `purchaser_type` | Eliminate | Post-origination field; it describes who purchased the loan after the loan decision |
| `interest_rate` | Eliminate | May be determined after approval/pricing and can create data leakage |
| `rate_spread` | Eliminate | Pricing-related and may be post-decision |
| `total_loan_costs` | Eliminate | Closing/pricing-related and may be post-decision |
| `total_points_and_fees` | Eliminate | Closing/pricing-related and highly missing |
| `origination_charges` | Eliminate | Closing/pricing-related and may be post-decision |
| `discount_points` | Eliminate | Pricing-related and may be post-decision |
| `lender_credits` | Eliminate | Pricing-related and may be post-decision |

---

## **D. High-Missing or Low-Utility Financial Terms**

| **Field** | **Decision** | **Elimination Reason** |
| --- | --- | --- |
| `loan_term` | Eliminate | Low diversity; most loans are 360-month loans |
| `prepayment_penalty_term` | Eliminate | Very high missingness |
| `intro_rate_period` | Eliminate | High missingness and mainly relevant to adjustable-rate products |
| `total_points_and_fees` | Eliminate | Very high missingness |
| `multifamily_affordable_units` | Eliminate | Very high missingness and not central to this study |

---

## **E. Low-Variation Repayment Feature Fields**

| **Field** | **Decision** | **Elimination Reason** |
| --- | --- | --- |
| `hoepa_status` | Eliminate | Low usefulness for this study and limited variation |
| `negative_amortization` | Eliminate | Very low variation; almost all records have no negative amortization |
| `interest_only_payment` | Eliminate | Low variation; most records have no interest-only payment |
| `balloon_payment` | Eliminate | Very low variation; most records have no balloon payment |
| `other_nonamortizing_features` | Eliminate | Very low variation; almost all records have no other non-amortizing features |

---

## **F. Property Fields Removed Due to Low Variation or Irrelevance**

| **Field** | **Decision** | **Elimination Reason** |
| --- | --- | --- |
| `construction_method` | Eliminate | Low variation; most records are site-built |
| `manufactured_home_secured_property_type` | Eliminate | Mostly not applicable because the study focuses on standard site-built/conventional first-lien loans |
| `manufactured_home_land_property_interest` | Eliminate | Mostly not applicable and not central to the study |
| `total_units` | Eliminate | Low variation; most properties have one unit |
| `multifamily_affordable_units` | Eliminate | Mostly missing or not applicable |

---

## **G. Redundant Detailed Demographic Fields**

| **Field** | **Decision** | **Elimination Reason** |
| --- | --- | --- |
| `applicant_ethnicity-1` | Eliminate | Redundant because `derived_ethnicity` provides cleaner aggregated ethnicity |
| `applicant_ethnicity-2` to `applicant_ethnicity-5` | Eliminate | High missingness and redundant with `derived_ethnicity` |
| `applicant_race-1` | Eliminate | Redundant because `derived_race` provides cleaner aggregated race |
| `applicant_race-2` to `applicant_race-5` | Eliminate | High missingness and redundant with `derived_race` |
| `applicant_sex` | Eliminate | Redundant because `derived_sex` provides cleaner aggregated sex |
| `applicant_age_above_62` | Eliminate | Redundant because `applicant_age` already captures age group |

---

## **H. Co-Applicant Fields**

| **Field** | **Decision** | **Elimination Reason** |
| --- | --- | --- |
| `co-applicant_ethnicity-1` to `co-applicant_ethnicity-5` | Eliminate | Often not applicable because many records have no co-applicant |
| `co-applicant_race-1` to `co-applicant_race-5` | Eliminate | Often not applicable or highly missing |
| `co-applicant_sex` | Eliminate | Often not applicable |
| `co-applicant_age` | Eliminate | Often not applicable |
| `co-applicant_age_above_62` | Eliminate | Often not applicable and redundant if co-applicant age is excluded |
| `co-applicant_credit_score_type` | Eliminate | Often not applicable and does not provide actual credit score |

---

## **I. Observation-Based Demographic Collection Fields**

| **Field** | **Decision** | **Elimination Reason** |
| --- | --- | --- |
| `applicant_ethnicity_observed` | Eliminate | Describes how demographic information was collected, not the applicant’s financial profile |
| `co-applicant_ethnicity_observed` | Eliminate | Co-applicant field and not central to the study |
| `applicant_race_observed` | Eliminate | Describes observation method only |
| `co-applicant_race_observed` | Eliminate | Co-applicant field and not central to the study |
| `applicant_sex_observed` | Eliminate | Describes observation method only |
| `co-applicant_sex_observed` | Eliminate | Co-applicant field and not central to the study |

---

## **J. Application Process Fields**

| **Field** | **Decision** | **Elimination Reason** |
| --- | --- | --- |
| `preapproval` | Eliminate | Preapproval status is not central to final approval/denial analysis |
| `submission_of_application` | Eliminate | Describes application channel/process rather than creditworthiness or prompt-bias conditions |
| `aus-1` | Eliminate | Automated underwriting system may reflect processing path but is not central to the LLM prompt-bias study |
| `aus-2` to `aus-5` | Eliminate | High missingness and not central to the study |

---

## **K. Record Identifier and Geography Fields**

| **Field** | **Decision** | **Elimination Reason** |
| --- | --- | --- |
| `activity_year` | Eliminate | Not needed if using one year of data |
| `lei` | Eliminate | Identifies the reporting institution; may create institution-specific effects that are outside the study goal |
| `state_code` | Eliminate | Removed to avoid geographic proxy effects |
| `county_code` | Eliminate | Removed to avoid geographic proxy effects |
| `census_tract` | Eliminate | Removed to avoid geographic proxy effects and excessive location specificity |
| `derived_msa-md` | Eliminate | Removed to simplify the study and avoid regional market proxy effects |

---

## **L. Census Tract Context Fields**

| **Field** | **Decision** | **Elimination Reason** |
| --- | --- | --- |
| `tract_population` | Eliminate | Neighborhood-level context is outside the main individual-level LLM prompt-bias study |
| `tract_minority_population_percent` | Eliminate | Could introduce geographic/racial proxy effects and make it harder to isolate prompt effects |
| `ffiec_msa_md_median_family_income` | Eliminate | Market-level income context is outside the main study goal |
| `tract_to_msa_income_percentage` | Eliminate | Could introduce socioeconomic proxy effects |
| `tract_owner_occupied_units` | Eliminate | Neighborhood housing composition is outside the study goal |
| `tract_one_to_four_family_homes` | Eliminate | Neighborhood housing composition is outside the study goal |
| `tract_median_age_of_housing_units` | Eliminate | Neighborhood housing age is outside the study goal |

---

# **7. Missing Value Handling Metadata**

| **Field** | **Missing Issue** | **Processing Recommendation** |
| --- | --- | --- |
| `debt_to_income_ratio` | Around 35% missing | Keep; create missing indicator or treat `NA` / `Exempt` as separate category |
| `combined_loan_to_value_ratio` | Around 33% missing | Keep; create missing indicator and convert valid values to numeric |
| `property_value` | Around 21% missing | Keep; create missing indicator or impute |
| `income` | Around 14% missing | Keep; create missing indicator or impute |
| `applicant_credit_score_type` | Many `Not applicable` values | Keep as categorical control variable |

Example missing indicators:

```python
df["dti_missing"] = df["debt_to_income_ratio"].isin(["NA", "Exempt"])

df["cltv_missing"] = (
    df["combined_loan_to_value_ratio"].isna() |
    df["combined_loan_to_value_ratio"].isin(["NA", "Exempt"])
)

df["property_value_missing"] = df["property_value"].isna()

df["income_missing"] = df["income"].isna()
```

---

# **8. Final Data Processing Summary**

| **Step** | **Processing Action** | **Purpose** |
| --- | --- | --- |
| 1 | Keep `action_taken in [1, 2, 3]` | Focus on clean approval/denial/origination outcomes |
| 2 | Filter to conventional first-lien loans | Remove FHA, VA, USDA, and subordinate-lien loans with different rules |
| 3 | Filter to conforming loans | Remove jumbo/nonconforming loans |
| 4 | Filter to non-business-purpose loans | Focus on consumer mortgage applications |
| 5 | Filter to loans initially payable to reporting institution | Keep records that better reflect the institution’s original decision |
| 6 | Remove unavailable applicant age values | Avoid invalid demographic categories |
| 7 | Remove post-decision and leakage fields | Prevent outcome leakage |
| 8 | Remove redundant detailed demographic fields | Use cleaner derived demographic categories |
| 9 | Remove high-missing and low-variation fields | Improve data quality and reduce noise |
| 10 | Keep financial, property, and demographic prompt-bias fields | Support LLM decision and fairness-response analysis |

---

# **9. Final Short Methodology Paragraph**

I processed the HMDA Public LAR data by selecting fields that are available before or during the mortgage application decision and removing variables that could create data leakage, such as denial reasons, interest rate, rate spread, loan costs, points, and lender credits. I filtered the dataset to conforming, conventional first-lien, non-commercial loans that were initially payable to the reporting institution in order to create a more consistent study population. I removed fields with high missingness, low variation, redundant demographic detail, post-origination information, and geography-based variables that could introduce proxy effects. I kept applicant demographic variables, including race, ethnicity, sex, and age, because the purpose of this study is to examine whether LLM-generated mortgage decisions differ under demographic or discrimination-related appeal prompts.

1. References

# **10. References / Sources**

The **Public HMDA LAR Data Fields** page was used as the main source for public LAR field names, field descriptions, and coded values such as `action_taken`, `loan_type`, `loan_purpose`, `construction_method`, `debt_to_income_ratio`, and other public loan/application register variables.

- The **2024 HMDA Filing Instructions Guide (FIG)** was used as a reference for the official HMDA filing structure, reporting context, and 2024 data collection/reporting guidance.

[2024 FIG (Filing Instructions Guide) | HMDA Documentation](https://ffiec.cfpb.gov/documentation/fig/2024/overview)

- The **Appended HMDA Data Fields** documentation was used for fields that are added or derived for public HMDA use, including appended geographic, demographic, and derived public-use variables.

[Appended HMDA Data Fields | HMDA Documentation](https://ffiec.cfpb.gov/documentation/publications/general/derived-data-fields)

- The **CFPB HMDA Platform Derived Fields Categorization 2018 Onward** GitHub documentation was used to understand how derived HMDA fields are categorized from underlying reported fields, especially for derived demographic and product-related variables.

[Derived Fields Categorization 2018 Onward](https://github.com/cfpb/hmda-platform/wiki/Derived-Fields-Categorization-2018-Onward)

- The **HMDA Data Disclosure Policy Guidance Executive Summary** was used to justify why some HMDA fields are excluded, modified, rounded, binned, or reduced in precision in the public dataset. The guidance explains that the Bureau modifies public loan-level HMDA data to balance public disclosure benefits with applicant and borrower privacy risks.
- https://files.consumerfinance.gov/f/documents/HMDA_Data_Disclosure_Policy_Guidance.Executive_Summary.FINAL.12212018.pdf

*Consumer Financial Protection Bureau. (2018). Executive summary of the HMDA data disclosure policy guidance.*

*Federal Financial Institutions Examination Council. (n.d.). Public HMDA - LAR data fields. HMDA Documentation.*

*Federal Financial Institutions Examination Council. (n.d.). 2024 Filing Instructions Guide: Overview. HMDA Documentation.*

*Federal Financial Institutions Examination Council. (n.d.). Appended HMDA data fields. HMDA Documentation.*

*Consumer Financial Protection Bureau. (n.d.). Derived Fields Categorization 2018 Onward. HMDA Platform GitHub Wiki.*