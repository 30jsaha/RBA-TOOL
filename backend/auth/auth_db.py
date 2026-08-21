from sqlalchemy import text

from config.db_config import get_mysql_engine


def fetch_user_for_login(email: str):
    """
    Returns a dict with user + roles, or None if not found.
    Expects old-backend-compatible tables: users, roles, user_roles.
    """
    engine = get_mysql_engine()
    with engine.connect() as conn:
        user = conn.execute(
            text(
                """
                SELECT id, email, password_hash, full_name, is_active
                FROM users
                WHERE LOWER(email) = :email
                LIMIT 1
                """
            ),
            {"email": (email or "").lower()},
        ).mappings().first()

        if not user:
            return None

        roles_rows = conn.execute(
            text(
                """
                SELECT r.name
                FROM roles r
                JOIN user_roles ur ON ur.role_id = r.id
                WHERE ur.user_id = :user_id
                """
            ),
            {"user_id": user["id"]},
        ).fetchall()

    roles = [r[0] for r in roles_rows] if roles_rows else []
    return {
        "id": int(user["id"]),
        "email": user["email"],
        "full_name": user.get("full_name"),
        "password_hash": user["password_hash"],
        "is_active": bool(user.get("is_active", True)),
        "roles": roles,
    }

