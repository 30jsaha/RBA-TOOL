"""SQLAlchemy repository for FBD history and durable jobs."""

import json
from datetime import datetime, timedelta

from sqlalchemy import text

from .policy import ACTIVE, INACTIVE, NORMAL


SOURCE_TABLES = {
    "GST": "gst_fraud_justification",
    "SWT": "swt_fraud_justification",
    "CIT": "cit_fraud_justification",
}


def _json(value):
    return json.dumps(value, default=str) if value is not None else None


def source_table(tax_type):
    key = str(tax_type or "").upper()
    if key not in SOURCE_TABLES:
        raise ValueError("Unsupported tax type")
    return SOURCE_TABLES[key]


def ensure_schema(engine):
    from .schema import FRAUD_BUSINESS_DECISIONS_DDL, FRAUD_BUSINESS_DECISION_JOBS_DDL
    with engine.begin() as conn:
        conn.execute(text(FRAUD_BUSINESS_DECISIONS_DDL))
        conn.execute(text(FRAUD_BUSINESS_DECISION_JOBS_DDL))


def get_current(conn, tax_type, source_record_id, for_update=False):
    suffix = " FOR UPDATE" if for_update else ""
    return conn.execute(text(
        "SELECT * FROM fraud_business_decisions "
        "WHERE tax_type=:tax_type AND source_record_id=:source_record_id "
        "AND is_current=1 LIMIT 1" + suffix
    ), {"tax_type": tax_type, "source_record_id": int(source_record_id)}).mappings().first()


def get_next_version(conn, tax_type, source_record_id):
    return int(conn.execute(text(
        "SELECT COALESCE(MAX(decision_version), 0) + 1 FROM fraud_business_decisions "
        "WHERE tax_type=:tax_type AND source_record_id=:source_record_id FOR UPDATE"
    ), {"tax_type": tax_type, "source_record_id": int(source_record_id)}).scalar() or 1)


def insert_decision(conn, data):
    columns = [
        "tax_type", "source_table", "source_record_id", "decision_version", "is_current",
        "previous_decision_id", "tin_original", "tin_key", "taxpayer_name_at_decision",
        "tax_period_year", "tax_period_month", "assessment_number", "tax_account_number",
        "upload_batch_id", "run_id", "source_user_id", "original_ml_result",
        "original_rule_result", "original_predicted_fraud", "original_is_fraud",
        "original_is_fraud_rule", "original_rules_violated", "original_fraud_probability",
        "original_explanation", "original_justification", "original_rule_evidence_json",
        "original_source_metadata_json", "invalid_tin_state_at_decision", "invalid_tin_id",
        "invalid_tin_status_at_decision", "current_business_result", "business_decision_type",
        "decision_reason", "override_reason", "override_by_user_id", "decided_by_user_id",
        "decided_at",
    ]
    params = {key: data.get(key) for key in columns}
    params["original_rule_evidence_json"] = _json(params["original_rule_evidence_json"])
    params["original_source_metadata_json"] = _json(params["original_source_metadata_json"])
    names = ", ".join(columns)
    values = ", ".join(f":{key}" for key in columns)
    result = conn.execute(text(f"INSERT INTO fraud_business_decisions ({names}) VALUES ({values})"), params)
    return int(result.lastrowid)


def mark_current(conn, decision_id, previous_id=None):
    if previous_id:
        conn.execute(text(
            "UPDATE fraud_business_decisions SET is_current=0 "
            "WHERE id=:id AND is_current=1"
        ), {"id": int(previous_id)})
    conn.execute(text(
        "UPDATE fraud_business_decisions SET is_current=1 WHERE id=:id"
    ), {"id": int(decision_id)})


def create_version(conn, *, source, original, decision, actor_id=None,
                   override_reason=None, previous=None, version=None):
    tax_type = source["tax_type"]
    source_id = int(source["source_record_id"])
    version = version or get_next_version(conn, tax_type, source_id)
    data = {
        **source,
        **original,
        **decision,
        "source_table": source.get("source_table") or source_table(tax_type),
        "decision_version": version,
        "is_current": 0,
        "previous_decision_id": previous["id"] if previous else None,
        "override_reason": override_reason,
        "override_by_user_id": actor_id if decision.get("business_decision_type") == "ADMIN_OVERRIDE" else None,
        "decided_by_user_id": actor_id,
        "decided_at": datetime.utcnow(),
    }
    decision_id = insert_decision(conn, data)
    mark_current(conn, decision_id, previous["id"] if previous else None)
    return decision_id


def find_source_rows(conn, tax_type, tin_key, after_id, limit):
    table = source_table(tax_type)
    query = f"SELECT * FROM `{table}` WHERE id > :after_id " \
            "AND (TRIM(CAST(tin AS CHAR)) = :tin_key " \
            "OR TRIM(CAST(tin AS CHAR)) = CONCAT(:tin_key, '.0')) " \
            "ORDER BY id ASC LIMIT :limit"
    return conn.execute(text(query), {"after_id": int(after_id or 0), "tin_key": tin_key, "limit": int(limit)}).mappings().all()


def get_invalid_tin(conn, tin_key, for_update=False):
    suffix = " FOR UPDATE" if for_update else ""
    return conn.execute(text(
        "SELECT id, tin_number, status FROM invalid_tins "
        "WHERE tin_number=:tin_key LIMIT 1" + suffix
    ), {"tin_key": tin_key}).mappings().first()


def serialize_job(row):
    if not row:
        return None
    result = dict(row)
    for key in ("started_at", "completed_at", "created_at", "updated_at", "lease_until"):
        if result.get(key):
            result[key] = result[key].isoformat()
    return result
