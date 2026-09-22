# SVIMS CampusBot — Official AI Assistant

Shri Vaishnav Institute of Management & Science (SVIMS), Indore ka AI chatbot.
**Saara data official college website https://www.svimi.org/ se aata hai:**
important facts hardcoded (verified), baaki live web-scraping se.

---

## Architecture (v3.0 — PDF-free)

```
┌────────────┐     ┌──────────────────────────────────────────────┐
│ index.html │◄────►│ svims_server.py  (Flask — single server)     │
└────────────┘     └──────────────┬───────────────────────────────┘
                                  │
                   ┌──────────────▼───────────────┐
                   │ svims_engine.py  (BRAIN)     │
                   │  Layer 0-3: greeting/math    │
                   │  Layer 4:   FACT ANSWERS  ◄──┼── svims_facts.py (hardcoded,
                   │  Layer 5:   SCRAPED DATA  ◄──┼──   website-verified data)
                   │  Layer 6:   RAG + GROQ API ◄─┼── svims_scraper.py (svimi.org
                   │  Layer 7:   fallback         │    crawling → FAISS index)
                   └──────────────────────────────┘
```

| File | Kaam |
|---|---|
| `svims_facts.py` | **Hardcoded verified knowledge** — courses, fees, seats, contacts, leadership, HODs, scholarships, library, hostel, cells, events, anti-ragging. Sab svimi.org se verify karke likha gaya. |
| `svims_scraper.py` | svimi.org ke ~55 pages crawl karke `knowledge/site_pages.json` mein cache + FAISS index build. Dynamic pages (notifications/results/time tables/events) refresh kar sakta hai. |
| `svims_engine.py` | Answer pipeline — pehle deterministic facts (100% accurate, no API), phir scraped data, phir RAG+Groq. |
| `svims_server.py` | Flask server + APIs. |
| `svims_config.json` | Updatable settings — Groq models, academic calendar, syllabus links, achievement links. |
| `index.html` | Chat UI (sidebar: quick questions, contacts, events, map). |

### Data flow ka rule
- **Facts** (fees, courses, contacts...) → `svims_facts.py` mein hardcoded → hamesha accurate
- **Dynamic** (notifications, results, time tables, events) → `svims_scraper.py` website se scrape
- **Complex questions** → FAISS (scraped pages) + Groq LLM, strict grounding prompt ke saath
- **Kuch bhi bahar ka data nahi** — sirf svimi.org

---

## Setup

```bash
cd svims_project

# 1. Dependencies
pip install -r requirements.txt

# 2. API key
cp .env.example .env        # phir .env mein apni Groq key daalo
                            # (free key: https://console.groq.com/keys)

# 3. (Optional) Pehle hi website scrape kar lo — recommended
python svims_scraper.py build

# 4. Server chalao
python svims_server.py
```

Browser mein kholo: **http://localhost:5000**

> **Note:** First run pe sentence-transformers ka embedding model (~90 MB)
> download hota hai. Uske baad seconds mein start hota hai.
> Bina Groq key ke bhi server chalta hai — fees/courses/contacts jaise
> factual questions ke jawab deterministic layers se milte hain;
> AI-wale answers ke liye key chahiye.

---

## APIs

| Endpoint | Method | Kaam |
|---|---|---|
| `/api/chat` | POST | `{message, session_id}` → `{response}` |
| `/api/status` | GET | Health — groq, knowledge base, scrape info |
| `/api/clear` | POST | Session history clear |
| `/api/reload-config` | POST | `svims_config.json` hot-reload |
| `/api/refresh-knowledge` | POST | Dynamic pages re-scrape + index rebuild |
| `/api/model-status` | GET | Groq models status |

## Maintenance

- **Fees/HOD/contacts change hue?** → `svims_facts.py` update karo, restart
- **Naya syllabus/calendar PDF aaya?** → `svims_config.json` update karo + `/api/reload-config`
- **Latest notifications chahiye?** → `POST /api/refresh-knowledge` ya `python svims_scraper.py refresh`
- **Full re-scrape?** → `python svims_scraper.py build`

## Production

```bash
gunicorn -w 1 -b 0.0.0.0:5000 svims_server:app
```
(1 worker zaroori hai — FAISS + in-memory sessions single process mein hain.)
