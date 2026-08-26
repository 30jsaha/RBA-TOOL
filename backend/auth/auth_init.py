import os
from datetime import timedelta

from flask_jwt_extended import JWTManager
from dotenv import load_dotenv
from flask import jsonify

from .auth_middleware import install_auth_middleware
from .auth_routes import auth_bp, public_auth_bp

from typing import Optional

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

MIN_JWT_SECRET_LENGTH = 32

DISALLOWED_WEAK_SECRETS = {
    "secret",
    "jwt_secret",
    "jwt_secret_key",
    "jwt-secret-key",
    "change_me",
    "changeme",
    "password",
    "123456",
    "12345678",
    "1234567890",
    "admin",
    "root",
    "default",
    "default_secret",
    "test_secret",
    "your-secret-key",
    "your_secret_key",
    "your_jwt_secret_key_here",
    "rba_tool_secret",
    "rba_tool_default_secret",
    "<generate-a-secure-secret>",
    "<generate_a_secure_secret>",
    "null",
    "none",
    "undefined",
    "placeholder",
}


def validate_jwt_secret(secret: Optional[str]) -> str:
    if secret is None:
        raise RuntimeError("JWT_SECRET_KEY is required. An explicit secret must be configured in the environment.")

    if not isinstance(secret, str):
        secret = str(secret)

    cleaned = secret.strip()
    if not cleaned:
        raise RuntimeError("JWT_SECRET_KEY cannot be empty or whitespace only.")

    if cleaned.lower() in DISALLOWED_WEAK_SECRETS:
        raise RuntimeError("JWT_SECRET_KEY is set to a known insecure default value. A secure secret must be configured.")

    if len(cleaned) < MIN_JWT_SECRET_LENGTH:
        raise RuntimeError(
            f"JWT_SECRET_KEY is too weak (minimum {MIN_JWT_SECRET_LENGTH} characters required)."
        )

    return cleaned


def _get_required_jwt_secret(app):
    configured_secret = app.config.get("JWT_SECRET_KEY")
    if configured_secret is None:
        configured_secret = os.getenv("JWT_SECRET_KEY")

    return validate_jwt_secret(configured_secret)


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def init_auth(app):
    app.config["JWT_SECRET_KEY"] = _get_required_jwt_secret(app)
    app.config.setdefault("JWT_ACCESS_TOKEN_EXPIRES", timedelta(hours=2))
    app.config.setdefault("JWT_REFRESH_TOKEN_EXPIRES", timedelta(days=30))
    app.config.setdefault("JWT_TOKEN_LOCATION", ["headers", "cookies"])
    app.config.setdefault("JWT_HEADER_TYPE", "Bearer")
    app.config.setdefault("JWT_COOKIE_CSRF_PROTECT", True)
    app.config.setdefault("JWT_CSRF_METHODS", ["POST", "PUT", "PATCH", "DELETE"])
    app.config.setdefault("JWT_COOKIE_SAMESITE", os.getenv("JWT_COOKIE_SAMESITE", "Lax"))
    app.config.setdefault("JWT_COOKIE_SECURE", _env_flag("JWT_COOKIE_SECURE"))
    app.config.setdefault("JWT_REFRESH_COOKIE_NAME", "rba_refresh_token")
    app.config.setdefault("JWT_REFRESH_CSRF_COOKIE_NAME", "rba_refresh_csrf")
    app.config.setdefault("JWT_REFRESH_CSRF_HEADER_NAME", "X-CSRF-TOKEN")
    app.config.setdefault("JWT_REFRESH_COOKIE_PATH", "/api/auth")
    app.config.setdefault("JWT_REFRESH_CSRF_COOKIE_PATH", "/")

    jwt = JWTManager(app)

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

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(public_auth_bp, url_prefix="/api")

    install_auth_middleware(app)

    return jwt
