# Milestone 3 — PowerPoint Content (2 slides max)

Copy each block into a slide. Numbers below are measured from the real build,
not estimates.

---

## Slide 1 — Container Architecture

**Title:** Legal AI Hub — One Image, Two Machines

### Diagram (recreate as boxes/arrows)

```
                  ┌──────────────────────────────────────────┐
  Browser  ──────▶│  host port 8501                          │
 :8501            │        │                                  │
                  │  ┌─────▼──────────────────────────────┐  │
                  │  │ network: legal-ai-net (bridge)     │  │
                  │  │                                    │  │
                  │  │  ┌──────────────────────────────┐  │  │
                  │  │  │ service: app                 │  │  │
                  │  │  │ legal-ai-hub:v1              │  │  │
                  │  │  │ streamlit · container :8501   │  │  │
                  │  │  │ USER appuser (uid 10001)     │  │  │
                  │  │  │                              │  │  │
                  │  │  │  /app/src        (code)      │  │  │
                  │  │  │  /app/data       (510 docs)  │  │  │
                  │  │  │  /opt/venv       (deps)      │  │  │
                  │  │  │  /opt/hf-cache   (MiniLM)    │  │  │
                  │  │  │                              │  │  │
                  │  │  │  /app/chromadb     ◀── vol 1 │  │  │
                  │  │  │  /app/vector_store ◀── vol 2 │  │  │
                  │  │  │  /app/.chromadb    ◀── vol 3 │  │  │
                  │  │  └───────────┬──────────────────┘  │  │
                  │  └──────────────┼─────────────────────┘  │
                  │  ┌──────────────▼───────────────────┐    │
                  │  │ legal-ai-chroma      (143 MB)    │    │
                  │  │ legal-ai-litigation  ( 59 MB)    │    │
                  │  │ legal-ai-regulations             │    │
                  │  │ vector indexes, persistent       │    │
                  │  └──────────────────────────────────┘    │
                  └──────────────────┼───────────────────────┘
                                     │ HTTPS egress
                          ┌──────────▼───────────┐
                          │ Groq · CourtListener │
                          │ Apify · Regulations  │
                          │ (keys injected at    │
                          │  run time, not baked)│
                          └──────────────────────┘
```

### Bullets

- **Service:** one `app` container — Streamlit multi-page UI with 6 RAG features.
- **Ports:** host `8501` → container `8501`; same URL as Milestone 2.
- **Volumes:** three, because the app keeps three independent index roots —
  `legal-ai-chroma` → `/app/chromadb` (contract Q&A, policies, audit, risk),
  `legal-ai-litigation` → `/app/vector_store`, and `legal-ai-regulations` →
  `/app/.chromadb`. This is the only mutable state, so indexes survive
  `docker compose down` and image version swaps.
- **Network:** user-defined bridge `legal-ai-net`. Only `8501` is published;
  everything else reaches out, nothing reaches in.
- **Baked in:** Python deps, the 510-document seed corpus, and the
  all-MiniLM-L6-v2 weights — so the container needs no network at start-up.
- **Not baked in:** every API key. Injected per-environment via `env_file`.

---

## Slide 2 — Before and After

**Title:** From a Hand-Built VM to a Versioned Artifact

| | Milestone 2 — manual VM | Milestone 3 — container |
|---|---|---|
| Deploy steps | ~12 manual commands over SSH | `docker compose pull && up -d` |
| Time to deploy | 25–40 min | ~2 min (pull + start) |
| Python runtime | whatever `apt` gave us | pinned `python:3.12-slim`, identical |
| Dependencies | `pip install` resolved live, different each run | frozen in the image layer |
| 510 seed documents | `scp`'d by hand | shipped inside the image |
| Embedding model | downloaded from HF on first use | pre-baked, runs fully offline |
| Rollback | reinstall and hope | `TAG=v1` and restart |
| Reproducibility | "works on my machine" | same `sha256:` digest on both machines |

### The specific problem containerization solved for us

> **Our laptop and the VM had silently drifted apart.** The VM resolved a
> different transitive dependency set than our laptops did, so a feature that
> worked locally failed on the VM and we burned hours diffing `pip freeze`
> output over SSH. Nobody could say what was actually deployed, because the VM's
> state was the sum of every command anyone had ever typed into it.
>
> The image removes the guesswork. The dependency set is resolved **once**, at
> build time, and is then frozen into a layer identified by a digest. The VM no
> longer installs anything — it pulls a finished artifact. "What's running in
> production?" went from an investigation to reading one `sha256:` string.

### Supporting numbers

- Final image: **1.51 GB** on disk, **513 MB** to pull.
- **86 % smaller** than our naive first build, which measured 10.73 GB.
- Zero secrets in the image, verified by scanning all layers of the saved
  tarball — not just the running container.
