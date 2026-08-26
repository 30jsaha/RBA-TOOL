# script_1_data_preprocessing
import numpy as np
import pandas as pd
import os
import re
from tqdm import tqdm
import time
import traceback
import warnings
warnings.filterwarnings("ignore")
pd.options.display.max_columns=None
pd.options.display.float_format = '{:.2f}'.format

_TAXPAYER_COLUMN_KEYS = {
    'taxpayer',
    'taxpayername',
    'taxpayer_name',
    'tax_payer',
    'tax_payer_name',
}
_TIN_COLUMN_KEYS = {'tin', 'taxid', 'tax_id', 'taxidentificationnumber', 'taxpayerid'}


def _normalize_column_key(col_name):
    return str(col_name).lower().replace('_', '')


def _is_taxpayer_column(col_name):
    return _normalize_column_key(col_name) in {
        key.lower().replace('_', '') for key in _TAXPAYER_COLUMN_KEYS
    }


def _is_tin_column(col_name):
    return _normalize_column_key(col_name) in {
        key.lower().replace('_', '') for key in _TIN_COLUMN_KEYS
    }

def load_and_preprocess_data(input_file="main_data.csv"):
    """
    Load and preprocess the raw CIT data
    Returns: Preprocessed DataFrame
    """
    print("--- Step 1: Loading and preprocessing data ---")
    
    # Use read_parquet instead of read_excel
    cit = pd.read_csv(input_file)
    print(f"Original data shape: {cit.shape}")
    
    # Optimize column dropping - use vectorized operations
    cit = cit.copy()
    # Get list of columns to drop using faster operations
    cols_to_drop = []
    for col in cit.columns:
        col_str = str(col)
        if ('BlankLine' in col_str or 
            pd.isna(col) or 
            col_str.strip() == '' or 
            'unnamed' in col_str.lower()):
            cols_to_drop.append(col)
    
    # Drop all columns at once
    if cols_to_drop:
        cit = cit.drop(columns=cols_to_drop)
    
    print(f"After dropping empty columns: {cit.shape}")
    
    return cit

def standardize_columns(df):
    """
    Standardize column names for consistency with progress tracking
    """
    print("\n--- Step 2: Standardizing column names ---")
    
    def clean_column(col):
        if pd.isna(col):
            return 'unnamed_column'
        
        col_str = str(col)
        
        # Combine regex patterns for better performance
        col_str = re.sub(r'^[\d\s\.\-\(\):]+|[sS]\d+[A-Z]?[\.\-\s]*', '', col_str)
        
        # Replace special characters in a single pass where possible
        replacements = [
            ('/', '_or_'),
            ('-', '_'),
            ('(', '_'),
            (')', '_'),
            ('.', '_'),
            (' ', '_')
        ]
        
        for old, new in replacements:
            col_str = col_str.replace(old, new)
        
        # Clean up multiple underscores
        col_str = re.sub(r'_+', '_', col_str)
        
        # Remove leading/trailing underscores
        col_str = col_str.strip('_')
        
        # Convert to lowercase
        col_str = col_str.lower()
        
        # Ensure it's not empty
        if not col_str:
            col_str = 'unnamed_column'
        
        return col_str
    
    # Apply cleaning with progress bar
    print("Cleaning column names...")
    new_columns = []
    for col in tqdm(df.columns, desc="Processing columns", unit="col"):
        new_columns.append(clean_column(col))
    
    # Handle duplicates
    seen = {}
    final_columns = []
    
    print("Handling duplicate column names...")
    for col in tqdm(new_columns, desc="Deduplicating", unit="col"):
        if col not in seen:
            seen[col] = 1
            final_columns.append(col)
        else:
            seen[col] += 1
            final_columns.append(f"{col}_{seen[col]}")
    
    df.columns = final_columns
    
    # Drop completely empty columns if any
    df = df.dropna(axis=1, how='all')
    
    print(f"Standardized DataFrame shape: {df.shape}")
    print(f"Number of columns: {len(df.columns)}")
    
    return df

def validate_required_columns(df):
    """
    Validate that all required columns are present
    """
    print("\n--- Step 3: Validating required columns ---")
    
    required_columns = [
        'gross_sales_cash_or_credit', 'total_gross_income', 'cost_of_goods_sold', 
        'property_or_equipment', 'leasehold_improvements', 'management_fees_foreign', 
        'total_operating_expenses', 'royalties_foreign', 'advertising_and_promotion', 
        'bad_debts_written_off', 'accounts_receivable_trade', 'consultancy_fees', 
        'legal_expenses', 'repairs_and_maintenance', 'travel_and_accommodation',
        'other_gross_income', 'total_current_assets', 'prior_year_losses_utilised', 
        'interest_expense_foreign', 'interest_income', 'management_fees_png', 
        'royalties_png', 'dividend_income', 'interest_expense_png', 'loans_from_directors', 
        'other_loans', 'total_non_deductible_items', 'total_deductible_items_ex', 'gross_tax'
    ]
    
    # Convert all column names to lowercase once
    existing_columns = {col.lower(): col for col in df.columns}
    required_columns_lower = {col.lower(): col for col in required_columns}
    
    missing_columns = []
    print("Checking required columns...")
    for col_lower, col_original in tqdm(required_columns_lower.items(), 
                                        desc="Validating columns", 
                                        unit="col"):
        if col_lower not in existing_columns:
            missing_columns.append(col_original)
    
    if missing_columns:
        message = (
            "ERROR: The following required columns are missing from the CIT dataset:\n"
            f"{', '.join(missing_columns)}\n\n"
            "These columns are essential for fraud detection. "
            "Please ensure your dataset contains all required columns before proceeding."
        )
        return False, message
    
    return True, "All required columns are present."

def create_aggregated_columns(cit):
    """
    Create aggregated columns in the cit dataset if they don't already exist.
    
    Parameters:
    -----------
    cit : pandas.DataFrame
        The dataframe containing company income tax data
    
    Returns:
    --------
    pandas.DataFrame
        The dataframe with aggregated columns added
    """
    
    print("--- Creating aggregated columns ---")
    
    # Helper function to create column only if it doesn't exist
    def create_column_if_not_exists(df, col_name, col_expression):
        if col_name not in df.columns:
            df[col_name] = col_expression
            print(f"Created column: {col_name}")
        else:
            print(f"Column already exists: {col_name}")
    
    print("Checking and creating aggregated columns...")
    
    # 1. Income-related aggregations
    if 'total_sales_revenue' not in cit.columns:
        cit['total_sales_revenue'] = cit['gross_sales_cash_or_credit'] + cit['gross_contract_and_sub_con']
        print("Created column: total_sales_revenue")
    
    if 'total_distributions_royalties' not in cit.columns:
        cit['total_distributions_royalties'] = (cit['partnership_distribution_i'] + cit['distributions_from_trusts'] + 
                                                cit['oil_pipeline_tariffs_and_r'] + cit['royalty_income'])
        print("Created column: total_distributions_royalties")
    
    if 'total_investment_income' not in cit.columns:
        cit['total_investment_income'] = cit['dividend_income'] + cit['interest_income']
        print("Created column: total_investment_income")
    
    if 'total_other_income' not in cit.columns:
        cit['total_other_income'] = cit['exchange_gains_or_losses'] + cit['rental_income'] + cit['other_gross_income']
        print("Created column: total_other_income")
    
    if 'total_gross_income' not in cit.columns:
        cit['total_gross_income'] = (cit['gross_sales_cash_or_credit'] + cit['gross_contract_and_sub_con'] + 
                                    cit['partnership_distribution_i'] + cit['distributions_from_trusts'] + 
                                    cit['oil_pipeline_tariffs_and_r'] + cit['royalty_income'] + 
                                    cit['dividend_income'] + cit['interest_income'] + 
                                    cit['exchange_gains_or_losses'] + cit['rental_income'] + 
                                    cit['other_gross_income'])
        print("Created column: total_gross_income")
    
    if 'non_operating_income' not in cit.columns:
        cit['non_operating_income'] = cit['exchange_gains_or_losses'] + cit['rental_income'] + cit['other_gross_income']
        print("Created column: non_operating_income")
    
    # 2. Expense-related aggregations
    if 'total_cost_of_goods_sold' not in cit.columns:
        cit['total_cost_of_goods_sold'] = cit['cost_of_goods_sold']
        print("Created column: total_cost_of_goods_sold")
    
    if 'total_property_rental_expenses' not in cit.columns:
        cit['total_property_rental_expenses'] = cit['rented_property_expenses_i'] + cit['rental_expenses']
        print("Created column: total_property_rental_expenses")
    
    if 'total_resource_operations' not in cit.columns:
        cit['total_resource_operations'] = cit['resource_operations_joint']
        print("Created column: total_resource_operations")
    
    if 'total_depreciation_amortization' not in cit.columns:
        cit['total_depreciation_amortization'] = cit['amortisation'] + cit['depreciation']
        print("Created column: total_depreciation_amortization")
    
    if 'total_marketing_promotion' not in cit.columns:
        cit['total_marketing_promotion'] = cit['advertising_and_promotion']
        print("Created column: total_marketing_promotion")
    
    if 'total_financial_expenses' not in cit.columns:
        cit['total_financial_expenses'] = (cit['bad_debts_written_off'] + cit['borrowing_expenses'] + 
                                          cit['interest_expense_png'] + cit['interest_expense_foreign'])
        print("Created column: total_financial_expenses")
    
    if 'total_employee_expenses' not in cit.columns:
        cit['total_employee_expenses'] = (cit['contract_employees'] + cit['salaries_or_wages'] + 
                                         cit['superannuation_png'] + cit['superannuation_foreign'])
        print("Created column: total_employee_expenses")
    
    if 'total_professional_fees' not in cit.columns:
        cit['total_professional_fees'] = (cit['commissions'] + cit['consultancy_fees'] + 
                                         cit['legal_expenses'] + cit['management_fees_png'] + 
                                         cit['management_fees_foreign'])
        print("Created column: total_professional_fees")
    
    if 'total_operational_expenses' not in cit.columns:
        cit['total_operational_expenses'] = (cit['consumables'] + cit['development_levy'] + 
                                            cit['directors_fees_and_expens'] + cit['entertainment_expenses'] + 
                                            cit['foreign_exchange_losses_or'] + cit['gifts_and_donations'] + 
                                            cit['insurance'] + cit['lease_payments'] + 
                                            cit['motor_vehicle_expenses'] + cit['repairs_and_maintenance'] + 
                                            cit['royalties_png'] + cit['royalties_foreign'] + 
                                            cit['travel_and_accommodation'] + cit['all_other_expenses'])
        print("Created column: total_operational_expenses")
    
    # 3. Non-allowable expense aggregations
    if 'total_amortization_depreciation' not in cit.columns:
        cit['total_amortization_depreciation'] = cit['amortisation_charged_in_th'] + cit['depreciation_charged_in_th']
        print("Created column: total_amortization_depreciation")
    
    if 'total_non_allowable_capital_expenses' not in cit.columns:
        cit['total_non_allowable_capital_expenses'] = cit['non_allowable_capital_expe']
        print("Created column: total_non_allowable_capital_expenses")
    
    if 'total_provisions_taxes' not in cit.columns:
        cit['total_provisions_taxes'] = cit['increase_in_provisions_and'] + cit['income_tax_if_claimed_in']
        print("Created column: total_provisions_taxes")
    
    if 'total_non_allowable_donations_legal' not in cit.columns:
        cit['total_non_allowable_donations_legal'] = cit['non_allowable_donations_or'] + cit['non_allowable_legal_expens']
        print("Created column: total_non_allowable_donations_legal")
    
    if 'total_goodwill_formation_expenses' not in cit.columns:
        cit['total_goodwill_formation_expenses'] = cit['goodwill_or_formation_expe']
        print("Created column: total_goodwill_formation_expenses")
    
    if 'total_recouped_lease_premiums' not in cit.columns:
        cit['total_recouped_lease_premiums'] = cit['recouped_lease_premiums']
        print("Created column: total_recouped_lease_premiums")
    
    if 'total_excess_fees_interest' not in cit.columns:
        cit['total_excess_fees_interest'] = cit['excess_management_fees'] + cit['excess_interest_deductions']
        print("Created column: total_excess_fees_interest")
    
    if 'total_other_non_allowable_items' not in cit.columns:
        cit['total_other_non_allowable_items'] = cit['other_items_not_allowable']
        print("Created column: total_other_non_allowable_items")
    
    # 4. Tax deduction aggregations
    if 'total_non_assessable_income' not in cit.columns:
        cit['total_non_assessable_income'] = cit['non_assessable_income']
        print("Created column: total_non_assessable_income")
    
    if 'total_depreciation' not in cit.columns:
        cit['total_depreciation'] = cit['depreciation'] + cit['depreciation_charged_in_th']
        print("Created column: total_depreciation")
    
    if 'total_exploration_capital_expenditure' not in cit.columns:
        cit['total_exploration_capital_expenditure'] = (cit['allowable_exploration_dedu'] + 
                                                       cit['allowable_capital_expendit'] + 
                                                       cit['allowable_capital_expendit_2'])
        print("Created column: total_exploration_capital_expenditure")
    
    if 'total_section_specific_deductions' not in cit.columns:
        cit['total_section_specific_deductions'] = cit['section_155n_inc_deduction'] + cit['double_deductions']
        print("Created column: total_section_specific_deductions")
    
    if 'total_prior_year_losses' not in cit.columns:
        cit['total_prior_year_losses'] = cit['prior_year_losses_utilised']
        print("Created column: total_prior_year_losses")
    
    if 'total_other_deductible_items' not in cit.columns:
        cit['total_other_deductible_items'] = cit['other_tax_deductible_items'] + cit['other_tax_deductible_items_2']
        print("Created column: total_other_deductible_items")
    
    if 'total_net_exempt_income' not in cit.columns:
        cit['total_net_exempt_income'] = cit['net_exempt_income']
        print("Created column: total_net_exempt_income")
    
    if 'total_resource_royalty_dev_levy' not in cit.columns:
        cit['total_resource_royalty_dev_levy'] = cit['res_royalty_and_dev_levy']
        print("Created column: total_resource_royalty_dev_levy")
    
    # 5. Tax credit aggregations
    if 'total_dividend_rebate' not in cit.columns:
        cit['total_dividend_rebate'] = cit['dividend_rebate']
        print("Created column: total_dividend_rebate")
    
    if 'total_foreign_taxes_paid' not in cit.columns:
        cit['total_foreign_taxes_paid'] = cit['foreign_taxes_paid']
        print("Created column: total_foreign_taxes_paid")
    
    if 'total_resource_royalty_development' not in cit.columns:
        if 'resource_royalty_and_devel' in cit.columns:
            cit['total_resource_royalty_development'] = cit['resource_royalty_and_devel']
            print("Created column: total_resource_royalty_development")
        elif 'res_royalty_and_dev_levy' in cit.columns:
            # Some standardized CIT inputs retain the royalty/development value
            # only under the levy-style column name.
            cit['total_resource_royalty_development'] = cit['res_royalty_and_dev_levy']
            print("Created column: total_resource_royalty_development from res_royalty_and_dev_levy")
        else:
            cit['total_resource_royalty_development'] = 0
            print("Created column: total_resource_royalty_development with default 0")
    
    # 6. Balance sheet aggregations
    if 'total_current_assets' not in cit.columns:
        cit['total_current_assets'] = (cit['cash_or_investments'] + cit['inventory_closing_stock'] + 
                                      cit['accounts_receivable_trade'] + cit['pre_paid_expenses'] + 
                                      cit['other'])
        print("Created column: total_current_assets")
    
    if 'total_fixed_assets' not in cit.columns:
        cit['total_fixed_assets'] = (cit['property_or_equipment'] + cit['leasehold_improvements'] + 
                                    cit['equity_or_other_investments'] + cit['other_2'] + 
                                    cit['less_accumulated_depreciat'])
        print("Created column: total_fixed_assets")
    
    if 'total_current_liabilities' not in cit.columns:
        cit['total_current_liabilities'] = (cit['accounts_payable'] + cit['accrued_salary_or_wages'] + 
                                           cit['taxes_and_fees_payable'] + cit['unearned_revenue'] + 
                                           cit['other_3'])
        print("Created column: total_current_liabilities")
    
    if 'total_long_term_liabilities' not in cit.columns:
        cit['total_long_term_liabilities'] = (cit['mortgage'] + cit['loans_from_directors'] + 
                                             cit['other_loans'] + cit['other_long_term_liabilitie'])
        print("Created column: total_long_term_liabilities")
    
    if 'total_liabilities' not in cit.columns:
        cit['total_liabilities'] = (cit['accounts_payable'] + cit['accrued_salary_or_wages'] + 
                                   cit['taxes_and_fees_payable'] + cit['unearned_revenue'] + 
                                   cit['other_3'] + cit['mortgage'] + cit['loans_from_directors'] + 
                                   cit['other_loans'] + cit['other_long_term_liabilitie'])
        print("Created column: total_liabilities")
    
    # 7. Tax incentives and taxable income
    tax_incentives_columns = [
        'interest', 'a_fishing_operations', 'dividends', 'b_export_sales', 
        'i_rural_development_ince', 'n_bougainville_incentive', 'a_solar_heating', 
        'a_gifts_sporting_bodie', 'c_gifts_law_order_an', 'e_gifts_charitable_org', 
        'h_gifts_law_or_order_pr', 'i_gifts_national_day_c', 'k_gifts_png_sports_fed', 
        'm_island_forum', 'a_education_expenses_in', 'a_double_deduction_sta', 
        'c_double_deduction_exp', 'c_double_deduction_exp_2', 'depreciation_20_l', 
        'depreciation_fuel', 'depreciation_non_o', 'depreciation_non_o_2', 
        'depreciation_indus', 'depreciation_prima', 'research_or_developme', 
        'a_primary_production_dev', 'b_1_150_extension_serv', 'j_double_deduction_un', 
        'n_amortisation_explor', 'd_amortisation_explor', 'e_double_deduction_ex', 
        'j_amortisation_allowa', 'ch119_pioneer_industries', 'current_year_approved', 
        'd_expenditure_for_the_p', 'other_4'
    ]
    
    taxable_income_columns = [
        'current_year_profit_or_loss', 'loss_utilised_from_prior_y', 'taxable_income', 
        'gross_tax', 'less_other_credits_rebate', 'gross_tax_net_of_other_cre', 
        'plus_additional_profits_ta', 'total_tax_payable', 'less_infrastructure_develo', 
        'less_interest_withholding', 'less_business_payments_tax', 'total_tax_to_pay_after_in', 
        'less_prov_tax_apt', 'net_tax_payable_or_refunda', 'instalment_basis_for_futur'
    ]
    
    if 'total_tax_incentives_deductions' not in cit.columns:
        # Check if all required columns exist before summing
        existing_cols = [col for col in tax_incentives_columns if col in cit.columns]
        if existing_cols:
            cit['total_tax_incentives_deductions'] = cit[existing_cols].sum(axis=1)
            print(f"Created column: total_tax_incentives_deductions (using {len(existing_cols)} of {len(tax_incentives_columns)} columns)")
        else:
            print("Warning: None of the tax incentives columns found. Skipping total_tax_incentives_deductions")
    
    if 'total_taxable_income_tax_payable' not in cit.columns:
        # Check if all required columns exist before summing
        existing_cols = [col for col in taxable_income_columns if col in cit.columns]
        if existing_cols:
            cit['total_taxable_income_tax_payable'] = cit[existing_cols].sum(axis=1)
            print(f"Created column: total_taxable_income_tax_payable (using {len(existing_cols)} of {len(taxable_income_columns)} columns)")
        else:
            print("Warning: None of the taxable income columns found. Skipping total_taxable_income_tax_payable")
    
    # 8. Tax foregone aggregations
    section_specific_tax_foregone_columns = [
        'tax_foregone', 'tax_foregone_2', 'tax_foregone_3', 'tax_foregone_4', 
        'tax_foregone_5', 'tax_foregone_6', 'tax_foregone_7', 'tax_foregone_8', 
        'tax_foregone_9', 'd_ded_manufac', 'd_ded_tourism', 'tax_foregone_3_', 
        'tax_foregone_4_', 'tax_foregone_5_', 'tax_foregone_6_', 'tax_foregone_7_', 
        'tax_foregone_9_', 'tax_foregone_1_', 'tax_foregone_10', 'tax_foregone_1_2', 
        'tax_foregone_11', 'tax_foregone_12', 'tax_foregone_13', 'tax_foregone_14', 
        'tax_foregone_15'
    ]
    
    if 'total_section_specific_tax_foregone' not in cit.columns:
        # Check if all required columns exist before summing
        existing_cols = [col for col in section_specific_tax_foregone_columns if col in cit.columns]
        if existing_cols:
            cit['total_section_specific_tax_foregone'] = cit[existing_cols].sum(axis=1)
            print(f"Created column: total_section_specific_tax_foregone (using {len(existing_cols)} of {len(section_specific_tax_foregone_columns)} columns)")
        else:
            print("Warning: None of the section specific tax foregone columns found. Skipping total_section_specific_tax_foregone")
    
    if 'total_other_tax_foregone' not in cit.columns and 'other_tax_foregone' in cit.columns:
        cit['total_other_tax_foregone'] = cit['other_tax_foregone']
        print("Created column: total_other_tax_foregone")
    
    # 9. Directors salary and other payments
    directors_salary_columns = [
        'total_directors_fees', 'total_salary_or_wages', 'total_allowances', 'total_salary_or_wages_tax_ded'
    ]
    
    bpt_columns = [
        'total_bpt_income', 'total_bpt_tax_deducted'
    ]
    
    dividends_columns = [
        'total_dividends_paid_durin', 'total_dwt_due', 'less_dwt_paid', 'total_1_dividends_paid',
        'total_gross_dividend_or_di', 'total_dwt_deducted', 'total_dividend_foreign_tax',
        'add_dwt_or_utwt_carried_fo', 'total_2_dwt_deducted_plus', 'balance_payable_or_or_to_b'
    ]
    
    interest_withholding_tax_columns = [
        'total_gross_interest_paid', 'total_iwt_deducted', 'foreign_tax_paid_if_appli'
    ]
    
    if 'total_directors_salary_related' not in cit.columns:
        existing_cols = [col for col in directors_salary_columns if col in cit.columns]
        if existing_cols:
            cit['total_directors_salary_related'] = cit[existing_cols].sum(axis=1)
            print(f"Created column: total_directors_salary_related (using {len(existing_cols)} of {len(directors_salary_columns)} columns)")
    
    if 'total_business_payments_tax' not in cit.columns:
        existing_cols = [col for col in bpt_columns if col in cit.columns]
        if existing_cols:
            cit['total_business_payments_tax'] = cit[existing_cols].sum(axis=1)
            print(f"Created column: total_business_payments_tax (using {len(existing_cols)} of {len(bpt_columns)} columns)")
    
    if 'total_dividends' not in cit.columns:
        existing_cols = [col for col in dividends_columns if col in cit.columns]
        if existing_cols:
            cit['total_dividends'] = cit[existing_cols].sum(axis=1)
            print(f"Created column: total_dividends (using {len(existing_cols)} of {len(dividends_columns)} columns)")
    
    if 'total_interest_withholding_tax' not in cit.columns:
        existing_cols = [col for col in interest_withholding_tax_columns if col in cit.columns]
        if existing_cols:
            cit['total_interest_withholding_tax'] = cit[existing_cols].sum(axis=1)
            print(f"Created column: total_interest_withholding_tax (using {len(existing_cols)} of {len(interest_withholding_tax_columns)} columns)")
    
    # 10. Rent, royalty, management fees, superannuation, and loan payments
    rent_royalty_columns = [
        'total_total_rent_paid_duri', 'royalty_payments_tot_paid'
    ]
    
    management_foreign_shipping_columns = [
        'management_fees_tot_paid', 'foreign_shipping_tot_amo'
    ]
    
    superannuation_columns = [
        'super_total_fully_taxed', 'super_total_employer_s', 'super_total_employees', 'super_total_payouts'
    ]
    
    loan_related_columns = [
        'super_total_loan_bal_start', 'super_total_interest', 'super_total_repayments', 'super_total_loan_bal_end'
    ]
    
    if 'total_rent_royalty_payments' not in cit.columns:
        existing_cols = [col for col in rent_royalty_columns if col in cit.columns]
        if existing_cols:
            cit['total_rent_royalty_payments'] = cit[existing_cols].sum(axis=1)
            print(f"Created column: total_rent_royalty_payments (using {len(existing_cols)} of {len(rent_royalty_columns)} columns)")
    
    if 'total_management_foreign_shipping_fees' not in cit.columns:
        existing_cols = [col for col in management_foreign_shipping_columns if col in cit.columns]
        if existing_cols:
            cit['total_management_foreign_shipping_fees'] = cit[existing_cols].sum(axis=1)
            print(f"Created column: total_management_foreign_shipping_fees (using {len(existing_cols)} of {len(management_foreign_shipping_columns)} columns)")
    
    if 'total_superannuation_payments' not in cit.columns:
        existing_cols = [col for col in superannuation_columns if col in cit.columns]
        if existing_cols:
            cit['total_superannuation_payments'] = cit[existing_cols].sum(axis=1)
            print(f"Created column: total_superannuation_payments (using {len(existing_cols)} of {len(superannuation_columns)} columns)")
    
    if 'total_loan_related_payments' not in cit.columns:
        existing_cols = [col for col in loan_related_columns if col in cit.columns]
        if existing_cols:
            cit['total_loan_related_payments'] = cit[existing_cols].sum(axis=1)
            print(f"Created column: total_loan_related_payments (using {len(existing_cols)} of {len(loan_related_columns)} columns)")
    
    print("Aggregated column creation completed!")
    return cit

def enrich_taxpayer_names(df):
    """
    Enrich taxpayer names from tin_registration_mst.
    """
    print("\n--- Step 4: Enriching taxpayer names ---")

    if df is None or df.empty:
        return df

    if "tin" not in df.columns:
        raise KeyError("TIN column not found in CIT data during taxpayer enrichment.")

    try:
        from config.db_config import get_mysql_engine
        from sqlalchemy import text, bindparam
    except Exception as exc:
        raise RuntimeError("Database imports failed during taxpayer enrichment.") from exc

    def normalize_tin(series):
        normalized = (
            series.fillna("")
            .astype(str)
            .str.replace(r"\.0$", "", regex=True)
            .str.strip()
        )
        digits_only = normalized.str.replace(r"\D+", "", regex=True)
        return digits_only.apply(
            lambda value: value.zfill(9) if isinstance(value, str) and 0 < len(value) < 9 else value
        )

    def fetch_taxpayer_names(normalized_tins, chunk_size=1000):
        normalized_tins = [
            tin for tin in normalized_tins
            if isinstance(tin, str) and tin.strip()
        ]

        if not normalized_tins:
            return {}

        engine = get_mysql_engine()

        try:
            mapping = {}
            with engine.connect() as conn:
                cols = conn.execute(text("SHOW COLUMNS FROM tin_registration_mst")).fetchall()
                col_names = {str(row[0]).lower().strip() for row in cols}

                if "normalized_tin" not in col_names:
                    raise KeyError("normalized_tin column not found in tin_registration_mst.")

                if "taxpayer_name" in col_names:
                    name_col = "taxpayer_name"
                elif "taxpayername" in col_names:
                    name_col = "taxpayername"
                else:
                    raise KeyError("No taxpayer name column found in tin_registration_mst.")

                query = text(f"""
                    SELECT
                        normalized_tin,
                        {name_col} AS taxpayer_name
                    FROM tin_registration_mst
                    WHERE normalized_tin IN :tins
                """).bindparams(bindparam("tins", expanding=True))

                for start in range(0, len(normalized_tins), chunk_size):
                    chunk = normalized_tins[start:start + chunk_size]
                    rows = conn.execute(query, {"tins": chunk}).fetchall()
                    for normalized_tin, taxpayer_name in rows:
                        if normalized_tin is None or taxpayer_name is None:
                            continue
                        mapping[str(normalized_tin)] = taxpayer_name

                return mapping
        finally:
            engine.dispose()

    try:
        existing_taxpayer_cols = [
            col for col in df.columns
            if _is_taxpayer_column(col)
        ]

        df["_normalized_tin"] = normalize_tin(df["tin"])

        unique_tins = [
            tin for tin in df["_normalized_tin"].dropna().astype(str).unique().tolist()
            if tin
        ]

        global _TIN_NAME_CACHE

        try:
            _TIN_NAME_CACHE
        except NameError:
            _TIN_NAME_CACHE = {}

        missing = [tin for tin in unique_tins if tin not in _TIN_NAME_CACHE]
        if missing:
            _TIN_NAME_CACHE.update(fetch_taxpayer_names(missing))

        df["_reg_taxpayer_name"] = df["_normalized_tin"].map(_TIN_NAME_CACHE)

        if existing_taxpayer_cols:
            source_taxpayer_col = existing_taxpayer_cols[0]
            df[source_taxpayer_col] = (
                df[source_taxpayer_col]
                .replace("", pd.NA)
                .fillna(df["_reg_taxpayer_name"])
            )
            df["taxpayer_name"] = df[source_taxpayer_col]
        else:
            df["taxpayer_name"] = df["_reg_taxpayer_name"]

        duplicate_taxpayer_cols = [
            col for col in existing_taxpayer_cols
            if col != "taxpayer_name"
        ]
        if duplicate_taxpayer_cols:
            df.drop(columns=duplicate_taxpayer_cols, inplace=True, errors="ignore")

        if "taxpayer_name" not in df.columns:
            raise ValueError("taxpayer_name column was not created during taxpayer enrichment.")

        df.drop(
            columns=["_normalized_tin", "_reg_taxpayer_name"],
            inplace=True,
            errors="ignore",
        )
        return df
    except Exception as exc:
        traceback.print_exc()
        raise RuntimeError("Taxpayer enrichment failed.") from exc
def reorganize_columns(df):
    """
    Reorganize columns for better readability.
    Always output: tin, taxpayer_name, <remaining columns...>
    """
    print("\n--- Step 5: Reorganizing columns ---")

    if df is None or df.empty:
        return df

    existing_tin_col = next((col for col in df.columns if _is_tin_column(col)), None)
    if existing_tin_col is None:
        raise KeyError("TIN column not found during column reorganization.")

    if existing_tin_col != "tin":
        if "tin" in df.columns and existing_tin_col != "tin":
            raise ValueError("Multiple TIN-like columns found; cannot safely standardize to 'tin'.")
        df = df.rename(columns={existing_tin_col: "tin"})

    taxpayer_cols = [col for col in df.columns if _is_taxpayer_column(col)]
    if not taxpayer_cols:
        raise KeyError("No taxpayer column found during column reorganization.")

    if "taxpayer_name" not in df.columns:
        df = df.rename(columns={taxpayer_cols[0]: "taxpayer_name"})

    duplicate_taxpayer_cols = [
        col for col in df.columns
        if _is_taxpayer_column(col) and col != "taxpayer_name"
    ]
    if duplicate_taxpayer_cols:
        df = df.drop(columns=duplicate_taxpayer_cols, errors="ignore")

    if "taxpayer_name" not in df.columns:
        raise ValueError("taxpayer_name column missing after column reorganization.")

    other_columns = [
        col for col in df.columns
        if col not in {"tin", "taxpayer_name"}
    ]
    return df[["tin", "taxpayer_name", *other_columns]]
def main():
    """
    Main function to execute data preprocessing pipeline with overall progress tracking
    """
    print("=" * 60)
    print("Starting CIT Data Preprocessing Pipeline")
    print("=" * 60)
    
    start_time = time.time()
    
    # Create overall progress bar for major steps
    steps = [
        "Loading and preprocessing data",
        "Standardizing column names",
        "Validating required columns",
        "Creating aggregated columns",
        "Enriching taxpayer names",
        "Reorganizing columns",
        "Saving output"
    ]
    
    with tqdm(total=len(steps), desc="Overall Progress", unit="step") as pbar:
        # Step 1: Load and preprocess
        cit = load_and_preprocess_data()
        pbar.update(1)
        pbar.set_postfix_str("Step 1/7 complete")
        
        # Step 2: Standardize columns
        cit = standardize_columns(cit)
        pbar.update(1)
        pbar.set_postfix_str("Step 2/7 complete")
        
        # Step 3: Validate required columns
        is_valid, message = validate_required_columns(cit)
        if not is_valid:
            print(message)
            print("Exiting due to missing required columns.")
            return None
        pbar.update(1)
        pbar.set_postfix_str("Step 3/7 complete")
        
        # Step 4: Create aggregated columns
        cit = create_aggregated_columns(cit)
        pbar.update(1)
        pbar.set_postfix_str("Step 4/7 complete")
        
        # Step 5: Enrich taxpayer names
        cit = enrich_taxpayer_names(cit)
        pbar.update(1)
        pbar.set_postfix_str("Step 5/7 complete")
        
        # Step 6: Reorganize columns
        cit = reorganize_columns(cit)
        pbar.update(1)
        pbar.set_postfix_str("Step 6/7 complete")
        
        # Save the preprocessed data in both parquet and csv formats
        output_file_parquet = "cit_preprocessed_data.parquet"
        output_file_csv = "cit_preprocessed_data.csv"
        
        print(f"\nSaving preprocessed data to {output_file_parquet}...")
        cit.to_parquet(output_file_parquet, index=False)
        
        print(f"Saving preprocessed data to {output_file_csv}...")
        if "taxpayer_name" not in cit.columns:
            raise ValueError("taxpayer_name column missing before CSV export.")
        cit.to_csv(
            output_file_csv, 
            index=False
        )
        pbar.update(1)
        pbar.set_postfix_str("Step 7/7 complete")
    
    end_time = time.time()
    
    print(f"\n{'='*60}")
    print("--- Data Preprocessing Complete ---")
    print(f"{'='*60}")
    print(f"Preprocessed data shape: {cit.shape}")
    print(f"Number of columns: {len(cit.columns)}")
    print(f"Number of rows: {len(cit)}")
    print(f"Output saved to: {output_file_parquet} (parquet)")
    print(f"Output saved to: {output_file_csv} (csv)")
    print(f"Total processing time: {end_time - start_time:.2f} seconds")
    print(f"\nFirst few columns: {list(cit.columns[:10])}")
    
    # Show memory usage if psutil is available
    try:
        import psutil
        import os
        process = psutil.Process(os.getpid())
        print(f"Memory usage: {process.memory_info().rss / 1024 ** 2:.2f} MB")
    except ImportError:
        pass
    
    return cit

if __name__ == "__main__":
    preprocessed_data = main()



