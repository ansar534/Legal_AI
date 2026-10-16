"""Centralised path / secret configuration for the whole app."""

from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path


# Directory layout (resolved at import, never hard-coded again elsewhere)
SRC_DIR: Path = Path(__file__).resolve().parent.parent
PROJECT_ROOT: Path = SRC_DIR.parent

DATA_DIR: Path = PROJECT_ROOT / "data"
MIGRATIONS_DIR: Path = PROJECT_ROOT / "migrations"

# Parsers need a real file path, so uploads are copied here after they are
# stored in Blob Storage. Disposable: losing it only costs a re-download.
SCRATCH_DIR: Path = Path(tempfile.gettempdir()) / "legal-ai-hub"


# Key Vault secret name -> environment variable the code reads.
_SECRETS = {
    "groq-api-key": "GROQ_API_KEY",
    "courtlistener-api-key": "COURTLISTENER_API_KEY",
    "apify-token": "APIFY_TOKEN",
    "regulations-api-key": "REGULATIONS_API_KEY",
    "postgres-password": "POSTGRES_PASSWORD",
}

_loaded = False
_load_lock = threading.Lock()


def load_env() -> None:
    """
    Copy secrets from Azure Key Vault into this process's environment, once.

    The vault is read with the VM's managed identity, so no credential is
    needed to reach it. Without AZURE_KEY_VAULT_URL nothing is fetched and
    secrets must already be in the environment.
    """
    global _loaded
    if _loaded:
        return
    with _load_lock:
        if _loaded:
            return
        vault_url = os.getenv("AZURE_KEY_VAULT_URL")
        if vault_url:
            from azure.core.exceptions import ResourceNotFoundError
            from azure.keyvault.secrets import SecretClient

            from src.core.identity import get_credential

            client = SecretClient(vault_url=vault_url, credential=get_credential())
            for secret_name, env_name in _SECRETS.items():
                if os.getenv(env_name):
                    continue
                try:
                    value = client.get_secret(secret_name).value
                except ResourceNotFoundError:
                    continue
                if value:
                    os.environ[env_name] = value
        _loaded = True


def get_required_env(key: str) -> str:
    """Fetch an env var or raise a clear error suitable for surfacing in the UI."""
    load_env()
    value = os.getenv(key)
    if not value:
        secret = next((s for s, e in _SECRETS.items() if e == key), None)
        where = f"Key Vault secret `{secret}`" if secret else "the container environment"
        raise RuntimeError(f"Missing required setting {key}. Set it in {where}.")
    return value


def ensure_dirs() -> None:
    """Make sure the scratch directory exists."""
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
