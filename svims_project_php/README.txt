SVIMS CampusBot — Setup Guide (PHP Version)
============================================
Ye puri Python project ka exact PHP port hai — koi logic ya UI change NAHI.
Har Python file ki corresponding PHP file hai:

  svims_server.py    ->  svims_server.php
  svims_app.py       ->  svims_app.php
  svims_engine.py    ->  svims_engine.php
  svims_processor.py ->  svims_processor.php
  svims_qa_loader.py ->  svims_qa_loader.php
  (pip packages)     ->  svims_lib.php   (dotenv/http/PDF/splitter/embeddings/vector-store/difflib)
  index.html         ->  index.html      (100% same file — touch nahi kiya)
  svims_config.json  ->  svims_config.json (100% same file)

Requirements:
  PHP 7.4+ (PHP 8.x recommended) — cURL extension ke saath (XAMPP/WAMP mein default hota hai)
  Koi composer/pip package NAHI chahiye — sab kuch pure PHP mein hai.

1. .env file banao (.env.example se copy karo):
   - GROQ_API_KEY_1 (apni Groq API key)
   - HF_API_TOKEN (free token: https://huggingface.co/settings/tokens)
     Ye embeddings ke liye hai (Python mein sentence-transformers model
     locally download hota tha; PHP mein wahi all-MiniLM-L6-v2 model
     HuggingFace Inference API se use hota hai).
   - Optional: EMBEDDINGS_API_URL — agar apna embedding server ho.

2. Apna PDF add karo:
   Folder banao: college_docs/
   Usme SVIMS_database.pdf daalo.

3. Server chalao:
   php svims_server.php

4. Browser kholo:
   http://127.0.0.1:5000

NOTE: Pehli run pe knowledge base banegi (index build hota hai).
Uske baad server seconds mein load hota hai (faiss_index/ cache se).

Config update (fees, links, etc.): svims_config.json edit karo
Config change ke baad: curl -X POST http://127.0.0.1:5000/api/reload-config
(NOTE: reload-config endpoint Python version mein bhi partial tha —
engine mein _build_syllabus_answers() defined na hone ki wajah se wo
config update karke bhi error return karta tha. Ye behaviour PHP port
mein bhi bilkul same rakha hai, koi logic change nahi kiya.)

Dusra backend variant (svims_app.py ka port): php svims_app.php
