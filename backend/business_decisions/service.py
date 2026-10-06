"""Business decision persistence service."""

import json
from datetime import datetime

from sqlalchemy import text

from .policy import ACTIVE, INACTIVE, NORMAL, evaluate_business_decision, evaluate_disabled_result
from .repository import create_version, get_current, get_invalid_tin, source_table
from .tin import normalize_tin


def _source_from_row(tax_type, row):
    return {
        "tax_type": tax_type,
        "source_record_id": int(row["id"]),
        "source_table": source_table(tax_type),
        "tin_original": row.get("tin"),
        "tin_key": normalize_tin(row.get("tin")),
        "taxpayer_name_at_decision": row.get("taxpayer_name") or row.get("taxpayer"),
        "tax_period_year": int(row.get("tax_period_year") or 0),
        "tax_period_month": row.get("tax_period_month"),
        "upload_batch_id": row.get("upload_batch_id"),
        "source_user_id": row.get("user_id"),
    }


def _original_from_row(tax_type, row):
    predicted = row.get("predicted_fraud") or "Non-Fraud"
    evidence = {}
    if tax_type == "GST":
        evidence = {key: row.get(key) for key in (
            "deduct_input_credits_violation", "invalid_gst_refundable",
            "fraud_output_debits_no_tax", "misreported_zero_rated_sales",
            "overstated_zero_rated_sales", "non_reported_taxable_sales",
            "fraud_incomplete_gst_returns", "non_filing_gst",
            "sales_drop_more_than_50_percent", "fraud_multiple_refund_claims_6_months"
        ) if key in row}
    return {
        "original_ml_result": str(predicted),
        "original_rule_result": str(row.get("is_fraud_rule" if tax_type == "SWT" else "is_fraud") or "") or None,
        "original_predicted_fraud": row.get("predicted_fraud"),
        "original_is_fraud": row.get("is_fraud"),
        "original_is_fraud_rule": row.get("is_fraud_rule"),
        "original_rules_violated": row.get("rules_violated"),
        "original_fraud_probability": row.get("fraud_probability"),
        "original_explanation": row.get("explanation"),
        "original_justification": row.get("Justification"),
        "original_rule_evidence_json": evidence,
        "original_source_metadata_json": {"tax_type": tax_type},
    }


def _original_from_current(current, fallback):
    """Use the immutable FBD snapshot, never a policy-projected source row."""
    original = dict(fallback)
    for key in (
        "original_ml_result", "original_rule_result", "original_predicted_fraud",
        "original_is_fraud", "original_is_fraud_rule", "original_rules_violated",
        "original_fraud_probability", "original_explanation", "original_justification",
        "original_rule_evidence_json", "original_source_metadata_json",
    ):
        if key in current and current[key] is not None:
            original[key] = current[key]
    return original


def source_projection(conn, tax_type, source_id, result):
    table = source_table(tax_type)
    conn.execute(text(f"UPDATE `{table}` SET predicted_fraud=:result WHERE id=:id"), {
        "result": result, "id": int(source_id)
    })


def ensure_original_and_policy(conn, *, tax_type, row, invalid_row=None, actor_id=None,
                               disabled=False, run_id=None):
    """Create/advance one source decision inside the caller transaction."""
    source = _source_from_row(tax_type, row)
    source["run_id"] = run_id
    original = _original_from_row(tax_type, row)
    current = get_current(conn, tax_type, source["source_record_id"], for_update=True)
    if not current:
        original_decision = {
            "current_business_result": original["original_ml_result"],
            "business_decision_type": "ORIGINAL",
            "decision_reason": "ORIGINAL_RESULT",
            "invalid_tin_state_at_decision": NORMAL,
            "invalid_tin_id": None,
            "invalid_tin_status_at_decision": None,
        }
        original_id = create_version(conn, source=source, original=original,
                                     decision=original_decision, actor_id=actor_id, version=1)
        current = get_current(conn, tax_type, source["source_record_id"], for_update=True)
    else:
        original = _original_from_current(current, original)
    if current and current.get("business_decision_type") == "ADMIN_OVERRIDE":
        return {"decision_id": int(current["id"]), "projected": False, "skipped": True}

    state = NORMAL
    tin_id = None
    tin_status = None
    if invalid_row:
        tin_id = invalid_row.get("id")
        tin_status = int(invalid_row.get("status") or 0)
        state = ACTIVE if tin_status else INACTIVE
    decision = evaluate_disabled_result(original["original_ml_result"]) if disabled else evaluate_business_decision(
        original["original_ml_result"], state
    )
    if current and current.get("decision_reason") == decision["decision_reason"] and \
            current.get("current_business_result") == decision["current_business_result"]:
        return {"decision_id": int(current["id"]), "projected": False, "skipped": True}
    decision.update({
        "business_decision_type": decision.pop("decision_type", None),
        "invalid_tin_state_at_decision": state,
        "invalid_tin_id": tin_id,
        "invalid_tin_status_at_decision": tin_status,
    })
    decision_id = create_version(conn, source=source, original=original, decision=decision,
                                 actor_id=actor_id, previous=current)
    if decision["should_project_source"] if "should_project_source" in decision else False:
        source_projection(conn, tax_type, source["source_record_id"], decision["current_business_result"])
    return {"decision_id": decision_id, "projected": bool(decision.get("should_project_source")), "skipped": False}


def admin_override(conn, *, tax_type, row, result, reason, actor_id):
    if not reason or not str(reason).strip():
        raise ValueError("Override reason is required")
    if result not in {"Fraud", "Non-Fraud"}:
        raise ValueError("Override result must be Fraud or Non-Fraud")
    source = _source_from_row(tax_type, row)
    original = _original_from_row(tax_type, row)
    current = get_current(conn, tax_type, source["source_record_id"], for_update=True)
    if not current:
        ensure_original_and_policy(conn, tax_type=tax_type, row=row, actor_id=actor_id)
        current = get_current(conn, tax_type, source["source_record_id"], for_update=True)
    original = _original_from_current(current, original)
    decision = {
        "current_business_result": result,
        "business_decision_type": "ADMIN_OVERRIDE",
        "decision_reason": "ADMIN_OVERRIDE",
        "invalid_tin_state_at_decision": current["invalid_tin_state_at_decision"],
        "invalid_tin_id": current["invalid_tin_id"],
        "invalid_tin_status_at_decision": current["invalid_tin_status_at_decision"],
    }
    decision_id = create_version(conn, source=source, original=original, decision=decision,
                                 actor_id=actor_id, override_reason=reason, previous=current)
    source_projection(conn, tax_type, source["source_record_id"], result)
    return decision_id
