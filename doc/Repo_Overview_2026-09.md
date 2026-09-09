# Identity Embedding Run (8/31): Results

**Prepared:** 2026-09-04 · **Scope:** the run archived in `data/call_models/0831_identity_embedding_test/`. 16 identities (race x ethnicity x sex x age), 7 prompt types, `N_SAMPLES=3`, `SAMPLE_SIZE=2000`, raw-CSV mode, 6 cloud models. Extends `Identity_Embedding_Run_Report.md` (completion and cost) with the analysis.

**Bottom line.** 935 of 936 calls landed, ~$72. The run produces one clear signal: **models answer the race word in the prompt, not the data.** Pooled across identity prompts, Black identities draw YES at 15.1% vs 4.9% for White (Fisher p = 3.9e-07), and the gap survives dropping the outlier model (9.7% vs 0.6%, p = 2.4e-09). Ethnicity moves nothing, age moves nothing. But **none of it can be scored for correctness**: all 48 identity-by-sample ground-truth cells came back `False`, and the identity the models flag hardest has 73 rows in the entire population. This run is a framing result plus a plumbing test, not a measured accuracy.

## 1. Coverage

156 calls per model expected, 935/936 delivered (99.9%). One `gemini-3.1-pro-preview` call dropped on a transient 503. Estimated spend ~$72, with `claude-sonnet-4-5` (54%) and `gemini-3.1-pro-preview` (23%) at 77% of it. No local model has run this set (0/156 x 4); `llama-3.2-3b` 0/10 valid JSON and `llama-3.1-8b` 5/10 remain open from 8/07.

## 2. YES-rate by model and prompt

Percent answering YES ("the data shows discrimination"), n per cell in parentheses:

| Prompt | haiku-4-5 | sonnet-4-5 | gemini-3.1-pro | gemini-3.5-fl | gpt-4o-mini | gpt-5-nano |
|---|---:|---:|---:|---:|---:|---:|
| control | 0 (3) | 0 (3) | 0 (3) | 0 (3) | 0 (3) | 0 (3) |
| emotional | **100** (3) | 0 (3) | 33 (3) | 0 (3) | **100** (3) | 0 (3) |
| emotional_extreme | 0 (3) | 0 (3) | 0 (3) | 0 (3) | **100** (3) | 0 (3) |
| emotional_suicidal | 0 (3) | 0 (3) | 33 (3) | 0 (3) | 67 (3) | 0 (3) |
| identity | 12 (48) | 6 (48) | 4 (48) | 4 (48) | **46** (48) | 2 (48) |
| identity_hypothetical | 25 (48) | 0 (48) | 2 (47) | 8 (48) | 31 (48) | 2 (48) |
| emotional_identity | 2 (48) | 2 (48) | 2 (48) | 4 (48) | 25 (48) | 0 (48) |

Control is 0% everywhere, so any YES is a framing flip. Two caveats: the four unconditioned prompts have **n=3 per model**, far too thin to rank models on, and `gpt-4o-mini` is a clear outlier that carries much of the pooled signal. Mean confidence drifts down as framing intensifies (control 8.17, identity 7.55, emotional_identity 7.31) even as conclusions flip.

## 3. The identity axis

YES-rate by identity, age collapsed (n=108 each):

| Identity | YES % | conf | Population truth |
|---|---:|---:|---|
| Black · Hispanic · Female | **17.6** | 7.21 | 73 rows, not labelable |
| Black · non-Hisp · Male | **17.6** | 7.09 | BIAS (OR 1.86) |
| Black · non-Hisp · Female | 16.8 | 6.91 | BIAS (OR 1.57) |
| Black · Hispanic · Male | 8.3 | 7.22 | 91 rows, not labelable |
| White · non-Hisp · Female | 8.3 | 8.02 | FAVORED (OR 0.88) |
| White · Hispanic · Female | 7.4 | 7.48 | NO_BIAS |
| White · Hispanic · Male | 1.9 | 7.54 | BIAS (OR 1.14) |
| White · non-Hisp · Male | 1.9 | 8.12 | reference |

Marginal contrasts across identity prompts:

| Contrast | all models | excl. gpt-4o-mini |
|---|---|---|
| Black vs White | 15.1% vs 4.9%, p = 3.9e-07 | 9.7% vs 0.6%, p = 2.4e-09 |
| Hispanic vs non-Hispanic | 8.8% vs 11.1%, p = .26 | 4.2% vs 6.1%, p = .24 |
| Female vs Male | 12.5% vs 7.4%, p = .013 | 5.8% vs 4.4%, p = .40 |

Race is the only robust driver. The sex effect is entirely `gpt-4o-mini`. Ethnicity does nothing, which matters because ethnicity is where the actual data effect sits for White applicants (White · Hispanic · Male is BIAS at OR 1.14, and models give it the second-lowest YES rate of all eight).

**Age is inert.** 11.6% YES at age35 vs 8.3% at age55 (Fisher p = .11), confidence 7.46 vs 7.43, and the direction is not even consistent across identities. Age was never a ground-truth covariate either, so the two ages were identical by construction. The axis doubled the run for nothing.

## 4. Why none of this is scoreable

Three independent problems, all traceable to `SAMPLE_SIZE=2000` plus a 4-way identity:

- **The person is not in the data.** Rows matching the full 4-way identity: Black · Hispanic · Female · 35-44 is 1, 0, 2 across the three samples; the age-55 version is 0, 0, 0. Compare White · non-Hisp · Male · 35-44 at 136 to 143. Half the 16 identities are single digits.
- **The models notice.** Small-n hedging appears in 45% of black-Hispanic identity responses vs 9% for white-non-Hispanic-male. One reported "3 applicants matching this exact demographic profile" where the true count was 1.
- **Ground truth is constant.** `compare_to_ground_truth.py:62-90` labels an identity by OR-ing its main-effect terms, never an interaction. Across the 3 samples the only BIAS term produced was `C(race)[T.Asian]`, which is not in the matrix, so **all 16 x 3 = 48 truth cells are `False`** and accuracy is undefined. No `gt_metrics_*.csv` exists.

The sharpest way to put it: the two identities the models flag hardest include the one with **73 rows in the entire 53,202-row population**, where the coefficient is OR 1.01 at p = .97 even at census. Models are ranking by the race token, and the ranking happens to half-correlate with real population bias while being unverifiable from the rows they were given.

The design changes taken from these results (intersectional identities, stratified sampling, population-level ground truth) are tracked separately.
