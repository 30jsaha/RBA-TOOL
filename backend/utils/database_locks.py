"""MySQL named locks used to coordinate financial-data maintenance jobs."""

from contextlib import contextmanager

from sqlalchemy import text


FINANCIAL_DATA_LOCK = "rba_financial_data_write_lock"


class DatabaseMaintenanceBusy(RuntimeError):
    """Raised when a reset or financial-data write would overlap another job."""


@contextmanager
def financial_data_lock(engine, *, timeout_seconds: int = 0):
    """Hold the cross-process lock for an insert, refresh, or reset operation.

    MySQL named locks are connection-scoped, so this deliberately keeps a
    dedicated connection open while the caller performs its work. The caller's
    own database transactions can still use the supplied engine normally.
    """
    connection = engine.connect()
    acquired = False
    try:
        acquired = connection.execute(
            text("SELECT GET_LOCK(:lock_name, :timeout_seconds)"),
            {
                "lock_name": FINANCIAL_DATA_LOCK,
                "timeout_seconds": max(0, int(timeout_seconds)),
            },
        ).scalar() == 1
        if not acquired:
            raise DatabaseMaintenanceBusy(
                "Another database reset, upload insert, or MultiTax refresh is still running. "
                "Wait for it to finish and try again."
            )
        yield
    finally:
        if acquired:
            try:
                connection.execute(
                    text("SELECT RELEASE_LOCK(:lock_name)"),
                    {"lock_name": FINANCIAL_DATA_LOCK},
                )
            except Exception:
                pass
        connection.close()
