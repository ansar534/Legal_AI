# Milestone 3 — Containerization and Registry Deployment

Everything below is copy-pasteable. Replace the three placeholders once and the
rest follows:

| Placeholder | Meaning | Example |
|---|---|---|
| `<ACR_NAME>` | Azure Container Registry name (no domain) | `legalaiacr` |
| `<RG>` | Resource group holding the Milestone 2 VM | `legal-ai-rg` |
| `<VM_IP>` | Public IP of the Milestone 2 VM | `20.55.13.42` |

---

## 0. One-time local setup

```bash
cp .env.example .env
# edit .env — at minimum GROQ_API_KEY

# Point compose at your registry. Appended to the same .env.
echo "REGISTRY=<ACR_NAME>.azurecr.io" >> .env
echo "TAG=v1"                         >> .env
```

`.env` is in both `.gitignore` and `.dockerignore`, so it is never committed and
never enters the build context.

---

## 1. Build and run locally with Compose

```bash
docker compose up --build
```

Open <http://localhost:8501>. Exercise at least two features (Contract Q&A and
Audit/Compliance) so Chroma writes into the volume — that proves the volume
mount is live and not just declared.

Useful during the demo:

```bash
docker compose ps                      # health = healthy
docker compose logs -f app
docker volume ls --filter name=legal-ai   # the three persisted index stores
docker network inspect legal-ai-net       # the bridge the service sits on
docker image ls <ACR_NAME>.azurecr.io/legal-ai-hub   # final image size

# Show the indexes the container has written, per feature group
docker compose exec app du -sh /app/chromadb /app/vector_store /app/.chromadb
```

### A note on the three volumes

The app writes vector indexes to three separate roots, which is easy to miss:

| Path | Volume | Features |
|---|---|---|
| `/app/chromadb` (+ `uploads/`) | `legal-ai-chroma` | Contract Q&A, Policies, Audit, Contract Risk |
| `/app/vector_store` | `legal-ai-litigation` | Litigation Support |
| `/app/.chromadb` | `legal-ai-regulations` | Regulations Search (live) |

All three are pre-created in the image and owned by `appuser` (uid 10001). This
matters: `/app` is root-owned, so a non-root process cannot create directories
inside it, and a named volume mounted onto a path that does **not** exist in the
image is created owned by root. Missing either half produces
`PermissionError: [Errno 13] Permission denied: '/app/vector_store'`.

---

## 2. Push a versioned image to Azure Container Registry

```bash
# Create the registry once (skip if it already exists)
az acr create --resource-group <RG> --name <ACR_NAME> --sku Basic
az acr login --name <ACR_NAME>

# Tag with BOTH an immutable version and a moving pointer.
docker tag <ACR_NAME>.azurecr.io/legal-ai-hub:v1 <ACR_NAME>.azurecr.io/legal-ai-hub:latest

docker push <ACR_NAME>.azurecr.io/legal-ai-hub:v1
docker push <ACR_NAME>.azurecr.io/legal-ai-hub:latest
```

### Record the digest — this is the proof of a byte-for-byte identical artifact

```bash
docker image inspect <ACR_NAME>.azurecr.io/legal-ai-hub:v1 \
  --format '{{index .RepoDigests 0}}'
```

Write that `sha256:...` down. Show it again after pulling on the VM; the two
strings matching **is** the success criterion for this milestone. The tag `v1` is
a human label and could be moved — the digest cannot.

Registry-side view for the screenshot:

```bash
az acr repository show-tags --name <ACR_NAME> --repository legal-ai-hub --output table
az acr manifest list-metadata --registry <ACR_NAME> --name legal-ai-hub \
  --query "[].{digest:digest, tags:tags, size:imageSize}" --output table
```

Screenshot the Azure Portal page **Container registries → `<ACR_NAME>` →
Repositories → `legal-ai-hub`** with the `v1` tag and digest column visible.

---

## 3. Pull and run the same image on the Milestone 2 VM

```bash
ssh azureuser@<VM_IP>
```

### 3a. Install Docker Engine (one time, the last manual step this project needs)

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker
```

### 3b. Stop the Milestone 2 process so port 8501 is free

```bash
sudo systemctl stop legal-ai 2>/dev/null || pkill -f streamlit
sudo ss -ltnp | grep 8501   # expect no output
```

### 3c. Authenticate to ACR without copying credentials around

```bash
# Preferred: Azure AD, no long-lived password on the VM
az login --identity 2>/dev/null || az login
az acr login --name <ACR_NAME>

# Fallback if the Azure CLI is not on the VM: a pull-only scoped token.
# Run on your laptop:
#   az acr token create --registry <ACR_NAME> --name vm-pull \
#     --repository legal-ai-hub content/read --output json
# Then on the VM:
#   echo "<password>" | docker login <ACR_NAME>.azurecr.io -u vm-pull --password-stdin
```

### 3d. Pull by digest and run

```bash
mkdir -p ~/legal-ai && cd ~/legal-ai

# Only two files are needed on the VM — no source, no pip, no venv, no data copy.
curl -fsSLO https://raw.githubusercontent.com/<you>/Legal_AI/main/docker-compose.yml

cat > .env <<'EOF'
REGISTRY=<ACR_NAME>.azurecr.io
TAG=v1
GROQ_API_KEY=...
COURTLISTENER_API_KEY=...
APIFY_TOKEN=...
EOF
chmod 600 .env

docker compose pull
docker compose up -d --no-build
docker compose ps
```

### 3e. Prove it is the identical artifact

```bash
docker image inspect <ACR_NAME>.azurecr.io/legal-ai-hub:v1 \
  --format '{{index .RepoDigests 0}}'
```

Put this side by side with the digest from step 2. Then confirm the app answers
at the same URL as Milestone 2: `http://<VM_IP>:8501`.

### 3f. Confirm the secret is not in the image, only in the container

```bash
# Nothing in any layer:
docker history --no-trunc <ACR_NAME>.azurecr.io/legal-ai-hub:v1 | grep -i -E "groq|api_key|token"   # no matches
docker image inspect <ACR_NAME>.azurecr.io/legal-ai-hub:v1 --format '{{json .Config.Env}}'          # no secrets
docker run --rm --entrypoint sh <ACR_NAME>.azurecr.io/legal-ai-hub:v1 -c 'ls -la /app; cat /app/.env'
#   -> ".env: No such file or directory"

# But present in the running container, injected by compose:
docker compose exec app printenv GROQ_API_KEY   # value is there
```

---

## 4. Rolling out a new version later

```bash
# laptop
docker compose build
docker tag <ACR_NAME>.azurecr.io/legal-ai-hub:v1 <ACR_NAME>.azurecr.io/legal-ai-hub:v2
docker push <ACR_NAME>.azurecr.io/legal-ai-hub:v2

# VM
sed -i 's/^TAG=v1/TAG=v2/' .env
docker compose pull && docker compose up -d --no-build
```

Rollback is `TAG=v1` and the same two commands. The `legal-ai-chroma` volume is
untouched, so indexes survive the swap.

---

## 5. Budget guardrails (Azure Cost Management)

The rubric asks for alerts at **10% / 25% / 50%** of the monthly budget; the demo
script also mentions 20/50/100. Configure all five thresholds so either reading
is satisfied — Azure allows multiple alert conditions on one budget.

```bash
az consumption budget create \
  --budget-name legal-ai-monthly \
  --amount 50 \
  --category cost \
  --time-grain Monthly \
  --start-date $(date -u +%Y-%m-01) \
  --end-date   $(date -u -d '+1 year' +%Y-%m-01) \
  --resource-group <RG>
```

Then in **Portal → Cost Management → Budgets → `legal-ai-monthly` → Manage alert
conditions**, add actual-cost alerts at 10, 20, 25, 50 and 100 percent, each
emailing the whole team. Scope the budget at the **subscription** level so the
ACR, the VM, its disk, the public IP and egress are all covered — a
resource-group-scoped budget would silently miss anything created outside it.

Evidence to capture for the video:

- **Cost Management → Cost analysis**, grouped by Service, month-to-date.
- The budget detail blade showing all alert thresholds and recipients.
- **Cost analysis → Budget: legal-ai-monthly** showing spend against the bar.

Cost-control actions actually taken:

- ACR on the **Basic** SKU (~$0.17/day, 10 GB included) rather than Standard.
- `az acr run --cmd 'acr purge ...'` scheduled to delete untagged manifests
  weekly so failed builds do not accumulate storage charges.
- VM is a single B-series burstable instance, deallocated when not demoing
  (`az vm deallocate` stops compute billing; the disk still bills).
- CPU-only image (see analysis) removed the need for any GPU SKU entirely.
