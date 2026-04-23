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


def llm_search_decision(client, user_message, history=None):
    """Ask the LLM whether product search is needed and return a reformulated search query.

    Returns (use_search: bool, search_query: str | None).
    The search_query is a standalone IR-friendly query built from conversation context.
    """
    history_text = ""
    if history:
        lines = []
        for m in history[-6:]:
            role = "User" if m.get("isUser") else "Assistant"
            lines.append(f"{role}: {m.get('text', '')}")
        history_text = "\n".join(lines)

    conversation = f"Conversation so far:\n{history_text}\n\n" if history_text else ""

    messages = [
        {
            "role": "system",
            "content": (
                "You help route queries to a Sephora skincare product database. "
                "Given the conversation history and the latest user message, decide if product data is needed. "
                "If YES, also rewrite the query as a short, standalone, IR-friendly search phrase "
                "that captures the full intent (e.g. include product type, skin concern, constraints like price or ingredients). "
                "Reply in exactly this format:\n"
                "YES: <reformulated query>\n"
                "or\n"
                "NO"
            ),
        },
        {
            "role": "user",
            "content": f"{conversation}Latest message: {user_message}",
        },
    ]
    response = client.chat(messages)
    content = (response.get("content") or "").strip()
    logger.info(f"LLM search decision: {content}")

    upper = content.upper()
    if re.match(r"NO\b", upper):
        return False, None

    yes_match = re.match(r"YES\s*:\s*(.+)", content, re.IGNORECASE)
    if yes_match:
        return True, yes_match.group(1).strip()

    return True, user_message


def register_chat_route(app, json_search):
    """Register the /api/chat SSE endpoint. Called from routes.py."""

    @app.route("/api/chat", methods=["POST"])
    def chat():
        data = request.get_json() or {}
        user_message = (data.get("message") or "").strip()
        history = data.get("history") or []
        if not user_message:
            return jsonify({"error": "Message is required"}), 400
        if len(user_message) > MAX_CHAT_MESSAGE_LENGTH:
            return jsonify({"error": f"Message must be {MAX_CHAT_MESSAGE_LENGTH} characters or fewer"}), 400

        api_key = os.getenv("SPARK_API_KEY")
        if not api_key:
            return jsonify({"error": "API key not set — add SPARK_API_KEY to your .env file"}), 500

        client = LLMClient(api_key=api_key)
        try:
            use_search, search_query = llm_search_decision(client, user_message, history)
        except Exception as e:
            if _is_auth_error(e):
                logger.error("LLM auth failed during search decision: %s", e)
                return jsonify({"error": "LLM authentication failed (401). Check your API key value."}), 401
            logger.exception("LLM search decision failed")
            return jsonify({"error": "LLM request failed before streaming response."}), 502

        prior = [
            {"role": "assistant" if m.get("isUser") is False else "user", "content": m["text"]}
            for m in history[-6:]
            if m.get("text")
        ]

        if use_search:
            products = json_search(search_query or user_message)
            context_text = "\n\n---\n\n".join(
                f"Title: {prod['name']}\nBrand: {prod['brand']}\nRating: {prod['rating']}\n"
                f"Price: ${prod.get('price', 'N/A')}\n"
                f"Safety Score: {prod.get('safety_score', 'N/A')}\n"
                f"Flagged Ingredients: {', '.join(prod.get('flagged_ingredients') or []) or 'None'}\n"
                f"Description: {(prod['description'] or '')[:300]}"
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
                *prior,
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
                *prior,
                {"role": "user", "content": user_message},
            ]

        def generate():
            if use_search:
                yield f"data: {json.dumps({'search_term': user_message})}\n\n"
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