from flask import Blueprint, request
from flask_jwt_extended import jwt_required
from sqlalchemy import inspect, text

from api.extensions import db
from config.db_config import get_mysql_engine
from utils.file_security import cleanup_all_final_output_directories
from utils.rbac import role_required

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
            if hasattr(db, "engine") and db.engine is not None:
                db.engine.dispose()
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


@bp.post("/cleanup-temp-files")
@jwt_required()
@role_required(["ADMIN"])
def cleanup_temp_files():
    data = request.get_json(silent=True) or {}
    if data.get("confirm") is not True:
        return {
            "success": False,
            "message": "Confirmation is required to clean temporary files",
        }, 400

    try:
        report = cleanup_all_final_output_directories()
        failed = report.get("failed") or []

        response = {
            "success": True,
            "message": (
                "Cleanup completed with warnings"
                if failed
                else "Temporary files cleaned successfully"
            ),
            "deleted": report.get("deleted", {}),
            "total_deleted": int(report.get("total_deleted", 0) or 0),
        }
        if failed:
            response["failed"] = failed

        return response, 200
    except Exception as exc:
        return {
            "success": False,
            "message": str(exc),
        }, 500
