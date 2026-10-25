#!/usr/bin/env bash
# One-time setup so GitHub Actions can deploy the backend (.github/workflows/deploy-backend.yml).
#
#   ./deploy/github-setup.sh          (from backend/, needs gcloud as a project Owner and `gh`)
#
# What it does, all idempotent:
#  1. Keyless sign-in (Workload Identity Federation): Google trusts GitHub's OIDC tokens, but
#     only from the main branch of virajchogle/minedtv. No key file is ever created.
#  2. A deploy-only service account, github-deployer, with Cloud Run admin + Artifact Registry
#     write, and permission to deploy as the compute account Cloud Run already runs as.
#  3. A Cloud Run job, minedtv-migrate, that runs `alembic upgrade head` with prod's settings
#     (read once from .env.prod here, then stored in Cloud Run). The workflow runs it before
#     every API deploy, so code never goes out ahead of its database changes.
#  4. GitHub repo variables (not secrets; none of these values are sensitive) for the workflow.
set -euo pipefail
cd "$(dirname "$0")/.."

P="${PROJECT_ID:-minedtv-78e0}"
REGION="${REGION:-us-east1}"
GH_REPO="${GH_REPO:-virajchogle/minedtv}"
N="$(gcloud projects describe "$P" --format='value(projectNumber)')"
SA="github-deployer@$P.iam.gserviceaccount.com"
CSA="$N-compute@developer.gserviceaccount.com"
POOL="github"
PROVIDER="minedtv"

gcloud services enable iamcredentials.googleapis.com sts.googleapis.com --project "$P"

gcloud iam service-accounts describe "$SA" --project "$P" >/dev/null 2>&1 ||
  gcloud iam service-accounts create github-deployer --project "$P" \
    --display-name "GitHub Actions deployer ($GH_REPO main)"
for role in roles/run.admin roles/artifactregistry.writer; do
  gcloud projects add-iam-policy-binding "$P" --member "serviceAccount:$SA" --role "$role" \
    --condition=None --quiet >/dev/null
done
gcloud iam service-accounts add-iam-policy-binding "$CSA" --project "$P" \
  --member "serviceAccount:$SA" --role roles/iam.serviceAccountUser --quiet >/dev/null

gcloud iam workload-identity-pools describe "$POOL" --location global --project "$P" >/dev/null 2>&1 ||
  gcloud iam workload-identity-pools create "$POOL" --location global --project "$P" --display-name "GitHub Actions"
gcloud iam workload-identity-pools providers describe "$PROVIDER" --location global \
  --workload-identity-pool "$POOL" --project "$P" >/dev/null 2>&1 ||
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" --location global \
    --workload-identity-pool "$POOL" --project "$P" \
    --issuer-uri https://token.actions.githubusercontent.com \
    --attribute-mapping google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref \
    --attribute-condition "assertion.repository=='$GH_REPO' && assertion.ref=='refs/heads/main'"
gcloud iam service-accounts add-iam-policy-binding "$SA" --project "$P" --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/$N/locations/global/workloadIdentityPools/$POOL/attribute.repository/$GH_REPO" \
  --quiet >/dev/null

# Migration job: the worker image already has alembic and the migrations.
ENV_YAML="$(mktemp)"
python3 - .env.prod > "$ENV_YAML" <<'PY'
import json, sys
for line in open(sys.argv[1]):
    line = line.split(" #")[0].strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        if v.strip():
            print(f"{k.strip()}: {json.dumps(v.strip())}")
PY
gcloud run jobs deploy minedtv-migrate --project "$P" --region "$REGION" \
  --image "$REGION-docker.pkg.dev/$P/minedtv/worker:latest" \
  --env-vars-file "$ENV_YAML" --memory 512Mi --cpu 1 --task-timeout 600 --max-retries 0 \
  --command alembic --args=upgrade,head
rm -f "$ENV_YAML"

gh variable set GCP_PROJECT_ID --repo "$GH_REPO" --body "$P"
gh variable set GCP_REGION --repo "$GH_REPO" --body "$REGION"
gh variable set GCP_DEPLOY_SA --repo "$GH_REPO" --body "$SA"
gh variable set GCP_WIF_PROVIDER --repo "$GH_REPO" \
  --body "projects/$N/locations/global/workloadIdentityPools/$POOL/providers/$PROVIDER"

echo "Done. GitHub Actions can now deploy the backend from main."
