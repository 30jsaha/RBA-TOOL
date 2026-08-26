import os
import traceback

from flask import jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, verify_jwt_in_request

from utils.rbac import enforce_path_permission


def _auth_debug_enabled() -> bool:
    return os.getenv("AUTH_DEBUG", "").strip() == "1"


def install_auth_middleware(app):
    """
    Centralized protection layer (avoids touching individual route handlers).
    """
    public_paths = {
        "/api/health",
        "/api/login",
        "/api/auth/login",
        "/api/auth/refresh",
        "/api/auth/logout",
        "/api/auth/me",
    }

    @app.before_request
    def _protect_api_routes():
        # Always allow CORS preflight
        if request.method == "OPTIONS":
            return None

        path = request.path or ""

        # Only protect API routes
        if not path.startswith("/api"):
            return None

        # Allowlist specific public endpoints
        if path in public_paths:
            return None

        # Recent Upload CSV file downloads use a signed one-time token in the URL,
        # so the browser can fetch the file without attaching the JWT auth header.
        if path.startswith("/api/upload-history/recent-uploads/downloads/"):
            return None

        try:
            # Force header-only lookup so JWT verification never touches request body/form
            # (important for multipart/form-data upload endpoints like /api/*/validate).
            verify_jwt_in_request(locations=["headers"])
        except Exception as e:
            # Treat any token verification issue as 401 (keeps behavior consistent and avoids 500s).
            # Note: Changing `JWT_SECRET_KEY` invalidates previously-issued tokens; clients must re-login.
            if _auth_debug_enabled():
                has_auth = bool(request.headers.get("Authorization"))
                content_type = request.content_type or ""
                is_multipart = content_type.lower().startswith("multipart/form-data")
                print(f"[AUTH_DEBUG] denied path={path} has_auth_header={has_auth} error={e}")
                print(f"[AUTH_DEBUG] content_type={content_type} multipart={is_multipart}")
                print("[AUTH_DEBUG] jwt_verify_traceback:\n" + traceback.format_exc())
            return jsonify({"message": "Missing or invalid token"}), 401

        forbidden = enforce_path_permission(path)
        if forbidden is not None:
            return forbidden

        if _auth_debug_enabled():
            try:
                user_id = get_jwt_identity()
                claims = get_jwt()
                print(f"[AUTH_DEBUG] allowed path={path} user_id={user_id} roles={claims.get('roles', [])}")
            except Exception:
                print(f"[AUTH_DEBUG] allowed path={path} (claims unavailable)")

        return None


