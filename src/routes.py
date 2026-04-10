"""
Routes: React app serving and episode search API.

To enable AI chat, set USE_LLM = True below. See llm_routes.py for AI code.
"""
import json
import os
import csv
import re
from functools import lru_cache
import pandas as pd
import numpy as np
from flask import send_from_directory, request, jsonify
from models import db, Product, Review
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.decomposition import TruncatedSVD
from sklearn.preprocessing import normalize

# ── AI toggle ────────────────────────────────────────────────────────────────
USE_LLM = False
# USE_LLM = True
# ─────────────────────────────────────────────────────────────────────────────


def clean_product_description(text):
    if not text:
        return ""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    kept = [
        s for s in sentences
        if not re.search(r'(?i)\bat\s+sephora[.!?]*\s*$', s.strip())
    ]
    cleaned = " ".join(kept)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    # Drop placeholder/noise descriptions like "wf", "n/a", "--", etc.
    cleaned_norm = normalize_search_text(cleaned)
    placeholder_values = {
        "na", "n a", "n\a", "none", "null", "unknown", "tbd", "wf", "-", "--"
    }
    if cleaned_norm in placeholder_values:
        return ""

    words = [w for w in cleaned_norm.split() if w]
    if len(cleaned_norm) < 4:
        return ""
    if len(words) <= 2 and len(cleaned_norm) <= 12:
        return ""

    return cleaned


def normalize_search_text(text):
    if not text:
        return ""
    text = re.sub(r"[^a-zA-Z0-9\s]", " ", str(text).lower())
    text = re.sub(r"\s+", " ", text).strip()
    return text


def stem_search_word(word):
    word = re.sub(r"[^a-z0-9]", "", str(word).lower())
    if len(word) <= 3:
        return word

    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("sses"):
        return word[:-2]
    if word.endswith("xes") or word.endswith("ches") or word.endswith("shes") or word.endswith("zes"):
        return word[:-2]
    if word.endswith("ing") and len(word) > 5:
        return word[:-3]
    if word.endswith("ed") and len(word) > 4:
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def tokenize_and_stem(text):
    normalized = normalize_search_text(text)
    if not normalized:
        return []
    return [stem_search_word(token) for token in normalized.split() if token]


def levenshtein_distance(left, right):
    left = left or ""
    right = right or ""
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)

    previous_row = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current_row = [i]
        for j, right_char in enumerate(right, start=1):
            insert_cost = current_row[j - 1] + 1
            delete_cost = previous_row[j] + 1
            replace_cost = previous_row[j - 1] + (left_char != right_char)
            current_row.append(min(insert_cost, delete_cost, replace_cost))
        previous_row = current_row
    return previous_row[-1]


def words_match(query_word, candidate_word):
    query_word = stem_search_word(query_word)
    candidate_word = stem_search_word(candidate_word)
    if not query_word or not candidate_word:
        return False
    if query_word == candidate_word:
        return True

    distance_limit = 1 if max(len(query_word), len(candidate_word)) <= 5 else 2
    return levenshtein_distance(query_word, candidate_word) <= distance_limit



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
            'description': clean_product_description(product.description),
        })
    return matches

score_name = []


@lru_cache(maxsize=1)
def load_skin_condition_rules():
    """
    Load skin condition ingredient guidance from CSV once and cache it.
    Returns dictionaries for condition -> good/bad ingredient lists,
    plus global ingredient lexicons for query intent extraction.
    """
    current_directory = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(current_directory, 'ingredients_skin_conditions.csv')

    condition_rules = {}
    alias_to_condition = {}
    all_good_terms = set()
    all_bad_terms = set()

    if not os.path.exists(file_path):
        return {
            'condition_rules': condition_rules,
            'alias_to_condition': alias_to_condition,
            'all_good_terms': all_good_terms,
            'all_bad_terms': all_bad_terms,
        }

    with open(file_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            raw_condition = (row.get('Skin_Condition/Concern') or '').strip()
            if not raw_condition:
                continue

            aliases = [c.strip() for c in raw_condition.split(',') if c.strip()]
            canonical_condition = aliases[0].lower()

            good_ingredients = [
                x.strip().lower()
                for x in (row.get('Good_Ingredients') or '').replace('\n', ',').split(',')
                if x.strip()
            ]
            bad_ingredients = [
                x.strip().lower()
                for x in (row.get('Bad_Ingredients') or '').replace('\n', ',').split(',')
                if x.strip()
            ]

            if canonical_condition not in condition_rules:
                condition_rules[canonical_condition] = {'good': set(), 'bad': set()}
            condition_rules[canonical_condition]['good'].update(good_ingredients)
            condition_rules[canonical_condition]['bad'].update(bad_ingredients)

            for alias in aliases:
                alias_to_condition[alias.lower()] = canonical_condition

            all_good_terms.update(good_ingredients)
            all_bad_terms.update(bad_ingredients)

    return {
        'condition_rules': condition_rules,
        'alias_to_condition': alias_to_condition,
        'all_good_terms': all_good_terms,
        'all_bad_terms': all_bad_terms,
    }


def _ingredients_present(ingredients_text, candidates):
    """Return candidate terms that appear in the product ingredient text."""
    if not ingredients_text or not candidates:
        return set()

    ingredients_norm = normalize_search_text(ingredients_text)
    matched = set()
    for term in candidates:
        term_norm = normalize_search_text(term)
        if term_norm and term_norm in ingredients_norm:
            matched.add(term)
    return matched


def parse_query_skin_context(query):
    """
    Extract condition-aware and ingredient-intent signals from the query.
    - Detects mentioned skin conditions using aliases from CSV.
    - Detects direct ingredient preferences/avoidance (e.g. "with niacinamide", "avoid fragrance").
    """
    rules = load_skin_condition_rules()
    normalized_query = normalize_search_text(query)

    detected_conditions = set()
    for alias, canonical in rules['alias_to_condition'].items():
        alias_norm = normalize_search_text(alias)
        if alias_norm and re.search(rf'\b{re.escape(alias_norm)}\b', normalized_query):
            detected_conditions.add(canonical)

    prefer_markers = ('with ', 'contains ', 'good for ', 'best for ', 'help ', 'helps ', 'for ')
    avoid_markers = ('without ', 'avoid ', 'no ', 'free of ', 'exclude ', 'exclude ')
    wants_prefer = any(marker in normalized_query for marker in prefer_markers)
    wants_avoid = any(marker in normalized_query for marker in avoid_markers)

    preferred_ingredients = set()
    avoided_ingredients = set()

    # Only include terms present in the user query to keep intent explicit.
    all_known_terms = rules['all_good_terms'].union(rules['all_bad_terms'])
    for term in all_known_terms:
        term_norm = normalize_search_text(term)
        if term_norm and re.search(rf'\b{re.escape(term_norm)}\b', normalized_query):
            if wants_avoid:
                avoided_ingredients.add(term)
            elif wants_prefer:
                preferred_ingredients.add(term)

    condition_good = set()
    condition_bad = set()
    for condition in detected_conditions:
        condition_good.update(rules['condition_rules'].get(condition, {}).get('good', set()))
        condition_bad.update(rules['condition_rules'].get(condition, {}).get('bad', set()))

    preferred_ingredients.update(condition_good)
    avoided_ingredients.update(condition_bad)

    return {
        'detected_conditions': detected_conditions,
        'preferred_ingredients': preferred_ingredients,
        'avoided_ingredients': avoided_ingredients,
    }

def get_chemical_frequency():
    current_directory = os.path.dirname(os.path.abspath(__file__))
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

def ranked_product_search(query, category='', min_price=None, max_price=None, min_rating=None, sort_by='relevance'):
    global score_name
    if not query or not query.strip():
        return []

    normalized_query = normalize_search_text(query)
    query_skin_context = parse_query_skin_context(query)

    # Expand query for retrieval using condition + ingredient guidance.
    expansion_terms = sorted(query_skin_context['detected_conditions']) + sorted(query_skin_context['preferred_ingredients'])
    expanded_query_text = " ".join([normalized_query] + expansion_terms).strip()

    # Keep original tokens for name/token coverage checks.
    raw_query_tokens = tokenize_and_stem(normalized_query)
    query_tokens = tokenize_and_stem(expanded_query_text)
    
    MIN_MATCH_SCORE = 0.20
    MIN_BASE_SIMILARITY = 0.02
    MIN_TFIDF_SIMILARITY = 0.003
    MIN_SVD_SIMILARITY = 0.05

    products = Product.query.all()

    # Filter out perfumes and hair products (identified by "All Hair Types" tag)
    products = [p for p in products if (p.category or '').lower() != 'perfume' and 'All Hair Types' not in (p.highlights or '')]

    chem_freq = get_chemical_frequency()
    max_chem_freq = max([freq for name, freq in chem_freq]) if chem_freq else 1

    # ---- Build text corpus ----
    corpus = []
    for p in products:
        text = f"{p.product_name or ''} {p.brand_name or ''} {p.primary_category or ''} {p.secondary_category or ''} {p.category or ''} {p.description or ''} {p.ingredients or ''}"
        corpus.append(" ".join(tokenize_and_stem(text)))

    # ---- TF-IDF ----
    vectorizer = TfidfVectorizer(stop_words='english')
    tfidf_matrix = vectorizer.fit_transform(corpus)

    query_vec = vectorizer.transform([" ".join(query_tokens)])

    # ---- Cosine similarity (baseline lexical relevance) ----
    tfidf_similarities = cosine_similarity(query_vec, tfidf_matrix).flatten()

    # ---- LSA via SVD (semantic relevance) ----
    # This projects TF-IDF vectors into a lower-dimensional latent space,
    # improving matching for related terms that may not share exact words.
    max_components = min(tfidf_matrix.shape[0] - 1, tfidf_matrix.shape[1] - 1, 150)
    svd_similarities = np.zeros_like(tfidf_similarities)
    if max_components >= 2:
        svd = TruncatedSVD(n_components=max_components, random_state=42)
        doc_lsa = svd.fit_transform(tfidf_matrix)
        query_lsa = svd.transform(query_vec)

        doc_lsa = normalize(doc_lsa)
        query_lsa = normalize(query_lsa)
        svd_similarities = cosine_similarity(query_lsa, doc_lsa).flatten()

    # Blend lexical + semantic signals.
    similarities = 0.45 * tfidf_similarities + 0.55 * svd_similarities

    results = []

    for i, p in enumerate(products):
        base_score = similarities[i]
        lexical_score = tfidf_similarities[i]
        semantic_score = svd_similarities[i]

        product_text_norm = normalize_search_text(
            f"{p.product_name or ''} {p.brand_name or ''} {p.primary_category or ''} {p.secondary_category or ''} {p.category or ''}"
        )
        product_name_norm = normalize_search_text(p.product_name or "")
        product_tokens = tokenize_and_stem(
            f"{p.product_name or ''} {p.brand_name or ''} {p.primary_category or ''} {p.secondary_category or ''} {p.category or ''} {p.description or ''} {p.ingredients or ''}"
        )

        cleaned_query_matches_name = bool(normalized_query and normalized_query in product_text_norm)
        query_token_coverage = 0.0
        if raw_query_tokens:
            matched_tokens = sum(
                1 for token in raw_query_tokens
                if any(words_match(token, candidate) for candidate in product_tokens)
            )
            query_token_coverage = matched_tokens / len(raw_query_tokens)

        fuzzy_name_match = False
        if raw_query_tokens and product_tokens:
            fuzzy_name_match = all(
                any(words_match(token, candidate) for candidate in product_tokens)
                for token in raw_query_tokens
            )

        # Require some query relevance before adding quality boosts.
        if base_score < MIN_BASE_SIMILARITY:
            continue
        if lexical_score < MIN_TFIDF_SIMILARITY and semantic_score < MIN_SVD_SIMILARITY:
            continue

        # Strong boost when the cleaned query is a direct phrase match in the product text.
        if cleaned_query_matches_name or fuzzy_name_match:
            base_score = max(base_score, 1.0 + query_token_coverage)
        elif query_token_coverage > 0:
            base_score = max(base_score, query_token_coverage)

        # ---- Boost 1: name + brand match (strong weight) ----
        name_brand_text = normalize_search_text(f"{p.product_name or ''} {p.brand_name or ''}")
        if normalized_query and normalized_query in name_brand_text:
            base_score *= 2.0

        # ---- Boost 2: category match ----
        category_text = normalize_search_text(f"{p.primary_category or ''} {p.secondary_category or ''} {p.category or ''}")
        if normalized_query and normalized_query in category_text:
            base_score *= 1.5

        # ---- Boost 3: rating + loves ----
        rating_boost = (p.rating or 0) / 5.0
        loves_boost = min((p.loves_count or 0) / 10000, 1)

        # ---- Safety Score ----
        safety_score = 100.0
        p.flagged_ingredients = []
        if p.ingredients:
            for chem_name, freq in chem_freq:
                if chem_name in p.ingredients:
                    p.flagged_ingredients.append(chem_name)
                    deduction = (freq / max_chem_freq) * 10
                    safety_score -= deduction
        
        p.flagged_ingredients = list(set(p.flagged_ingredients))
        p.safety_score = max(0.0, safety_score)

        # ---- Condition-aware ingredient weighting ----
        preferred_hits = _ingredients_present(p.ingredients, query_skin_context['preferred_ingredients'])
        avoided_hits = _ingredients_present(p.ingredients, query_skin_context['avoided_ingredients'])

        ingredient_alignment_multiplier = 1.0
        if preferred_hits:
            ingredient_alignment_multiplier += min(0.08 * len(preferred_hits), 0.32)
        if avoided_hits:
            ingredient_alignment_multiplier -= min(0.12 * len(avoided_hits), 0.48)
        ingredient_alignment_multiplier = max(0.30, ingredient_alignment_multiplier)

        quality_multiplier = 1.0 + 0.25 * rating_boost + 0.20 * loves_boost + 0.15 * (p.safety_score / 100.0)
        final_score = base_score * quality_multiplier * ingredient_alignment_multiplier

        results.append((final_score, p))

    if results:
        max_score = max(r[0] for r in results)
        if max_score > 0:
            results = [(score / max_score, p) for score, p in results]

    # ---- Apply filters ----
    if category:
        results = [(s, p) for s, p in results if (p.primary_category or '').lower() == category.lower()]
    if min_price is not None:
        results = [(s, p) for s, p in results if p.price is not None and p.price >= min_price]
    if max_price is not None:
        results = [(s, p) for s, p in results if p.price is not None and p.price <= max_price]
    if min_rating is not None:
        results = [(s, p) for s, p in results if p.rating is not None and p.rating >= min_rating]

    results = [(s, p) for s, p in results if s > MIN_MATCH_SCORE]
    if not results:
        return []
    
    # ---- Sort ----
    if sort_by == 'price_asc':
        results.sort(key=lambda x: x[1].price or 0)
    elif sort_by == 'price_desc':
        results.sort(key=lambda x: x[1].price or 0, reverse=True)
    elif sort_by == 'rating':
        results.sort(key=lambda x: x[1].rating or 0, reverse=True)
    elif sort_by == 'safety':
        results.sort(key=lambda x: getattr(x[1], 'safety_score', 100.0), reverse=True)
    else:
        results.sort(key=lambda x: x[0], reverse=True)

    score_name = [(score, p.product_name) for score, p in results]

    # ---- Return top results ----
    return [{
        "id": p.id,
        "name": p.product_name,
        "category": p.category,
        "brand": p.brand_name,
        "price": p.price,
        "sale_price": p.sale_price_usd,
        "rating": p.rating,
        "review_count": p.review_count,
        "loves_count": p.loves_count,
        "description": clean_product_description(p.description),
        "ingredients": p.ingredients,
        "highlights": p.highlights,
        "is_new": p.new,
        "sephora_exclusive": p.sephora_exclusive,
        "limited_edition": p.limited_edition,
        "out_of_stock": p.out_of_stock,
        "safety_score": getattr(p, "safety_score", 100.0),
        "score": score,
        "flagged_ingredients": p.flagged_ingredients
    } for score, p in results]



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
    
    @app.route("/api/categories")
    def get_categories():
        rows = db.session.query(Product.primary_category).distinct().filter(
            Product.primary_category != None, Product.primary_category != ''
        ).all()
        return jsonify(sorted([r[0] for r in rows if r[0]]))

    @app.route("/api/products/search")
    def search_products():
        q = request.args.get("q", "")
        category = request.args.get("category", "")
        min_price = request.args.get("min_price", type=float)
        max_price = request.args.get("max_price", type=float)
        min_rating = request.args.get("min_rating", type=float)
        sort_by = request.args.get("sort_by", "relevance")
        return jsonify(ranked_product_search(q, category=category, min_price=min_price, max_price=max_price, min_rating=min_rating, sort_by=sort_by))
    
    @app.get('/score')
    def get_score_name():
        return jsonify({'Similarity Score': score_name})
    

    # @app.route("/api/products")
    # def products():
    #     text = request.args.get("name", "")
    #     return jsonify(json_search(text))

    # i dont think we need this!
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
