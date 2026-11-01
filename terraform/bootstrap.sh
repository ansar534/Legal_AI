#!/usr/bin/env bash
# One-time setup before `terraform init` can use the azurerm backend in
# backend.tf. Run once; safe to re-run (idempotent).
set -euo pipefail

az storage container create \
  --account-name stlegalaiuploads \
  --name tfstate \
  --auth-mode login \
  --public-access off
