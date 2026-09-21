"""Shared backend ownership checks for user-owned tax data."""

from sqlalchemy import text

from utils.auth_helper import get_authenticated_user_id
from utils.rbac import get_current_security_context


def current_user_id():
    raw = get_authenticated_user_id()
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def is_global_admin():
    """Use the existing RBAC role assignment; never trust request user_id."""
    context = get_current_security_context()
    return any(
        str(role.get("name", "")).upper() == "ADMIN"
        for role in (context.get("roles") or [])
        if isinstance(role, dict)
    )


def can_access_owner(owner_id):
    user_id = current_user_id()
    if is_global_admin():
        return True
    try:
        return user_id is not None and int(owner_id) == user_id
    except (TypeError, ValueError):
        return False


def ownership_clause(alias="", column="user_id"):
    """Return a parameterized SQL predicate for normal-user data scope."""
    if is_global_admin():
        return "1 = 1", {}
    user_id = current_user_id()
    qualified = f"{alias}.{column}" if alias else column
    if user_id is None:
        return "1 = 0", {}
    return f"{qualified} = :__current_user_id", {"__current_user_id": user_id}


def ownership_sql_literal(alias="", column="user_id"):
    """Safe SQL fragment for generated queries whose parameter map is opaque."""
    if is_global_admin():
        return "1 = 1"
    user_id = current_user_id()
    if user_id is None:
        return "1 = 0"
    qualified = f"{alias}.{column}" if alias else column
    return f"{qualified} = {int(user_id)}"


def run_owner(engine, run_id, tax_type=None):
    clauses = ["run_id = :run_id"]
    params = {"run_id": str(run_id)}
    if tax_type:
        clauses.append("UPPER(tax_type) = :tax_type")
        params["tax_type"] = str(tax_type).upper()
    with engine.connect() as conn:
        row = conn.execute(
            text(f"SELECT user_id FROM pipeline_log WHERE {' AND '.join(clauses)} "
                 "ORDER BY id ASC LIMIT 1"), params
        ).mappings().first()
    return row.get("user_id") if row else None


def authorize_run(engine, run_id, tax_type, in_memory_status=None):
    if is_global_admin():
        return True
    owner = (in_memory_status or {}).get("user_id")
    if owner is None:
        owner = run_owner(engine, run_id, tax_type)
    return owner is not None and can_access_owner(owner)
