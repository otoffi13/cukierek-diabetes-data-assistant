# Agent Cukierek

**Agent Cukierek** is a local data-processing and AI-assisted analysis project for exploring how glucose, insulin, carbohydrate intake, and menstrual cycle phase may relate to day-to-day changes in insulin sensitivity.

The project combines exported data from:

* **Glooko** — glucose, CGM, insulin, basal, bolus and carbohydrate data
* **Samsung Health** — menstrual cycle logs and Samsung Health cycle predictions
* **Ollama** — optional local language model used to generate natural-language daily summaries

The system is designed to run locally on the user's computer. Medical and health-related source files are not intended to be uploaded to GitHub.

---

## Important medical disclaimer

This project is for **personal data analysis and educational purposes only**.

It does **not** provide medical advice, insulin dosing recommendations, therapy instructions, or treatment decisions.
The calculated insulin sensitivity index is a **relative descriptive indicator**, not a clinical insulin sensitivity factor.

Any diabetes treatment decisions should be made according to medical advice and the user's approved diabetes management plan.

---

## Main features

* Imports Glooko ZIP exports directly without permanently unpacking them.
* Imports Samsung Health ZIP exports directly.
* Stores normalized historical data in a deduplicated event-level history.
* Handles overlapping reports safely.
* Preserves older data while adding newly available records.
* Rebuilds daily glucose, insulin, carbohydrate, and cycle features from the full history.
* Builds a relative daily insulin sensitivity index.
* Uses Ollama locally to generate a readable daily explanation.
* Can send a morning email notification.
* Supports scheduled execution with Windows Task Scheduler.

---

## How the data pipeline works

The intended workflow is:

```text
Glooko/Samsung Health ZIP export
→ temporary extraction
→ source-specific importer
→ normalized historical storage
→ event-level deduplication
→ daily feature generation
→ insulin sensitivity index
→ optional Ollama explanation
→ optional email notification
```

Processed ZIP files can be archived or deleted after successful import, depending on the configured retention mode.

---

## Project structure

```text
agent_cukierek/
├── src/
│   ├── process_zip_exports.py
│   ├── import_glooko.py
│   ├── import_samsung_cycle.py
│   ├── history_store.py
│   ├── build_sensitivity_index.py
│   ├── daily_prediction_message.py
│   └── agent_cli.py
│
├── data_raw/                  # local ZIP input folders, ignored by Git
│   ├── glooko/
│   └── samsung_health/
│
├── data_history/              # deduplicated normalized history, ignored by Git
├── data_processed/            # generated daily tables, ignored by Git
├── data_archive/              # archived processed ZIP files, ignored by Git
├── reports/                   # generated reports/messages, ignored by Git
├── run_morning_prediction.bat
├── README.md
└── .gitignore
```

Only the source code and documentation should be committed to GitHub.

---

## Data sources

### Glooko

The project expects Glooko export ZIP files containing CSV files such as:

```text
bg_data_1.csv
cgm_data_1.csv
cgm_carbs_data_1.csv
Insulin data/basal_data_1.csv
Insulin data/bolus_data_1.csv
Insulin data/insulin_data_1.csv
Manual data/food_data_1.csv
Manual data/manual_insulin_data_1.csv
```

### Samsung Health

The project expects Samsung Health export ZIP files containing cycle-related CSV files such as:

```text
com.samsung.health.cycle.flow...
com.samsung.health.cycle.profile...
com.samsung.shealth.cycle.prediction...
```

The system distinguishes between:

* actually logged period data,
* Samsung Health predictions,
* cycle-day estimates inferred from actual data,
* cycle-day estimates inferred from predicted data.

---

## Deduplication and overlapping reports

The project is designed to support overlapping exports.

For example:

```text
First report:  June 1–14
Second report: June 8–21
```

The final historical dataset should contain:

```text
June 1–21
```

Records from June 8–14 are recognized as duplicates and are not counted twice.
New records from June 15–21 are added to the history.

Deduplication is performed at the event level, not at the date level. This means that if an export contains only half of a day and a later export contains the full day, the missing records from the second half of the day can still be added.

---

## Requirements

* Python 3.11+
* pandas
* requests
* Ollama, optional but recommended for natural-language summaries

Install Python dependencies:

```bash
pip install pandas requests
```

Install and run Ollama separately:

```bash
ollama pull llama3.1:8b
```

The project can still run without Ollama, but daily explanations will use fallback text instead of a local language model response.

---

## Environment variables

Secrets are not stored in the source code.

Email settings are read from Windows environment variables:

```powershell
setx AGENT_EMAIL_FROM "your-email@gmail.com"
setx AGENT_EMAIL_TO "your-email@gmail.com"
setx AGENT_EMAIL_APP_PASSWORD "your-gmail-app-password"
```

`AGENT_EMAIL_APP_PASSWORD` should be a Gmail app password, not the main Google account password.

After setting environment variables with `setx`, close and reopen PowerShell.

Optional ZIP retention mode:

```powershell
setx ZIP_RETENTION_MODE "archive"
```

Supported values:

```text
archive   move processed ZIP files to data_archive/
delete    delete ZIP files after successful import
keep      leave ZIP files in place
```

The recommended mode is:

```text
archive
```

---

## Importing new data

Place ZIP exports in local input folders, for example:

```text
data_raw/glooko/
data_raw/samsung_health/
```

Then run:

```bash
python src/process_zip_exports.py
```

The processor will:

1. detect ZIP files,
2. classify them as Glooko or Samsung Health exports,
3. temporarily extract them,
4. run the correct importer,
5. update the deduplicated history,
6. rebuild daily feature tables,
7. move successfully processed ZIPs to the archive.

---

## Building the insulin sensitivity index

After importing data, run:

```bash
python src/build_sensitivity_index.py
```

This creates a relative daily sensitivity index based on available glucose, insulin, carbohydrate, and cycle features.

The index is descriptive and relative. It is not a medical insulin sensitivity factor.

---

## Generating a daily prediction message

To generate a daily message:

```bash
python src/daily_prediction_message.py
```

The script can:

* read recent glucose, insulin, carbohydrate, and cycle data,
* estimate whether today may be closer to lower, typical, or higher relative sensitivity,
* ask Ollama to generate a short explanation,
* send the message by email if email environment variables are configured.

---

## Morning automation

A Windows batch file can run the full morning workflow:

```bat
@echo off
cd /d C:\Users\grosz\Documents\agent_cukierek

python .\src\process_zip_exports.py
python .\src\build_sensitivity_index.py
python .\src\daily_prediction_message.py
```

This file can be scheduled with Windows Task Scheduler, for example at 08:30 every morning.

Example command:

```powershell
schtasks /Create /SC DAILY /TN "Agent Cukierek - morning prediction" /TR "C:\Users\grosz\Documents\agent_cukierek\run_morning_prediction.bat" /ST 08:30
```

---

## Privacy and repository safety

Do not commit medical data, ZIP exports, generated CSV files, reports, logs, or secrets.

Recommended `.gitignore`:

```gitignore
# Medical data and exports
data_raw/
data_history/
data_processed/
data_archive/
reports/
logs/

# Exported/generated files
*.zip
*.csv
*.xlsx

# Secrets and local configuration
.env
*.env

# Python
__pycache__/
*.pyc
.venv/
venv/

# System files
.DS_Store
Thumbs.db
```

Before committing, check staged files:

```bash
git status
git diff --cached --name-only
```

Only source code, documentation, and safe configuration examples should be committed.

---

## Current limitations

* Fresh Glooko and Samsung Health exports still need to be provided by the user.
* The system does not automatically download data from Glooko or Samsung Health accounts.
* Daily predictions depend on how recent the imported data is.
* Cycle predictions from Samsung Health are treated as predictions, not confirmed biological events.
* The model is exploratory and should not be used for treatment decisions.

---

## License

This project is intended for personal and educational use. Add a license file before publishing it as an open-source project.
