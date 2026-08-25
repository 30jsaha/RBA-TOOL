# RBA-TOOL Frontend — React UI & Dashboard

This directory contains the user interface for **RBA-TOOL (Risk-Based Audit & Tax Fraud Detection System)**.

Built with **React 19**, **Vite 7**, and **Material UI (MUI v7)**, it provides an interactive web dashboard for tax auditors and risk analysts to inspect fraud scores, analyze multi-tax anomalies, upload tax return files, and manage risk compliance workflows.

---

## 🛠️ Key Libraries & Frameworks

- **UI Components**: Material UI (`@mui/material`), `@mui/x-data-grid`, Lucide Icons (`lucide-react`), SweetAlert2
- **Data Visualization**: ApexCharts (`apexcharts`, `react-apexcharts`), D3.js, Leaflet maps
- **Form Handling**: React Hook Form, Zod validation schema
- **State & HTTP**: Axios, React Router DOM v7
- **Build System**: Vite 7, Babel Fast Refresh plugin

---

## 🚀 Getting Started

### 1. Install Dependencies
```bash
npm install
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Ensure `VITE_API_BASE_URL` points to your backend Flask API (default: `http://localhost:5000/api`).

### 3. Development Server
Run Vite dev server with hot module replacement (HMR):
```bash
npm run dev
```
Open `http://localhost:5173` in your browser.

### 4. Build for Production
```bash
npm run build
```
The production bundle will be generated in `dist/`.

---

## 📜 Available NPM Scripts

- `npm run dev`: Starts the local development server on port 5173.
- `npm run build`: Bundles assets for production deployment into `dist/`.
- `npm run preview`: Locally previews the production build.
- `npm run lint`: Runs ESLint across project files.
