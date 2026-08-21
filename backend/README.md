# RBA-TOOL Backend API & ML Pipelines

The backend for **RBA-TOOL** is built with Python 3.10+ and Flask. It serves RESTful APIs for the web interface, manages MySQL database connections, handles JWT authentication, and executes machine learning inference pipelines across **GST**, **SWT**, and **CIT** tax datasets.

---

## 📁 Backend Directory Structure

```
backend/
├── api/                      # Main Flask Application
│   ├── app.py                # Server entry point & blueprint registration
│   ├── extensions.py         # SQLAlchemy & extension instances
│   ├── routes/               # API endpoint definitions
│   │   ├── auth_routes.py    # Login, token refresh & authentication
│   │   ├── gst_routes.py     # GST pipeline & audit routes
│   │   ├── swt_routes.py     # SWT pipeline & audit routes
│   │   ├── cit_routes.py     # CIT pipeline & audit routes
│   │   ├── multi_tax_routes.py # Integrated multi-tax analysis
│   │   ├── dashboard_*.py    # Analytics & dashboard endpoints
│   │   ├── risk_profiling.py # Risk scoring & profiling
│   │   ├── user_management.py# User administration
│   │   └── logs_routes.py   # Execution logs and file history
│   ├── models/               # SQLAlchemy ORM schemas
│   └── helpers/              # Data parsing & API response utilities
├── auth/                     # JWT Authentication middleware & helpers
├── config/                   # MySQL connection strings & initialization
├── gst/                      # GST ML pipeline, models (.pkl), and feature extractors
├── swt/                      # SWT ML pipeline, models (.pkl), and justification rules
├── cit/                      # CIT ML pipeline, models (.pkl), and preprocessing scripts
├── utils/                    # Shared helper functions & logging modules
├── requirements.txt          # Python dependencies
├── SETUP_CHECKLIST.md        # Step-by-step developer setup checklist
└── .env.example              # Environment variables template
```

---

## ⚙️ Environment Variables

Create a `.env` file in `backend/` based on `.env.example`:

```env
# MySQL Database
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=rba_tool_database

# JWT Configuration
JWT_SECRET_KEY=secure_random_key_32_characters_minimum

# Model & Data Paths
GST_MODEL_PATH=gst/models/xgboost_selected_model.pkl
SWT_MODEL_PATH=swt/models/xgboost_model.pkl
CIT_MODEL_PATH=cit/models/xgboost_fraud_model.pkl
```

---

## 🚀 Running the Backend

1. **Activate Virtual Environment**:
   ```powershell
   # Windows PowerShell
   .\venv\Scripts\Activate.ps1

   # Linux / macOS
   source venv/bin/activate
   ```

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Start the API Server**:
   ```bash
   python api/app.py
   ```

4. **Verify Health Endpoint**:
   ```bash
   curl http://localhost:5000/api/health
   ```
   *Expected Response:* `{"status": "ok", "message": "Tax Fraud Detection API is running"}`

---

## 🧪 Running Smoke Tests

Verify API stability and pipeline execution:

```bash
# Smoke test general API endpoints
python test_api_irc.py

# Smoke test multi-tax routes
python test_multitax.py
```

---

## 📋 Developer Checklist

Refer to [`SETUP_CHECKLIST.md`](file:///d:/jyotirmoy/Projects/py-projects/RBA-TOOL/backend/SETUP_CHECKLIST.md) for step-by-step onboarding, database setup notes, and expected execution times for large data pipelines.
