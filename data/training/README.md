# Training data

`biashara_training_data.csv`: 500 **synthetic** Kenyan SMEs, 18,088 business-months (July 2022 to September 2026), made by `ml/synthetic.py`:

```
venv\Scripts\python -m ml.synthetic --csv data/training/biashara_training_data.csv --businesses 500 --seed 2026
```

The same seed always gives the same file. All 16 types of business; 24–48 months each; five patterns (healthy 45%, declining sales 15%, costs creeping up 15%, a sudden shock 15%, up and down 10%). 10.9% of months are losses; 18.5% of labelled months are followed by a loss within 3 months.

**Load it:** Admin → Risk model → **Import training CSV**, then **Train the model**. Or from the terminal:

```
venv\Scripts\python -m ml.import_csv data/training/biashara_training_data.csv
venv\Scripts\python -m ml.train
```

The businesses (`TRN-0001` … `TRN-0500`) are added as synthetic: no login, counted apart from real participants, and deleted with **Remove all synthetic businesses**. Importing twice is safe; existing codes are skipped.

| Column | Meaning |
| --- | --- |
| business_code | `TRN-0001` … |
| sector | Type of business key (retail, food, agent …; see `app/sectors.py`) |
| is_synthetic | Always 1 |
| month | `YYYY-MM` |
| revenue | Total sales, KES |
| cogs | Cost of goods sold, KES |
| operating_expenses | Running expenses, KES |
| cash_inflows, cash_outflows | Money received and paid out, KES |
| mobile_money_receipts | Received by M-Pesa, KES |
| closing_stock | Stock value at month end, KES |
| outstanding_debt | Money owed at month end, KES |
| transaction_count | Number of sales |
| net_operating_result | revenue − cogs − operating_expenses |
| loss_next_3m | The label: 1 if any of the next 3 months is a loss, 0 if not, blank if those months aren't all in the file |
| trajectory | The simulated pattern (for analysis only; not used by the model) |

The importer reads only the columns the app stores, so `loss_next_3m` and `trajectory` are ignored there; they are for notebooks. Results on this file show that the method works, not how well it predicts real businesses.
