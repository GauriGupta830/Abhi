import os
import re
import requests
import pdfplumber
from bs4 import BeautifulSoup
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FAISS_PATH = os.path.join(BASE_DIR, "faiss_index")
PDF_FOLDER = os.path.join(BASE_DIR, "college_docs")

# Backup scraping — SIRF wo pages jo regularly UPDATE hote hain.
# PDF mein static info (courses, fees, faculty names, policies, clubs, etc.)
# already hai — unko dobara scrape NAHI karna, taaki duplicate/conflicting
# data na bane aur AI confuse na ho.
BACKUP_PAGES = {
    "https://www.svimi.org/Notification.php": "Latest Notifications",
    "https://www.svimi.org/Time-Table-Main.php": "Exam Time Table Main",
    "https://www.svimi.org/Time-Table-ATKT.php": "Exam Time Table ATKT",
    "https://www.svimi.org/Results.php": "Exam Results",
    "https://www.svimi.org/placement/prominent-selections.php": "Latest Placed Students",
    "https://www.svimi.org/placement/recruiters.php": "Current Recruiters List",
    "https://www.svimi.org/event-gallery.php?q=events": "Upcoming/Recent Events",
}


def extract_qa_chunks_from_pdf(pdf_path):
    """
    PDF se Q&A pairs extract karo.
    Har Q+A+Link ek saath rakho — context nahi tootega.
    """
    chunks = []

    try:
        with pdfplumber.open(pdf_path) as pdf:
            total = len(pdf.pages)
            print(f"  📄 Pages: {total}")

            full_text = ""
            for page in pdf.pages:
                text = page.extract_text() or ""
                full_text += text + "\n"

        lines = full_text.split('\n')
        block = []

        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith('Q:') and block:
                chunk_text = '\n'.join(block)
                if len(chunk_text) > 30:
                    chunks.append(chunk_text)
                block = [line]
            else:
                block.append(line)

        if block:
            chunk_text = '\n'.join(block)
            if len(chunk_text) > 30:
                chunks.append(chunk_text)

        print(f"  ✅ Q&A chunks extracted: {len(chunks)}")

        link_count = sum(1 for c in chunks if 'http' in c.lower())
        print(f"  🔗 Chunks with links: {link_count}")

    except Exception as e:
        print(f"  ❌ PDF error: {e}")

    return chunks


def read_all_pdfs():
    """college_docs folder se PDFs padho"""
    all_chunks = []

    if not os.path.exists(PDF_FOLDER):
        os.makedirs(PDF_FOLDER)
        return []

    pdf_files = [f for f in os.listdir(PDF_FOLDER) if f.endswith('.pdf')]

    if not pdf_files:
        print("  ⚠️ Koi PDF nahi mili!")
        return []

    print(f"  📄 {len(pdf_files)} PDF(s) mili!")

    for pdf_file in pdf_files:
        print(f"\n  Reading: {pdf_file}")
        chunks = extract_qa_chunks_from_pdf(
            os.path.join(PDF_FOLDER, pdf_file)
        )
        all_chunks.extend(chunks)

    return all_chunks


def scrape_page(url, topic=""):
    """Backup scraping — sirf tab jab PDF mein nahi ho"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=8)
        soup = BeautifulSoup(response.text, 'html.parser')
        for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
            tag.decompose()
        text = ' '.join(soup.get_text().split())
        if len(text) > 100:
            print(f"  ✅ {topic}")
            return f"TOPIC: {topic}\nSOURCE: {url}\n{text[:4000]}"
        return ""
    except KeyboardInterrupt:
        raise
    except Exception:
        print(f"  ⏭️ Skipped: {topic}")
        return ""


def create_knowledge_base(college_url=None):
    print("\n" + "="*60)
    print("🔄 SVIMS KNOWLEDGE BASE BAN RAHI HAI")
    print("="*60)

    all_chunks = []

    # ─────────────────────────────────────────
    # SOURCE 1: PDF Q&A (PRIMARY — sabse pehle priority)
    # ─────────────────────────────────────────
    print("\n📄 SOURCE 1: PDF Q&A Database (Primary)...")
    print("-"*40)
    pdf_chunks = read_all_pdfs()

    if pdf_chunks:
        # PDF chunks 2x weight — duplicate karke add karo
        all_chunks.extend(pdf_chunks)
        all_chunks.extend(pdf_chunks)
        print(f"  ✅ PDF chunks: {len(pdf_chunks)} (added 2x weight)")
    else:
        print("  ⚠️ No PDF found! Sirf website se chalega.")

    # ─────────────────────────────────────────
    # SOURCE 2: Website Scraping (BACKUP ONLY)
    # ─────────────────────────────────────────
    print(f"\n🌐 SOURCE 2: Backup Website Scraping ({len(BACKUP_PAGES)} pages)...")
    print("-"*40)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=900,
        chunk_overlap=150,
        separators=["\n\n", "\n", ".", " "]
    )

    scraped = 0
    for url, topic in BACKUP_PAGES.items():
        result = scrape_page(url, topic)
        if result:
            web_chunks = splitter.split_text(result)
            all_chunks.extend(web_chunks)
            scraped += 1

    print(f"  ✅ Scraped: {scraped}/{len(BACKUP_PAGES)}")

    # ─────────────────────────────────────────
    # FAISS INDEX
    # ─────────────────────────────────────────
    print(f"\n📊 Total chunks: {len(all_chunks)}")
    print("🧠 FAISS index ban raha hai... (2-5 min wait karo)")

    embeddings = HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2"
    )

    vector_store = FAISS.from_texts(all_chunks, embedding=embeddings)
    os.makedirs(FAISS_PATH, exist_ok=True)
    vector_store.save_local(FAISS_PATH)

    print("\n" + "="*60)
    print("✅ KNOWLEDGE BASE READY!")
    print(f"   📄 PDF Q&A chunks: {len(pdf_chunks) if pdf_chunks else 0}")
    print(f"   🌐 Web scraped (backup): {scraped} pages")
    print(f"   🧩 Total: {len(all_chunks)}")
    print("="*60 + "\n")

    return vector_store


def load_knowledge_base():
    index_file = os.path.join(FAISS_PATH, "index.faiss")
    if os.path.exists(FAISS_PATH) and os.path.exists(index_file):
        print(f"📂 Loading: {FAISS_PATH}")
        embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )
        return FAISS.load_local(
            FAISS_PATH,
            embeddings,
            allow_dangerous_deserialization=True
        )
    return None