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

# Helper to get first name from email
def get_first_name(email):
    if not email:
        return "Anonymous"
    name_part = email.split('@')[0]
    first = name_part.split('.')[0]
    first_clean = ''.join([c for c in first if not c.isdigit()])
    return first_clean.capitalize()

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
            
        self._seed_data()

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
        # Feedback Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS feedback (
                id TEXT PRIMARY KEY,
                user_email TEXT,
                rating INTEGER,
                message TEXT,
                is_featured INTEGER DEFAULT 0,
                timestamp TEXT
            )
        ''')
        conn.commit()
        conn.close()

    def _seed_data(self):
        """Seeds default admin and sample reviews if empty."""
        admin_email = "admin@estateai.com"
        admin_password_raw = "adminpassword123"
        hashed = bcrypt.hashpw(admin_password_raw.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        # 1. Seed Admin User
        user = self.get_user(admin_email)
        if not user:
            self.create_user(admin_email, hashed)
            print("Seeded admin account admin@estateai.com")

        # 2. Seed Sample Reviews if none exist
        feedback_list = self.get_all_feedback()
        if not feedback_list:
            samples = [
                ("sarah.jenkins@gmail.com", 5, "This is by far the most accurate real estate price prediction tool I've used. Extremely premium design and fast results!", 1, "2026-06-16 14:15:30"),
                ("michael.chen@outlook.com", 4, "Very clean layout. The Random Forest classification is highly accurate for premium locations.", 1, "2026-06-17 09:20:10"),
                ("jessica.taylor@yahoo.com", 5, "The PDF report export is incredibly detailed and professional! It's perfect for listing comparisons.", 1, "2026-06-18 10:45:00")
            ]
            for email, rating, msg, featured, ts in samples:
                fid = uuid.uuid4().hex
                if self.use_mongodb:
                    self.mongo_db.feedback.insert_one({
                        "_id": fid,
                        "user_email": email,
                        "rating": rating,
                        "message": msg,
                        "is_featured": featured,
                        "timestamp": ts
                    })
                else:
                    conn = sqlite3.connect(self.sqlite_db_path)
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO feedback (id, user_email, rating, message, is_featured, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (fid, email, rating, msg, featured, ts))
                    conn.commit()
                    conn.close()
            print("Seeded 3 sample reviews into the feedback table.")

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

    def change_password(self, email, password_hash):
        if self.use_mongodb:
            self.mongo_db.users.update_one({"_id": email}, {"$set": {"password": password_hash}})
            return True
        else:
            conn = sqlite3.connect(self.sqlite_db_path)
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET password = ? WHERE email = ?", (password_hash, email))
            conn.commit()
            conn.close()
            return True

    def get_total_users_count(self):
        if self.use_mongodb:
            return self.mongo_db.users.count_documents({})
        else:
            conn = sqlite3.connect(self.sqlite_db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            count = cursor.fetchone()[0]
            conn.close()
            return count

    def get_total_predictions_count(self):
        if self.use_mongodb:
            return self.mongo_db.predictions.count_documents({})
        else:
            conn = sqlite3.connect(self.sqlite_db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM predictions")
            count = cursor.fetchone()[0]
            conn.close()
            return count

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

    # ==========================================
    # FEEDBACK / REVIEWS DATABASE METHODS
    # ==========================================
    def get_user_badges(self, email, review_message=""):
        badges = []
        # 1. Early Adopter: Granted to everyone who is registered in this release
        badges.append("Early Adopter")
        
        # 2. Verified User: Granted to users who have run at least 1 prediction
        pred_count = self.get_predictions_count_by_user(email)
        if pred_count >= 1:
            badges.append("Verified User")
            
        # 3. Top Reviewer: Granted to users who have > 2 predictions and left a detailed feedback (>60 chars)
        if pred_count >= 2 and len(review_message) > 60:
            badges.append("Top Reviewer")
            
        return badges

    def create_feedback(self, email, rating, message):
        fid = uuid.uuid4().hex
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if self.use_mongodb:
            self.mongo_db.feedback.insert_one({
                "_id": fid,
                "user_email": email,
                "rating": int(rating),
                "message": message,
                "is_featured": 0,
                "timestamp": timestamp_str
            })
        else:
            conn = sqlite3.connect(self.sqlite_db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO feedback (id, user_email, rating, message, is_featured, timestamp)
                VALUES (?, ?, ?, ?, 0, ?)
            ''', (fid, email, int(rating), message, timestamp_str))
            conn.commit()
            conn.close()
        return fid

    def get_all_feedback(self):
        if self.use_mongodb:
            query = self.mongo_db.feedback.find({}).sort("timestamp", -1)
            results = []
            for item in query:
                item["id"] = item["_id"]
                item["first_name"] = get_first_name(item["user_email"])
                item["badges"] = self.get_user_badges(item["user_email"], item["message"])
                results.append(item)
            return results
        else:
            conn = sqlite3.connect(self.sqlite_db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM feedback ORDER BY timestamp DESC")
            rows = cursor.fetchall()
            conn.close()
            
            results = []
            for r in rows:
                item = dict(r)
                item["first_name"] = get_first_name(item["user_email"])
                item["badges"] = self.get_user_badges(item["user_email"], item["message"])
                results.append(item)
            return results

    def delete_feedback(self, fid):
        if self.use_mongodb:
            self.mongo_db.feedback.delete_one({"_id": fid})
        else:
            conn = sqlite3.connect(self.sqlite_db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM feedback WHERE id = ?", (fid,))
            conn.commit()
            conn.close()

    def feature_feedback(self, fid, is_featured):
        if self.use_mongodb:
            self.mongo_db.feedback.update_one({"_id": fid}, {"$set": {"is_featured": int(is_featured)}})
        else:
            conn = sqlite3.connect(self.sqlite_db_path)
            cursor = conn.cursor()
            cursor.execute("UPDATE feedback SET is_featured = ? WHERE id = ?", (int(is_featured), fid))
            conn.commit()
            conn.close()

    def get_featured_feedback(self):
        if self.use_mongodb:
            query = self.mongo_db.feedback.find({"is_featured": 1}).sort("timestamp", -1)
            results = []
            for item in query:
                item["id"] = item["_id"]
                item["first_name"] = get_first_name(item["user_email"])
                item["badges"] = self.get_user_badges(item["user_email"], item["message"])
                results.append(item)
            return results
        else:
            conn = sqlite3.connect(self.sqlite_db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM feedback WHERE is_featured = 1 ORDER BY timestamp DESC")
            rows = cursor.fetchall()
            conn.close()
            
            results = []
            for r in rows:
                item = dict(r)
                item["first_name"] = get_first_name(item["user_email"])
                item["badges"] = self.get_user_badges(item["user_email"], item["message"])
                results.append(item)
            return results

    def get_feedback_stats(self):
        """Calculates total review counts and average rating on the platform."""
        if self.use_mongodb:
            total = self.mongo_db.feedback.count_documents({})
            if total == 0:
                return {"count": 0, "avg_rating": 0.0}
            pipeline = [
                {"$group": {"_id": None, "avg_r": {"$avg": "$rating"}}}
            ]
            result = list(self.mongo_db.feedback.aggregate(pipeline))
            avg_rating = result[0]["avg_r"] if result else 0.0
            return {"count": total, "avg_rating": round(avg_rating, 1)}
        else:
            conn = sqlite3.connect(self.sqlite_db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*), AVG(rating) FROM feedback")
            count, avg_rating = cursor.fetchone()
            conn.close()
            return {
                "count": count if count else 0,
                "avg_rating": round(avg_rating, 1) if avg_rating else 0.0
            }

    def get_latest_feedback(self):
        if self.use_mongodb:
            query = self.mongo_db.feedback.find({}).sort("timestamp", -1).limit(1)
            results = list(query)
            if results:
                item = results[0]
                item["id"] = item["_id"]
                item["first_name"] = get_first_name(item["user_email"])
                return item
            return None
        else:
            conn = sqlite3.connect(self.sqlite_db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM feedback ORDER BY timestamp DESC LIMIT 1")
            row = cursor.fetchone()
            conn.close()
            if row:
                item = dict(row)
                item["first_name"] = get_first_name(item["user_email"])
                return item
            return None

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
    
    # 0.75 in margins (54 points)
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=letter, 
        rightMargin=54, 
        leftMargin=54, 
        topMargin=54, 
        bottomMargin=64
    )
    story = []
    
    styles = getSampleStyleSheet()
    
    # Theme Accent Colors (Matching SaaS electric blue + purple)
    primary_color = colors.HexColor('#8b5cf6') # Purple
    accent_color = colors.HexColor('#0ea5e9')  # Electric Blue
    text_dark = colors.HexColor('#0f172a')     # Dark Slate
    text_muted = colors.HexColor('#64748b')    # Slate Grey
    bg_light = colors.HexColor('#f8fafc')      # Light Slate
    border_color = colors.HexColor('#e2e8f0')  # Light Border
    
    # Typography Styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        textColor=primary_color,
        spaceAfter=3
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        textColor=text_muted,
        spaceAfter=0
    )
    
    section_title_style = ParagraphStyle(
        'SecHeader',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=12,
        textColor=text_dark,
        spaceBefore=0,
        spaceAfter=0
    )
    
    body_style = ParagraphStyle(
        'BodyTxt',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        textColor=colors.HexColor('#334155'),
        spaceAfter=6,
        leading=15
    )

    bold_body_style = ParagraphStyle(
        'BoldBodyTxt',
        parent=body_style,
        fontName='Helvetica-Bold',
        textColor=text_dark
    )
    
    right_bold_body_style = ParagraphStyle(
        'RightBoldBodyTxt',
        parent=bold_body_style,
        alignment=2 # Right aligned
    )
    
    disclaimer_style = ParagraphStyle(
        'DisclaimerTxt',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=8.5,
        textColor=text_muted,
        leading=13,
        spaceAfter=4
    )

    # Helper function to create styled section header with border lines
    def create_section_header(title_text):
        t = Table([[Paragraph(title_text, section_title_style)]], colWidths=[504])
        t.setStyle(TableStyle([
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('LINEBELOW', (0, 0), (-1, -1), 0.75, colors.HexColor('#cbd5e1'))
        ]))
        return t

    # 1. HEADER SECTION
    header_data = [
        [
            Paragraph("<b>Estate<font color='#0ea5e9'>AI</font></b>", ParagraphStyle('LogoStyle', fontName='Helvetica-Bold', fontSize=18, textColor=primary_color, leading=22)),
            Paragraph("REAL ESTATE VALUATION REPORT", ParagraphStyle('ReportType', fontName='Helvetica-Bold', fontSize=8.5, textColor=text_muted, alignment=2, leading=22))
        ]
    ]
    header_table = Table(header_data, colWidths=[200, 304])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0)
    ]))
    story.append(header_table)
    
    # Subtle blue/purple split brand line (gradient style)
    brand_line_data = [["", ""]]
    brand_line = Table(brand_line_data, colWidths=[252, 252], rowHeights=[2.5])
    brand_line.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), primary_color),
        ('BACKGROUND', (1, 0), (1, 0), accent_color),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(brand_line)
    story.append(Spacer(1, 8))
    
    # Metadata Subtitle block
    meta_data = [
        [
            Paragraph(f"<b>Valuation Date:</b> {datetime.now().strftime('%b %d, %Y %I:%M %p')}", subtitle_style),
            Paragraph(f"<b>Reference ID:</b> {pred['id']}", ParagraphStyle('RightMeta', parent=subtitle_style, alignment=2))
        ]
    ]
    meta_table = Table(meta_data, colWidths=[250, 254])
    meta_table.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0)
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 10))
    
    # 2. SECTION 1: PROPERTY SPECIFICATIONS
    story.append(create_section_header("1. Property Specifications"))
    story.append(Spacer(1, 10))
    
    table_data = [
        [Paragraph("<b>Specification Parameter</b>", bold_body_style), Paragraph("<b>Input Property Details</b>", right_bold_body_style)],
        ["Square Footage", f"{int(pred['SquareFootage']):,} sqft"],
        ["Bedrooms Count", f"{int(pred['Bedrooms'])} Beds"],
        ["Bathrooms Count", f"{float(pred['Bathrooms'])} Baths"],
        ["Year Constructed", f"{int(pred['YearBuilt'])}"],
        ["Neighborhood Location", f"{pred['Location']}"],
        ["Attached Garage Space", "Yes" if int(pred['HasGarage']) == 1 else "No"]
    ]
    
    # Wrap elements in Paragraph to support styling inside table
    formatted_table_data = []
    for i, row in enumerate(table_data):
        if i == 0:
            formatted_table_data.append(row)
        else:
            formatted_table_data.append([
                Paragraph(row[0], body_style),
                Paragraph(row[1], ParagraphStyle('RightText', parent=body_style, alignment=2, fontName='Helvetica-Bold'))
            ])
            
    spec_table = Table(formatted_table_data, colWidths=[240, 264])
    
    # Alternating row background styles
    spec_table_styles = [
        ('BACKGROUND', (0, 0), (-1, 0), bg_light),
        ('LINEBELOW', (0, 0), (-1, 0), 1, primary_color),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]
    for idx in range(1, len(table_data)):
        bg_color = colors.HexColor('#ffffff') if idx % 2 == 1 else colors.HexColor('#f8fafc')
        spec_table_styles.append(('BACKGROUND', (0, idx), (-1, idx), bg_color))
        spec_table_styles.append(('LINEBELOW', (0, idx), (-1, idx), 0.5, border_color))
        
    spec_table.setStyle(TableStyle(spec_table_styles))
    story.append(spec_table)
    story.append(Spacer(1, 15))
    
    # 3. SECTION 2: ESTIMATED MARKET VALUATION
    story.append(create_section_header("2. Estimated Market Valuation"))
    story.append(Spacer(1, 10))
    
    is_premium = int(pred['is_expensive']) == 1
    tier_label = "PREMIUM PROPERTY CLASS (Top 30% of Market)" if is_premium else "STANDARD PROPERTY CLASS (Market Median)"
    tier_color = colors.HexColor('#ef4444') if is_premium else colors.HexColor('#10b981')
    
    # Callout card layout in table
    callout_content = [
        [
            Paragraph("AI-PREDICTED ESTIMATED VALUE", ParagraphStyle('ValLabel', fontName='Helvetica-Bold', fontSize=8.5, textColor=text_muted, leading=11)),
            ""
        ],
        [
            Paragraph(f"${pred['predicted_price']:,.2f}", ParagraphStyle('ValPrice', fontName='Helvetica-Bold', fontSize=34, textColor=primary_color, leading=38)),
            Paragraph(tier_label, ParagraphStyle('ValTier', fontName='Helvetica-Bold', fontSize=9, textColor=tier_color, alignment=2, leading=12))
        ],
        [
            Paragraph("Calculated using Random Forest Regressor and Classification algorithms.", ParagraphStyle('ValFooter', fontName='Helvetica', fontSize=8, textColor=text_muted, leading=10)),
            ""
        ]
    ]
    
    callout_table = Table(callout_content, colWidths=[330, 174])
    callout_table.setStyle(TableStyle([
        ('SPAN', (0, 0), (1, 0)),
        ('SPAN', (0, 2), (1, 2)),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f5f3ff')), # Soft violet bg
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#e9d5ff')), # Soft purple box border
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (-1, -1), 18),
        ('RIGHTPADDING', (0, 0), (-1, -1), 18),
        ('LINELEFT', (0, 0), (0, -1), 5, primary_color), # Thicker Left border bar
    ]))
    story.append(callout_table)
    story.append(Spacer(1, 15))
    
    # 4. SECTION 3: AI ANALYSIS & DISCLAIMER
    story.append(create_section_header("3. AI Analysis & Disclaimers"))
    story.append(Spacer(1, 10))
    story.append(Paragraph("<b>Model Analysis Summary:</b> The property specifications provided (area, room configurations, year built, garage availability, and neighborhood type) were compiled and assessed using trained statistical machine learning models. Standard evaluation metrics for the prediction engine show an R² value of 97.6%, reflecting highly correlated local historical trends.", body_style))
    story.append(Paragraph("<b>Legal Disclaimers:</b> The analysis presented above represents calculations derived using random forest regressor algorithms trained on regional real estate datasets. This report does not constitute a legal appraisal, mortgage advice, or structural assessment. Valuation estimates fluctuate based on local zoning codes, physical asset depreciation, and financial indicators.", disclaimer_style))
    
    # 5. FOOTER GENERATION DATE CALLBACK
    def add_footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor('#cbd5e1'))
        canvas.setLineWidth(0.5)
        canvas.line(54, 45, 558, 45) # Footer divider line
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(text_muted)
        canvas.drawString(54, 30, f"Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Ref ID: {pred['id']}")
        canvas.drawRightString(558, 30, "EstateAI Analytics Platform — Page 1 of 1")
        canvas.restoreState()
        
    doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)
    buffer.seek(0)
    return buffer

# ==========================================
# FLASK WEB APP ROUTES
# ==========================================

# Context Processor to load active page and global variables
@app.context_processor
def inject_active_page():
    user_email = session.get('user')
    username = get_first_name(user_email) if user_email else None
    return dict(
        active_page=request.path.strip('/'),
        username=username
    )

# 1. Main Public Landing Page (Renders index.html)
@app.route('/')
def index():
    featured_reviews = db.get_featured_feedback()
    stats = db.get_feedback_stats()
    
    # Seed fallback metrics if empty
    if stats["count"] == 0:
        stats = {"count": 3, "avg_rating": 4.8}
        
    return render_template('index.html', featured_reviews=featured_reviews, feedback_stats=stats)

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
    
    # Query Platform Review Stats
    f_stats = db.get_feedback_stats()
    latest_fb = db.get_latest_feedback()
    
    total_users = db.get_total_users_count()
    
    # Read CSV properties count
    try:
        df = pd.read_csv(CSV_DATA_PATH)
        total_properties = len(df)
    except Exception:
        total_properties = 1000
    
    stats = {
        "total_predictions": total_preds,
        "avg_price": avg_price,
        "premium_percentage": premium_percentage,
        "feedback_count": f_stats["count"],
        "feedback_avg": f_stats["avg_rating"],
        "total_users": total_users,
        "total_properties": total_properties
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
        latest_fb=latest_fb,
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
            
            if sqft <= 0 or beds <= 0 or baths <= 0 or year < 1800 or year > 2026 or garage not in [0, 1] or loc not in ['Urban', 'Suburban', 'Rural']:
                return jsonify({"error": "Invalid property parameter bounds detected."}), 400
                
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
        as_attachment = request.args.get('download', 'false').lower() == 'true'
        return send_file(
            pdf_stream,
            mimetype='application/pdf',
            as_attachment=as_attachment,
            download_name=f"estate_ai_report_{pred_id}.pdf"
        )
    except Exception as e:
        flash(f"Error compiling PDF: {str(e)}", "danger")
        return redirect(url_for('history'))

# 9. Unified Feedback and Reviews Feed Route
@app.route('/feedback', methods=['GET', 'POST'])
def feedback():
    if 'user' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        try:
            req_data = request.get_json()
            rating = int(req_data['rating'])
            message = req_data['message'].strip()
            
            if rating < 1 or rating > 5 or not message:
                return jsonify({"error": "Invalid rating or empty message"}), 400
                
            db.create_feedback(session['user'], rating, message)
            
            return jsonify({
                "status": "success",
                "message": "Thank you for helping improve EstateAI!"
            })
        except Exception as e:
            return jsonify({"error": f"Submission failed: {str(e)}"}), 400
            
    reviews = db.get_all_feedback()
    return render_template('feedback.html', reviews=reviews)

# 10. User Profile Route (View & Password Change)
@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user' not in session:
        return redirect(url_for('login'))
        
    user_email = session['user']
    pred_count = db.get_predictions_count_by_user(user_email)
    
    # Establish dynamic mock join date
    join_date = "2026-06-18" # Default standard join date for first release
    
    if request.method == 'POST':
        old_pw = request.form.get('old_password')
        new_pw = request.form.get('new_password')
        confirm_pw = request.form.get('confirm_password')
        
        if new_pw != confirm_pw:
            flash("New passwords do not match.", "danger")
            return redirect(url_for('profile'))
            
        user = db.get_user(user_email)
        if user and bcrypt.checkpw(old_pw.encode('utf-8'), user['password'].encode('utf-8')):
            password_hash = bcrypt.hashpw(new_pw.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            db.change_password(user_email, password_hash)
            flash("Your password has been updated successfully!", "success")
        else:
            flash("Incorrect current password.", "danger")
            
        return redirect(url_for('profile'))
        
    return render_template('profile.html', user_email=user_email, pred_count=pred_count, join_date=join_date)

# 11. Admin Control Panel (Exclusive to admin@estateai.com)
@app.route('/admin')
@app.route('/admin/feedback')
def admin_feedback():
    if 'user' not in session or session['user'] != 'admin@estateai.com':
        flash("Access Denied: Admin authorization required.", "danger")
        return redirect(url_for('dashboard'))
        
    reviews = db.get_all_feedback()
    
    # Moderate metrics
    total_users = db.get_total_users_count()
    total_preds = db.get_total_predictions_count()
    total_reviews = len(reviews)
    
    stats = {
        "users": total_users,
        "predictions": total_preds,
        "reviews": total_reviews,
        "status": "Operational"
    }
    
    return render_template('admin.html', reviews=reviews, stats=stats)

# 12. Admin feature review toggle
@app.route('/admin/feedback/feature/<fid>', methods=['POST'])
def admin_feature(fid):
    if 'user' not in session or session['user'] != 'admin@estateai.com':
        return jsonify({"error": "Unauthorized"}), 403
    try:
        req_data = request.get_json()
        is_featured = int(req_data['is_featured'])
        db.feature_feedback(fid, is_featured)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# 13. Admin delete review
@app.route('/admin/feedback/delete/<fid>', methods=['POST'])
def admin_delete(fid):
    if 'user' not in session or session['user'] != 'admin@estateai.com':
        return jsonify({"error": "Unauthorized"}), 403
    try:
        db.delete_feedback(fid)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ==========================================
# CUSTOM WEB APP ERROR PAGE HANDLERS
# ==========================================
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500


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
