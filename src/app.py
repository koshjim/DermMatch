import json
import os
import csv
import re
from dotenv import load_dotenv
from flask import Flask
# from fastapi import FastAPI

load_dotenv()
from flask_cors import CORS
from models import db, Product, Review
from routes import register_routes

# src/ directory and project root (one level up)
current_directory = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_directory)

# app = FastAPI()

# Serve React build files from <project_root>/frontend/dist
app = Flask(__name__,
    static_folder=os.path.join(project_root, 'frontend', 'dist'),
    static_url_path='')
CORS(app)

# Configure SQLite database - using 3 slashes for relative path
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///data.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False


# Initialize database with app
db.init_app(app)

# Register routes
register_routes(app)

# score_name = "My Score"

# @app.get("/score")
# def get_score_name():
#     return {"Similarity Score": score_name}

# Function to initialize database, change this to your own database initialization logic
def to_bool(val):
    return str(val).lower() in ["true", "1", "yes"]

def to_float(val):
    try:
        return float(val)
    except:
        return None

def to_int(val):
    try:
        return int(float(val))
    except:
        return None

def get_chemical_frequency():
    file_path = os.path.join(current_directory, 'makeupchemicalscleaned.csv')
    chemical_counts = {}

    if os.path.exists(file_path):
        with open(file_path, newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                name = row.get('ChemicalName')
                if name:
                    chemical_counts[name] = chemical_counts.get(name, 0) + 1
    
    return list(chemical_counts.items())

def init_db():
    with app.app_context():
        db.create_all()

        if Product.query.count() == 0:
            file_path = os.path.join(current_directory, 'final_merged_dataset.csv')

            with open(file_path, newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)

                for row in reader:
                    # Clean description: remove "Shop..." sentences and specific phrases
                    desc = row.get('description') or ""
                    desc = re.sub(r'(?i)shop[^.]*\.\s*', '', desc)
                    desc = re.sub(r'(?i)what\s+it\s+is:\s*', ' ', desc)
                    desc = re.sub(r'(?i)what\s+is\s+it\s+formulated\s+to\s+do:\s*', ' ', desc)
                    desc = re.sub(r'\s+', ' ', desc).strip()

                    # Clean highlights: remove quotes and brackets
                    high = (row.get('highlights') or "").replace('[', '').replace(']', '').replace("'", "")

                    # Clean category: replace dashes with spaces
                    cat = (row.get('category') or "").replace('-', ' ')

                    product = Product(
                        product_id=row.get('product_id'),
                        product_name=row.get('product_name'),
                        brand_name=row.get('brand_name'),

                        price=to_float(row.get('price')),
                        value_price_usd=to_float(row.get('value_price_usd')),
                        sale_price_usd=to_float(row.get('sale_price_usd')),

                        description=desc,
                        ingredients=row.get('ingredients'),

                        loves_count=to_int(row.get('loves_count')),
                        rating=to_float(row.get('rating')),
                        reviews=to_int(row.get('reviews')),
                        review_count=to_int(row.get('review_count')),
                        aggregate_rating=to_float(row.get('aggregate_rating')),
                        best_rating=to_float(row.get('best_rating')),

                        size=row.get('size'),
                        variation_type=row.get('variation_type'),
                        variation_value=row.get('variation_value'),

                        brand_id=row.get('brand_id'),

                        limited_edition=to_bool(row.get('limited_edition')),
                        new=to_bool(row.get('new')),
                        online_only=to_bool(row.get('online_only')),
                        out_of_stock=to_bool(row.get('out_of_stock')),
                        sephora_exclusive=to_bool(row.get('sephora_exclusive')),

                        highlights=high,

                        primary_category=row.get('primary_category'),
                        secondary_category=row.get('secondary_category'),
                        tertiary_category=row.get('tertiary_category'),
                        category=cat,

                        child_count=to_int(row.get('child_count')),
                        child_max_price=to_float(row.get('child_max_price')),
                        child_min_price=to_float(row.get('child_min_price')),

                        currency=row.get('currency'),
                        label=row.get('label'),
                        score=0.0,
                        safety_score=100.0,
                        flagged_ingredients=[]
                    )

                    db.session.add(product)

            db.session.commit()
            print("Database initialized with products CSV data")


init_db()

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=5001)
