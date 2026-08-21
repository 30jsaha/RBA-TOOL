# RBA-TOOL — Risk-Based Audit & Tax Fraud Detection System

**RBA-TOOL** is an enterprise Risk-Based Audit (RBA) engine and intelligent analytics web platform designed for tax compliance and audit selection (developed for Inland Revenue Commission - IRC Papua New Guinea). 

The platform leverages machine learning (XGBoost, statistical segmentation, and anomaly detection rules) alongside batch/real-time data pipelines to detect tax fraud, compute risk profiles, and generate actionable compliance reports across multiple tax types: **Goods & Services Tax (GST)**, **Salary & Wages Tax (SWT)**, and **Corporate Income Tax (CIT)**.

---

## 🏗️ Architecture & Project Structure

```
RBA-TOOL/
├── backend/                  # Python Flask REST API & ML Pipelines
│   ├── api/                  # Application factory, routes, controllers & models
│   │   ├── routes/           # REST endpoints (GST, SWT, CIT, Risk, Auth, Users, Logs, etc.)
│   │   ├── models/           # Database ORM models
│   │   └── helpers/          # Utility functions and formatters
│   ├── auth/                 # Authentication, JWT handling & middleware
│   ├── config/               # MySQL database and configuration settings
│   ├── gst/                  # GST ML fraud pipeline, models & standardizers
│   ├── swt/                  # SWT ML fraud pipeline, models & justification scripts
│   ├── cit/                  # CIT ML fraud pipeline & preprocessing scripts
│   ├── utils/                # Shared helper scripts and logging utilities
│   ├── requirements.txt      # Python dependencies
│   ├── SETUP_CHECKLIST.md    # Step-by-step developer onboarding checklist
│   ├── .env.example          # Environment variable template for backend
│   └── README.md             # Backend detailed documentation
│
├── frontend/                 # React Single Page Application (SPA)
│   ├── rbafront/             # Vite + React 19 Frontend application
│   │   ├── src/              # React components, pages, hooks & services
│   │   ├── public/           # Static assets
│   │   ├── package.json      # Dependencies and scripts
│   │   ├── vite.config.js    # Vite configuration
│   │   └── .env.example      # Environment variable template for frontend
│   └── README.md             # Frontend detailed documentation
│
├── .gitignore                # Root Git ignore configuration
└── README.md                 # Root project documentation
```

---

## 🛠️ Technology Stack

| Layer | Technologies Used |
|---|---|
| **Backend API** | Python 3.10+, Flask 3.1, SQLAlchemy 2.0, Flask-JWT-Extended, PyMySQL |
| **Machine Learning & Data** | XGBoost, Scikit-Learn, Pandas, PyArrow (Parquet), FastParquet, OpenPyXL, APScheduler |
| **Frontend Framework** | React 19, Vite 7, React Router DOM v7 |
| **UI Component Library** | Material UI (MUI v7), Lucide Icons, Emotion, SweetAlert2 |
| **Data Visualization** | ApexCharts, React-ApexCharts, D3.js, Leaflet |
| **Database** | MySQL Server 8.0+ |

---

## 🚀 Quick Start Guide

### Prerequisites
- **Python**: 3.10 or higher (`python --version`)
- **Node.js**: 18+ and npm 9+ (`node -v`, `npm -v`)
- **MySQL**: 8.0+ Server and MySQL Workbench / CLI

---

### 1. Backend Setup

1. **Navigate to backend directory**:
   ```bash
   cd backend
   ```

2. **Create and activate Python virtual environment**:
   - *Windows (PowerShell)*:
     ```powershell
     python -m venv venv
     .\venv\Scripts\Activate.ps1
     ```
   - *Linux / macOS*:
     ```bash
     python3 -m venv venv
     source venv/bin/activate
     ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Configuration**:
   Copy `.env.example` to `.env` and fill in your MySQL credentials:
   ```bash
   cp .env.example .env
   ```
   *Update `DB_USER`, `DB_PASSWORD`, `DB_NAME`, and `JWT_SECRET_KEY` in `.env`.*

5. **Database Initialization**:
   Ensure MySQL server is running, then create the database:
   ```sql
   CREATE DATABASE rba_tool_database;
   ```

6. **Start Backend Server**:
   ```bash
   python api/app.py
   ```
   The Flask API will run at `http://localhost:5000`. Verify health status at:
   `http://localhost:5000/api/health`

---

### 2. Frontend Setup

1. **Navigate to frontend project directory**:
   ```bash
   cd frontend/rbafront
   ```

2. **Install Node Dependencies**:
   ```bash
   npm install
   ```

3. **Environment Configuration**:
   Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
   Default API URL: `VITE_API_BASE_URL=http://localhost:5000/api`

4. **Start Development Server**:
   ```bash
   npm run dev
   ```
   Open your browser at `http://localhost:5173`.

---

## 📊 Core Features & Capabilities

- **Multi-Tax Fraud Pipelines**: Automated pipeline execution for GST, SWT, and CIT tax returns with fraud score calculation and justifications.
- **Risk Assessment & Profiling**: Taxpayer segmentation, anomaly detection, and risk scoring to optimize audit resource allocation.
- **Interactive Dashboards**: Comprehensive visualization of revenue risk, predicted high-risk entities, and multi-tax conflicts.
- **User & Role Management**: JWT-backed authentication with role-based access controls for auditors, administrators, and analysts.
- **Audit & History Logs**: Step-by-step logs tracking file uploads, pipeline execution status, and audit trails.

---

## 🧪 Testing & Smoke Check

To run backend test suites:

```bash
cd backend
# Smoke test core API routes
python test_api_irc.py

# Smoke test multi-tax integration
python test_multitax.py
```

Refer to [`backend/SETUP_CHECKLIST.md`](file:///d:/jyotirmoy/Projects/py-projects/RBA-TOOL/backend/SETUP_CHECKLIST.md) for a complete developer checklist.

---

## 📄 License & Confidentiality

Internal software system for tax audit and compliance management. All rights reserved.
