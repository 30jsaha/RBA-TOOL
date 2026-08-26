from flask import Blueprint, request, jsonify
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
            if hasattr(db, "session") and db.session is not None:
                db.session.remove()
            if hasattr(db, "_Session") and db._Session is not None:
                db._Session.remove()
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

                    try:
                        conn.execute(text(f"DELETE FROM `{table}`"))
                    except Exception as err:
                        print(f"[RESET_DB] Failed DELETE on `{table}`: {err}")

                    try:
                        conn.execute(text(f"ALTER TABLE `{table}` AUTO_INCREMENT = 1"))
                    except Exception:
                        pass
            finally:
                try:
                    conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
                except Exception:
                    pass

        return jsonify({
            "status": "success",
            "message": "Database reset completed successfully",
        }), 200
    except Exception as e:
        import traceback
        print(f"[RESET_DB ERROR]\n{traceback.format_exc()}")
        try:
            if hasattr(db, "session") and db.session is not None:
                db.session.remove()
        except Exception:
            pass
        return jsonify({
            "status": "error",
            "message": str(e),
        }), 500
    finally:
        try:
            if hasattr(db, "session") and db.session is not None:
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
        return jsonify({
            "success": False,
            "message": "Confirmation is required to clean temporary files",
        }), 400

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

        return jsonify(response), 200
    except Exception as exc:
        return jsonify({
            "success": False,
            "message": str(exc),
        }), 500
