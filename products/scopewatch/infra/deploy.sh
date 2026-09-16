#!/usr/bin/env bash
# Build Scopewatch, push it, and put it in front of a judge. One command, safe to
# run again.
#
#   products/scopewatch/infra/deploy.sh [options]
#
#     --tag TAG       image tag (default: short git sha, plus -dirty if the tree is)
#     --skip-build    deploy a tag that is already in ECR
#     --status        print the service's status and URL, change nothing
#     --min-free-gb N wait until this much RAM is free before building (default 5)
#     --no-wait-mem   build immediately, however loaded the machine is
#
# Nothing here reimplements the shared scripts. infra/ecr.sh owns the repository,
# the login, buildx and the push; infra/apprunner.sh owns the ECR access role, the
# create-or-update, the wait and the health check. This file is the three
# Scopewatch-specific facts those scripts cannot know: the build context is the
# repo root rather than the product directory, the service listens on 8080, and it
# runs at 2 vCPU / 4 GB because a 960px video pipeline on 0.25 vCPU is a timeout.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRODUCT_DIR="$(cd "$HERE/.." && pwd)"
ROOT="$(cd "$PRODUCT_DIR/../.." && pwd)"

PRODUCT="scopewatch"
CPU="2"
MEMORY="4"
PORT="8080"
ARCH="linux/amd64"   # App Runner has no arm64 runtime. Not negotiable.

MODEL="$PRODUCT_DIR/models/yolox_tiny.onnx"
MODEL_SHA="427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7"
MODEL_URL="https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_tiny.onnx"
SAMPLE="$PRODUCT_DIR/media/sample-case.mp4"

TAG=""
SKIP_BUILD=0
STATUS_ONLY=0
MIN_FREE_GB=5
WAIT_FOR_MEMORY=1
MEMORY_WAIT_LIMIT=1800   # seconds

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag)          TAG="$2"; shift 2 ;;
    --skip-build)   SKIP_BUILD=1; shift ;;
    --status)       STATUS_ONLY=1; shift ;;
    --min-free-gb)  MIN_FREE_GB="$2"; shift 2 ;;
    --no-wait-mem)  WAIT_FOR_MEMORY=0; shift ;;
    -h|--help)      sed -n '2,18p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *)              printf 'unknown option %s\n' "$1" >&2; exit 2 ;;
  esac
done

# common.sh gives the same colours, logging and account guard the shared scripts
# use, plus ecr_repo_uri(). Sourcing it means this script cannot drift from them.
# shellcheck source=/dev/null
source "$ROOT/infra/common.sh"

if [[ "$STATUS_ONLY" == "1" ]]; then
  exec "$ROOT/infra/apprunner.sh" "$PRODUCT" --status
fi

require_aws

# ---- preflight -------------------------------------------------------------
# Both of these are baked into the image. Catching a missing one here costs a
# second; catching it after a ten-minute build does not.

log "checking the baked-in assets"
[[ -f "$MODEL" ]] || die "no model at $MODEL - fetch it with:
     curl -fL -o '$MODEL' '$MODEL_URL'"
actual_sha="$(sha256sum "$MODEL" | cut -d' ' -f1)"
[[ "$actual_sha" == "$MODEL_SHA" ]] \
  || die "yolox_tiny.onnx sha256 mismatch: expected $MODEL_SHA, got $actual_sha"
[[ -f "$SAMPLE" ]] || die "no sample clip at $SAMPLE - a judge needs it on a cold start"
ok "yolox_tiny.onnx verified, sample clip present"

# ---- the tag ---------------------------------------------------------------
# Computed here rather than left to ecr.sh's default, because apprunner.sh has to
# be handed the same string. Same rule as ecr.sh so the two never disagree.

if [[ -z "$TAG" ]]; then
  TAG="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo manual)"
  if ! git -C "$ROOT" diff --quiet 2>/dev/null; then
    TAG="${TAG}-dirty"
  fi
fi
dim "image tag $TAG"

# ---- memory gate -----------------------------------------------------------
# Several agents build on this machine at once. A buildx job that starts with no
# headroom gets OOM-killed somewhere inside the opencv wheel and reports it as a
# corrupt download, which is a genuinely confusing hour.

available_gb() {
  local gb
  gb="$(free -g | awk '/^Mem:/ {print $7}')"
  # procps older than 3.3.10 has no "available" column; fall back to the kernel.
  if [[ -z "$gb" ]]; then
    gb="$(awk '/^MemAvailable:/ {printf "%d", $2 / 1048576}' /proc/meminfo)"
  fi
  printf '%s' "${gb:-0}"
}

wait_for_memory() {
  local available deadline
  available="$(available_gb)"
  if [[ "$available" -ge "$MIN_FREE_GB" ]]; then
    dim "${available} GB available, building"
    return 0
  fi
  if [[ "$WAIT_FOR_MEMORY" != "1" ]]; then
    warn "only ${available} GB available; --no-wait-mem was passed, building anyway"
    return 0
  fi
  log "only ${available} GB available, waiting for ${MIN_FREE_GB} GB (up to 30 minutes)"
  deadline=$(( $(date +%s) + MEMORY_WAIT_LIMIT ))
  while :; do
    sleep 60
    available="$(available_gb)"
    if [[ "$available" -ge "$MIN_FREE_GB" ]]; then
      ok "${available} GB available, building"
      return 0
    fi
    dim "still ${available} GB; waiting"
    if [[ $(date +%s) -ge $deadline ]]; then
      die "waited 30 minutes and RAM never reached ${MIN_FREE_GB} GB. Either something
     large is stuck, or pass --no-wait-mem if you know it will fit."
    fi
  done
}

# ---- build and push --------------------------------------------------------

IMAGE_URI="$(ecr_repo_uri "$PRODUCT")"

if [[ "$SKIP_BUILD" == "1" ]]; then
  log "--skip-build: expecting $IMAGE_URI:$TAG to be in ECR already"
  aws ecr describe-images --repository-name "$(ecr_repo_name "$PRODUCT")" \
    --image-ids "imageTag=$TAG" >/dev/null 2>&1 \
    || die "no image tagged $TAG in $(ecr_repo_name "$PRODUCT"); drop --skip-build"
  ok "image present"
else
  wait_for_memory
  log "building and pushing $PRODUCT:$TAG from the repo root"
  # The context is $ROOT: the image needs packages/visioncore and
  # packages/servicekit, which live outside this product's directory.
  "$ROOT/infra/ecr.sh" "$PRODUCT" \
    --context "$ROOT" \
    --dockerfile "$PRODUCT_DIR/Dockerfile" \
    --arch "$ARCH" \
    --tag "$TAG" >/dev/null
  ok "pushed $IMAGE_URI:$TAG"
fi

# ---- deploy ----------------------------------------------------------------
# apprunner.sh creates the service if it is absent and updates it if it is not,
# then waits for RUNNING and curls /healthz. It prints the URL on stdout.

log "deploying to App Runner at $CPU vCPU / $MEMORY GB"
URL="$("$ROOT/infra/apprunner.sh" "$PRODUCT" \
        --tag "$TAG" \
        --cpu "$CPU" \
        --memory "$MEMORY" \
        --port "$PORT" | tail -n1)"

# apprunner.sh tags on create but not on update, so a service that predates the
# tagging convention would stay untagged and drop out of the Cost Explorer split.
# tag-resource is idempotent; reconcile every time.
SERVICE_ARN="$(aws apprunner list-services \
  --query "ServiceSummaryList[?ServiceName=='opencv26-$PRODUCT'].ServiceArn | [0]" \
  --output text 2>/dev/null | grep -v '^None$' || true)"
if [[ -n "$SERVICE_ARN" ]]; then
  aws apprunner tag-resource --resource-arn "$SERVICE_ARN" \
    --tags "$(tags_json "$PRODUCT")" >/dev/null
  dim "tags reconciled: Project=$PROJECT_TAG, Product=$PRODUCT"
fi

ok "Scopewatch is live"
printf '%s\n' "$URL"
