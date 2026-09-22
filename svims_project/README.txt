SVIMS CampusBot — Setup Guide
==============================

1. Install dependencies:
   pip install -r requirements.txt

2. Create .env file (copy from .env.example):
   Copy .env.example to .env
   Add your Groq API key

3. Add your PDF:
   Create folder: college_docs/
   Place SVIMS_database.pdf inside it

4. Run server:
   python svims_server.py

5. Open browser:
   http://127.0.0.1:5000

NOTE: First run will build FAISS index (2-3 minutes).
After that, server loads in seconds.

Update config (fees, links, etc.): Edit svims_config.json
After config change: curl -X POST http://127.0.0.1:5000/api/reload-config
