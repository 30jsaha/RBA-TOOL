"""Single source of truth for the Invalid-TIN policy matrix."""


ACTIVE = "ACTIVE_INVALID_TIN"
INACTIVE = "INACTIVE_INVALID_TIN"
NORMAL = "NORMAL"


def _result(value):
    value = str(value or "").strip()
    return "Non-Fraud" if value.lower().replace("_", "-") in {"non-fraud", "nonfraud"} else "Fraud"


def evaluate_business_decision(original_result, invalid_tin_state):
    """Evaluate one policy decision without mutating source data."""
    original = _result(original_result)
    state = str(invalid_tin_state or NORMAL).strip().upper()
    if state == ACTIVE and original == "Fraud":
        return {
            "current_business_result": "Non-Fraud",
            "decision_type": "INVALID_TIN",
            "decision_reason": "ACTIVE_INVALID_TIN",
            "should_project_source": True,
        }
    if state in {ACTIVE, INACTIVE}:
        return {
            "current_business_result": original,
            "decision_type": "INVALID_TIN",
            "decision_reason": state,
            "should_project_source": False,
        }
    return {
        "current_business_result": original,
        "decision_type": "ORIGINAL",
        "decision_reason": "ORIGINAL_RESULT",
        "should_project_source": False,
    }


def evaluate_disabled_result(original_result):
    return {
        "current_business_result": _result(original_result),
        "decision_type": "INVALID_TIN_DISABLED",
        "decision_reason": "INVALID_TIN_DISABLED",
        "should_project_source": True,
    }
