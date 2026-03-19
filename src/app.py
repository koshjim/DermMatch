import json
import os
import csv
from dotenv import load_dotenv
from flask import Flask
from fastapi import FastAPI

load_dotenv()
from flask_cors import CORS
<<<<<<< HEAD
from models import db, Episode, Review, Product
=======
from models import db, Product, Review
>>>>>>> 3c69a1c (I changed title and app.py and models)
from routes import register_routes

# src/ directory and project root (one level up)
current_directory = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_directory)

app = FastAPI()

score_name = "My Score"

@app.get("/score")
def get_score_name():
    return {"Similarity Score": score_name}

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

<<<<<<< HEAD
        # Check if the products table is empty
        if Product.query.count() == 0:
            csv_path = os.path.join(os.path.dirname(__file__), 'final_merged_clean_skincare.csv')
            df = pd.read_csv(csv_path)

            for _, row in df.iterrows():
                product = Product(
                    product_id=int(row['product_id']),
                    product_name=row['product_name'],
                    brand_name=row['brand_name'],
                    price=float(row['price']) if not pd.isna(row['price']) else None,
                    description=row.get('description', None),
                    ingredients=row.get('ingredients', None),
                    primary_category=row.get('primary_category', None),
                    secondary_category=row.get('secondary_category', None),
                    tertiary_category=row.get('tertiary_category', None)
                )
                db.session.add(product)

            db.session.commit()
            print("Database initialized with skincare products data")
=======
        if Product.query.count() == 0:
            file_path = os.path.join(current_directory, 'final_merged_dataset.csv')

            with open(file_path, newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)

                for row in reader:
                    product = Product(
                        product_id=row.get('product_id'),
                        product_name=row.get('product_name'),
                        brand_name=row.get('brand_name'),

                        price=to_float(row.get('price')),
                        value_price_usd=to_float(row.get('value_price_usd')),
                        sale_price_usd=to_float(row.get('sale_price_usd')),

                        description=row.get('description'),
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

                        highlights=row.get('highlights'),

                        primary_category=row.get('primary_category'),
                        secondary_category=row.get('secondary_category'),
                        tertiary_category=row.get('tertiary_category'),
                        category=row.get('category'),

                        child_count=to_int(row.get('child_count')),
                        child_max_price=to_float(row.get('child_max_price')),
                        child_min_price=to_float(row.get('child_min_price')),

                        currency=row.get('currency'),
                        label=row.get('label'),
                        score=0.0,
                        safety_score=100.0
                    )

                    db.session.add(product)

            db.session.commit()
            print("Database initialized with products CSV data")
>>>>>>> 3c69a1c (I changed title and app.py and models)


init_db()

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=5001)
