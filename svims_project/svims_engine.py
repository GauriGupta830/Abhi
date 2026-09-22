import os
import re
import json
import time
from groq import Groq
from dotenv import load_dotenv
from difflib import get_close_matches, SequenceMatcher

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

GROQ_API_KEYS = []
i = 1
while True:
    v = os.getenv(f"GROQ_API_KEY_{i}", "").strip()
    if not v:
        break
    GROQ_API_KEYS.append(v)
    i += 1

_legacy = os.getenv("GROQ_API_KEY", "").strip()
if _legacy and _legacy not in GROQ_API_KEYS:
    GROQ_API_KEYS.append(_legacy)

if not GROQ_API_KEYS:
    raise ValueError("No Groq API key found! Set GROQ_API_KEY_1 in .env")

print(f"✅ Engine loaded with {len(GROQ_API_KEYS)} Groq key(s): "
      f"{[k[:10] + '...' for k in GROQ_API_KEYS]}")

_groq_clients = [Groq(api_key=k) for k in GROQ_API_KEYS]
_key_index = 0


def _get_client():
    global _key_index
    idx = _key_index
    client = _groq_clients[idx % len(_groq_clients)]
    key_preview = GROQ_API_KEYS[idx % len(GROQ_API_KEYS)][:10]
    print(f"🔑 Using Key #{(idx % len(_groq_clients)) + 1} ({key_preview}...) for this request")
    _key_index = (_key_index + 1) % len(_groq_clients)
    return client


groq_client = _groq_clients[0]

# ══════════════════════════════════════════════════════
# CONFIG LOADER — svims_config.json se sab updatable data
# ══════════════════════════════════════════════════════
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "svims_config.json")

def _load_config():
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Config load failed ({e}) — using defaults")
        return {}

CFG = _load_config()

SHOW_STAFF_PHONES = CFG.get("show_staff_phones", False)
ACADEMIC_CALENDAR = CFG.get("academic_calendar", {
    "year": "2025-26",
    "link": "https://www.svimi.org/assets/images/Academic_Calender_2025-26.pdf"
})
ACHIEVEMENT_CFG = CFG.get("achievement_links", {})
FEES_CFG = CFG.get("fees", {})
MODELS_TO_TRY = CFG.get("groq_models", [
    "llama-3.1-8b-instant",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-20b",
])

# ══════════════════════════════════════════════════════
# SMART MODEL MANAGER
# ══════════════════════════════════════════════════════
_BLACKLISTED_MODELS = set()
_LIVE_MODELS_CACHE = []
_LIVE_MODELS_FETCHED_AT = 0
_LIVE_MODELS_TTL = 3600
_NON_CHAT_KEYWORDS = ["whisper", "tts", "vision", "distil", "guard", "embed", "moderation"]


def _fetch_live_groq_models():
    global _LIVE_MODELS_CACHE, _LIVE_MODELS_FETCHED_AT
    now = time.time()
    if _LIVE_MODELS_CACHE and (now - _LIVE_MODELS_FETCHED_AT) < _LIVE_MODELS_TTL:
        return _LIVE_MODELS_CACHE
    try:
        import requests as _req
        r = _req.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {GROQ_API_KEYS[0]}"},
            timeout=6
        )
        if r.status_code == 200:
            all_models = r.json().get("data", [])
            chat_models = [
                m["id"] for m in all_models
                if not any(kw in m["id"].lower() for kw in _NON_CHAT_KEYWORDS)
            ]
            if chat_models:
                _LIVE_MODELS_CACHE = chat_models
                _LIVE_MODELS_FETCHED_AT = now
                print(f"  🔄 Live Groq models: {chat_models}")
                return chat_models
    except Exception as e:
        print(f"  ⚠️ Live model fetch failed: {e}")
    return _LIVE_MODELS_CACHE


def _get_active_models():
    active = [m for m in MODELS_TO_TRY if m not in _BLACKLISTED_MODELS]
    if active:
        return active
    print("  ⚠️ All configured models failed — fetching live list...")
    live = _fetch_live_groq_models()
    if live:
        _BLACKLISTED_MODELS.clear()
        return live
    _BLACKLISTED_MODELS.clear()
    return MODELS_TO_TRY

# ══════════════════════════════════════════════════════
# RESPONSE CACHE — same question dobara → no API call
# TTL: 1800 sec (30 min). Server busy errors 30-40% kam.
# ══════════════════════════════════════════════════════
_CACHE = {}       # key → (answer, timestamp)
_CACHE_TTL = 1800  # seconds

def _cache_get(key):
    entry = _CACHE.get(key)
    if entry and (time.time() - entry[1]) < _CACHE_TTL:
        return entry[0]
    return None

def _cache_set(key, value):
    _CACHE[key] = (value, time.time())
    # Memory guard — 500 entries se zyada hone par purane hata do
    if len(_CACHE) > 500:
        oldest = sorted(_CACHE.items(), key=lambda x: x[1][1])[:100]
        for k, _ in oldest:
            del _CACHE[k]


# ══════════════════════════════════════════════════════
# QUERY EXPANSION — short queries + typos
# ══════════════════════════════════════════════════════
QUERY_EXPANSION = {
    "faculties": "list all faculty members professors of svims departments cs management",
    "faculty": "list all faculty members professors of svims",
    "list all faculty members of svims": "list all faculty members professors cs bioscience management ug pg svims",
    "list all faculty": "list all faculty members professors cs bioscience management ug pg svims",
    "list faculty": "list all faculty members professors cs bioscience management ug pg svims",
    "all faculty members": "list all faculty members professors cs bioscience management ug pg svims",
    "policies": "attendance policy code of conduct fee refund policy svims",
    "policy": "attendance policy rules svims",
    "admission": "admission process eligibility how to apply svims",
    "fees": "fee structure all courses bca bba bsc mba mca svims",
    "fee": "fee structure courses svims",
    "syllabus": "syllabus curriculum all courses svims",
    "courses": "all courses offered ug pg svims",
    "clubs": "clubs activities edc nss it hr marketing finance svims",
    "cells": "cells edc nss iic rdc cdc iiic svims",
    "cels": "cells edc nss iic rdc cdc iiic svims",
    "events": "events prabandhotsav srijan khelotsav nav udyami abhisanskaran confluence svims",
    "placement": "placement cell training jobs recruiters svims",
    "hostel": "hostel facilities accommodation boys girls svims",
    "library": "library books timings resources svims",
    "scholarship": "scholarships schemes eligibility svims",
    "contact": "contact phone email address svims",
    "result": "how to check exam results svims",
    "results": "how to check exam results svims",
    "timetable": "exam time table schedule main atkt svims",
    "attendance": "attendance policy 75 percent mandatory all courses svims",
    "director": "director svims dr george thomas",
    "chairman": "chairman svims leadership trust",
    "patron": "patron svims leadership trust",
    "facilities": "facilities labs library hostel sports canteen svims",
    "about": "about svims history overview accreditation naac",
    "faq": "frequently asked questions svims",
    "faqs": "frequently asked questions svims",
    "labs": "laboratories computer microbiology biotechnology chemistry physics svims",
    "sports": "sports facilities ground playground svims",
    "canteen": "canteen food svims",
    "address": "address location svims gumasta nagar indore",
    "naac": "naac accreditation grade a svims",
    "ranking": "ranking business today svims",
    "achievement": "faculty achievements student achievements awards phd research paper patent svims",
    "achievements": "faculty achievements student achievements awards phd research paper patent svims",
    "student achievements": "student achievements awards topper university rank svims",
    "teacher achievements": "faculty achievements awards research paper phd patent conference svims",
    "faculty achievements": "faculty achievements awards phd research paper patent intellectual property svims",
    "faculties achivments": "faculty achievements awards phd research paper patent intellectual property svims",
    "dress code": "dress code uniform svims",
    "iqac": "iqac quality assurance svims",
    "alumni": "alumni association svims",
    "alumini": "alumni association svims",
    "alumnii": "alumni association svims",
    # Typos
    "slyabus": "syllabus svims", "sylabus": "syllabus svims",
    "palcements": "placement cell svims", "placments": "placement svims",
    "schoalrship": "scholarship svims", "scholrship": "scholarship svims",
    "addmission": "admission process svims", "admision": "admission svims",
    "libary": "library svims", "libraray": "library svims",
    "hostle": "hostel svims",
    "faculity": "faculty members svims", "faculy": "faculty svims",
    "driector": "director svims", "dierctor": "director svims",
    "attendence": "attendance policy svims", "atendance": "attendance svims",
    "fess": "fee structure svims", "feees": "fee structure svims",
    "pg faculties": "pg management faculty list svims",
    "ug faculties": "ug management faculty list svims",
    "cs faculties": "cs bioscience faculty list svims",
    "achivments": "achievements awards svims",
    "achivment": "achievement awards svims",
    "placement officiers": "training placement officer tpo name designation svims",
    "placement officer": "training placement officer tpo name designation svims",
    "mca syllabus": "mca syllabus curriculum master computer applications svims",
    "biotechnology syllabus": "bsc biotechnology bt syllabus i year svims",
    "bioinformatics syllabus": "bsc bioinformatics bi syllabus i year svims",
    "microbiology syllabus": "bsc microbiology mb syllabus i year svims",
}


def expand_query(question):
    q_lower = question.lower().strip()
    if q_lower in QUERY_EXPANSION:
        return QUERY_EXPANSION[q_lower]
    close = get_close_matches(q_lower, list(QUERY_EXPANSION.keys()), n=1, cutoff=0.82)
    if close:
        return QUERY_EXPANSION[close[0]]
    return question


# ══════════════════════════════════════════════════════
# OUT OF SCOPE — only block CLEARLY unrelated topics
# Default = SVIMS related (safer)
# ══════════════════════════════════════════════════════
NON_SVIMS_TOPICS = [
    "prime minister", "president of india", "weather today",
    "write code", "write a program", "python code", "java code",
    "recipe", "movie review", "cricket score", "stock price",
    "who is elon musk", "who is modi", "who is ambani", "who is mukesh",
    "who is bill gates", "who is sachin", "capital of", "population of",
    "translate", "joke", "poem about", "story about",
    "what is ai", "what is machine learning", "chatgpt",
    "taj mahal", "where is taj", "pythagoras", "pythagorean",
    "explain theorem", "newton", "einstein", "who is virat",
    "who is dhoni", "bollywood", "hollywood", "cricket team",
]

# Math-only patterns — answer directly without SVIMS context
import re as _re
MATH_PATTERN = _re.compile(r'^[\d\s\+\-\*\/\(\)\=\?\.]+$')


def is_out_of_scope(question):
    q = question.lower().strip()
    if q in ["hi", "hello", "hey", "ok", "okay", "thanks", "thank you"]:
        return False
    return any(topic in q for topic in NON_SVIMS_TOPICS)


def is_pure_math(question):
    """Simple arithmetic like 2+5=? — answer directly"""
    q = question.strip()
    return bool(MATH_PATTERN.match(q)) and len(q) < 30


# ══════════════════════════════════════════════════════════════
# FULLY HARDCODED ANSWERS — zero AI involvement, always identical
# ══════════════════════════════════════════════════════════════
# In sawalon ke jawab kabhi AI se nahi banaye jaate — yeh static text
# hai jo direct return hota hai. Isse "Server busy" jaisa error kabhi
# nahi aata in queries pe, aur jawab hamesha 100% same rehta hai.
#
# PHONE NUMBERS: show_staff_phones = false (config.json) hone par
# HOD/Director ke numbers chatbot answer mein nahi dikhenge. Sirf
# official email aur faculty directory link milega.
# ══════════════════════════════════════════════════════════════

def _build_faculty_answers():
    """Faculty hardcoded answers — sirf naam, designation, email, aur directory link (no phone numbers)."""
    global FACULTY_LIST_ANSWER, CS_FACULTY_ANSWER, UG_FACULTY_ANSWER, PG_FACULTY_ANSWER

    FACULTY_LIST_ANSWER = """SVIMS Faculty — Department Overview

**Director:** Dr. George Thomas | svimi@svimi.org

**Computer & BioScience:**
HOD: Dr. Kshama Paithankar (Professor & HOD)
Full List → https://www.svimi.org/departments/faculties.php?q=faculty_cs

**Management (UG):**
HOD: Dr. Deepa Katiyal (Professor & HOD)
Full List → https://www.svimi.org/departments/faculties.php?q=faculty_UG

**Management (PG):**
HOD: Dr. Mandip Gill (Professor & HOD)
Full List → https://www.svimi.org/departments/faculties.php?q=faculty_PG

**Training & Placement:**
T&P Officer: Mr. Hemant Pathak
Asst. T&P Officer: Mr. Sourabh Upadhyay
For queries: svimi@svimi.org"""

    CS_FACULTY_ANSWER = """**Computer & BioScience Department**

HOD: Dr. Kshama Paithankar (Professor & HOD) | svimi@svimi.org

For complete faculty list with profiles and qualifications, visit:
https://www.svimi.org/departments/faculties.php?q=faculty_cs"""

    UG_FACULTY_ANSWER = """**Management (UG) Department**

HOD: Dr. Deepa Katiyal (Professor & HOD) | svimi@svimi.org

For complete faculty list with profiles and qualifications, visit:
https://www.svimi.org/departments/faculties.php?q=faculty_UG"""

    PG_FACULTY_ANSWER = """**Management (PG) Department**

HOD: Dr. Mandip Gill (Professor & HOD) | svimi@svimi.org

For complete faculty list with profiles and qualifications, visit:
https://www.svimi.org/departments/faculties.php?q=faculty_PG"""

_build_faculty_answers()





# ══ SYLLABUS ANSWERS — config.json se build hote hain ══
# ══ SCHOLARSHIP HARDCODED ANSWER ══
SCHOLARSHIP_ANSWER = f"""Scholarships Available at SVIMS

— Post Metric Scholarship (SC/ST/OBC — based on family income)
— Minority Scholarship (minority community students)
— Central Sector Scheme (80%+ marks in 10+2)
— Awas Scholarship (SC/ST students)
— PG Indira Gandhi Scholarship (Single Girl Child pursuing PG)
— AICTE PG Scholarship / GATE Fellowship
— SVIMS Meritorious Scholarship (for students with 75%+ attendance and good academic performance)

For eligibility details and application process, visit:
https://www.svimi.org/scholarship.php
Or email: svimi@svimi.org"""




ACADEMIC_CALENDAR_ANSWER = f"""Academic Calendar {ACADEMIC_CALENDAR.get('year', '2025-26')} — SVIMS

Download the full Academic Calendar PDF here:
{ACADEMIC_CALENDAR.get('link', 'https://www.svimi.org/assets/images/Academic_Calender_2025-26.pdf')}

For semester dates, exam schedules, and holidays — refer to this PDF or visit www.svimi.org/Notification.php for latest updates."""

FAQS_ANSWER = """Frequently Asked Questions (FAQs) — SVIMS

For the complete list of FAQs covering admissions, courses, fees, attendance, facilities and more, visit the official FAQ pages:

— **General FAQs:** https://www.svimi.org/FAQs.php
— **Academic FAQs:** https://www.svimi.org/academic-faqs.php

If your question is not answered there, email svimi@svimi.org or call Toll Free: 18002332601"""


def get_hardcoded_answer(question):
    """
    Faculty list aur syllabus jaise FIXED-answer queries ke liye hamesha
    same, static jawab return karta hai — AI ko bilkul call nahi kiya jaata.
    Match nahi mila toh None return karta hai (normal flow continue hoga).
    """
    q = question.lower().strip()
    q_clean = re.sub(r'[^a-z0-9 ]', ' ', q)
    q_clean = ' '.join(q_clean.split())

    # ── Faculty list queries (check specific department FIRST) ──
    if "pg faculty" in q_clean or "pg faculties" in q_clean or \
       "management pg faculty" in q_clean or "faculty list of pg" in q_clean or \
       "pg faculty list" in q_clean or "faculty of pg" in q_clean or \
       "mba faculty" in q_clean:
        return PG_FACULTY_ANSWER, "https://www.svimi.org/departments/faculties.php?q=faculty_PG"

    if "ug faculty" in q_clean or "ug faculties" in q_clean or \
       "management ug faculty" in q_clean or "faculty list of ug" in q_clean or \
       "ug faculty list" in q_clean or "faculty of ug" in q_clean or \
       "bba faculty" in q_clean:
        return UG_FACULTY_ANSWER, "https://www.svimi.org/departments/faculties.php?q=faculty_UG"

    if "cs faculty" in q_clean or "computer science faculty" in q_clean or \
       "bioscience faculty" in q_clean or "computer faculty" in q_clean or \
       "cs faculties" in q_clean or "faculty list of cs" in q_clean or \
       "faculty of cs" in q_clean or "faculty of computer" in q_clean or \
       "bca faculty" in q_clean:
        return CS_FACULTY_ANSWER, "https://www.svimi.org/departments/faculties.php?q=faculty_cs"

    faculty_all_triggers = [
        "list all faculty", "all faculty member", "faculty members of svims",
        "list faculty", "all faculties", "faculty list", "faculties list",
        "complete faculty", "show all faculty", "total faculty",
    ]
    if any(t in q_clean for t in faculty_all_triggers) or q_clean in ["faculty", "faculties", "faculty members"]:
        return FACULTY_LIST_ANSWER, "https://www.svimi.org/departments/faculties.php"

    # ── Syllabus queries ──────────────────────────────────────
    syllabus_words = ["syllabus", "sylabus", "slyabus", "slybus", "sllyabus",
                      "sllybus", "syllabuss", "curriculum", "sillabus", "sllaybus"]
    has_syllabus = any(w in q_clean for w in syllabus_words)
    if has_syllabus:
        # "all syllabus", "give me all syllabus", "all syllabus link" etc
        all_triggers = ["all syllabus", "all syla", "give me all", "give all", "sabhi syllabus",
                        "sare syllabus", "saare syllabus", "complete syllabus", "every syllabus",
                        "all course syllabus", "list syllabus", "show syllabus"]
        course_kws = {
            "bca": ["bca"], "bba": ["bba"],
            "mba": ["mba"], "mca": ["mca"],
            "msc cs": ["msc cs", "m sc cs", "msc computer", "m.sc"],
            "bsc cs": ["bsc cs", "b sc cs", "bsc computer", "computer science"],
            "biotechnology": ["biotechnology", "biotech"],
            "bioinformatics": ["bioinformatics"],
            "microbiology": ["microbiology"],
        }
        matched = [c for c, kws in course_kws.items() if any(kw in q_clean for kw in kws)]

        if any(t in q_clean for t in all_triggers) or (has_syllabus and not matched):
            # No specific course mentioned OR "all syllabus" asked → full list
            all_text = (
                "Here are all available syllabus PDFs at SVIMS:\n\n"
                "**UG Programmes:**\n"
                "— BCA I Year: https://www.svimi.org/assets/images/BCA_I_Year_Syllabus.pdf\n"
                "— BBA II Sem: https://www.svimi.org/assets/images/BBA_II_Sem_Syllabus.pdf\n"
                "— BBA (Foreign Trade) II Sem: https://www.svimi.org/assets/images/BBA_(FT)_II_Sem_Syllabus.pdf\n"
                "— BBA (Hospital Admin) II Sem: https://www.svimi.org/assets/images/BBA_(HA)_II_Sem_Syllabus.pdf\n"
                "— B.Sc. Computer Science I Year: https://www.svimi.org/assets/images/B.%20Sc._(CS)_I_Year_Syllabus.pdf\n"
                "— B.Sc. Biotechnology I Year: https://www.svimi.org/assets/images/B.%20Sc._(BT)_I_Year_Syllabus.pdf\n"
                "— B.Sc. Bioinformatics I Year: https://www.svimi.org/assets/images/B.%20Sc._(BI)_I_Year_Syllabus.pdf\n"
                "— B.Sc. Microbiology I Year: https://www.svimi.org/assets/images/B.%20Sc._(MB)_I_Year_Syllabus.pdf\n\n"
                "**PG Programmes:**\n"
                "— MBA Full Time: https://www.svimi.org/assets/images/MBA_FT_Syllabus.pdf\n"
                "— MBA Financial Administration: https://www.svimi.org/assets/images/MBA_FA_Syllabus.pdf\n"
                "— MBA Marketing Management: https://www.svimi.org/assets/images/MBA_MM_Syllabus.pdf\n"
                "— MCA: https://www.svimi.org/assets/images/MCA_Syllabus.pdf\n"
                "— M.Sc. CS: https://www.svimi.org/assets/images/M.Sc.CS_Syllabus.pdf"
            )
            return all_text, "https://www.svimi.org/under-graduate.php"

    # ── Academic Calendar ─────────────────────────────────────
    calendar_triggers = ["academic calendar", "calender", "calendar", "semester dates",
                         "academic schedule", "holiday list", "exam calendar"]
    if any(t in q_clean for t in calendar_triggers):
        return ACADEMIC_CALENDAR_ANSWER, ACADEMIC_CALENDAR.get(
            "link", "https://www.svimi.org/assets/images/Academic_Calender_2025-26.pdf")

    # ── FAQs ─────────────────────────────────────────────────
    faq_triggers = ["faq", "faqs", "frequently asked", "show me all faq",
                    "all faqs", "common questions", "academic faq"]
    if any(t in q_clean for t in faq_triggers):
        return FAQS_ANSWER, "https://www.svimi.org/FAQs.php"

    # ── Anti-Ragging ──────────────────────────────────────────
    ragging_triggers = ["anti ragging", "anti-ragging", "ragging", "ragging committee",
                        "anti ragging committee"]
    if any(t in q_clean for t in ragging_triggers):
        ragging_answer = (
            "**Anti-Ragging Committee — SVIMS**\n\n"
            "SVIMS has constituted an Anti-Ragging Committee as per UGC Anti-Ragging Regulations, 2009.\n\n"
            "**Key Officials:**\n"
            "— Director: Dr. George Thomas\n"
            "— Nodal Officer: Dr. Sandeep Malu\n"
            "— Monitoring Cell: Dr. Kshama Paithankar, Dr. Deepa Katiyal, Dr. Mandip Gill\n\n"
            "**Committee includes representatives from:**\n"
            "— Institute Administration, Police (ACP + Station), Media, Parents, Students, Hostel Wardens, Canteen\n\n"
            "**If you experience ragging:** Contact any committee member, faculty, hostel warden, or email svimi@svimi.org immediately.\n\n"
            "Full committee details: https://www.svimi.org/assets/images/Anti_Ragging_Committee.pdf"
        )
        return ragging_answer, "https://www.svimi.org/assets/images/Anti_Ragging_Committee.pdf"

    # ── Scholarship queries ──────────────────────────────────
    scholarship_triggers = [
        "scholarship", "schoalrship", "scholrship", "merit scholarship",
        "meritorious", "svims scholarship", "fee waiver", "financial aid",
        "post metric", "minority scholarship", "central sector",
    ]
    if any(t in q_clean for t in scholarship_triggers):
        return SCHOLARSHIP_ANSWER, "https://www.svimi.org/scholarship.php"

    return None


# ══════════════════════════════════════════════════════
# VERIFIED LINKS (from PDF + official site — 75+ real URLs)
# ══════════════════════════════════════════════════════
TOPIC_LINKS = [
    (["admission", "apply", "eligibility", "counselling", "addmission", "admision"],
     "https://www.svimi.org/admission-process.php", "Admission Process"),
    (["pg admission", "mba admission", "mca admission"],
     "https://www.svimi.org/admission-process.php#pg_admission_process", "PG Admission"),
    (["fee payment", "pay fee", "online payment", "pay online"],
     "https://accsoft.svimi.org/Accsoft_SVG/AdmissionRegPayment.aspx", "Online Fee Payment"),
    (["fee refund", "refund policy", "cancel admission"],
     "https://www.svimi.org/assets/images/Fee_Refund_Policy.pdf", "Fee Refund Policy"),
    (["fee", "fees", "fess", "feees", "tuition", "cost"],
     "https://www.svimi.org/scholarship.php", "Fee & Scholarship Info"),
    (["scholarship", "schoalrship", "scholrship", "merit"],
     "https://www.svimi.org/scholarship.php", "Scholarships"),
    (["placement officer", "placement officiers", "tpo", "training placement officer"],
     "https://www.svimi.org/placement/about-placement.php", "Placement Cell - T&P Team"),
    (["highest package", "average package", "placement rate", "placement percentage",
      "placement 2025", "placement 2024", "placement stats", "placement record",
      "kitne students place", "placement details", "package kitna", "salary package",
      "prominent", "placed students"],
     "https://www.svimi.org/placement/prominent-selections.php", "Placement Details & Glimpses"),
    (["placement cell", "placement", "palcements", "placments", "job", "recruiter"],
     "https://www.svimi.org/placement/about-placement.php", "Placement Cell"),
    (["library", "books", "libary", "libraray", "journal"],
     "https://www.svimi.org/infrastructure/library.php", "Library"),
    (["computer lab", "lab", "laboratory", "labs"],
     "https://www.svimi.org/infrastructure/computer.php", "Computer Lab"),
    (["bio lab", "biotech lab", "microbiology lab", "mi-bt"],
     "https://www.svimi.org/infrastructure/MI-BT.php", "Bio Lab"),
    (["auditorium", "abhay prashal"],
     "https://www.svimi.org/infrastructure/auditorium.php", "Auditorium"),
    (["about bca", "bca program", "bca course"],
     "https://www.svimi.org/under-graduate.php#aboutBCASec", "About BCA"),
    (["about bba", "bba program", "bba course"],
     "https://www.svimi.org/under-graduate.php#aboutBBASec", "About BBA"),
    (["about bsc", "b.sc program", "bsc course", "b.sc. computer science",
      "bsc computer science", "b.sc computer science", "career after b.sc",
      "career opportunities after b.sc", "career opportunities for b.sc"],
     "https://www.svimi.org/under-graduate.php#aboutBscSec", "About B.Sc"),
    (["about mba", "mba program", "mba course"],
     "https://www.svimi.org/post-graduate.php#aboutMBASec", "About MBA"),
    (["about mca", "mca program", "mca course"],
     "https://www.svimi.org/post-graduate.php", "About MCA"),
    (["pg faculty", "mba faculty", "faculity", "faculy", "pg faculties"],
     "https://www.svimi.org/departments/faculties.php?q=faculty_PG", "PG Faculty"),
    (["ug faculty", "bba faculty", "ug faculties"],
     "https://www.svimi.org/departments/faculties.php?q=faculty_UG", "UG Faculty"),
    (["cs faculty", "computer faculty", "bioscience faculty", "cs faculties", "faculty", "faculties"],
     "https://www.svimi.org/departments/faculties.php?q=faculty_cs", "CS Faculty"),
    (["faculty achievement", "faculty achievements", "research paper", "patent", "phd award"],
     ACHIEVEMENT_CFG.get("faculty",
         "https://www.svimi.org/assets/images/achievements/Faculty_Other_Achievement_2024-25.pdf"),
     f"Faculty Achievements {ACHIEVEMENT_CFG.get('faculty_year','2024-25')}"),
    (["student achievement", "topper", "university rank"],
     ACHIEVEMENT_CFG.get("student",
         "https://www.svimi.org/assets/images/achievements/Student_Achievements_2024-25.pdf"),
     f"Student Achievements {ACHIEVEMENT_CFG.get('student_year','2024-25')}"),
    (["edc", "entrepreneurship", "nav udyami", "incubation"],
     "https://www.svimi.org/cells/edc.php", "EDC Cell"),
    (["nss"], "https://www.svimi.org/cells/nss.php", "NSS Cell"),
    (["iic", "innovation"], "https://www.svimi.org/cells/iic.php", "IIC"),
    (["rdc", "research development"], "https://www.svimi.org/cells/rdc.php", "RDC"),
    (["cdc", "case development"], "https://www.svimi.org/cells/cdc.php", "CDC"),
    (["iiic", "industry institute"], "https://www.svimi.org/cells/iiic.php", "IIIC"),
    (["iqac", "quality assurance"], "https://www.svimi.org/iqac.php", "IQAC"),
    (["nirf", "ranking"], "https://www.svimi.org/ranking-nirf.php", "NIRF Ranking"),
    (["naac", "accreditation"], "https://www.svimi.org/recongnition-description.php", "Recognition & Accreditation"),
    (["academic faq"], "https://www.svimi.org/FAQs.php", "FAQs"),
    (["faq", "faqs", "frequently asked"], "https://www.svimi.org/FAQs.php", "FAQs"),
    (["erp", "student portal", "login"],
     "https://accsoft.svimi.org/accsoft_SVG/studentlogin.aspx", "Student ERP"),
    (["atkt"], "https://www.svimi.org/Time-Table-ATKT.php", "ATKT Time Table"),
    (["timetable", "time table", "exam schedule"],
     "https://www.svimi.org/Time-Table-Main.php", "Exam Time Table"),
    (["result", "marks", "results"], "https://www.svimi.org/Results.php", "Results"),
    (["notification", "notice", "announcement"],
     "https://www.svimi.org/Notification.php", "Notifications"),
    (["anti ragging", "ragging"],
     "https://www.svimi.org/assets/images/Anti_Ragging_Committee.pdf", "Anti-Ragging Committee"),
    (["contact", "phone", "email", "address"],
     "https://www.svimi.org/contact-us.php", "Contact Us"),
    (["governing body", "trust", "board"],
     "https://www.svimi.org/governing-body.php", "Governing Body"),
    (["chairman", "patron", "director", "leadership", "driector", "dierctor"],
     "https://www.svimi.org/leadership.php?q=director", "Leadership"),
    (["alumni", "alumini", "alumnii"], "https://www.svimi.org/alumni-speak.php", "Alumni Speaks"),
    (["alumni association", "alumni meet", "confluence"],
     "https://www.svimi.org/alumni_association.php", "Alumni Association"),
    (["journal", "management effigy"], "https://www.managementeffigy.in/archives.php", "Management Effigy Journal"),
    (["vision", "mission"], "https://www.svimi.org/vision.php", "Vision & Mission"),
    (["calendar", "academic calendar"],
     ACADEMIC_CALENDAR.get("link",
         "https://www.svimi.org/assets/images/Academic_Calender_2025-26.pdf"),
     f"Academic Calendar {ACADEMIC_CALENDAR.get('year','2025-26')}"),
    (["virtual tour", "campus tour", "360"],
     "https://www.svimi.org/", "Virtual Campus Tour"),
    (["about svims", "history of svims", "svims history"],
     "https://www.svimi.org/about-institute-description.php", "About SVIMS"),
    (["hostel", "hostle"], "https://www.svimi.org/infrastructure/hostel.php", "Hostel"),
    (["canteen"], "https://www.svimi.org/infrastructure/canteen.php", "Canteen"),
    (["sports"], "https://www.svimi.org/infrastructure/sports.php", "Sports"),
    (["it club"], "https://www.svimi.org/activity-clubs/it-club.php", "IT Club"),
    (["finance club"], "https://www.svimi.org/activity-clubs/finance-club.php", "Finance Club"),
    (["hr club"], "https://www.svimi.org/activity-clubs/hr-club.php", "HR Club"),
    (["marketing club"], "https://www.svimi.org/activity-clubs/marketing-club.php", "Marketing Club"),
    (["literary club"], "https://www.svimi.org/activity-clubs/literary-club.php", "Literary Club"),
    (["science club"], "https://www.svimi.org/activity-clubs/science-club.php", "Science Club"),
    (["photography club"], "https://www.svimi.org/activity-clubs/photography-club.php", "Photography Club"),
    (["what clubs", "clubs available", "clubs at svims", "list of clubs", "all clubs", "club"],
     "https://www.svimi.org/activity-clubs/it-club.php", "Activity Clubs"),
    (["events", "major events", "event calendar", "prabandhotsav", "srijan", "khelotsav",
      "nav udyami", "abhisanskaran", "confluence"],
     "https://www.svimi.org/event-gallery.php", "Events"),
    (["faculites", "faculty overview", "all faculty"],
     "https://www.svimi.org/departments/faculties.php?q=faculty_cs", "Faculty Directory"),
    (["slybus", "sylabus", "syllabus", "curriculum"],
     "https://www.svimi.org/under-graduate.php", "Syllabus Info"),
]


def get_links(question, context=""):
    """
    Sirf EK relevant link return karo.
    Pehle question ke keyword se TOPIC_LINKS mein best match dhundo.
    Agar match ka URL None hai (e.g. MCA syllabus), koi link mat do.
    Agar koi match nahi mila, tabhi context se URL nikalo (fallback).
    """
    import re

    q = question.lower()

    best_match = None
    best_score = 0
    for keywords, url, label in TOPIC_LINKS:
        for kw in keywords:
            if kw in q and len(kw) > best_score:
                best_score = len(kw)
                best_match = (url, label)

    if best_match:
        url, label = best_match
        if url is None:
            # Explicitly "no link exists" — don't show any link
            return []
        return [(url, label)]

    if context:
        urls = re.findall(r'https?://[^\s\)\]\>",]+', context)
        specific_urls = [u for u in urls if u.rstrip('/') != "https://www.svimi.org"]
        target = specific_urls[0] if specific_urls else (urls[0] if urls else None)
        if target:
            url = target.rstrip('.,;)')
            return [(url, "More Info")]

    return []


def create_chatbot(vector_store, api_key=None, pdf_path=None):
    """
    pdf_path: agar diya jaaye, toh PDF se direct Q&A matcher bhi banta hai —
    isse exact PDF questions ka jawab 100% accurate (hallucination-free) milta hai.
    """
    qa_matcher = None
    if pdf_path is None:
        # college_docs/ folder mein PDF dhundo automatically
        docs_folder = "college_docs"
        if os.path.isdir(docs_folder):
            pdfs = [f for f in os.listdir(docs_folder) if f.lower().endswith(".pdf")]
            if pdfs:
                pdf_path = os.path.join(docs_folder, pdfs[0])

    if pdf_path and os.path.exists(pdf_path):
        try:
            from svims_qa_loader import SVIMSQAMatcher
            qa_matcher = SVIMSQAMatcher(pdf_path, cache_path="svims_qa_cache.pkl")
        except Exception as e:
            print(f"  ⚠️ Q&A direct matcher could not be built: {e}")
            qa_matcher = None

    return {
        "client": groq_client,
        "retriever": vector_store.as_retriever(search_kwargs={"k": 8}),
        "qa_matcher": qa_matcher,
    }


def _call_groq(client, messages):
    """
    client param backward-compat ke liye rakha hai (ignore hota hai) —
    ab yeh function khud _groq_clients list mein se key rotate karta hai:
      1. Round-robin: har naya request agli key try karta hai (load balance)
      2. Fallback: agar current key rate-limited/invalid ho, to next key
         automatically try hoti hai — user ko error nahi dikhta.
    """
    last_error = None
    num_keys = len(_groq_clients)

    for key_attempt in range(num_keys):
        active_client = _get_client()

        for model in _get_active_models():
            for attempt in range(3):
                try:
                    response = active_client.chat.completions.create(
                        model=model, messages=messages,
                        max_tokens=600, temperature=0.0,
                    )
                    return response.choices[0].message.content
                except Exception as e:
                    last_error = e
                    err = str(e).lower()
                    if any(x in err for x in ["invalid_api_key", "401"]):
                        print("  \u274c This key invalid — trying next key...")
                        break  # is key ko chhodo, agli key try karo
                    if any(x in err for x in ["model_not_found", "does not exist",
                                               "model not found", "deprecated"]):
                        print(f"  \u274c '{model}' expired/not found — blacklisting, switching...")
                        _BLACKLISTED_MODELS.add(model)
                        break
                    if "413" in err or "request too large" in err or "tokens_per_minute" in err:
                        break
                    if "429" in err or "rate_limit" in err:
                        if attempt < 2:
                            time.sleep(2 ** attempt)
                            continue
                        print("  \u23f3 Key rate-limited — trying next key...")
                        break
                    break
        # is key se sab models fail ho gaye — agli key try karo (agar hai)
        if key_attempt < num_keys - 1:
            continue

    # Sab keys/models fail — live API se fresh models try karo (pehli key se)
    for model in (_fetch_live_groq_models() or []):
        if model in MODELS_TO_TRY:
            continue
        for gclient in _groq_clients:
            try:
                response = gclient.chat.completions.create(
                    model=model, messages=messages,
                    max_tokens=600, temperature=0.0,
                )
                print(f"  \u2705 Live fallback '{model}' worked!")
                return response.choices[0].message.content
            except Exception as e:
                last_error = e
    raise last_error if last_error else RuntimeError("No working Groq model found")


def get_answer(chain, question, external_history=None):
    try:
        client = chain["client"]
        retriever = chain["retriever"]
        qa_matcher = chain.get("qa_matcher")

        q_clean = question.lower().strip()
        if q_clean in ["hi", "hello", "hey", "hii", "helo"]:
            return ("👋 Hello! I'm SVIMS CampusBot — your official guide for "
                    "Shri Vaishnav Institute of Management & Science, Indore. "
                    "Ask me about courses, fees, admissions, faculty, placements, "
                    "hostel, or any other campus information!")

        if is_out_of_scope(question):
            return ("I'm here to help with information about SVIMS Indore only. "
                    "Please ask about courses, fees, admissions, faculty, "
                    "placements, or facilities.\n\n"
                    "📧 svimi@svimi.org | 📞 0731-2789925 | 🆓 18002332601")

        # ═══════════════════════════════════════════════════════
        # SEMESTER COUNT — pure logic, no PDF needed
        # ═══════════════════════════════════════════════════════
        semester_map = {
            "bca": ("BCA is a 3-year programme with 6 semesters (2 semesters per year).\n"
                    "NEP-based 4-year Honours option has 8 semesters.",
                    "https://www.svimi.org/under-graduate.php#aboutBCASec"),
            "bba": ("BBA is a 3-year programme with 6 semesters (2 semesters per year).\n"
                    "NEP-based 4-year Honours option has 8 semesters.",
                    "https://www.svimi.org/under-graduate.php#aboutBBASec"),
            "b.sc": ("B.Sc. is a 3-year programme with 6 semesters (2 semesters per year).\n"
                     "NEP-based 4-year Honours option has 8 semesters.",
                     "https://www.svimi.org/under-graduate.php#aboutBscSec"),
            "bsc": ("B.Sc. is a 3-year programme with 6 semesters (2 semesters per year).\n"
                    "NEP-based 4-year Honours option has 8 semesters.",
                    "https://www.svimi.org/under-graduate.php#aboutBscSec"),
            "mba": ("MBA is a 2-year programme with 4 semesters.",
                    "https://www.svimi.org/post-graduate.php#aboutMBASec"),
            "mca": ("MCA is a 2-year programme with 4 semesters.",
                    "https://www.svimi.org/post-graduate.php"),
            "m.sc": ("M.Sc. CS is a 2-year programme with 4 semesters.",
                     "https://www.svimi.org/post-graduate.php"),
            "msc": ("M.Sc. CS is a 2-year programme with 4 semesters.",
                    "https://www.svimi.org/post-graduate.php"),
        }
        if any(w in q_clean for w in ["semester", "semesters", "sem", "semster"]):
            for course, (ans, link) in semester_map.items():
                if course in q_clean:
                    return f"{ans}\n\n🔗 **More Info:** {link}"
            if any(w in q_clean for w in ["each course", "all course", "total semester", "kitne semester"]):
                return ("Semester count at SVIMS:\n"
                        "— BCA: 6 semesters (3 years) | 8 with 4-year Honours (NEP)\n"
                        "— BBA: 6 semesters (3 years) | 8 with 4-year Honours (NEP)\n"
                        "— B.Sc.: 6 semesters (3 years) | 8 with 4-year Honours (NEP)\n"
                        "— MBA: 4 semesters (2 years)\n"
                        "— MCA: 4 semesters (2 years)\n"
                        "— M.Sc. CS: 4 semesters (2 years)\n\n"
                        "🔗 **More Info:** https://www.svimi.org/under-graduate.php")

        # ═══════════════════════════════════════════════════════
        # PRIORITY 0 — FULLY HARDCODED ANSWERS (faculty list, syllabus, scholarship)
        # ═══════════════════════════════════════════════════════
        hardcoded = get_hardcoded_answer(question)
        if hardcoded:
            answer, link = hardcoded
            if link:
                answer += f"\n\n🔗 **More Info:** {link}"
            return answer

        # ═══════════════════════════════════════════════════════
        # RESPONSE CACHE — same question (case-insensitive, trimmed) dobara
        # puchha gaya to cached answer return karo (no API call).
        # TTL: 30 min. History-based follow-up questions skip karo (unhe cache nahi karo).
        # ═══════════════════════════════════════════════════════
        has_history = bool(external_history)
        cache_key = q_clean if not has_history else None
        if cache_key:
            cached = _cache_get(cache_key)
            if cached:
                return cached

        # ═══════════════════════════════════════════════════════
        # PRIORITY 1 — DIRECT PDF MATCH (most reliable, zero hallucination)
        # Agar user ka question PDF ke kisi exact Q&A se closely match
        # karta hai, toh PDF ka EXACT answer + EXACT link directly do.
        # AI ko bilkul call nahi kiya jaata — content seedha PDF se aata hai.
        # ═══════════════════════════════════════════════════════
        if qa_matcher:
            direct = qa_matcher.get_direct_answer(question)
            if direct:
                # PDF answer clean karo — raw Q:/A:/Source:/More Information: lines
                # hata do taaki chatbot response mein raw PDF formatting na aaye
                raw_ans = direct["answer"]
                clean_lines = []
                for line in raw_ans.split("\n"):
                    ls = line.strip()
                    if not ls:
                        continue
                    # Skip: Q: lines, Source:, More Information:, Link: lines
                    if (ls.startswith("Q:") or ls.startswith("Source:") or
                            ls.startswith("More Information") or ls.startswith("Link:")):
                        continue
                    # "A: " prefix hata do agar ho
                    if ls.startswith("A:"):
                        ls = ls[2:].strip()
                    clean_lines.append(ls)
                answer = "\n".join(clean_lines).strip() or raw_ans

                pdf_link = direct["link"]
                topic_match = get_links(question, "")
                final_link = pdf_link
                if topic_match and topic_match[0][0]:
                    final_link = topic_match[0][0]
                if final_link and final_link != "https://www.svimi.org/":
                    answer += f"\n\n🔗 **More Info:** {final_link}"
                return answer

        expanded = expand_query(question)

        docs1 = retriever.invoke(expanded.lower())
        docs2 = retriever.invoke(question.lower())
        seen_keys = set()
        all_docs = []
        for d in docs1 + docs2:
            key = d.page_content[:80]
            if key not in seen_keys:
                seen_keys.add(key)
                all_docs.append(d)
        context = "\n\n---\n\n".join([d.page_content for d in all_docs[:6]])

        # ═══════════════════════════════════════════════════════
        # PRIORITY 2 — If no single direct match, but qa_matcher exists,
        # pull the most relevant PDF Q&A pairs as STRONGER context
        # (these are more reliable than generic FAISS chunks since they
        # preserve the exact Q&A + Link structure from the PDF).
        # ═══════════════════════════════════════════════════════
        if qa_matcher:
            qa_context, _ = qa_matcher.get_relevant_context(question, top_k=6)
            if qa_context:
                context = qa_context + "\n\n---\n\n" + context

        system_prompt = f"""You are CampusBot — official AI assistant for SVIMS Indore (Shri Vaishnav Institute of Management & Science).

══════════════════════════════════════
LANGUAGE: Always reply in English only. Understand Hindi/Hinglish but reply in English.

FORMATTING RULES:
- NEVER use markdown tables (no | column | format |). Use clean lines instead.
- For lists, use simple dashes (—) or bullet points, not numbered lists.
- Keep answers short and clean — no unnecessary padding or repetition.
- For faculty: mention only HOD name + email. For full list, give the link.
- Example of GOOD format:
  HOD: Dr. Kshama Paithankar | svimi@svimi.org
  Full list: https://www.svimi.org/departments/faculties.php?q=faculty_cs
- Example of BAD format (avoid):
  | Name | Phone | Designation |
  |------|-------|-------------|
══════════════════════════════════════

══════════════════════════════════════
STRICT RULES — NO EXCEPTIONS
══════════════════════════════════════
1. Answer using ONLY the CONTEXT below and the KNOWN FACTS section.
2. CRITICAL — If a topic is NOT clearly and explicitly present in CONTEXT or
   KNOWN FACTS, say: "I don't have this specific information. Please visit
   www.svimi.org or contact svimi@svimi.org | Toll Free: 18002332601"
   Do NOT guess. Do NOT build a plausible-sounding structure from general
   knowledge of what such things "usually" look like.
2a. CRITICAL — CELL/COMMITTEE MEMBERSHIP: Never invent who manages, heads,
    coordinates, or is a member of any cell or committee (EDC, NSS, IIC, RDC,
    IIIC, CDC, etc.) unless their EXACT name and role is explicitly stated in
    CONTEXT. Do NOT assume the T&P team runs the EDC cell, or that a Dept HOD
    is automatically an "Advisor" to a cell. Each cell may have its own
    separate committee with different people — never reuse names from one
    cell/department and assign them roles in a different cell without
    explicit evidence in CONTEXT. If exact committee members are not in
    CONTEXT, say "I don't have the exact list of committee members for this
    cell. Please visit www.svimi.org or contact svimi@svimi.org."
3. NEVER repeat the same name for multiple different people/roles.
4. NEVER invent: phone extensions, emails, fake URLs, fake event names,
   fake statistics, fake committee members, fake office bearers.
4a. CRITICAL — PHONE NUMBERS: Each person has at most ONE phone number listed
    in KNOWN FACTS. If a person's phone number is NOT explicitly given in
    KNOWN FACTS or CONTEXT, do NOT attach any other person's number to them.
    Say "contact via svimi@svimi.org" instead. NEVER reuse the Admin Officer's
    number (9301527178) for T&P Officer, faculty, or anyone else — that
    number belongs ONLY to the Administrative Officer.
4b. NEVER invent specific FACTUAL numbers: placement percentage, salary
    packages, company-wise placement percentages, batch years, student
    counts, or any SVIMS-specific statistic not VERBATIM present in CONTEXT.
    This includes "estimated", "approximate", or "anumaniya" (अनुमानित)
    numbers — giving a number with a disclaimer like "this is an estimate"
    is STILL forbidden and STILL hallucination. If exact placement
    percentage/data is not in CONTEXT, say EXACTLY: "I don't have the exact
    placement details. For verified placement data and latest glimpses,
    please visit: https://www.svimi.org/placement/prominent-selections.php"
    Do NOT soften this into a guessed number under any framing.
    EXCEPTION — this rule does NOT apply to simple logic/math questions that
    don't require any SVIMS-specific fact, e.g. "if a course is 4 years,
    how many semesters is that?" (answer: 8, using standard 2 semesters/year
    — this is basic arithmetic, not a fact lookup, so answer it normally).
    The restriction is only on SVIMS-specific data points (placement %,
    fees amounts, student counts, dates) that we don't actually have.
4b2. NEVER rank, compare, or recommend one course as "better" than another
    for placement, career prospects, or any other reason UNLESS CONTEXT
    explicitly states such a comparison. Do NOT say things like "B.Sc. CS
    has stronger placement results than BCA" or "X is more popular" unless
    this exact comparison is in CONTEXT. If asked "which course is best for
    placement", say: "I don't have comparative placement data between
    courses. Please visit the Prominent Selections page on www.svimi.org or
    contact the Placement Cell for guidance." All UG/PG courses share the
    same recruiter list (TCS, Deloitte, Wipro, etc.) — do not imply one
    course has better outcomes than another.
4c. Do NOT invent generic clubs that sound plausible unless explicitly named
    in CONTEXT. SVIMS's real clubs are listed in KNOWN FACTS — use ONLY those.
5. The ONLY official email is svimi@svimi.org (or admission@svimi.org for admissions).
6. The ONLY official phone numbers are listed in KNOWN FACTS — never invent extensions
   or reassign one person's number to another person.
7. Do NOT add URLs or "Source:" labels in answer text — the system adds ONE
   link separately after your answer. Just give the factual answer in prose.
   NEVER write the literal word "Source" as a placeholder (e.g. never write
   "Source: Source" or "🔗 Source:" with nothing useful after it). If you are
   tempted to cite a source, simply omit it — the system handles all links.
8. Attendance is ALWAYS 75% for ALL courses.
9. SVIMS has ONLY ONE campus in Gumasta Nagar, Indore. Never mention Khandwa Road.
10. When unsure whether something is real or plausible-sounding, ALWAYS choose
    to say "I don't have this information" rather than answer with invented details.
11. For syllabus PDF links: ONLY mention links that are explicitly present in
    CONTEXT. MCA does NOT have a direct syllabus PDF link in our data — if asked,
    say "I don't have a direct syllabus PDF link for MCA. Please contact
    svimi@svimi.org or visit www.svimi.org/post-graduate.php"
12. CRITICAL — NEVER invent individual named examples (student names, specific
    years, specific competitions, specific universities like "IIM Ahmedabad",
    specific startup names, specific awards with names attached) UNLESS that
    exact name/detail is explicitly present in CONTEXT. This applies even when
    using a placeholder like "[Name]" — using a placeholder to invent a fake
    structured example is STILL hallucination and is forbidden. If CONTEXT only
    has a GENERAL statement (e.g. "students have won awards"), give ONLY that
    general statement and point to the relevant PDF/webpage — do NOT elaborate
    with invented specifics to make the answer sound more complete.
13. CRITICAL — NEVER invent specific numbers/timings/schedules that are not
    explicitly in CONTEXT or KNOWN FACTS. Examples of forbidden invention:
    college class timings (e.g. "9 AM to 4 PM" — we do NOT have this data),
    labeling a general contact number as "Reception" when no such label
    exists in our data, number of buses, holiday schedules, semester counts.
    If asked for any specific number/timing/schedule not explicitly given
    below, say "I don't have this specific information. Please visit
    www.svimi.org or contact svimi@svimi.org | Toll Free: 18002332601" —
    do NOT guess a "reasonable-sounding" answer.

══════════════════════════════════════
KNOWN FACTS — ALWAYS USE THESE EXACTLY
══════════════════════════════════════

--- BASIC INFO ---
Full Name: Shri Vaishnav Institute of Management & Science (SVIMS / SVIMI)
Established: 1987 | Autonomous Institute | Campus: 7 acres, Central Indore
Address: Scheme No. 71, Gumasta Nagar, Indore - 452009, Madhya Pradesh, India
NAAC: A Grade — 3 consecutive cycles (2012, 2017, 2024)
Approved: AICTE, New Delhi | Affiliated: DAVV Indore (UG/PG/PhD) + RGPV Bhopal (MBA)
ISO 9001:2015 Certified | Ranking: Business Today 2024 — 266 (Management category)

--- CONTACTS (ONLY THESE ARE REAL — each number belongs to exactly ONE person/purpose) ---
Main Email: svimi@svimi.org
Admission Email: admission@svimi.org
Phone: +91-731-2789925, +91-731-2780011, +91-731-2382962 (Alternate)
Toll Free: 18002332601
Admission UG: 9329912587, 9630451445 | Admission MBA: 9329912582
WhatsApp: +91-9329912587
Student Welfare: 7312580137 | Exam Controller: 7312518030 | Enquiry: 7312580157
PRIVATE (never share in answers): Administrative Officer (internal only): 9301527178
NEVER share Director, HOD, or any faculty phone numbers. These are not published.
NOTE: Exam Controller (7312518030) has NO published email address — there is
NO examcontroller@svimi.org. For exam queries direct to svimi@svimi.org or
the phone number only. Do NOT invent department-specific email addresses.
NOTE: T&P Officer Mr. Hemant Pathak and Assistant T&P Mr. Sourabh Upadhyay do
NOT have published phone numbers in our data — direct queries about them to
svimi@svimi.org, do NOT attach the Admin Officer's number (9301527178) to them.
NOTE: There is NO healthcentre@svimi.org, sports@svimi.org, hostel@svimi.org,
placement@svimi.org — these emails DO NOT EXIST. Use only svimi@svimi.org.

--- GOVERNING BODY (exact names — verified from PDF) ---
Chairman: Shri Vishnu Pasari (also Chairman of Shri Vaishnav Institute of Management Shikshan Samiti)
Member Secretary: Dr. George Thomas (Director, SVIMS)
Vice Chairman (of Shikshan Samiti): Shri Rajkumar Bhatia
Secretary (of Shikshan Samiti): Shri Manish Baheti
Joint Secretary (of Shikshan Samiti): Shri Shashank Gupta
Treasurer (of Shikshan Samiti): Shri Puneet Soni
Special Invitees:
  - Shri Purushottamdas Pasari (Chairman, Shri Vaishnav Group of Trusts, Indore)
  - Shri Devendrakumar Muchhal (Secretary, Shri Vaishnav Sahayak Kapda Market Committee)
  - Shri Girdhargopal Nagar (Secretary, Shri Vaishnav Shaikshanik Avam Parmarthik Nyas)
Parent Trust: Shri Vaishnav Shaikshanik Avam Parmarthik Nyas, Indore (established 1987)

--- LEADERSHIP ---
Director: Dr. George Thomas (contact via svimi@svimi.org)
HOD CS & BioScience: Dr. Kshama Paithankar (contact via svimi@svimi.org)
HOD Management UG: Dr. Deepa Katiyal (contact via svimi@svimi.org)
HOD Management PG: Dr. Mandip Gill (contact via svimi@svimi.org)
Chairman and Patron details: see Leadership page on website.

--- FACULTY ---
IMPORTANT: The complete faculty list IS available below. If asked "list all
faculty members", "all faculty", or similar, ALWAYS answer using this list.
For ANY faculty question — give only HOD names and link. NEVER list all
individual teacher names in the answer text.
Director: Dr. George Thomas | svimi@svimi.org
HOD CS & BioScience: Dr. Kshama Paithankar
  Full CS list: https://www.svimi.org/departments/faculties.php?q=faculty_cs
HOD Management UG: Dr. Deepa Katiyal
  Full UG list: https://www.svimi.org/departments/faculties.php?q=faculty_UG
HOD Management PG: Dr. Mandip Gill
  Full PG list: https://www.svimi.org/departments/faculties.php?q=faculty_PG
T&P Team: Mr. Hemant Pathak (T&P Officer), Mr. Sourabh Upadhyay (Asst T&P)
IMPORTANT: The URL for faculty is ONLY one of these three — never use
"svimi.org/faculties.php" (does not exist). Always use the exact URLs above.

--- COURSES ---
UG: BCA, BBA (General/Foreign Trade/Hospital Admin), B.Sc. (CS/Biotechnology/Microbiology/Bioinformatics)
PG: MBA (Dual Specialization/Financial Administration/Marketing Management), MCA, M.Sc. Computer Science
Research: PhD in Management (DAVV recognized)
NOT OFFERED: B.Com, B.A., B.Tech, BE, B.Ed, Law, Medical

--- EXACT FEES ---
BBA (all variants): Rs. 80,000/year | BCA: Rs. 60,000/year | B.Sc. (all): Rs. 40,000/year
MBA Dual Specialization: Rs. 43,000/semester | MBA FA: Rs. 40,500/semester | MBA MM: Rs. 30,000/semester
MCA: Rs. 27,500/semester | M.Sc. CS: Rs. 40,000/year
Caution Money (BBA/BCA/MBA/MCA/MSc): Rs. 1,500 refundable | B.Sc.: Rs. 2,000 refundable
Installments: 1st - July 1-15 | 2nd - January 1-15

--- ATTENDANCE ---
Minimum 75% in EACH subject — ALL courses. Required for exams, placements, scholarship.
Medical leave: max 10% weightage, certificate within 7 days of rejoining.

--- LIBRARY ---
Books: 52,785+ | E-Books: 17,000+ | Online Journals: 10,000+
Print Journals: 88 | CDs: 2,907 | Video Cassettes: 41 | Encyclopedias: 18
Timings: 9:00 AM to 9:00 PM (Working Days)
UG: 3 books for 15 days | PG: 4 books for 15 days | Late fine: Rs. 2/day/book
Special Collections: Indian Philosophy, Value Management, Harvard Business Publishing,
ICFAI Publishing, IGNOU Study Materials, Project Reports, Case Studies, Biographies
Databases: IEEE Xplore, Emerald Insight, National Digital Library, EBSCO

--- HOSTEL ---
Separate hostels for boys and girls. Facilities: room sharing, lockable almirah,
attached toilet, study table, 24hr water, hot water (solar), common dining hall
with mess, internet, indoor games, security guards, CCTV, warden supervision.
Girls hostel has additional lift facility and sanitary napkin vending machine.
For booking/charges: contact svimi@svimi.org

--- LABS ---
Computer Laboratories (7 labs), Microbiology & Biotechnology Lab, Chemistry Lab,
Physics Lab, Language Lab, Business Analytics Lab — all support practical sessions,
research, and project work.

--- SPORTS ---
Outdoor playgrounds and indoor courts for various sports — part of curriculum to
promote fitness and competitive spirit. For details contact svimi@svimi.org

--- CANTEEN ---
On-campus canteen provides quality food at student-friendly prices — popular
gathering spot for students and staff.

--- PLACEMENT ---
T&P Officer: Mr. Hemant Pathak | Asst: Mr. Sourabh Upadhyay (no individual phone
numbers published — use svimi@svimi.org for queries)
Recruiters: TCS, Deloitte, Wipro, ICICI Bank, Cognizant, Tech Mahindra, Infosys,
Capgemini, HCL, Accenture | PEP Model: Project Based + Value Based + Personality Development Training
For exact placement numbers/statistics, direct to Prominent Selections page.

--- DRESS CODE ---
MBA: Unicode Shirting (Real B-4970), Trouser (P-Power Shade 017), Blazer
UG: Sarafarosh Pc Shirting, Siyaram Unicode Black Trouser, Blazer
All: Formal black leather shoes/bellies, plain white socks
Bioscience: White Lab Apron compulsory

--- ONLINE PORTALS ---
Online Fee Payment: accsoft.svimi.org/Accsoft_SVG/AdmissionRegPayment.aspx
  (students log in to the ERP portal and pay fees through this payment gateway)
Student ERP Login: accsoft.svimi.org/accsoft_SVG/studentlogin.aspx
Results: www.svimi.org/Results.php
Notifications: www.svimi.org/Notification.php
IMPORTANT: If asked "how to pay fees online", answer that students can pay
via the Online Fee Payment portal (link above) after logging into the
Student ERP — do NOT say "I don't have this information".

--- CELLS ---
EDC (Entrepreneurship Development Cell): Coordinator — Mr. Devendra Jain.
  Members: Dr. Poonam Nagar, Ms. Deepika Raikwar, Dr. Chandni Keswani,
  Mr. Ashish Sinhal, Mr. Hemant Pathak (Member only, not Incharge).
  Activities: Nav Udyami, Business Plan Competitions, Entrepreneurship
  Workshops, Startup Awareness Sessions, MSME Programs, IPR Workshops.

NSS (National Service Scheme): Program Officer — Mr. Ritesh Kushwah.
  Members: Ms. Pooja Parmar, Ms. Harsha Yadav, Mr. Ravi Chouhan,
  Mr. Varun Agrawal, Mr. Harish Sharma.
  Source: https://www.svimi.org/cells/nss.php

IIIC (Industry Institute Interface Cell): Coordinator — Dr. Digamber Negi.
  Members: Mr. Gaurav Porwal, Mr. Ravi Chouhan, Ms. Nidhi Dubey,
  Mr. Hemant Pathak (Member).
  Source: https://www.svimi.org/cells/iiic.php

IIC (Institution's Innovation Council), RDC (Research & Development Cell),
CDC (Case Development Cell), Monitoring Cell (supervises anti-ragging policy)
— for committee member details of these cells, say "I don't have the exact
list, please visit www.svimi.org"

--- ACTIVITY CLUBS (these are the ONLY real clubs — do not invent others) ---
IT Club, Finance Club, HR Club, Marketing Club, Literary Club,
Science Club, Photography Club

--- EVENTS ---
Abhisanskaran: Induction — August | Nav Udyami: Entrepreneurship by EDC — February
Srijan: Cultural fest — November | Khelotsav: Sports week — January
Prabandhotsav: Annual fest — March (past performers: Asees Kaur, Shirley Setia,
Sayli Kamble, Shanmukha Priya, Rupali Jagga, Ankush Bhardwaj — these are PERFORMERS not founders)
Confluence: Alumni Meet — March

--- SCHOLARSHIPS ---
SVIMS Meritorious Scholarship: for students with 75%+ attendance and strong academic performance — SVIMS's OWN scholarship, mention this prominently when asked about SVIMS scholarships.
Post Metric (SC/ST/OBC based on income), Minority Scholarship, Central Sector Scheme
(80%+ marks), Awas Scholarship (SC/ST), PG Indira Gandhi Scholarship (Single Girl
Child PG), AICTE Fellowship / GATE Fellowship.
For details: www.svimi.org/scholarship.php

--- FACULTY & STUDENT ACHIEVEMENTS ---
CRITICAL: We do NOT have any individual student/faculty names, specific years,
specific competition names, specific universities (IIM/IIT etc.), or specific
startup names for achievements. NEVER invent any of these — not even as
examples or placeholders like "[Name]". This is a common hallucination
mistake — avoid it completely.
PDF states ONLY these general facts (use ONLY this, nothing more specific):
- "SVIMS students regularly secure top positions in university merit lists.
  Students from BCA, BBA, B.Sc. Computer Science, Biotechnology, and
  Bioinformatics programmes have achieved University Topper and DAVV Merit
  positions with excellent CGPA and AGPA scores."
- "Students actively participate in national conferences, paper presentations,
  poster presentations, and research activities. Many students have received
  Best Paper Awards, Best Poster Awards, and recognition for their research
  contributions in Computer Science, Biotechnology, Bioinformatics, and Management."
- Faculty achievements include PhD awards, Best Research Paper Awards, Patents,
  publications, conference presentations (general categories only, no names/years).
For specific names, years, or detailed lists, ALWAYS direct the user to:
Student Achievement Report 2024-25: www.svimi.org/assets/images/achievements/Student_Achievements_2024-25.pdf
Faculty Achievement Report 2024-25: www.svimi.org/assets/images/achievements/Faculty_Other_Achievement_2024-25.pdf

--- SYLLABUS LINKS AVAILABLE (only these PDFs exist — copy URLs EXACTLY, do not simplify or rewrite them) ---
BCA I Year: https://www.svimi.org/assets/images/BCA_I_Year_Syllabus.pdf
BBA II Sem: https://www.svimi.org/assets/images/BBA_II_Sem_Syllabus.pdf
BBA (Foreign Trade) II Sem: https://www.svimi.org/assets/images/BBA_(FT)_II_Sem_Syllabus.pdf
BBA (Hospital Admin) II Sem: https://www.svimi.org/assets/images/BBA_(HA)_II_Sem_Syllabus.pdf
MBA Full Time: https://www.svimi.org/assets/images/MBA_FT_Syllabus.pdf
MBA Financial Administration: https://www.svimi.org/assets/images/MBA_FA_Syllabus.pdf
MBA Marketing Management: https://www.svimi.org/assets/images/MBA_MM_Syllabus.pdf
MCA: https://www.svimi.org/assets/images/MCA_Syllabus.pdf
M.Sc. CS: https://www.svimi.org/assets/images/M.Sc.CS_Syllabus.pdf
B.Sc. Computer Science I Year: https://www.svimi.org/assets/images/B.%20Sc._(CS)_I_Year_Syllabus.pdf
B.Sc. Biotechnology I Year: https://www.svimi.org/assets/images/B.%20Sc._(BT)_I_Year_Syllabus.pdf
B.Sc. Bioinformatics I Year: https://www.svimi.org/assets/images/B.%20Sc._(BI)_I_Year_Syllabus.pdf
B.Sc. Microbiology I Year: https://www.svimi.org/assets/images/B.%20Sc._(MB)_I_Year_Syllabus.pdf
CRITICAL: These B.Sc. URLs contain "B.%20Sc._(CS)_" with a literal "%20" and parentheses —
copy them EXACTLY character-for-character. Do NOT rewrite as "BSc_CS_" or any simplified form.
NOTE: College is newly autonomous (2025) — more semester syllabi will be added as they are uploaded.
When asked for 3rd/4th/5th/6th sem syllabus and it's not in the list above, say:
"Syllabi for higher semesters are being updated — please check www.svimi.org or contact svimi@svimi.org"

══════════════════════════════════════
CONTEXT FROM PDF & KNOWLEDGE BASE
══════════════════════════════════════
{context}"""

        messages = [{"role": "system", "content": system_prompt}]

        if external_history:
            for msg in external_history[-4:]:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "user":
                    messages.append({"role": "user", "content": content})
                elif role in ("bot", "assistant"):
                    messages.append({"role": "assistant", "content": content})

        messages.append({"role": "user", "content": question})

        answer = _call_groq(client, messages)

        # Defensive check — agar AI ne khali ya bahut chhota jawab diya,
        # generic fallback do instead of returning just a link with no text
        if not answer or len(answer.strip()) < 3:
            answer = ("I'm not sure about the exact details for this. "
                       "Please visit www.svimi.org or contact svimi@svimi.org | "
                       "Toll Free: 18002332601")

        links = get_links(question, context)
        if links and links[0]:
            url, label = links[0]
            answer += f"\n\n🔗 **More Info:** [{label}]({url})"

        # Cache karo — future mein same question ke liye no API call
        if cache_key:
            _cache_set(cache_key, answer)

        return answer

    except Exception as e:
        error = str(e).lower()
        print(f"🚨 ERROR: {e}")
        if any(x in error for x in ["quota", "429", "rate_limit"]):
            return "⏳ Server busy. Please try again!\n\n📧 svimi@svimi.org | 📞 0731-2789925 | 🆓 18002332601"
        elif any(x in error for x in ["invalid_api_key", "401"]):
            return "❌ API Key error. Check .env file."
        else:
            return "😊 Please rephrase and try again!\n\n📧 svimi@svimi.org | 📞 0731-2789925"