# ══════════════════════════════════════════════════════════════
#  config/db_init.py
#  Auto-creates all required MySQL tables on server startup.
#  Called once from api/app.py before the server starts serving.
#  No pipeline run needed — tables are created with full schema.
# ══════════════════════════════════════════════════════════════

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from config.db_config import get_mysql_engine


# ─────────────────────────────────────────────────────────────
#  DDL statements — one per table
#  All columns match exactly what the pipelines write to DB.
# ─────────────────────────────────────────────────────────────

DDL_STATEMENTS = {

    # ── Shared logging tables (upload_logger.py) ──────────────

    "upload_log": """
        CREATE TABLE IF NOT EXISTS upload_log (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            user_id         BIGINT NULL,
            tax_type        VARCHAR(10),
            filename        VARCHAR(255),
            filepath        VARCHAR(500),
            file_size_kb    FLOAT,
            file_format     VARCHAR(20),
            row_count       INT,
            column_count    INT,
            status          VARCHAR(20),
            error_message   TEXT,
            pipeline_run    TINYINT(1),
            notes           TEXT,
            uploaded_at     DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """,

    "pipeline_log": """
        CREATE TABLE IF NOT EXISTS pipeline_log (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            user_id         BIGINT NULL,
            run_id          VARCHAR(40)  NOT NULL,
            tax_type        VARCHAR(10)  NOT NULL,
            step_number     INT,
            step_name       VARCHAR(100),
            substep_name    VARCHAR(100),
            status          VARCHAR(20)  NOT NULL,
            records_in      INT,
            records_out     INT,
            elapsed_sec     FLOAT,
            message         TEXT,
            error_detail    TEXT,
            logged_at       DATETIME     NOT NULL
        )
    """,

    # ── GST fraud justification (gst_upload_hook.py) ──────────

    "gst_fraud_justification": """
        CREATE TABLE IF NOT EXISTS gst_fraud_justification (
            id                                      INT AUTO_INCREMENT PRIMARY KEY,
            user_id                                 BIGINT NULL,
            tin                                     BIGINT,
            taxpayer_type                           TEXT,
            tax_account_number                      BIGINT,
            assessment_number                       BIGINT,
            form_version                            BIGINT,
            tax_period_year                         BIGINT,
            tax_period_month                        BIGINT,
            received_date                           TEXT,
            entry_date                              TEXT,
            due_date                                TEXT,
            total_sales_income                      DOUBLE,
            exempt_sales                            DOUBLE,
            zero_rated_sales                        DOUBLE,
            add_exempt_and_zero_rated_sales         DOUBLE,
            gst_taxable_sales                       DOUBLE,
            output_debits                           DOUBLE,
            deferred_import_liabilities             DOUBLE,
            gst_paid_on_inputs                      DOUBLE,
            gst_paid_exempt_sales                   DOUBLE,
            gst_paid_private                        DOUBLE,
            add_private_and_exempt_gst_paid         DOUBLE,
            input_credits                           DOUBLE,
            deduct_input_credits                    DOUBLE,
            gst_payable                             DOUBLE,
            gst_refundable                          DOUBLE,
            gst_sec65a_credit_allowable             DOUBLE,
            taxpayer_name                           TEXT,
            predicted_fraud                         TEXT,
            deduct_input_credits_violation          BIGINT,
            invalid_gst_refundable                  BIGINT,
            fraud_output_debits_no_tax              BIGINT,
            misreported_zero_rated_sales            BIGINT,
            overstated_zero_rated_sales             BIGINT,
            non_reported_taxable_sales              BIGINT,
            fraud_incomplete_gst_returns            BIGINT,
            non_filing_gst                          BIGINT,
            sales_drop_more_than_50_percent         BIGINT,
            fraud_multiple_refund_claims_6_months   BIGINT,
            is_fraud                                BIGINT,
            explanation                             TEXT,
            upload_batch_id                         TEXT,
            uploaded_at                             DATETIME
        )
    """,

    # GST upload-vs-DB financial differences captured during validation
    # (these rows are INVALID and must not enter the main pipeline tables)
    "upload_differences": """
        CREATE TABLE IF NOT EXISTS upload_differences (
            id                                      INT AUTO_INCREMENT PRIMARY KEY,
            user_id                                 BIGINT NULL,
            tin                                     BIGINT,
            tax_account_number                      BIGINT,
            tax_period_year                         BIGINT,
            tax_period_month                        BIGINT,
            upload_total_sales_income               DOUBLE,
            upload_exempt_sales                     DOUBLE,
            upload_zero_rated_sales                 DOUBLE,
            upload_add_exempt_and_zero_rated_sales  DOUBLE,
            upload_gst_taxable_sales                DOUBLE,
            upload_output_debits                    DOUBLE,
            upload_deferred_import_liabilities      DOUBLE,
            upload_gst_paid_on_inputs               DOUBLE,
            upload_gst_paid_exempt_sales            DOUBLE,
            upload_gst_paid_private                 DOUBLE,
            upload_add_private_and_exempt_gst_paid  DOUBLE,
            upload_input_credits                    DOUBLE,
            upload_deduct_input_credits             DOUBLE,
            upload_gst_payable                      DOUBLE,
            upload_gst_refundable                   DOUBLE,
            upload_gst_sec65a_credit_allowable      DOUBLE,
            db_total_sales_income                   DOUBLE,
            db_exempt_sales                         DOUBLE,
            db_zero_rated_sales                     DOUBLE,
            db_add_exempt_and_zero_rated_sales      DOUBLE,
            db_gst_taxable_sales                    DOUBLE,
            db_output_debits                        DOUBLE,
            db_deferred_import_liabilities          DOUBLE,
            db_gst_paid_on_inputs                   DOUBLE,
            db_gst_paid_exempt_sales                DOUBLE,
            db_gst_paid_private                     DOUBLE,
            db_add_private_and_exempt_gst_paid      DOUBLE,
            db_input_credits                        DOUBLE,
            db_deduct_input_credits                 DOUBLE,
            db_gst_payable                          DOUBLE,
            db_gst_refundable                       DOUBLE,
            db_gst_sec65a_credit_allowable          DOUBLE
        )
    """,

    # ── CIT fraud justification (cit_upload_hook.py) ──────────

    "cit_fraud_justification": """
    CREATE TABLE IF NOT EXISTS cit_fraud_justification (
        id                                      INT AUTO_INCREMENT PRIMARY KEY,
        user_id                                 BIGINT NULL,
        tin                                     BIGINT,
        taxpayer                                TEXT,
        tax_account_no                          BIGINT,
        tax_type                                TEXT,
        tax_period_year                         BIGINT,
        assessment_no                           BIGINT,
        received_date                           TEXT,
        entry_date                              TEXT,
        due_date                                TEXT,
        form_no                                 DOUBLE,
        form_version_no                         BIGINT,
        irc_form_version_no                     TEXT,
        form_description                        TEXT,
        gross_sales_cash_or_credit              DOUBLE,
        gross_contract_and_sub_con              DOUBLE,
        partnership_distribution_i              DOUBLE,
        distributions_from_trusts               DOUBLE,
        oil_pipeline_tariffs_and_r              DOUBLE,
        dividend_income                         DOUBLE,
        exchange_gains_or_losses                DOUBLE,
        interest_income                         DOUBLE,
        rental_income                           DOUBLE,
        royalty_income                          DOUBLE,
        other_gross_income                      DOUBLE,
        total_gross_income                      DOUBLE,
        cost_of_goods_sold                      DOUBLE,
        rented_property_expenses_i              DOUBLE,
        resource_operations_joint               DOUBLE,
        amortisation                            DOUBLE,
        advertising_and_promotion               DOUBLE,
        bad_debts_written_off                   DOUBLE,
        borrowing_expenses                      DOUBLE,
        commissions                             DOUBLE,
        contract_employees                      DOUBLE,
        consultancy_fees                        DOUBLE,
        consumables                             DOUBLE,
        depreciation                            DOUBLE,
        development_levy                        DOUBLE,
        directors_fees_and_expens               DOUBLE,
        entertainment_expenses                  DOUBLE,
        foreign_exchange_losses_or              DOUBLE,
        gifts_and_donations                     DOUBLE,
        insurance                               DOUBLE,
        interest_expense_png                    DOUBLE,
        interest_expense_foreign                DOUBLE,
        lease_payments                          DOUBLE,
        legal_expenses                          DOUBLE,
        management_fees_png                     DOUBLE,
        management_fees_foreign                 DOUBLE,
        motor_vehicle_expenses                  DOUBLE,
        repairs_and_maintenance                 DOUBLE,
        rental_expenses                         DOUBLE,
        royalties_png                           DOUBLE,
        royalties_foreign                       DOUBLE,
        salaries_or_wages                       DOUBLE,
        superannuation_png                      DOUBLE,
        superannuation_foreign                  DOUBLE,
        travel_and_accommodation                DOUBLE,
        all_other_expenses                      DOUBLE,
        total_operating_expenses                DOUBLE,
        amortisation_charged_in_th              DOUBLE,
        depreciation_charged_in_th              DOUBLE,
        non_allowable_capital_expe              DOUBLE,
        increase_in_provisions_and              DOUBLE,
        income_tax_if_claimed_in                DOUBLE,
        non_allowable_donations_or              DOUBLE,
        non_allowable_legal_expens              DOUBLE,
        goodwill_or_formation_expe              DOUBLE,
        recouped_lease_premiums                 DOUBLE,
        excess_management_fees                  DOUBLE,
        excess_interest_deductions              DOUBLE,
        other_items_not_allowable               DOUBLE,
        total_non_deductible_items              DOUBLE,
        non_assessable_income                   DOUBLE,
        depreciation_for_tax_purpo              DOUBLE,
        depreciation_incentiveonly              DOUBLE,
        allowable_exploration_dedu              DOUBLE,
        allowable_capital_expendit              DOUBLE,
        allowable_capital_expendit_2            DOUBLE,
        section_155n_inc_deduction              DOUBLE,
        double_deductions                       DOUBLE,
        prior_year_losses_utilised              DOUBLE,
        other_tax_deductible_items              DOUBLE,
        net_exempt_income                       DOUBLE,
        res_royalty_and_dev_levy                DOUBLE,
        other_tax_deductible_items_2            DOUBLE,
        total_deductible_items_ex               DOUBLE,
        dividend_rebate                         DOUBLE,
        foreign_taxes_paid                      DOUBLE,
        resource_royalty_and_devel              DOUBLE,
        total_other_credits_and_re              DOUBLE,
        cash_or_investments                     DOUBLE,
        inventory_closing_stock                 DOUBLE,
        accounts_receivable_trade               DOUBLE,
        pre_paid_expenses                       DOUBLE,
        other                                   DOUBLE,
        total_current_assets                    DOUBLE,
        property_or_equipment                   DOUBLE,
        leasehold_improvements                  DOUBLE,
        equity_or_other_investments             DOUBLE,
        other_2                                 DOUBLE,
        less_accumulated_depreciat              DOUBLE,
        total_fixed_assets                      DOUBLE,
        total_assets                            DOUBLE,
        accounts_payable                        DOUBLE,
        accrued_salary_or_wages                 DOUBLE,
        taxes_and_fees_payable                  DOUBLE,
        unearned_revenue                        DOUBLE,
        other_3                                 DOUBLE,
        total_current_liabilities               DOUBLE,
        mortgage                                DOUBLE,
        loans_from_directors                    DOUBLE,
        other_loans                             DOUBLE,
        other_long_term_liabilitie              DOUBLE,
        total_long_term_liabilitie              DOUBLE,
        total_liabilities                       DOUBLE,
        interest                                DOUBLE,
        a_fishing_operations                    DOUBLE,
        dividends                               DOUBLE,
        b_export_sales                          DOUBLE,
        i_rural_development_ince                DOUBLE,
        n_bougainville_incentive                DOUBLE,
        a_solar_heating                         DOUBLE,
        a_gifts_sporting_bodie                  DOUBLE,
        c_gifts_law_order_an                    DOUBLE,
        e_gifts_charitable_org                  DOUBLE,
        h_gifts_law_or_order_pr                 DOUBLE,
        i_gifts_national_day_c                  DOUBLE,
        k_gifts_png_sports_fed                  DOUBLE,
        m_island_forum                          DOUBLE,
        a_education_expenses_in                 DOUBLE,
        a_double_deduction_sta                  DOUBLE,
        c_double_deduction_exp                  DOUBLE,
        c_double_deduction_exp_2                DOUBLE,
        depreciation_20_l                       DOUBLE,
        depreciation_fuel                       DOUBLE,
        depreciation_non_o                      DOUBLE,
        depreciation_non_o_2                    DOUBLE,
        depreciation_indus                      DOUBLE,
        depreciation_prima                      DOUBLE,
        research_or_developme                   DOUBLE,
        a_primary_production_dev                DOUBLE,
        b_1_150_extension_serv                  DOUBLE,
        j_double_deduction_un                   DOUBLE,
        n_amortisation_explor                   DOUBLE,
        d_amortisation_explor                   DOUBLE,
        e_double_deduction_ex                   DOUBLE,
        j_amortisation_allowa                   DOUBLE,
        ch119_pioneer_industries                DOUBLE,
        current_year_approved                   DOUBLE,
        d_expenditure_for_the_p                 DOUBLE,
        other_4                                 DOUBLE,
        total_enter_the_sum_of_all              DOUBLE,
        current_year_profit_or_loss             DOUBLE,
        loss_utilised_from_prior_y              DOUBLE,
        taxable_income                          DOUBLE,
        gross_tax                               DOUBLE,
        less_other_credits_rebate               DOUBLE,
        gross_tax_net_of_other_cre              DOUBLE,
        plus_additional_profits_ta              DOUBLE,
        total_tax_payable                       DOUBLE,
        less_infrastructure_develo              DOUBLE,
        less_interest_withholding               DOUBLE,
        less_business_payments_tax              DOUBLE,
        total_tax_to_pay_after_in               DOUBLE,
        less_prov_tax_apt                       DOUBLE,
        net_tax_payable_or_refunda              DOUBLE,
        instalment_basis_for_futur              DOUBLE,
        total_directors_fees                    DOUBLE,
        total_salary_or_wages                   DOUBLE,
        total_allowances                        DOUBLE,
        total_salary_or_wages_tax_ded           DOUBLE,
        total_bpt_income                        DOUBLE,
        total_bpt_tax_deducted                  DOUBLE,
        schedule_3                              DOUBLE,
        total_dividends_paid_durin              DOUBLE,
        total_dwt_due                           DOUBLE,
        less_dwt_paid                           DOUBLE,
        total_1_dividends_paid                  DOUBLE,
        total_gross_dividend_or_di              DOUBLE,
        total_dwt_deducted                      DOUBLE,
        total_dividend_foreign_tax              DOUBLE,
        add_dwt_or_utwt_carried_fo              DOUBLE,
        total_2_dwt_deducted_plus               DOUBLE,
        balance_payable_or_or_to_b              DOUBLE,
        total_gross_interest_paid               DOUBLE,
        total_iwt_deducted                      DOUBLE,
        foreign_tax_paid_if_appli               DOUBLE,
        total_total_rent_paid_duri              DOUBLE,
        royalty_payments_tot_paid               DOUBLE,
        management_fees_tot_paid                DOUBLE,
        foreign_shipping_tot_amo                DOUBLE,
        super_total_fully_taxed                 DOUBLE,
        super_total_employer_s                  DOUBLE,
        super_total_employees                   DOUBLE,
        super_total_payouts                     DOUBLE,
        super_total_loan_bal_start              DOUBLE,
        super_total_interest                    DOUBLE,
        super_total_repayments                  DOUBLE,
        super_total_loan_bal_end                DOUBLE,
        total_beneficiary_s_share               DOUBLE,
        total_amount_income_deriv               DOUBLE,
        sector_activity                         TEXT,
        ent_activity_code                       DOUBLE,
        enterprise_activity                     TEXT,
        infrastr_develop_cr                     DOUBLE,
        tax_foregone                            DOUBLE,
        tax_foregone_2                          DOUBLE,
        tax_foregone_3                          DOUBLE,
        tax_foregone_4                          DOUBLE,
        tax_foregone_5                          DOUBLE,
        tax_foregone_6                          DOUBLE,
        tax_foregone_7                          DOUBLE,
        tax_foregone_8                          DOUBLE,
        tax_foregone_9                          DOUBLE,
        d_ded_manufac                           DOUBLE,
        d_ded_tourism                           DOUBLE,
        tax_foregone_3_                         DOUBLE,
        tax_foregone_4_                         DOUBLE,
        tax_foregone_5_                         DOUBLE,
        tax_foregone_6_                         DOUBLE,
        tax_foregone_7_                         DOUBLE,
        tax_foregone_9_                         DOUBLE,
        tax_foregone_1_                         DOUBLE,
        tax_foregone_10                         DOUBLE,
        tax_foregone_1_2                        DOUBLE,
        tax_foregone_11                         DOUBLE,
        tax_foregone_12                         DOUBLE,
        tax_foregone_13                         DOUBLE,
        tax_foregone_14                         DOUBLE,
        tax_foregone_15                         DOUBLE,
        other_tax_foregone                      DOUBLE,
        total_tax_revenue_foregone              DOUBLE,
        less_res_royalty_or_dev_levy            DOUBLE,
        tot_tax_to_pay_afterrrdcr               DOUBLE,
        assessed_date                           TEXT,
        res_royalty_and_dev_levy_1              DOUBLE,
        total_sales_revenue                     DOUBLE,
        total_distributions_royalties           DOUBLE,
        total_investment_income                 DOUBLE,
        total_other_income                      DOUBLE,
        total_cost_of_goods_sold                DOUBLE,
        total_property_rental_expenses          DOUBLE,
        total_resource_operations               DOUBLE,
        total_depreciation_amortization         DOUBLE,
        total_marketing_promotion               DOUBLE,
        total_financial_expenses                DOUBLE,
        total_employee_expenses                 DOUBLE,
        total_professional_fees                 DOUBLE,
        total_operational_expenses              DOUBLE,
        total_amortization_depreciation         DOUBLE,
        total_non_allowable_capital_expenses    DOUBLE,
        total_provisions_taxes                  DOUBLE,
        total_non_allowable_donations_legal     DOUBLE,
        total_goodwill_formation_expenses       DOUBLE,
        total_recouped_lease_premiums           DOUBLE,
        total_excess_fees_interest              DOUBLE,
        total_other_non_allowable_items         DOUBLE,
        total_non_assessable_income             DOUBLE,
        total_depreciation                      DOUBLE,
        total_exploration_capital_expenditure   DOUBLE,
        total_section_specific_deductions       DOUBLE,
        total_prior_year_losses                 DOUBLE,
        total_other_deductible_items            DOUBLE,
        total_net_exempt_income                 DOUBLE,
        total_resource_royalty_dev_levy         DOUBLE,
        total_dividend_rebate                   DOUBLE,
        total_foreign_taxes_paid                DOUBLE,
        total_resource_royalty_development      DOUBLE,
        total_current_assets_2                  DOUBLE,
        total_fixed_assets_2                    DOUBLE,
        total_current_liabilities_2             DOUBLE,
        total_long_term_liabilities             DOUBLE,
        total_tax_incentives_deductions         DOUBLE,
        total_taxable_income_tax_payable        DOUBLE,
        total_section_specific_tax_foregone     DOUBLE,
        total_other_tax_foregone                DOUBLE,
        total_directors_salary_related          DOUBLE,
        total_business_payments_tax             DOUBLE,
        total_dividends                         DOUBLE,
        total_interest_withholding_tax          DOUBLE,
        total_rent_royalty_payments             DOUBLE,
        total_management_foreign_shipping_fees  DOUBLE,
        total_superannuation_payments           DOUBLE,
        total_loan_related_payments             DOUBLE,
        total_liabilities_2                     DOUBLE,
        total_gross_income_2                    DOUBLE,
        non_operating_income                    DOUBLE,
        predicted_fraud                         TEXT,
        Justification                           TEXT,
        upload_batch_id                         TEXT,
        uploaded_at                             DATETIME
    )
""",

    # ── SWT fraud justification (swt_upload_hook.py) ──────────

    "swt_fraud_justification": """
        CREATE TABLE IF NOT EXISTS swt_fraud_justification (
            id                          INT AUTO_INCREMENT PRIMARY KEY,
            user_id                     BIGINT NULL,
            tin                         TEXT,
            taxpayer_name               TEXT,
            establishment_number        BIGINT,
            head_office                 TEXT,
            tax_account_number          BIGINT,
            tax_period_year             BIGINT,
            tax_period_month            BIGINT,
            assessment_number           BIGINT,
            form_version                BIGINT,
            entry_date                  DATETIME,
            assessed_date               DATETIME,
            due_date                    DATETIME,
            employees_on_payroll        DOUBLE,
            total_salary_wages_paid     DOUBLE,
            employees_paid_swt          DOUBLE,
            sw_paid_for_swt_deduction   DOUBLE,
            total_swt_tax_deducted      DOUBLE,
            is_fraud                    BIGINT,
            rules_violated              TEXT,
            is_fraud_rule               BIGINT,
            fraud_probability           FLOAT,
            predicted_fraud             TEXT,
            explanation                 TEXT,
            upload_batch_id             TEXT,
            uploaded_at                 DATETIME
        )
    """,
    "agg_cit": """
        CREATE TABLE IF NOT EXISTS agg_cit (
            tin                     VARCHAR(20),
            user_id                 BIGINT NULL,
            taxpayer_name           TEXT,
            tax_account_number      BIGINT,
            assessment_number       BIGINT,
            tax_period_year         BIGINT,
            sector_activity         TEXT,
            enterprise_activity     TEXT,
            cit_total_gross_income  DOUBLE,
            cit_gross_sales         DOUBLE,
            cit_salaries_or_wages   DOUBLE,
            cit_total_tax_payable   DOUBLE,
            cit_net_tax_payable     DOUBLE,
            cit_fraud_flag          TINYINT
        )
    """,

    "agg_gst": """
        CREATE TABLE IF NOT EXISTS agg_gst (
            tin                     VARCHAR(20),
            user_id                 BIGINT NULL,
            taxpayer_name           TEXT,
            taxpayer_type           TEXT,
            tax_account_number      BIGINT,
            assessment_number       BIGINT,
            tax_period_year         BIGINT,
            gst_total_sales_income  DOUBLE,
            gst_taxable_sales       DOUBLE,
            gst_output_debits       DOUBLE,
            gst_input_credits       DOUBLE,
            gst_payable             DOUBLE,
            gst_refundable          DOUBLE,
            gst_fraud_flag          TINYINT
        )
    """,

    "agg_swt": """
        CREATE TABLE IF NOT EXISTS agg_swt (
            tin                         VARCHAR(20),
            user_id                     BIGINT NULL,
            taxpayer_name               TEXT,
            tax_account_number          BIGINT,
            assessment_number           BIGINT,
            tax_period_year             BIGINT,
            swt_total_salary_wages_paid DOUBLE,
            swt_total_tax_deducted      DOUBLE,
            swt_employees_on_payroll    DOUBLE,
            swt_employees_paid_swt      DOUBLE,
            swt_fraud_flag              TINYINT
        )
    """,

    "multi_tax_integration_results": """
        CREATE TABLE IF NOT EXISTS multi_tax_integration_results (
            tin                         VARCHAR(20),
            user_id                     BIGINT NULL,
            taxpayer_name               TEXT,
            taxpayer_type               TEXT,
            tax_account_number          BIGINT,
            assessment_number           BIGINT,
            tax_period_year             BIGINT,
            sector_activity             TEXT,
            enterprise_activity         TEXT,
            cit_gross_sales             DOUBLE,
            cit_total_gross_income      DOUBLE,
            cit_salaries_or_wages       DOUBLE,
            cit_total_tax_payable       DOUBLE,
            cit_net_tax_payable         DOUBLE,
            gst_total_sales_income      DOUBLE,
            gst_taxable_sales           DOUBLE,
            gst_output_debits           DOUBLE,
            gst_input_credits           DOUBLE,
            gst_payable                 DOUBLE,
            gst_refundable              DOUBLE,
            swt_total_salary_wages_paid DOUBLE,
            swt_total_tax_deducted      DOUBLE,
            swt_employees_on_payroll    DOUBLE,
            swt_employees_paid_swt      DOUBLE,
            gst_vs_cit_sales_diff       DOUBLE,
            gst_vs_cit_sales_diff_abs   DOUBLE,
            gst_vs_cit_sales_pct        DOUBLE,
            swt_vs_cit_salary_diff      DOUBLE,
            swt_vs_cit_salary_diff_abs  DOUBLE,
            swt_vs_cit_salary_pct       DOUBLE,
            gst_validation              VARCHAR(50),
            swt_validation              VARCHAR(50),
            cit_fraud_flag              TINYINT,
            gst_fraud_flag              TINYINT,
            swt_fraud_flag              TINYINT,
            flagged_in_tax_types        INT,
            multi_tax_issue             VARCHAR(20)
        )
    """,

    "permissions": """
        CREATE TABLE IF NOT EXISTS permissions (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            parent_id   INT NULL,
            code        VARCHAR(120) NOT NULL,
            name        VARCHAR(150) NOT NULL,
            description VARCHAR(255) NULL,
            sort_order  INT NOT NULL DEFAULT 0,
            is_active   TINYINT(1) NOT NULL DEFAULT 1,
            created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_permissions_code (code),
            CONSTRAINT fk_permissions_parent
                FOREIGN KEY (parent_id) REFERENCES permissions(id)
                ON DELETE SET NULL
        )
    """,

    "role_permissions": """
        CREATE TABLE IF NOT EXISTS role_permissions (
            id            INT AUTO_INCREMENT PRIMARY KEY,
            role_id       INT NOT NULL,
            permission_id INT NOT NULL,
            created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_role_permissions_role_permission (role_id, permission_id),
            KEY idx_role_permissions_role_id (role_id),
            KEY idx_role_permissions_permission_id (permission_id),
            CONSTRAINT fk_role_permissions_role
                FOREIGN KEY (role_id) REFERENCES roles(id)
                ON DELETE CASCADE,
            CONSTRAINT fk_role_permissions_permission
                FOREIGN KEY (permission_id) REFERENCES permissions(id)
                ON DELETE CASCADE
        )
    """,
}


PERMISSION_SEED = [
    {"code": "dashboard", "name": "Dashboard", "description": "Dashboard navigation", "parent_code": None, "sort_order": 10},
    {"code": "dashboard.dashboard", "name": "Dashboard", "description": "Common dashboard", "parent_code": "dashboard", "sort_order": 11},
    {"code": "dashboard.gst", "name": "GST", "description": "GST dashboard", "parent_code": "dashboard", "sort_order": 12},
    {"code": "dashboard.swt", "name": "SWT", "description": "SWT dashboard", "parent_code": "dashboard", "sort_order": 13},
    {"code": "dashboard.cit", "name": "CIT", "description": "CIT dashboard", "parent_code": "dashboard", "sort_order": 14},
    {"code": "upload_sheets", "name": "Upload Sheets", "description": "Upload sheets module", "parent_code": None, "sort_order": 20},
    {"code": "analytics", "name": "Analytics", "description": "Analytics navigation", "parent_code": None, "sort_order": 30},
    {"code": "analytics.risk_assessment", "name": "Risk Assessment", "description": "Risk assessment analytics", "parent_code": "analytics", "sort_order": 31},
    {"code": "analytics.compliance", "name": "Compliance", "description": "Compliance analytics", "parent_code": "analytics", "sort_order": 32},
    {"code": "reports", "name": "Reports", "description": "Reports navigation", "parent_code": None, "sort_order": 40},
    {"code": "reports.recent_uploads", "name": "Recent Uploads", "description": "Recent uploads report", "parent_code": "reports", "sort_order": 41},
    {"code": "reports.taxpayer_profile", "name": "Taxpayer Profile", "description": "Taxpayer profile report", "parent_code": "reports", "sort_order": 42},
    {"code": "reports.risk_profiling", "name": "Risk Profiling", "description": "Risk profiling report", "parent_code": "reports", "sort_order": 43},
    {"code": "upload_history", "name": "Upload History", "description": "Upload history module", "parent_code": None, "sort_order": 50},
    {"code": "settings", "name": "Settings", "description": "Settings navigation", "parent_code": None, "sort_order": 60},
    {"code": "settings.users", "name": "Users", "description": "User management", "parent_code": "settings", "sort_order": 61},
    {"code": "settings.invalid_tins", "name": "Invalid Tins", "description": "Invalid TIN management", "parent_code": "settings", "sort_order": 62},
    {"code": "settings.reset_db", "name": "Reset DB", "description": "Database reset", "parent_code": "settings", "sort_order": 63},
    {"code": "settings.conflicts", "name": "Conflicts", "description": "Conflict management navigation", "parent_code": "settings", "sort_order": 64},
    {"code": "settings.conflicts.list", "name": "List", "description": "Conflicts list", "parent_code": "settings.conflicts", "sort_order": 65},
    {"code": "settings.conflicts.history", "name": "History", "description": "Conflicts history", "parent_code": "settings.conflicts", "sort_order": 66},
    {"code": "settings.conflicts.audit_logs", "name": "Audit Logs", "description": "Conflicts audit logs", "parent_code": "settings.conflicts", "sort_order": 67},
    {"code": "settings.roles", "name": "Roles", "description": "Role master", "parent_code": "settings", "sort_order": 68},
    {"code": "settings.role_permissions", "name": "Role Permissions", "description": "Role permission assignment", "parent_code": "settings", "sort_order": 69},
    {"code": "upload_tin_registration", "name": "Upload TIN Registration", "description": "Upload TIN registration module", "parent_code": None, "sort_order": 70},
]


ROLE_PERMISSION_SEED = {
    "ADMIN": [item["code"] for item in PERMISSION_SEED],
    "ANALYST": [
        "dashboard.dashboard",
        "dashboard.gst",
        "dashboard.swt",
        "dashboard.cit",
        "upload_sheets",
        "analytics.risk_assessment",
        "analytics.compliance",
        "reports.recent_uploads",
        "reports.taxpayer_profile",
        "reports.risk_profiling",
        "upload_history",
    ],
    "VIEWER": [
        "dashboard.dashboard",
        "dashboard.gst",
        "dashboard.swt",
        "dashboard.cit",
        "upload_sheets",
        "analytics.risk_assessment",
        "analytics.compliance",
        "reports.recent_uploads",
        "reports.taxpayer_profile",
        "reports.risk_profiling",
        "upload_history",
    ],
}


def _expand_permission_codes(permission_codes):
    parent_by_code = {item["code"]: item["parent_code"] for item in PERMISSION_SEED}
    expanded = set(permission_codes or [])
    changed = True
    while changed:
        changed = False
        for code in list(expanded):
            parent_code = parent_by_code.get(code)
            if parent_code and parent_code not in expanded:
                expanded.add(parent_code)
                changed = True
    return expanded


def _ensure_roles_table_supports_custom_names(conn):
    column_type = conn.execute(
        text(
            """
            SELECT COLUMN_TYPE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'roles'
              AND COLUMN_NAME = 'name'
            LIMIT 1
            """
        )
    ).scalar()

    if column_type and str(column_type).lower().startswith("enum("):
        conn.execute(text("ALTER TABLE roles MODIFY COLUMN name VARCHAR(100) NOT NULL"))


def _seed_permissions(conn):
    permission_ids = {}
    for item in PERMISSION_SEED:
        parent_id = permission_ids.get(item["parent_code"]) if item.get("parent_code") else None
        existing = conn.execute(
            text("SELECT id FROM permissions WHERE code = :code LIMIT 1"),
            {"code": item["code"]},
        ).fetchone()
        if existing:
            permission_id = int(existing[0])
            conn.execute(
                text(
                    """
                    UPDATE permissions
                    SET parent_id = :parent_id,
                        name = :name,
                        description = :description,
                        sort_order = :sort_order,
                        is_active = 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :permission_id
                    """
                ),
                {
                    "permission_id": permission_id,
                    "parent_id": parent_id,
                    "name": item["name"],
                    "description": item["description"],
                    "sort_order": int(item["sort_order"]),
                },
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO permissions (parent_id, code, name, description, sort_order, is_active, created_at, updated_at)
                    VALUES (:parent_id, :code, :name, :description, :sort_order, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """
                ),
                {
                    "parent_id": parent_id,
                    "code": item["code"],
                    "name": item["name"],
                    "description": item["description"],
                    "sort_order": int(item["sort_order"]),
                },
            )
            permission_id = int(conn.execute(text("SELECT LAST_INSERT_ID()")).scalar())
        permission_ids[item["code"]] = permission_id
    return permission_ids


def _seed_role_permissions(conn, permission_ids):
    role_rows = conn.execute(text("SELECT id, name FROM roles")).fetchall()
    role_ids = {str(row[1]).upper(): int(row[0]) for row in (role_rows or []) if row and row[1]}

    for role_name, permission_codes in ROLE_PERMISSION_SEED.items():
        role_id = role_ids.get(role_name)
        if role_id is None:
            continue

        for code in sorted(_expand_permission_codes(permission_codes)):
            permission_id = permission_ids.get(code)
            if permission_id is None:
                continue
            conn.execute(
                text(
                    """
                    INSERT INTO role_permissions (role_id, permission_id, created_at, updated_at)
                    SELECT :role_id, :permission_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    FROM DUAL
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM role_permissions
                        WHERE role_id = :role_id AND permission_id = :permission_id
                    )
                    """
                ),
                {"role_id": role_id, "permission_id": permission_id},
            )


# ─────────────────────────────────────────────────────────────
#  Main init function — call this from app.py
# ─────────────────────────────────────────────────────────────

def init_db():
    """
    Creates all required tables if they don't already exist.
    Safe to call on every server startup — uses CREATE TABLE IF NOT EXISTS.
    """
    print("\n  [DB Init] Checking / creating required tables...")
    try:
        engine = get_mysql_engine()
        with engine.connect() as conn:
            for table_name, ddl in DDL_STATEMENTS.items():
                conn.execute(text(ddl))
                print(f"  [DB Init] {table_name}")

            _ensure_roles_table_supports_custom_names(conn)
            permission_ids = _seed_permissions(conn)
            _seed_role_permissions(conn, permission_ids)
            conn.commit()
        engine.dispose()
        print("  [DB Init] All tables ready.\n")
    except Exception as e:
        print(f"  [DB Init] ✗ Error during table creation: {e}\n")
