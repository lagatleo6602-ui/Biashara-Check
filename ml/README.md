# ml/: the 90-day loss-risk model

Predicts, for one business at month *t*, the probability that **at least one of months t+1, t+2, t+3 is an operating loss**, and explains the prediction with SHAP.

| File | What it does |
| --- | --- |
| `synthetic.py` | Generates synthetic businesses (`SYN-001`…) for development and testing |
| `features.py` | Turns monthly records into one row of features per business-month, plus the label |
| `train.py` | Time-based split, trains and compares four models, SHAP importance, saves the best |
| `predict.py` | Predicts one business's latest month; top reasons and protective factors in English or Kiswahili |
| `artifacts/` | `model.joblib` and `model_meta.json` (git-ignored; train again on each computer) |

## Commands

Run from the project folder, with MySQL running:

```
venv\Scripts\python -m ml.synthetic --businesses 120    # add synthetic businesses
venv\Scripts\python -m ml.train                         # train on everything
venv\Scripts\python -m ml.train --real-only             # leave synthetic businesses out
venv\Scripts\python -m ml.synthetic --remove            # delete all synthetic businesses
```

The same actions are on the Admin page under **Risk model**. After training there, every business is scored again in the background.

## Label

Net operating result for a month = sales − cost of goods sold − running expenses.

`label(t) = 1` if net < 0 in any of t+1, t+2, t+3, else 0. If any of those three months is missing, the row has no label: it can be predicted but is never used for training or testing.

## Features (month t and earlier only)

| Group | Features |
| --- | --- |
| Profitability | `margin`, `margin_3m`, `margin_trend`, `losses_last3` |
| Growth | `rev_growth_3m`, `cost_growth_3m`, `cost_vs_sales_growth`, `rev_mom` |
| Cost structure | `cogs_ratio`, `opex_ratio` |
| Cash flow | `net_cf_ratio`, `neg_cf_months_3` |
| Activity | `mpesa_share`, `tx_growth_3m` |
| Leverage and stock | `debt_to_rev`, `debt_growth_3m`, `stock_to_rev` |
| Context | `age_months`, `month_sin`, `month_cos`, one column per type of business (16) |

Each business is put on a full monthly calendar first, so a missing month leaves gaps in the 3-month windows rather than silently joining months that aren't next to each other. Ratios are clipped to ±5 so one odd month can't dominate. Optional fields (M-Pesa, stock, debt, number of sales) may be empty; the models handle that (median imputation for logistic regression and random forest, native handling in XGBoost and LightGBM).

## Validation

Out-of-time, never random:

1. Sort the labelled months; the latest 20% are the **test** set.
2. **Training** stops 3 months before the test period begins, because a training label looks 3 months ahead and would otherwise use test-period outcomes.
3. Every model is scored on the test set: **PR-AUC** (main metric, since losses are the rarer class), ROC-AUC, recall, precision, F1 at 0.5, Brier score, confusion matrix.
4. The model with the best PR-AUC is refitted on all labelled months and saved.

Training needs at least 150 labelled months, with at least 15 of each outcome.

## Models

| Key | Model | Notes |
| --- | --- | --- |
| `logreg` | Logistic regression | Baseline; median imputation, scaling, `class_weight="balanced"` |
| `rf` | Random forest | 300 trees, min 5 per leaf, balanced |
| `xgb` | XGBoost | 300 trees, depth 4, `scale_pos_weight` = negatives / positives |
| `lgbm` | LightGBM | 300 trees, 15 leaves, balanced |

## Calibration and test evidence

- The chosen model is **Platt-scaled** (`train.fit_scaler`, `train.calibrate`): a one-variable logistic regression on logit(p), fitted on the last 20% of the training months by a copy of the model trained on the months before them (same 3-month gap). The test months are never used. The scaler is saved in the model file and applied in `predict.predict_rows`.
- `meta["evidence"]` keeps: the calibration table (`train.calibration`, 7 ranges), the observed loss rate in each band (`train.by_band`), the same metrics for a no-ML rule (`train.rule_baseline`: average margin over 3 months below zero), the uncalibrated Brier score and calibration, and the training and test month ranges. Shown on `/how`.

## Financial-distress model (`distress.py`)

A separate, statistical **logistic regression** for a second label (`features.py`): 1 if over months t+1..t+3 money out exceeds money in, or money owed rises by more than half a month's sales.

- 8 figures, median-imputed and standardised; unpenalised maximum likelihood, no class weights.
- Saved statistics: coefficients, standard errors (inverse Fisher information), z, p-values, odds ratios and 95% intervals, McFadden R², likelihood-ratio test; on the test months PR-AUC, ROC-AUC, Brier, calibration and Hosmer-Lemeshow.
- `distress.predict_rows` returns every term (value, mean, sd, z, coefficient, contribution), the intercept and the log-odds, so the probability can be checked by hand. Driver sentences reuse `predict.explain` only when the direction matches; otherwise a neutral factual line is used.
- Trained inside `train.train()` and saved to `artifacts/distress.joblib`; its summary is `meta["distress"]`.

## The 1-12 month outlook (`horizon.py`)

One LightGBM for all horizons h = 1..12 (stacked examples with h as an input, monotone in h, no class weights).
Labels: any loss in t+1..t+h, only when all h months are recorded (`future_losses`). Test: latest 25% of months,
training examples only when their label window ends before the test period. The curve is shifted on the log-odds
scale so h = 3 equals the main model's calibrated %, then made non-decreasing (`anchor`). Per-horizon evidence is
in `meta["horizon"]["horizons"]`. `predict_rows(rows, months, p3)` returns the curve, the chosen horizon's %,
band and SHAP reasons (shared `predict.reasons_from`).

## Risk bands

| Band | Probability |
| --- | --- |
| Low | below 0.35 |
| Moderate | 0.35 to 0.60 |
| High | 0.60 and above |

Set in `train.BANDS`.

## Explanations

- **Per business:** SHAP values for that business-month (TreeExplainer for the tree models, LinearExplainer for logistic regression). The three features pushing the risk up most become the **reasons**, each a plain sentence with the business's own figure and a practical tip (`predict.explain`, Kiswahili in `predict.explain_sw`). The features pulling the risk down most become **what's working for you**.
- **Overall:** mean |SHAP| on the test months, with the two time-of-year columns and the 16 business-type columns each reported as one feature. Shown on the Admin page and in the study report.

## Synthetic data

Each synthetic business gets a type of business with its own typical margins and costs, 18–36 months of records and one of five patterns: healthy (45%), declining sales (15%), costs creeping up (15%), a sudden shock (15%), up and down (10%). Seasonality, random noise, M-Pesa share, stock, debt and number of sales are included. About 9% of months are losses, and about 16% of labelled months are followed by a loss within 3 months.

Synthetic businesses are flagged (`is_synthetic`), have no login, never get messages, and are counted separately everywhere. **Model results on synthetic data show that the method works, not how well it will predict real businesses.** Report them that way, and retrain with `--real-only` once enough real months are collected.
