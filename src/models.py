from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# Define Episode model
# class Episode(db.Model):
#     __tablename__ = 'episodes'
#     id = db.Column(db.Integer, primary_key=True)
#     title = db.Column(db.String(64), nullable=False)
#     descr = db.Column(db.String(1024), nullable=False)
    
#     def __repr__(self):
#         return f'Episode {self.id}: {self.title}'


# A class to hold each product's information
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    product_id = db.Column(db.String)
    product_name = db.Column(db.String)
    brand_name = db.Column(db.String)

    price = db.Column(db.Float)
    value_price_usd = db.Column(db.Float)
    sale_price_usd = db.Column(db.Float)

    description = db.Column(db.Text)
    ingredients = db.Column(db.Text)

    loves_count = db.Column(db.Integer)
    rating = db.Column(db.Float)
    reviews = db.Column(db.Integer)
    review_count = db.Column(db.Integer)
    aggregate_rating = db.Column(db.Float)
    best_rating = db.Column(db.Float)

    size = db.Column(db.String)
    variation_type = db.Column(db.String)
    variation_value = db.Column(db.String)

    brand_id = db.Column(db.String)

    limited_edition = db.Column(db.Boolean)
    new = db.Column(db.Boolean)
    online_only = db.Column(db.Boolean)
    out_of_stock = db.Column(db.Boolean)
    sephora_exclusive = db.Column(db.Boolean)

    highlights = db.Column(db.Text)

    primary_category = db.Column(db.String)
    secondary_category = db.Column(db.String)
    tertiary_category = db.Column(db.String)
    category = db.Column(db.String)

    child_count = db.Column(db.Integer)
    child_max_price = db.Column(db.Float)
    child_min_price = db.Column(db.Float)

    currency = db.Column(db.String)
    label = db.Column(db.String)
    score = 0.0
    safety_score = 100.0
    flagged_ingredients = []
    good_ingredients = []

## All CSV Column Names
# product_name,brand_name,price,description, product_id, 
# brand_id,
# loves_count,rating,
# reviews != reviews_count,
# size,variation_type,variation_value,ingredients,value_price_usd,sale_price_usd,
# limited_edition,new,online_only,out_of_stock,sephora_exclusive,

# highlights,primary_category, secondary_category,

# tertiary_category,child_count,child_max_price,child_min_price,category,currency,
# review_count,
# aggregate_rating,best_rating,label


# Define Review model
class Review(db.Model):
    __tablename__ = 'reviews'
    id = db.Column(db.Integer, primary_key=True)
    reviews_count = db.Column(db.Float, nullable=False)
    
    def __repr__(self):
        return f'Review {self.id}: {self.reviews_count}'

