# syntax=docker/dockerfile:1.7

# ---------------------------------------------------------------------------
# Stage 1 — builder: compile wheels into a self-contained virtualenv.
# Build toolchains, pip caches and source tarballs stay in this stage and are
# never copied forward.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install the CPU-only PyTorch build before anything else. sentence-transformers
# would otherwise pull the default CUDA wheel, which drags in ~2.5 GB of NVIDIA
# runtime libraries this app can never use (embeddings are pinned to device=cpu).
RUN pip install --no-cache-dir \
      --index-url https://download.pytorch.org/whl/cpu \
      torch

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# ---------------------------------------------------------------------------
# Stage 2 — model: pre-download the embedding model, then prune the venv.
# Baking the weights in means the container has no network dependency on
# huggingface.co at start-up, so laptop and VM behave identically even on a
# cold start or a locked-down network.
# ---------------------------------------------------------------------------
FROM builder AS model

ENV PATH="/opt/venv/bin:$PATH" \
    HF_HOME=/opt/hf-cache \
    HF_HUB_DISABLE_TELEMETRY=1

# Fetch only the PyTorch weights. The repo also ships ONNX, OpenVINO, TensorFlow
# and Flax copies of the same model that this app will never load.
RUN python -c "\
from sentence_transformers import SentenceTransformer; \
SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')" \
 && find /opt/hf-cache \( -name '*.onnx' -o -name '*.msgpack' -o -name '*.h5' \) -delete \
 && find /opt/hf-cache -type d -name 'openvino*' -prune -exec rm -rf {} +

ENV VENV_LIB=/opt/venv/lib/python3.12/site-packages

# Strip artefacts that exist to build or test packages, not to run them.
RUN set -eux; \
    # C++/CUDA headers for compiling torch extensions at run time — we never do.
    rm -rf "$VENV_LIB/torch/include" "$VENV_LIB/torch/utils/benchmark"; \
    # torch/test is upstream's own C++ test suite; torch/bin holds its compiled
    # test runners alongside torch_shm_manager, which torch/__init__.py requires
    # at import time — so that one binary stays.
    rm -rf "$VENV_LIB/torch/test"; \
    find "$VENV_LIB/torch/bin" -type f ! -name 'torch_shm_manager' -delete; \
    # Vendored static libs and test-only shared objects used when linking new
    # extensions, plus debug symbols in the 418 MB libtorch_cpu.so.
    find "$VENV_LIB/torch/lib" -name '*.a' -delete; \
    find "$VENV_LIB/torch/lib" -name 'lib*test*.so' -delete; \
    find "$VENV_LIB" -name '*.so' -exec strip --strip-unneeded {} + 2>/dev/null || true; \
    # Bundled test suites shipped inside installed wheels. torch is excluded:
    # torch.testing is a real runtime module that transformers imports.
    find "$VENV_LIB" -type d -name 'tests' -not -path "*/torch/*" -prune -exec rm -rf {} +; \
    # Host-side bytecode and the installer itself.
    find "$VENV_LIB" -type d -name '__pycache__' -prune -exec rm -rf {} +; \
    pip uninstall -y pip setuptools wheel 2>/dev/null || true; \
    rm -rf "$VENV_LIB/pip" "$VENV_LIB/setuptools" "$VENV_LIB/pkg_resources" \
           "$VENV_LIB"/pip-*.dist-info "$VENV_LIB"/setuptools-*.dist-info

# Gate the pruning behind a real smoke test: if anything above removed something
# the application needs, the BUILD fails here rather than the container at 3am.
# HF_HUB_OFFLINE also proves the baked weights are genuinely self-sufficient.
RUN HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -c "\
import chromadb; \
from langchain_chroma import Chroma; \
from langchain_groq import ChatGroq; \
from langchain_huggingface import HuggingFaceEmbeddings; \
v = HuggingFaceEmbeddings( \
      model_name='sentence-transformers/all-MiniLM-L6-v2', \
      model_kwargs={'device': 'cpu'}, \
      encode_kwargs={'normalize_embeddings': True}, \
    ).embed_query('indemnification clause'); \
assert len(v) == 384, len(v); \
print('smoke ok: embedding dim', len(v))"


# ---------------------------------------------------------------------------
# Stage 3 — runtime: slim base + venv + weights + application source.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="Legal AI Hub" \
      org.opencontainers.image.description="Streamlit RAG workbench for legal document analysis" \
      org.opencontainers.image.source="https://github.com/ansar/Legal_AI" \
      org.opencontainers.image.licenses="MIT"

# libgomp1 is the OpenMP runtime that the CPU PyTorch wheel links against.
# It is the only OS-level dependency the application has at run time.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/opt/hf-cache \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    TOKENIZERS_PARALLELISM=false \
    HOME=/home/appuser \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Both come from the `model` stage: it holds the pruned, smoke-tested venv.
# Copying the venv from `builder` instead would silently discard every
# size reduction made above.
COPY --from=model /opt/venv /opt/venv
COPY --from=model /opt/hf-cache /opt/hf-cache

WORKDIR /app

# Application source and the seed corpus. data/ is read-only at run time, so it
# ships in the image — the VM no longer needs a manual scp of 546 documents.
COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser data/ ./data/
COPY --chown=appuser:appuser streamlit_app.py ./

# The app writes vector indexes to three separate roots under /app:
#   chromadb/      - contract Q&A, policies, audit, contract risk (+ uploads/)
#   vector_store/  - litigation support (src/features/litigation/page.py)
#   .chromadb/     - live regulations search (src/features/regulations_rag)
# All three are pre-created and chowned here for two reasons: /app itself is
# root-owned so appuser cannot mkdir inside it, and a named volume mounted onto
# a path that exists in the image inherits that path's ownership rather than
# defaulting to root.
RUN mkdir -p /app/chromadb/uploads /app/vector_store /app/.chromadb \
 && chown -R appuser:appuser /app/chromadb /app/vector_store /app/.chromadb

USER appuser

EXPOSE 8501

VOLUME ["/app/chromadb", "/app/vector_store", "/app/.chromadb"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD python -c "\
import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4).status == 200 else 1)"

CMD ["streamlit", "run", "streamlit_app.py"]
