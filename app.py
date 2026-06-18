import os
import io
import uuid
import sqlite3
from datetime import datetime
import pandas as pd
import numpy as np
import bcrypt
import joblib

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, send_file
from pymongo import MongoClient

# Initialize Flask App
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "estate-ai-premium-secret-key-12345")

# Models paths
MODEL_PRICE_PATH = 'models/price_model.joblib'
MODEL_EXPENSIVE_PATH = 'models/expensive_model.joblib'
PREPROCESSOR_PATH = 'models/preprocessor.joblib'
CSV_DATA_PATH = 'house_data.csv'

# ==========================================
# DATABASE MANAGER (MONGODB WITH SQLITE FALLBACK)
# ==========================================
class DatabaseManager:
    def __init__(self):
        self.use_mongodb = False
        self.mongo_client = None
        self.mongo_db = None
        self.sqlite_db_path = "real_estate.db"

        # Try connecting to MongoDB
        try:
            mongo_uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
            self.mongo_client = MongoClient(mongo_uri, serverSelectionTimeoutMS=2000)
            self.mongo_client.server_info() # Ping check
            self.mongo_db = self.mongo_client["real_estate_db"]
            self.use_mongodb = True
            print("Successfully connected to MongoDB!")
        except Exception as e:
            print(f"MongoDB connection failed: {e}. Falling back to SQLite.")
            self.use_mongodb = False
            self._init_sqlite()

    def _init_sqlite(self):
        conn = sqlite3.connect(self.sqlite_db_path)
        cursor = conn.cursor()
        # Users Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                password TEXT NOT NULL
            )
        ''')
        # Predictions Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS predictions (
                id TEXT PRIMARY KEY,
                user_email TEXT,
                SquareFootage REAL,
                Bedrooms INTEGER,
                Bathrooms REAL,
                YearBuilt INTEGER,
                Location TEXT,
                HasGarage INTEGER,
                predicted_price REAL,
                is_expensive INTEGER,
                timestamp TEXT
            )
        ''')
        conn.commit()
        conn.close()

    def create_user(self, email, password_hash):
        if self.use_mongodb:
            try:
                self.mongo_db.users.insert_one({
                    "_id": email,
                    "password": password_hash
                })
                return True
            except Exception:
                return False
        else:
            try:
                conn = sqlite3.connect(self.sqlite_db_path)
                cursor = conn.cursor()
                cursor.execute("INSERT INTO users (email, password) VALUES (?, ?)", (email, password_hash))
                conn.commit()
                conn.close()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_user(self, email):
        if self.use_mongodb:
            user = self.mongo_db.users.find_one({"_id": email})
            if user:
                return {"email": user["_id"], "password": user["password"]}
            return None
        else:
            conn = sqlite3.connect(self.sqlite_db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT email, password FROM users WHERE email = ?", (email,))
            row = cursor.fetchone()
            conn.close()
            if row:
                return {"email": row[0], "password": row[1]}
            return None

    def save_prediction(self, user_email, data):
        pred_id = uuid.uuid4().hex
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if self.use_mongodb:
            self.mongo_db.predictions.insert_one({
                "_id": pred_id,
                "user_email": user_email,
                "SquareFootage": float(data["SquareFootage"]),
                "Bedrooms": int(data["Bedrooms"]),
                "Bathrooms": float(data["Bathrooms"]),
                "YearBuilt": int(data["YearBuilt"]),
                "Location": data["Location"],
                "HasGarage": int(data["HasGarage"]),
                "predicted_price": float(data["predicted_price"]),
                "is_expensive": int(data["is_expensive"]),
                "timestamp": timestamp_str
            })
        else:
            conn = sqlite3.connect(self.sqlite_db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO predictions (id, user_email, SquareFootage, Bedrooms, Bathrooms, YearBuilt, Location, HasGarage, predicted_price, is_expensive, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                pred_id, user_email, float(data["SquareFootage"]), int(data["Bedrooms"]),
                float(data["Bathrooms"]), int(data["YearBuilt"]), data["Location"],
                int(data["HasGarage"]), float(data["predicted_price"]), int(data["is_expensive"]), timestamp_str
            ))
            conn.commit()
            conn.close()
        return pred_id

    def get_prediction(self, pred_id):
        if self.use_mongodb:
            item = self.mongo_db.predictions.find_one({"_id": pred_id})
            if item:
                item["id"] = item["_id"]
                return item
            return None
        else:
            conn = sqlite3.connect(self.sqlite_db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM predictions WHERE id = ?", (pred_id,))
            row = cursor.fetchone()
            conn.close()
            if row:
                return dict(row)
            return None

    def get_predictions_by_user(self, user_email, limit=None):
        if self.use_mongodb:
            query = self.mongo_db.predictions.find({"user_email": user_email}).sort("timestamp", -1)
            if limit:
                query = query.limit(limit)
            results = []
            for item in query:
                item["id"] = item["_id"]
                results.append(item)
            return results
        else:
            conn = sqlite3.connect(self.sqlite_db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            query = "SELECT * FROM predictions WHERE user_email = ? ORDER BY timestamp DESC"
            if limit:
                query += f" LIMIT {int(limit)}"
            cursor.execute(query, (user_email,))
            rows = cursor.fetchall()
            conn.close()
            return [dict(r) for r in rows]

    def get_predictions_count_by_user(self, user_email):
        if self.use_mongodb:
            return self.mongo_db.predictions.count_documents({"user_email": user_email})
        else:
            conn = sqlite3.connect(self.sqlite_db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM predictions WHERE user_email = ?", (user_email,))
            count = cursor.fetchone()[0]
            conn.close()
            return count

    def get_user_average_valuation(self, user_email):
        if self.use_mongodb:
            pipeline = [
                {"$match": {"user_email": user_email}},
                {"$group": {"_id": None, "avg_price": {"$avg": "$predicted_price"}}}
            ]
            result = list(self.mongo_db.predictions.aggregate(pipeline))
            return result[0]["avg_price"] if result else 0.0
        else:
            conn = sqlite3.connect(self.sqlite_db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT AVG(predicted_price) FROM predictions WHERE user_email = ?", (user_email,))
            val = cursor.fetchone()[0]
            conn.close()
            return val if val else 0.0

    def get_user_premium_ratio(self, user_email):
        if self.use_mongodb:
            total = self.mongo_db.predictions.count_documents({"user_email": user_email})
            if total == 0:
                return 0.0
            premium = self.mongo_db.predictions.count_documents({"user_email": user_email, "is_expensive": 1})
            return (premium / total) * 100
        else:
            conn = sqlite3.connect(self.sqlite_db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM predictions WHERE user_email = ?", (user_email,))
            total = cursor.fetchone()[0]
            if total == 0:
                conn.close()
                return 0.0
            cursor.execute("SELECT COUNT(*) FROM predictions WHERE user_email = ? AND is_expensive = 1", (user_email,))
            premium = cursor.fetchone()[0]
            conn.close()
            return (premium / total) * 100

db = DatabaseManager()

# ==========================================
# MACHINE LEARNING HELPER UTILS
# ==========================================
def get_ml_models():
    """Loads ML models & Preprocessor dynamically."""
    try:
        price_model = joblib.load(MODEL_PRICE_PATH)
        expensive_model = joblib.load(MODEL_EXPENSIVE_PATH)
        preprocessor = joblib.load(PREPROCESSOR_PATH)
        return price_model, expensive_model, preprocessor
    except Exception as e:
        print(f"Error loading models: {e}. Run training.py first.")
        return None, None, None

def get_market_analytics():
    """Extracts summary charts metrics from house_data.csv dataset."""
    try:
        df = pd.read_csv(CSV_DATA_PATH)
        
        # Location prices averages
        loc_price = df.groupby('Location')['Price'].mean().to_dict()
        price_by_location = {
            "labels": list(loc_price.keys()),
            "values": [round(v, 2) for v in loc_price.values()]
        }
        
        # Location sample counts
        loc_counts = df['Location'].value_counts().to_dict()
        distribution = {
            "labels": list(loc_counts.keys()),
            "values": [int(v) for v in loc_counts.values()]
        }
        
        return price_by_location, distribution
    except Exception as e:
        print(f"Error reading dataset: {e}")
        return {"labels": [], "values": []}, {"labels": [], "values": []}

# ==========================================
# PDF REPORT BUILDER UTILS (REPORTLAB)
# ==========================================
def generate_report_pdf(pred):
    """Compiles prediction metrics into a print-ready PDF binary stream."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=letter, 
        rightMargin=45, 
        leftMargin=45, 
        topMargin=45, 
        bottomMargin=45
    )
    story = []
    
    styles = getSampleStyleSheet()
    
    # Styles config
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=24,
        textColor=colors.HexColor('#6366f1'),
        spaceAfter=5
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        textColor=colors.HexColor('#64748b'),
        spaceAfter=25
    )
    
    section_title_style = ParagraphStyle(
        'SecHeader',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=13,
        textColor=colors.HexColor('#0c0f22'),
        spaceBefore=15,
        spaceAfter=10
    )
    
    body_style = ParagraphStyle(
        'BodyTxt',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        textColor=colors.HexColor('#475569'),
        spaceAfter=8
    )

    bold_body_style = ParagraphStyle(
        'BoldBodyTxt',
        parent=body_style,
        fontName='Helvetica-Bold'
    )
    
    price_val_style = ParagraphStyle(
        'PriceVal',
        fontName='Helvetica-Bold',
        fontSize=26,
        textColor=colors.HexColor('#14b8a6'),
        spaceAfter=4
    )
    
    # Render document elements
    story.append(Paragraph("EstateAI Valuation Report", title_style))
    story.append(Paragraph(f"Created: {datetime.now().strftime('%b %d, %Y %I:%M %p')} | Ref ID: {pred['id']}", subtitle_style))
    story.append(Spacer(1, 10))
    
    # Section: Property Specs
    story.append(Paragraph("Property Specifications", section_title_style))
    
    table_data = [
        [Paragraph("<b>Parameter</b>", bold_body_style), Paragraph("<b>Input Value</b>", bold_body_style)],
        ["Square Footage", f"{int(pred['SquareFootage']):,} sqft"],
        ["Bedrooms", f"{int(pred['Bedrooms'])} Beds"],
        ["Bathrooms", f"{float(pred['Bathrooms'])} Baths"],
        ["Year Built", f"{int(pred['YearBuilt'])}"],
        ["Neighborhood Location", f"{pred['Location']}"],
        ["Attached Garage", "Yes" if int(pred['HasGarage']) == 1 else "No"]
    ]
    
    spec_table = Table(table_data, colWidths=[200, 320])
    spec_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f8fafc')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9.5),
    ]))
    story.append(spec_table)
    story.append(Spacer(1, 20))
    
    # Section: Valuation
    story.append(Paragraph("Estimated Market Valuation", section_title_style))
    story.append(Paragraph("AI-Predicted Price Estimate", body_style))
    story.append(Paragraph(f"${pred['predicted_price']:,.2f}", price_val_style))
    
    is_premium = int(pred['is_expensive']) == 1
    tier_label = "Premium Property Class (Top 30% of Market)" if is_premium else "Standard Property Class"
    tier_color = '#f43f5e' if is_premium else '#10b981'
    
    tier_banner_style = ParagraphStyle(
        'TierBanner',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        textColor=colors.HexColor(tier_color),
        spaceAfter=15
    )
    story.append(Paragraph(f"Property Classification: {tier_label}", tier_banner_style))
    story.append(Spacer(1, 15))
    
    # Disclaimer Text
    story.append(Paragraph("<b>Disclaimers:</b> The analysis presented above represents calculations derived using random forest regressor algorithms trained on regional real estate datasets. This report does not constitute a legal appraisal, mortgage advice, or structural assessment. Valuation estimates fluctuate based on local zoning codes, physical asset depreciation, and financial indicators.", body_style))
    
    doc.build(story)
    buffer.seek(0)
    return buffer

# ==========================================
# FLASK WEB APP ROUTES
# ==========================================

# Context Processor to load active page variable
@app.context_processor
def inject_active_page():
    return dict(active_page=request.path.strip('/'))

# 1. Main Root Endpoint (Redirect to Dashboard or Login)
@app.route('/')
def index():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

# 2. Login Route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user' in session:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        email = request.form.get('email').strip().lower()
        password = request.form.get('password')
        
        user = db.get_user(email)
        if user and bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
            session['user'] = email
            flash("Welcome back! Successful login.", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid email or password. Please try again.", "danger")
            
    return render_template('login.html')

# 3. Registration Route
@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user' in session:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        email = request.form.get('email').strip().lower()
        password = request.form.get('password')
        confirm_pw = request.form.get('confirm_password')
        
        if password != confirm_pw:
            flash("Passwords do not match.", "danger")
            return render_template('register.html')
            
        # Check if email exists
        if db.get_user(email):
            flash("An account already exists with that email address.", "danger")
            return render_template('register.html')
            
        # Save User
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        if db.create_user(email, password_hash):
            flash("Account registered successfully! Please sign in.", "success")
            return redirect(url_for('login'))
        else:
            flash("Failed to register account. Database error.", "danger")
            
    return render_template('register.html')

# 4. Logout Route
@app.route('/logout')
def logout():
    session.pop('user', None)
    flash("You have logged out successfully.", "info")
    return redirect(url_for('login'))

# 5. Executive Dashboard Route
@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
        
    user_email = session['user']
    
    # Calculate User statistics
    total_preds = db.get_predictions_count_by_user(user_email)
    avg_price = db.get_user_average_valuation(user_email)
    premium_percentage = db.get_user_premium_ratio(user_email)
    
    stats = {
        "total_predictions": total_preds,
        "avg_price": avg_price,
        "premium_percentage": premium_percentage
    }
    
    # Query recent predictions list
    recent_predictions = db.get_predictions_by_user(user_email, limit=5)
    
    # Generate Chart JS config lists
    price_by_location, distribution = get_market_analytics()
    chart_data = {
        "price_by_location": price_by_location,
        "distribution": distribution
    }
    
    return render_template(
        'dashboard.html', 
        stats=stats, 
        recent_predictions=recent_predictions, 
        chart_data=chart_data
    )

# 6. Predict Calculator Route
@app.route('/predict', methods=['GET', 'POST'])
def predict():
    if 'user' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        # Retrieve JSON input fields
        try:
            req_data = request.get_json()
            
            sqft = float(req_data['SquareFootage'])
            beds = int(req_data['Bedrooms'])
            baths = float(req_data['Bathrooms'])
            year = int(req_data['YearBuilt'])
            loc = req_data['Location']
            garage = int(req_data['HasGarage'])
            
            # Retrieve Model Pipeline
            price_model, expensive_model, preprocessor = get_ml_models()
            
            if not price_model:
                return jsonify({"error": "ML Models are not initialized on the server. Please run training.py"}), 500
                
            # Parse inputs into dataframe
            input_df = pd.DataFrame([{
                'SquareFootage': sqft,
                'Bedrooms': beds,
                'Bathrooms': baths,
                'YearBuilt': year,
                'Location': loc,
                'HasGarage': garage
            }])
            
            # Preprocess
            processed_data = preprocessor.transform(input_df)
            
            # Predict reg & clf
            pred_price = float(price_model.predict(processed_data)[0])
            is_expensive = int(expensive_model.predict(processed_data)[0])
            
            # Save results
            prediction_record = {
                "SquareFootage": sqft,
                "Bedrooms": beds,
                "Bathrooms": baths,
                "YearBuilt": year,
                "Location": loc,
                "HasGarage": garage,
                "predicted_price": pred_price,
                "is_expensive": is_expensive
            }
            
            prediction_id = db.save_prediction(session['user'], prediction_record)
            
            return jsonify({
                "prediction_id": prediction_id,
                "predicted_price": pred_price,
                "is_expensive": is_expensive
            })
            
        except Exception as e:
            return jsonify({"error": f"Failed to parse inputs: {str(e)}"}), 400
            
    return render_template('predict.html')

# 7. Predictions Log History Route
@app.route('/history')
def history():
    if 'user' not in session:
        return redirect(url_for('login'))
        
    user_email = session['user']
    user_history = db.get_predictions_by_user(user_email)
    
    return render_template('history.html', history=user_history)

# 8. Download Prediction PDF report
@app.route('/prediction/<pred_id>/pdf')
def download_pdf(pred_id):
    if 'user' not in session:
        return redirect(url_for('login'))
        
    prediction = db.get_prediction(pred_id)
    if not prediction:
        flash("Property prediction records could not be found.", "danger")
        return redirect(url_for('history'))
        
    # Check if prediction belongs to the current user
    if prediction.get('user_email') != session['user']:
        flash("Access Denied: Prediction report does not belong to you.", "danger")
        return redirect(url_for('dashboard'))
        
    try:
        pdf_stream = generate_report_pdf(prediction)
        return send_file(
            pdf_stream,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"estate_ai_report_{pred_id}.pdf"
        )
    except Exception as e:
        flash(f"Error compiling PDF: {str(e)}", "danger")
        return redirect(url_for('history'))

# ==========================================
# RUN FLASK APP
# ==========================================
if __name__ == '__main__':
    # Verify model availability, train them if missing
    if not os.path.exists(MODEL_PRICE_PATH) or not os.path.exists(MODEL_EXPENSIVE_PATH):
        print("Model files not found. Initiating auto-training first...")
        from training import train_models
        train_models()
        
    print("Starting Flask Web Server...")
    app.run(host='0.0.0.0', port=5000, debug=True)
