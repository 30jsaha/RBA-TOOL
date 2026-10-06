"""Persistence-boundary integration for new GST/SWT/CIT source rows."""

from sqlalchemy import MetaData, Table

from utils.bulk_insert_utils import DEFAULT_INSERT_CHUNK_SIZE, sanitize_chunk_for_mysql, table_exists

from .repository import ensure_schema, get_invalid_tin
from .service import ensure_original_and_policy
from .tin import normalize_tin


def insert_with_business_decisions(df, table_name, tax_type, engine, *,
                                   chunksize=DEFAULT_INSERT_CHUNK_SIZE,
                                   progress_callback=None, run_id=None,
                                   user_id=None):
    """Insert source rows and FBD versions in one transaction per chunk.

    ``lastrowid`` is taken from each actual source INSERT; no ID inference is
    performed. The caller owns the existing financial-data lock.
    """
    ensure_schema(engine)
    if not table_exists(engine, table_name):
        df.head(0).to_sql(table_name, con=engine, if_exists="fail", index=False)
    table = Table(table_name, MetaData(), autoload_with=engine)
    total = int(len(df.index))
    inserted = 0
    for start in range(0, total, chunksize):
        end = min(start + chunksize, total)
        chunk = sanitize_chunk_for_mysql(df.iloc[start:end])
        with engine.begin() as conn:
            for record in chunk:
                record.pop("id", None)
                result = conn.execute(table.insert().values(**record))
                source_id = result.lastrowid
                if not source_id:
                    raise RuntimeError(f"{table_name} insert did not return source ID")
                source_row = dict(record)
                source_row["id"] = source_id
                source_row["user_id"] = source_row.get("user_id", user_id)
                tin_key = normalize_tin(source_row.get("tin"))
                invalid_row = get_invalid_tin(conn, tin_key) if tin_key else None
                ensure_original_and_policy(
                    conn, tax_type=tax_type, row=source_row,
                    invalid_row=invalid_row, run_id=run_id, actor_id=user_id,
                )
        inserted = end
        if progress_callback:
            progress_callback(inserted, total, (start // chunksize) + 1,
                              (total + chunksize - 1) // chunksize)
    return inserted
