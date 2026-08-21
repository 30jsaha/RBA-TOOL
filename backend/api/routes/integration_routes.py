# ══════════════════════════════════════════════════════════════
#  api/routes/integration_routes.py
#  POST /api/integration/run
#  Runs all three pipelines in parallel, merges by TIN
# ══════════════════════════════════════════════════════════════

import os
import sys
from flask import Blueprint, request, jsonify
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config.db_config import get_mysql_engine

integration_bp = Blueprint('integration', __name__)


@integration_bp.route('/api/integration/logs', methods=['GET'])
def get_logs():
    """Return recent pipeline step logs from MySQL."""
    try:
        import pandas as pd
        tax_type = request.args.get('tax_type', None)
        limit    = int(request.args.get('limit', 100))

        engine = get_mysql_engine()
        if tax_type:
            query = f"SELECT * FROM pipeline_log WHERE tax_type = '{tax_type.upper()}' ORDER BY logged_at DESC LIMIT {limit}"
        else:
            query = f"SELECT * FROM pipeline_log ORDER BY logged_at DESC LIMIT {limit}"     

        with engine.connect() as conn:
            df = pd.read_sql(query, conn)
        engine.dispose()        

        return jsonify(df.to_dict(orient='records')), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@integration_bp.route('/api/uploads/history', methods=['GET'])
def get_upload_history():
    """Return upload history from MySQL."""
    try:
        import pandas as pd
        tax_type = request.args.get('tax_type', None)
        limit    = int(request.args.get('limit', 50))

        engine = get_mysql_engine()
        query  = 'SELECT * FROM upload_log'
        if tax_type:
            query += f" WHERE tax_type = '{tax_type.upper()}'"
        query += f' ORDER BY uploaded_at DESC LIMIT {limit}'

        with engine.connect() as conn:
            df = pd.read_sql(query, conn)
        engine.dispose()

        return jsonify(df.to_dict(orient='records')), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500