# gst_fraud_predictor.py
import pandas as pd
import numpy as np
import joblib

def load_model_and_features(model_path='xgboost_selected_model.pkl', 
                           features_path='feature_info_selected.pkl'):
    """
    Load XGBoost model and feature information
    
    Args:
        model_path (str): Path to XGBoost model pickle file
        features_path (str): Path to feature information pickle file
        
    Returns:
        tuple: (model, feature_info)
    """
    xgb_model = joblib.load(model_path)
    feature_info = joblib.load(features_path)
    
    return xgb_model, feature_info

def prepare_features_for_prediction(new_data, feature_columns=None):
    """
    Prepare features for fraud prediction
    
    Args:
        new_data (pd.DataFrame): Input data
        feature_columns (list): List of feature columns to use
        
    Returns:
        pd.DataFrame: Prepared features
    """
    # Default feature columns if not provided
    if feature_columns is None:
        feature_columns = [
            "total_sales_income", "taxpayer_type", "exempt_sales", 
            "zero_rated_sales", "add_exempt_and_zero_rated_sales", 
            "gst_taxable_sales", "output_debits", "deferred_import_liabilities", 
            "gst_paid_on_inputs", "gst_paid_exempt_sales", "gst_paid_private", 
            "add_private_and_exempt_gst_paid", "input_credits", 
            "deduct_input_credits", "gst_payable", "gst_refundable", 
            "gst_sec65a_credit_allowable"
        ]
    
    # Select and prepare features
    new_df = new_data[feature_columns].copy()
    new_df = new_df.fillna(0)
    
    # Convert taxpayer_type to categorical
    if 'taxpayer_type' in new_df.columns:
        new_df["taxpayer_type"] = new_df["taxpayer_type"].astype('category')
    
    return new_df

def encode_features(new_df, feature_info):
    """
    Encode features for model prediction
    
    Args:
        new_df (pd.DataFrame): Prepared features
        feature_info (dict): Feature information dictionary
        
    Returns:
        np.ndarray: Encoded features for prediction
    """
    # One-hot encode categorical variables
    X_new_encoded = pd.get_dummies(new_df, drop_first=True)
    
    # Select features based on training feature names
    X_new_selected = X_new_encoded[feature_info['feature_names']].copy()
    
    # Add missing columns with zeros
    missing_cols = set(feature_info['feature_names']) - set(X_new_selected.columns)
    for col in missing_cols:
        X_new_selected[col] = 0
    
    # Ensure column order matches training
    X_new_selected = X_new_selected[feature_info['feature_names']]
    
    # Convert to numpy array
    X_new_final = X_new_selected.values
    
    return X_new_final

def predict_fraud(model, X_features, threshold=0.4):
    """
    Make fraud predictions
    
    Args:
        model: Trained XGBoost model
        X_features (np.ndarray): Features for prediction
        threshold (float): Fraud prediction threshold
        
    Returns:
        tuple: (predictions, probabilities)
    """
    # Get prediction probabilities
    fraud_probabilities = model.predict_proba(X_features)[:, 1]
    
    # Convert to labels based on threshold
    predictions = ['Fraud' if prob > threshold else 'Non-Fraud' 
                   for prob in fraud_probabilities]
    
    return predictions, fraud_probabilities

def run_fraud_prediction_pipeline(new_data_path='gst_segmented_output.parquet',
                                 model_path='xgboost_selected_model.pkl',
                                 features_path='feature_info_selected.pkl',
                                 threshold=0.4,
                                 output_base='gst_fraud_prediction'):
    """
    Run complete fraud prediction pipeline
    
    Args:
        new_data_path (str): Path to input data
        model_path (str): Path to model file
        features_path (str): Path to feature info file
        threshold (float): Fraud prediction threshold
        output_base (str): Base name for output files
        
    Returns:
        pd.DataFrame: Data with fraud predictions
    """
    # Load model and feature info
    model, feature_info = load_model_and_features(model_path, features_path)
    
    # Load new data
    new_data = pd.read_parquet(new_data_path)
    
    # Prepare features
    feature_columns = [
        "total_sales_income", "taxpayer_type", "exempt_sales", 
        "zero_rated_sales", "add_exempt_and_zero_rated_sales", 
        "gst_taxable_sales", "output_debits", "deferred_import_liabilities", 
        "gst_paid_on_inputs", "gst_paid_exempt_sales", "gst_paid_private", 
        "add_private_and_exempt_gst_paid", "input_credits", 
        "deduct_input_credits", "gst_payable", "gst_refundable", 
        "gst_sec65a_credit_allowable"
    ]
    
    new_df = prepare_features_for_prediction(new_data, feature_columns)
    
    # Encode features
    X_encoded = encode_features(new_df, feature_info)
    
    # Make predictions
    predictions, probabilities = predict_fraud(model, X_encoded, threshold)
    
    # Add predictions to original data
    new_data['predicted_fraud'] = predictions
    new_data['fraud_probability'] = probabilities
    new_data['fraud_prediction_numeric'] = (probabilities > threshold).astype(int)
    
    # Save results
    csv_output = f"{output_base}.csv"
    new_data.to_csv(csv_output, index=False)
    
    parquet_output = f"{output_base}.parquet"
    new_data.to_parquet(parquet_output, index=False)
    
    print("fraud prediction completed!")
    
    return new_data

# Helper function to get required columns
def get_required_columns():
    """Get list of columns required for fraud prediction"""
    return [
        "total_sales_income", "taxpayer_type", "exempt_sales", 
        "zero_rated_sales", "add_exempt_and_zero_rated_sales", 
        "gst_taxable_sales", "output_debits", "deferred_import_liabilities", 
        "gst_paid_on_inputs", "gst_paid_exempt_sales", "gst_paid_private", 
        "add_private_and_exempt_gst_paid", "input_credits", 
        "deduct_input_credits", "gst_payable", "gst_refundable", 
        "gst_sec65a_credit_allowable"
    ]