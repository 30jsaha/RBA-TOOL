from flask import Blueprint
from flask_jwt_extended import jwt_required
from sqlalchemy import inspect, text

from api.extensions import db
from config.db_config import get_mysql_engine

bp = Blueprint("admin", __name__)

@bp.post("/reset-db")
@jwt_required()
def reset_db():
    tables = [
        "upload_validation_errors",
        "upload_validation_summary",
        "fraud_justification_history",
        "process_temp_records",
        "multi_tax_integration_results",
        "upload_conflicts",
        "upload_differences",
        "agg_cit",
        "agg_gst",
        "agg_swt",
        "cit_fraud_justification",
        "gst_fraud_justification",
        "swt_fraud_justification",
        "upload_log",
        "upload_history",
        "pipeline_log",
    ]

    reset_engine = None

    try:
        try:
            db.session.rollback()
            db.session.remove()
        except Exception:
            pass

        reset_engine = get_mysql_engine(force_new=True)
        inspector = inspect(reset_engine)
        existing_tables = set(inspector.get_table_names())

        with reset_engine.begin() as conn:
            try:
                conn.execute(text("SET SESSION innodb_lock_wait_timeout = 30"))
            except Exception:
                pass

            try:
                conn.execute(text("SET SESSION lock_wait_timeout = 30"))
            except Exception:
                pass

            conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
            try:
                for table in tables:
                    if table not in existing_tables:
                        continue

                    conn.execute(text(f"DELETE FROM `{table}`"))

                    try:
                        conn.execute(text(f"ALTER TABLE `{table}` AUTO_INCREMENT = 1"))
                    except Exception:
                        # Tables without AUTO_INCREMENT do not need a reset.
                        pass
            finally:
                conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))

        return {
            "status": "success",
            "message": "Database reset completed successfully",
        }, 200
    except Exception as e:
        try:
            db.session.rollback()
            db.session.remove()
        except Exception:
            pass
        return {
            "status": "error",
            "message": str(e),
        }, 500
    finally:
        try:
            db.session.rollback()
            db.session.remove()
        except Exception:
            pass

        if reset_engine is not None:
            try:
                reset_engine.dispose()
            except Exception:
                pass
