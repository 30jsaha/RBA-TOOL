"""Durable Invalid-TIN worker with keyset checkpoints."""

import logging
import time
import uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from utils.database_locks import financial_data_lock

from .jobs import claim_job, update_job
from .policy import ACTIVE, INACTIVE
from .repository import ensure_schema, find_source_rows, get_invalid_tin
from .service import ensure_original_and_policy
from .tin import normalize_tin

logger = logging.getLogger(__name__)
TAX_TYPES = ("GST", "SWT", "CIT")
DEFAULT_CHUNK_SIZE = 1000
MAX_RETRIES = 3


def _retryable(exc):
    value = str(exc or "").lower()
    return any(marker in value for marker in (
        "deadlock", "lock wait timeout", "server has gone away", "lost connection",
        "connection reset", "forcibly closed",
    ))


def _set_state(engine, job_id, status, **extra):
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE fraud_business_decision_jobs SET status=:status, "
            "updated_at=UTC_TIMESTAMP(6), completed_at=:completed_at, error_message=:error "
            "WHERE job_id=:id"
        ), {"status": status, "id": int(job_id),
            "completed_at": extra.get("completed_at"), "error": extra.get("error_message")})


def process_job(engine, job, *, chunk_size=DEFAULT_CHUNK_SIZE):
    """Process one claimed job; each chunk and cursor are one transaction."""
    job_id = int(job["job_id"])
    worker_id = job["worker_id"]
    tin_key = normalize_tin(job["tin"])
    if not tin_key:
        _set_state(engine, job_id, "FAILED", error_message="Invalid canonical TIN")
        return

    current_tax = job.get("current_tax_type") or "GST"
    cursor = job.get("last_processed_source_id")
    processed = int(job.get("records_processed") or 0)
    overridden = int(job.get("records_overridden") or 0)
    skipped = int(job.get("records_skipped") or 0)
    failed = int(job.get("records_failed") or 0)
    action = str(job["requested_action"]).upper()

    while current_tax:
        try:
            with financial_data_lock(engine, timeout_seconds=30):
                with engine.begin() as conn:
                    invalid_row = get_invalid_tin(conn, tin_key)
                    # The status snapshot is read inside each chunk. History stores
                    # the value; it is never recomputed for committed rows.
                    rows = find_source_rows(conn, current_tax, tin_key, cursor, chunk_size)
                    if not rows:
                        next_index = TAX_TYPES.index(current_tax) + 1
                        if next_index >= len(TAX_TYPES):
                            update_job(conn, job_id, worker_id, status="COMPLETED",
                                       current_tax_type=None, last_processed_source_id=cursor,
                                       records_processed=processed, records_overridden=overridden,
                                       records_skipped=skipped, records_failed=failed,
                                       completed_at=datetime.utcnow())
                            return
                        current_tax = TAX_TYPES[next_index]
                        cursor = None
                        update_job(conn, job_id, worker_id, current_tax_type=current_tax,
                                   last_processed_source_id=None, records_processed=processed,
                                   records_overridden=overridden, records_skipped=skipped,
                                   records_failed=failed)
                        continue

                    last_id = cursor
                    for row in rows:
                        last_id = int(row["id"])
                        result = ensure_original_and_policy(
                            conn, tax_type=current_tax, row=row,
                            invalid_row=invalid_row,
                            disabled=action == "DISABLE",
                            actor_id=job.get("requested_by_user_id"),
                        )
                        processed += 1
                        if result.get("skipped"):
                            skipped += 1
                        elif result.get("projected"):
                            overridden += 1
                    cursor = last_id
                    update_job(conn, job_id, worker_id, status="RUNNING",
                               current_tax_type=current_tax,
                               last_processed_source_id=cursor,
                               records_processed=processed,
                               records_overridden=overridden,
                               records_skipped=skipped,
                               records_failed=failed)
        except OperationalError as exc:
            retries = int(job.get("retry_count") or 0) + 1
            if retries <= MAX_RETRIES and _retryable(exc):
                with engine.begin() as conn:
                    update_job(conn, job_id, worker_id, status="RETRYING", retry_count=retries,
                               error_message=str(exc), current_tax_type=current_tax,
                               last_processed_source_id=cursor,
                               records_processed=processed, records_overridden=overridden,
                               records_skipped=skipped, records_failed=failed)
                time.sleep(min(2 ** retries, 8))
                job["retry_count"] = retries
                continue
            with engine.begin() as conn:
                update_job(conn, job_id, worker_id, status="FAILED", retry_count=retries,
                           error_message=str(exc), current_tax_type=current_tax,
                           last_processed_source_id=cursor, records_processed=processed,
                           records_overridden=overridden, records_skipped=skipped,
                           records_failed=failed)
            return
        except Exception as exc:
            with engine.begin() as conn:
                update_job(conn, job_id, worker_id, status="FAILED", error_message=str(exc),
                           current_tax_type=current_tax, last_processed_source_id=cursor,
                           records_processed=processed, records_overridden=overridden,
                           records_skipped=skipped, records_failed=failed + 1)
            logger.exception("Invalid-TIN business-decision job failed: %s", job_id)
            return


def run_claimed_job(engine):
    ensure_schema(engine)
    job = claim_job(engine, worker_id=f"rba-{uuid.uuid4()}")
    if not job:
        return None
    process_job(engine, job)
    return job["job_id"]


def worker_loop(engine, poll_seconds=5):
    """Recover queued/stale jobs in a process-local daemon loop.

    Ownership is database-backed by ``worker_id``/``lease_until``; multiple
    web workers may run this loop safely because claims are row-locked.
    """
    while True:
        try:
            run_claimed_job(engine)
        except Exception:
            logger.exception("Invalid-TIN worker loop iteration failed")
        time.sleep(poll_seconds)
