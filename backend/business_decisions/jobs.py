"""Durable per-TIN job admission and state transitions."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from utils.database_locks import DatabaseMaintenanceBusy

TIN_LOCK_PREFIX = "rba_invalid_tin_"
ACTIVE_STATES = ("QUEUED", "RUNNING", "RETRYING", "PAUSED")


def get_active_job(engine, tin_key, action=None):
    clauses = ["active_job_key=CONCAT(:tin, '\\:ACTIVE')"]
    params = {"tin": tin_key}
    if action:
        clauses.append("requested_action=:action")
        params["action"] = action
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT * FROM fraud_business_decision_jobs WHERE "
            + " AND ".join(clauses) + " LIMIT 1"
        ), params).mappings().first()
    return dict(row) if row else None


def tin_lock(conn, tin_key, timeout=10):
    result = conn.execute(text("SELECT GET_LOCK(:name, :timeout)"), {
        "name": TIN_LOCK_PREFIX + tin_key, "timeout": int(timeout)
    }).scalar()
    if result != 1:
        raise DatabaseMaintenanceBusy("Another Invalid-TIN job is active for this TIN.")


def release_tin_lock(conn, tin_key):
    conn.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": TIN_LOCK_PREFIX + tin_key})


def create_status_job(engine, *, tin_key, action, requested_by, before, after, policy_version="1", tin_id=None):
    with engine.begin() as conn:
        tin_lock(conn, tin_key)
        try:
            active = conn.execute(text(
                "SELECT * FROM fraud_business_decision_jobs "
                "WHERE active_job_key=CONCAT(:tin, '\\:ACTIVE') LIMIT 1 FOR UPDATE"
            ), {"tin": tin_key}).mappings().first()
            if active:
                if active["requested_action"] == action:
                    return dict(active), False
                raise ValueError("An opposite Invalid-TIN action is already active for this TIN")
            target = conn.execute(text(
                "SELECT id, status FROM invalid_tins WHERE id=:id FOR UPDATE"
            ), {"id": tin_id}).mappings().first() if tin_id is not None else conn.execute(text(
                "SELECT id, status FROM invalid_tins WHERE tin_number=:tin LIMIT 1 FOR UPDATE"
            ), {"tin": tin_key}).mappings().first()
            if not target:
                raise LookupError("Invalid TIN not found")
            if bool(target["status"]) != bool(before):
                raise ValueError("Invalid-TIN status changed; refresh and retry")
            result = conn.execute(text("""
                INSERT INTO fraud_business_decision_jobs
                  (tin, requested_action, status, current_tax_type,
                   requested_by_user_id, requested_status_before,
                   requested_status_after, policy_version)
                VALUES (:tin, :action, 'QUEUED', 'GST', :user_id, :before, :after, :policy)
            """), {"tin": tin_key, "action": action, "user_id": int(requested_by),
                    "before": int(before), "after": int(after), "policy": policy_version})
            conn.execute(text(
                "UPDATE invalid_tins SET status=:after, modified_date=UTC_TIMESTAMP() WHERE id=:id"
            ), {"after": int(after), "id": target["id"]})
            row = conn.execute(text(
                "SELECT * FROM fraud_business_decision_jobs WHERE job_id=:id"
            ), {"id": result.lastrowid}).mappings().first()
            return dict(row), True
        except IntegrityError:
            raise ValueError("An Invalid-TIN job is already active for this TIN")
        finally:
            release_tin_lock(conn, tin_key)


def claim_job(engine, *, worker_id=None, lease_seconds=120):
    worker_id = worker_id or str(uuid.uuid4())
    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT * FROM fraud_business_decision_jobs
            WHERE status IN ('QUEUED','RETRYING')
               OR (status='RUNNING' AND lease_until < UTC_TIMESTAMP(6))
            ORDER BY created_at, job_id LIMIT 1 FOR UPDATE
        """)).mappings().first()
        if not row:
            return None
        lease = datetime.utcnow() + timedelta(seconds=lease_seconds)
        conn.execute(text("""
            UPDATE fraud_business_decision_jobs
            SET status='RUNNING', worker_id=:worker, lease_until=:lease,
                started_at=COALESCE(started_at, UTC_TIMESTAMP(6)), updated_at=UTC_TIMESTAMP(6)
            WHERE job_id=:id
        """), {"worker": worker_id, "lease": lease, "id": row["job_id"]})
        row = dict(row)
        row.update(status="RUNNING", worker_id=worker_id, lease_until=lease)
        return row


def update_job(conn, job_id, worker_id, **fields):
    fields["job_id"] = int(job_id)
    fields["worker_id"] = worker_id
    assignments = ", ".join(f"{key}=:{key}" for key in fields if key not in {"job_id", "worker_id"})
    fields["updated_at"] = datetime.utcnow()
    assignments += ", updated_at=:updated_at"
    conn.execute(text(
        f"UPDATE fraud_business_decision_jobs SET {assignments} "
        "WHERE job_id=:job_id AND worker_id=:worker_id"
    ), fields)
