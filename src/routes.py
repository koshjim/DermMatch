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
    current_directory = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(current_directory, 'ingredients_skin_conditions.csv')

    condition_rules = {}
    alias_to_condition = {}
    all_good_terms = set()
    all_bad_terms = set()

    if not os.path.exists(file_path):
        return {'condition_rules': condition_rules, 'alias_to_condition': alias_to_condition,
                'all_good_terms': all_good_terms, 'all_bad_terms': all_bad_terms}

    with open(file_path, newline='', encoding='utf-8') as csvfile:
        for row in csv.DictReader(csvfile):
            raw_condition = (row.get('Skin_Condition/Concern') or '').strip()
            if not raw_condition:
                continue
            aliases = [c.strip() for c in raw_condition.split(',') if c.strip()]
            canonical = aliases[0].lower()
            good = [x.strip().lower() for x in (row.get('Good_Ingredients') or '').replace('\n', ',').split(',') if x.strip()]
            bad  = [x.strip().lower() for x in (row.get('Bad_Ingredients')  or '').replace('\n', ',').split(',') if x.strip()]

            condition_rules.setdefault(canonical, {'good': set(), 'bad': set()})
            condition_rules[canonical]['good'].update(good)
            condition_rules[canonical]['bad'].update(bad)
            for alias in aliases:
                alias_to_condition[alias.lower()] = canonical
            all_good_terms.update(good)
            all_bad_terms.update(bad)

    return {'condition_rules': condition_rules, 
            'alias_to_condition': alias_to_condition,
            'all_good_terms': all_good_terms, 
            'all_bad_terms': all_bad_terms}


def _ingredients_present(ingredients_text, candidates):
    if not ingredients_text or not candidates:
        return set()
    ingredients_norm = normalize_search_text(ingredients_text)
    return {term for term in candidates if normalize_search_text(term) and normalize_search_text(term) in ingredients_norm}

CATEGORY_KEYWORDS = {
    'cleanser':    ['cleanser', 'cleanse', 'face wash', 'foaming wash', 'facewash'],
    'moisturizer': ['moisturizer', 'moisturize', 'moisturiser', 'lotion', 'cream', 'hydrator'],
    'serum':       ['serum', 'essence', 'ampoule', 'treatment'],
    'toner':       ['toner', 'tonic', 'mist'],
    'mask':        ['mask', 'masque', 'peel'],
    'sunscreen':   ['sunscreen', 'spf', 'sunblock'],
    'eye cream':   ['eye cream', 'eye gel', 'eye serum'],
    'oil':         ['face oil', 'facial oil'],
    'exfoliator':  ['exfoliator', 'scrub', 'exfoliant'],
    'foundation':  ['foundation'],
    'concealer':   ['concealer'],
    'primer':      ['primer'],
    'blush':       ['blush'],
    'highlighter': ['highlighter'],
    'mascara':     ['mascara'],
    'eyeliner':    ['eyeliner'],
    'eyeshadow':   ['eyeshadow'],
    'lipstick':    ['lipstick'],
    'palette':     ['palette'],
    'brow':        ['brow'],
}

def parse_query_skin_context(query):
    rules = load_skin_condition_rules()
    normalized_query = normalize_search_text(query)

    # Detect skin conditions
    detected_conditions = {
        canonical for alias, canonical in rules['alias_to_condition'].items()
        if normalize_search_text(alias) and re.search(rf'\b{re.escape(normalize_search_text(alias))}\b', normalized_query)
    }

    # Detect ingredient preferences/avoidances from query markers
    prefer_markers = ('with ', 'contains ', 'good for ', 'best for ', 'help ', 'helps ', 'for ')
    avoid_markers  = ('without ', 'avoid ', 'no ', 'free of ', 'exclude ')
    wants_prefer = any(m in normalized_query for m in prefer_markers)
    wants_avoid  = any(m in normalized_query for m in avoid_markers)

    preferred_ingredients, avoided_ingredients = set(), set()
    for term in rules['all_good_terms'] | rules['all_bad_terms']:
        term_norm = normalize_search_text(term)
        if term_norm and re.search(rf'\b{re.escape(term_norm)}\b', normalized_query):
            (avoided_ingredients if wants_avoid else preferred_ingredients if wants_prefer else set()).add(term)

    # Pull condition-based ingredient guidance
    for condition in detected_conditions:
        preferred_ingredients.update(rules['condition_rules'].get(condition, {}).get('good', set()))
        avoided_ingredients.update(rules['condition_rules'].get(condition, {}).get('bad', set()))

    # Detect category using CATEGORY_KEYWORDS (with fuzzy matching via levenshtein)
    detected_category = None
    query_words = normalized_query.split()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            kw_words = kw.split()
            # Multi-word keyword: check phrase presence
            if len(kw_words) > 1:
                if re.search(rf'\b{re.escape(kw)}\b', normalized_query):
                    detected_category = cat
                    break
            elif any(levenshtein_distance(w, kw) <= 1 and len(w) >= len(kw) - 1 for w in query_words):
                detected_category = cat
                break
        if detected_category:
            break

    # Detect if query is purely a category with no other attributes
    residual = normalized_query
    if detected_category:
        for kw in CATEGORY_KEYWORDS[detected_category]:
            residual = residual.replace(kw, '').strip()
    pure_category_query = detected_category is not None and len(residual) <= 2

    return {
        'detected_conditions': detected_conditions,
        'preferred_ingredients': preferred_ingredients,
        'avoided_ingredients': avoided_ingredients,
        'detected_category': detected_category,
        'pure_category_query': pure_category_query,
    }


def get_chemical_frequency():
    current_directory = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(current_directory, 'makeupchemicalscleaned.csv')
    chemical_counts = {}
    if os.path.exists(file_path):
        with open(file_path, newline='', encoding='utf-8') as csvfile:
            for row in csv.DictReader(csvfile):
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
    query_category     = query_skin_context['detected_category']
    pure_category_query = query_skin_context['pure_category_query']

    expansion_terms = sorted(query_skin_context['detected_conditions'])
    expanded_query  = " ".join([normalized_query] + expansion_terms).strip()
    raw_query_tokens = tokenize_and_stem(normalized_query)
    query_tokens     = tokenize_and_stem(expanded_query)

    MIN_MATCH_SCORE = 0.1
    MIN_BASE_SIMILARITY = 0.2
    MIN_TFIDF_SIMILARITY = 0.01
    MIN_SVD_SIMILARITY = 0.1

    products = Product.query.all()
    products = [p for p in products
        if (p.category or '').lower() != 'perfume'
        and 'All Hair Types' not in (p.highlights or '')]

    chem_freq = get_chemical_frequency()
    max_chem_freq = max((freq for _, freq in chem_freq), default=1)

    def product_full_text(p):
        structured = (f"{p.product_name or ''} {p.brand_name or ''} {p.primary_category or ''} "
                    f"{p.secondary_category or ''} {p.category or ''} {p.highlights or ''}")
        description = f"{p.description or ''} {p.ingredients or ''}"
        return f"{structured} {structured} {structured} {description}"

    # TF-IDF + SVD/LSA
    corpus = [" ".join(tokenize_and_stem(product_full_text(p))) for p in products]
    vectorizer = TfidfVectorizer(stop_words='english')
    tfidf_matrix = vectorizer.fit_transform(corpus)
    query_vec = vectorizer.transform([" ".join(query_tokens)])

    tfidf_sim = cosine_similarity(query_vec, tfidf_matrix).flatten()

    n_components = min(tfidf_matrix.shape[0] - 1, tfidf_matrix.shape[1] - 1, 150)
    svd_sim = np.zeros_like(tfidf_sim)
    if n_components >= 2:
        svd = TruncatedSVD(n_components=n_components, random_state=42)
        doc_lsa = normalize(svd.fit_transform(tfidf_matrix))
        query_lsa = normalize(svd.transform(query_vec))
        svd_sim = cosine_similarity(query_lsa, doc_lsa).flatten()

    similarities = 0.45 * tfidf_sim + 0.55 * svd_sim

    results = []

    for i, p in enumerate(products):
        product_category_text = f"{p.primary_category or ''} {p.secondary_category or ''} {p.category or ''}".lower()
        category_match = bool(query_category and query_category in product_category_text)

        if pure_category_query:
            # Drop non-matching categories; all matches start equal, ranked by quality
            if not category_match:
                continue
            base_score = 0.0
        else:
            base_score = similarities[i]
            if base_score < MIN_BASE_SIMILARITY:
                continue
            if tfidf_sim[i] < MIN_TFIDF_SIMILARITY and svd_sim[i] < MIN_SVD_SIMILARITY:
                continue

            # Token coverage + phrase match boosts
            product_tokens = tokenize_and_stem(product_full_text(p))
            token_coverage = (
                sum(1 for t in raw_query_tokens if any(words_match(t, c) for c in product_tokens))
                / len(raw_query_tokens)
            ) if raw_query_tokens else 0.0

            phrase_match = normalized_query in normalize_search_text(
                f"{p.product_name or ''} {p.brand_name or ''} {p.primary_category or ''} "
                f"{p.secondary_category or ''} {p.category or ''}"
            )
            full_token_match = raw_query_tokens and all(
                any(words_match(t, c) for c in product_tokens) for t in raw_query_tokens
            )

            if phrase_match or full_token_match:
                base_score += 0.05 + token_coverage * 0.05
            elif token_coverage > 0:
                base_score += token_coverage * 0.05

            if normalized_query in normalize_search_text(f"{p.product_name or ''} {p.brand_name or ''}"):
                base_score += 0.05

            # Category multiplier: strong lift for matches, penalty for mismatches
            if query_category:
                base_score *= 1.6 if category_match else 0.15

        # Safety score Old Version (chemical frequency deductions only):
        # safety_score = max(0.0, 100.0 - sum(
        #     (freq / max_chem_freq) * 10 for name, freq in chem_freq if name in (p.ingredients or '')
        # ))
        # p.flagged_ingredients = list({name for name, _ in chem_freq if p.ingredients and name in p.ingredients})
        # p.good_ingredients = list(_ingredients_present(p.ingredients, query_skin_context['preferred_ingredients']))
        # p.safety_score = safety_score

        # Safety score — chemical safety dataset deductions
        safety_score = max(0.0, 100.0 - sum(
            (freq / max_chem_freq) * 10 for name, freq in chem_freq if name in (p.ingredients or '')
        ))

        # Additional deduction for condition-specific bad ingredients
        if query_skin_context['avoided_ingredients']:
            avoided_hits = _ingredients_present(p.ingredients, query_skin_context['avoided_ingredients'])
            safety_score = max(0.0, safety_score - len(avoided_hits) * 10)

        p.flagged_ingredients = list({name for name, _ in chem_freq if p.ingredients and name in p.ingredients})
        
        # Also flag condition-specific bad ingredients
        if query_skin_context['avoided_ingredients']:
            condition_flags = _ingredients_present(p.ingredients, query_skin_context['avoided_ingredients'])
            p.flagged_ingredients = list(set(p.flagged_ingredients) | condition_flags)

        p.safety_score = safety_score

        # Ingredient alignment
        preferred_hits = _ingredients_present(p.ingredients, query_skin_context['preferred_ingredients'])
        avoided_hits   = _ingredients_present(p.ingredients, query_skin_context['avoided_ingredients'])
        alignment = max(0.30, 1.0 + min(0.08 * len(preferred_hits), 0.32) - min(0.12 * len(avoided_hits), 0.48))

        rating_boost = (p.rating or 0) / 5.0
        loves_boost  = min((p.loves_count or 0) / 10000, 1.0)

        if pure_category_query:
            # Quality is the only ranking signal if pure category query
            quality_add = 0.4 * rating_boost + 0.3 * loves_boost + 0.3 * (safety_score / 100.0)
        else:
            quality_add = 0.02 * rating_boost + 0.02 * loves_boost + 0.05 * (safety_score / 100.0)

        ingredient_add = (alignment - 1.0) * 0.02
        results.append((base_score + quality_add + ingredient_add, p))

    if not results:
        return []

    max_score = max(s for s, _ in results)
    if max_score > 0:
        results = [(s / max_score * 100, p) for s, p in results]

    # Filters
    if category:
        results = [(s, p) for s, p in results if category.lower() in {
            (p.primary_category or '').lower(),
            (p.secondary_category or '').lower(),
            (p.category or '').lower()
        }]
    if min_price is not None: results = [(s, p) for s, p in results if (p.price  or 0) >= min_price]
    if max_price is not None: results = [(s, p) for s, p in results if (p.price  or 0) <= max_price]
    if min_rating is not None: results = [(s, p) for s, p in results if (p.rating or 0) >= min_rating]

    results = [(s, p) for s, p in results if s > MIN_MATCH_SCORE]
    if not results:
        return []

    sort_keys = {
        'price_asc': (lambda x: x[1].price or 0, False),
        'price_desc': (lambda x: x[1].price or 0, True),
        'rating': (lambda x: x[1].rating or 0, True),
        'safety': (lambda x: getattr(x[1], 'safety_score', 100.0), True),
    }
    key, reverse = sort_keys.get(sort_by, (lambda x: x[0], True))
    results.sort(key=key, reverse=reverse)

    score_name = [(s, p.product_name) for s, p in results]

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
        "safety_score": getattr(p, 'safety_score', 100.0), 
        "score": s,
        "flagged_ingredients": p.flagged_ingredients,
        "url": f"https://www.sephora.com/product/{p.product_id}" if p.product_id else None,
    } for s, p in results]

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
