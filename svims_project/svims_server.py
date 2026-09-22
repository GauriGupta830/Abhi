import os
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
load_dotenv()

from svims_processor import load_knowledge_base, create_knowledge_base
from svims_engine import create_chatbot, get_answer

app = Flask(__name__, static_folder=".")
CORS(app)

print("⚙️  SVIMS CampusBot Server starting...")
v_store = load_knowledge_base()
if v_store is None:
    print("🔄 Building fresh knowledge base...")
    v_store = create_knowledge_base()

bot_chain = create_chatbot(v_store)
session_histories = {}
print("✅ Server ready!")


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json or {}
    user_msg = data.get("message", "").strip()
    session_id = data.get("session_id", "default")

    if not user_msg:
        return jsonify({"error": "Empty message"}), 400

    if session_id not in session_histories:
        session_histories[session_id] = []

    history = session_histories[session_id]

    # ✅ History pass karo — context maintain hoga
    answer = get_answer(bot_chain, user_msg, history)

    history.append({"role": "user", "content": user_msg})
    history.append({"role": "assistant", "content": answer})

    if len(history) > 10:
        session_histories[session_id] = history[-10:]

    return jsonify({"response": answer})


@app.route("/api/status", methods=["GET"])
def status():
    return jsonify({"status": "online", "bot": "SVIMS CampusBot", "version": "2.0"})


@app.route("/api/reload-config", methods=["POST"])
def reload_config():
    """
    Config hot-reload — bina server restart ke svims_config.json ke changes
    apply ho jaate hain. Fees, calendar link, achievement links, syllabus links,
    show_staff_phones — sab reload ho jaata hai.

    Use: browser ya terminal se POST request bhejo:
      curl -X POST http://127.0.0.1:5000/api/reload-config
    Ya index.html mein ek hidden admin button bana sakte ho.
    """
    try:
        import svims_engine as eng
        import importlib
        # Config file dobara padhte hain
        new_cfg = eng._load_config()
        eng.CFG = new_cfg
        eng.SHOW_STAFF_PHONES    = new_cfg.get("show_staff_phones", False)
        eng.ACADEMIC_CALENDAR    = new_cfg.get("academic_calendar", eng.ACADEMIC_CALENDAR)
        eng.SYLLABUS_CFG         = new_cfg.get("syllabus_links", {})
        eng.ACHIEVEMENT_CFG      = new_cfg.get("achievement_links", {})
        eng.FEES_CFG             = new_cfg.get("fees", {})
        eng.MODELS_TO_TRY        = new_cfg.get("groq_models", eng.MODELS_TO_TRY)
        # Blacklist reset karo — naye models tryable ho jaayein
        eng._BLACKLISTED_MODELS.clear()
        eng._LIVE_MODELS_CACHE = []
        # Dependent data rebuild karo
        eng.SYLLABUS_ANSWERS     = eng._build_syllabus_answers()
        eng.ALL_SYLLABUS_ANSWER  = eng._build_all_syllabus_text()
        eng._build_faculty_answers()
        # Response cache clear karo taaki purane answers serve na hon
        eng._CACHE.clear()
        return jsonify({
            "status": "reloaded",
            "show_staff_phones": eng.SHOW_STAFF_PHONES,
            "calendar_year": eng.ACADEMIC_CALENDAR.get("year"),
            "student_achievement_year": eng.ACHIEVEMENT_CFG.get("student_year"),
            "models": eng.MODELS_TO_TRY,
            "message": "✅ Config reloaded — changes active immediately (no restart needed)"
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/model-status", methods=["GET"])
def model_status():
    """Kaunse models active hain, kaunse blacklist mein hain — status check."""
    try:
        import svims_engine as eng
        return jsonify({
            "configured_models": eng.MODELS_TO_TRY,
            "blacklisted": list(eng._BLACKLISTED_MODELS),
            "active_models": eng._get_active_models(),
            "live_models_cached": eng._LIVE_MODELS_CACHE,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route("/api/rebuild", methods=["POST"])
def rebuild():
    """Knowledge base rebuild karo (admin use)"""
    global v_store, bot_chain
    try:
        v_store = create_knowledge_base()
        bot_chain = create_chatbot(v_store)
        return jsonify({"status": "rebuilt", "message": "Knowledge base rebuilt successfully"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    print("🚀 Server: http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)