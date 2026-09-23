# LegalAI Data Sources Guide

Where to get documents for each feature, and where to put them on disk.

All feature folders live under `data/`. After adding files, restart Streamlit (or clear the relevant Chroma collection under `chromadb/`) so new documents are indexed.

---

## 1. Compliance Audit Generator

**Drop path:** `data/Compliance/` (top-level `.pdf` files)  
**Uploads:** `data/Compliance/uploads/`

True internal audit / SOC 2 reports are rarely public. Use these instead:

| Source | What you get | Link |
|---|---|---|
| SEC EDGAR company search | 10-K filings (auditor’s report, Item 9A / ICFR) | https://www.sec.gov/edgar/searchedgar/companysearch |
| Notre Dame SRAF 10-X archives | Bulk cleaned 10-K/Q text | https://sraf.nd.edu/sec-edgar-data/ |
| PCAOB inspection reports | Audit-firm inspections (not company-level) | https://pcaobus.org/oversight/inspections |

**Suggested seed tickers:** AAPL, MSFT, AMZN, GOOGL, JPM, JNJ, XOM, WMT.

**Scripted option:** SEC full-index + a User-Agent header, e.g. [simonschoe/scraper-edgar](https://github.com/simonschoe/scraper-edgar) filtered to form `10-K`.

---

## 2. Contract Q&A

**Drop path:** `data/Contract_Renewal_QNA/` (top-level `.txt` only)  
**Uploads:** `data/Contract_Renewal_QNA/uploads/`

You already have ~510 EDGAR-style contracts. To expand or replace:

| Source | Size | Link |
|---|---|---|
| Stanford Material Contracts Corpus (MCC) | ~1M contracts (~21 GB full) — use a small filtered subset | https://mcc.law.stanford.edu/ |
| CUAD (Atticus) | 510 annotated commercial contracts | https://www.atticusprojectai.org/cuad |
| Hand-picked EDGAR Exhibit 10 | Dozens–hundreds of `.txt` | SEC company filings → Exhibits |

Convert HTML/PDF to `.txt` before placing files here. Nested folders are not listed by the app’s existing-source picker.

---

## 3. Contract Risk Analyzer

**Risk KB (always loaded):** `data/Contract_Risk/*.{pdf,csv,txt}`  
**Contracts to analyze:** upload in the UI, or place under `data/Contract_Risk/uploaded_contracts/`

| Asset | Path | Notes |
|---|---|---|
| Clause risk matrix | `data/Contract_Risk/legal_contract_clauses.csv` | Columns: `clause_text`, `clause_type`, `risk_level` |
| Clause reference PDF | `data/Contract_Risk/Contract_Clauses_Data.pdf` | Secondary KB source |

**Sample contracts for upload testing:** reuse any `.txt` from `data/Contract_Renewal_QNA/`, or download EDGAR Exhibit 10 EULAs / MSAs / NDAs as PDF or TXT.

Use the in-app **Browse risky clauses** panel to filter the CSV by risk level and clause type without asking the LLM.

---

## 4. Policies Q&A

**Drop path:** `data/Policies_QNA/`  
No change required. Current Apple policy PDFs are fine.

---

## 5. Litigation Support

**Drop path:** `data/Litigation/` (top-level `.pdf`)  
**Uploads:** `data/Litigation/uploads/`  
**Live case law:** CourtListener API (`COURTLISTENER_API_KEY` in `.env`)

| Document type | Where to get |
|---|---|
| Complaints / indictments | https://www.justice.gov/ |
| Opinions / dockets | CourtListener (export PDFs for cases you care about) |
| Briefs / amicus | Circuit / Supreme Court sites; SCOTUSblog linked PDFs |
| Public settlements | EDGAR Exhibit 10/99; DOJ antitrust settlements |
| Pattern jury instructions | Federal circuit pattern jury instruction PDFs |

Aim for ~10–20 focused PDFs in one domain (e.g. commercial disputes + antitrust) so Document Q&A has real case language.

---

## 6. Regulations Search (live)

No local `data/` folder. Search hits Regulations.gov via Apify.

Useful U.S. federal bodies to track (also shown in the app sidebar):

| Area | Bodies |
|---|---|
| Securities / markets | SEC, CFTC, FINRA |
| Consumer / privacy | FTC, CFPB, HHS OCR (HIPAA) |
| Workplace / safety | OSHA, DOL, EEOC |
| Health / pharma | FDA, CMS |
| Environment | EPA |
| Finance / AML | FinCEN, OCC, FDIC, Federal Reserve |
| Tech / comms | FCC, NIST, CISA |
| Trade / export | BIS (Commerce), OFAC |
| Tax | IRS |

Also follow: Federal Register daily, agency RSS feeds, and eCFR titles for your vertical.

---

## After adding documents

1. Place files in the correct folder (top-level, correct extension).
2. Restart: `streamlit run streamlit_app.py`
3. If old embeddings stick around, delete the feature’s collection under `chromadb/` (or `vector_store/litigation_support` for Litigation) and reload from the UI.
