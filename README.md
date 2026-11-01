# Biashara Check

**An explainable early-warning system for short-term operating-loss risk in Kenyan SMEs.**

Capstone II project, KCA University. Small business owners enter their monthly sales, costs and cash figures (or import them from Excel or an M-Pesa statement). Biashara Check estimates the risk that the business makes a net operating loss in the next 90 days and explains the main reasons in plain language, with what to do about each one.

| | |
| --- | --- |
| **Stack** | Python 3.12, FastAPI, SQLAlchemy, MySQL (XAMPP), plain HTML/CSS/JavaScript |
| **Models** | Machine learning (scikit-learn, XGBoost, LightGBM, SHAP) for the loss risk; a statistical logistic regression (scipy) for financial distress; fixed business rules for warnings |
| **Reports** | reportlab (PDF monthly report, lender summary, study report) |
| **Integrations** | Gmail SMTP (email codes), TextBee or Africa's Talking (SMS), Safaricom Daraja (M-Pesa Express), ngrok (payment callbacks) |
| **Data protection** | Kenya Data Protection Act, 2019: pseudonymous business codes, encrypted contacts, consent, right to erasure |

---

## Contents

1. [Features](#features)
2. [Quick start (Windows)](#quick-start-windows)
3. [Starting the app every day](#starting-the-app-every-day)
4. [Configuration (.env)](#configuration-env)
5. [Users and roles](#users-and-roles)
6. [Using Biashara Check](#using-biashara-check)
7. [Biashara Pro and M-Pesa](#biashara-pro-and-m-pesa)
8. [M-Pesa callbacks with ngrok](#m-pesa-callbacks-with-ngrok)
9. [The risk model](#the-risk-model)
   - [Is it machine learning, statistics or rules?](#is-it-machine-learning-statistics-or-rules)
   - [How accurate is it?](#how-accurate-is-it)
   - [The financial-distress model](#the-financial-distress-model-logistic-regression)
   - [Business figures and formulas](#business-figures-and-formulas)
10. [Reports](#reports)
11. [Email and SMS](#email-and-sms)
12. [Kiswahili and the phone app](#kiswahili-and-the-phone-app)
13. [Security and privacy](#security-and-privacy)
14. [Backups](#backups)
15. [Hosting it online](#hosting-it-online)
16. [Project structure](#project-structure)
17. [API overview](#api-overview)
18. [Testing](#testing)
19. [Sample files](#sample-files)
20. [Troubleshooting](#troubleshooting)
21. [Roadmap](#roadmap)

---

## Features

**For business owners**
- Sign-up that confirms the email with a 6-digit code before the account is created.
- A five-step welcome walkthrough on the first visit (reopen it any time from **Tour**).
- **How it's calculated** page: every formula, what the risk % means, which parts are machine learning, statistics or rules, the test results that show how accurate the predictions are, the owner's own track record, and how data is kept private and correct.
- Add a month with a live preview of profit and cash; edit or delete any month.
- Upload many months at once from the CSV template.
- **Risk check by a trained model:** the chance of at least one loss month in the next 3 months, a low, moderate or high band, the top 3 reasons from SHAP in plain language with a practical action for each, what is working in the owner's favour, and the risk month by month.
- **Movable Ask button:** owners can drag it anywhere; it sticks to the nearer side and remembers the spot on that phone. Dropping it at the very edge (or "tuck it away" in the chat) hides it to a small tab; tap the tab to bring it back. While scrolling down it shrinks to just the icon.
- **Ask Biashara Check (chat assistant):** a free, built-in helper (the **Ask** button). Owners ask in English or Kiswahili, e.g. "What were my sales in March?", "Why is my risk high?", "What if I raise prices by 5%?", "What is break-even?", "How do I change my username?". Answers come from the owner's own figures, risk and distress checks, formulas and help texts, with follow-up suggestions and links. No outside AI service: no cost, works without internet access to any AI provider, nothing typed leaves the app, and messages aren't stored (only the topic is logged).
- **Your outlook, 1 to 12 months ahead:** a **Look ahead** bar above the risk check (1, 3, 6, 9, 12 months, or any month from the list). The choice changes the big risk card itself (its %, band, verdict and reasons) and is saved on the account. Until the model is retrained with this version, the bar says only 3 months is available. The owner also sees the chance of at least one loss month in that time, a bar for every month ahead (tap a bar to choose it), the reasons and tips for that horizon, and how well predictions that far ahead tested. At 3 months it equals the risk check. If the owner picks something other than 3 months, they also get an SMS/email warning when that outlook goes up a band, and the monthly email includes it. The assistant answers "what's my risk in the next 6 months?" too.
- **Financial distress check (logistic regression):** the chance of a cash shortfall or fast-rising debt in the next 3 months, what pushes it up or down, and the whole calculation term by term.
- **Business figures with formulas:** gross profit, gross margin, operating profit, net margin, net cash flow, the gap between profit and cash, break-even sales, margin of safety, sales received as money, costs per 100 shillings, months of stock, money owed in months of sales, average sale and M-Pesa share. Tap any figure to see its formula with the owner's own numbers.
- **Warnings from business rules:** for example selling below cost, gross profit not covering running costs, profit but cash going down, a cash shortfall in 2 of the last 3 months, sales below break-even, costs growing faster than sales. Each warning names the rule that triggered it.
- **Checks while typing:** figures that look wrong (sales of 0, costs far above sales, a missing or extra zero compared with last month) get a warning before they are saved.
- **Reports (PDF), to download or have emailed:** a free monthly summary; with Pro, a full **business report** for 6, 12 or 24 months (about 4 pages, up to 10 charts) and a summary for lenders.
- **Messages:** the monthly report by email, a reminder early each month to add last month's figures, and an SMS and email alert when the risk goes up a band. Each can be switched off.
- **Kiswahili or English**, switched from the top bar.
- **Installable** on a phone's home screen, like an app.
- **Feedback form** for the study (11 questions, 1–5 scale, and three open questions).
- **Charts the owner can switch:** five figures (profit, sales and costs, cash, margin, money owed), each shown as bar, line, area, pie, histogram or table, for the last 6 or 12 months or all months. Choices are remembered.
- **At-a-glance tiles:** sales, gross profit, profit and cash left over for the latest month, compared with the month before.
- Gap detection for missing months.
- **Biashara Pro**, paid with M-Pesa: import an M-Pesa statement (PDF or CSV) to fill in M-Pesa receipts and number of sales.
- An Account page in tabs (contact and messages, Biashara Pro, username and password, feedback, delete account): download your figures, change contact details or language, **change your username**, change password, delete your account and all data. Owners can always log in with their username, business code or email.

**For the study team**
- Progress meter towards 1,500 business-months, real and synthetic counted separately.
- The Admin page in tabs, under a summary of business-months collected: businesses, add a business, risk model, payments, email and SMS, feedback, activity log, admins.
- Businesses table: create logins, reset passwords, switch logins off, give Pro free, delete a business.
- Dataset export (CSV, no personal data) for the ML notebooks.
- Super admin with one-time invite codes for new admins.
- Payments list, M-Pesa connection check and callback test.
- **Risk model:** generate synthetic businesses or import a training CSV, train and compare four models, see PR-AUC, ROC-AUC, recall, precision, Brier score, the confusion matrix and SHAP feature importance.
- **Study report (PDF)** for the write-up, and a summary of the owners' feedback.
- Send the monthly reminders now, instead of waiting for the automatic run.
- Email and SMS status with test sends.
- Full activity log: who did what, when, from which IP.

**Works on phones** from 320 px wide. Fonts are stored in the app, and the installed app shows its screens even on a weak connection.

---

## Quick start (Windows)

You need **Python 3.12**, **XAMPP** (for MySQL) and **VS Code**.

1. **Install Python 3.12** from python.org and tick **Add python.exe to PATH**.
2. **Start MySQL** in the XAMPP Control Panel (Apache isn't needed).
3. **Create the database:** open http://localhost/phpmyadmin, create `sme_risk_db` with collation `utf8mb4_general_ci`.
4. **Open a terminal** in the project folder and run:

   ```
   cd C:\projects\sme-risk
   py -3.12 -m venv venv
   venv\Scripts\pip install -r requirements.txt
   copy .env.example .env
   ```

5. **Edit `.env`** and set `ADMIN_SIGNUP_CODE` to a secret of 8+ characters (see [Configuration](#configuration-env)).
6. **Start the app:**

   ```
   venv\Scripts\python -m uvicorn app.main:app --reload
   ```

   Wait for **Application startup complete**. Tables are created automatically.
7. **Create the first admin:** open http://127.0.0.1:8000/login → **Create account** → **Study admin**, and enter your `ADMIN_SIGNUP_CODE`. The first admin becomes the **super admin**. (Backup: `venv\Scripts\python -m app.create_admin`.)
8. **Train the risk model:** Admin → **Risk model** → add synthetic businesses (for example 120) → **Train the model**. Training takes under a minute. Until a model is trained, owners see the simple rule-based check.

| Page | Address |
| --- | --- |
| Login and sign-up | http://127.0.0.1:8000/login |
| Owner dashboard | http://127.0.0.1:8000/ |
| Account and Biashara Pro | http://127.0.0.1:8000/account |
| Admin console | http://127.0.0.1:8000/admin |
| API documentation | http://127.0.0.1:8000/docs |

---

## Starting the app every day

1. Start **MySQL** in XAMPP.
2. Either:
   - **Double-click `start-with-ngrok.bat`**: starts ngrok and the app together (needed for M-Pesa callbacks), or
   - run the app alone:
     ```
     cd C:\projects\sme-risk
     venv\Scripts\python -m uvicorn app.main:app --reload
     ```
3. Open http://127.0.0.1:8000/login. Press **Ctrl+F5** after an update so the browser loads the new pages.

To stop: **Ctrl+C** in the app window, and close the ngrok window.

---

## Configuration (.env)

Settings live in `.env` (never in `.env.example`, which is the shared blank template). The server reads `.env` only when it starts, so **restart after any change**. Never put `.env` on GitHub.

| Setting | What it does | Example |
| --- | --- | --- |
| `DATABASE_URL` | MySQL connection | `mysql+pymysql://root:@localhost:3306/sme_risk_db` |
| `ADMIN_SIGNUP_CODE` | Creates the **first** admin only (8+ characters) | a long secret |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM` | Sends email (Gmail: use an app password) | `smtp.gmail.com`, `587` |
| `TEXTBEE_API_KEY`, `TEXTBEE_DEVICE_ID` | Free SMS from your own Android phone | from textbee.dev |
| `AT_USERNAME`, `AT_API_KEY`, `AT_SENDER_ID` | SMS through Africa's Talking | `sandbox` for testing |
| `MPESA_ENV` | `sandbox` or `production` | `sandbox` |
| `MPESA_CONSUMER_KEY`, `MPESA_CONSUMER_SECRET` | Daraja app keys | from developer.safaricom.co.ke |
| `MPESA_SHORTCODE`, `MPESA_PASSKEY` | Leave empty in sandbox (test Paybill 174379 is used) | |
| `MPESA_TILL` | Only for a Buy Goods till | |
| `NGROK_URL` | Your fixed ngrok address, used by `start-with-ngrok.bat` | `https://your-name.ngrok-free.dev` |
| `MPESA_CALLBACK_URL` | Forces a callback address (normally found from ngrok) | |
| `PRO_PRICE_MONTH`, `PRO_PRICE_YEAR` | Biashara Pro prices in KES | `300`, `3000` |
| `CONTACT_KEY` | Encryption key for contacts (empty = `instance/contact.key` is created) | |
| `COOKIE_SECURE` | Set `true` when hosted on https | |
| `APP_URL` | Public address put in emails and SMS as a link | `https://biasharacheck.co.ke` |
| `REMINDERS` | `off` stops the automatic monthly reminders | `on` |
| `RENEWALS` | `off` stops Biashara Pro renewal notices and M-Pesa renewal prompts | `on` |

Without email, SMS or M-Pesa settings, the app still works: messages and codes are printed in the server window, and payments run in **test mode**.

> **Back up `instance/contact.key`.** Without it, saved emails and phone numbers can't be decrypted.

---

## Users and roles

| Role | Can do |
| --- | --- |
| **Business owner** | Sees only their own business: figures, risk check, charts, Pro, account |
| **Study admin** | Sees all businesses; creates logins; resets passwords; switches logins off; gives Pro free; exports data; views activity |
| **Super admin** | Everything an admin can do, plus invites new admins and switches admins off. There is always exactly one |

**Adding an admin:** Admin → **Admins** → **Generate code**. Give the one-time code to the new admin; they choose **Create account → Study admin** on the login page. Codes work once and expire after 24 hours, and generating a new one cancels the old one. The super admin can hand the role over to another admin (password needed) and can't delete their own account while other admins exist.

---

## Using Biashara Check

### Signing up
Fill in a business code (for example `SME-014`, never your name), type of business (16 types), email, Kenyan mobile number, password and both consents. Press **Continue**, then enter the 6-digit code from the email. The account is created only then. Write down the **recovery code** shown next.

### Entering figures
- **Add a month:** sales, cost of goods sold, running expenses, money received, money paid out; optional M-Pesa receipts, stock, money owed and number of sales. Profit and cash show as you type.
- Months that haven't ended yet are blocked, and duplicates are caught.
- **Upload a spreadsheet (any layout):** CSV or Excel (.xlsx). The app works out what each column is and shows a review before anything is saved:
  - column names in English or Kiswahili, with units like "(KES)", title rows above the table, totals rows, commas, semicolons or tabs;
  - one row per month, or one row per sale or expense (added up per month), or months across the top (turned around);
  - dates such as 2025-06, Jun 2025, June-25, 15/06/2025, Excel dates, or separate Year and Month columns; no dates at all → the owner picks the first month;
  - costs split over several columns (rent, wages, power...) or several sales columns (cash, M-Pesa) are added up; missing money in/out is worked out from sales and costs;
  - every assumption is listed under **How we read your file**, and **Check which column is which** lets the owner change any match;
  - a file with several businesses asks which one is theirs; months already saved stay as they are unless the owner ticks **Also update**.
  The template (`/template.csv`) still works for anyone who wants it.
- **Edit** on any row of Your records to fix or delete a month.
- A file in the wrong tab is spotted: monthly records put in the M-Pesa tab (or a statement in the CSV tab) get one button that moves the file to the right place.

### Risk check and charts
After 3 months the dashboard shows a risk band (green = low, amber = moderate, red = high).

- **With a trained model:** "Our model puts the chance of at least one loss month in the next 3 months at 64%", then the 3 main reasons (from SHAP) with what to do about each, what is keeping the risk down, and a strip showing the band for each past month. The check runs again every time a month is added, edited or deleted.
- **Before a model is trained:** a simple rule compares the last 3 months with the 3 before and lists warning signs.

**Charts:** choose the figure (Profit, Sales and costs, Cash, Margin, Money owed), then how to see it:

| Display | Shows |
| --- | --- |
| Bar, Line, Area | Each month over time; red bars are losses |
| Pie | The whole period: where sales went (cost of goods, running expenses, profit), M-Pesa vs other money received, profit vs loss months, months debt went up or down |
| Histogram | How many months fell in each range (for example, 2 months lost between KES 10,000 and 0) |
| Table | Every month's figure, newest first |

Hover, tap or use the arrow keys to read exact amounts.

### Reports and messages
Dashboard → **Reports (PDF)** opens a window with three reports. Each can be downloaded or sent to the owner's own confirmed email with **Email me** (up to 10 a day):
- **Monthly summary** (free): the latest month, the risk check, and the last 12 months.
- **Business report** (Pro): a period of 6, 12 or 24 months or everything, with 8 key figures compared with the period before, the risk check and how it changed, up to 10 charts (profit, sales and costs, where the money went, profit per 100, cash, money owed and stock, M-Pesa share, number of sales and average sale), highlights and a month-by-month table.
- **Summary for lenders** (Pro, 6+ months): 6–12 months of figures, totals, cash and debt, which months' M-Pesa figures came from a statement, and a signature line.
- **Account → Messages from Biashara Check:** switch the monthly report email, the monthly reminder and the risk alerts on or off. Messages only go to a confirmed email or mobile number.

### Feedback
After 3 months, the dashboard invites owners to rate the app. The form is at the bottom of the Account page.

### Username and password
- **Username:** Account → Username and password → **Change username** (needs the current password). 3–30 letters, numbers, dots, dashes or underscores; no phone or ID numbers. Owners can still log in with their business code or email. Each change is in the activity log.
- **Change password:** Account → Change password (other devices are logged out).
- **Forgot:** on the login page, reset by email code, SMS code (confirmed number) or recovery code.
- **Locked out of everything:** an admin gives a temporary password; the owner chooses a new one at first login.

### Deleting an account
Account → **Delete my account** (password + type the business code). It erases the business, every month, the login and the encrypted contacts. **Download my figures (CSV)** first if you want a copy. The activity log keeps the entry with IP addresses blanked.

---

## Biashara Pro and M-Pesa

**Biashara Pro** adds M-Pesa statement import, the full business report and the summary for lenders. Price: KES 300 a month or KES 3,000 a year (set in `.env`). Study participants can get it free: Admin → Businesses → **Give Pro** (90 days).

**Paying:** Account → Biashara Pro → choose a plan → enter the M-Pesa number → **Pay with M-Pesa**. The owner gets a PIN prompt (M-Pesa Express / STK Push), and the page waits for Safaricom's answer. Paying again adds time on top. **Check again with M-Pesa** under Your payments re-asks Safaricom about a payment from the last 3 days. Time is never added twice.

**End date and automatic renewal:**
- Account → Biashara Pro shows the exact end date and time (Nairobi time) with a **live countdown**, the plan, and whether it renews. The dashboard shows a small "Biashara Pro until … · N days left" label.
- **Renew automatically when this plan ends** is ticked by default when paying. M-Pesa can't take money without the PIN, so renewal works like this: 3 days before the end the owner gets an email/SMS saying when and how much; about 24 hours before, the app sends an M-Pesa prompt for the same plan to the saved number. Nothing is paid unless the owner enters their PIN. If it isn't paid, they're told, and Pro ends on its date.
- **Cancel automatic renewal** (Account → Biashara Pro) stops every future prompt at once and deletes the saved renewal number; Pro keeps working until its end date. **Turn renewal back on** reverses it. Pro given free by the study team never renews.
- The check runs every 30 minutes inside the app (`app/renewals.py`); Admin → Email and SMS → **Run renewals now** runs it at once; `RENEWALS=off` in `.env` stops it. Cancelling, turning on, notices and prompts are all in the activity log.

| Mode | When | What happens |
| --- | --- | --- |
| **Test** | No Daraja keys in `.env` | No prompt, no money; payments succeed at once (marked "test") |
| **Sandbox** | `MPESA_ENV=sandbox` + consumer key and secret | Safaricom's test system, Paybill 174379, always KES 1 |
| **Live** | `MPESA_ENV=production` + your shortcode, passkey (and till) | Real money; needs Safaricom go-live approval |

**Check the setup:** Admin → Biashara Pro and M-Pesa → **Check M-Pesa connection** (logs in to Daraja, charges nothing), or from the terminal:

```
venv\Scripts\python -m app.mpesa_check              # log in to Daraja only
venv\Scripts\python -m app.mpesa_check 0712345678   # also send a KES 1 sandbox prompt
```

**M-Pesa statement import (Pro):** Dashboard → **M-Pesa** tab → choose the statement PDF (with its password, usually the ID number) or a business-portal CSV → **Read statement**. Tick the months to update; they fill in M-Pesa receipts and number of sales. For a month not saved yet, **Add this month** pre-fills the form. Months the statement only partly covers are flagged.

---

## M-Pesa callbacks with ngrok

Safaricom sends each payment's final result and receipt number to a public https address. ngrok gives your laptop one. Without it, payments still work: the app asks Safaricom for the result instead.

1. Create a free account at ngrok.com, then:
   ```
   winget install ngrok.ngrok
   ngrok config add-authtoken YOUR_TOKEN
   ```
2. Copy your free address (ngrok dashboard → Domains, ends in `.ngrok-free.dev`) into `.env`:
   ```
   NGROK_URL=https://your-name.ngrok-free.dev
   ```
3. Start everything with **`start-with-ngrok.bat`**, or run ngrok yourself:
   ```
   ngrok http 127.0.0.1:8000 --url https://your-name.ngrok-free.dev
   ```
   Use `127.0.0.1`, not `localhost`, to avoid **502 Bad Gateway** on Windows.
4. Admin → **Test callback address** should say Safaricom can reach the app.

The app finds the ngrok address by itself from ngrok's local page (http://127.0.0.1:4040). The callback path contains a random secret (`instance/mpesa_callback.secret`), so results can't be faked. While ngrok runs, the app is reachable on that address (behind the login); free ngrok shows browser visitors a warning page first.

---

## The risk model

Code in `ml/` (details in `ml/README.md`).

- **Unit:** one business-month. **Label:** 1 if any of the next 3 months is a loss (net = sales − cost of goods − running expenses < 0). Months whose next 3 months aren't all recorded have no label and are only predicted, never used for training.
- **Features (month t and earlier only):** profit margin now and over 3 months, margin trend, loss months in the last 3, sales and cost growth, costs growing faster than sales, month-on-month sales change, cost ratios, net cash flow, months with negative cash, M-Pesa share, change in number of sales, debt to sales and debt growth, stock to sales, business age, time of year, type of business.
- **Validation:** time-based. The latest 20% of months are the test set; training stops 3 months earlier so that no label looks into the test period.
- **Models:** logistic regression (baseline), random forest, XGBoost, LightGBM, all weighted for the rarer loss class. The one with the best PR-AUC is refitted on all labelled months and saved to `ml/artifacts/` (not committed; train again on each computer).
- **Calibration:** the class weighting pushes the % up, so the chosen model is Platt-scaled (chance = 1 / (1 + e^-(a·logit(p) + b))). The scaler is fitted on a calibration window inside the training months (the last 20% of them, with the same 3-month gap), never on the test months. It keeps the ranking (PR-AUC, ROC-AUC, SHAP reasons) and makes the % match how often losses actually followed.
- **Bands:** Low below 35%, Moderate from 35%, High from 60%.
- **Explanations:** SHAP values for that business-month, turned into sentences with an action for each, in English or Kiswahili.

**Synthetic data:** Admin → Risk model → **Add synthetic businesses** creates businesses coded `SYN-001` and up, with 18–36 months each and realistic patterns (healthy, declining, costs creeping up, a sudden shock, up-and-down), flagged as synthetic and counted separately. Remove them all with one button. From the terminal:

```
venv\Scripts\python -m ml.synthetic --businesses 120
venv\Scripts\python -m ml.train               # or --real-only once there are enough real months
venv\Scripts\python -m ml.synthetic --remove
```

**A ready-made training file:** `data/training/biashara_training_data.csv` has 500 synthetic businesses and 18,088 business-months (July 2022 to September 2026). Load it with Admin → Risk model → **Import training CSV** (or `venv\Scripts\python -m ml.import_csv data/training/biashara_training_data.csv`), then train. Imported businesses are always marked synthetic. On this file the random forest reached a PR-AUC of 0.89 and caught 80% of coming losses; training takes about a minute. Columns are explained in `data/training/README.md`.

### Is it machine learning, statistics or rules?

All three, each for a different job:

| Part | Kind | How |
| --- | --- | --- |
| Business figures | Arithmetic | Fixed formulas (`app/finance.py`) |
| Warnings | Rule-based | Fixed if-then thresholds, each shown with its rule (`app/finance.py`) |
| Outlook, 1-12 months | Machine learning | One LightGBM for all horizons, anchored to the 3-month % (`ml/horizon.py`) |
| Loss risk % | Machine learning | Best of four models, calibrated, explained with SHAP (`ml/train.py`, `ml/predict.py`) |
| Financial distress % | Statistical model | Unpenalised logistic regression with standard errors and tests (`ml/distress.py`) |
| Check before a model exists | Rule-based | "The next 3 months look like the last 3" |
| Ask (chat assistant) | Rule-based | Topic matching with typo tolerance, answers from the owner's data (`app/assistant.py`) |

### How accurate is it?

Every training run saves its test evidence, shown to owners and admins on **How it's calculated** (`GET /method/evidence`):
- **What happened after each band** in the test months. On the ready-made training file: about 5% of Low months, 42% of Moderate months and 84% of High months were followed by a loss.
- **Calibration table and chart:** predicted chance against the share actually followed by a loss, in 7 ranges.
- **Comparison** of the four models and a simple no-ML rule (last 3 months' average margin below zero) on the same months. The best model catches about 80% of coming losses against about 53% for the rule.
- **Recall, precision, PR-AUC, ROC-AUC, Brier score and the confusion matrix** in plain words.
- **The owner's track record:** each saved risk check against what happened in the 3 months after it (High followed by a loss, or Low without one, counts as right).
- The page says plainly how much of the training data is synthetic, and that real-world accuracy is being measured in the study.

### The 1-12 month outlook

`ml/horizon.py`, trained together with the main model.

- **Question:** for a chosen horizon h (1-12 months), the chance of at least one loss month in months t+1..t+h.
- **One model for every horizon:** each past business-month is used once per horizon whose months are all recorded, with h as an extra input (about 178,000 examples from the 18,088 months in the training file). LightGBM, no class weights, with a monotone constraint so the chance can only rise with h.
- **Agrees with the risk check:** the whole curve is shifted on the log-odds scale so its 3-month point equals the main model's calibrated %, then a running maximum keeps it non-decreasing.
- **Leak-free test:** the latest 25% of months are the test period; a training example is used only if its whole label window ends before that. Per horizon the meta saves test months, loss share, ROC-AUC, PR-AUC, recall, precision, Brier (anchored and not) and what happened after each band. On the training file ROC-AUC goes from about 0.96 at 1 month to about 0.90 at 12; 80-90% of months rated High had a loss at every horizon, against 4-12% of those rated Low.
- **API:** `GET /businesses/{code}/outlook?months=1..12`; the preference is `outlook_months` in `PUT /auth/settings`.
- Training the full file now takes about 2 minutes instead of about 1.

### The financial-distress model (logistic regression)

- **Label:** 1 if over months t+1 to t+3 money paid out adds up to more than money received (a cash shortfall), or money owed rises by more than half a month's sales (`ml/features.py`).
- **Model:** log-odds = b0 + Σ bᵢ·zᵢ with zᵢ = (value − mean) / sd for 8 figures: margin over 3 months, loss months in the last 3, cash left over per 100 of sales, months with more cash out than in, sales trend, money owed in months of sales, change in money owed, stock in months of sales. Fitted by maximum likelihood with no penalty and no class weights, so the chances are not pushed up or down. "Costs vs sales growth" was left out because it overlaps with margin so much that its sign flipped (multicollinearity).
- **Statistics saved:** coefficients, standard errors (inverse Fisher information), z, p-values, odds ratios with 95% intervals, McFadden pseudo-R², likelihood-ratio test, and on the test months ROC-AUC, PR-AUC, Brier score, a calibration table and the Hosmer-Lemeshow test. On the training file: ROC-AUC about 0.94, McFadden R² about 0.36.
- **On the dashboard:** the %, the band, what pushes it up and down, and **See the full calculation** (each figure, its z, weight and effect, the intercept, the total log-odds and 1 / (1 + e^-total)) so it can be checked with a calculator.
- Trained together with the main model by `python -m ml.train` or Admin → Risk model → Train.

### Business figures and formulas

`GET /businesses/{code}/figures` (dashboard card **Your business figures**):

| Figure | Formula |
| --- | --- |
| Gross profit | sales − cost of goods sold |
| Gross margin | gross profit ÷ sales |
| Operating profit | gross profit − running expenses (below zero = loss month) |
| Net margin | operating profit ÷ sales |
| Net cash flow | money received − money paid out |
| Profit vs cash difference | operating profit − net cash flow |
| Break-even sales | running expenses ÷ gross margin |
| Margin of safety | (sales − break-even) ÷ sales |
| Sales received as money | money received ÷ sales |
| Costs per 100 shillings | (cost of goods + running expenses) ÷ sales |
| Months of stock | closing stock ÷ cost of goods sold |
| Money owed in months of sales | money owed ÷ sales |
| Average sale | sales ÷ number of sales |
| M-Pesa share | M-Pesa receipts ÷ money received |

It also returns a profit-and-loss and cash-flow statement for the latest month, 3-month trends, the rule-based warnings, data-integrity checks (gaps, months that look like typing mistakes, changes logged, a SHA-256 fingerprint of all figures) and the track record.

On 120 synthetic businesses all four models reach a PR-AUC of about 0.65–0.75 and a ROC-AUC of about 0.83–0.85 (a model guessing at random would get a PR-AUC equal to the share of months followed by a loss, about 0.2). Which model wins changes with the generated data. These figures describe synthetic data only; retrain with `--real-only` once enough real months are collected.

---

## Reports

| Report | Where | Contents |
| --- | --- | --- |
| Monthly summary | Dashboard → **Reports (PDF)**; also emailed when a month is added | Key figures for the latest month, the last 12 months with a profit chart, risk and reasons |
| Business report (Pro) | Dashboard → **Reports (PDF)**, period 6, 12, 24 months or all | 8 key figures, risk and its history, up to 10 charts, highlights, month-by-month table |
| Summary for lenders (Pro, 6+ months) | Dashboard → **Reports (PDF)** | 6–12 months of figures and totals, cash and debt, M-Pesa months from statements, signature line |
| Study report | Admin → **Study report (PDF)** | Data collected, data completeness, participants, questionnaire results, model comparison, confusion matrix, SHAP feature importance |

Reports need `reportlab` (`venv\Scripts\pip install reportlab==4.2.5`).

---

## Email and SMS

- **Email (Gmail):** turn on 2-Step Verification, create an **app password** at myaccount.google.com/apppasswords, and set the `SMTP_*` settings. A dedicated Gmail account for the app is recommended.
- **SMS:** `TEXTBEE_API_KEY` (free, 50 a day / 300 a month, sends from your Android phone) takes priority; otherwise Africa's Talking (`AT_USERNAME=sandbox` shows messages only in their simulator).
- Admin → **Email and SMS** shows each one as live, sandbox or not set up, and sends a test message.
- **Automatic messages:**
  - *Monthly report email:* after the owner adds the newest month, once per month.
  - *Reminder:* from the 2nd to the 10th of each month, after 9 am Nairobi time, to owners who haven't added last month. Once per owner per month. Admin → **Send reminders now** runs it at once. `REMINDERS=off` in `.env` stops it.
  - *Risk alert:* when a new check puts the business in a higher band (Low → Moderate, Moderate → High), by SMS and email.
  - All are logged in the activity log and respect the owner's choices on the Account page. Set `APP_URL` so messages include a link to the app.

---

## Kiswahili and the phone app

- **Kiswahili:** press **Kiswahili** in the top bar (**SW** on a phone). The choice is saved on the account, so it follows the owner to other devices, and the risk reasons and tips come from the server in Kiswahili. Press **English** to switch back. The admin pages stay in English. The assistant answers in the language the question is written in; its main answers (figures, risk, what-ifs, advice) are in Kiswahili too, while some longer help texts are still English-only.
- **Installing in one tap:** every "Install the app" button (the green card on the dashboard, the link under the login form, the Get the app page) opens the phone's own install prompt straight away when the browser allows it. When it doesn't (iPhone, or a browser that hasn't offered it yet), it opens a guide with a big arrow pointing at the browser menu. The Android install dialog shows screenshots of the app (`app/static/icons/screens/`).
- **ngrok note:** the free ngrok address shows its warning page once and then remembers you with a cookie. Pages now fetch the app's install details (`manifest.webmanifest`) with that cookie, so Chrome can offer Install. If the Get the app page still says the address is blocking installation, use the browser menu → *Add to Home screen*, or a hosted / paid-ngrok address.
- **Get the app** page (`/install`, linked from the login page, the dashboard and the Account page; no login needed): an **Install** button when the browser offers it, steps for Android, iPhone/iPad and computers (picked automatically), a QR code to open the app on a phone from a computer, and answers to common questions (cost, offline use, updates, removing it). It's an installable web app (PWA), so there's no Play Store or App Store listing and nothing to approve; it updates itself. On `127.0.0.1` the page warns that a phone can't open that address and points to the ngrok or hosted https address.
- **Install on a phone:** open the app in Chrome on Android and choose **Install app** in the top bar (or the browser menu → *Add to Home screen*; on iPhone, Share → *Add to Home Screen*). It opens full screen with its own icon. Installing needs https, so use the ngrok address or the hosted site, not `127.0.0.1`, on the phone.
- Figures are never stored on the phone: they always come fresh from the server. With no connection, the installed app shows a short offline message.

---

## Security and privacy

- No owner names or ID numbers; businesses are codes such as `SME-001`.
- Emails and phone numbers encrypted (Fernet), looked up by keyed hash, masked for admins; every reveal is logged; never exported.
- Passwords hashed with scrypt; server-side sessions in HttpOnly cookies; 5 wrong passwords lock a login for 10 minutes.
- Email confirmed before an account exists; pending sign-ups are encrypted and expire after 15 minutes.
- M-Pesa statements are read in memory and discarded; only monthly totals are kept; passwords never stored.
- Payment receipts are kept when a business is deleted (financial records) but unlinked, with the phone blanked.
- Activity log of logins, changes to figures, uploads, payments and admin actions.
- Research consent and contact consent recorded with timestamps; owners can export and erase their data.
- **Data integrity:** validation when typing and uploading, every change logged, every prediction stamped with its model version and kept, and a SHA-256 fingerprint of all of a business's figures, printed in the footer of the owner's PDF reports, so a report can be matched to the records it came from.
- Usernames can be changed but can't be phone or ID numbers; the business code keeps working for login.
- Owners can read all of this in plain words on **How it's calculated → Your data and privacy**.

---

## Backups

Double-click **`backup.bat`** (or schedule it, see below). It saves to `backups\YYYY-MM-DD_HHMM\`:

- `sme_risk_db.sql`: the whole database (with XAMPP's `mysqldump`);
- `instance\contact.key` and `instance\mpesa_callback.secret`: **without `contact.key`, saved emails and phone numbers can't be read**;
- `.env` and the trained model.

It keeps the last 14 backups. Copy the `backups` folder to a flash disk or Google Drive now and then: a backup on the same laptop doesn't help if the laptop is lost. The folder is never committed (it holds the database and `.env`).

**Schedule a daily backup at 8 pm** (run once in a terminal):
```
schtasks /Create /SC DAILY /ST 20:00 /TN "Biashara Check backup" /TR "C:\projects\sme-risk\backup.bat --quiet"
```

**Restore:** start MySQL, then
```
C:\xampp\mysql\bin\mysql -u root sme_risk_db < backups\2026-10-10_2000\sme_risk_db.sql
```
and copy the `instance` files back into `instance\`.

---

## Hosting it online

`docs/DEPLOYMENT.md` explains running Biashara Check on a cloud server (Ubuntu, MySQL, Caddy for https) at an address such as `biasharacheck.co.ke`, and the settings to change for that: `COOKIE_SECURE=true`, `APP_URL`, live Daraja keys and the callback address.

---

## Project structure

```
sme-risk/
├── app/
│   ├── main.py            app start-up, pages, /sectors
│   ├── database.py        MySQL connection and column upgrades
│   ├── models.py          tables
│   ├── schemas.py         input validation
│   ├── auth.py            passwords, sessions, lockout, access rules
│   ├── contacts.py        email/phone checks, codes, activity log
│   ├── crypto.py          contact encryption
│   ├── erase.py           right to erasure
│   ├── invites.py         super admin and admin invite codes
│   ├── mailer.py          email (Gmail SMTP)
│   ├── sms.py             SMS (TextBee, Africa's Talking)
│   ├── mpesa.py           Daraja: STK Push, query, callback address, ngrok detection
│   ├── mpesa_check.py     command-line Daraja check
│   ├── pro.py             Biashara Pro plans and status (end date, renewal)
│   ├── renewals.py        renewal notices and M-Pesa renewal prompts (every 30 minutes)
│   ├── statements.py      M-Pesa statement reader (PDF, CSV)
│   ├── sectors.py         the 16 types of business
│   ├── risk.py            risk check: model prediction, distress check, history, track record, refresh after changes
│   ├── finance.py         business figures with formulas, rule-based warnings, data-integrity checks
│   ├── assistant.py       the built-in chat assistant (no outside AI): topics, figures, what-ifs, help texts
│   ├── rules.py           the simple rule-based check (before a model is trained)
│   ├── reports.py         PDF reports: monthly summary, business report (Pro), lender summary, study report
│   ├── notify.py          monthly report email, reminders, risk alerts
│   ├── create_admin.py    command-line admin creation
│   ├── routers/           auth, businesses, uploads, statements, payments, feedback, method, assistant, admin
│   └── static/            pages, styles, scripts (how.html/how.js = How it's calculated, assistant.js = the chat panel, charts.js = the six chart displays, i18n.js = Kiswahili, sw.js + pwa.js = phone app), fonts, icons
├── data/
│   ├── samples/           test CSVs and fictional M-Pesa statements
│   ├── templates/         CSV upload template
│   ├── training/          ready-made synthetic training CSV (500 businesses) and its column guide
│   ├── raw/               real SME records (never committed)
│   └── processed/         cleaned dataset for modelling
├── ml/
│   ├── synthetic.py       synthetic businesses for training and testing (or a training CSV)
│   ├── import_csv.py      load a training CSV as synthetic businesses
│   ├── features.py        features and the 90-day loss label
│   ├── train.py           model comparison, calibration, test evidence, SHAP importance, saving
│   ├── distress.py        financial-distress logistic regression with its statistics
│   ├── horizon.py         the 1-12 month outlook (one model for every horizon, anchored to the 3-month check)
│   ├── predict.py         one business's risk with reasons (English and Kiswahili)
│   └── artifacts/         the trained model (never committed)
├── docs/DEPLOYMENT.md     hosting on a cloud server
├── notebooks/             exploration and model comparison
├── tests/test_api.py      automated tests
├── instance/              contact.key, callback secret (never committed; back up)
├── start-with-ngrok.bat   starts ngrok and the app
├── backup.bat, backup.ps1 database and key backup
├── backups/               backup folders (never committed)
├── requirements.txt
└── .env.example           settings template
```

**Main tables:** `businesses`, `monthly_records` (one row per business-month), `users`, `login_sessions`, `contacts`, `one_time_codes`, `pending_signups`, `admin_invites`, `payments`, `predictions` (each risk check, kept for the history), `feedback`, `audit_log`.

---

## API overview

Full interactive documentation at **/docs**.

| Area | Endpoints |
| --- | --- |
| Sign-up and login | `POST /auth/register`, `/auth/register-admin`, `/auth/register/confirm`, `/auth/register/resend`, `/auth/login`, `/auth/logout`, `GET /auth/me` |
| Account | `PUT /auth/contact`, `/auth/email/*`, `/auth/phone/*`, `/auth/change-password`, `/auth/forgot`, `/auth/reset-with-code`, `/auth/recover`, `/auth/delete-account`, `PUT /auth/settings` (messages, language), `PUT /auth/username`, `POST /auth/tour-done` |
| Figures | `GET/POST /businesses/{code}/records`, `PUT/DELETE /businesses/{code}/records/{month}`, `POST /businesses/{code}/upload-csv`, `GET /template.csv` |
| Risk and reports | `GET /businesses/{code}/risk` (with the distress check), `GET /businesses/{code}/outlook?months=1..12`, `GET /businesses/{code}/figures`, `GET /method/evidence`, `/businesses/{code}/report.pdf`, `/businesses/{code}/business-report.pdf?months=` (Pro), `/businesses/{code}/loan-report.pdf` (Pro), `POST /businesses/{code}/reports/email` |
| Assistant | `POST /assistant/ask` `{message, context}` → `{reply, intent, suggestions, links, lang, context}` (owners; 300 a day) |
| Feedback | `GET /feedback/questions`, `POST /feedback` |
| M-Pesa statement (Pro) | `POST /businesses/{code}/mpesa-statement`, `/businesses/{code}/mpesa-statement/apply` |
| Payments | `GET /payments/pro`, `POST /payments/stk` (`auto_renew`), `POST /payments/auto-renew` (`{on}`: cancel or turn on renewal), `GET /payments/{id}`, `POST /payments/{id}/check`, `POST /payments/mpesa/callback/{secret}` |
| Admin | `/admin/overview`, `/admin/businesses`, `/admin/export.csv`, `/admin/activity`, `/admin/admins`, `/admin/invite`, `/admin/payments`, `/admin/mpesa/check`, `/admin/mpesa/callback-test`, `/admin/messaging`, `/admin/model`, `/admin/model/train`, `/admin/synthetic`, `/admin/training-csv`, `/admin/study-report.pdf`, `/admin/reminders/send`, `/admin/feedback` |

---

## Testing

```
cd C:\projects\sme-risk
venv\Scripts\python -m pytest
```

77 automated tests cover the 1-12 month outlook (curve, anchoring, warnings), the install page and app manifest, sign-up, changing usernames, the chat assistant and its links, cancelling and renewing Biashara Pro, business figures and their formulas, the distress model (its sum adds up to the probability shown), the test evidence, login, roles, records, CSV upload, contacts, password resets, admin invites, deletion, M-Pesa payments (with Safaricom's replies simulated), callbacks, statement import, ngrok detection, synthetic data, features and labels, model training and prediction, Kiswahili reasons, PDF reports (including the business report), emailing a report to yourself, importing a training CSV, the report email, reminders, risk alerts, the feedback form and the phone-app files. Tests use a temporary SQLite file and ignore your `.env` email, SMS and M-Pesa settings, so they never touch real data or send anything.

---

## Sample files

| File | Use |
| --- | --- |
| `data/samples/1_healthy_shop_LOW.csv` | Upload to see a low-risk business |
| `data/samples/2_costs_creeping_MODERATE.csv` | Costs rising faster than sales |
| `data/samples/3_heading_to_loss_HIGH.csv` | A business heading for a loss |
| `data/samples/4_with_mistakes_ERRORS.csv` | Shows the upload error messages |
| `data/samples/sample_SME-001.csv` | 24 months of example figures |
| `data/samples/mpesa_statement_SAMPLE.pdf` | Fictional M-Pesa statement, password `12345678` |
| `data/samples/mpesa_business_SAMPLE.csv` | The same fictional statement as a business-portal CSV |

The fictional statements are made by `data/samples/make_mpesa_samples.py`; they are not real statements.

---

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `No module named app` | You're in the wrong folder: `cd C:\projects\sme-risk` first |
| `127.0.0.1 refused to connect` | The app isn't running: start it and wait for "Application startup complete" |
| "Can't load your figures" | MySQL isn't running in XAMPP |
| A setting has no effect | It's in `.env.example` instead of `.env`, or the server wasn't restarted |
| Statement import shows error about PDF reading | Run `venv\Scripts\pip install pdfplumber==0.11.4` and restart |
| Report button says reports aren't installed | Run `venv\Scripts\pip install reportlab==4.2.5` and restart |
| "Not enough data to train yet" | Add synthetic businesses first (Admin → Risk model), then train |
| Risk card still shows the simple check | No model is trained on this computer yet (the model file isn't copied with the code) |
| No **Install app** button | Installing needs https: open the ngrok address or the hosted site in Chrome |
| Payment says "still processing" | Wait a minute, then **Check again with M-Pesa** under Your payments |
| "Safaricom rejected the consumer key or secret" | Check the Daraja keys in `.env` and that `MPESA_ENV` matches the app (sandbox or production) |
| ngrok shows **502 Bad Gateway** | The app isn't running, or use `ngrok http 127.0.0.1:8000` instead of `localhost` |
| ngrok `ERR_NGROK_334` (already online) | Another ngrok is running: `taskkill /IM ngrok.exe /F`, then start again |
| Email didn't arrive on your phone | Emails sent to yourself go to Sent; test with another address and check spam |
| Page looks old after an update | Restart the app; pages ask for the newest styles and scripts by themselves. If not, press **Ctrl+F5** |
| "Couldn't find the 'Paid In' column" | That's a monthly records file, not an M-Pesa statement: press **Upload it as monthly records** |
| **Email me** is greyed out | Confirm your email on the Account page first |

---

## Roadmap

Done: features and label, model comparison, SHAP explanations, PDF reports, messages and alerts, feedback form, Kiswahili, installable app, backups.

Next:
1. Collect real months from partner SMEs and retrain with `--real-only`; compare with the synthetic results.
2. User testing with owners using the feedback form and short interviews.
3. Calibrate the probability (for example isotonic) once there is enough real data.
4. A 90-day cash forecast for Biashara Pro.
5. Pilot hosting on a cloud server with HTTPS; live Daraja Paybill or Till.

---

*Biashara Check is decision support, not a guarantee of business outcomes or financial advice.*
