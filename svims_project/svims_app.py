"""
SVIMS CampusBot — Flask Backend
================================
Frontend (templates/index.html) already tumhari di hui file hai — usko
bilkul touch nahi kiya. Ye backend usi ke API format se match karta hai:

  POST /api/chat   { message, session_id }  ->  { response }
  GET  /api/status                           ->  { ready }
  POST /api/clear  { session_id }            ->  { ok }

Backend logic (Groq calls, PDF matching, RAG) svims_engine.py /
svims_qa_loader.py / svims_processor.py se hi aata hai — unhe touch
nahi kiya.
"""

import os
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

from svims_processor import create_knowledge_base, load_knowledge_base
from svims_engine import create_chatbot, get_answer

# .env load
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
load_dotenv()

app = Flask(__name__)

# ─────────────────────────────────────────────
# KNOWLEDGE BASE + CHATBOT — ek baar app start hone pe load hota hai
# ─────────────────────────────────────────────
print("🎓 SVIMS CampusBot loading knowledge base...")
_chain = None
_load_error = None
try:
    vector_store = load_knowledge_base()
    if vector_store is None:
        print("🔄 Knowledge base not found — building fresh (1-2 mins)...")
        vector_store = create_knowledge_base()
    _chain = create_chatbot(vector_store)
    print("✅ CampusBot ready!")
except Exception as e:
    _load_error = str(e)
    print(f"🚨 Startup Error: {_load_error}")

# ─────────────────────────────────────────────
# PER-SESSION CHAT HISTORY (in-memory)
# Frontend sirf current message bhejta hai + session_id, poori history
# nahi bhejta — isliye history yahan server pe track karte hain.
# NOTE: server restart hone pe history khatam ho jaati hai (in-memory hai).
# ─────────────────────────────────────────────
_SESSIONS = {}
_MAX_HISTORY_TURNS = 12  # per session kitne purane messages yaad rakhein


def _get_history(session_id):
    return _SESSIONS.setdefault(session_id, [])


def _trim_history(history):
    # Zyada purani history hatate jao taaki memory na badhe
    if len(history) > _MAX_HISTORY_TURNS * 2:
        del history[: len(history) - _MAX_HISTORY_TURNS * 2]


# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/status")
def status():
    return jsonify({"ready": _chain is not None, "error": _load_error})


@app.route("/api/chat", methods=["POST"])
def chat():
    if _chain is None:
        return jsonify({"response": f"⚠️ Bot not ready: {_load_error}"}), 500

    data = request.get_json(force=True) or {}
    message = (data.get("message") or "").strip()
    session_id = data.get("session_id") or "default"

    if not message:
        return jsonify({"response": "Please type a question."}), 400

    history = _get_history(session_id)

    try:
        answer = get_answer(_chain, message, history)
    except Exception as e:
        print(f"Chat error: {e}")
        answer = f"Something went wrong: {e}\n\nPlease contact svimi@svimi.org"

    history.append({"role": "user", "content": message})
    history.append({"role": "bot", "content": answer})
    _trim_history(history)

    return jsonify({"response": answer})


@app.route("/api/clear", methods=["POST"])
def clear():
    data = request.get_json(force=True) or {}
    session_id = data.get("session_id") or "default"
    _SESSIONS.pop(session_id, None)
    return jsonify({"ok": True})


if __name__ == "__main__":
    # Local development ke liye. Production/deploy ke liye gunicorn use karo.
    app.run(host="0.0.0.0", port=5000, debug=True)