"""
Routes: React app serving and episode search API.

To enable AI chat, set USE_LLM = True below. See llm_routes.py for AI code.
"""
import json
import os
from flask import send_from_directory, request, jsonify
from models import db, Product, Review

# ── AI toggle ────────────────────────────────────────────────────────────────
USE_LLM = False
# USE_LLM = True
# ─────────────────────────────────────────────────────────────────────────────


def json_search(query):
    if not query or not query.strip():
        query = "Kardashian"
    results = db.session.query(Product, Review).join(
        Review, Product.id == Review.id
    ).filter(
        Product.name.ilike(f'%{query}%')
    ).all()
    matches = []
    for product, review in results:
        matches.append({
            'name': product.name,
            'brand': product.brand,
            'rating': product.rating,
            'ingredients': product.ingredients,
            'description': product.description,
        })
    return matches




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

    @app.route("/api/products")
    def products():
        text = request.args.get("name", "")
        return jsonify(json_search(text))

    if USE_LLM:
        from llm_routes import register_chat_route
        register_chat_route(app, json_search)
