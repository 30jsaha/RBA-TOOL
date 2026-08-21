# Setup Checklist
### Tax Fraud Detection System — Developer Onboarding
*Print this page. Check off each box as you complete it.*

---

## Phase 1 — Prerequisites

- [ ] Python 3.10+ installed (`python --version` to verify)
- [ ] MySQL Server 8.0+ installed and running
- [ ] MySQL Workbench installed (for viewing database)
- [ ] Project folder extracted / cloned to your machine
- [ ] You have the MySQL `root` password (or a dedicated DB user + password)

---

## Phase 2 — Python Environment

- [ ] Opened terminal and navigated to project root folder
- [ ] Created virtual environment: `python -m venv venv`
- [ ] Activated virtual environment
  - Windows: `.\venv\Scripts\Activate.ps1`
  - Mac/Linux: `source venv/bin/activate`
- [ ] Confirmed `(venv)` appears at the start of your terminal prompt
- [ ] Installed all dependencies: `pip install -r requirements.txt`
- [ ] No red error messages during install

---

## Phase 3 — Database & Configuration

- [ ] Created MySQL database: `CREATE DATABASE rba_tool_database;`
- [ ] Copied `.env.example` to `.env`: `cp .env.example .env`
- [ ] Opened `.env` and filled in `DB_PASSWORD` with your MySQL password
- [ ] Confirmed `DB_USER` and `DB_NAME` match your MySQL setup
- [ ] Left all file paths unchanged (unless you moved folders)

---

## Phase 4 — First Run

- [ ] Started the API server: `python api/app.py`
- [ ] Server started without errors (check terminal output)
- [ ] Saw "Connected to MySQL: localhost:3306/rba_tool_database" in terminal
- [ ] Opened browser and visited: `http://localhost:5000/api/health`
- [ ] Received response: `{"status": "ok", "message": "Tax Fraud Detection API is running"}`
- [ ] Opened MySQL Workbench and confirmed `rba_tool_database` now has tables

---

## Phase 5 — Smoke Test (Optional but Recommended)

- [ ] Ran full API test suite: `python test_api_irc.py`
- [ ] Saw: `43 passed  0 failed  0 skipped`
- [ ] Ran multi-tax tests: `python test_multitax.py`
- [ ] Saw: `6 passed  0 failed  0 skipped`

---

## Known Expected Behaviours

| Observation | Is This Normal? |
|-------------|-----------------|
| GST pipeline takes ~6 minutes | ✅ Yes — it processes 1.3 million records |
| SWT pipeline takes ~3 minutes | ✅ Yes — 1.4 million records |
| CIT pipeline takes ~2 minutes | ✅ Yes |
| `/api/gst/results` returns empty right after starting | ✅ Yes — pipeline still running; poll `/api/gst/status/<run_id>` |
| Seeing `NaN` values in some JSON responses | ✅ Yes — these are null numeric fields from the source data |
| APScheduler warning in terminal about job timing | ✅ Harmless — it schedules the nightly 01:00 table refresh |

---

## Who to Contact

| Question | Contact |
|----------|---------|
| Python/API issues | Data Science Team |
| MySQL access / permissions | System Administrator |
| Tax domain questions (what counts as fraud) | Tax Technical Team |
| Frontend integration | Frontend Development Team |

---

*IRC Papua New Guinea — Version 1.0 — April 2026*
