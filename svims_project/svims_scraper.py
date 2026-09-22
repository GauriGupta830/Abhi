"""
SVIMS CampusBot — Website Scraper & Knowledge Base Builder
==========================================================
PURANE ARCHITECTURE MEIN KYA PROBLEM THI:
  — Sirf 7 pages scrape hote the, text 4000 chars pe truncate ho jaata tha
  — Har rebuild pe dobara scrape (koi caching nahi)
  — PDF (SVIMS_database.pdf) pe poora dependency — PDF na ho to KB khaali
  — Internet na ho to 5+ minute HF retries ke baad CRASH

NAYA DESIGN:
  1. check_connectivity() → pehle quick internet check (6 sec max).
     Internet nahi? → scraping + model download skip, OFFLINE MODE
     (server turant start hota hai, facts-based answers full chalte hain)
  2. crawl()      → saare pages PARALLEL scrape karke knowledge/site_pages.json
                    mein cache (48 pages ~30 sec mein, pehle 10+ min lagte the)
  3. refresh()    → sirf DYNAMIC pages (notifications, results, time tables,
                    events, placements) dobara scrape — fast update
  4. build_index()→ verified facts (svims_facts.py) + scraped pages → FAISS index
  5. Agar website/site na mile → cached JSON + facts se hi KB banti hai

USAGE:
  python svims_scraper.py build     # full crawl + FAISS build
  python svims_scraper.py refresh   # sirf dynamic pages refresh + rebuild
  python svims_scraper.py status    # cache/health/internet info
"""

import os
import sys
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE_DIR = os.path.join(BASE_DIR, "knowledge")
SITE_CACHE_PATH = os.path.join(KNOWLEDGE_DIR, "site_pages.json")
FAISS_PATH = os.path.join(BASE_DIR, "faiss_index")

_CACHE_LOCK = threading.Lock()

# ══════════════════════════════════════════════════════════════════
# SITEMAP — official pages of www.svimi.org
# ══════════════════════════════════════════════════════════════════
SITEMAP = {
    # Home & About
    "https://www.svimi.org/": "Home",
    "https://www.svimi.org/about-institute-description.php": "About Institute",
    "https://www.svimi.org/vision.php": "Vision Mission and Quality Policy",
    "https://www.svimi.org/leadership.php?q=director": "Leadership Messages (Patron Chairman Secretary Director)",
    "https://www.svimi.org/governing-body.php": "Governing Body",
    "https://www.svimi.org/recongnition-description.php": "Recognition and Accreditation",
    "https://www.svimi.org/ranking-nirf.php": "NIRF Ranking Reports",
    "https://www.svimi.org/iqac.php": "IQAC",

    # Admissions & Programmes
    "https://www.svimi.org/admission-process.php": "Admission Process UG PG",
    "https://www.svimi.org/under-graduate.php": "Under Graduate Programmes BBA BCA BSc",
    "https://www.svimi.org/post-graduate.php": "Post Graduate Programmes MBA MCA MSc",
    "https://www.svimi.org/scholarship.php": "Scholarship and Financial Aid",
    "https://www.svimi.org/FAQs.php": "FAQs",
    "https://www.svimi.org/academic-faqs.php": "Academic FAQs",

    # Departments & Faculty
    "https://www.svimi.org/departments/faculties.php?q=faculty_cs": "Faculty Computer Science and BioScience Department",
    "https://www.svimi.org/departments/faculties.php?q=faculty_UG": "Faculty Management UG Department",
    "https://www.svimi.org/departments/faculties.php?q=faculty_PG": "Faculty Management PG Department",

    # Infrastructure
    "https://www.svimi.org/infrastructure/library.php": "Library",
    "https://www.svimi.org/infrastructure/computer.php": "Computer Labs",
    "https://www.svimi.org/infrastructure/MI-BT.php": "Microbiology Biotechnology Labs",
    "https://www.svimi.org/infrastructure/auditorium.php": "Auditorium Abhay Prashal",
    "https://www.svimi.org/infrastructure/hostel.php": "Hostel",
    "https://www.svimi.org/infrastructure/canteen.php": "Canteen",
    "https://www.svimi.org/infrastructure/sports.php": "Sports",

    # Placement
    "https://www.svimi.org/placement/about-placement.php": "Training and Placement Cell",
    "https://www.svimi.org/placement/recruiters.php": "Recruiters",
    "https://www.svimi.org/placement/prominent-selections.php": "Prominent Selections",
    "https://www.svimi.org/placement/placement.php": "Placement Glimpse",

    # Cells
    "https://www.svimi.org/cells/edc.php": "EDC Entrepreneurship Development Cell",
    "https://www.svimi.org/cells/nss.php": "NSS National Service Scheme Cell",
    "https://www.svimi.org/cells/iic.php": "IIC Institutions Innovation Council",
    "https://www.svimi.org/cells/rdc.php": "RDC Research Development Cell",
    "https://www.svimi.org/cells/cdc.php": "CDC Case Development Cell",
    "https://www.svimi.org/cells/iiic.php": "IIIC Industry Institute Interface Cell",

    # Clubs
    "https://www.svimi.org/activity-clubs/it-club.php": "IT Club",
    "https://www.svimi.org/activity-clubs/finance-club.php": "Finance Club",
    "https://www.svimi.org/activity-clubs/hr-club.php": "HR Club",
    "https://www.svimi.org/activity-clubs/marketing-club.php": "Marketing Club",
    "https://www.svimi.org/activity-clubs/literary-club.php": "Literary Club",
    "https://www.svimi.org/activity-clubs/science-club.php": "Science Club",
    "https://www.svimi.org/activity-clubs/photography-club.php": "Photography Club",

    # Events & Alumni
    "https://www.svimi.org/event-gallery.php?q=events": "Latest Events",
    "https://www.svimi.org/event-gallery.php?q=events-gallery": "Events Gallery",
    "https://www.svimi.org/video-gallery.php": "Video Gallery",
    "https://www.svimi.org/alumni-speak.php": "Alumni Speaks",
    "https://www.svimi.org/alumni_association.php": "Alumni Association",
    "https://www.svimi.org/e-newsletter.php": "E-News Letter",

    # Contact
    "https://www.svimi.org/contact-us.php": "Contact Us",
}

# Dynamic pages — yeh regularly update hoti hain
DYNAMIC_URLS = [
    "https://www.svimi.org/",
    "https://www.svimi.org/Notification.php",
    "https://www.svimi.org/Results.php",
    "https://www.svimi.org/Time-Table-Main.php",
    "https://www.svimi.org/Time-Table-ATKT.php",
    "https://www.svimi.org/event-gallery.php?q=events",
    "https://www.svimi.org/placement/prominent-selections.php",
    "https://www.svimi.org/placement/recruiters.php",
]

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}


def _load_cfg():
    try:
        with open(os.path.join(BASE_DIR, "svims_config.json"), "r", encoding="utf-8") as f:
            return json.load(f).get("scraper", {})
    except Exception:
        return {}


# ══════════════════════════════════════════════════════════════════
# CONNECTIVITY CHECK — no internet to fast-fail (10 min hang se bacho)
# ══════════════════════════════════════════════════════════════════
_CONNECTIVITY = {"checked_at": 0.0, "online": None}


def check_connectivity(timeout=6, force=False):
    """
    Quick internet check. Result 60 sec ke liye cache hota hai.
    svimi.org pehle try karte hain (asli target), phir google (general net).
    """
    now = time.time()
    if (not force and _CONNECTIVITY["online"] is not None
            and (now - _CONNECTIVITY["checked_at"]) < 60):
        return _CONNECTIVITY["online"]

    online = False
    try:
        import requests
        for url in ("https://www.svimi.org/", "https://www.google.com/",
                    "https://huggingface.co/"):
            try:
                r = requests.head(url, headers=_HEADERS, timeout=timeout,
                                  allow_redirects=True)
                if r.status_code < 500:
                    online = True
                    break
            except Exception:
                continue
    except Exception:
        online = False

    _CONNECTIVITY.update(checked_at=now, online=online)
    return online


# ══════════════════════════════════════════════════════════════════
# PAGE SCRAPING
# ══════════════════════════════════════════════════════════════════

def scrape_page(url, title="", max_chars=8000, timeout=10):
    """Ek page scrape karke saaf text return karo. Fail ho to None."""
    import requests
    from bs4 import BeautifulSoup

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        if resp.status_code != 200:
            return None
        resp.encoding = resp.apparent_encoding or "utf-8"

        soup = BeautifulSoup(resp.text, "html.parser")

        # Navigation/footer/script/style hatao — content hi chahiye
        for tag in soup(["script", "style", "nav", "footer", "header",
                         "noscript", "iframe", "form", "button"]):
            tag.decompose()

        text = soup.get_text(separator="\n")
        lines = [ln.strip() for ln in text.split("\n")]
        lines = [ln for ln in lines if ln and len(ln) > 1]
        text = "\n".join(lines)

        # Footer noise hatao (copyright etc. repeat hota hai)
        for noise in ["Copyright ©", "All rights reserved", "Designed & Developed",
                      "Follow Us", "Quick Links", "Get in Touch"]:
            if noise in text:
                text = text.split(noise)[0]

        text = text.strip()
        if len(text) < 120:          # effectively empty page
            return None

        return {
            "url": url,
            "title": title or url,
            "text": text[:max_chars],
            "scraped_at": time.time(),
        }
    except KeyboardInterrupt:
        raise
    except Exception as e:
        print(f"    ⚠️ Skipped {url} ({type(e).__name__})")
        return None


def _load_cache():
    with _CACHE_LOCK:
        if os.path.exists(SITE_CACHE_PATH):
            try:
                with open(SITE_CACHE_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
    return {}


def _save_cache(cache):
    with _CACHE_LOCK:
        os.makedirs(KNOWLEDGE_DIR, exist_ok=True)
        tmp = SITE_CACHE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=1)
        os.replace(tmp, SITE_CACHE_PATH)   # atomic-ish write


def crawl(urls=None, quiet=False, max_workers=5, skip_connectivity_check=False):
    """
    Diye gaye URLs (default: pura SITEMAP) PARALLEL scrape karke cache
    update karo. Internet nahi hai to fast-return (purana cache wapas).
    """
    cfg = _load_cfg()
    timeout = cfg.get("request_timeout", 10)
    max_chars = cfg.get("max_page_chars", 8000)

    # ── No internet? → 48 × timeout ka wait NE karo ──
    if not skip_connectivity_check and not check_connectivity():
        if not quiet:
            print("  ⚠️ Internet reachable nahi — scraping skipped")
            print("     (cached data + hardcoded facts use honge)")
        return _load_cache()

    targets = urls or list(SITEMAP.keys())
    results = {}

    def _worker(url):
        title = SITEMAP.get(url, "")
        return scrape_page(url, title, max_chars=max_chars, timeout=timeout)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_worker, u): u for u in targets}
        for fut in as_completed(futures):
            url = futures[fut]
            try:
                page = fut.result()
            except Exception:
                page = None
            if page:
                results[url] = page

    cache = _load_cache()
    cache.update(results)
    _save_cache(cache)
    if not quiet:
        print(f"  📊 Crawled: {len(results)}/{len(targets)} OK "
              f"(total cached: {len(cache)})")
    return cache


def refresh_dynamic(quiet=False):
    """Sirf dynamic pages dobara scrape karo (fast — notifications/results/events)."""
    if not quiet:
        print("🔄 Refreshing dynamic pages (notifications, results, time tables, events)...")
    return crawl(urls=DYNAMIC_URLS, quiet=quiet)


def _needs_refresh(cache, url, max_age_hours):
    if url not in cache:
        return True
    return (time.time() - cache[url].get("scraped_at", 0)) > (max_age_hours * 3600)


def auto_refresh_if_stale(quiet=True):
    """Dynamic pages purani ho gayi hain (config ke hisaab se) to refresh karo.
    Offline hone par fast-skip. Return True agar refresh hua."""
    cfg = _load_cfg()
    max_age = cfg.get("auto_refresh_hours", 12)
    cache = _load_cache()
    stale = [u for u in DYNAMIC_URLS if _needs_refresh(cache, u, max_age)]
    if not stale:
        return False
    try:
        refresh_dynamic(quiet=quiet)
        return True
    except Exception as e:
        print(f"  ⚠️ auto refresh failed: {e}")
        return False


# ══════════════════════════════════════════════════════════════════
# DYNAMIC PAGE SUMMARIES — LLM ke bina, seedha scraped cache se
# ══════════════════════════════════════════════════════════════════

def get_dynamic_summary(url, max_items=6):
    """Scraped page cache se latest items ki list nikaalo (notifications etc.).
    Return: (title, [lines]) ya None."""
    cache = _load_cache()
    page = cache.get(url)
    if not page:
        return None
    text = page["text"]

    items = []
    for ln in text.split("\n"):
        ln = ln.strip()
        if not ln or len(ln) < 12:
            continue
        low = ln.lower()
        if any(k in low for k in ["notice", "result", "declared", "exam", "time table",
                                  "timetable", "dated", "atkt", "form"]):
            if ln not in items:
                items.append(ln)
        if len(items) >= max_items:
            break

    if not items:
        items = [ln for ln in text.split("\n")
                 if len(ln) > 15 and "svimi.org" not in ln][:max_items]

    return page.get("title", url), items


def get_events_summary(max_items=5):
    """Latest events — event gallery page cache se."""
    res = get_dynamic_summary("https://www.svimi.org/event-gallery.php?q=events", max_items)
    if res:
        return res
    return None


# ══════════════════════════════════════════════════════════════════
# FAISS INDEX BUILD
# ══════════════════════════════════════════════════════════════════

def _split_long_text(text, chunk_size=900, overlap=120):
    """Lambi page text ko overlapping chunks mein todo (RAG ke liye)."""
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            cut = text.rfind(" ", start + chunk_size - 150, end)
            if cut > start:
                end = cut
        chunk = text[start:end].strip()
        if len(chunk) > 80:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def build_knowledge_docs():
    """Facts + scraped pages → document list (FAISS input)."""
    import svims_facts

    docs = []

    # 1) VERIFIED FACTS — hamesha available (offline-safe)
    docs.extend(svims_facts.build_fact_documents())

    # 2) SCRAPED WEBSITE PAGES — cache se (fresh ho ya purani)
    cache = _load_cache()
    for url, page in cache.items():
        header = f"[{page.get('title', '')} — {url}]\n"
        body = page.get("text", "")
        if len(body) <= 1000:
            docs.append(header + body)
        else:
            for chunk in _split_long_text(body):
                docs.append(header + chunk)

    return docs


def _embedding_model_available():
    """Embedding model cache mein hai ya nahi (bina download ke check)."""
    try:
        from huggingface_hub import scan_cache_dir
        for repo in scan_cache_dir().repos:
            if "all-MiniLM-L6-v2" in repo.repo_id:
                return True
    except Exception:
        pass
    return False


def build_index(quiet=False):
    """FAISS index banao: facts + scraped pages. Return: vector_store."""
    from langchain_community.vectorstores import FAISS
    from langchain_huggingface import HuggingFaceEmbeddings

    docs = build_knowledge_docs()
    if not quiet:
        print(f"  📚 Knowledge documents: {len(docs)} "
              f"(facts + {len(_load_cache())} scraped pages)")

    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    vector_store = FAISS.from_texts(docs, embedding=embeddings)
    os.makedirs(FAISS_PATH, exist_ok=True)
    vector_store.save_local(FAISS_PATH)
    if not quiet:
        print(f"  ✅ FAISS index saved: {FAISS_PATH}")
    return vector_store


def load_index():
    """Existing FAISS index load karo, warna None."""
    try:
        from langchain_community.vectorstores import FAISS
        from langchain_huggingface import HuggingFaceEmbeddings

        if os.path.exists(os.path.join(FAISS_PATH, "index.faiss")):
            embeddings = HuggingFaceEmbeddings(
                model_name="sentence-transformers/all-MiniLM-L6-v2")
            return FAISS.load_local(FAISS_PATH, embeddings,
                                    allow_dangerous_deserialization=True)
    except Exception as e:
        print(f"  ⚠️ FAISS load failed: {e}")
    return None


def ensure_knowledge_base(crawl_first=True, quiet=False):
    """
    Server startup ke liye main entry — NEVER crashes, NEVER hangs:
      1. Internet check FIRST (6 sec) — offline to seedha facts-only mode
      2. FAISS index hai? → load karo
      3. Nahi hai → (best-effort crawl) + build
    Offline hone par HF offline flags set hote hain taaki model-download
    5+ minute retry na kare — instant fail-fast.
    """
    # ── STEP 1: connectivity (sabse pehle — load_index se bhi pehle,
    #    kyunki load_index embedding model download try kar sakta hai) ──
    online = check_connectivity()
    if not online:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        print("  ⚠️ Internet NOT reachable — OFFLINE MODE")
        print("     • Website scraping: skipped")
        print("     • Facts-based answers (fees/courses/contacts/admission...): FULL")
        print("     • AI (RAG) answers: internet wapas aane pe")
        print("     • Internet aane ke baad full build: python svims_scraper.py build")

        # Model pehle se cached hai? → offline index ban sakta hai
        try:
            vs = load_index()
            if vs is not None:
                return vs
            if _embedding_model_available():
                return build_index(quiet=True)
        except Exception:
            pass
        return None

    # ── STEP 2: online — normal flow ──
    vs = load_index()
    if vs is not None:
        return vs

    if crawl_first:
        try:
            crawl(quiet=quiet, skip_connectivity_check=True)
        except Exception as e:
            print(f"  ⚠️ Crawl failed ({e}) — building from facts only")

    try:
        return build_index(quiet=quiet)
    except Exception as e:
        print(f"  ⚠️ Index build failed: {e}")
        return None


def rebuild_after_refresh():
    """Dynamic refresh ke baad index rebuild."""
    return build_index(quiet=True)


# ══════════════════════════════════════════════════════════════════
# STATUS
# ══════════════════════════════════════════════════════════════════

def status():
    cache = _load_cache()
    has_index = os.path.exists(os.path.join(FAISS_PATH, "index.faiss"))
    newest = max((p.get("scraped_at", 0) for p in cache.values()), default=0)
    return {
        "cached_pages": len(cache),
        "faiss_index": has_index,
        "last_scrape": time.strftime("%Y-%m-%d %H:%M", time.localtime(newest)) if newest else None,
        "sitemap_pages": len(SITEMAP),
        "internet": check_connectivity(),
        "embedding_model_cached": _embedding_model_available(),
    }


# ══════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"

    if cmd == "build":
        print("🔄 Full crawl + knowledge base build...")
        if not check_connectivity():
            print("❌ Internet nahi mil raha — scraping ke liye internet chahiye.")
            print("   Check: WiFi/LAN connected? VPN/proxy/firewall? 'ping www.google.com'")
            sys.exit(1)
        crawl(skip_connectivity_check=True)
        build_index()
        print("✅ Done.")
    elif cmd == "refresh":
        refresh_dynamic()
        rebuild_after_refresh()
        print("✅ Dynamic pages refreshed + index rebuilt.")
    elif cmd == "status":
        print(json.dumps(status(), indent=2))
    else:
        print("Usage: python svims_scraper.py [build|refresh|status]")
