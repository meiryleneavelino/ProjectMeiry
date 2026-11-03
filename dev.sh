#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DOCKER="${DOCKER_BIN:-docker}"
if [[ -z "${DOCKER_BIN:-}" && -x /Applications/Docker.app/Contents/Resources/bin/docker ]]; then
    DOCKER=/Applications/Docker.app/Contents/Resources/bin/docker
fi
IMAGE="${DYNAMOS_DEV_IMAGE:-scattered-dev-tools:local}"
CONTAINER="${DYNAMOS_DEV_CONTAINER:-dynamos-dev}"
CONTAINER_ROOT="${SCATTERED_CONTAINER_ROOT:-/workspace/Scattered-Directive}"

if [[ "${1:-}" != "--no-rebuild" ]]; then
    "$DOCKER" build -f "$SCRIPT_DIR/configuration/federated-training/Dockerfile.tools" -t "$IMAGE" "$SCRIPT_DIR"
fi

if "$DOCKER" container inspect "$CONTAINER" >/dev/null 2>&1; then
    if [[ "$("$DOCKER" inspect --format '{{.State.Running}}' "$CONTAINER")" != true ]]; then
        "$DOCKER" start "$CONTAINER"
    fi
    "$DOCKER" exec "$CONTAINER" test -f "$CONTAINER_ROOT/configuration/federated-training/manage.py"
    printf 'Tools container %s is ready.\n' "$CONTAINER"
    exit 0
fi

mkdir -p "$HOME/.kube"
"$DOCKER" run --detach --interactive --tty --name "$CONTAINER" --network host \
    -v "$SCRIPT_DIR:$CONTAINER_ROOT" \
    -v "$HOME/.kube:/root/.kube" \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -w "$CONTAINER_ROOT" "$IMAGE" bash
printf 'Tools container %s is ready.\n' "$CONTAINER"