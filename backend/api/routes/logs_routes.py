# api/routes/logs_routes.py



from flask import Blueprint, jsonify, request
from sqlalchemy import text
from config.db_config import get_mysql_engine
from flask_jwt_extended import jwt_required
from utils.data_access import ownership_clause
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
@jwt_required()
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
        scope, scope_params = ownership_clause("upload_log")
        params.update(scope_params)
        if pipeline == 'all':
            query = text(f"SELECT * FROM upload_log WHERE {scope} ORDER BY uploaded_at DESC LIMIT :limit OFFSET :offset")
            count_query = text(f"SELECT COUNT(*) as total FROM upload_log WHERE {scope}")
        else:
            params["pipeline"] = pipeline.upper()
            query = text(f"SELECT * FROM upload_log WHERE tax_type = :pipeline AND {scope} ORDER BY uploaded_at DESC LIMIT :limit OFFSET :offset")
            count_query = text(f"SELECT COUNT(*) as total FROM upload_log WHERE tax_type = :pipeline AND {scope}")
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
@jwt_required()
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
        scope, scope_params = ownership_clause("pipeline_log")
        params.update(scope_params)
        if pipeline == 'all':
            query = text(f"SELECT * FROM pipeline_log WHERE {scope} ORDER BY logged_at DESC LIMIT :limit OFFSET :offset")
            count_query = text(f"SELECT COUNT(*) as total FROM pipeline_log WHERE {scope}")
        else:
            params["pipeline_pattern"] = f"%{pipeline.upper()}%"
            query = text(f"SELECT * FROM pipeline_log WHERE tax_type LIKE :pipeline_pattern AND {scope} ORDER BY logged_at DESC LIMIT :limit OFFSET :offset")
            count_query = text(f"SELECT COUNT(*) as total FROM pipeline_log WHERE tax_type LIKE :pipeline_pattern AND {scope}")
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
@jwt_required()
def get_latest_activity():
    try:
        engine  = get_mysql_engine()
        results = {}
        scope, scope_params = ownership_clause("upload_log")
        pipeline_scope, pipeline_scope_params = ownership_clause("pipeline_log")
        for p in _PIPELINE_ORDER:
            params = {
                "pipeline": p,
                "pipeline_pattern": f"%{p.upper()}%",
            }
            upload_df = pd.read_sql(
                text(f"SELECT * FROM upload_log WHERE tax_type = :pipeline AND {scope} ORDER BY uploaded_at DESC LIMIT 1"),
                engine,
                params={**params, **scope_params},
            )
            pipeline_df = pd.read_sql(
                text(f"SELECT * FROM pipeline_log WHERE tax_type LIKE :pipeline_pattern AND {pipeline_scope} ORDER BY logged_at DESC LIMIT 1"),
                engine,
                params={**params, **pipeline_scope_params},
            )
            results[p]  = {
                "latest_upload"   : upload_df.to_dict(orient='records')[0] if not upload_df.empty else None,
                "latest_pipeline" : pipeline_df.to_dict(orient='records')[0] if not pipeline_df.empty else None
            }
        engine.dispose()
        return jsonify(results), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
