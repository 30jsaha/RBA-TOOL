from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from passlib.hash import bcrypt
from sqlalchemy import text

from ..extensions import db
from utils.rbac import require_permission

bp = Blueprint("user_management", __name__, url_prefix="/api/users")


def _resolve_role_assignments(raw_roles):
    normalized_roles = []
    seen = set()

    for role_name in (raw_roles or []):
        normalized_name = str(role_name or "").strip().upper()
        if not normalized_name or normalized_name in seen:
            continue
        normalized_roles.append(normalized_name)
        seen.add(normalized_name)

    if not normalized_roles:
        return [], None

    placeholders = ", ".join([f":role_name_{index}" for index, _ in enumerate(normalized_roles)])
    params = {f"role_name_{index}": role_name for index, role_name in enumerate(normalized_roles)}

    rows = db.session.execute(
        text(
            f"""
            SELECT id, name
            FROM roles
            WHERE UPPER(TRIM(name)) IN ({placeholders})
            """
        ),
        params,
    ).fetchall()

    role_map = {str(row[1]).upper(): int(row[0]) for row in (rows or [])}
    missing = [role_name for role_name in normalized_roles if role_name not in role_map]
    if missing:
        return None, missing

    return [(role_map[role_name], role_name) for role_name in normalized_roles], None


# ======================================================
# GET /api/users/list
# ======================================================
@bp.get("/list")
@jwt_required()
@require_permission("settings.users")
def list_users():
    """
    Returns:
    {
      "total": <int>,
      "users": [{ id, email, full_name, roles: [..], is_active, created_at }]
    }
    """
    query = text(
        """
        SELECT
            u.id AS id,
            u.email AS email,
            u.full_name AS full_name,
            u.is_active AS is_active,
            u.created_at AS created_at,
            GROUP_CONCAT(DISTINCT r.name ORDER BY r.name SEPARATOR ',') AS roles
        FROM users u
        LEFT JOIN user_roles ur ON u.id = ur.user_id
        LEFT JOIN roles r ON ur.role_id = r.id
        GROUP BY u.id, u.email, u.full_name, u.is_active, u.created_at
        ORDER BY u.created_at DESC
        """
    )

    try:
        rows = db.session.execute(query).fetchall()
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Database query failed", "error": str(e)}), 500

    users = []
    for r in rows or []:
        raw_roles = getattr(r, "roles", None)
        roles = [s for s in (str(raw_roles).split(",") if raw_roles else []) if s]
        created_at = getattr(r, "created_at", None)

        users.append(
            {
                "id": getattr(r, "id", None),
                "email": getattr(r, "email", None),
                "full_name": getattr(r, "full_name", None),
                "roles": roles,
                "is_active": bool(getattr(r, "is_active", False)),
                "created_at": created_at.isoformat() if created_at else None,
            }
        )

    return jsonify({"total": len(users), "users": users}), 200
# ======================================================
# POST /api/users/create-user
# ======================================================
@bp.post("/create-user")
@jwt_required()
@require_permission("settings.users")
def create_user():
    data = request.get_json() or {}

    email = data.get("email")
    password = data.get("password")
    full_name = data.get("full_name")
    roles = data.get("roles", []) or []

    if not email or not password:
        return jsonify({"message": "Email and password are required"}), 400

    email_norm = str(email).lower().strip()

    try:
        existing = db.session.execute(
            text("SELECT id FROM users WHERE LOWER(email) = :email LIMIT 1"),
            {"email": email_norm},
        ).fetchone()
        if existing:
            return jsonify({"message": "User already exists"}), 409

        # Hash password using the same scheme as login verification (passlib bcrypt).
        password_hash = bcrypt.hash(str(password))

        # created_at column may or may not exist depending on DB snapshot; be NULL-safe.
        has_created_at = False
        try:
            has_created_at = (
                db.session.execute(
                    text(
                        "SELECT COUNT(*) AS cnt "
                        "FROM INFORMATION_SCHEMA.COLUMNS "
                        "WHERE TABLE_SCHEMA = DATABASE() "
                        "  AND TABLE_NAME = 'users' "
                        "  AND COLUMN_NAME = 'created_at'"
                    )
                ).scalar()
                or 0
            ) > 0
        except Exception:
            has_created_at = False

        if has_created_at:
            db.session.execute(
                text(
                    """
                    INSERT INTO users (email, password_hash, full_name, is_active, created_at)
                    VALUES (:email, :password_hash, :full_name, 1, NOW())
                    """
                ),
                {"email": email_norm, "password_hash": password_hash, "full_name": full_name},
            )
        else:
            db.session.execute(
                text(
                    """
                    INSERT INTO users (email, password_hash, full_name, is_active)
                    VALUES (:email, :password_hash, :full_name, 1)
                    """
                ),
                {"email": email_norm, "password_hash": password_hash, "full_name": full_name},
            )

        user_id = db.session.execute(text("SELECT LAST_INSERT_ID()")).scalar()

        role_assignments, missing_roles = _resolve_role_assignments(roles)
        if missing_roles:
            db.session.rollback()
            return jsonify({"message": f"Invalid role(s): {', '.join(missing_roles)}"}), 400

        role_names = [role_name for _, role_name in (role_assignments or [])]
        if user_id and role_assignments:
            for role_id, role_name in role_assignments:
                db.session.execute(
                    text("INSERT INTO user_roles (user_id, role_id) VALUES (:user_id, :role_id)"),
                    {"user_id": int(user_id), "role_id": int(role_id)},
                )

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Create user failed", "error": str(e)}), 500

    return (
        jsonify(
            {
                "message": "User created successfully",
                "user": {
                    "id": int(user_id) if user_id is not None else None,
                    "email": email_norm,
                    "full_name": full_name,
                    "roles": role_names,
                    "is_active": True,
                },
            }
        ),
        201,
    )
# ======================================================
# POST /api/users/<user_id>/status
# ======================================================
@bp.put("/<int:user_id>/status")
@jwt_required()
@require_permission("settings.users")
def toggle_user_status(user_id):
    data = request.get_json() or {}

    if "is_active" not in data:
        return jsonify({"message": "is_active field required"}), 400

    if get_jwt_identity() == user_id:
        return jsonify({"message": "You cannot change your own status"}), 400

    try:
        exists = (
            db.session.execute(text("SELECT COUNT(*) AS cnt FROM users WHERE id = :id"), {"id": user_id}).scalar()
            or 0
        )
        if int(exists) <= 0:
            return jsonify({"message": "User not found"}), 404

        db.session.execute(
            text("UPDATE users SET is_active = :is_active WHERE id = :id"),
            {"id": user_id, "is_active": bool(data["is_active"])},
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Update failed", "error": str(e)}), 500

    return jsonify({"message": "User status updated", "user": {"id": user_id, "is_active": bool(data["is_active"])}}), 200

# ======================================================
# POST /api/users/<user_id>
# ======================================================
@bp.put("/<int:user_id>")
@jwt_required()
@require_permission("settings.users")
def update_user(user_id):
    data = request.get_json() or {}

    full_name = data.get("full_name", None)
    password = data.get("password", None)
    roles = data.get("roles", None)

    if full_name is None and (password is None or password == "") and roles is None:
        return jsonify({"message": "No fields to update"}), 400

    try:
        exists = (
            db.session.execute(text("SELECT COUNT(*) AS cnt FROM users WHERE id = :id"), {"id": user_id}).scalar()
            or 0
        )
        if int(exists) <= 0:
            return jsonify({"message": "User not found"}), 404

        if full_name is not None:
            db.session.execute(
                text("UPDATE users SET full_name = :full_name WHERE id = :id"),
                {"id": user_id, "full_name": full_name},
            )

        if password is not None and password != "":
            password_hash = bcrypt.hash(str(password))
            db.session.execute(
                text("UPDATE users SET password_hash = :password_hash WHERE id = :id"),
                {"id": user_id, "password_hash": password_hash},
            )

        if roles is not None:
            role_assignments, missing_roles = _resolve_role_assignments(roles)
            if missing_roles:
                db.session.rollback()
                return jsonify({"message": f"Invalid role(s): {', '.join(missing_roles)}"}), 400

            db.session.execute(text("DELETE FROM user_roles WHERE user_id = :user_id"), {"user_id": user_id})
            role_names = [role_name for _, role_name in (role_assignments or [])]
            for role_id, role_name in (role_assignments or []):
                db.session.execute(
                    text("INSERT INTO user_roles (user_id, role_id) VALUES (:user_id, :role_id)"),
                    {"user_id": user_id, "role_id": int(role_id)},
                )
        else:
            role_names = None

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Update failed", "error": str(e)}), 500

    payload = {"id": user_id}
    if full_name is not None:
        payload["full_name"] = full_name
    if role_names is not None:
        payload["roles"] = role_names
    return jsonify({"message": "User updated successfully", "user": payload}), 200

# ======================================================
# GET /api/users/roles
# ======================================================
@bp.get("/roles")
@jwt_required()
@require_permission("settings.users")
def list_roles():
    try:
        rows = db.session.execute(text("SELECT id, name FROM roles ORDER BY name ASC")).fetchall()
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Database query failed", "error": str(e)}), 500

    roles = [{"id": r[0], "name": r[1]} for r in (rows or [])]
    return jsonify({"total": len(roles), "roles": roles}), 200
