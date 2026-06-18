import os
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor, RandomForestClassifier
from sklearn.metrics import mean_squared_error, r2_score, accuracy_score, classification_report
import joblib

# Ensure models directory exists
os.makedirs('models', exist_ok=True)

CSV_PATH = 'house_data.csv'

def generate_synthetic_data(num_samples=1000):
    """Generates synthetic house data and saves it to a CSV file."""
    print("Generating synthetic real estate dataset...")
    np.random.seed(42)
    
    # Generate features
    square_footage = np.random.randint(800, 5000, size=num_samples)
    bedrooms = np.random.randint(1, 6, size=num_samples)
    bathrooms = np.random.randint(1, 5, size=num_samples)
    year_built = np.random.randint(1950, 2026, size=num_samples)
    location = np.random.choice(['Urban', 'Suburban', 'Rural'], size=num_samples, p=[0.35, 0.45, 0.20])
    has_garage = np.random.choice([0, 1], size=num_samples, p=[0.3, 0.7])
    
    # Compute base price with noise
    base_price = 50000
    price_per_sqft = 160
    price_per_bed = 25000
    price_per_bath = 18000
    year_factor = (year_built - 1950) * 1200
    
    loc_multipliers = {'Urban': 1.35, 'Suburban': 1.15, 'Rural': 0.85}
    loc_multiplier = np.array([loc_multipliers[l] for l in location])
    
    garage_premium = has_garage * 22000
    
    # Random noise
    noise = np.random.normal(0, 25000, size=num_samples)
    
    price = (
        base_price 
        + (square_footage * price_per_sqft) 
        + (bedrooms * price_per_bed) 
        + (bathrooms * price_per_bath) 
        + year_factor 
        + garage_premium
    ) * loc_multiplier + noise
    
    # Clean price (ensure minimum)
    price = np.clip(price, 85000, None).round(-2)
    
    # Define expensive threshold (top 30%)
    price_threshold = np.percentile(price, 70)
    is_expensive = (price >= price_threshold).astype(int)
    
    df = pd.DataFrame({
        'SquareFootage': square_footage,
        'Bedrooms': bedrooms,
        'Bathrooms': bathrooms,
        'YearBuilt': year_built,
        'Location': location,
        'HasGarage': has_garage,
        'Price': price,
        'IsExpensive': is_expensive
    })
    
    df.to_csv(CSV_PATH, index=False)
    print(f"Dataset saved to {CSV_PATH} with {num_samples} rows. Expensive threshold: ${price_threshold:,.2f}")
    return df

def train_models():
    # Load or generate dataset
    if not os.path.exists(CSV_PATH):
        df = generate_synthetic_data()
    else:
        print(f"Loading existing dataset from {CSV_PATH}...")
        df = pd.read_csv(CSV_PATH)
        
    # Split features and targets
    X = df.drop(columns=['Price', 'IsExpensive'])
    y_reg = df['Price']
    y_clf = df['IsExpensive']
    
    # Preprocessing pipeline
    numerical_cols = ['SquareFootage', 'Bedrooms', 'Bathrooms', 'YearBuilt']
    categorical_cols = ['Location']
    binary_cols = ['HasGarage']
    
    # Column transformer
    preprocessor = ColumnTransformer(
        transformers=[
            ('num', StandardScaler(), numerical_cols),
            ('cat', OneHotEncoder(drop='first', handle_unknown='ignore'), categorical_cols)
        ],
        remainder='passthrough' # For binary/HasGarage
    )
    
    # Fit preprocessor
    X_processed = preprocessor.fit_transform(X)
    
    # Split data for Regression (Price prediction)
    X_train_r, X_test_r, y_train_r, y_test_r = train_test_split(X_processed, y_reg, test_size=0.2, random_state=42)
    
    # Split data for Classification (Expensive prediction)
    X_train_c, X_test_c, y_train_c, y_test_c = train_test_split(X_processed, y_clf, test_size=0.2, random_state=42)
    
    # 1. Regressor (Price Prediction)
    print("Training RandomForestRegressor...")
    reg_model = RandomForestRegressor(n_estimators=150, max_depth=12, random_state=42)
    reg_model.fit(X_train_r, y_train_r)
    
    # Evaluate Regressor
    y_pred_r = reg_model.predict(X_test_r)
    r2 = r2_score(y_test_r, y_pred_r)
    rmse = np.sqrt(mean_squared_error(y_test_r, y_pred_r))
    print(f"Regression Performance: R2 Score = {r2:.4f}, RMSE = ${rmse:,.2f}")
    
    # 2. Classifier (Expensive / Not Expensive)
    print("Training RandomForestClassifier...")
    clf_model = RandomForestClassifier(n_estimators=100, max_depth=8, random_state=42)
    clf_model.fit(X_train_c, y_train_c)
    
    # Evaluate Classifier
    y_pred_c = clf_model.predict(X_test_c)
    acc = accuracy_score(y_test_c, y_pred_c)
    print(f"Classification Performance: Accuracy = {acc:.4f}")
    print("Classification Report:")
    print(classification_report(y_test_c, y_pred_c))
    
    # Save the models and preprocessor
    joblib.dump(reg_model, 'models/price_model.joblib')
    joblib.dump(clf_model, 'models/expensive_model.joblib')
    joblib.dump(preprocessor, 'models/preprocessor.joblib')
    print("Models and preprocessor successfully saved to 'models/' directory.")

if __name__ == '__main__':
    train_models()
