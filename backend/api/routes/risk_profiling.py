from flask import Blueprint, jsonify, request, current_app
from flask_jwt_extended import jwt_required
from sqlalchemy import text

from ..extensions import db
from .dashboard_common import get_date_filter

bp = Blueprint("risk_profiling", __name__, url_prefix="/api/risk-profiling")


@bp.get("/gst-sales-comparison")
@jwt_required()
def gst_sales_comparison():
    """
    Returns sales comparison grouped by industry & year (or month for GST/SWT).
    Frontend calls this for multiple `taxtype` values including `cit`.
    Response format matches old-backend:
      { "group_by": "...", "data": [...] }
    """
    group_by = (request.args.get("group_by") or "year").lower()
    taxtype = (request.args.get("taxtype") or "gst").lower()

    try:
        if taxtype == "gst":
            date_filter, date_params = get_date_filter(
                column_year="pr.tax_period_year",
                column_month="pr.tax_period_month",
            )

            if group_by == "month":
                sql = f"""
                    SELECT
                        COALESCE(NULLIF(trm.enterpriseactivity, ''), 'Unknown') AS industry,
                        pr.tax_period_year AS year,
                        pr.tax_period_month AS month,
                        SUM(COALESCE(pr.total_sales_income, 0)) AS total_sales_income,
                        SUM(COALESCE(pr.gst_taxable_sales, 0)) AS gst_taxable_sales,
                        COUNT(DISTINCT pr.tin) AS taxpayers
                    FROM gst_fraud_justification pr
                    LEFT JOIN tin_registration_mst trm
                        ON TRIM(CAST(pr.tin AS CHAR(20))) COLLATE utf8mb4_unicode_ci
                         = TRIM(trm.tin) COLLATE utf8mb4_unicode_ci
                    WHERE ({date_filter})
                    GROUP BY industry, pr.tax_period_year, pr.tax_period_month
                    ORDER BY industry, pr.tax_period_year, pr.tax_period_month
                """
            else:
                sql = f"""
                    SELECT
                        COALESCE(NULLIF(trm.enterpriseactivity, ''), 'Unknown') AS industry,
                        pr.tax_period_year AS year,
                        SUM(COALESCE(pr.total_sales_income, 0)) AS total_sales_income,
                        SUM(COALESCE(pr.gst_taxable_sales, 0)) AS gst_taxable_sales,
                        COUNT(DISTINCT pr.tin) AS taxpayers
                    FROM gst_fraud_justification pr
                    LEFT JOIN tin_registration_mst trm
                        ON TRIM(CAST(pr.tin AS CHAR(20))) COLLATE utf8mb4_unicode_ci
                         = TRIM(trm.tin) COLLATE utf8mb4_unicode_ci
                    WHERE ({date_filter})
                    GROUP BY industry, pr.tax_period_year
                    ORDER BY industry, pr.tax_period_year
                """

            rows = db.session.execute(text(sql), date_params).fetchall()

        elif taxtype == "swt":
            date_filter, date_params = get_date_filter(
                column_year="pr.tax_period_year",
                column_month="pr.tax_period_month",
            )

            if group_by == "month":
                sql = f"""
                    SELECT
                        COALESCE(NULLIF(trm.enterpriseactivity, ''), 'Unknown') AS industry,
                        pr.tax_period_year AS year,
                        pr.tax_period_month AS month,
                        SUM(COALESCE(pr.total_salary_wages_paid, 0)) AS total_sales_income,
                        SUM(COALESCE(pr.total_swt_tax_deducted, 0)) AS gst_taxable_sales,
                        COUNT(DISTINCT pr.tin) AS taxpayers
                    FROM swt_fraud_justification pr
                    LEFT JOIN tin_registration_mst trm
                        ON TRIM(CAST(pr.tin AS CHAR(20))) COLLATE utf8mb4_unicode_ci
                         = TRIM(trm.tin) COLLATE utf8mb4_unicode_ci
                    WHERE ({date_filter})
                    GROUP BY industry, pr.tax_period_year, pr.tax_period_month
                    ORDER BY industry, pr.tax_period_year, pr.tax_period_month
                """
            else:
                sql = f"""
                    SELECT
                        COALESCE(NULLIF(trm.enterpriseactivity, ''), 'Unknown') AS industry,
                        pr.tax_period_year AS year,
                        SUM(COALESCE(pr.total_salary_wages_paid, 0)) AS total_sales_income,
                        SUM(COALESCE(pr.total_swt_tax_deducted, 0)) AS gst_taxable_sales,
                        COUNT(DISTINCT pr.tin) AS taxpayers
                    FROM swt_fraud_justification pr
                    LEFT JOIN tin_registration_mst trm
                        ON TRIM(CAST(pr.tin AS CHAR(20))) COLLATE utf8mb4_unicode_ci
                         = TRIM(trm.tin) COLLATE utf8mb4_unicode_ci
                    WHERE ({date_filter})
                    GROUP BY industry, pr.tax_period_year
                    ORDER BY industry, pr.tax_period_year
                """

            rows = db.session.execute(text(sql), date_params).fetchall()

        elif taxtype == "cit":
            # New-backend uses `cit_fraud_justification` (no month column).
            # Keep response shape stable for the frontend.
            date_filter, date_params = get_date_filter(
                column_year="pr.tax_period_year",
                column_month=None,
            )

            sql = f"""
                SELECT
                    COALESCE(NULLIF(trm.enterpriseactivity, ''), 'Unknown') AS industry,
                    pr.tax_period_year AS year,
                    SUM(COALESCE(pr.total_gross_income, 0)) AS total_sales_income,
                    SUM(COALESCE(pr.total_gross_income, 0) - COALESCE(pr.cost_of_goods_sold, 0)) AS gst_taxable_sales,
                    COUNT(DISTINCT pr.tin) AS taxpayers
                FROM cit_fraud_justification pr
                LEFT JOIN tin_registration_mst trm
                    ON TRIM(pr.tin) COLLATE utf8mb4_unicode_ci = TRIM(trm.tin) COLLATE utf8mb4_unicode_ci
                WHERE ({date_filter})
                GROUP BY industry, pr.tax_period_year
                ORDER BY industry, pr.tax_period_year
            """

            rows = db.session.execute(text(sql), date_params).fetchall()

        else:
            return jsonify({"error": "Invalid taxtype"}), 400

        data = []
        for r in rows:
            item = {
                "industry": getattr(r, "industry", None),
                "year": getattr(r, "year", None),
                "total_sales_income": float(getattr(r, "total_sales_income", 0) or 0),
                "gst_taxable_sales": float(getattr(r, "gst_taxable_sales", 0) or 0),
                "taxpayers": int(getattr(r, "taxpayers", 0) or 0),
            }
            if group_by == "month" and hasattr(r, "month"):
                item["month"] = getattr(r, "month")
            data.append(item)

        return jsonify({"group_by": group_by, "data": data})

    except Exception as e:
        current_app.logger.exception(e)
        return jsonify({"error": str(e)}), 500
