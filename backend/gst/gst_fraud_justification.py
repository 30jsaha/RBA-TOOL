# gst_fraud_justification.py
import pandas as pd
import numpy as np

# Human-friendly names for model feature columns
FRIENDLY_NAMES = {
    "total_sales_income":               "total sales income",
    "exempt_sales":                     "tax-exempt sales",
    "zero_rated_sales":                 "zero-rated sales",
    "add_exempt_and_zero_rated_sales":  "combined exempt and zero-rated sales",
    "gst_taxable_sales":                "taxable sales",
    "output_debits":                    "output GST debits",
    "deferred_import_liabilities":      "deferred import liabilities",
    "gst_paid_on_inputs":               "GST paid on inputs",
    "gst_paid_exempt_sales":            "GST paid on exempt sales",
    "gst_paid_private":                 "GST paid on private use",
    "add_private_and_exempt_gst_paid":  "combined private and exempt GST paid",
    "input_credits":                    "input tax credits",
    "deduct_input_credits":             "deducted input credits",
    "gst_payable":                      "GST payable",
    "gst_refundable":                   "GST refund claimed",
    "gst_sec65a_credit_allowable":      "Section 65A allowable credit",
}

# Plain-English explanations for each rule flag (value = 1 means the rule fired)
RULE_MESSAGES = {
    "deduct_input_credits_violation":         "Claimed more input credits than are allowed — the deducted input credits exceed the actual input credits on record.",
    "invalid_gst_refundable":                "Claimed a GST refund without meeting the basic requirement — a refund is only valid when input credits exceed output debits.",
    "fraud_output_debits_no_tax":            "Had output GST debits exceeding input credits but reported zero tax payable — tax was owed but not paid.",
    "misreported_zero_rated_sales":          "Reported exempt sales higher than total sales income, which is not possible and suggests misreporting.",
    "overstated_zero_rated_sales":           "Reported zero-rated sales higher than total sales income — this appears to be an overstatement.",
    "non_reported_taxable_sales":            "Taxable sales figures suggest some sales may not have been reported for tax.",
    "fraud_incomplete_gst_returns":          "Did not file GST returns for all 12 months of the year — incomplete filing is a common fraud indicator.",
    "non_filing_gst":                        "Filed zero GST returns for the entire year — non-filing is a strong fraud indicator.",
    "sales_drop_more_than_50_percent":       "Sales dropped by more than 50% compared to the previous period while input credits stayed the same or increased — this unusual pattern suggests possible manipulation.",
    "fraud_multiple_refund_claims_6_months": "Claimed GST refunds for 6 or more consecutive months while having very low total sales — this is a common pattern in fraudulent refund claims.",
}


def _build_model_parts(row, feature_cols, thresholds):
    """Generate model-based explanation points for a single row."""
    model_parts = []
    for feature in feature_cols:
        if feature not in row or feature not in thresholds:
            continue

        value = row[feature]
        label = FRIENDLY_NAMES.get(feature, feature)

        if feature == 'taxpayer_type':
            fraud_common = thresholds[feature].get('fraud_common')
            if fraud_common is not None and value == fraud_common:
                model_parts.append(
                    f"This taxpayer is registered as '{value}', which is the most common type seen in fraud cases."
                )
        else:
            fraud_90th   = thresholds[feature].get('fraud_90th', 0)
            fraud_median = thresholds[feature].get('fraud_median', 0)

            if fraud_90th > 0 and value > fraud_90th:
                model_parts.append(
                    f"The {label} of PGK.{value:,.0f} is unusually high — it is in the top 10% of all fraud cases."
                )
            elif fraud_median > 0 and value > fraud_median:
                model_parts.append(
                    f"The {label} of PGK.{value:,.0f} is higher than what is typically seen in fraud cases."
                )

    return model_parts


def _build_rule_parts(row):
    """Collect all business-rule violation messages that fired for a single row."""
    rule_parts = []
    for rule_col, message in RULE_MESSAGES.items():
        if rule_col in row and row[rule_col] == 1:
            rule_parts.append(message)
    return rule_parts


def _build_explanation(row, feature_cols, thresholds):
    """
    Determine justification text using 4-case logic:

    Case 1  Model=Fraud   & Rules=Fraud      → Combined explanation (MODEL + RULES)
    Case 2  Model=Fraud   & Rules=Non-Fraud  → Model explanation only
    Case 3  Model=Non-Fraud & Rules=Fraud    → Violated business rules only
    Case 4  Model=Non-Fraud & Rules=Non-Fraud→ No significant issues found
    """
    model_fraud = str(row.get('predicted_fraud', 'Non-Fraud')).strip() == 'Fraud'
    rule_fraud  = int(row.get('is_fraud', 0)) == 1

    # ── CASE 1: Both model AND rules say Fraud ──────────────────────────────
    if model_fraud and rule_fraud:
        model_parts = _build_model_parts(row, feature_cols, thresholds)
        rule_parts  = _build_rule_parts(row)

        sections = []
        if model_parts:
            sections.append("MODEL SIGNALS: " + " | ".join(model_parts))
        if rule_parts:
            sections.append("RULE VIOLATIONS: " + " | ".join(rule_parts))

        if sections:
            return "FLAGGED BY BOTH MODEL AND RULES. " + " || ".join(sections)
        return (
            "Flagged as suspicious by both the predictive model and business rules "
            "based on a combination of irregularities across multiple filing fields."
        )

    # ── CASE 2: Model says Fraud, Rules say Non-Fraud ───────────────────────
    if model_fraud and not rule_fraud:
        model_parts = _build_model_parts(row, feature_cols, thresholds)
        if model_parts:
            return "FLAGGED BY MODEL ONLY. MODEL SIGNALS: " + " | ".join(model_parts)
        return (
            "FLAGGED BY MODEL ONLY. Flagged as suspicious based on a combination of "
            "small irregularities across multiple filing fields detected by the predictive model."
        )

    # ── CASE 3: Model says Non-Fraud, Rules say Fraud ───────────────────────
    if not model_fraud and rule_fraud:
        rule_parts = _build_rule_parts(row)
        if rule_parts:
            return "FLAGGED BY RULES ONLY. RULE VIOLATIONS: " + " | ".join(rule_parts)
        return (
            "FLAGGED BY RULES ONLY. This filing triggered one or more business rule checks "
            "but the specific violation details could not be determined."
        )

    # ── CASE 4: Both say Non-Fraud ───────────────────────────────────────────
    return "No significant issues found. Filing appears to follow a normal pattern."


def create_gst_fraud_justification_file(input_file='gst_fraud_prediction.parquet',
                                        output_file='gst_fraud_justification'):
    """
    Creates justification explanations for GST fraud predictions.

    Justification uses BOTH the predictive model outcome (predicted_fraud) and
    the business-rule outcome (is_fraud) to determine what to explain:

      predicted_fraud=Fraud   & is_fraud=1  → Combined model + rules explanation
      predicted_fraud=Fraud   & is_fraud=0  → Model explanation only
      predicted_fraud=Non-Fraud & is_fraud=1 → Business rules violated (rules only)
      predicted_fraud=Non-Fraud & is_fraud=0 → No significant issues found

    Args:
        input_file (str): Path to input parquet file with predictions
        output_file (str): Base name for output files (without extension)

    Returns:
        tuple: (enhanced_data, fraud_cases, non_fraud_cases, thresholds)
    """
    predictions_data = pd.read_parquet(input_file)

    for required_col in ('predicted_fraud', 'is_fraud'):
        if required_col not in predictions_data.columns:
            raise ValueError(f"Input file must contain '{required_col}' column")

    feature_cols = [
        "total_sales_income", "taxpayer_type", "exempt_sales",
        "zero_rated_sales", "add_exempt_and_zero_rated_sales",
        "gst_taxable_sales", "output_debits", "deferred_import_liabilities",
        "gst_paid_on_inputs", "gst_paid_exempt_sales", "gst_paid_private",
        "add_private_and_exempt_gst_paid", "input_credits",
        "deduct_input_credits", "gst_payable", "gst_refundable",
        "gst_sec65a_credit_allowable"
    ]

    # Build thresholds from model-predicted fraud cases
    fraud_mask      = predictions_data['predicted_fraud'] == 'Fraud'
    fraud_cases     = predictions_data[fraud_mask]
    non_fraud_cases = predictions_data[~fraud_mask]

    thresholds = {}
    for feature in feature_cols:
        if feature in predictions_data.columns:
            if feature == 'taxpayer_type':
                thresholds[feature] = {
                    'fraud_common':     fraud_cases[feature].mode()[0] if not fraud_cases[feature].mode().empty else None,
                    'non_fraud_common': non_fraud_cases[feature].mode()[0] if not non_fraud_cases[feature].mode().empty else None,
                }
            else:
                thresholds[feature] = {
                    'fraud_90th':     fraud_cases[feature].quantile(0.9) if len(fraud_cases) > 0 else 0,
                    'fraud_median':   fraud_cases[feature].median()      if len(fraud_cases) > 0 else 0,
                    'non_fraud_90th': non_fraud_cases[feature].quantile(0.9) if len(non_fraud_cases) > 0 else 0,
                }

    is_historical = (
        'tax_period_year' in predictions_data.columns
        and predictions_data['tax_period_year'].nunique() > 1
    )
    years = sorted(predictions_data['tax_period_year'].unique()) if is_historical else [None]

    explanations = []

    for year in years:
        year_data = (
            predictions_data[predictions_data['tax_period_year'] == year]
            if year is not None else predictions_data
        )
        for idx, row in year_data.iterrows():
            explanations.append(_build_explanation(row, feature_cols, thresholds))

    predictions_data['explanation'] = explanations

    columns_to_drop = ['fraud_probability', 'fraud_prediction_numeric']
    existing_to_drop = [c for c in columns_to_drop if c in predictions_data.columns]
    if existing_to_drop:
        predictions_data = predictions_data.drop(columns=existing_to_drop)

    predictions_data.to_csv(f"{output_file}.csv", index=False)
    predictions_data.to_parquet(f"{output_file}.parquet", index=False)

    print("Justification done!")
    return predictions_data, fraud_cases, non_fraud_cases, thresholds


def get_required_columns():
    """Returns list of columns required for justification."""
    return [
        "total_sales_income", "taxpayer_type", "exempt_sales",
        "zero_rated_sales", "add_exempt_and_zero_rated_sales",
        "gst_taxable_sales", "output_debits", "deferred_import_liabilities",
        "gst_paid_on_inputs", "gst_paid_exempt_sales", "gst_paid_private",
        "add_private_and_exempt_gst_paid", "input_credits",
        "deduct_input_credits", "gst_payable", "gst_refundable",
        "gst_sec65a_credit_allowable", "predicted_fraud", "is_fraud"
    ]