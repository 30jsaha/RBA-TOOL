import math
import time
import threading
from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import MetaData, Table, text
from sqlalchemy.exc import OperationalError


DEFAULT_INSERT_CHUNK_SIZE = 1000


def mysql_safe_value(value):
    """
    Convert pandas/numpy values into MySQL-safe Python primitives.
    """

    # pandas missing values
    if pd.isna(value):
        return None

    # numpy scalar types -> native python
    if isinstance(value, np.integer):
        return int(value)

    if isinstance(value, np.floating):
        if math.isnan(value):
            return None
        return float(value)

    if isinstance(value, np.bool_):
        return bool(value)

    # pandas timestamp -> python datetime
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()

    # pandas timedelta
    if isinstance(value, pd.Timedelta):
        return str(value)

    return value


def sanitize_chunk_for_mysql(df):
    """
    Convert dataframe chunk to fully MySQL-safe values.
    Prevent any raw nan from reaching executemany().
    """

    records = []

    for row in df.to_dict(orient="records"):
        safe_row = {
            key: mysql_safe_value(value)
            for key, value in row.items()
        }
        records.append(safe_row)

    return records


def table_exists(engine, table_name: str) -> bool:
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT COUNT(*) "
                "FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :tbl"
            ),
            {"tbl": table_name},
        )
        return bool(result.scalar() or 0)


def get_table_columns(engine, table_name: str):
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT COLUMN_NAME "
                "FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :tbl "
                "ORDER BY ORDINAL_POSITION"
            ),
            {"tbl": table_name},
        )
        return [row[0] for row in result]


def chunked_multi_insert(
    df,
    table_name: str,
    engine,
    *,
    table_already_exists: bool,
    chunksize: int = DEFAULT_INSERT_CHUNK_SIZE,
    progress_callback=None,
    atomic: bool = False,
):
    total_rows = int(len(df.index))
    if total_rows <= 0:
        return 0

    total_chunks = int(math.ceil(total_rows / float(chunksize)))
    inserted_rows = 0

    def _is_retryable_operational_error(exc: Exception) -> bool:
        text_value = str(exc or "").lower()
        retry_markers = (
            "mysql server has gone away",
            "lost connection",
            "connectionreseterror",
            "forcibly closed by the remote host",
            "server has gone away",
        )
        return any(marker in text_value for marker in retry_markers)

    if not table_already_exists:
        # Create the table schema once using the DataFrame columns, then switch
        # to SQLAlchemy Core bulk inserts for all row writes.
        df.head(0).to_sql(table_name, con=engine, if_exists="fail", index=False)

    table = Table(table_name, MetaData(), autoload_with=engine)
    rows_before = None
    try:
        with engine.connect() as conn:
            rows_before = conn.execute(text(f"SELECT COUNT(*) FROM `{table_name}`")).scalar()
    except Exception:
        rows_before = None
    print("=" * 100)
    print("chunked_multi_insert START")
    print("Timestamp:", datetime.utcnow().isoformat())
    print("Thread ID:", threading.get_ident())
    print("Table:", table_name)
    print("Rows before:", rows_before)
    print("Rows to insert:", total_rows)
    print("Chunks:", total_chunks)
    print("=" * 100)

    def _insert_chunks(conn):
        nonlocal inserted_rows, table

        for chunk_index, start in enumerate(range(0, total_rows, chunksize), start=1):
            end = min(start + chunksize, total_rows)
            chunk_df = df.iloc[start:end]
            last_error = None
            print(
                f"[chunked_multi_insert] Chunk {chunk_index}/{total_chunks} | "
                f"Thread ID: {threading.get_ident()} | Rows: {len(chunk_df)}"
            )

            for attempt in range(2):
                try:
                    chunk_records = sanitize_chunk_for_mysql(chunk_df)
                    for row in chunk_records:
                        for key, value in row.items():
                            if isinstance(value, float) and math.isnan(value):
                                raise ValueError(
                                    f"Raw NaN detected before MySQL insert. Column={key}"
                                )
                    conn.execute(table.insert(), chunk_records)
                    last_error = None
                    break
                except OperationalError as exc:
                    last_error = exc
                    if atomic:
                        raise
                    if attempt == 0 and _is_retryable_operational_error(exc):
                        print(
                            f"Retrying chunk {chunk_index}/{total_chunks} due to lost connection"
                        )
                        try:
                            engine.dispose()
                        except Exception:
                            pass
                        time.sleep(3)
                        table = Table(table_name, MetaData(), autoload_with=engine)
                        continue
                    raise

            if last_error is not None:
                raise last_error

            inserted_rows = end
            print(f"Chunk {chunk_index}/{total_chunks} inserted")
            if progress_callback is not None:
                progress_callback(inserted_rows, total_rows, chunk_index, total_chunks)

    if atomic:
        with engine.begin() as conn:
            _insert_chunks(conn)
    else:
        for chunk_index, start in enumerate(range(0, total_rows, chunksize), start=1):
            end = min(start + chunksize, total_rows)
            chunk_df = df.iloc[start:end]
            last_error = None
            print(
                f"[chunked_multi_insert] Chunk {chunk_index}/{total_chunks} | "
                f"Thread ID: {threading.get_ident()} | Rows: {len(chunk_df)}"
            )

            for attempt in range(2):
                try:
                    chunk_records = sanitize_chunk_for_mysql(chunk_df)
                    for row in chunk_records:
                        for key, value in row.items():
                            if isinstance(value, float) and math.isnan(value):
                                raise ValueError(
                                    f"Raw NaN detected before MySQL insert. Column={key}"
                                )
                    with engine.begin() as conn:
                        conn.execute(table.insert(), chunk_records)
                    last_error = None
                    break
                except OperationalError as exc:
                    last_error = exc
                    if attempt == 0 and _is_retryable_operational_error(exc):
                        print(
                            f"Retrying chunk {chunk_index}/{total_chunks} due to lost connection"
                        )
                        try:
                            engine.dispose()
                        except Exception:
                            pass
                        time.sleep(3)
                        table = Table(table_name, MetaData(), autoload_with=engine)
                        continue
                    raise

            if last_error is not None:
                raise last_error

            inserted_rows = end
            print(f"Chunk {chunk_index}/{total_chunks} inserted")
            if progress_callback is not None:
                progress_callback(inserted_rows, total_rows, chunk_index, total_chunks)

    rows_after = None
    try:
        with engine.connect() as conn:
            rows_after = conn.execute(text(f"SELECT COUNT(*) FROM `{table_name}`")).scalar()
    except Exception:
        rows_after = None
    print("=" * 100)
    print("chunked_multi_insert END")
    print("Timestamp:", datetime.utcnow().isoformat())
    print("Thread ID:", threading.get_ident())
    print("Table:", table_name)
    print("Rows before:", rows_before)
    print("Rows after:", rows_after)
    print("Rows inserted:", inserted_rows)
    print("=" * 100)
    return inserted_rows
