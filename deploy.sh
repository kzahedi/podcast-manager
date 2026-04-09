#!/usr/bin/env bash
# Build the podcast-manager image and deploy it to a remote host (e.g. Synology NAS).
#
# Configuration — set via environment variables or a local .env.deploy file:
#
#   DEPLOY_HOST       Hostname or IP of the target machine  (required)
#   DEPLOY_USER       SSH username on the target             (required)
#   DEPLOY_PATH       Absolute path on the target where
#                     docker-compose.yml lives               (required)
#   DEPLOY_PORT       SSH port                               (default: 22)
#   IMAGE_NAME        Local image tag to build               (default: podcast-manager)
#   COMPOSE_SERVICE   Service name in docker-compose.yml     (default: podcast-manager)
#
# Example .env.deploy:
#   DEPLOY_HOST=192.168.1.100
#   DEPLOY_USER=admin
#   DEPLOY_PATH=/volume1/docker/podcast-manager
#
# Usage:
#   ./deploy.sh                   # build + push + restart
#   ./deploy.sh --build-only      # build and export image tar, skip remote steps
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load .env.deploy if it exists
if [[ -f "$SCRIPT_DIR/.env.deploy" ]]; then
    # shellcheck disable=SC1091
    set -o allexport
    source "$SCRIPT_DIR/.env.deploy"
    set +o allexport
fi

BUILD_ONLY=false
if [[ "${1:-}" == "--build-only" ]]; then
    BUILD_ONLY=true
fi

IMAGE_NAME="${IMAGE_NAME:-podcast-manager}"
COMPOSE_SERVICE="${COMPOSE_SERVICE:-podcast-manager}"
DEPLOY_PORT="${DEPLOY_PORT:-22}"
TAR_FILE="$SCRIPT_DIR/${IMAGE_NAME}.tar"

# Validate required vars (unless build-only)
if [[ "$BUILD_ONLY" == "false" ]]; then
    for var in DEPLOY_HOST DEPLOY_USER DEPLOY_PATH; do
        if [[ -z "${!var:-}" ]]; then
            echo "ERROR: $var is not set."
            echo "Set it in .env.deploy or as an environment variable."
            echo "  $var=value ./deploy.sh"
            exit 1
        fi
    done
fi

SSH_OPTS=(-p "$DEPLOY_PORT" -o BatchMode=yes -o StrictHostKeyChecking=accept-new)

# ── 1. Build ────────────────────────────────────────────────────────────────
echo "=== Building image: $IMAGE_NAME (linux/amd64) ==="
docker build --platform linux/amd64 -t "$IMAGE_NAME" "$SCRIPT_DIR/podcast-manager"

if [[ "$BUILD_ONLY" == "true" ]]; then
    echo ""
    echo "=== Exporting image to $TAR_FILE ==="
    docker save "$IMAGE_NAME" -o "$TAR_FILE"
    echo "Done. Transfer $TAR_FILE to your target host and run:"
    echo "  docker load -i ${IMAGE_NAME}.tar"
    echo "  docker compose up -d"
    exit 0
fi

# ── 2. Export ────────────────────────────────────────────────────────────────
echo ""
echo "=== Exporting image to $TAR_FILE ==="
docker save "$IMAGE_NAME" -o "$TAR_FILE"

# ── 3. Transfer ──────────────────────────────────────────────────────────────
echo ""
echo "=== Transferring to ${DEPLOY_USER}@${DEPLOY_HOST}:${DEPLOY_PATH}/ ==="
scp "${SSH_OPTS[@]}" "$TAR_FILE" "${DEPLOY_USER}@${DEPLOY_HOST}:${DEPLOY_PATH}/${IMAGE_NAME}.tar"

# ── 4. Remote: load + restart ────────────────────────────────────────────────
echo ""
echo "=== Loading image and restarting service on remote host ==="
# shellcheck disable=SC2029
ssh "${SSH_OPTS[@]}" "${DEPLOY_USER}@${DEPLOY_HOST}" "
    set -e
    cd '${DEPLOY_PATH}'
    sudo -n /usr/local/bin/docker load -i '${IMAGE_NAME}.tar'
    rm -f '${IMAGE_NAME}.tar'
    sudo -n /usr/local/bin/docker compose up -d --no-build '${COMPOSE_SERVICE}'
    echo 'Service restarted.'
    sudo -n /usr/local/bin/docker compose ps '${COMPOSE_SERVICE}'
"

# ── 5. Cleanup local tar ─────────────────────────────────────────────────────
rm -f "$TAR_FILE"

echo ""
echo "=== Deployment complete ==="
