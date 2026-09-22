"""
SVIMS CampusBot — Engine ("Brain")
==================================
ANSWER PIPELINE (priority order):

  LAYER 0  Greeting / thanks / bye            → static, no API
  LAYER 1  Identity ("who are you")           → static, no API
  LAYER 2  Pure math (2+5=?)                  → direct, no API
  LAYER 3  Out-of-scope guard                 → static, no API
  LAYER 4  DETERMINISTIC FACT ANSWERS         → svims_facts.py + config se
           (fees, courses, seats, admission, contacts, HOD,            no API
            scholarships, library, hostel, cells, events, ...)
  LAYER 5  DYNAMIC SCRAPED ANSWERS            → knowledge/site_pages.json se
           (latest notifications, results, time tables, events)        no API
  LAYER 6  RAG: FAISS context + Groq LLM      → website-scraped context ke
           saath strict grounded answer                                 API
  LAYER 7  Graceful fallback                  → contact info + website

DESIGN RULES:
  — College ka saara data: svims_facts.py (verified) + svimi.org scraping
  — PDF se answer matching (purana svims_qa_loader system) POORA HATA DIYA
  — Bina Groq key ke bhi server chalta hai (Layer 0-5 + Layer 7 kaam karte hain)
  — Bina FAISS/embeddings ke bhi server chalta hai (facts layers kaam karte hain)
  — Engine kabhi bhi exception bahar nahi throw karta
"""

import os
import re
import json
import time
import threading

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
load_dotenv()

import svims_facts as F

# ══════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(BASE_DIR, "svims_config.json")


def _load_config():
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Config load failed ({e}) — using defaults")
        return {}


CFG = _load_config()

ACADEMIC_CALENDAR = CFG.get("academic_calendar", {
    "year": "2025-26",
    "link": "https://www.svimi.org/assets/images/Academic_Calender_2025-26.pdf",
})
SYLLABUS_CFG = CFG.get("syllabus_links", {})
ACHIEVEMENT_CFG = CFG.get("achievement_links", {})
MODELS_TO_TRY = CFG.get("groq_models", [
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-20b",
    "meta-llama/llama-4-scout-17b-16e-instruct",
])


def reload_config():
    """svims_config.json dobara padho (server restart ke bina)."""
    global CFG, ACADEMIC_CALENDAR, SYLLABUS_CFG, ACHIEVEMENT_CFG, MODELS_TO_TRY
    CFG = _load_config()
    ACADEMIC_CALENDAR = CFG.get("academic_calendar", ACADEMIC_CALENDAR)
    SYLLABUS_CFG = CFG.get("syllabus_links", {})
    ACHIEVEMENT_CFG = CFG.get("achievement_links", {})
    MODELS_TO_TRY = CFG.get("groq_models", MODELS_TO_TRY)
    _BLACKLISTED_MODELS.clear()
    _CACHE.clear()


# ══════════════════════════════════════════════════════════════════
# GROQ CLIENTS — lazy init (bina key ke import pe crash NAHI hota)
# ══════════════════════════════════════════════════════════════════

def _collect_api_keys():
    keys = []
    i = 1
    while True:
        v = os.getenv(f"GROQ_API_KEY_{i}", "").strip()
        if not v:
            break
        keys.append(v)
        i += 1
    legacy = os.getenv("GROQ_API_KEY", "").strip()
    if legacy and legacy not in keys:
        keys.append(legacy)
    return keys


GROQ_API_KEYS = _collect_api_keys()
_groq_clients = []
_key_index = 0
_clients_lock = threading.Lock()


def groq_ready():
    return len(GROQ_API_KEYS) > 0


def _get_clients():
    global _groq_clients
    if _groq_clients or not GROQ_API_KEYS:
        return _groq_clients
    with _clients_lock:
        if not _groq_clients:
            from groq import Groq
            _groq_clients = [Groq(api_key=k) for k in GROQ_API_KEYS]
            print(f"✅ Engine: {len(_groq_clients)} Groq key(s) loaded")
    return _groq_clients


def _get_client():
    """Round-robin key rotation — load balance + auto-failover."""
    global _key_index
    clients = _get_clients()
    if not clients:
        return None
    idx = _key_index % len(clients)
    _key_index = (_key_index + 1) % len(clients)
    return clients[idx]


# ══════════════════════════════════════════════════════════════════
# SMART MODEL MANAGER (purane code ka achha hissa — rakha)
# ══════════════════════════════════════════════════════════════════
_BLACKLISTED_MODELS = set()
_LIVE_MODELS_CACHE = []
_LIVE_MODELS_FETCHED_AT = 0
_NON_CHAT_KEYWORDS = ["whisper", "tts", "vision", "distil", "guard", "embed",
                      "moderation", "preview"]


def _fetch_live_groq_models():
    global _LIVE_MODELS_CACHE, _LIVE_MODELS_FETCHED_AT
    now = time.time()
    if _LIVE_MODELS_CACHE and (now - _LIVE_MODELS_FETCHED_AT) < 3600:
        return _LIVE_MODELS_CACHE
    try:
        import requests as _req
        r = _req.get("https://api.groq.com/openai/v1/models",
                     headers={"Authorization": f"Bearer {GROQ_API_KEYS[0]}"},
                     timeout=6)
        if r.status_code == 200:
            models = [m["id"] for m in r.json().get("data", [])
                      if not any(kw in m["id"].lower() for kw in _NON_CHAT_KEYWORDS)]
            if models:
                _LIVE_MODELS_CACHE = models
                _LIVE_MODELS_FETCHED_AT = now
    except Exception:
        pass
    return _LIVE_MODELS_CACHE


def _get_active_models():
    active = [m for m in MODELS_TO_TRY if m not in _BLACKLISTED_MODELS]
    if active:
        return active
    live = _fetch_live_groq_models()
    if live:
        _BLACKLISTED_MODELS.clear()
        return live
    _BLACKLISTED_MODELS.clear()
    return MODELS_TO_TRY


def _call_groq(messages):
    """Key rotation + model fallback + retries ke saath Groq call."""
    last_error = None
    clients = _get_clients()
    if not clients:
        raise RuntimeError("No Groq API key configured")

    for _key_attempt in range(len(clients)):
        client = _get_client()
        for model in _get_active_models():
            for attempt in range(3):
                try:
                    response = client.chat.completions.create(
                        model=model, messages=messages,
                        max_tokens=700, temperature=0.0,
                    )
                    return response.choices[0].message.content
                except Exception as e:
                    last_error = e
                    err = str(e).lower()
                    if any(x in err for x in ["invalid_api_key", "401"]):
                        break
                    if any(x in err for x in ["model_not_found", "does not exist",
                                              "model not found", "deprecated"]):
                        _BLACKLISTED_MODELS.add(model)
                        break
                    if any(x in err for x in ["413", "request too large",
                                              "tokens_per_minute"]):
                        break
                    if any(x in err for x in ["429", "rate_limit"]):
                        if attempt < 2:
                            time.sleep(2 ** attempt)
                            continue
                        break
                    break

    # Live list se fresh models try karo (last resort)
    for model in (_fetch_live_groq_models() or []):
        if model in MODELS_TO_TRY:
            continue
        for client in clients:
            try:
                response = client.chat.completions.create(
                    model=model, messages=messages,
                    max_tokens=700, temperature=0.0)
                return response.choices[0].message.content
            except Exception as e:
                last_error = e

    raise last_error if last_error else RuntimeError("No working Groq model found")


# ══════════════════════════════════════════════════════════════════
# RESPONSE CACHE — same question → no API call (30 min TTL)
# ══════════════════════════════════════════════════════════════════
_CACHE = {}
_CACHE_TTL = 1800


def _cache_get(key):
    entry = _CACHE.get(key)
    if entry and (time.time() - entry[1]) < _CACHE_TTL:
        return entry[0]
    return None


def _cache_set(key, value):
    _CACHE[key] = (value, time.time())
    if len(_CACHE) > 400:
        oldest = sorted(_CACHE.items(), key=lambda x: x[1][1])[:80]
        for k, _ in oldest:
            del _CACHE[k]


# ══════════════════════════════════════════════════════════════════
# TEXT HELPERS
# ══════════════════════════════════════════════════════════════════

def _norm(q):
    """Lowercase + punctuation hatao + extra spaces hatao."""
    q = q.lower().strip()
    q = re.sub(r"[^a-z0-9. +]", " ", q)
    return " ".join(q.split())


# Common typos → canonical words (query expansion ka compact version)
_TYPO_FIXES = {
    "slyabus": "syllabus", "sylabus": "syllabus", "slybus": "syllabus",
    "sllyabus": "syllabus", "sillabus": "syllabus", "sllaybus": "syllabus",
    "palcements": "placements", "placments": "placement",
    "schoalrship": "scholarship", "scholrship": "scholarship",
    "addmission": "admission", "admision": "admission",
    "libary": "library", "libraray": "library",
    "hostle": "hostel", "faculity": "faculty", "faculy": "faculty",
    "driector": "director", "dierctor": "director",
    "attendence": "attendance", "atendance": "attendance",
    "fess": "fees", "feees": "fees", "faculites": "faculties",
    "achivments": "achievements", "achivment": "achievement",
    "alumini": "alumni", "alumnii": "alumni", "semster": "semester",
}


# Important keywords — inke fuzzy matches query mein correct ho jaate hain
_VOCAB = {
    # Domain keywords (typo-correction targets)
    "syllabus", "admission", "scholarship", "placement", "faculty", "faculties",
    "library", "hostel", "attendance", "director", "fees", "semester",
    "achievements", "calendar", "notification", "result", "timetable",
    "eligibility", "scholarships", "recruiter", "recruiters", "canteen",
    "committee", "ragging", "counselling", "programs", "programme",
    # Words that must NEVER be fuzzy-changed (warna facilities→faculties,
    # mission→admission jaise galat conversion ho jaate hain)
    "facilities", "vision", "mission", "sports", "dress", "uniform",
    "events", "clubs", "cells", "hostels", "contact", "contacts",
}


def _fix_typos(q):
    """Exact typo-map + word-level fuzzy match (admisson→admission type)."""
    from difflib import get_close_matches
    out = []
    for w in q.split():
        if w in _TYPO_FIXES:
            out.append(_TYPO_FIXES[w])
            continue
        if w not in _VOCAB and len(w) >= 6:
            close = get_close_matches(w, _VOCAB, n=1, cutoff=0.8)
            if close:
                out.append(close[0])
                continue
        out.append(w)
    return " ".join(out)


# ══════════════════════════════════════════════════════════════════
# LAYER 0-3: GREETING / IDENTITY / MATH / OUT-OF-SCOPE
# ══════════════════════════════════════════════════════════════════
_GREETINGS = {"hi", "hello", "hey", "hii", "helo", "hiii", "namaste",
              "good morning", "good afternoon", "good evening", "yo", "sup"}
_THANKS = {"thanks", "thank you", "thanku", "thx", "ty", "thankyou", "great", "nice",
           "awesome", "perfect", "ok", "okay", "cool", "good"}
_BYE = {"bye", "goodbye", "see you", "alright", "that's all", "thats all"}

_MATH_PATTERN = re.compile(r"^[\d\s+\-*/().=?]+$")

_NON_SVIMS_TOPICS = [
    "prime minister", "president of india", "weather today", "write code",
    "write a program", "python code", "java code", "recipe", "movie review",
    "cricket score", "stock price", "who is elon musk", "who is modi",
    "who is ambani", "who is bill gates", "who is sachin", "who is virat",
    "who is dhoni", "capital of", "population of", "joke", "poem about",
    "story about", "what is ai", "what is machine learning", "chatgpt",
    "taj mahal", "pythagoras", "explain theorem", "newton", "einstein",
    "bollywood", "hollywood", "cricket team", "translate this",
]


def _is_out_of_scope(q):
    if q in _GREETINGS or q in _THANKS or q in _BYE:
        return False
    return any(t in q for t in _NON_SVIMS_TOPICS)


_MATH_PREFIXES = ("what is ", "whats ", "what's ", "calculate ", "how much is ",
                  "solve ", "compute ", "kitna hota hai ", "kitna hai ")


def _is_pure_math(q):
    ql = q.lower()
    for p in _MATH_PREFIXES:
        if ql.startswith(p):
            ql = ql[len(p):]
            break
    ql = ql.strip()
    return bool(_MATH_PATTERN.match(ql)) and len(ql) < 30 and any(c.isdigit() for c in ql)


def _safe_math(q):
    """Sirf digits/operators — evaluate karo (eval injection safe)."""
    ql = q.lower()
    for p in _MATH_PREFIXES:
        if ql.startswith(p):
            q = q[len(p):]
            break
    expr = q.replace("?", "").replace("=", "").strip()
    try:
        return str(int(eval(expr, {"__builtins__": {}}, {})))
    except Exception:
        try:
            return str(round(float(eval(expr, {"__builtins__": {}}, {})), 4))
        except Exception:
            return None


# ══════════════════════════════════════════════════════════════════
# LAYER 4: DETERMINISTIC FACT ANSWERS (zero hallucination, zero API)
# Har function → (answer, link) ya None
# ══════════════════════════════════════════════════════════════════

def _ans_fees(q):
    if not any(w in q for w in ["fee", "fees", "cost", "tuition", "charge"]):
        return None
    # Online payment pehle check (different intent)
    if any(w in q for w in ["pay online", "online payment", "pay fee online",
                            "how to pay", "payment portal", "pay fees online"]):
        return None  # _ans_portals handle karega
    if "refund" in q:
        return ("**Fee Refund Policy**\n\nFee refund rules institute ki official "
                "Fee Refund Policy document mein diye gaye hain.", F.FEE_REFUND_POLICY_URL)
    course = F.find_course(q)
    if course:
        return (f"**{course['name']} — Fee**\n\n— Fee: {course['fee']}\n"
                f"— Seats: {course['seats']}\n— Duration: {course['duration']}",
                "https://www.svimi.org/under-graduate.php" if course["level"] == "UG"
                else "https://www.svimi.org/post-graduate.php")
    return (F.fee_table(), "https://www.svimi.org/scholarship.php")


def _ans_seats(q):
    if not any(w in q for w in ["seat", "seats", "intake", "capacity", "how many seats"]):
        return None
    course = F.find_course(q)
    if course:
        return (f"**{course['name']}** — {course['seats']} seats (Student Intake).",
                "https://www.svimi.org/under-graduate.php" if course["level"] == "UG"
                else "https://www.svimi.org/post-graduate.php")
    lines = ["**Student Intake (Seats) — SVIMS**", ""]
    for c in F.COURSES:
        lines.append(f"— {c['name']}: {c['seats']} seats")
    return ("\n".join(lines), "https://www.svimi.org/under-graduate.php")


def _ans_eligibility(q):
    if not any(w in q for w in ["eligib", "eligibal", "criteria", "qualification",
                                "minimum marks", "can i get admission in"]):
        return None
    course = F.find_course(q)
    if course:
        return (f"**{course['name']} — Eligibility**\n\n— {course['eligibility']}\n"
                f"— Admission: {course['admission']}",
                F.ADMISSION["admission_url"])
    return ("**Eligibility — SVIMS**\n\n"
            f"— UG (BBA/BCA): {F.UG_ELIGIBILITY_COMMON}\n"
            "— B.Sc.: 10+2 with Physics, Maths and Chemistry/Biology (or relevant Diploma)\n"
            "— PG (MBA/MCA/M.Sc.): Graduate with min. 50% (45% for SC/ST/OBC of M.P.)\n"
            "— M.Sc. CS: B.Sc./BCA/B.Com/B.A. with Mathematics",
            F.ADMISSION["admission_url"])


def _ans_admission(q):
    if not any(w in q for w in ["admission", "apply", "admit", "enroll", "counselling",
                                "counseling", "cmat"]):
        return None
    if "mba" in q or "cmat" in q:
        return ("**Admission Process — MBA (FT/FA/MM)**\n\n" + F.ADMISSION["pg"] +
                f"\n\nCounselling portal: {F.ADMISSION['counselling_site']}",
                F.ADMISSION["admission_url"])
    if any(w in q for w in ["mca", "m.sc", "msc"]):
        return ("**Admission Process — MCA / M.Sc.**\n\nMCA & M.Sc. admissions are "
                "through DTE M.P. counselling on qualifying-exam merit. "
                f"Counselling portal: {F.ADMISSION['counselling_site']}",
                F.ADMISSION["admission_url"])
    if any(w in q for w in ["bba", "bca", "bsc", "b sc", "b.sc", "ug", "under graduate",
                            "undergraduate"]):
        return ("**Admission Process — UG (BBA/BCA/B.Sc.)**\n\n" + F.ADMISSION["ug"],
                F.ADMISSION["admission_url"])
    return ("**Admission Process — SVIMS**\n\n**UG (BBA/BCA/B.Sc.):** " + F.ADMISSION["ug"] +
            "\n\n**PG (MBA/MCA/M.Sc.):** " + F.ADMISSION["pg"] +
            f"\n\nAdmission helpline: {F.CONTACTS['admission_ug']} (UG), "
            f"{F.CONTACTS['admission_mba']} (MBA), {F.CONTACTS['admission_mca']} (MCA)",
            F.ADMISSION["admission_url"])


def _ans_semesters(q):
    if not any(w in q for w in ["semester", "semesters", "sem", "duration",
                                "how many years", "years course"]):
        return None
    course = F.find_course(q)
    if course:
        return (f"**{course['name']}** — {course['duration']} programme with "
                f"{course['semesters']} semesters.",
                "https://www.svimi.org/under-graduate.php" if course["level"] == "UG"
                else "https://www.svimi.org/post-graduate.php")
    if any(w in q for w in ["all course", "each course", "every course", "all program"]):
        lines = ["**Programme Duration & Semesters — SVIMS**", ""]
        for c in F.COURSES:
            lines.append(f"— {c['name']}: {c['duration']} ({c['semesters']} semesters)")
        return ("\n".join(lines), "https://www.svimi.org/under-graduate.php")
    return None


def _ans_courses(q):
    if not any(w in q for w in ["course", "courses", "program", "programme", "programmes",
                                "branch", "departments offer", "what all"]):
        return None
    course = F.find_course(q)
    if course and any(w in q for w in ["about", "detail", "tell me", "info", "information"]):
        return (F.course_detail(course),
                "https://www.svimi.org/under-graduate.php" if course["level"] == "UG"
                else "https://www.svimi.org/post-graduate.php")
    return (F.courses_overview() +
            "\n\nNOT OFFERED at SVIMS: " + ", ".join(F.NOT_OFFERED),
            "https://www.svimi.org/under-graduate.php")


def _ans_course_detail(q):
    course = F.find_course(q)
    if not course:
        return None
    if any(w in q for w in ["about", "detail", "tell me about", "info", "information",
                            "what is"]):
        return (F.course_detail(course),
                "https://www.svimi.org/under-graduate.php" if course["level"] == "UG"
                else "https://www.svimi.org/post-graduate.php")
    return None


def _ans_leadership(q):
    role_map = [
        (["director", "dr george", "george thomas"], F.LEADERSHIP[3]),
        (["chairman"], F.LEADERSHIP[1]),
        (["patron"], F.LEADERSHIP[0]),
        (["secretary"], F.LEADERSHIP[2]),
    ]
    for keys, person in role_map:
        if any(k in q for k in keys):
            return (f"**{person['role']} — SVIMS**\n\n{person['name']}\n{person['detail']}",
                    "https://www.svimi.org/leadership.php?q=director")
    if any(w in q for w in ["leadership", "management of college", "who runs"]):
        lines = ["**SVIMS Leadership**", ""]
        for p in F.LEADERSHIP:
            lines.append(f"— {p['role']}: {p['name']} ({p['detail']})")
        return ("\n".join(lines), "https://www.svimi.org/leadership.php?q=director")
    return None


def _ans_hod(q):
    if not any(w in q for w in ["hod", "head of", "head of the department",
                                "department head"]):
        return None
    if any(w in q for w in ["cs", "computer", "bioscience", "biotechnology", "microbiology",
                            "bioinformatics", "bca", "b.sc", "bsc", "mca", "m.sc", "msc"]):
        d = F.DEPARTMENTS["cs"]
    elif any(w in q for w in ["pg", "mba"]):
        d = F.DEPARTMENTS["pg"]
    elif any(w in q for w in ["ug", "bba"]):
        d = F.DEPARTMENTS["ug"]
    elif "all" in q or "list" in q:
        lines = ["**Department Heads (HODs) — SVIMS**", ""]
        for d_ in F.DEPARTMENTS.values():
            lines.append(f"— {d_['name']}: {d_['hod']} ({d_['hod_designation']})")
        return ("\n".join(lines), "https://www.svimi.org/departments/faculties.php?q=faculty_cs")
    else:
        d = F.DEPARTMENTS["cs"]
    return (f"**HOD — {d['name']}**\n\n{d['hod']} ({d['hod_designation']})\n"
            f"Programs: {d['programs']}\n\nFull faculty list: {d['faculty_url']}",
            d["faculty_url"])


def _ans_faculty(q):
    if not any(w in q for w in ["faculty", "faculties", "professor", "teacher",
                                "teaching staff", "lecturer"]):
        return None
    lines = ["**Faculty — SVIMS (Department Overview)**", ""]
    for d in F.DEPARTMENTS.values():
        lines.append(f"— **{d['name']}** — HOD: {d['hod']}")
        lines.append(f"   Programs: {d['programs']}")
        lines.append(f"   Full list: {d['faculty_url']}")
    lines.append("")
    lines.append("Individual faculty members ke naam, designation aur qualification "
                 "ke liye department pages dekho (links upar).")
    lines.append(f"Faculty queries ke liye email: {F.CONTACTS['email']}")
    return ("\n".join(lines), "https://www.svimi.org/departments/faculties.php?q=faculty_cs")


def _ans_placement(q):
    if not any(w in q for w in ["placement", "recruiter", "job", "package", "salary",
                                "company", "internship", "training and placement",
                                "tpo", "t&p"]):
        return None
    if any(w in q for w in ["highest package", "average package", "placement rate",
                            "placement percentage", "placement stat", "placement record",
                            "how many student", "placed student", "placement detail",
                            "salary package"]):
        return ("I don't have exact placement statistics (packages/percentages) — "
                "institute inko regularly apne Prominent Selections page pe update "
                "karta hai. Verified data wahan dekho:",
                "https://www.svimi.org/placement/prominent-selections.php")
    if any(w in q for w in ["recruiter", "company", "companies"]):
        return ("**Recruiters at SVIMS**\n\n" +
                ", ".join(F.PLACEMENT["recruiters"]) +
                "\n\n(Prominent recruiters over the years — full logo wall website pe.)",
                "https://www.svimi.org/placement/recruiters.php")
    if any(w in q for w in ["team", "officer", "who handle", "incharge", "in charge",
                            "tpo", "t&p"]):
        lines = ["**Training & Placement Cell — Team**", ""]
        for m in F.PLACEMENT["team"]:
            lines.append(f"— {m['name']} ({m['role']})")
        return ("\n".join(lines), "https://www.svimi.org/placement/about-placement.php")
    team_lines = "\n".join(f"— {m['name']} ({m['role']})" for m in F.PLACEMENT["team"])
    return ("**Training & Placement Cell — SVIMS**\n\n" + F.PLACEMENT["training"] +
            "\n\n**Team:**\n" + team_lines +
            "\n\n**" + F.PLACEMENT["pep_model"] + "**\n\nRecruiters: " +
            ", ".join(F.PLACEMENT["recruiters"]),
            "https://www.svimi.org/placement/about-placement.php")


def _ans_scholarship(q):
    if not any(w in q for w in ["scholarship", "financial aid", "fee waiver",
                                "freeship", "stipend"]):
        return None
    lines = ["**Scholarship / Financial Aid — SVIMS**", ""]
    for s in F.SCHOLARSHIPS:
        lines.append(f"— **{s['name']}**: {s['detail']}")
    return ("\n".join(lines), "https://www.svimi.org/scholarship.php")


def _ans_library(q):
    if "library" not in q and "book" not in q and "journal" not in q:
        return None
    L = F.LIBRARY
    return (f"**Library — SVIMS**\n\n"
            f"— {L['books']} | {L['ebooks']} | {L['online_journals']}\n"
            f"— {L['print_journals']} | {L['cds']} | {L['encyclopedias']} encyclopedias\n\n"
            f"**Special Collections:** {L['special_collections']}\n\n"
            f"**Databases:** {L['databases']}\n\n"
            f"**Services:** {L['services']}",
            L["url"])


def _ans_hostel(q):
    if "hostel" not in q and "accommodation" not in q and "stay" not in q:
        return None
    H = F.HOSTEL
    return (f"**Hostel — SVIMS**\n\n{H['summary']}\n\n**Facilities (both hostels):**\n"
            f"{H['facilities']}\n\n**Girls hostel extra:** {H['girls_extra']}\n\n"
            f"Boys hostel: {H['boys_url']}\nGirls hostel: {H['girls_url']}",
            H["url"])


def _ans_facilities(q):
    # NOTE: word-boundary matching zaroori hai — warna "lab" "available" ke
    # andar mil jaata tha (substring bug)
    if re.search(r"\blabs?\b|\blaborator", q):
        return (f"**Laboratories — SVIMS**\n\n{F.LABS}", "https://www.svimi.org/infrastructure/computer.php")
    if re.search(r"\bsports?\b|\bgames?\b|playground|\bkhel", q):
        return (f"**Sports — SVIMS**\n\n{F.SPORTS}", "https://www.svimi.org/infrastructure/sports.php")
    if re.search(r"\bcanteen\b|\bfood\b|cafeteria|\bmess\b", q):
        return (f"**Canteen — SVIMS**\n\n{F.CANTEEN}", "https://www.svimi.org/infrastructure/canteen.php")
    if "auditorium" in q or "abhay prashal" in q:
        return (f"**Auditorium — SVIMS**\n\n{F.AUDITORIUM}", "https://www.svimi.org/infrastructure/auditorium.php")
    if any(w in q for w in ["infrastructure", "facilities", "facility", "campus feature"]):
        return ("**Facilities at SVIMS**\n\n"
                f"— Library: {F.LIBRARY['books']}, {F.LIBRARY['ebooks']}, journals & databases\n"
                f"— Labs: {F.LABS}\n"
                f"— Hostel: separate boys & girls hostels near campus\n"
                f"— Sports: outdoor playgrounds & indoor courts\n"
                f"— Canteen: on-campus, student-friendly prices\n"
                f"— Auditorium: Abhay Prashal\n"
                f"— Wi-Fi enabled campus with audio-visual facilities",
                "https://www.svimi.org/infrastructure/library.php")
    return None


def _ans_clubs(q):
    if "club" not in q:
        return None
    lines = ["**Activity Clubs — SVIMS**", ""]
    for name, url in F.CLUBS:
        lines.append(f"— {name}: {url}")
    return ("\n".join(lines), "https://www.svimi.org/activity-clubs/it-club.php")


def _ans_cells(q):
    cell_keys = {
        "edc": ["edc", "entrepreneurship"], "nss": ["nss", "national service"],
        "iic": [" iic ", "innovation council"], "rdc": ["rdc", "research development"],
        "cdc": ["cdc", "case development"], "iiic": ["iiic", "industry institute"],
    }
    if "cell" not in q and "cells" not in q and not any(
            any(k in f" {q} " for k in keys) for keys in cell_keys.values()):
        return None
    for key, keys in cell_keys.items():
        if any(k in f" {q} " for k in keys):
            cell = F.CELLS[key.upper()]  # FIX: F.CELLS keys UPPERCASE hain
            lines = [f"**{cell['name']} — SVIMS**", ""]
            if "about" in cell:
                lines.append(cell["about"])
            if "team" in cell:
                lines.append("\n**Team:**")
                for n, r in cell["team"]:
                    lines.append(f"— {n} ({r})")
            return ("\n".join(lines), cell["url"])
    # Generic "cells" question
    lines = ["**Cells at SVIMS**", ""]
    for key, cell in F.CELLS.items():
        lines.append(f"— **{key}** ({cell['name']}): {cell['url']}")
    return ("\n".join(lines), "https://www.svimi.org/cells/edc.php")


def _ans_events(q):
    if "prabandhotsav" in q or "annual fest" in q or "fest" in q:
        return ("**Prabandhotsav — Annual Fest of SVIMS**\n\n"
                "SVIMS ka annual fest — typically February/March mein. Celebrity "
                "concerts Abhay Prashal mein hote hain.\n\n"
                "**Past performers:** " + ", ".join(F.PRABANDHOTSAV_PERFORMERS),
                "https://www.svimi.org/event-gallery.php?q=events")
    if "srijan" in q:
        return ("**Srijan** — Cultural fest of SVIMS (typically November).",
                "https://www.svimi.org/event-gallery.php?q=events")
    if "khelotsav" in q:
        return ("**Khelotsav** — Sports week of SVIMS (typically January).",
                "https://www.svimi.org/event-gallery.php?q=events")
    if "nav udyami" in q or "navudyami" in q:
        return ("**Nav Udyami** — Entrepreneur Meet organized by EDC "
                "(typically February).",
                "https://www.svimi.org/cells/edc.php")
    if "abhisanskaran" in q:
        return ("**Abhisanskaran** — Induction Ceremony for new students "
                "(typically August).",
                "https://www.svimi.org/event-gallery.php?q=events")
    if "confluence" in q:
        return ("**Confluence** — Alumni Meet of SVIMS (typically March).",
                "https://www.svimi.org/alumni_association.php")
    if "event" in q or "festival" in q or "happening" in q:
        # Pehle scraped latest events try karo (Layer 5 ka kaam yahan inline)
        try:
            import svims_scraper as S
            res = S.get_events_summary(max_items=5)
            if res:
                title, items = res
                lines = ["**Latest Events — SVIMS** (from www.svimi.org)", ""]
                for it in items:
                    lines.append(f"— {it}")
                lines.append("")
                lines.append("Latest updates ke liye events page dekho:")
                return ("\n".join(lines),
                        "https://www.svimi.org/event-gallery.php?q=events")
        except Exception:
            pass
        lines = ["**Annual Events — SVIMS**", ""]
        for n, t, m in F.ANNUAL_EVENTS:
            lines.append(f"— {n} ({t}) — typically {m}")
        return ("\n".join(lines), "https://www.svimi.org/event-gallery.php?q=events")
    return None


def _ans_anti_ragging(q):
    if "ragging" not in q:
        return None
    A = F.ANTI_RAGGING
    return (f"**Anti-Ragging — SVIMS (Session 2026-27)**\n\n"
            f"SVIMS ne UGC Anti-Ragging Regulations, 2009 ke according committee "
            f"banaayi hai.\n\n"
            f"**Anti-Ragging Committee:** {', '.join(A['committee_2026_27'])}\n\n"
            f"**Nodal Officer:** {A['nodal_officer']}\n\n"
            f"**Monitoring Cell:** {', '.join(A['monitoring_cell'])}\n\n"
            f"{A['helpline']}\n\n"
            f"Ragging ka koi bhi case turant kisi bhi committee member, faculty ya "
            f"{F.CONTACTS['email']} pe report karo.",
            A["url"])


def _ans_attendance(q):
    if "attendance" not in q:
        return None
    return (f"**Attendance Policy — SVIMS**\n\n{F.ATTENDANCE_POLICY}",
            F.ATTENDANCE_POLICY_URL)


def _ans_dress_code(q):
    if "dress" not in q and "uniform" not in q and "apron" not in q:
        return None
    return (f"**Dress Code — SVIMS**\n\n{F.DRESS_CODE}", F.DRESS_CODE_URL)


def _ans_contact(q):
    if not any(w in q for w in ["contact", "phone", "email", "address", "number",
                                "reach", "toll free", "call", "where is svims",
                                "location"]):
        return None
    if "admission" in q and any(w in q for w in ["contact", "number", "phone", "call"]):
        return (f"**Admission Contact — SVIMS**\n\n"
                f"— UG Programmes: {F.CONTACTS['admission_ug']}\n"
                f"— MBA: {F.CONTACTS['admission_mba']}\n"
                f"— MCA: {F.CONTACTS['admission_mca']}\n"
                f"— Email: {F.CONTACTS['admission_email']}",
                "https://www.svimi.org/contact-us.php")
    return (F.contact_block(), "https://www.svimi.org/contact-us.php")


def _ans_portals(q):
    if any(w in q for w in ["pay fee", "fees online", "fee payment", "online payment",
                            "pay online", "pay fees", "payment portal", "fee portal"]):
        return ("**Online Fee Payment — SVIMS**\n\nStudents apni fees online de "
                "sakte hain:\n"
                f"1. Student ERP portal pe login karo: {F.PORTALS['student_erp']}\n"
                f"2. Online Fee Payment gateway se payment karo: {F.PORTALS['fee_payment']}",
                F.PORTALS["fee_payment"])
    if any(w in q for w in ["erp", "student portal", "student login", "login portal"]):
        return ("**Student ERP Portal**\n\n" + F.PORTALS["student_erp"] +
                "\n\nResults, fee payment aur academic records sab ERP se hoti hain.",
                F.PORTALS["student_erp"])
    return None


def _ans_syllabus(q):
    if "syllabus" not in q and "curriculum" not in q:
        return None
    course = F.find_course(q)
    key_map = {"bca": "bca", "bba": "bba", "bba_ft": "bba", "bba_ha": "bba",
               "mba": "mba", "mba_fa": "mba", "mba_mm": "mba", "mca": "mca",
               "msc_cs": "msc_cs", "bsc_cs": "bsc_cs", "bsc_bt": "bsc_bt",
               "bsc_bi": "bsc_bi", "bsc_mb": "bsc_mb"}
    if course and key_map.get(course["key"]) in SYLLABUS_CFG:
        entries = SYLLABUS_CFG[key_map[course["key"]]]
        lines = [f"**Syllabus — {course['name']}**", ""]
        for e in entries:
            lines.append(f"— {e['label']}: {e['link']}")
        return ("\n".join(lines),
                "https://www.svimi.org/under-graduate.php" if course["level"] == "UG"
                else "https://www.svimi.org/post-graduate.php")
    # All syllabus
    lines = ["**Syllabus PDFs — SVIMS**", ""]
    for group, entries in SYLLABUS_CFG.items():
        if group.startswith("_"):
            continue
        for e in entries:
            lines.append(f"— {e['label']}: {e['link']}")
    lines.append("")
    lines.append("Higher semester syllabi college website pe upload hote rahenge — "
                 "latest ke liye website check karo.")
    return ("\n".join(lines), "https://www.svimi.org/under-graduate.php")


def _ans_calendar(q):
    if not any(w in q for w in ["academic calendar", "calender", "calendar",
                                "semester dates", "holiday list"]):
        return None
    return (f"**Academic Calendar {ACADEMIC_CALENDAR.get('year', '')} — SVIMS**\n\n"
            f"Download PDF: {ACADEMIC_CALENDAR.get('link', '')}",
            ACADEMIC_CALENDAR.get("link"))


def _ans_achievements(q):
    if not any(w in q for w in ["achievement", "topper", "university rank", "award",
                                "research paper", "patent", "phd award"]):
        return None
    if "faculty" in q or "teacher" in q or "professor" in q:
        return (f"**Faculty Achievements {ACHIEVEMENT_CFG.get('faculty_year', '')}**\n\n"
                "Detailed report (awards, research, patents):",
                ACHIEVEMENT_CFG.get("faculty",
                    "https://www.svimi.org/assets/images/achievements/Faculty_Other_Achievement_2024-25.pdf"))
    return (f"**Student Achievements {ACHIEVEMENT_CFG.get('student_year', '')}**\n\n"
            "SVIMS students regularly secure top positions in DAVV university merit "
            "lists (BCA, BBA, B.Sc. programmes). Detailed report:",
            ACHIEVEMENT_CFG.get("student",
                "https://www.svimi.org/assets/images/achievements/Student_Achievements_2024-25.pdf"))


def _ans_misc(q):
    if any(w in q for w in ["nirf", "ranking", "rank"]):
        return ("**NIRF Ranking — SVIMS**\n\nSVIMS annually NIRF (Overall & "
                "Management category) mein participate karta hai. Reports "
                "(2018–2025) website pe available hain:", F.NIRF_URL)
    if "iqac" in q:
        return ("**IQAC — Internal Quality Assurance Cell**\n\nQuality sustenance "
                "and enhancement ke liye NAAC guidelines ke according kaam karta "
                "hai. Details, AQAR reports aur meetings:", F.IQAC_URL)
    if any(w in q for w in ["governing body", "trust", "samiti", "nyas"]):
        return ("**Governing Body — SVIMS**\n\nSVIMS Shri Vaishnav Shaikshanik Avam "
                "Parmarthik Nyas, Indore (est. 1987) ke under Shri Vaishnav Shikshan "
                "Samiti dwara operate hota hai. Members ki poori list:", F.GOVERNING_BODY_URL)
    if any(w in q for w in ["brochure", "prospectus"]):
        return ("**SVIMS Brochure**\n\n" + F.BROCHURE_URL, F.BROCHURE_URL)
    if any(w in q for w in ["virtual tour", "campus tour", "360"]):
        return ("**Virtual Campus Tour — SVIMS**\n\n" + F.VIRTUAL_TOUR_URL,
                F.VIRTUAL_TOUR_URL)
    if any(w in q for w in ["naac", "accreditation", "grade"]):
        return (f"**NAAC Accreditation — SVIMS**\n\n{F.INSTITUTE['naac']}\n\n"
                f"{F.INSTITUTE['iso']}", "https://www.svimi.org/recongnition-description.php")
    if any(w in q for w in ["autonomous", "autonomy"]):
        return ("**Autonomous Status**\n\nSVIMS is an Autonomous institute — "
                "self-governed academic structure under UGC guidelines, with DAVV "
                "degree affiliation.", "https://www.svimi.org/")
    if any(w in q for w in ["history", "about svims", "about college", "about institute",
                            "established", "old is svims"]):
        return (f"**About SVIMS**\n\n{F.INSTITUTE['description']}\n\n"
                f"{F.INSTITUTE['naac']}\n\n{F.INSTITUTE['campus']}",
                "https://www.svimi.org/about-institute-description.php")
    if any(w in q for w in ["vision", "mission"]):
        return ("**Vision** — To be the center of excellence in multidisciplinary "
                "education by instilling lifelong learning and skill development, "
                "transforming individuals to be globally competent, ethically and "
                "socially responsible professionals.\n\n"
                "**Mission** — (1) Quality education → advancement of knowledge & "
                "sustainable career (2) Holistic development & employability "
                "(3) Experiential, process-oriented pedagogy (4) Entrepreneurial "
                "orientation with moral & ethical values.",
                "https://www.svimi.org/vision.php")
    if "phd" in q or "research" in q and "centre" in q or "doctoral" in q:
        return (f"**Research at SVIMS**\n\n{F.RESEARCH}",
                "https://www.svimi.org/about-institute-description.php")
    return None


# Ordered pipeline of deterministic answer functions
_FACT_ANSWERERS = [
    _ans_syllabus,        # syllabus pehle (course keyword overlap avoid)
    _ans_calendar,
    _ans_portals,
    _ans_fees,
    _ans_seats,
    _ans_eligibility,
    _ans_admission,
    _ans_semesters,
    _ans_course_detail,
    _ans_courses,
    _ans_leadership,
    _ans_hod,
    _ans_faculty,
    _ans_placement,
    _ans_scholarship,
    _ans_library,
    _ans_hostel,
    _ans_facilities,
    _ans_clubs,
    _ans_cells,
    _ans_events,
    _ans_anti_ragging,
    _ans_attendance,
    _ans_dress_code,
    _ans_contact,
    _ans_achievements,
    _ans_misc,
]


def get_fact_answer(question):
    """Layer 4 — deterministic answer ya None."""
    q = _fix_typos(_norm(question))
    for answerer in _FACT_ANSWERERS:
        try:
            result = answerer(q)
        except Exception:
            result = None
        if result:
            answer, link = result
            if link:
                answer += f"\n\n🔗 **More Info:** {link}"
            return answer
    return None


# ══════════════════════════════════════════════════════════════════
# LAYER 5: DYNAMIC SCRAPED ANSWERS (notifications/results/time table)
# ══════════════════════════════════════════════════════════════════

def get_dynamic_answer(question):
    q = _fix_typos(_norm(question))
    try:
        import svims_scraper as S

        page_map = [
            (["notification", "notice", "announcement", "latest news"],
             "https://www.svimi.org/Notification.php"),
            (["result", "results", "marks", "grade card"],
             "https://www.svimi.org/Results.php"),
            (["time table", "timetable", "exam schedule", "exam date"],
             "https://www.svimi.org/Time-Table-Main.php"),
            (["atkt"],
             "https://www.svimi.org/Time-Table-ATKT.php"),
        ]
        for keys, url in page_map:
            if any(k in q for k in keys):
                res = S.get_dynamic_summary(url)
                if res:
                    title, items = res
                    lines = [f"**{title} — latest from www.svimi.org**", ""]
                    for it in items:
                        lines.append(f"— {it}")
                    lines.append("")
                    lines.append("Latest updates ke liye official page dekho:")
                    return ("\n".join(lines), url)
                # Cache nahi hai → seedha official page link do
                return (f"Latest {keys[0]}s ke liye official page dekho:", url)
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════
# LAYER 6: RAG — FAISS context + Groq
# ══════════════════════════════════════════════════════════════════

def _facts_prompt_block():
    """svims_facts ko compact prompt-text mein render karo."""
    lines = []
    lines.append(f"Full Name: {F.INSTITUTE['full_name']} (SVIMS), {F.INSTITUTE['city']} | "
                 f"Established {F.INSTITUTE['established']} | Autonomous")
    lines.append(f"Address: {F.INSTITUTE['address']}")
    lines.append(f"NAAC: {F.INSTITUTE['naac']}")
    lines.append(f"Affiliations: {F.INSTITUTE['affiliations']}")
    lines.append(f"Emails: {F.CONTACTS['email']} (main), {F.CONTACTS['admission_email']} (admission)")
    lines.append(f"Phones: {F.CONTACTS['phone']} | Toll Free: {F.CONTACTS['toll_free']}")
    lines.append(f"Admission: {F.CONTACTS['admission_ug']} (UG), "
                 f"{F.CONTACTS['admission_mba']} (MBA), {F.CONTACTS['admission_mca']} (MCA)")
    lines.append("Leadership: " + "; ".join(f"{p['role']} {p['name']}" for p in F.LEADERSHIP))
    lines.append("HODs: " + "; ".join(f"{d['name']} — {d['hod']}" for d in F.DEPARTMENTS.values()))
    lines.append("T&P Team: " + "; ".join(f"{m['name']} ({m['role']})"
                                          for m in F.PLACEMENT["team"]))
    lines.append("Courses & Fees: " + "; ".join(
        f"{c['name']} — {c['fee']}, {c['seats']} seats, {c['duration']}" for c in F.COURSES))
    lines.append("Attendance: minimum 75% in each subject (all courses)")
    lines.append("Scholarships: " + "; ".join(s["name"] for s in F.SCHOLARSHIPS))
    lines.append(f"Library: {F.LIBRARY['books']}, {F.LIBRARY['ebooks']}, "
                 f"{F.LIBRARY['online_journals']}")
    lines.append("Official website: www.svimi.org (sabse reliable source)")
    return "\n".join(lines)


_SYSTEM_PROMPT_TEMPLATE = """You are CampusBot — the official AI assistant of {inst_name}, {inst_city} (www.svimi.org).

LANGUAGE: Understand Hindi/Hinglish, but ALWAYS reply in English.

FORMATTING:
- NO markdown tables. Use simple dash lists (—) and short paragraphs.
- Keep answers concise and factual. No padding, no repetition.
- Do NOT add URLs in your text — the system appends one official link separately.

STRICT GROUNDING RULES — NO EXCEPTIONS:
1. Answer ONLY from the KNOWN FACTS and the WEBSITE CONTEXT given below.
2. If the answer is not present there, say exactly:
   "I don't have this specific information. Please visit www.svimi.org or contact svimi@svimi.org | Toll Free: 1800-233-2601"
   Never guess, never invent plausible-sounding details.
3. NEVER invent: phone numbers, emails, URLs, names, statistics (placement %, packages, student counts), dates, timings, committee members.
4. Placement statistics question → direct to https://www.svimi.org/placement/prominent-selections.php (do NOT quote numbers).
5. Do NOT compare/rank courses ("which is better") — no comparative data exists.
6. Only official emails: svimi@svimi.org and admission@svimi.org. Only the phone numbers in KNOWN FACTS.
7. Faculty questions: give HOD + department link, not invented individual details.
8. One campus only: Gumasta Nagar, Indore.

KNOWN FACTS (verified from official website):
{facts}

WEBSITE CONTEXT (scraped from www.svimi.org):
{context}"""


def _rag_answer(question, vector_store, history=None):
    """FAISS retrieval + Groq generation. Exception upar handle hoti hai."""
    context = ""
    if vector_store is not None:
        try:
            retriever = vector_store.as_retriever(search_kwargs={"k": 6})
            docs = retriever.invoke(question)
            # Query ke words se relevant chunks pehle
            context = "\n\n---\n\n".join(d.page_content for d in docs[:5])
        except Exception as e:
            print(f"  ⚠️ Retrieval failed: {e}")

    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        inst_name=F.INSTITUTE["full_name"],
        inst_city=F.INSTITUTE["city"],
        facts=_facts_prompt_block(),
        context=context or "(no additional context found)",
    )

    messages = [{"role": "system", "content": system_prompt}]
    if history:
        for msg in history[-4:]:
            role = msg.get("role", "")
            content = str(msg.get("content", ""))[:1500]
            if role == "user":
                messages.append({"role": "user", "content": content})
            elif role in ("bot", "assistant"):
                messages.append({"role": "assistant", "content": content})
    messages.append({"role": "user", "content": question})

    answer = _call_groq(messages)

    if not answer or len(answer.strip()) < 3:
        answer = ("I'm not sure about the exact details. Please visit www.svimi.org "
                  "or contact svimi@svimi.org | Toll Free: 1800-233-2601")
    return answer


# ══════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════

_FALLBACK = ("I don't have this specific information. Please visit www.svimi.org "
             "or contact svimi@svimi.org | Toll Free: 1800-233-2601")


def get_answer(question, vector_store, history=None):
    """
    Main API — server ise call karta hai.
      vector_store: FAISS store ya None (graceful degradation)
      history: [{"role": "user"|"bot", "content": ...}, ...]
    """
    try:
        raw = question.strip()
        q = _fix_typos(_norm(raw))

        # ── LAYER 0: greeting / thanks / bye ──
        if q in _GREETINGS or (len(q) < 25 and q.startswith(("hi ", "hello ", "hey "))
                               and "svims" not in q and "?" not in q):
            return ("👋 Hello! I'm SVIMS CampusBot — official AI assistant of "
                    f"{F.INSTITUTE['full_name']}, Indore.\n\n"
                    "Ask me about courses, fees, admissions, faculty, placements, "
                    "hostel, scholarships, exams or anything else about the campus!")
        if q in _THANKS:
            return ("😊 You're welcome! Ask me anytime about SVIMS — courses, "
                    "fees, admissions, placements and more.\n\n"
                    f"📧 {F.CONTACTS['email']} | 🆓 {F.CONTACTS['toll_free']}")
        if q in _BYE:
            return ("👋 Goodbye! SVIMS CampusBot is always here for your queries.\n\n"
                    f"📧 {F.CONTACTS['email']} | 🌐 www.svimi.org")

        # ── LAYER 1: identity ──
        if any(q == p or q.startswith(p + " ") for p in
               ["who are you", "what are you", "who is this", "your name",
                "what can you do", "help", "introduce yourself"]) or "campusbot" in q:
            return ("🎓 I'm **SVIMS CampusBot** — the official AI assistant of "
                    f"{F.INSTITUTE['full_name']}, Indore (www.svimi.org).\n\n"
                    "Main aapko in topics mein help kar sakta hoon:\n"
                    "— Courses, eligibility, fees & seats\n"
                    "— Admission process (UG/PG)\n"
                    "— Faculty, HODs & leadership\n"
                    "— Placements, scholarships, hostels, library\n"
                    "— Notifications, results, time tables\n"
                    "— Cells, clubs, events aur bahut kuch!\n\n"
                    "All my information comes from the official college website.")

        # ── LAYER 2: pure math ──
        if _is_pure_math(raw):
            result = _safe_math(raw)
            if result:
                return f"The answer is **{result}**."
            return "Please give a valid arithmetic expression (e.g. 2+5*3)."

        # ── LAYER 3: out of scope ──
        if _is_out_of_scope(q):
            return ("I'm SVIMS CampusBot — I only help with information about "
                    f"{F.INSTITUTE['full_name']}, Indore.\n\n"
                    "Ask me about courses, fees, admissions, faculty, placements "
                    "or campus facilities.\n\n"
                    f"📧 {F.CONTACTS['email']} | 🆓 {F.CONTACTS['toll_free']}")

        # ── LAYER 4: deterministic facts ──
        fact_answer = get_fact_answer(raw)
        if fact_answer:
            return fact_answer

        # ── LAYER 5: dynamic scraped data ──
        dynamic = get_dynamic_answer(raw)
        if dynamic:
            answer, link = dynamic
            return answer + f"\n\n🔗 **More Info:** {link}"

        # ── LAYER 6: RAG + Groq ──
        if groq_ready():
            cache_key = None if history else q
            if cache_key:
                cached = _cache_get(cache_key)
                if cached:
                    return cached
            answer = _rag_answer(raw, vector_store, history)
            if cache_key:
                _cache_set(cache_key, answer)
            return answer

        # ── LAYER 7: graceful fallback (no API key) ──
        return ("⚠️ AI answering is not configured yet (missing Groq API key in "
                ".env). Basic queries (courses, fees, contacts, admission...) still "
                "work.\n\n" + _FALLBACK)

    except Exception as e:
        err = str(e).lower()
        print(f"🚨 Engine error: {e}")
        if any(x in err for x in ["quota", "429", "rate_limit"]):
            return ("⏳ Server busy — please try again in a moment.\n\n"
                    f"📧 {F.CONTACTS['email']} | 🆓 {F.CONTACTS['toll_free']}")
        if any(x in err for x in ["invalid_api_key", "401"]):
            return "❌ Groq API key error — .env file mein valid key daalo."
        return ("😊 Please rephrase and try again!\n\n"
                f"📧 {F.CONTACTS['email']} | 🌐 www.svimi.org")


# ══════════════════════════════════════════════════════════════════
# LEGACY COMPAT — purana server code chain-dict expect karta tha
# ══════════════════════════════════════════════════════════════════

def create_chatbot(vector_store):
    """Compatibility wrapper — naya engine stateless hai."""
    return {"vector_store": vector_store}


def engine_status():
    """Status info — /api/status ke liye."""
    try:
        import svims_scraper as S
        scrape = S.status()
    except Exception:
        scrape = {}
    return {
        "groq_configured": groq_ready(),
        "facts_loaded": True,
        "vector_store_ready": True,   # server set karta hai
        "knowledge": scrape,
    }
