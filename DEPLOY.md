# Deploying Legal AI Hub (Azure VM or any Linux host)

Vectors use **local ChromaDB** on disk (`chromadb/`, `.chromadb/`, `vector_store/`).  
There is **no** Azure PostgreSQL login and **no** Pinecone requirement.

## What you need

| Item | Purpose |
|------|---------|
| VM or laptop with Python 3.11+ (3.12 recommended) | Run Streamlit |
| ≥4–8 GB RAM | Embedding model `all-MiniLM-L6-v2` |
| `GROQ_API_KEY` | LLM for all features |
| `COURTLISTENER_API_KEY` | Litigation CourtListener tab only |
| `APIFY_TOKEN` | Live regulations feature only |
| `data/` folder | Source PDFs/TXT on the same machine |

---

## 1. Install and run

```bash
cd /path/to/LegalAI
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env — at minimum set GROQ_API_KEY

streamlit run streamlit_app.py --server.address 0.0.0.0 --server.port 8501
```

Open the app in a browser (`http://<vm-public-ip>:8501`).  
First use of a feature builds/loads Chroma collections on disk under the repo.

---

## 2. Azure VM networking

1. Create Ubuntu VM (B2s or larger if embeddings feel slow).
2. NSG inbound rule: TCP **8501** from your IP (or put nginx + TLS in front).
3. Copy the repo (and `data/`) onto the VM, or clone from git.
4. Prefer keeping `data/` and `chromadb/` on persistent disk so indexes survive reboot.

---

## 3. Smoke checklist

- [ ] App opens with no login screen
- [ ] Contract Q&A / Policies loads existing docs and answers a question
- [ ] `chromadb/` (or feature persist path) gains files after first index
- [ ] Regulations works when `APIFY_TOKEN` is set (uses `.chromadb/`)

---

## Not used in this mode

- Azure Database for PostgreSQL / `DATABASE_URL` / `migrations/`
- Pinecone / Langfuse cloud keys
- `scripts/bootstrap_admin.py` / `scripts/reindex_to_pinecone.py`
