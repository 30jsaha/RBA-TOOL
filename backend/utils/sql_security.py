# ══════════════════════════════════════════════════════════════
#  backend/utils/sql_security.py
#  
#  Centralized SQL security validation and parameter handling.
#  Ensures all dynamic SQL construction is properly validated.
# ══════════════════════════════════════════════════════════════

from typing import Optional, Set, Dict, Any, List
from flask import jsonify


# ─────────────────────────────────────────────────────────────
#  ALLOWLISTS - Centralized Validation
# ─────────────────────────────────────────────────────────────

# Tax types - used for table selection and filtering
ALLOWED_TAX_TYPES = {
    "gst",
    "swt", 
    "cit"
}

ALLOWED_TAX_TYPES_UPPER = {t.upper() for t in ALLOWED_TAX_TYPES}

# Primary fraud justification tables (one per tax type)
FRAUD_JUSTIFICATION_TABLES = {
    "gst": "gst_fraud_justification",
    "swt": "swt_fraud_justification",
    "cit": "cit_fraud_justification"
}

# Flagged audit record tables (one per tax type)
FLAGGED_AUDIT_TABLES = {
    "gst": "flagged_audit_records",
    "swt": "flagged_audit_records_swt",
    "cit": "flagged_audit_records_cit"
}

# All known internal tables (safe for identifier validation)
KNOWN_TABLES = {
    # Fraud justification tables
    "gst_fraud_justification",
    "swt_fraud_justification",
    "cit_fraud_justification",
    # Flagged audit tables
    "flagged_audit_records",
    "flagged_audit_records_swt",
    "flagged_audit_records_cit",
    # Conflict management
    "upload_conflicts",
    "fraud_justification_history",
    # Registration
    "tin_registration_mst",
    # Aggregation tables
    "agg_cit",
    "agg_gst",
    "agg_swt",
    # Multi-tax integration
    "multi_tax_integration_results",
    "multi_tax_integration_results_new",
    # Logging
    "upload_log",
    "pipeline_log",
    # User/auth tables
    "users",
    "upload_history",
}

# Sortable columns by table (for ORDER BY validation)
SORTABLE_COLUMNS_BY_TABLE = {
    "gst_fraud_justification": {
        "tin", "tax_period_year", "tax_period_month", "taxpayer_name", 
        "total_sales_income", "gst_payable", "gst_refundable", "is_fraud",
        "predicted_fraud", "assessment_number", "id", "created_at", "updated_at"
    },
    "swt_fraud_justification": {
        "tin", "tax_period_year", "tax_period_month", "taxpayer_name",
        "total_salary_wages_paid", "swt_payable", "predicted_fraud", 
        "assessment_number", "id", "created_at", "updated_at"
    },
    "cit_fraud_justification": {
        "tin", "tax_period_year", "taxpayer_name",
        "total_gross_income", "taxable_income", "predicted_fraud",
        "assessment_number", "id", "created_at", "updated_at"
    },
    "upload_conflicts": {
        "id", "tax_type", "tin", "taxpayer_name", "field_name",
        "status", "created_at", "source_record_id"
    },
    "upload_history": {
        "id", "tax_type", "filename", "uploaded_at", "status", "row_count"
    },
    "pipeline_log": {
        "id", "tax_type", "step_name", "status", "logged_at", "run_id"
    },
}

# Valid sort directions
SORT_DIRECTIONS = {"asc", "desc"}


# ─────────────────────────────────────────────────────────────
#  VALIDATION FUNCTIONS
# ─────────────────────────────────────────────────────────────

def validate_taxtype(taxtype_input: Optional[str], 
                     default: str = "gst") -> str:
    """
    Validate and normalize tax type from user input.
    
    Args:
        taxtype_input: User-provided tax type string
        default: Default tax type if input is invalid
        
    Returns:
        Validated lowercase tax type ("gst", "swt", or "cit")
        
    Raises:
        ValueError: If input is not None/empty and not in ALLOWED_TAX_TYPES
    """
    if not taxtype_input or isinstance(taxtype_input, str) and not taxtype_input.strip():
        return default.lower()
    
    normalized = str(taxtype_input).strip().lower()
    
    if normalized not in ALLOWED_TAX_TYPES:
        raise ValueError(f"Invalid tax type: {taxtype_input}. Must be one of {ALLOWED_TAX_TYPES}")
    
    return normalized


def get_fraud_justification_table(taxtype: str) -> str:
    """
    Get the fraud justification table name for a tax type.
    
    Args:
        taxtype: Validated tax type ("gst", "swt", or "cit")
        
    Returns:
        Table name (e.g., "gst_fraud_justification")
        
    Raises:
        ValueError: If tax type is invalid
    """
    normalized = validate_taxtype(taxtype)
    table = FRAUD_JUSTIFICATION_TABLES.get(normalized)
    if not table:
        raise ValueError(f"No fraud justification table for tax type: {taxtype}")
    return table


def get_flagged_audit_table(taxtype: str) -> str:
    """
    Get the flagged audit records table name for a tax type.
    
    Args:
        taxtype: Validated tax type ("gst", "swt", or "cit")
        
    Returns:
        Table name (e.g., "flagged_audit_records")
        
    Raises:
        ValueError: If tax type is invalid
    """
    normalized = validate_taxtype(taxtype)
    table = FLAGGED_AUDIT_TABLES.get(normalized)
    if not table:
        raise ValueError(f"No flagged audit table for tax type: {taxtype}")
    return table


def validate_table_name(table_name: str) -> str:
    """
    Validate that a table name is in the allowlist.
    
    Args:
        table_name: Table name to validate
        
    Returns:
        Validated table name
        
    Raises:
        ValueError: If table name is not in allowlist
    """
    normalized = str(table_name).strip()
    if normalized not in KNOWN_TABLES:
        raise ValueError(f"Invalid table name: {table_name}")
    return normalized


def validate_sort_field(table_name: str, field_name: str) -> str:
    """
    Validate that a sort field is allowed for the given table.
    
    Args:
        table_name: Table being sorted
        field_name: Column name to sort by
        
    Returns:
        Validated field name
        
    Raises:
        ValueError: If field is not in sortable columns for table
    """
    normalized_field = str(field_name).strip()
    if not normalized_field:
        raise ValueError("Sort field cannot be empty")
    
    allowed_fields = SORTABLE_COLUMNS_BY_TABLE.get(table_name, set())
    if normalized_field.lower() not in {f.lower() for f in allowed_fields}:
        raise ValueError(
            f"Invalid sort field '{field_name}' for table '{table_name}'. "
            f"Allowed: {', '.join(sorted(allowed_fields))}"
        )
    
    return normalized_field


def validate_sort_direction(direction: Optional[str]) -> str:
    """
    Validate sort direction (ASC or DESC).
    
    Args:
        direction: Sort direction string
        
    Returns:
        Validated direction ("asc" or "desc")
        
    Raises:
        ValueError: If direction is invalid
    """
    if not direction:
        return "asc"
    
    normalized = str(direction).strip().lower()
    if normalized not in SORT_DIRECTIONS:
        raise ValueError(f"Invalid sort direction: {direction}. Must be 'asc' or 'desc'")
    
    return normalized


def validate_pagination(page: Any = None, per_page: Any = None,
                       default_per_page: int = 50,
                       max_per_page: int = 1000) -> tuple:
    """
    Validate and normalize pagination parameters.
    
    Args:
        page: Page number (1-indexed)
        per_page: Records per page
        default_per_page: Default per_page if not provided
        max_per_page: Maximum allowed per_page
        
    Returns:
        Tuple of (page, per_page) - both integers, guaranteed valid
        
    Raises:
        ValueError: If parameters cannot be converted to valid integers
    """
    try:
        if page is None or page == "":
            page_num = 1
        else:
            page_num = int(page)
            if page_num < 1:
                page_num = 1
    except (ValueError, TypeError):
        page_num = 1
    
    try:
        if per_page is None or per_page == "":
            per_page_num = default_per_page
        else:
            per_page_num = int(per_page)
            if per_page_num < 1:
                per_page_num = default_per_page
            elif per_page_num > max_per_page:
                per_page_num = max_per_page
    except (ValueError, TypeError):
        per_page_num = default_per_page
    
    return page_num, per_page_num


def validate_year(year: Any) -> Optional[int]:
    """
    Validate a year parameter.
    
    Args:
        year: Year value to validate
        
    Returns:
        Validated year as integer, or None if invalid
    """
    try:
        if year is None or year == "":
            return None
        year_int = int(year)
        if 1900 <= year_int <= 2999:
            return year_int
        return None
    except (ValueError, TypeError):
        return None


def validate_month(month: Any) -> Optional[int]:
    """
    Validate a month parameter (1-12).
    
    Args:
        month: Month value to validate
        
    Returns:
        Validated month as integer, or None if invalid
    """
    try:
        if month is None or month == "":
            return None
        month_int = int(month)
        if 1 <= month_int <= 12:
            return month_int
        return None
    except (ValueError, TypeError):
        return None


def validate_id(id_value: Any) -> Optional[int]:
    """
    Validate an ID parameter (positive integer).
    
    Args:
        id_value: ID value to validate
        
    Returns:
        Validated ID as integer, or None if invalid
    """
    try:
        if id_value is None or id_value == "":
            return None
        id_int = int(id_value)
        if id_int > 0:
            return id_int
        return None
    except (ValueError, TypeError):
        return None


# ─────────────────────────────────────────────────────────────
#  RESPONSE HELPERS
# ─────────────────────────────────────────────────────────────

def error_invalid_parameter(param_name: str, reason: str = "", details: str = "") -> tuple:
    """
    Return a standardized 400 response for invalid parameter.
    
    Args:
        param_name: Name of the invalid parameter
        reason: Brief reason why it's invalid
        details: Additional details
        
    Returns:
        (jsonify response, 400)
    """
    message = f"Invalid parameter: {param_name}"
    if reason:
        message += f" - {reason}"
    
    response = {"status": "error", "message": message}
    if details:
        response["details"] = details
    
    return jsonify(response), 400


def error_invalid_taxtype(taxtype: Any = "") -> tuple:
    """Return a standardized 400 response for invalid tax type."""
    return error_invalid_parameter(
        "taxtype",
        f"Invalid tax type '{taxtype}'",
        f"Must be one of: {', '.join(sorted(ALLOWED_TAX_TYPES))}"
    )
