#!/usr/bin/env bash
# Prove that an image contains no credential material.
#
#   ./scripts/verify-no-secrets.sh legalai.azurecr.io/legal-ai-hub:v1
#
# Reads the real values out of the local .env and searches for each one across
# every byte of the saved image: all layers, including files that a later layer
# deletes. A `rm` in a Dockerfile hides a secret from `docker run`; it does not
# remove it from the layer that added it. Only scanning the saved tarball
# catches that class of mistake.
#
# No secret value is ever printed; only match counts.
set -euo pipefail

IMAGE="${1:?usage: verify-no-secrets.sh <image:tag> [env-file]}"
ENV_FILE="${2:-.env}"

# Kept in the working directory rather than /tmp: the Docker CLI resolves this
# path itself, and on Windows it cannot see a Git Bash or WSL /tmp.
TAR=".imgscan.$$.tar"
trap 'rm -f "$TAR"' EXIT

echo "==> Saving $IMAGE"
docker save "$IMAGE" -o "$TAR"
printf '    %s MB\n' "$(( $(wc -c < "$TAR") / 1024 / 1024 ))"

fail=0

check() {
  local label="$1" needle="$2" n
  n=$(grep -c -a -- "$needle" "$TAR" || true)
  if [ "$n" -eq 0 ]; then
    printf '    PASS  %s\n' "$label"
  else
    printf '    FAIL  %s  (%s matching blocks)\n' "$label" "$n"
    fail=1
  fi
}

echo "==> Scanning layers for values from $ENV_FILE"
if [ -f "$ENV_FILE" ]; then
  while IFS='=' read -r key value; do
    case "$key" in ''|\#*) continue ;; esac
    # Non-secret build coordinates legitimately appear in the image reference.
    case "$key" in REGISTRY|TAG|HOST_PORT) continue ;; esac
    # Strip the quotes and stray spaces a hand-edited .env tends to carry.
    value="$(printf '%s' "$value" | tr -d "\"' ")"
    [ "${#value}" -ge 12 ] || continue
    check "value of $key" "$value"
  done < "$ENV_FILE"
else
  echo "    (no $ENV_FILE found; skipping value scan)"
fi

echo "==> Scanning layers for secret-bearing files and provider key prefixes"
for needle in "GROQ_API_KEY=" "APIFY_TOKEN=" "COURTLISTENER_API_KEY=" \
              "gsk_" "apify_api_" "BEGIN RSA PRIVATE KEY" \
              "BEGIN OPENSSH PRIVATE KEY"; do
  check "marker '$needle'" "$needle"
done

echo "==> Image metadata"
# Match on variable NAME with a non-empty value, not on substrings. A substring
# search false-positives on the base image's public GPG_KEY and on
# TOKENIZERS_PARALLELISM, neither of which is a credential.
baked_env="$(docker image inspect "$IMAGE" \
  --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep -iE '^[A-Z0-9_]*(API_KEY|_TOKEN|_SECRET|SECRET_|PASSWORD|CREDENTIAL)[A-Z0-9_]*=.+' || true)"
if [ -n "$baked_env" ]; then
  echo "    FAIL  Config.Env bakes in a credential-shaped variable:"
  printf '%s\n' "$baked_env" | sed 's/=.*/=<value present>/; s/^/          /'
  fail=1
else
  echo "    PASS  Config.Env holds no credential-shaped variables"
fi

if docker history --no-trunc "$IMAGE" \
   | grep -qiE 'gsk_|apify_api_|(API_KEY|TOKEN|PASSWORD)=[^ "]'; then
  echo "    FAIL  build history mentions a credential"
  fail=1
else
  echo "    PASS  build history holds no credentials"
fi

echo
if [ "$fail" -eq 0 ]; then
  echo "RESULT: clean - no credential material in $IMAGE"
else
  echo "RESULT: SECRETS DETECTED in $IMAGE - do not push"
fi
exit "$fail"
