"""
SVIMS Direct Q&A Matcher
=========================
PDF mein 383 ready-made Q&A pairs hain (Question + Answer + Source Link).
Yeh module FAISS ke saath integrate hota hai: jab user ka question PDF ke
kisi exact Q&A se closely match karta hai, toh PDF ka EXACT answer aur
EXACT link directly use hota hai — AI ko sirf phrasing/tone ke liye call
kiya jaata hai, content invent karne ka koi mauka nahi milta.

Ismein WHI sentence-transformers model use hota hai jo svims_processor.py
FAISS ke liye already use kar raha hai — koi extra dependency/download nahi.
"""

import os
import re
import pickle


def parse_pdf_qa_pairs(pdf_path):
    """
    PDF se saare Q&A pairs nikalo, poora document ek saath (pypdf se text
    extract karte hain) taaki cross-page Q&A split na ho.

    NOTE: Pehle 'pdftotext' (Poppler) use hota tha jo external software hai
    aur Windows/naye laptop pe manually install karna padta tha. Ab
    'pypdf' use kar rahe hain — ye pure Python library hai, requirements.txt
    se hi 'pip install' ho jaati hai, koi extra setup nahi chahiye.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        print("  pypdf not installed — run: pip install pypdf")
        return []

    try:
        reader = PdfReader(pdf_path)
        pages_text = [page.extract_text() or "" for page in reader.pages]
        text = "\n".join(pages_text)
    except Exception as e:
        print(f"  PDF text extraction failed: {e}")
        return []

    pattern = re.compile(
        r'Q[:.]\s*(.+?)\n+'
        r'A:\s*(.*?)'
        r'(?:\n+(?:Link|Source):\s*(\S+))?'
        r'(?=\n+Q[:.]|\Z)',
        re.DOTALL
    )

    qa_pairs = []
    for m in pattern.finditer(text):
        q = m.group(1).strip()
        a = re.sub(r'\n{2,}', '\n', m.group(2).strip())
        link = (m.group(3) or '').strip().rstrip('.,;)')
        if q and a and len(a) > 3:
            qa_pairs.append({"question": q, "answer": a, "link": link})

    return qa_pairs


class SVIMSQAMatcher:
    """
    User question ko PDF ke Q&A pairs se semantic similarity se match karta hai.
    High-confidence match -> PDF ka EXACT answer + link directly return.
    """

    def __init__(self, pdf_path, cache_path="svims_qa_cache.pkl",
                 high_threshold=0.68, low_threshold=0.40):
        self.high_threshold = high_threshold
        self.low_threshold = low_threshold
        self.qa_pairs = []
        self.question_embeddings = None
        self.model = None
        self._load(pdf_path, cache_path)

    def _load(self, pdf_path, cache_path):
        pdf_mtime = os.path.getmtime(pdf_path) if os.path.exists(pdf_path) else 0

        if os.path.exists(cache_path):
            try:
                with open(cache_path, "rb") as f:
                    cached = pickle.load(f)
                if cached.get("pdf_mtime") == pdf_mtime:
                    self.qa_pairs = cached["qa_pairs"]
                    self.question_embeddings = cached["question_embeddings"]
                    print(f"✅ Q&A cache loaded: {len(self.qa_pairs)} pairs")
                    self._load_model()
                    return
            except Exception as e:
                print(f"  Q&A cache load failed: {e} — rebuilding...")

        print("🔄 Building direct Q&A index from PDF...")
        self.qa_pairs = parse_pdf_qa_pairs(pdf_path)
        print(f"  Parsed {len(self.qa_pairs)} Q&A pairs from PDF")

        if not self.qa_pairs:
            print("  ⚠️ No Q&A pairs found — direct matching disabled")
            return

        self._load_model()
        questions = [p["question"] for p in self.qa_pairs]
        self.question_embeddings = self.model.encode(
            questions, show_progress_bar=False, convert_to_numpy=True
        )

        try:
            with open(cache_path, "wb") as f:
                pickle.dump({
                    "pdf_mtime": pdf_mtime,
                    "qa_pairs": self.qa_pairs,
                    "question_embeddings": self.question_embeddings,
                }, f)
            print(f"✅ Q&A index built and cached: {len(self.qa_pairs)} pairs")
        except Exception as e:
            print(f"  Cache save failed (non-fatal): {e}")

    def _load_model(self):
        if self.model is None:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

    def find_best_matches(self, user_question, top_k=3):
        if not self.qa_pairs or self.question_embeddings is None:
            return []

        import numpy as np
        query_emb = self.model.encode([user_question], convert_to_numpy=True)[0]

        norms = np.linalg.norm(self.question_embeddings, axis=1) * np.linalg.norm(query_emb)
        norms[norms == 0] = 1e-10
        similarities = np.dot(self.question_embeddings, query_emb) / norms

        top_indices = np.argsort(similarities)[::-1][:top_k]
        results = []
        for idx in top_indices:
            results.append({
                "question": self.qa_pairs[idx]["question"],
                "answer": self.qa_pairs[idx]["answer"],
                "link": self.qa_pairs[idx]["link"],
                "score": float(similarities[idx]),
            })
        return results

    def get_direct_answer(self, user_question):
        """High-confidence single match -> PDF ka exact answer/link. Warna None."""
        matches = self.find_best_matches(user_question, top_k=1)
        if not matches:
            return None
        best = matches[0]
        if best["score"] >= self.high_threshold:
            return best
        return None

    def get_relevant_context(self, user_question, top_k=6):
        """
        Top-k relevant Q&A pairs ko context string banakar do — AI ko dene
        ke liye jab single direct match na mile (multi-part/combined queries).
        """
        matches = self.find_best_matches(user_question, top_k=top_k)
        relevant = [m for m in matches if m["score"] >= self.low_threshold]
        if not relevant:
            relevant = matches[:3]

        context_parts = []
        for m in relevant:
            part = f"Q: {m['question']}\nA: {m['answer']}"
            if m["link"]:
                part += f"\nLink: {m['link']}"
            context_parts.append(part)
        return "\n\n---\n\n".join(context_parts), relevant