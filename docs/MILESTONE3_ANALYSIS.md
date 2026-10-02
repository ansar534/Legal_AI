# Milestone 3 — Written Analysis

Every number below was measured on the actual build, not estimated. Commands to
reproduce each one are given so they can be re-run during the demo.

## Final image size, and what we did to reduce it

The final image `legal-ai-hub:v1` is **1.51 GB** on disk and **513 MB** as a
transferable artifact — that second figure is what the registry stores and what
the VM actually downloads.

```bash
docker image ls legalai.azurecr.io/legal-ai-hub           # 539 MB content size
docker save legalai.azurecr.io/legal-ai-hub:v1 | wc -c    # 513 MB
docker run --rm --user 0 --entrypoint sh legalai.azurecr.io/legal-ai-hub:v1 \
  -c "du -sm --exclude=/proc --exclude=/sys /"            # 1511 MB
```

A naive first attempt — `FROM python:3.12`, `COPY . .`, `pip install -r
requirements.txt` — measured **10.73 GB**. We cut **86 %** of that, in four steps:

| Change | Saved | Why it was safe |
|---|---:|---|
| CPU-only PyTorch wheel from `download.pytorch.org/whl/cpu` | **4.85 GB** | The default PyPI `torch` drags in 3.20 GB of `nvidia/*` CUDA libraries plus 897 MB of `triton`. `src/core/embeddings.py` pins `device="cpu"`, so none of it could ever execute. |
| `python:3.12-slim` instead of `python:3.12` | **~0.85 GB** | The full image carries a GCC toolchain, Git and build headers. Those live in the builder stage now; the runtime needs exactly one OS library, `libgomp1`, for PyTorch's OpenMP calls. |
| Multi-stage build; runtime copies only `/opt/venv` | **~0.35 GB** | `build-essential`, pip's wheel cache and downloaded tarballs stay in the discarded builder stage. |
| Pruning the venv (details below) | **0.88 GB** | Each removal is covered by a build-time smoke test. |

The venv pruning, from 2124 MB to 1240 MB:

- `torch/include` (63 MB) and `torch/test` (85 MB) — C++ headers and upstream's
  own test suite, needed to compile extensions, not to run inference.
- Test runner binaries in `torch/bin` (~52 MB) and `lib*test*.so` — but
  `torch_shm_manager` is kept, because `torch/__init__.py` requires it at import.
- `strip --strip-unneeded` on every `.so`, which alone took `libtorch_cpu.so`
  from 418 MB down to roughly half.
- Bundled `tests/` directories inside installed wheels (pandas, scipy, sympy).
- `pip`, `setuptools` and `wheel`, which a running container has no use for and
  which only widen the attack surface.

Two things are deliberately **added** to the image rather than trimmed out:

- The **all-MiniLM-L6-v2 weights** (88 MB), pre-downloaded at build time. With
  `HF_HUB_OFFLINE=1` the container never contacts huggingface.co, so a cold start
  on the VM behaves identically to one on the laptop. We fetch only the PyTorch
  weights and delete the ONNX, OpenVINO, TensorFlow and Flax copies of the same
  model that the repo also ships.
- The **510-document seed corpus** (59 MB). It is read-only at run time, so
  shipping it removes the manual `scp` step that Milestone 2 required.

### The pruning is verified, not assumed

Aggressive deletion inside `site-packages` is the kind of optimization that
breaks a month later on a code path nobody tested. So the `model` stage ends with
a smoke test that imports chromadb, langchain-chroma and langchain-groq and
computes a real embedding, with `HF_HUB_OFFLINE=1` set:

```
#16 34.59 smoke ok: embedding dim 384
```

If a prune removes something the application needs, **the build fails** instead
of the container. This caught two real mistakes during development: deleting
`torch/testing` (a genuine runtime module that `transformers` imports, despite
the name) and deleting all of `torch/bin` (which holds `torch_shm_manager`).

## What we excluded via `.dockerignore`, and why each exclusion matters

Without `.dockerignore`, Docker transfers **121.29 MB** of context to the daemon.
Reproduce with `docker build --progress=plain` and read `transferring context`.

| Excluded | Why it matters |
|---|---|
| `.env`, `.env.*`, `*.pem`, `*.key`, `.ssh/`, `.azure/` | The security control. These are the files that actually hold credentials. No exception is made for `.env.example` — see the incident note below. |
| `.git/` (90.3 MB) | The single largest item, and 60 × larger than the source it tracks. It is also a history: a key committed once and removed later still sits in `.git`, so copying it in can reintroduce a secret that was already cleaned up. |
| `chromadb/`, `.chromadb/`, `vector_store/` | Generated vector indexes — all three roots the app writes to. These belong on volumes. Baking them in would freeze stale embeddings into every deployment and make the image grow without bound as the corpus is re-indexed. |
| `venv/`, `.venv/` | Host virtualenvs contain Windows/macOS binaries that cannot execute on Linux, and would shadow the image's own `/opt/venv`. Largest accidental-bloat risk in the context. |
| `__pycache__/`, `*.pyc` | Bytecode compiled against a different interpreter path. Stale `.pyc` files can be loaded in preference to the `.py` beside them. |
| `*.log` | Build and run logs change on every build, which needlessly invalidates the `COPY` layer cache, and they can carry stack traces, hostnames and registry URLs. |
| `docs/`, `*.md`, `Dockerfile*`, `docker-compose*.yml` | Not read by the running process. Keeping the recipe out of the artifact also avoids leaking internal registry names and host paths. |
| `.vscode/`, `.idea/`, `.cursor/`, `.DS_Store` | Editor state. Pure noise, but it changes constantly and so breaks layer caching. |

## Confirmation that no secrets are baked into the image

**Verified clean.** `scripts/verify-no-secrets.sh` is committed and reproducible:

```
$ ./scripts/verify-no-secrets.sh legalai.azurecr.io/legal-ai-hub:v1
==> Saving legalai.azurecr.io/legal-ai-hub:v1
    513 MB
==> Scanning layers for values from .env
    PASS  value of GROQ_API_KEY
    PASS  value of APIFY_TOKEN
    PASS  value of REGULATIONS_API_KEY
    PASS  value of COURTLISTENER_API_KEY
==> Scanning layers for secret-bearing files and provider key prefixes
    PASS  marker 'GROQ_API_KEY='      PASS  marker 'gsk_'
    PASS  marker 'APIFY_TOKEN='       PASS  marker 'apify_api_'
    PASS  marker 'COURTLISTENER_API_KEY='
    PASS  marker 'BEGIN RSA PRIVATE KEY'
    PASS  marker 'BEGIN OPENSSH PRIVATE KEY'
==> Image metadata
    PASS  Config.Env holds no credential-shaped variables
    PASS  build history holds no credentials

RESULT: clean - no credential material in legalai.azurecr.io/legal-ai-hub:v1
```

How the verification works, and why each part is necessary:

1. **Layer-level scan, not container-level.** The script runs `docker save` and
   greps all 513 MB of the resulting tarball for the literal values in `.env`.
   This is the part that matters: a secret added in one layer and `rm`'d in a
   later one is invisible to `docker run` and to `ls`, but is still sitting in
   the earlier layer, fully recoverable by anyone who pulls the image. Only
   scanning the saved layers catches it.
2. **`Config.Env` check**, matching variable *names* with non-empty values. An
   earlier substring version of this check false-positived on the base image's
   `GPG_KEY` (Python's public release-signing key) and on
   `TOKENIZERS_PARALLELISM`, neither of which is a credential.
3. **`docker history --no-trunc`**, which catches a key passed as a build
   argument or inlined into a `RUN`.
4. **Positive control** — proving the app still gets its keys, just at run time:

```bash
# absent from the image
docker run --rm --entrypoint sh IMAGE -c 'echo "[${GROQ_API_KEY:-<unset>}]"'
#   -> [<unset>]

# present in the running container, injected by compose from .env
docker compose exec app python -c \
  "import os;k=os.environ['GROQ_API_KEY'];print(len(k),k[:4])"
#   -> 56 gsk_

# and genuinely functional
docker compose exec app python -c \
  "from src.core.llm import get_llm; print(get_llm().invoke('Reply with exactly: container ok').content)"
#   -> container ok
```

The architectural reason this holds: the Dockerfile's only `COPY` statements name
`src/`, `data/` and `streamlit_app.py` explicitly. There is no `COPY . .`, so
secrets cannot enter the image by being forgotten — they can only enter if
someone adds them on purpose.

### Incident found and remediated during this work

While containerizing we found that **`.env.example` in the working tree had been
edited to contain four live API keys** (Groq, Apify, Regulations.gov,
CourtListener) instead of the empty placeholders it ships with. It was caught
because `git status` flagged the file as modified.

Actions taken:

- `git log --all -S <each key>` returned nothing, confirming the keys were
  **never committed** and never reached GitHub. No history rewrite was required.
- The keys were moved into `.env`, which is listed in both `.gitignore` and
  `.dockerignore`, and `.env.example` was restored to placeholders.
- A throwaway baseline image built during size measurement *did* contain the
  keys, via its `COPY . .`. It was confirmed to be affected, deleted with
  `docker rmi -f`, and was never tagged for or pushed to any registry.
- Our initial `.dockerignore` had a `!.env.example` re-inclusion, on the
  assumption that a file named "example" is safe. **That line was removed.** It
  is precisely how real keys ship to production: the template is the file
  developers edit in place, and nothing in the image needs it.

**Recommendation: rotate all four keys before the demo.** They sat in plaintext
in a working tree inside a repo directory. Rotation is cheap; assuming no
exposure is not.

## Cost-control actions

- Monthly Azure budget `legal-ai-monthly` scoped at the **subscription** level,
  so the registry, VM, disk, public IP and egress are all covered. A
  resource-group-scoped budget silently misses anything created outside it.
- Alert thresholds at **10 %, 20 %, 25 %, 50 % and 100 %** of actual spend,
  emailing the whole team, covering both threshold sets named in the brief.
- Registry on the **Basic** SKU (10 GB included) rather than Standard. At 513 MB
  per version we can hold ~19 tagged versions inside the included quota.
- `acr purge` scheduled weekly to delete untagged manifests, so failed and
  superseded builds do not accumulate storage charges.
- The CPU-only image removed any reason to consider a GPU VM SKU — the single
  largest cost decision in the project.
- VM `az vm deallocate` when not demoing, which stops compute billing.
- Compose-based deploys made the VM disposable, so we can run a smaller B-series
  instance and rebuild it in two minutes instead of over-provisioning a
  hand-configured machine we are afraid to lose.
