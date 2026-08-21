from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy import text

from ..extensions import db
from utils.rbac import require_permission

bp = Blueprint("role_management", __name__)

SYSTEM_ROLE_NAMES = {"ADMIN", "ANALYST", "VIEWER"}
ROLE_NAME_MAX_LENGTH = 100


def _normalize_role_name(name):
    return str(name or "").strip().upper()


def _bad_request(message, status=400):
    return jsonify({"message": message}), status


def _get_role_row(role_id):
    return db.session.execute(
        text(
            """
            SELECT id, name
            FROM roles
            WHERE id = :role_id
            LIMIT 1
            """
        ),
        {"role_id": role_id},
    ).mappings().first()


def _validate_role_name(name, role_id=None):
    normalized_name = _normalize_role_name(name)
    if not normalized_name:
        return None, _bad_request("Role name is required")

    if len(normalized_name) > ROLE_NAME_MAX_LENGTH:
        return None, _bad_request(f"Role name must be {ROLE_NAME_MAX_LENGTH} characters or fewer")

    duplicate = db.session.execute(
        text(
            """
            SELECT id
            FROM roles
            WHERE UPPER(TRIM(name)) = :name
              AND (:role_id IS NULL OR id <> :role_id)
            LIMIT 1
            """
        ),
        {"name": normalized_name, "role_id": role_id},
    ).fetchone()
    if duplicate:
        return None, _bad_request("Role name already exists", 409)

    return normalized_name, None


def _build_permission_tree(permission_rows):
    nodes = {}
    roots = []

    for row in permission_rows or []:
        node = {
            "id": int(row["id"]),
            "parent_id": int(row["parent_id"]) if row.get("parent_id") is not None else None,
            "code": row["code"],
            "name": row["name"],
            "description": row.get("description"),
            "sort_order": int(row.get("sort_order") or 0),
            "children": [],
        }
        nodes[node["id"]] = node

    for node in nodes.values():
        parent_id = node["parent_id"]
        if parent_id and parent_id in nodes:
            nodes[parent_id]["children"].append(node)
        else:
            roots.append(node)

    def sort_nodes(items):
        items.sort(key=lambda item: (item.get("sort_order", 0), item.get("name") or "", item.get("id") or 0))
        for item in items:
            sort_nodes(item["children"])

    sort_nodes(roots)
    return roots


@bp.get("/api/roles")
@jwt_required()
@require_permission("settings.roles")
def list_roles():
    try:
        rows = db.session.execute(
            text(
                """
                SELECT
                    r.id,
                    r.name,
                    COUNT(DISTINCT ur.user_id) AS user_count
                FROM roles r
                LEFT JOIN user_roles ur ON ur.role_id = r.id
                GROUP BY r.id, r.name
                ORDER BY r.id ASC
                """
            )
        ).mappings().all()
    except Exception as e:
        return jsonify({"message": "Database query failed", "error": str(e)}), 500

    roles = [
        {
            "id": int(row["id"]),
            "name": row["name"],
            "user_count": int(row.get("user_count") or 0),
            "is_system": str(row["name"]).upper() in SYSTEM_ROLE_NAMES,
        }
        for row in (rows or [])
    ]
    return jsonify({"total": len(roles), "roles": roles}), 200


@bp.post("/api/roles")
@jwt_required()
@require_permission("settings.roles")
def create_role():
    data = request.get_json() or {}
    normalized_name, error = _validate_role_name(data.get("name"))
    if error:
        return error

    try:
        db.session.execute(
            text("INSERT INTO roles (name) VALUES (:name)"),
            {"name": normalized_name},
        )
        role_id = db.session.execute(text("SELECT LAST_INSERT_ID()")).scalar()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Create role failed", "error": str(e)}), 500

    return jsonify({"message": "Role created successfully", "role": {"id": int(role_id), "name": normalized_name, "is_system": False}}), 201


@bp.put("/api/roles/<int:role_id>")
@jwt_required()
@require_permission("settings.roles")
def update_role(role_id):
    role_row = _get_role_row(role_id)
    if not role_row:
        return _bad_request("Role not found", 404)

    current_name = str(role_row["name"] or "").upper()
    normalized_name, error = _validate_role_name((request.get_json() or {}).get("name"), role_id=role_id)
    if error:
        return error

    if current_name in SYSTEM_ROLE_NAMES and normalized_name != current_name:
        return _bad_request("System roles cannot be renamed")

    try:
        db.session.execute(
            text("UPDATE roles SET name = :name WHERE id = :role_id"),
            {"name": normalized_name, "role_id": role_id},
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Update role failed", "error": str(e)}), 500

    return jsonify({"message": "Role updated successfully", "role": {"id": role_id, "name": normalized_name, "is_system": current_name in SYSTEM_ROLE_NAMES}}), 200


@bp.get("/api/permissions")
@jwt_required()
@require_permission("settings.role_permissions")
def list_permissions():
    try:
        rows = db.session.execute(
            text(
                """
                SELECT id, parent_id, code, name, description, sort_order, is_active
                FROM permissions
                WHERE COALESCE(is_active, 1) = 1
                ORDER BY sort_order ASC, id ASC
                """
            )
        ).mappings().all()
    except Exception as e:
        return jsonify({"message": "Database query failed", "error": str(e)}), 500

    permission_tree = _build_permission_tree(rows)
    return jsonify({"total": len(rows or []), "permissions": permission_tree}), 200


@bp.get("/api/roles/<int:role_id>/permissions")
@jwt_required()
@require_permission("settings.role_permissions")
def get_role_permissions(role_id):
    role_row = _get_role_row(role_id)
    if not role_row:
        return _bad_request("Role not found", 404)

    rows = db.session.execute(
        text(
            """
            SELECT DISTINCT p.id, p.code
            FROM permissions p
            JOIN role_permissions rp ON rp.permission_id = p.id
            WHERE rp.role_id = :role_id
            ORDER BY p.sort_order ASC, p.id ASC
            """
        ),
        {"role_id": role_id},
    ).mappings().all()

    permission_ids = [int(row["id"]) for row in (rows or [])]
    permission_codes = [row["code"] for row in (rows or [])]

    return jsonify({
        "role": {"id": int(role_row["id"]), "name": role_row["name"]},
        "permission_ids": permission_ids,
        "permission_codes": permission_codes,
    }), 200


@bp.put("/api/roles/<int:role_id>/permissions")
@jwt_required()
@require_permission("settings.role_permissions")
def replace_role_permissions(role_id):
    role_row = _get_role_row(role_id)
    if not role_row:
        return _bad_request("Role not found", 404)

    data = request.get_json() or {}
    raw_permission_ids = data.get("permission_ids", [])
    if raw_permission_ids is None:
        raw_permission_ids = []
    if not isinstance(raw_permission_ids, list):
        return _bad_request("permission_ids must be an array")

    try:
        permission_ids = sorted({int(permission_id) for permission_id in raw_permission_ids})
    except (TypeError, ValueError):
        return _bad_request("permission_ids contains invalid values")

    if permission_ids:
        placeholders = ", ".join([f":permission_id_{index}" for index, _ in enumerate(permission_ids)])
        params = {f"permission_id_{index}": permission_id for index, permission_id in enumerate(permission_ids)}
        rows = db.session.execute(
            text(
                f"""
                SELECT id
                FROM permissions
                WHERE id IN ({placeholders})
                  AND COALESCE(is_active, 1) = 1
                """
            ),
            params,
        ).fetchall()
        valid_ids = {int(row[0]) for row in (rows or [])}
        if len(valid_ids) != len(permission_ids):
            return _bad_request("One or more permissions are invalid or inactive")

    try:
        db.session.execute(
            text("DELETE FROM role_permissions WHERE role_id = :role_id"),
            {"role_id": role_id},
        )

        for permission_id in permission_ids:
            db.session.execute(
                text(
                    """
                    INSERT INTO role_permissions (role_id, permission_id, created_at, updated_at)
                    VALUES (:role_id, :permission_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """
                ),
                {"role_id": role_id, "permission_id": permission_id},
            )

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Update role permissions failed", "error": str(e)}), 500

    return jsonify({
        "message": "Role permissions updated successfully",
        "role": {"id": int(role_row["id"]), "name": role_row["name"]},
        "permission_ids": permission_ids,
    }), 200
