# ══════════════════════════════════════════════════════════════
#  api/routes/integration_routes.py
#  POST /api/integration/run
#  Runs all three pipelines in parallel, merges by TIN
# ══════════════════════════════════════════════════════════════

import os
import sys
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from sqlalchemy import text
from utils.data_access import ownership_clause
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config.db_config import get_mysql_engine

integration_bp = Blueprint('integration', __name__)


@integration_bp.route('/api/integration/logs', methods=['GET'])
@jwt_required()
def get_logs():
    """Return recent pipeline step logs from MySQL."""
    try:
        import pandas as pd
        tax_type = request.args.get('tax_type', None)
        limit    = int(request.args.get('limit', 100))

        engine = get_mysql_engine()
        scope, scope_params = ownership_clause("pipeline_log")
        params = dict(scope_params)
        if tax_type:
            query = text(f"SELECT * FROM pipeline_log WHERE tax_type = :tax_type AND {scope} ORDER BY logged_at DESC LIMIT :limit")
            params.update({"tax_type": tax_type.upper(), "limit": limit})
        else:
            query = text(f"SELECT * FROM pipeline_log WHERE {scope} ORDER BY logged_at DESC LIMIT :limit")
            params["limit"] = limit

        with engine.connect() as conn:
            df = pd.read_sql(query, conn, params=params)
        engine.dispose()        

        return jsonify(df.to_dict(orient='records')), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@integration_bp.route('/api/uploads/history', methods=['GET'])
@jwt_required()
def get_upload_history():
    """Return upload history from MySQL."""
    try:
        import pandas as pd
        tax_type = request.args.get('tax_type', None)
        limit    = int(request.args.get('limit', 50))

        engine = get_mysql_engine()
        scope, scope_params = ownership_clause("upload_log")
        query  = 'SELECT * FROM upload_log WHERE ' + scope
        params = dict(scope_params)
        if tax_type:
            query += ' AND tax_type = :tax_type'
            params['tax_type'] = tax_type.upper()
        query += ' ORDER BY uploaded_at DESC LIMIT :limit'
        params['limit'] = limit

        with engine.connect() as conn:
            df = pd.read_sql(text(query), conn, params=params)
        engine.dispose()

        return jsonify(df.to_dict(orient='records')), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500
