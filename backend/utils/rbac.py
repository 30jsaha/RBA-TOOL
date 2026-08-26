from functools import wraps

from flask import g, jsonify
from flask_jwt_extended import get_jwt_identity
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from api.extensions import db


PATH_PERMISSION_RULES = [
    ("/api/admin/conflicts/history", ("settings.conflicts.history", "settings.conflicts.audit_logs")),
    ("/api/admin/conflicts/list", ("settings.conflicts.list",)),
    ("/api/admin/conflicts/", ("settings.conflicts.list",)),
    ("/api/admin/reset-db", ("settings.reset_db",)),
    ("/api/admin/cleanup-temp-files", ("settings.reset_db",)),
    ("/api/users", ("settings.users",)),
    ("/api/invalid-tins", ("settings.invalid_tins",)),
    ("/api/tin/sync-missing", ("upload_tin_registration",)),
    ("/api/upload-tin-reg", ("upload_tin_registration",)),
    ("/api/predicted-records/recent-uploads", ("reports.recent_uploads",)),
    ("/api/predicted-records/all-tax-records", ("reports.taxpayer_profile",)),
    ("/api/predicted-records/taxpayer-history", ("reports.taxpayer_profile",)),
    ("/api/predicted-records/fraud-reasons", ("reports.taxpayer_profile",)),
    ("/api/taxpayer_report_risk_profiling", ("reports.risk_profiling",)),
    ("/api/upload-history/recent-uploads/download-csv", ("reports.recent_uploads",)),
    ("/api/upload-history", ("upload_history",)),
    ("/api/risk-assessment", ("analytics.risk_assessment",)),
    ("/api/risk-profiling", ("reports.risk_profiling",)),
    ("/api/compliance", ("analytics.compliance",)),
    ("/api/common/download-csv", ("dashboard.dashboard",)),
    ("/api/common-dashboard", ("dashboard.dashboard",)),
    ("/api/gst/download-csv", ("dashboard.gst",)),
    ("/api/dashboard", ("dashboard.gst",)),
    ("/api/swt/download-csv", ("dashboard.swt",)),
    ("/api/swt/dashboard", ("dashboard.swt",)),
    ("/api/cit/download-csv", ("dashboard.cit",)),
    ("/api/cit/dashboard", ("dashboard.cit",)),
    ("/api/segmentation", ("upload_sheets",)),
    ("/api/multitax", ("upload_sheets",)),
    ("/api/gst/validate", ("upload_sheets",)),
    ("/api/gst/run", ("upload_sheets",)),
    ("/api/gst/status/", ("upload_sheets",)),
    ("/api/gst/progress/", ("upload_sheets",)),
    ("/api/gst/summary", ("upload_sheets",)),
    ("/api/gst/results", ("upload_sheets",)),
    ("/api/gst/download/", ("upload_sheets",)),
    ("/api/swt/validate", ("upload_sheets",)),
    ("/api/swt/run", ("upload_sheets",)),
    ("/api/swt/status/", ("upload_sheets",)),
    ("/api/swt/progress/", ("upload_sheets",)),
    ("/api/swt/summary", ("upload_sheets",)),
    ("/api/swt/results", ("upload_sheets",)),
    ("/api/swt/download/", ("upload_sheets",)),
    ("/api/cit/validate", ("upload_sheets",)),
    ("/api/cit/run", ("upload_sheets",)),
    ("/api/cit/status/", ("upload_sheets",)),
    ("/api/cit/progress/", ("upload_sheets",)),
    ("/api/cit/summary", ("upload_sheets",)),
    ("/api/cit/results", ("upload_sheets",)),
    ("/api/cit/download/", ("upload_sheets",)),
    ("/api/cit/sales-cogs-details", ("dashboard.cit",)),
]


def _permission_denied_response():
    return jsonify({"success": False, "message": "Permission denied"}), 403


def get_request_permissions(path: str):
    normalized_path = (path or "").rstrip("/") or "/"
    for prefix, permission_codes in PATH_PERMISSION_RULES:
        normalized_prefix = prefix.rstrip("/") or "/"
        if normalized_path == normalized_prefix or normalized_path.startswith(normalized_prefix + "/"):
            return permission_codes
    return ()


def get_current_security_context():
    cached = getattr(g, "_rbac_security_context", None)
    if cached is not None:
        return cached

    try:
        raw_user_id = get_jwt_identity()
        user_id = int(raw_user_id) if raw_user_id is not None else None
    except Exception:
        user_id = None

    if not user_id:
        context = {
            "user": None,
            "roles": [],
            "permissions": set(),
            "is_active": False,
        }
        g._rbac_security_context = context
        return context

    try:
        user_row = db.session.execute(
            text(
                """
                SELECT id, email, full_name, is_active
                FROM users
                WHERE id = :user_id
                LIMIT 1
                """
            ),
            {"user_id": user_id},
        ).mappings().first()

        if not user_row:
            context = {
                "user": None,
                "roles": [],
                "permissions": set(),
                "is_active": False,
            }
            g._rbac_security_context = context
            return context

        role_rows = db.session.execute(
            text(
                """
                SELECT DISTINCT r.id, r.name
                FROM roles r
                JOIN user_roles ur ON ur.role_id = r.id
                WHERE ur.user_id = :user_id
                ORDER BY r.name
                """
            ),
            {"user_id": user_id},
        ).mappings().all()

        permission_rows = db.session.execute(
            text(
                """
                SELECT DISTINCT p.code
                FROM permissions p
                JOIN role_permissions rp ON rp.permission_id = p.id
                JOIN user_roles ur ON ur.role_id = rp.role_id
                WHERE ur.user_id = :user_id
                  AND COALESCE(p.is_active, 1) = 1
                """
            ),
            {"user_id": user_id},
        ).fetchall()
    except Exception:
        try:
            db.session.remove()
        except Exception:
            pass
        context = {
            "user": None,
            "roles": [],
            "permissions": set(),
            "is_active": False,
        }
        g._rbac_security_context = context
        return context

    context = {
        "user": {
            "id": int(user_row["id"]),
            "email": user_row.get("email"),
            "full_name": user_row.get("full_name"),
        },
        "roles": [{"id": int(row["id"]), "name": row["name"]} for row in (role_rows or [])],
        "permissions": {str(row[0]) for row in (permission_rows or []) if row and row[0]},
        "is_active": bool(user_row.get("is_active", True)),
    }
    g._rbac_security_context = context
    return context


def has_any_permission(*permission_codes):
    required_codes = {code for code in permission_codes if code}
    if not required_codes:
        return True

    context = get_current_security_context()
    if not context.get("is_active"):
        return False

    user_permissions = context.get("permissions") or set()
    return not user_permissions.isdisjoint(required_codes)


def enforce_path_permission(path: str):
    required_codes = get_request_permissions(path)
    if not required_codes:
        return None

    if has_any_permission(*required_codes):
        return None

    return _permission_denied_response()


def require_permission(*permission_codes):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not has_any_permission(*permission_codes):
                return _permission_denied_response()
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def role_required(required_roles):
    allowed = {str(role).upper() for role in (required_roles or [])}

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            context = get_current_security_context()
            if not context.get("is_active"):
                return {"message": "Inactive or invalid user"}, 403

            user_roles = {
                str(role.get("name", "")).upper()
                for role in (context.get("roles") or [])
                if isinstance(role, dict)
            }
            if allowed and user_roles.isdisjoint(allowed):
                return {"message": "Access denied"}, 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator
