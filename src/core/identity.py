"""The app's Azure identity: the managed identity attached to the VM."""

from __future__ import annotations

import os
from functools import lru_cache

from azure.identity import ManagedIdentityCredential


@lru_cache(maxsize=1)
def get_credential() -> ManagedIdentityCredential:
    """
    Token source for Key Vault and Blob Storage.

    Tokens come from the VM's instance metadata endpoint, so there is no key
    file or connection string anywhere. AZURE_CLIENT_ID picks the
    user-assigned identity when the VM has more than one.
    """
    client_id = os.getenv("AZURE_CLIENT_ID")
    if client_id:
        return ManagedIdentityCredential(client_id=client_id)
    return ManagedIdentityCredential()
