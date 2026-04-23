"""
LLM chat route — only loaded when USE_LLM = True in routes.py.
Adds a POST /api/chat endpoint that performs LLM-driven RAG.

Setup:
  1. Add SPARK_API_KEY=your_key to .env
  2. Set USE_LLM = True in routes.py
"""
import json
import os
import re
import logging
from flask import request, jsonify, Response, stream_with_context
from infosci_spark_client import LLMClient

logger = logging.getLogger(__name__)

MAX_CHAT_MESSAGE_LENGTH = 200
MAX_CHAT_RESPONSE_LENGTH = 300


def _is_auth_error(exc):
    """Return True when the upstream LLM provider rejected authentication."""
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    return status_code == 401


def llm_search_decision(client, user_message):
    """Ask the LLM whether to search the DB and which word to use."""
    messages = [
        {
            "role": "system",
            "content": (
                "You have access to a database of Sephora skincare products, descriptions, ingredients, "
               "and product review ratings. Search is by a single word in the product name or description. "
                "Reply with exactly: YES followed by one space and ONE word to search (e.g. YES wedding), "
                "or NO if the question does not need product data."
            ),
        },
        {"role": "user", "content": user_message},
    ]
    response = client.chat(messages)
    content = (response.get("content") or "").strip().upper()
    logger.info(f"LLM search decision: {content}")
    if re.search(r"\bNO\b", content) and not re.search(r"\bYES\b", content):
        return False, None
    yes_match = re.search(r"\bYES\s+(\w+)", content)
    if yes_match:
        return True, yes_match.group(1).lower()
    if re.search(r"\bYES\b", content):
        return True, "Kardashian"
    return False, None


def register_chat_route(app, json_search):
    """Register the /api/chat SSE endpoint. Called from routes.py."""

    @app.route("/api/chat", methods=["POST"])
    def chat():
        data = request.get_json() or {}
        user_message = (data.get("message") or "").strip()
        if not user_message:
            return jsonify({"error": "Message is required"}), 400
        if len(user_message) > MAX_CHAT_MESSAGE_LENGTH:
            return jsonify({"error": f"Message must be {MAX_CHAT_MESSAGE_LENGTH} characters or fewer"}), 400

        api_key = os.getenv("API_KEY")
        if not api_key:
            return jsonify({"error": "SPARK_API key not set — add API_KEY to your .env file"}), 500

        client = LLMClient(api_key=api_key)
        try:
            use_search, search_term = llm_search_decision(client, user_message)
        except Exception as e:
            if _is_auth_error(e):
                logger.error("LLM auth failed during search decision: %s", e)
                return jsonify({"error": "LLM authentication failed (401). Check your API key value."}), 401
            logger.exception("LLM search decision failed")
            return jsonify({"error": "LLM request failed before streaming response."}), 502

        if use_search:
            products = json_search(search_term or "skincare")
            context_text = "\n\n---\n\n".join(
                f"Name: {prod['name']}\nBrand: {prod['brand']}\nPrice: {prod['price']}\nDescription: {prod['description']}\nRating: {prod['rating']}"
                for prod in products
            ) or "No matching products found."
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Answer questions about Sephora skincare products using only the product information provided. "
                        f"Keep the answer concise and under {MAX_CHAT_RESPONSE_LENGTH} characters."
                    ),
                },
                {"role": "user", "content": f"Product information:\n\n{context_text}\n\nUser question: {user_message}"},
            ]
        else:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a helpful assistant for Sephora skincare product questions. "
                        f"Keep the answer concise and under {MAX_CHAT_RESPONSE_LENGTH} characters."
                    ),
                },
                {"role": "user", "content": user_message},
            ]

        def generate():
            if use_search and search_term:
                yield f"data: {json.dumps({'search_term': search_term})}\n\n"
            try:
                emitted_length = 0
                truncated = False
                for chunk in client.chat(messages, stream=True):
                    if chunk.get("content"):
                        remaining = MAX_CHAT_RESPONSE_LENGTH - emitted_length
                        if remaining <= 0:
                            truncated = True
                            break

                        piece = chunk["content"][:remaining]
                        emitted_length += len(piece)
                        yield f"data: {json.dumps({'content': piece})}\n\n"

                        if len(piece) < len(chunk["content"]):
                            truncated = True
                            break

                if truncated:
                    yield f"data: {json.dumps({'content': '…'})}\n\n"
            except Exception as e:
                if _is_auth_error(e):
                    logger.error("LLM auth failed during streaming: %s", e)
                    yield f"data: {json.dumps({'error': 'LLM authentication failed (401). Check your API key value.'})}\n\n"
                    return
                logger.error(f"Streaming error: {e}")
                yield f"data: {json.dumps({'error': 'Streaming error occurred'})}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )