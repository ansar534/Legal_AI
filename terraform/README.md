# Terraform — Legal AI Hub cloud infrastructure

Covers every cloud resource the app depends on: resource group, networking,
managed identity + role assignments, Key Vault, Storage, ACR, the Postgres
Flexible Server, the AKS cluster (with Container Insights enabled), the
Milestone 6 monitoring stack (Log Analytics, the 5xx log alert, action group,
dashboard workbook), and the GitHub Actions OIDC managed identity
(`id-legalai-github` with a federated credential for `main`).

## One-time setup

```bash
az login
./bootstrap.sh                 # creates the tfstate blob container once
terraform init
export TF_VAR_postgres_admin_password="$(az keyvault secret show --vault-name kv-legalai-m4 --name postgres-password --query value -o tsv)"
./import.sh                    # imports every pre-existing resource
terraform plan                 # should converge to "no changes" after a
                                # couple of fixup passes on individual resources
```

## What Terraform does NOT manage, and why

- **Kubernetes objects inside AKS** (`../k8s/*.yaml`: Deployment, Service,
  Ingress, HPA, PDB, Traefik, cert-manager's ClusterIssuer). Terraform owns
  the cluster; `kubectl apply -k ../k8s/` (now wired into the CI/CD pipeline)
  owns what runs inside it. This is the standard split between cloud IaC and
  in-cluster manifests.
- **`vm-legalai` and its public IP / NIC / OS disk / NSG / SSH key** — the
  Milestone 4 VM, already stopped (`deallocated`) and superseded by AKS in
  Milestone 5. Not imported; left as dead resources rather than deleted
  mid-course. `rg-legalai-vnet` (a second, unused VNet) is the same leftover
  and is likewise not imported — only `vnet-northcentralus-1`, which AKS and
  Postgres actually use, is.
- **AKS's own auto-created identities and their role assignments**: the
  kubelet identity's `AcrPull` on the registry, and the cluster's
  system-assigned identity's `Network Contributor` / `Contributor` roles on
  its own subnet and node resource group. These are created and maintained
  by the AKS resource provider itself as a side effect of
  `azurerm_kubernetes_cluster`, not something a Terraform run should also
  declare ownership of.
- **Secret values** (Groq/CourtListener/Apify keys, the Postgres password's
  plaintext). Only the Key Vault container and the RBAC role that lets the
  app's managed identity *read* secrets are managed; secret values stay in
  Key Vault only. The one exception, the Postgres admin password, must be
  supplied to `azurerm_postgresql_flexible_server` at all — it is passed as
  a sensitive variable sourced from Key Vault at apply time, never written to
  a committed `.tfvars` file.
- **State itself**: `*.tfstate` and `.terraform/` are gitignored. State lives
  only in the private `tfstate` blob container.
