"""
SVIMS CampusBot — Flask Server (single entry point)
===================================================
PURANE CODE KI PROBLEM:
  — DO server files thi (svims_app.py + svims_server.py) — svims_app.py
    templates/index.html dhundta tha jo exist hi nahi karti (crash)
  — /api/reload-config aise functions call karta tha jo engine mein the hi nahi

NAYA SERVER:
  — Ek hi file, ek hi entry point
  — Background initialization (server turant start hota hai, KB saath mein load)
  — /api/status → poora health report (groq, KB, scrape info)
  — /api/chat → engine.get_answer (history ke saath)
  — /api/reload-config → ab sach mein kaam karta hai
  — /api/refresh-knowledge → dynamic pages dobara scrape (admin)
  — Bina Groq key / bina internet pe bhi server chalta hai (graceful)
"""

import os
import threading

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"))
load_dotenv()

import svims_engine
import svims_scraper

app = Flask(__name__, static_folder=BASE_DIR)
CORS(app)

# ─────────────────────────────────────────────
# STATE
# ─────────────────────────────────────────────
_vector_store = None
_init_done = False
_init_error = None
_init_lock = threading.Lock()
_SESSIONS = {}
_MAX_HISTORY = 24  # messages (12 turns)


def _background_init():
    """Knowledge base background mein load/build karo — server block nahi hota."""
    global _vector_store, _init_done, _init_error
    try:
        print("🎓 SVIMS CampusBot: knowledge base loading...")
        _vector_store = svims_scraper.ensure_knowledge_base(crawl_first=True, quiet=False)
        if _vector_store is not None:
            print("✅ Knowledge base ready (facts + scraped website pages)")
        else:
            print("⚠️ FAISS index nahi ban saka — facts-only mode "
                  "(deterministic answers still work)")
    except Exception as e:
        _init_error = str(e)
        print(f"🚨 KB init error: {_init_error}")
    finally:
        _init_done = True


# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/api/status")
def status():
    st = {
        "status": "online",
        "bot": "SVIMS CampusBot",
        "version": "3.0",
        "ready": True,
        "groq_configured": svims_engine.groq_ready(),
        "kb_ready": _vector_store is not None,
        "kb_loading": not _init_done,
        "init_error": _init_error,
    }
    try:
        st["knowledge"] = svims_scraper.status()
    except Exception:
        pass
    return jsonify(st)


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True, silent=True) or {}
    message = (data.get("message") or "").strip()
    session_id = data.get("session_id") or "default"

    if not message:
        return jsonify({"response": "Please type a question."}), 400
    if len(message) > 600:
        message = message[:600]

    history = _SESSIONS.setdefault(session_id, [])

    answer = svims_engine.get_answer(message, _vector_store, history)

    history.append({"role": "user", "content": message})
    history.append({"role": "bot", "content": answer})
    if len(history) > _MAX_HISTORY:
        del history[: len(history) - _MAX_HISTORY]

    return jsonify({"response": answer})


@app.route("/api/clear", methods=["POST"])
def clear():
    data = request.get_json(force=True, silent=True) or {}
    session_id = data.get("session_id") or "default"
    _SESSIONS.pop(session_id, None)
    return jsonify({"ok": True})


@app.route("/api/reload-config", methods=["POST"])
def reload_config():
    """svims_config.json hot-reload — ab sach mein kaam karta hai."""
    try:
        svims_engine.reload_config()
        return jsonify({
            "status": "reloaded",
            "models": svims_engine.MODELS_TO_TRY,
            "calendar_year": svims_engine.ACADEMIC_CALENDAR.get("year"),
            "message": "✅ Config reloaded — no restart needed",
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/refresh-knowledge", methods=["POST"])
def refresh_knowledge():
    """Dynamic pages (notifications/results/time tables/events) dobara scrape
    karo aur FAISS index rebuild karo. Admin use ke liye.

    Robust: scrape ya rebuild fail ho to bhi server purane index se chalta
    rehta hai — dono stages ka result alag-alag report hota hai.
    """
    global _vector_store
    scrape_ok, rebuild_ok, err = True, True, None
    try:
        svims_scraper.refresh_dynamic()
    except Exception as e:
        scrape_ok = False
        err = str(e)
    try:
        new_vs = svims_scraper.rebuild_after_refresh()
        if new_vs is not None:
            _vector_store = new_vs
        else:
            rebuild_ok = False
    except Exception as e:
        rebuild_ok = False
        err = err or str(e)

    if scrape_ok and rebuild_ok:
        return jsonify({"status": "refreshed",
                        "knowledge": svims_scraper.status(),
                        "message": "✅ Dynamic pages re-scraped + index rebuilt"})
    if scrape_ok and not rebuild_ok:
        return jsonify({"status": "partial",
                        "knowledge": svims_scraper.status(),
                        "message": "⚠️ Pages scraped, but index rebuild failed "
                                   "(embedding model?) — old index still serving"})
    return jsonify({"status": "error", "message": err or "scrape+rebuild failed"}), 500


@app.route("/api/model-status", methods=["GET"])
def model_status():
    return jsonify({
        "configured_models": svims_engine.MODELS_TO_TRY,
        "blacklisted": list(svims_engine._BLACKLISTED_MODELS),
        "groq_keys": len(svims_engine.GROQ_API_KEYS),
    })


# ─────────────────────────────────────────────
# STARTUP
# ─────────────────────────────────────────────
print("⚙️  SVIMS CampusBot Server starting...")
print(f"   Groq API keys: {len(svims_engine.GROQ_API_KEYS)} "
      f"({'✅' if svims_engine.groq_ready() else '⚠️ none — set GROQ_API_KEY_1 in .env'})")
threading.Thread(target=_background_init, daemon=True).start()

if __name__ == "__main__":
    # Production: gunicorn -w 1 -b 0.0.0.0:5000 svims_server:app
    app.run(host="0.0.0.0", port=5000, debug=False)
