# RBA Tool — UAT Deployment & Developer Environment Guide

## 1. Purpose

This document describes the complete UAT deployment and access architecture for the **RBA Tool**, from VPN connectivity through the Windows Jump Host and Ubuntu VM, including:

- VPN access
- UAT CORP Jump Host access
- RBA Ubuntu VM access
- Ubuntu environment configuration
- Python backend environment
- Node.js / React frontend environment
- MySQL configuration
- Git-based deployment
- Nginx + Gunicorn architecture
- Frontend/API routing
- File-upload limits
- Developer debugging workflow
- Important commands and troubleshooting points

This document is intended to help developers understand the UAT environment before debugging or making code changes.

---

# 2. High-Level UAT Architecture

The current deployment path is:

```text
Developer Local PC
       |
       | FortiClient SSL-VPN
       v
UAT Corporate Network
       |
       v
Windows UAT Jump Host
       |
       | RDP
       v
Ubuntu RBA Tool VM
10.7.102.18
       |
       +-----------------------------+
       |                             |
       v                             v
     Nginx                        MySQL 8
      :80                         :3306
       |
       +-----------------------------+
       |
       | /api/*
       v
Gunicorn
127.0.0.1:5000
       |
       v
Flask Application
       |
       v
rba_tool_database
```

The browser does **not** directly communicate with Flask on port 5000 in the production deployment.

Instead:

```text
Browser
  |
  | HTTP :80
  v
Nginx
  |
  | /api/*
  v
Gunicorn :5000
  |
  v
Flask
```

This is important when debugging API problems.

---

# 3. Network Access Flow

## 3.1 Developer Local PC

The developer's local Windows machine is outside the UAT network.

The developer first establishes a VPN connection using **FortiClient VPN**.

Example VPN configuration:

```text
VPN Type: SSL-VPN
VPN Name: IRC_UAT_Env
Remote Gateway: <provided by infrastructure>
Custom Port: <provided by infrastructure>
```

Credentials must be obtained from the organization's infrastructure/security team.

Do not store production/UAT passwords in this document.

---

# 4. VPN Connection

## 4.1 FortiClient

Open FortiClient and select the configured UAT VPN profile.

Typical flow:

```text
FortiClient
   |
   +-- VPN Name: IRC_UAT_Env
   |
   +-- Username
   +-- Password
   |
   v
Connect
```

A successful VPN connection provides access to the UAT corporate network.

### Important

If FortiClient reports:

```text
Unable to establish the VPN connection.
The VPN server may be unreachable.
```

check:

1. Internet connectivity on the local PC.
2. VPN gateway hostname/IP.
3. SSL-VPN port.
4. VPN profile name.
5. VPN username/password.
6. Whether the VPN account is active.
7. Whether the VPN server is reachable from the current network.
8. Whether the organization requires MFA.
9. Whether another VPN connection is already active.

Do not change VPN settings without the network/security team's configuration.

---

# 5. UAT Jump Host

After VPN connectivity is established, connect to the UAT CORP Jump Host using Windows Remote Desktop.

Example:

```text
Hostname/IP:
demo.uat.pgv.dd.com
```

Use the supplied **Domain Credentials**.

The Jump Host is used as the controlled entry point into the UAT environment.

---

# 6. RBA Ubuntu VM

From the Jump Host, open Remote Desktop Connection and connect to:

```text
10.7.102.18
```

Use the RBA Tool VM credentials.

The Ubuntu VM is accessed through XRDP.

The VM has:

```text
OS: Ubuntu 24.04.4 LTS
Architecture: x86_64 / amd64
```

---

# 7. Network Characteristics

The Jump Host itself does not necessarily have general Internet access.

The Ubuntu RBA VM, however, has Internet access.

This was verified using an HTTP request from the Ubuntu VM.

Therefore:

```text
Developer PC
   |
   | VPN
   v
Jump Host
   |
   | RDP
   v
Ubuntu VM
   |
   +-- Internet access
   |
   +-- UAT internal access
```

This distinction is important.

Do not assume that because the Jump Host cannot access the Internet, the Ubuntu VM also cannot.

---

# 8. Ubuntu VM Baseline Environment

Current operating system:

```text
Ubuntu 24.04.4 LTS
Ubuntu Codename: noble
Architecture: amd64
```

Disk configuration observed:

```text
Root filesystem:
~98 GB total
~82 GB available
```

The VM has sufficient space for the current application and data workload, but disk usage should be monitored because the application handles large tax datasets and generated files.

---

# 9. Installed System Components

The Ubuntu VM currently contains:

```text
Python:      3.12.10
Node.js:    22.14.0
npm:        10.9.2
MySQL:       8.0.46
Nginx:       1.24.0
Git:         2.43.0
curl:        8.5.0
GCC:         13.3.0
Make:        4.3
```

Nginx is enabled and running.

MySQL is enabled.

Git is installed.

---

# 10. Project Location

The application is deployed under:

```text
/var/www/rba-tool
```

Project structure:

```text
/var/www/rba-tool
├── backend
├── frontend
├── .git
├── .gitignore
├── README.md
└── rba_tool_database_*.zip
```

Backend:

```text
/var/www/rba-tool/backend
```

Frontend:

```text
/var/www/rba-tool/frontend
```

---

# 11. Git Deployment

The project is stored in a Git repository.

The UAT VM was cloned from the public repository after the project's `.gitignore` was configured correctly.

Current repository state was verified using:

```bash
cd /var/www/rba-tool

git status
git branch --show-current
```

Expected state:

```text
On branch master
Your branch is up to date with 'origin/master'.

nothing to commit, working tree clean
```

The deployment approach is therefore:

```text
Developer
   |
   v
Git repository
   |
   v
Ubuntu VM
   |
   v
/var/www/rba-tool
```

Large dependency directories such as:

```text
backend/venv
frontend/rbafront/node_modules
frontend/rbafront/dist
```

should not normally be committed to Git.

They are generated on the target machine.

---

# 12. Backend Structure

Current backend structure includes:

```text
backend/
├── api/
│   ├── app.py
│   ├── extensions.py
│   └── __init__.py
│
├── auth/
│   ├── auth_db.py
│   ├── auth_init.py
│   ├── auth_middleware.py
│   ├── auth_routes.py
│   └── __init__.py
│
├── cit/
│   ├── cit_fraud_pipeline.py
│   ├── cit_fraud_pipeline_with_timer.py
│   ├── cit_upload_hook.py
│   └── ...
│
├── gst/
│   ├── gst_fraud_detector.py
│   ├── gst_fraud_predictor.py
│   ├── gst_validator.py
│   ├── gst_upload_hook.py
│   └── ...
│
├── swt/
│   ├── 1_swt_preparation.py
│   ├── 2_swt_validation.py
│   ├── 3_swt_feature_engineering.py
│   ├── 4_swt_fraud_prediction.py
│   ├── 5_swt_justification.py
│   ├── swt_upload_hook.py
│   └── ...
│
├── config/
│   ├── db_config.py
│   └── db_init.py
│
├── utils/
│   ├── auth_helper.py
│   ├── bulk_insert_utils.py
│   ├── extensions.py
│   ├── file_utils.py
│   ├── pipeline_logger.py
│   ├── rbac.py
│   └── upload_logger.py
│
├── requirements.txt
├── .env
└── README.md
```

---

# 13. Python Virtual Environment

The backend uses a dedicated Python virtual environment:

```text
/var/www/rba-tool/backend/venv
```

Activate it:

```bash
cd /var/www/rba-tool/backend
source venv/bin/activate
```

The shell prompt should show:

```text
(venv)
```

Verify:

```bash
python --version
which python
```

Expected:

```text
Python 3.12.10
/var/www/rba-tool/backend/venv/bin/python
```

---

# 14. Backend Python Dependencies

Dependencies are installed from:

```text
backend/requirements.txt
```

After installation, verify:

```bash
pip check
```

Expected:

```text
No broken requirements found.
```

Known working package examples:

```text
Flask:      3.1.3
SQLAlchemy: 2.0.49
PyMySQL:    installed and working
```

A database connection was successfully verified using the SQLAlchemy engine.

---

# 15. Backend Environment Variables

Backend configuration is stored in:

```text
/var/www/rba-tool/backend/.env
```

The environment contains database settings such as:

```env
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=rba_app
DB_PASSWORD=<secret>
DB_NAME=rba_tool_database
```

JWT configuration:

```env
JWT_SECRET_KEY=<secret>
```

CIT configuration includes model/data paths.

GST configuration includes model/data paths.

SWT configuration includes model/data paths.

Pipeline/storage configuration includes:

```env
UPLOAD_LOG_PATH=upload_history.log
TEMP_OUTPUT_DIR=temp_outputs
FINAL_OUTPUT_DIR=final_output
```

### Security

Never commit the real `.env` file.

Only `.env.example` should be tracked.

Secrets should be provided securely through the deployment process.

---

# 16. MySQL

MySQL 8 is installed and enabled.

Check:

```bash
mysql --version
```

Expected version family:

```text
MySQL 8.0.46
```

Check service:

```bash
sudo systemctl status mysql
```

Check whether it starts automatically:

```bash
sudo systemctl is-enabled mysql
```

Expected:

```text
enabled
```

---

# 17. Application Database

Database:

```text
rba_tool_database
```

Application MySQL user:

```text
rba_app
```

The application connects through:

```text
127.0.0.1:3306
```

This means MySQL is local to the Ubuntu VM.

The application should not require external access to MySQL port 3306.

---

# 18. Database Initialization

The backend contains:

```text
config/db_config.py
config/db_init.py
```

Database connectivity can be tested with:

```bash
cd /var/www/rba-tool/backend
source venv/bin/activate

python -c "
from config.db_config import get_mysql_engine
engine = get_mysql_engine()
with engine.connect() as conn:
    print('Database connection: SUCCESS')
engine.dispose()
"
```

Database initialization:

```bash
python -c "
from config.db_init import init_db
init_db()
"
```

The initialization process creates/checks application tables.

Examples include:

```text
upload_log
pipeline_log
gst_fraud_justification
upload_differences
cit_fraud_justification
swt_fraud_justification
agg_cit
agg_gst
agg_swt
multi_tax_integration_results
permissions
role_permissions
```

The database may also contain additional tables imported from the application's database dump.

---

# 19. Database Import

A database dump can be transferred to:

```text
/var/www/rba-tool
```

If compressed as ZIP:

```bash
unzip database.zip
```

If `unzip` is not installed:

```bash
sudo apt update
sudo apt install unzip
```

Before importing a replacement database, existing application tables may need to be removed according to the approved deployment/database-refresh procedure.

Then MySQL can be opened:

```bash
mysql -u rba_app -p rba_tool_database
```

A SQL dump can be imported with:

```sql
source /path/to/database.sql;
```

Always take an approved backup before destructive database operations.

---

# 20. Nginx

Nginx is the public HTTP entry point for the application.

Check:

```bash
sudo systemctl status nginx
```

Configuration location:

```text
/etc/nginx/sites-available/rba-tool
```

Enabled site:

```text
/etc/nginx/sites-enabled/rba-tool
```

The default Nginx site was disabled.

---

# 21. Nginx Production Architecture

The production Nginx configuration serves the React build:

```text
/var/www/rba-tool/frontend/dist
```

and proxies API requests to:

```text
127.0.0.1:5000
```

Conceptually:

```nginx
server {
    listen 80;

    root /var/www/rba-tool/frontend/rbafront/dist;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:5000;
    }
}
```

The actual configuration also contains proxy headers and timeout settings.

---

# 22. Large File Uploads

The RBA Tool processes large GST/CIT/SWT files.

During UAT testing, a request of approximately:

```text
19.2 MB
```

was rejected by Nginx with:

```text
413 Request Entity Too Large
```

The response came from:

```text
nginx/1.24.0
```

Therefore the request was rejected before reaching Flask.

The Nginx configuration should include an appropriate upload limit, for example:

```nginx
client_max_body_size 500M;
```

After modifying Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Verify:

```bash
sudo nginx -T | grep client_max_body_size
```

Do not blindly use very large limits in production. The limit should reflect the application's approved maximum upload size.

---

# 23. Frontend Environment

Frontend location:

```text
/var/www/rba-tool/frontend/rbafront
```

Node.js:

```text
22.14.0
```

npm:

```text
10.9.2
```

Verify:

```bash
node -v
npm -v
```

---

# 24. Frontend Dependencies

The frontend contains:

```text
package.json
package-lock.json
```

Use:

```bash
npm ci
```

rather than `npm install` for reproducible deployment when `package-lock.json` is available.

The project currently installs hundreds of packages.

Warnings about deprecated packages were observed during installation.

These warnings do not necessarily prevent deployment, but dependency/security remediation should be handled separately from the UAT deployment.

Avoid using:

```bash
npm audit fix --force
```

during a deployment unless dependency changes have been reviewed and tested.

---

# 25. Frontend Production Build

Production environment:

```text
.env.production
```

The frontend is configured to use the relative API path:

```env
VITE_API_BASE_URL=/api
```

This is preferable to:

```env
VITE_API_BASE_URL=http://127.0.0.1:5000/api
```

for the deployed browser application.

Reason:

```text
Browser
   |
   | /api
   v
Nginx
   |
   v
127.0.0.1:5000
```

If the frontend used `127.0.0.1:5000`, the browser would interpret `127.0.0.1` as the client machine rather than the Ubuntu VM.

Build:

```bash
cd /var/www/rba-tool/frontend/rbafront
npm run build
```

Generated output:

```text
frontend/rbafront/dist/
```

Nginx serves this directory.

---

# 26. Production Backend

The Flask application should not be exposed directly through the Flask development server.

The Flask development server displays:

```text
WARNING: This is a development server.
Do not use it in a production deployment.
Use a production WSGI server instead.
```

Production architecture should therefore be:

```text
Nginx
   |
   v
Gunicorn
   |
   v
Flask
```

The backend systemd service is referred to in this environment as:

```text
rba-backend.service
```

Check:

```bash
sudo systemctl status rba-backend
```

Check:

```bash
sudo systemctl is-active rba-backend
```

Expected:

```text
active
```

---

# 27. Backend Port

Gunicorn listens internally on:

```text
127.0.0.1:5000
```

Nginx listens publicly on:

```text
0.0.0.0:80
```

Therefore:

```text
Browser
   |
   | :80
   v
Nginx
   |
   | :5000 internally
   v
Gunicorn
```

Port 5000 does not need to be exposed to the UAT network.

Check listening ports:

```bash
sudo ss -tulpn
```

Expected important ports:

```text
22       SSH
80       Nginx
3389     XRDP
5000     Gunicorn on localhost
3306     MySQL, normally local
```

---

# 28. RBA API Endpoints

The backend exposes endpoints including:

```text
GET  /api/health

GST:
POST /api/gst/run
GET  /api/gst/status/<run_id>
GET  /api/gst/results

CIT:
POST /api/cit/run
GET  /api/cit/status/<run_id>
GET  /api/cit/results

SWT:
POST /api/swt/run
GET  /api/swt/status/<run_id>
GET  /api/swt/results

ALL:
POST /api/integration/run
GET  /api/integration/logs?tax_type=GST
```

Administrative endpoints include functionality such as database reset.

---

# 29. Browser Access

Current UAT application URL:

```text
http://10.7.102.18/
```

The application was successfully accessed from the Jump Host.

Login was successfully completed.

Therefore the following chain has been confirmed:

```text
Jump Host Browser
      |
      v
10.7.102.18:80
      |
      v
Nginx
      |
      v
React
      |
      v
/api
      |
      v
Gunicorn
      |
      v
Flask
      |
      v
MySQL
```

---

# 30. Optional Friendly Hostname

For a temporary single-Jump-Host solution, Windows hosts file mapping can be used.

On the Jump Host:

```text
C:\Windows\System32\drivers\etc\hosts
```

Example:

```text
10.7.102.18    rba-tool-uat
```

Then:

```text
http://rba-tool-uat/
```

For multiple users, an internal DNS record should be created by the infrastructure team instead.

---

# 31. Developer Debugging Model

When debugging an application error, first determine which layer is failing.

```text
Layer 1 — Browser
        |
Layer 2 — Nginx
        |
Layer 3 — Gunicorn
        |
Layer 4 — Flask
        |
Layer 5 — SQLAlchemy
        |
Layer 6 — MySQL
        |
Layer 7 — ML/Data/Pipeline code
```

Do not immediately modify application code if the failure is occurring at Nginx.

---

# 32. Browser Developer Tools

Use Edge/Chrome Developer Tools.

Open:

```text
F12
```

Then:

```text
Network
```

For an API failure, inspect:

```text
Request URL
Request Method
Status Code
Request Headers
Payload
Response
```

Examples:

```text
200   Success
400   Application/request validation problem
401   Authentication problem
403   Authorization problem
404   Route not found
413   Request too large
500   Backend/application error
502   Nginx cannot communicate with backend
504   Backend timeout
```

---

# 33. Diagnosing HTTP 413

Example:

```text
POST /api/gst/validate
413 Request Entity Too Large
Server: nginx/1.24.0
```

Interpretation:

```text
Browser
   |
   | large multipart request
   v
Nginx
   |
   X 413
   |
   Flask is never reached
```

Check:

```bash
sudo nginx -T | grep client_max_body_size
```

Then inspect Nginx logs:

```bash
sudo tail -n 100 /var/log/nginx/error.log
```

---

# 34. Diagnosing HTTP 502

If the browser reports:

```text
502 Bad Gateway
```

check:

```bash
sudo systemctl status rba-backend
```

Then:

```bash
sudo ss -ltnp | grep 5000
```

Then:

```bash
sudo journalctl -u rba-backend -n 100 --no-pager
```

A 502 commonly means Nginx cannot successfully communicate with Gunicorn.

---

# 35. Diagnosing HTTP 504

If the application returns:

```text
504 Gateway Timeout
```

check:

```bash
sudo journalctl -u rba-backend -n 100 --no-pager
```

and:

```bash
sudo tail -n 100 /var/log/nginx/error.log
```

The application may be processing a large tax file or a long-running ML pipeline.

Check the Gunicorn/Nginx timeout configuration before changing application code.

---

# 36. Diagnosing HTTP 500

For a 500 error, first inspect the backend service:

```bash
sudo journalctl -u rba-backend -n 100 --no-pager
```

For recent failures:

```bash
sudo journalctl -u rba-backend --since "15 minutes ago" --no-pager
```

Then inspect Nginx:

```bash
sudo tail -n 100 /var/log/nginx/error.log
```

Important:

The browser's generic:

```text
500 Internal Server Error
```

is usually not enough to identify the root cause.

Find the **first exception** in the backend log.

---

# 37. SQLAlchemy Transaction Errors

An example error encountered in UAT was:

```text
Can't reconnect until invalid transaction is rolled back.
Please rollback() fully before proceeding.
```

This generally indicates that a SQLAlchemy transaction/session has entered a failed state and another database operation is being attempted without first rolling back the failed transaction.

When debugging this type of error, do not focus only on the final message.

Look for the **original database exception immediately before it**.

Useful commands:

```bash
sudo journalctl -u rba-backend -n 200 --no-pager
```

and:

```bash
sudo journalctl -u rba-backend --since "15 minutes ago" --no-pager
```

The original MySQL/SQLAlchemy exception is usually the more useful diagnostic.

---

# 38. Reset DB Debugging

The Reset DB feature previously returned:

```text
500 Internal Server Error
```

with:

```text
Can't reconnect until invalid transaction is rolled back.
```

The browser request was:

```text
POST /api/admin/reset-db
```

Because the response was application JSON rather than an Nginx-generated 413/502/504 page, the request was reaching the backend.

Recommended debugging sequence:

```bash
sudo journalctl -u rba-backend --since "15 minutes ago" --no-pager
```

Find the first database exception.

Then inspect the Reset DB implementation and its SQLAlchemy session/transaction handling.

Do not drop or re-import the database just to troubleshoot this error.

---

# 39. Database Debugging

Check MySQL:

```bash
sudo systemctl status mysql
```

Check login:

```bash
mysql -u rba_app -p
```

Check databases:

```sql
SHOW DATABASES;
```

Select:

```sql
USE rba_tool_database;
```

Check tables:

```sql
SHOW TABLES;
```

Inspect a table:

```sql
DESCRIBE table_name;
```

---

# 40. Backend Manual Debugging

For development-only debugging, activate the environment:

```bash
cd /var/www/rba-tool/backend
source venv/bin/activate
```

Then run targeted Python commands.

Example:

```bash
python -c "
from config.db_config import get_mysql_engine
engine = get_mysql_engine()
with engine.connect() as conn:
    print('Database connection: SUCCESS')
engine.dispose()
"
```

Do not run a second copy of the production backend on port 5000 while the systemd Gunicorn service is already using that port.

---

# 41. Service Restart Commands

Backend:

```bash
sudo systemctl restart rba-backend
```

Check:

```bash
sudo systemctl status rba-backend
```

Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

MySQL:

```bash
sudo systemctl restart mysql
```

Use MySQL restarts only when actually required.

---

# 42. Deployment After a Git Update

Typical workflow:

```bash
cd /var/www/rba-tool

git status
git pull origin master
```

Backend changes:

```bash
cd backend
source venv/bin/activate
pip install -r requirements.txt
pip check
```

If backend code changed:

```bash
sudo systemctl restart rba-backend
```

Frontend changes:

```bash
cd /var/www/rba-tool/frontend/rbafront

npm ci
npm run build
```

Then Nginx automatically serves the newly generated `dist` files.

Usually:

```bash
sudo systemctl reload nginx
```

is sufficient if Nginx configuration itself did not change.

---

# 43. Recommended Deployment Sequence

For a normal code deployment:

```text
1. Verify VPN
       ↓
2. Connect to Jump Host
       ↓
3. RDP to Ubuntu VM
       ↓
4. Check disk/service health
       ↓
5. git status
       ↓
6. git pull
       ↓
7. Update backend dependencies if requirements changed
       ↓
8. pip check
       ↓
9. Update frontend dependencies if package-lock changed
       ↓
10. npm ci
       ↓
11. npm run build
       ↓
12. Restart backend if backend code changed
       ↓
13. nginx -t
       ↓
14. Reload Nginx if config changed
       ↓
15. Verify services
       ↓
16. Browser smoke test
       ↓
17. Inspect Network tab
       ↓
18. Review backend logs
```

---

# 44. Pre-Deployment Health Checklist

Run:

```bash
hostname
uname -m
python --version
node -v
npm -v
mysql --version
nginx -v
git --version
```

Services:

```bash
sudo systemctl is-active mysql
sudo systemctl is-active nginx
sudo systemctl is-active rba-backend
```

Ports:

```bash
sudo ss -tulpn
```

Disk:

```bash
df -h
```

Git:

```bash
cd /var/www/rba-tool
git status
git branch --show-current
```

Backend:

```bash
cd /var/www/rba-tool/backend
source venv/bin/activate
pip check
```

Frontend:

```bash
cd /var/www/rba-tool/frontend/rbafront
ls -lah dist
```

Nginx:

```bash
sudo nginx -t
```

---

# 45. Important Environment Difference: Local vs UAT

Developers should understand that local development and UAT are different environments.

## Local

Typical:

```text
Windows
Python 3.12.10
Node.js 22.14.0
MySQL local/developer database
Vite development server
```

The local frontend may use:

```env
VITE_API_BASE_URL=http://127.0.0.1:5000/api
```

## UAT

```text
Ubuntu 24.04.4
Python 3.12.10
Node.js 22.14.0
MySQL 8
Nginx
Gunicorn
React production build
```

The UAT frontend uses:

```env
VITE_API_BASE_URL=/api
```

because Nginx handles API proxying.

---

# 46. Do Not Copy Virtual Environments

Never copy:

```text
Windows venv
```

to:

```text
Ubuntu venv
```

and vice versa.

Python virtual environments contain OS/platform-specific binaries.

Create them independently:

```text
Windows:
py -3.12 -m venv venv

Ubuntu:
python3.12 -m venv venv
```

Then install dependencies from:

```text
requirements.txt
```

---

# 47. Do Not Copy node_modules Between Operating Systems

Similarly, do not copy:

```text
node_modules
```

between machines/operating systems.

Use:

```bash
npm ci
```

from:

```text
package-lock.json
```

on the target environment.

---

# 48. File Transfer Strategy

Because the Jump Host has restricted Internet connectivity, large project transfers should not depend on downloading directly from the Jump Host.

The established workflow is:

```text
Developer Local PC
       |
       | Copy files
       v
Windows Jump Host
       |
       | RDP / file transfer / approved transfer mechanism
       v
Ubuntu VM
```

For source code, Git is preferred because the Ubuntu VM has Internet access:

```text
Git repository
       |
       v
Ubuntu VM
```

For sensitive UAT files, database dumps, or files excluded by `.gitignore`, use the organization's approved file-transfer mechanism.

---

# 49. Security Rules

Do not commit:

```text
.env
passwords
JWT secrets
database credentials
VPN credentials
private certificates
private keys
```

Do not place real credentials in:

```text
README.md
deployment documentation
Git commits
screenshots
browser URLs
source code
```

Use placeholders:

```text
<USERNAME>
<PASSWORD>
<DB_PASSWORD>
<JWT_SECRET>
<VPN_GATEWAY>
```

The credentials used for UAT access should be treated as confidential even when they are only intended for testing.

---

# 50. Final Environment Diagram

```text
                         INTERNET
                            |
                            |
                    Developer PC
                            |
                            | FortiClient SSL-VPN
                            v
                 +----------------------+
                 | UAT Corporate Network|
                 +----------------------+
                            |
                            v
                 +----------------------+
                 | Windows Jump Host    |
                 | RDP Entry Point      |
                 +----------------------+
                            |
                            | RDP / XRDP
                            v
       +------------------------------------------------+
       | Ubuntu 24.04.4 UAT VM                          |
       | 10.7.102.18                                    |
       |                                                |
       |  +----------------------+                      |
       |  | Nginx :80            |                      |
       |  +----------+-----------+                      |
       |             |                                  |
       |       +-----+------+                           |
       |       |            |                           |
       |       v            v                           |
       |   React dist/   /api/*                         |
       |                    |                           |
       |                    v                           |
       |              Gunicorn :5000                   |
       |                    |                           |
       |                    v                           |
       |                  Flask                         |
       |                    |                           |
       |             +------+-------+                   |
       |             |              |                   |
       |             v              v                   |
       |         SQLAlchemy      ML Pipelines           |
       |             |              |                   |
       |             v              v                   |
       |         MySQL 8       GST/CIT/SWT             |
       |         :3306         Models/Data             |
       |                                                |
       +------------------------------------------------+
```

---

# 51. Developer Troubleshooting Decision Tree

When an API fails:

```text
Browser error
     |
     v
Check Network tab
     |
     +-- 413?
     |      |
     |      +--> Nginx upload size
     |
     +-- 502?
     |      |
     |      +--> Gunicorn/backend service
     |
     +-- 504?
     |      |
     |      +--> Timeout / long-running processing
     |
     +-- 404?
     |      |
     |      +--> Route / Nginx / Flask endpoint
     |
     +-- 401/403?
     |      |
     |      +--> Authentication/RBAC
     |
     +-- 500?
            |
            +--> Backend logs
                   |
                   +--> First exception
                          |
                          +--> SQLAlchemy?
                          +--> MySQL?
                          +--> Python?
                          +--> ML/data?
```

This should be the default debugging methodology.

---

# 52. Current UAT Deployment Status

At the time this document was prepared:

```text
VPN access                         Configured
Jump Host access                  Configured
Ubuntu VM access                  Configured
Ubuntu 24.04.4                    Confirmed
Python 3.12.10                   Confirmed
Node.js 22.14.0                  Confirmed
npm 10.9.2                       Confirmed
MySQL 8.0.46                     Confirmed
Nginx 1.24.0                     Confirmed
Git                              Confirmed
Backend virtual environment      Confirmed
Backend dependencies             Confirmed
Database connection              Confirmed
Database imported                Confirmed
React production build           Confirmed
Gunicorn backend                 Configured
Nginx reverse proxy              Configured
Frontend browser access          Confirmed
Login                             Confirmed
Large file upload                Requires appropriate Nginx limit
Reset DB                         Requires application-level debugging
```

---

# 53. Most Important Commands

## Services

```bash
sudo systemctl status nginx
sudo systemctl status rba-backend
sudo systemctl status mysql
```

## Logs

```bash
sudo journalctl -u rba-backend -n 100 --no-pager
sudo journalctl -u rba-backend --since "15 minutes ago" --no-pager
sudo tail -n 100 /var/log/nginx/error.log
```

## Nginx

```bash
sudo nginx -t
sudo nginx -T
sudo systemctl reload nginx
```

## Ports

```bash
sudo ss -tulpn
```

## Backend

```bash
cd /var/www/rba-tool/backend
source venv/bin/activate
python --version
pip check
```

## Frontend

```bash
cd /var/www/rba-tool/frontend/rbafront
node -v
npm -v
npm ci
npm run build
```

## Git

```bash
cd /var/www/rba-tool
git status
git pull origin master
```

## Disk

```bash
df -h
```

---

# 54. Operational Principle

For this environment, developers should follow this rule:

> **First identify which layer failed; then debug that layer.**

Do not immediately modify application code for an error generated by:

- VPN
- RDP
- DNS
- Nginx
- upload limits
- Gunicorn
- MySQL connectivity

Likewise, do not modify Nginx when the request has already reached Flask and the error is a Python/SQLAlchemy exception.

The complete request path is:

```text
User Browser
    ↓
Network / VPN
    ↓
Jump Host
    ↓
Ubuntu VM
    ↓
Nginx
    ↓
Gunicorn
    ↓
Flask
    ↓
Application Modules
    ↓
SQLAlchemy
    ↓
MySQL
    ↓
ML / Tax Processing / Files
```

Understanding this path should be the starting point for debugging every UAT issue.
