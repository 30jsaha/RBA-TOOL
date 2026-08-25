# ══════════════════════════════════════════════════════════════
#  api/app.py
#  Flask API entrypoint
#  Run: python api/app.py
#  All endpoints available at http://localhost:5000
# ══════════════════════════════════════════════════════════════

import os
import sys

from dotenv import load_dotenv

# Prevent Windows console UnicodeEncodeError (cp1252/charmap) from crashing requests.
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ── Allow imports from project root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(dotenv_path=os.path.join(BACKEND_ROOT, ".env"))

from flask import Flask, jsonify
from werkzeug.exceptions import RequestEntityTooLarge
from flask_cors import CORS
from utils.file_utils import get_backend_storage_dir, get_backend_upload_dir
from utils.file_security import validate_final_output_encryption_config
from utils.upload_security import get_max_upload_size_bytes
from utils.rbac import role_required

def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = get_max_upload_size_bytes()
# CORS (scoped to local React dev server).
# NOTE: Preflight (OPTIONS) is already allowlisted in auth middleware.
# CORS(
#     app,
#     resources={
#         r"/api/*": {
#             "origins": [
#                 "http://localhost:5173",
#                 "http://127.0.0.1:5173",
#             ]
#         }
#     },
#     supports_credentials=True,
#     allow_headers=["Authorization", "Content-Type"],
#     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
# )

CORS(
        app,
        resources={
            r"/api/*": {  # API routes
                "origins": [
                    "http://13.55.253.247",
                    "http://13.55.253.247:80",
                    "http://localhost:5173",
                    "http://127.0.0.1:5173"
                ],
                "supports_credentials": True,
                "allow_headers": ["Content-Type", "Authorization"],
                "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
            },
            r"/outputs/*": {  # ← ADD THIS for file downloads
                "origins": [
                    "http://13.55.253.247",
                    "http://13.55.253.247:80",
                    "http://localhost:5173",
                    "http://127.0.0.1:5173"
                ],
                "supports_credentials": True,
                "allow_headers": ["Content-Type", "Authorization"],
                "methods": ["GET", "OPTIONS"]  # Only GET and OPTIONS needed for downloads
            }
        }
    )
# SQLAlchemy session for dashboards (compatible with existing `db.session.execute(...)` usage)
from api.extensions import cache, db
db.init_app(app)
app.config.setdefault("CACHE_TYPE", "SimpleCache")
app.config.setdefault("CACHE_DEFAULT_TIMEOUT", 300)
app.config.setdefault("CACHE_THRESHOLD", 512)
cache.init_app(app)

# ── Auth (ported from old-backend) ──────────────────────────────
# Centralized middleware protects all `/api/*` routes except allowlisted.
from auth import init_auth
init_auth(app)
validate_final_output_encryption_config()


@app.errorhandler(RequestEntityTooLarge)
def handle_request_entity_too_large(_exc):
    return jsonify({'error': 'Uploaded file exceeds the configured size limit'}), 413

# ── Register route blueprints
from api.routes import gst_routes, cit_routes, swt_routes, segmentation as segmentation_routes
from api.routes.logs_routes        import logs_bp
from api.routes.multi_tax_routes   import multi_tax_bp
from api.routes.integration_routes import integration_bp  
from api.routes.dashboard_gst      import bp as gst_dashboard_bp, download_bp as gst_dashboard_download_bp
from api.routes.dashboard_swt      import bp as swt_dashboard_bp, download_bp as swt_dashboard_download_bp
from api.routes.dashboard_cit      import bp as cit_dashboard_bp, download_bp as cit_dashboard_download_bp, details_bp as cit_dashboard_details_bp
from api.routes.dashboard_common   import bp as common_dashboard_bp, download_bp as common_dashboard_download_bp
from api.routes.risk_assessment   import bp as risk_assessment_bp
from api.routes.risk_profiling     import bp as risk_profiling_bp
from api.routes.compliance_api     import bp as compliance_bp
from api.routes.predicted_records import bp as predicted_records_bp
from api.routes.taxpayer_report_risk_profiling import bp as taxpayer_report_risk_profiling_bp
from api.routes.upload_history import bp as upload_history_bp
from api.routes.admin import bp as admin_bp
from api.routes.user_management import bp as user_management_bp
from api.routes.role_management import bp as role_management_bp
from api.routes.conflicts_api import bp as conflicts_admin_bp

from api.routes.steps_routes    import steps_bp
from api.routes.validate_routes import validate_bp

shared_upload_dir = get_backend_upload_dir()
for route_module in (gst_routes, swt_routes, cit_routes):
    route_module.UPLOAD_FOLDER = shared_upload_dir

segmentation_routes.UPLOAD_FOLDER = shared_upload_dir
segmentation_routes.OUTPUT_FOLDER = get_backend_storage_dir("outputs")
segmentation_routes.SEGMENTED_FOLDER = get_backend_storage_dir("segmented")
 
app.register_blueprint(steps_bp)
app.register_blueprint(gst_routes.gst_bp)
app.register_blueprint(cit_routes.cit_bp)
app.register_blueprint(swt_routes.swt_bp)
app.register_blueprint(logs_bp)
app.register_blueprint(multi_tax_bp)
app.register_blueprint(integration_bp)
app.register_blueprint(validate_bp)         
# ── Auto-create all DB tables on startup
from config.db_init import init_db
init_db()

# Dashboards (ported from old-backend)
app.register_blueprint(gst_dashboard_bp)
app.register_blueprint(gst_dashboard_download_bp)
app.register_blueprint(swt_dashboard_bp)
app.register_blueprint(swt_dashboard_download_bp)
app.register_blueprint(cit_dashboard_bp)
app.register_blueprint(cit_dashboard_download_bp)
app.register_blueprint(cit_dashboard_details_bp)
app.register_blueprint(common_dashboard_bp)
app.register_blueprint(common_dashboard_download_bp)
app.register_blueprint(risk_assessment_bp)
app.register_blueprint(risk_profiling_bp)
app.register_blueprint(compliance_bp)
app.register_blueprint(predicted_records_bp)
app.register_blueprint(taxpayer_report_risk_profiling_bp)
app.register_blueprint(upload_history_bp)
app.register_blueprint(segmentation_routes.bp, url_prefix="/api/segmentation")
app.register_blueprint(user_management_bp)
app.register_blueprint(role_management_bp)
app.register_blueprint(conflicts_admin_bp)
app.register_blueprint(admin_bp, url_prefix="/api/admin")

# ── Health check
@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'message': 'Tax Fraud Detection API is running'}), 200


# ── List all routes (useful during dev)
@app.route('/api/routes', methods=['GET'])
@role_required(["ADMIN"])
def list_routes():
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append({
            'endpoint': rule.endpoint,
            'methods':  sorted(list(rule.methods - {'HEAD', 'OPTIONS'})),
            'url':      str(rule)
        })
    return jsonify(sorted(routes, key=lambda x: x['url'])), 200


if __name__ == '__main__':
    print("\n" + "="*60)
    print("  TAX FRAUD DETECTION API")
    print("="*60)
    print("  http://localhost:5000/api/health")
    print()
    print("  GST    POST /api/gst/run")
    print("          GET  /api/gst/status/<run_id>")
    print("          GET  /api/gst/results")
    print()
    print("  CIT    POST /api/cit/run")
    print("          GET  /api/cit/status/<run_id>")
    print("          GET  /api/cit/results")
    print()
    print("  SWT    POST /api/swt/run")
    print("          GET  /api/swt/status/<run_id>")
    print("          GET  /api/swt/results")
    print()
    print("  ALL    POST /api/integration/run")
    print("          GET  /api/integration/logs?tax_type=GST")
    print("="*60 + "\n")

    app.run(debug=_env_flag("FLASK_DEBUG") or _env_flag("DEBUG"), port=5000, threaded=True)


# ──────────────────────────────────────────────────────────────
#  That's it. All 8 new endpoints are now live:
#
#  Static step definitions (no auth, no DB):
#    GET  /api/gst/steps
#    GET  /api/cit/steps
#    GET  /api/swt/steps
#
#  Live per-step progress (reads pipeline_log table):
#    GET  /api/gst/progress/<run_id>
#    GET  /api/cit/progress/<run_id>
#    GET  /api/swt/progress/<run_id>
#
#  Pre-flight file validation (no pipeline run, instant response):
#    POST /api/gst/validate   (multipart/form-data, field: file)
#    POST /api/cit/validate   (multipart/form-data, field: file)
#    POST /api/swt/validate   (multipart/form-data, field: file)
# ──────────────────────────────────────────────────────────────



