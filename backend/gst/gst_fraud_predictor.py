try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import numpy as np
except ImportError:
    np = None

try:
    import joblib
except ImportError:
    joblib = None
import pickle

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
    if joblib is not None:
        xgb_model = joblib.load(model_path)
        feature_info = joblib.load(features_path)
    else:
        with open(model_path, 'rb') as f:
            xgb_model = pickle.load(f)
        with open(features_path, 'rb') as f:
            feature_info = pickle.load(f)
    
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
    
    # Extract available columns and add any missing columns with 0
    new_df = pd.DataFrame(index=new_data.index)
    for col in feature_columns:
        if col in new_data.columns:
            new_df[col] = new_data[col]
        else:
            new_df[col] = 0
            
    new_df = new_df[feature_columns].copy()
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
    expected_features = feature_info['feature_names']

    # One-hot encode categorical variables
    X_new_encoded = pd.get_dummies(new_df, drop_first=True)

    # Ensure taxpayer_type_INDIVIDUAL is accurately computed if taxpayer_type column is present
    if 'taxpayer_type' in new_df.columns and 'taxpayer_type_INDIVIDUAL' not in X_new_encoded.columns:
        if 'taxpayer_type_INDIVIDUAL' in expected_features:
            X_new_encoded['taxpayer_type_INDIVIDUAL'] = (
                new_df['taxpayer_type'].astype(str).str.strip().str.upper() == 'INDIVIDUAL'
            ).astype(int)

    # Add any missing expected columns with zeros
    for col in expected_features:
        if col not in X_new_encoded.columns:
            X_new_encoded[col] = 0

    # Ensure exact column selection and deterministic ordering matching the training contract
    X_new_selected = X_new_encoded[expected_features].copy()

    # Ensure all columns are numeric float to prevent data type mismatch during XGBoost inference
    for col in expected_features:
        X_new_selected[col] = pd.to_numeric(X_new_selected[col], errors='coerce').fillna(0).astype(float)

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
    proba_matrix = model.predict_proba(X_features)
    if hasattr(proba_matrix, 'shape') and len(proba_matrix.shape) == 2:
        fraud_probabilities = proba_matrix[:, 1]
    else:
        fraud_probabilities = [row[1] for row in proba_matrix]
    
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