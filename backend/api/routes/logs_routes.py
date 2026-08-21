# api/routes/logs_routes.py



from flask import Blueprint, jsonify, request
from sqlalchemy import text
from config.db_config import get_mysql_engine
import pandas as pd

logs_bp = Blueprint('logs', __name__)

_ALLOWED_PIPELINES = {'all', 'gst', 'cit', 'swt'}
_PIPELINE_ORDER = ('gst', 'cit', 'swt')


def _normalize_pipeline(raw_value):
    pipeline = (raw_value or 'all').strip().lower()
    if pipeline not in _ALLOWED_PIPELINES:
        return None
    return pipeline


def _invalid_pipeline_response():
    return jsonify({"error": "Invalid pipeline"}), 400


@logs_bp.route('/api/logs/uploads', methods=['GET'])
def get_upload_history():
    pipeline  = _normalize_pipeline(request.args.get('pipeline', 'all'))
    if pipeline is None:
        return _invalid_pipeline_response()

    page      = int(request.args.get('page', 1))
    per_page  = int(request.args.get('per_page', 50))
    offset    = (page - 1) * per_page
    try:
        engine = get_mysql_engine()
        params = {"limit": per_page, "offset": offset}
        if pipeline == 'all':
            query = text("SELECT * FROM upload_log ORDER BY uploaded_at DESC LIMIT :limit OFFSET :offset")
            count_query = text("SELECT COUNT(*) as total FROM upload_log")
        else:
            params["pipeline"] = pipeline.upper()
            query = text("SELECT * FROM upload_log WHERE tax_type = :pipeline ORDER BY uploaded_at DESC LIMIT :limit OFFSET :offset")
            count_query = text("SELECT COUNT(*) as total FROM upload_log WHERE tax_type = :pipeline")
        df = pd.read_sql(query, engine, params=params)
        total = pd.read_sql(count_query, engine, params=params)['total'].iloc[0]
        engine.dispose()
        return jsonify({
            "pipeline"      : pipeline,
            "page"          : page,
            "per_page"      : per_page,
            "total_records" : int(total),
            "total_pages"   : (int(total) + per_page - 1) // per_page,
            "results"       : df.to_dict(orient='records')
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@logs_bp.route('/api/logs/pipeline', methods=['GET'])
def get_pipeline_logs():
    pipeline = _normalize_pipeline(request.args.get('pipeline', 'all'))
    if pipeline is None:
        return _invalid_pipeline_response()

    page     = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    offset   = (page - 1) * per_page
    try:
        engine = get_mysql_engine()
        params = {"limit": per_page, "offset": offset}
        if pipeline == 'all':
            query = text("SELECT * FROM pipeline_log ORDER BY logged_at DESC LIMIT :limit OFFSET :offset")
            count_query = text("SELECT COUNT(*) as total FROM pipeline_log")
        else:
            params["pipeline_pattern"] = f"%{pipeline.upper()}%"
            query = text("SELECT * FROM pipeline_log WHERE tax_type LIKE :pipeline_pattern ORDER BY logged_at DESC LIMIT :limit OFFSET :offset")
            count_query = text("SELECT COUNT(*) as total FROM pipeline_log WHERE tax_type LIKE :pipeline_pattern")
        df = pd.read_sql(query, engine, params=params)
        total = pd.read_sql(count_query, engine, params=params)['total'].iloc[0]
        engine.dispose()
        return jsonify({
            "pipeline"      : pipeline,
            "page"          : page,
            "per_page"      : per_page,
            "total_records" : int(total),
            "total_pages"   : (int(total) + per_page - 1) // per_page,
            "results"       : df.to_dict(orient='records')
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@logs_bp.route('/api/logs/latest', methods=['GET'])
def get_latest_activity():
    try:
        engine  = get_mysql_engine()
        results = {}
        for p in _PIPELINE_ORDER:
            params = {
                "pipeline": p,
                "pipeline_pattern": f"%{p.upper()}%",
            }
            upload_df = pd.read_sql(
                text("SELECT * FROM upload_log WHERE tax_type = :pipeline ORDER BY uploaded_at DESC LIMIT 1"),
                engine,
                params=params,
            )
            pipeline_df = pd.read_sql(
                text("SELECT * FROM pipeline_log WHERE tax_type LIKE :pipeline_pattern ORDER BY logged_at DESC LIMIT 1"),
                engine,
                params=params,
            )
            results[p]  = {
                "latest_upload"   : upload_df.to_dict(orient='records')[0] if not upload_df.empty else None,
                "latest_pipeline" : pipeline_df.to_dict(orient='records')[0] if not pipeline_df.empty else None
            }
        engine.dispose()
        return jsonify(results), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
