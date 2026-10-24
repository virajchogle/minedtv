#!/usr/bin/env bash
# Deploy the API (Cloud Run service) and worker (Cloud Run Job, run every minute by Cloud Scheduler).
#
#   PROJECT_ID=my-project ./deploy/cloudrun.sh            # build + deploy everything
#   PROJECT_ID=my-project SKIP_BUILD=1 ./deploy/cloudrun.sh
#   PROJECT_ID=my-project BUILD=cloud ./deploy/cloudrun.sh   # build with Cloud Build instead of local buildx
#
# Reads settings from .env.prod (same keys as .env.example).
set -euo pipefail
cd "$(dirname "$0")/.."

: "${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-us-east1}"
REPO="$REGION-docker.pkg.dev/$PROJECT_ID/minedtv"
ENV_FILE="${ENV_FILE:-.env.prod}"
[[ -f "$ENV_FILE" ]] || { echo "missing $ENV_FILE (copy .env.example)"; exit 1; }

# .env -> YAML for --env-vars-file (skips blanks and comments).
ENV_YAML="$(mktemp)"
python3 - "$ENV_FILE" > "$ENV_YAML" <<'PY'
import json, sys
for line in open(sys.argv[1]):
    line = line.split(" #")[0].strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        if v.strip():
            print(f"{k.strip()}: {json.dumps(v.strip())}")
PY

gcloud config set project "$PROJECT_ID" >/dev/null
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudscheduler.googleapis.com
gcloud artifacts repositories describe minedtv --location "$REGION" >/dev/null 2>&1 ||
  gcloud artifacts repositories create minedtv --repository-format=docker --location "$REGION"

if [[ -z "${SKIP_BUILD:-}" ]]; then
  if [[ "${BUILD:-local}" == "cloud" ]]; then
    gcloud builds submit --config deploy/cloudbuild.yaml --substitutions "_REPO=$REPO" .
  else
    # Local cross-build (Cloud Run needs linux/amd64). Needs docker buildx
    # (`brew install docker-buildx` if `docker buildx` is missing).
    BX="$(command -v docker-buildx || echo /opt/homebrew/lib/docker/cli-plugins/docker-buildx)"
    [[ -x "$BX" ]] || BX="docker buildx"
    gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet
    $BX build --platform linux/amd64 -f Dockerfile.api -t "$REPO/api:latest" --push .
    $BX build --platform linux/amd64 -f Dockerfile.worker -t "$REPO/worker:latest" --push .
  fi
fi

# API: scales to zero; free tier covers hackathon traffic.
gcloud run deploy minedtv-api \
  --image "$REPO/api:latest" --region "$REGION" --allow-unauthenticated \
  --env-vars-file "$ENV_YAML" --memory 512Mi --cpu 1 --min-instances 0 --max-instances 3 --concurrency 80

# Worker: a job that drains the queue and exits. Billed only while it runs.
gcloud run jobs deploy minedtv-worker \
  --image "$REPO/worker:latest" --region "$REGION" \
  --env-vars-file "$ENV_YAML" --memory 4Gi --cpu 2 --task-timeout 3600 --max-retries 0 \
  --command python --args=-m,app.worker,--burst

# Kick the worker every minute. Each run exits in seconds when the queue is empty.
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
SA="$PROJECT_NUMBER-compute@developer.gserviceaccount.com"
gcloud run jobs add-iam-policy-binding minedtv-worker --region "$REGION" --member "serviceAccount:$SA" --role roles/run.invoker >/dev/null
URI="https://run.googleapis.com/v2/projects/$PROJECT_ID/locations/$REGION/jobs/minedtv-worker:run"
if gcloud scheduler jobs describe minedtv-worker-tick --location "$REGION" >/dev/null 2>&1; then
  gcloud scheduler jobs update http minedtv-worker-tick --location "$REGION" --schedule "* * * * *" --uri "$URI" --http-method POST --oauth-service-account-email "$SA"
else
  gcloud scheduler jobs create http minedtv-worker-tick --location "$REGION" --schedule "* * * * *" --uri "$URI" --http-method POST --oauth-service-account-email "$SA"
fi

rm -f "$ENV_YAML"
echo "API: $(gcloud run services describe minedtv-api --region "$REGION" --format='value(status.url)')"
