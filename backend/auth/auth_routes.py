import os

from flask import Blueprint, jsonify, request
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    get_jwt,
    get_jwt_identity,
    jwt_required,
)
from passlib.hash import bcrypt

from .auth_db import fetch_user_for_login
from utils.rbac import get_current_security_context

auth_bp = Blueprint("auth", __name__)
public_auth_bp = Blueprint("public_auth", __name__)


def _auth_debug_enabled() -> bool:
    return os.getenv("AUTH_DEBUG", "").strip() == "1"


def _login_impl():
    """
    Ported from old-backend `app/blueprints/auth.py` with DB access adapted
    to this backend's SQLAlchemy engine.
    """
    data = request.get_json(silent=True) or {}
    email = (data.get("email", "") or "").lower().strip()
    password_raw = data.get("password", "")

    # Ensure we only ever verify the *raw* password, not pre-hashed/encoded data.
    # Never print the password value; only type/length when AUTH_DEBUG=1.
    if isinstance(password_raw, bytes):
        password = password_raw.decode("utf-8", errors="ignore")
    elif password_raw is None:
        password = ""
    else:
        password = str(password_raw)

    if not email or not password:
        return jsonify({"message": "Email and password are required"}), 400

    try:
        user = fetch_user_for_login(email=email)
    except Exception as e:
        if _auth_debug_enabled():
            print(f"[AUTH_DEBUG] login db error: {e}")
        return jsonify({"message": "Authentication service unavailable"}), 500

    stored_hash = user.get("password_hash") if user else None
    if isinstance(stored_hash, bytes):
        stored_hash = stored_hash.decode("utf-8", errors="ignore")
    if isinstance(stored_hash, str):
        stored_hash = stored_hash.strip()

    if _auth_debug_enabled():
        try:
            pw_len = len(password.encode("utf-8", errors="ignore"))
        except Exception:
            pw_len = None
        print(f"[AUTH_DEBUG] password type={type(password_raw)} len_bytes={pw_len}")
        print(f"[AUTH_DEBUG] stored_hash type={type(stored_hash)}")
        print(f"[AUTH_DEBUG] user_found={bool(user)} is_active={bool(user.get('is_active')) if user else None}")
        if isinstance(stored_hash, str):
            # Never print full hash; prefix is enough to detect scheme.
            print(f"[AUTH_DEBUG] stored_hash_prefix={stored_hash[:4]}")

    password_ok = False
    if user and user.get("is_active") and stored_hash:
        try:
            password_ok = bcrypt.verify(password, stored_hash)
        except ValueError as e:
            # passlib's bcrypt may raise on invalid/oversized secret inputs;
            # treat as invalid credentials (do not leak details).
            if _auth_debug_enabled():
                print(f"[AUTH_DEBUG] password verify error: {e}")
            password_ok = False

    if not password_ok:
        return jsonify({"message": "Invalid credentials"}), 401

    access_token = create_access_token(
        identity=str(user["id"]),
        additional_claims={"email": user["email"], "roles": user.get("roles", [])},
    )
    refresh_token = create_refresh_token(identity=str(user["id"]))

    if _auth_debug_enabled():
        print(f"[AUTH_DEBUG] authenticated user_id={user['id']} email={user['email']}")

    return jsonify(
        {
            "access": access_token,
            "refresh": refresh_token,
            "user": {
                "id": user["id"],
                "email": user["email"],
                "full_name": user.get("full_name"),
                "roles": user.get("roles", []),
            },
        }
    ), 200


@auth_bp.post("/login")
def login():
    return _login_impl()


@public_auth_bp.post("/login")
def login_alias():
    # Alias for compatibility with clients expecting POST /api/login
    return _login_impl()


@auth_bp.post("/refresh")
@jwt_required(refresh=True)
def refresh():
    current_user_id = get_jwt_identity()
    claims = get_jwt()

    new_access_token = create_access_token(
        identity=str(current_user_id),
        additional_claims={"email": claims.get("email"), "roles": claims.get("roles", [])},
    )
    return jsonify({"access": new_access_token}), 200


@auth_bp.get("/me")
@jwt_required()
def me():
    context = get_current_security_context()
    user = context.get("user") or {}
    roles = context.get("roles") or []
    permissions = sorted(context.get("permissions") or [])

    payload = {
        "id": user.get("id"),
        "email": user.get("email"),
        "full_name": user.get("full_name"),
        "roles": roles,
        "permissions": permissions,
        "user": user,
    }
    return jsonify(payload), 200
