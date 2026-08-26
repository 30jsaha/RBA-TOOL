import os
import time
import threading
from collections import defaultdict

from flask import Blueprint, jsonify, request, make_response
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    get_jwt,
    get_jwt_identity,
    jwt_required,
    set_refresh_cookies,
    unset_jwt_cookies,
)
from passlib.hash import bcrypt

from .auth_db import fetch_user_for_login
from utils.rbac import get_current_security_context

auth_bp = Blueprint("auth", __name__)
public_auth_bp = Blueprint("public_auth", __name__)


class LoginRateLimiter:
    def __init__(self, max_attempts=5, window_seconds=60, lockout_seconds=300):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.lockout_seconds = lockout_seconds
        self.attempts = defaultdict(list)
        self.lockouts = {}
        self.lock = threading.Lock()

    def is_locked_out(self, ip):
        with self.lock:
            now = time.time()
            if ip in self.lockouts:
                if now > self.lockouts[ip]:
                    del self.lockouts[ip]
                else:
                    return int(self.lockouts[ip] - now)
            return 0

    def record_attempt(self, ip, success):
        with self.lock:
            now = time.time()
            if success:
                self.attempts[ip] = []
                if ip in self.lockouts:
                    del self.lockouts[ip]
                return True
            self.attempts[ip].append(now)
            self.attempts[ip] = [t for t in self.attempts[ip] if now - t < self.window_seconds]
            if len(self.attempts[ip]) >= self.max_attempts:
                self.lockouts[ip] = now + self.lockout_seconds
                return False
            return True


limiter = LoginRateLimiter()


def _auth_debug_enabled() -> bool:
    return os.getenv("AUTH_DEBUG", "").strip() == "1"


def _build_user_payload(user):
    return {
        "id": user["id"],
        "email": user["email"],
        "full_name": user.get("full_name"),
        "roles": user.get("roles", []),
    }


def _issue_auth_response(user):
    access_token = create_access_token(
        identity=str(user["id"]),
        additional_claims={"email": user["email"], "roles": user.get("roles", [])},
    )
    refresh_token = create_refresh_token(identity=str(user["id"]))

    response = jsonify(
        {
            "access": access_token,
            "user": _build_user_payload(user),
        }
    )
    set_refresh_cookies(response, refresh_token)
    return response, access_token


def _login_impl():
    ip = request.headers.get("X-Forwarded-For", request.remote_addr) or "unknown"
    lockout_remaining = limiter.is_locked_out(ip)
    if lockout_remaining > 0:
        return jsonify({
            "message": f"Too many failed login attempts. Please try again in {lockout_remaining} seconds."
        }), 429

    data = request.get_json(silent=True) or {}
    email = (data.get("email", "") or "").lower().strip()
    password_raw = data.get("password", "")

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
            print(f"[AUTH_DEBUG] stored_hash_prefix={stored_hash[:4]}")

    password_ok = False
    if user and user.get("is_active") and stored_hash:
        try:
            password_ok = bcrypt.verify(password, stored_hash)
        except ValueError as e:
            if _auth_debug_enabled():
                print(f"[AUTH_DEBUG] password verify error: {e}")
            password_ok = False

    if not password_ok:
        limiter.record_attempt(ip, success=False)
        return jsonify({"message": "Invalid credentials"}), 401

    limiter.record_attempt(ip, success=True)
    response, _ = _issue_auth_response(user)

    if _auth_debug_enabled():
        print(f"[AUTH_DEBUG] authenticated user_id={user['id']} email={user['email']}")

    return response, 200


@auth_bp.post("/login")
def login():
    return _login_impl()


@public_auth_bp.post("/login")
def login_alias():
    return _login_impl()


@auth_bp.post("/refresh")
@jwt_required(refresh=True, locations=["cookies"])
def refresh():
    current_user_id = get_jwt_identity()
    claims = get_jwt()

    access_token = create_access_token(
        identity=str(current_user_id),
        additional_claims={"email": claims.get("email"), "roles": claims.get("roles", [])},
    )
    refresh_token = create_refresh_token(identity=str(current_user_id))

    response = jsonify({"access": access_token})
    set_refresh_cookies(response, refresh_token)
    return response, 200


@auth_bp.post("/logout")
def logout_route():
    response = make_response(jsonify({"message": "Logged out"}), 200)
    unset_jwt_cookies(response)
    return response


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
