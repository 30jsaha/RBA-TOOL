import os
from datetime import timedelta

from flask_jwt_extended import JWTManager
from dotenv import load_dotenv
from flask import jsonify

from .auth_middleware import install_auth_middleware
from .auth_routes import auth_bp, public_auth_bp


load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))


def _get_required_jwt_secret(app):
    configured_secret = app.config.get("JWT_SECRET_KEY")
    if configured_secret is None:
        configured_secret = os.getenv("JWT_SECRET_KEY")

    if isinstance(configured_secret, str):
        configured_secret = configured_secret.strip()

    if not configured_secret:
        raise RuntimeError("JWT_SECRET_KEY is required")

    return configured_secret


def init_auth(app):
    """
    Initialize JWT + auth routes + centralized API protection.

    This is intentionally minimal and does not touch any business logic.
    """
    app.config["JWT_SECRET_KEY"] = _get_required_jwt_secret(app)
    app.config.setdefault("JWT_ACCESS_TOKEN_EXPIRES", timedelta(hours=2))
    app.config.setdefault("JWT_REFRESH_TOKEN_EXPIRES", timedelta(days=30))
    app.config.setdefault("JWT_TOKEN_LOCATION", ["headers"])
    app.config.setdefault("JWT_HEADER_TYPE", "Bearer")

    jwt = JWTManager(app)

    # Provide consistent JSON for JWT errors (prevents silent/opaque 400s).
    @jwt.unauthorized_loader
    def _jwt_unauthorized(reason):
        return jsonify({"message": "Missing or invalid token"}), 401

    @jwt.invalid_token_loader
    def _jwt_invalid(reason):
        return jsonify({"message": "Missing or invalid token"}), 401

    @jwt.expired_token_loader
    def _jwt_expired(jwt_header, jwt_payload):
        return jsonify({"message": "Token expired"}), 401

    @jwt.needs_fresh_token_loader
    def _jwt_needs_fresh(jwt_header, jwt_payload):
        return jsonify({"message": "Fresh token required"}), 401

    # Routes:
    # - old-backend compatible: /api/auth/login, /api/auth/refresh, /api/auth/me
    # - convenience alias: /api/login (commonly expected by frontend)
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(public_auth_bp, url_prefix="/api")

    # Protect everything under /api/* except allowlisted routes
    install_auth_middleware(app)

    return jwt
