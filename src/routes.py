"""
Routes: React app serving and products search API.

To enable AI chat, set USE_LLM = True below. See llm_routes.py for AI code.
"""
import json
import os
import csv
import re
import logging
from functools import lru_cache
import pandas as pd
import numpy as np
from flask import send_from_directory, request, jsonify
from models import db, Product, Review
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.decomposition import TruncatedSVD
from sklearn.preprocessing import normalize

logger = logging.getLogger(__name__)

# ── AI toggle ────────────────────────────────────────────────────────────────
# USE_LLM = False
USE_LLM = True
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
    cleaned = re.sub(r'(?i)\bp\s+h\b', 'pH', cleaned)

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


def phrase_tokens_match(query_text, phrase_text):
    """Return True when phrase appears in query after normalization/stemming.

    This makes phrase matching tolerant to simple singular/plural and minor
    inflection differences (e.g., "face oils" matches keyword "face oil").
    """
    query_tokens = tokenize_and_stem(query_text)
    phrase_tokens = tokenize_and_stem(phrase_text)
    if not query_tokens or not phrase_tokens or len(phrase_tokens) > len(query_tokens):
        return False

    window_size = len(phrase_tokens)
    for start in range(len(query_tokens) - window_size + 1):
        window = query_tokens[start:start + window_size]
        if all(words_match(phrase_tokens[i], window[i]) for i in range(window_size)):
            return True
    return False


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
    
    if len(query_word) >= 4 and candidate_word.startswith(query_word):
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

    ingredient_aliases = {
        'titanium dioxide': ['ci 77891'],
    }

    hits = set()
    for term in candidates:
        term_norm = normalize_search_text(term)
        if not term_norm:
            continue

        if term_norm in ingredients_norm:
            hits.add(term)
            continue

        aliases = ingredient_aliases.get(term_norm, [])
        if any(normalize_search_text(alias) in ingredients_norm for alias in aliases):
            hits.add(term)

    return hits

CATEGORY_KEYWORDS = {
    'cleanser':    ['cleanser', 'cleanse', 'face wash', 'foaming wash', 'facewash'],
    'moisturizer': ['moisturizer', 'moisturize', 'moisturiser', 'lotion', 'cream', 'hydrator'],
    'serum':       ['serum', 'essence', 'ampoule', 'treatment'],
    'toner':       ['toner', 'tonic', 'mist'],
    'mask':        ['mask', 'masque'],
    'sunscreen':   ['sunscreen', 'spf', 'sunblock'],
    'eye cream':   ['eye cream', 'eye gel', 'eye serum'],
    'oil':         ['face oil', 'facial oil'],
    'facial peels': ['peel pad', 'facial peel', 'daily peel'],
    'exfoliator':  ['exfoliator', 'scrub', 'exfoliant', 'peel'],
    'foundation':  ['foundation'],
    'concealer':   ['concealer'],
    'primer':      ['primer'],
    'blush':       ['blush'],
    'highlighter': ['highlighter'],
    'mascara':     ['mascara'],
    'eyeliner':    ['eyeliner'],
    'eyeshadow':   ['eyeshadow'],
    'lipstick':    ['lipstick', 'lip gloss', 'lip balm'],
    'palette':     ['palette'],
    'brow':        ['brow', 'eyebrow', 'eyebrow pencil', 'eyebrow gel'],
    'hair':       ['shampoo', 'conditioner', 'hair mask', 'hair oil', 'hair treatment'],
    'perfume':     ['perfume', 'fragrance', 'eau de parfum', 'eau de toilette', 'cologne', 'scent'],
}

def fuzzy_expand_token(token, vocab, max_distance=2):
    """Return vocab terms that fuzzy-match a token not found in vocab."""
    if token in vocab:
        return [token]
    matches = []
    for v in vocab:
        if abs(len(v) - len(token)) > max_distance:
            continue
        if levenshtein_distance(token, v) <= max_distance:
            matches.append(v)
    return matches

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
    avoid_markers  = ('without ', 'avoid ', 'no ', 'free of ', 'exclude ', 'not ')

    wants_avoid  = any(m in normalized_query for m in avoid_markers)
    wants_prefer = not wants_avoid or any(m in normalized_query for m in prefer_markers)

    preferred_ingredients, avoided_ingredients = set(), [set(),set()] ## for avoided ingredients, have one set for direct mentions and one for indirect mentions via skin conditions.
    for term in rules['all_good_terms'] | rules['all_bad_terms']:
        term_norm = normalize_search_text(term)
        if term_norm and re.search(rf'\b{re.escape(term_norm)}\b', normalized_query):
            if wants_avoid:
                avoided_ingredients[0].add(term) #corresponds to direct mentions in query
            elif wants_prefer:
                preferred_ingredients.add(term)

    # Also support explicit free-form avoid phrases that may not exist in the
    # skin-condition rules file, e.g., "without titanium dioxide".
    if wants_avoid:
        for marker in avoid_markers:
            if marker not in normalized_query:
                continue

            tail = normalized_query.split(marker, 1)[1]
            tail = re.split(r'\b(?:for|good for|best for|with|that|which|because)\b', tail, maxsplit=1)[0]
            candidates = re.split(r',|\band\b|\bor\b|/|\bbut\b', tail)

            for candidate in candidates:
                phrase = normalize_search_text(candidate)
                phrase = re.sub(r'^(?:any|all|the|a|an)\s+', '', phrase).strip()
                phrase = re.sub(r'\s+(?:ingredient|ingredients)$', '', phrase).strip()
                if phrase and len(phrase) >= 3:
                    avoided_ingredients[0].add(phrase)

    # Pull condition-based ingredient guidance
    for condition in detected_conditions:
        preferred_ingredients.update(rules['condition_rules'].get(condition, {}).get('good', set()))
        avoided_ingredients[1].update(rules['condition_rules'].get(condition, {}).get('bad', set())) ##skin condition specific avoidances

    # Detect category by checking specific multi-word phrases first, then fallback to
    # single-word fuzzy matching. This prevents generic terms like "cream" from
    # overriding more specific intents such as "eye cream".
    detected_category = None
    query_words = normalized_query.split()

    phrase_matches = []
    for cat, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            kw_norm = normalize_search_text(kw)
            if " " in kw_norm and phrase_tokens_match(normalized_query, kw_norm):
                phrase_matches.append((len(kw_norm.split()), cat))

    if phrase_matches:
        phrase_matches.sort(key=lambda item: item[0], reverse=True)
        detected_category = phrase_matches[0][1]
    else:
        for cat, keywords in CATEGORY_KEYWORDS.items():
            for kw in keywords:
                kw_norm = normalize_search_text(kw)
                if " " in kw_norm:
                    continue
                if any(levenshtein_distance(w, kw_norm) <= 1 and len(w) >= len(kw_norm) - 1 for w in query_words):
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

_search_index = None

# extract svd info once to decr computation per query
def _product_svd_text(p):
    """Full-text for SVD corpus — brand name excluded intentionally."""
    structured = (
        f"{p.product_name or ''} {p.primary_category or ''} "
        f"{p.secondary_category or ''} {p.category or ''} {p.highlights or ''}"
    )
    ingredients = list(dict.fromkeys((p.ingredients or '').lower().split(',')))
    ingredients_text = ' '.join(i.strip() for i in ingredients[:100])
        
    return f"{structured} {structured} {structured} {p.description or ''} {ingredients_text}"


def build_search_index():
    global _search_index

    products = Product.query.all()

    corpus = [" ".join(tokenize_and_stem(_product_svd_text(p))) for p in products]

    vectorizer = TfidfVectorizer(
        stop_words='english',
        min_df=1,
        max_df=0.98,
        ngram_range=(1, 2),
    )
    tfidf_matrix = vectorizer.fit_transform(corpus)
    terms = vectorizer.get_feature_names_out()

    # Build inverted index: term → [product indices]
    inverted_index = {}
    cx = tfidf_matrix.tocsr()
    for term, col_idx in vectorizer.vocabulary_.items():
        col = cx.getcol(col_idx)
        doc_indices = col.nonzero()[0].tolist()
        if doc_indices:
            inverted_index[term] = doc_indices

    n_components = min(tfidf_matrix.shape[0] - 1, tfidf_matrix.shape[1] - 1, 100)

    svd = None
    doc_lsa = np.zeros((len(products), max(n_components, 1)))

    if n_components >= 2:
        svd = TruncatedSVD(n_components=n_components, random_state=42)
        doc_lsa = normalize(svd.fit_transform(tfidf_matrix))

    _search_index = {
        'products':     products,
        'vectorizer':   vectorizer,
        'tfidf_matrix': tfidf_matrix,
        'svd':          svd,
        'doc_lsa':      doc_lsa,
        'terms':        terms,
        'n_components': n_components,
        'inverted_index': inverted_index,
    }

    return _search_index


def _get_search_index():
    if _search_index is None:
        build_search_index()
    return _search_index


def build_rag_query_context(query, max_snippets=8):
    """Retrieve top product snippets as grounding context for query expansion."""
    normalized_query = normalize_search_text(query)
    query_tokens = tokenize_and_stem(normalized_query)
    if not query_tokens:
        return ""

    idx = _get_search_index()
    products = idx['products']
    vectorizer = idx['vectorizer']
    tfidf_matrix = idx['tfidf_matrix']

    vocab = vectorizer.vocabulary_
    query_terms = [token for token in query_tokens if token in vocab]
    if not query_terms:
        query_terms = query_tokens

    query_vec = vectorizer.transform([" ".join(query_terms)])
    similarities = cosine_similarity(query_vec, tfidf_matrix).flatten()
    ranked_indices = similarities.argsort()[::-1]

    snippets = []
    for doc_idx in ranked_indices:
        if len(snippets) >= max_snippets:
            break
        sim = float(similarities[doc_idx])
        if sim <= 0 and snippets:
            continue

        p = products[doc_idx]
        categories = " / ".join(
            x for x in [p.primary_category, p.secondary_category, p.category] if x
        )
        snippet = (
            f"Product: {p.product_name or ''}; "
            f"Brand: {p.brand_name or ''}; "
            f"Category: {categories}; "
            f"Highlights: {(p.highlights or '')[:120]}; "
            f"Ingredients: {(p.ingredients or '')[:180]}"
        )
        snippets.append(snippet)

    return "\n".join(snippets)


def rag_expand_query(query):
    """Expand the user query with RAG context before retrieval scoring."""
    raw_query = (query or "").strip()
    if not raw_query or not USE_LLM:
        return raw_query

    api_key = os.getenv("API_KEY")
    if not api_key:
        return raw_query

    context = build_rag_query_context(raw_query)
    if not context:
        return raw_query

    try:
        from infosci_spark_client import LLMClient

        client = LLMClient(api_key=api_key)
        messages = [
            {
                "role": "system",
                "content": (
                    "You rewrite search queries for skincare product retrieval. "
                    "Output exactly one short expanded query, no explanation. "
                    "Preserve hard constraints and negations such as without/avoid/no/free of. "
                    "Keep brand, category, skin concerns, and ingredient intent explicit."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Original query: {raw_query}\n\n"
                    f"Retrieved context:\n{context}\n\n"
                    "Return only the expanded query."
                ),
            },
        ]

        response = client.chat(messages)
        expanded = (response.get("content") or "").strip()
        expanded = re.sub(r"^expanded query\s*:\s*", "", expanded, flags=re.IGNORECASE)
        expanded = re.sub(r"\s+", " ", expanded).strip(" \"'")

        if not expanded:
            return raw_query

        if len(expanded.split()) > 30:
            expanded = " ".join(expanded.split()[:30])

        return expanded
    except Exception as exc:
        logger.warning("RAG query expansion failed, falling back to raw query: %s", exc)
        return raw_query


def rocchio_pseudo_feedback_query(
    query_vec,
    tfidf_matrix,
    base_scores,
    candidate_indices,
    alpha=1.0,
    beta=0.70,
    gamma=0.10,
    top_k=10,
    bottom_k=20,
):
    """Apply Rocchio pseudo-relevance feedback and return an updated query vector."""
    q_dense = query_vec.toarray().ravel()
    if q_dense.size == 0:
        return query_vec

    if candidate_indices:
        scored_candidates = sorted(
            ((base_scores[i], i) for i in sorted(candidate_indices)),
            key=lambda pair: pair[0],
            reverse=True,
        )
    else:
        scored_candidates = sorted(
            ((score, i) for i, score in enumerate(base_scores)),
            key=lambda pair: pair[0],
            reverse=True,
        )

    relevant_ids = [idx for _, idx in scored_candidates[:top_k]]
    non_relevant_ids = [idx for _, idx in scored_candidates[-bottom_k:]]

    if not relevant_ids:
        return query_vec

    relevant_centroid = tfidf_matrix[relevant_ids].mean(axis=0).A1
    non_relevant_centroid = (
        tfidf_matrix[non_relevant_ids].mean(axis=0).A1
        if non_relevant_ids else np.zeros_like(relevant_centroid)
    )

    updated = alpha * q_dense + beta * relevant_centroid - gamma * non_relevant_centroid
    updated = np.maximum(updated, 0.0)

    updated_norm = np.linalg.norm(updated)
    if updated_norm > 0:
        updated = updated / updated_norm
        return updated.reshape(1, -1)

    original_norm = np.linalg.norm(q_dense)
    if original_norm > 0:
        return (q_dense / original_norm).reshape(1, -1)

    return query_vec


def ranked_product_search(query, category='', min_price=None, max_price=None, min_rating=None, sort_by='relevance'):
    global score_name

    if not query or not query.strip():
        return []

    #use pre-computed search index
    idx          = _get_search_index()
    products     = idx['products']
    vectorizer   = idx['vectorizer']
    tfidf_matrix = idx['tfidf_matrix']
    svd          = idx['svd']
    doc_lsa      = idx['doc_lsa']
    terms        = idx['terms']
    n_components = idx['n_components']
    inverted_index = idx['inverted_index']

    # parse query
    normalized_query    = normalize_search_text(query)
    query_skin_context  = parse_query_skin_context(query)
    query_category      = query_skin_context['detected_category']
    pure_category_query = query_skin_context['pure_category_query']
    explicit_category_intent = bool(
        query_category and any(
            phrase_tokens_match(normalized_query, kw)
            for kw in CATEGORY_KEYWORDS.get(query_category, [])
        )
    )

    query_skin_context = parse_query_skin_context(query)
    explicit_avoided  = query_skin_context['avoided_ingredients'][0]
    condition_avoided = query_skin_context['avoided_ingredients'][1]

    # print('=== FULL DEBUG ===')
    # print('1. avoided_ingredients:', query_skin_context['avoided_ingredients'])

    # p_retinol = next((p for p in products if 'retinol' in (p.product_name or '').lower()), None)
    # if p_retinol:
    #     print('2. raw ingredients:', repr(p_retinol.ingredients[:200]))
    #     print('3. retinol in ingredients:', 'retinol' in (p_retinol.ingredients or '').lower())
    #     print('4. _ingredients_present:', _ingredients_present(p_retinol.ingredients, query_skin_context['avoided_ingredients']))

    expansion_terms  = sorted(query_skin_context['detected_conditions'])
    expanded_query   = " ".join([normalized_query] + expansion_terms).strip()
    raw_query_tokens = tokenize_and_stem(normalized_query)
    query_tokens     = tokenize_and_stem(expanded_query)

    is_partial_query     = len(normalized_query.split()) == 1 and len(normalized_query) <= 6
    MIN_MATCH_SCORE      = 0.1
    MIN_BASE_SIMILARITY  = 0.05  if is_partial_query else 0.2
    MIN_TFIDF_SIMILARITY = 0.001 if is_partial_query else 0.01
    MIN_SVD_SIMILARITY   = 0.02  if is_partial_query else 0.1

    # vectorize query
    avoided_tokens = set()
    for term in explicit_avoided | condition_avoided:
        avoided_tokens.update(tokenize_and_stem(term))

    vocab = vectorizer.vocabulary_
    expanded_query_tokens = []
    
    for token in query_tokens:
        if token in avoided_tokens:
            continue
        if token in vocab:
            expanded_query_tokens.append(token)
            # also grab prefix matches
            expanded_query_tokens.extend(v for v in vocab if v.startswith(token) and v != token)
        else:
            # token is OOV (e.g. a typo) — fuzzy match it into the vocab
            fuzzy_matches = fuzzy_expand_token(token, vocab)
            expanded_query_tokens.extend(fuzzy_matches)
    
    # OLD QUERY EXPANSION (WITHOUT FUZZY)
    # expanded_query_tokens = []
    # for token in query_tokens:
    #     if token in avoided_tokens:
    #         continue
    #     expanded_query_tokens.append(token)
    #     if len(token) >= 4:
    #         expanded_query_tokens.extend(v for v in vocab if v.startswith(token) and v != token)

    # Look up candidate product indices from inverted index
    candidate_indices = set()
    for token in expanded_query_tokens:
        if token in inverted_index:
            candidate_indices.update(inverted_index[token])

    # Fall back to all products for very short/unmatched queries
    if not candidate_indices:
        candidate_indices = set(range(len(products)))

    query_vec = vectorizer.transform([" ".join(expanded_query_tokens)])

    initial_tfidf_sim = cosine_similarity(query_vec, tfidf_matrix).flatten()
    rocchio_query_vec = rocchio_pseudo_feedback_query(
        query_vec=query_vec,
        tfidf_matrix=tfidf_matrix,
        base_scores=initial_tfidf_sim,
        candidate_indices=candidate_indices,
    )

    tfidf_sim = cosine_similarity(rocchio_query_vec, tfidf_matrix).flatten()

    svd_sim = np.zeros_like(tfidf_sim)
    query_lsa = None
    if n_components >= 2 and svd is not None:
        query_lsa = normalize(svd.transform(rocchio_query_vec))
        svd_sim   = cosine_similarity(query_lsa, doc_lsa).flatten()

    similarities = 0.60 * tfidf_sim + 0.40 * svd_sim

    # SVD dimensions (for frontend display)
    def get_top_dimensions(doc_lsa_row, n=5):
        dim_contributions = doc_lsa_row * query_lsa.flatten()
        top_dims    = dim_contributions.argsort()[-n:][::-1]
        bottom_dims = dim_contributions.argsort()[:n]

        def dims_to_list(dims):
            return [{
                'dim':          int(d),
                'contribution': float(dim_contributions[d]),
                'top_terms':    [terms[i] for i in svd.components_[d].argsort()[-5:][::-1]],
            } for d in dims]

        return {'top': dims_to_list(top_dims), 'bottom': dims_to_list(bottom_dims)}

    # apply chemical frequency penalty
    chem_freq     = get_chemical_frequency()
    max_chem_freq = max((freq for _, freq in chem_freq), default=1)

    # text parsing for ingredient matching and category detection
    def product_full_text(p):
        structured = (f"{p.product_name or ''} {p.brand_name or ''} {p.primary_category or ''} "
                      f"{p.secondary_category or ''} {p.category or ''} {p.highlights or ''}")
        ingredients = list(dict.fromkeys((p.ingredients or '').lower().split(',')))
        ingredients_text = ' '.join(i.strip() for i in ingredients[:100])
        return f"{structured} {structured} {structured} {p.description or ''} {ingredients_text}"

    # product scoring
    results = []

    for i, p in enumerate(products):
        product_category_text = f"{p.primary_category or ''} {p.secondary_category or ''} {p.category or ''}".lower()
        category_match = bool(query_category and query_category in product_category_text)

        if i not in candidate_indices:
            continue

        if explicit_category_intent and not category_match:
            continue

        # ── Hard exclude products containing avoided ingredients ──
        explicit_hits  = _ingredients_present(p.ingredients, explicit_avoided)
        if explicit_avoided and explicit_hits:
            continue  # hard exclude — user said "without X"

        condition_hits = _ingredients_present(p.ingredients, condition_avoided)
        avoided_hits   = explicit_hits | condition_hits  # used for scoring/display below

        if query_skin_context['avoided_ingredients'] and avoided_hits:
            continue # hard exclude — even if user didn't explicitly say "without" but best for their skin condition"

        if pure_category_query:
            if not category_match:
                continue
            base_score = 0.0
        else:
            base_score = similarities[i]
            if tfidf_sim[i] < MIN_TFIDF_SIMILARITY and svd_sim[i] < MIN_SVD_SIMILARITY:
                continue
            if query_category:
                base_score *= 1.6 if category_match else 0.15
            if base_score < MIN_BASE_SIMILARITY:
                continue

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

        ingredients_lower = (p.ingredients or '').lower()

        safety_score = max(0.0, 100.0 - sum(
            (freq / max_chem_freq) * 2000 for name, freq in chem_freq if name.lower() in ingredients_lower
        ) - len(avoided_hits) * 10)

        p.flagged_ingredients = list({name for name, _ in chem_freq if name.lower() in ingredients_lower})
        p.avoided_ingredients = list(avoided_hits)
        p.safety_score        = safety_score

        preferred_hits     = _ingredients_present(p.ingredients, query_skin_context['preferred_ingredients'])
        p.good_ingredients = list(preferred_hits)
        alignment = max(0.30, 1.0 + min(0.08 * len(preferred_hits), 0.32) - min(0.12 * len(avoided_hits), 0.48))

        p.svd_score      = float(svd_sim[i])
        p.top_dimensions = get_top_dimensions(doc_lsa[i]) if (n_components >= 2 and query_lsa is not None) else []

        rating_boost = (p.rating or 0) / 5.0
        loves_boost  = min((p.loves_count or 0) / 10000, 1.0)

        if pure_category_query:
            quality_add = 0.2 * rating_boost + 0.3 * loves_boost + 0.5 * (safety_score / 100.0)
        else:
            quality_add = 0.02 * rating_boost + 0.02 * loves_boost + 0.5 * (safety_score / 100.0)

        ingredient_add = (alignment - 1.0) * 0.15
        results.append((base_score + quality_add + ingredient_add, p))

    if not results:
        return []

    max_score = max(s for s, _ in results)
    if max_score > 0:
        results = [(s / max_score * 100, p) for s, p in results]


    if category:
        results = [(s, p) for s, p in results if category.lower() in {
            (p.primary_category or '').lower(),
            (p.secondary_category or '').lower(),
            (p.category or '').lower()
        }]
    if min_price  is not None: results = [(s, p) for s, p in results if (p.price  or 0) >= min_price]
    if max_price  is not None: results = [(s, p) for s, p in results if (p.price  or 0) <= max_price]
    if min_rating is not None: results = [(s, p) for s, p in results if (p.rating or 0) >= min_rating]

    results = [(s, p) for s, p in results if s > MIN_MATCH_SCORE]
    if not results:
        return []

    sort_keys = {
        'price_asc':  (lambda x: x[1].price or 0,                      False),
        'price_desc': (lambda x: x[1].price or 0,                      True),
        'rating':     (lambda x: x[1].rating or 0,                     True),
        'safety':     (lambda x: getattr(x[1], 'safety_score', 100.0), True),
    }
    key, reverse = sort_keys.get(sort_by, (lambda x: x[0], True))
    results.sort(key=key, reverse=reverse)

    score_name = [(s, p.product_name) for s, p in results]

    return [{
        'id':                  p.id,
        'name':                p.product_name,
        'category':            p.category,
        'brand':               p.brand_name,
        'price':               p.price,
        'sale_price':          p.sale_price_usd,
        'rating':              p.rating,
        'review_count':        p.review_count,
        'loves_count':         p.loves_count,
        'description':         clean_product_description(p.description),
        'ingredients':         p.ingredients,
        'highlights':          p.highlights,
        'safety_score':        getattr(p, 'safety_score', 100.0),
        'score':               s,
        'flagged_ingredients': p.flagged_ingredients,
        'avoided_ingredients': getattr(p, 'avoided_ingredients', []),
        'good_ingredients':    getattr(p, 'good_ingredients', []),
        'svd_score':           getattr(p, 'svd_score', 0.0),
        'top_dimensions':      getattr(p, 'top_dimensions', []),
        'url':                 f"https://www.sephora.com/product/{p.product_id}" if p.product_id else None,
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
    # Queries can be transformed upstream (e.g., by RAG), then ranked here
    # with fuzzy expansion + Rocchio pseudo-relevance feedback.
    
    @app.route("/api/categories")
    def get_categories():
        rows = db.session.query(Product.category).filter(
            Product.category != None, Product.category != ''
        ).all()

        parent_counts = {}
        for (category,) in rows:
            parent = category.split(">")[0].split("/")[0].strip()
            if parent:
                parent_counts[parent] = parent_counts.get(parent, 0) + 1

        all_categories = sorted(parent_counts, key=lambda k: parent_counts[k], reverse=True)

        # print(sorted(parent_counts.items(), key=lambda k: k[1], reverse=True))
        return jsonify(all_categories)

    @app.route("/api/products/search")
    def search_products():
        q = request.args.get("q", "")
        category = request.args.get("category", "")
        min_price = request.args.get("min_price", type=float)
        max_price = request.args.get("max_price", type=float)
        min_rating = request.args.get("min_rating", type=float)
        sort_by = request.args.get("sort_by", "relevance")
        use_rag = request.args.get("use_rag", "true").strip().lower() not in {"false", "0", "no", "off"}
        debug_query = request.args.get("debug_query", "false").strip().lower() in {"true", "1", "yes", "on"}

        query_for_search = rag_expand_query(q) if use_rag else q
        results = ranked_product_search(
            query_for_search,
            category=category,
            min_price=min_price,
            max_price=max_price,
            min_rating=min_rating,
            sort_by=sort_by,
        )

        if debug_query:
            return jsonify({
                "original_query": q,
                "rag_query": query_for_search,
                "results": results,
            })

        return jsonify(results)
    
    @app.get('/score')
    def get_score_name():
        return jsonify({'Similarity Score': score_name})

    if USE_LLM:
        from llm_routes import register_chat_route
        register_chat_route(app, json_search)
