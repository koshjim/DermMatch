"""
Routes: React app serving and episode search API.

To enable AI chat, set USE_LLM = True below. See llm_routes.py for AI code.
"""
import json
import os
import pandas as pd
import numpy as np
from flask import send_from_directory, request, jsonify
from models import db, Product, Review
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# ── AI toggle ────────────────────────────────────────────────────────────────
USE_LLM = False
# USE_LLM = True
# ─────────────────────────────────────────────────────────────────────────────



def json_search(query):
    if not query or not query.strip():
        return []
    results = db.session.query(Product).filter(
        Product.product_name.ilike(f'%{query}%')
    ).all()
    matches = []
    for product in results:
        matches.append({
            'id': product.id,
            'name': product.product_name,
            'brand': product.brand_name,
            'price': product.price,
            'rating': product.rating,
            'category': product.category,
            'ingredients': product.ingredients,
            'description': product.description,
        })
    return matches

# # Use absolute path to find the CSV file
# current_directory = os.path.dirname(os.path.abspath(__file__))
# csv_path = os.path.join(current_directory, 'final_merged_dataset.csv')
# merged_df = pd.read_csv(csv_path)

# score = np.zeros(merged_df.shape[0])
score_name = []

def ranked_product_search(query):
    if not query or not query.strip():
        return []

    products = Product.query.all()

    # ---- Build text corpus ----
    corpus = []
    for p in products:
        text = f"{p.product_name or ''} {p.brand_name or ''} {p.primary_category or ''} {p.secondary_category or ''} {p.category or ''}"
        corpus.append(text.lower())

    # ---- TF-IDF ----
    vectorizer = TfidfVectorizer(stop_words='english')
    tfidf_matrix = vectorizer.fit_transform(corpus)

    query_vec = vectorizer.transform([query.lower()])

    # ---- Cosine similarity ----
    similarities = cosine_similarity(query_vec, tfidf_matrix).flatten()

    results = []

    for i, p in enumerate(products):
        base_score = similarities[i]

        # ---- Boost 1: name + brand match (strong weight) ----
        name_brand_text = f"{p.product_name} {p.brand_name}".lower()
        if query.lower() in name_brand_text:
            base_score *= 2.0

        # ---- Boost 2: category match ----
        category_text = f"{p.primary_category} {p.secondary_category} {p.category}".lower()
        if query.lower() in category_text:
            base_score *= 1.5

        # ---- Boost 3: rating + loves ----
        rating_boost = (p.rating or 0) / 5.0
        loves_boost = min((p.loves_count or 0) / 10000, 1)

        final_score = base_score + 0.3 * rating_boost + 0.3 * loves_boost
        score[p.id] = final_score

        results.append((final_score, p))

    # ---- Sort by score ----
    results.sort(key=lambda x: x[0], reverse=True)
    score_name = [(score, p.product_name) for score, p in results]

    # ---- Return top results ----
    return [{
        "id": p.id,
        "name": p.product_name,
        "category": p.category,
        "brand": p.brand_name,
        "price": p.price,
        "rating": p.rating,
        "description": p.description,
        "ingredients": p.ingredients,
        "score": p.score
    } for score, p in results[:15]]



def register_routes(app):
    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def serve(path):
        if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
            return send_from_directory(app.static_folder, path)
        else:
            return send_from_directory(app.static_folder, 'index.html')

    @app.route("/api/config")
    def config():
        return jsonify({"use_llm": USE_LLM})
    
    @app.route("/api/products/search")
    def search_products():
        q = request.args.get("q", "")
        return jsonify(ranked_product_search(q))
    
    @app.get('/score')
    def get_score_name():
        return jsonify({'Similarity Score': score_name})
    

    # @app.route("/api/products")
    # def products():
    #     text = request.args.get("name", "")
    #     return jsonify(json_search(text))

    @app.route("/api/products")
    def get_products():
        products = Product.query.limit(15).all()

        return jsonify([{
            "id": p.id,
            "name": p.product_name,
            "brand": p.brand_name,
            "price": p.price,
            "rating": p.rating
        } for p in products])

    if USE_LLM:
        from llm_routes import register_chat_route
        register_chat_route(app, json_search)
