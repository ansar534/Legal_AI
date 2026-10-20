"""The app's Azure identity: the user-assigned managed identity id-legalai-app."""

from __future__ import annotations

import os
from functools import lru_cache

from azure.core.credentials import TokenCredential
from azure.identity import ManagedIdentityCredential, WorkloadIdentityCredential


@lru_cache(maxsize=1)
def get_credential() -> TokenCredential:
    """
    Token source for Key Vault and Blob Storage. There is no key file or
    connection string anywhere.

    On AKS the workload identity webhook mounts a service-account token and
    sets AZURE_FEDERATED_TOKEN_FILE, AZURE_CLIENT_ID and AZURE_TENANT_ID; that
    token is exchanged for an Entra ID token for the managed identity. On a VM
    tokens come from the instance metadata endpoint instead, and
    AZURE_CLIENT_ID picks the user-assigned identity.
    """
    if os.getenv("AZURE_FEDERATED_TOKEN_FILE"):
        return WorkloadIdentityCredential()
    client_id = os.getenv("AZURE_CLIENT_ID")
    if client_id:
        return ManagedIdentityCredential(client_id=client_id)
    return ManagedIdentityCredential()
