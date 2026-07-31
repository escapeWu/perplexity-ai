#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

COMPOSE_FILE="${PERPLEXITY_DEPLOY_COMPOSE_FILE:-docker-compose.yml}"
ENV_FILE="${PERPLEXITY_DEPLOY_ENV_FILE:-.env}"
WAIT_TIMEOUT="${PERPLEXITY_DEPLOY_WAIT_TIMEOUT:-180}"
LOG_TAIL="${PERPLEXITY_DEPLOY_LOG_TAIL:-200}"
LOCK_FILE="${PERPLEXITY_DEPLOY_LOCK_FILE:-/tmp/perplexity-deploy.lock}"

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

compose() {
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
}

preflight() {
  require_command docker
  docker compose version >/dev/null

  test -f "${COMPOSE_FILE}" || fail "compose file not found: ${COMPOSE_FILE}"
  test -f "${ENV_FILE}" || fail "environment file not found: ${ENV_FILE}"
  test -s token_pool_config.json || fail "token_pool_config.json is missing or empty"
  grep -Eq '^MCP_TOKEN=.+$' "${ENV_FILE}" || fail "MCP_TOKEN is missing from ${ENV_FILE}"

  mkdir -p data
  compose config --quiet
}

acquire_lock() {
  if command -v flock >/dev/null 2>&1; then
    exec 9>"${LOCK_FILE}"
    flock -n 9 || fail "another deployment is already running"
  fi
}

verify() {
  compose exec -T perplexity-mcp \
    curl -fsS http://127.0.0.1:8000/health
  printf '\n'
}

status() {
  compose ps
}

up() {
  acquire_lock
  preflight
  compose build --pull perplexity-mcp
  compose up --detach --wait --wait-timeout "${WAIT_TIMEOUT}" --remove-orphans
  verify
  status
}

usage() {
  cat <<'EOF'
Usage: ./deploy/compose.sh <command>

Commands:
  config   Validate deployment configuration without printing resolved secrets
  build    Build the application image from the checked-out source
  up       Build, start, wait for health, verify, and print service status
  verify   Call the container-local /health endpoint
  status   Print Docker Compose service status
  logs     Print recent application logs
EOF
}

case "${1:-}" in
  config)
    preflight
    ;;
  build)
    preflight
    compose build --pull perplexity-mcp
    ;;
  up)
    up
    ;;
  verify)
    preflight
    verify
    ;;
  status)
    preflight
    status
    ;;
  logs)
    preflight
    compose logs --tail "${LOG_TAIL}" perplexity-mcp
    ;;
  *)
    usage
    exit 2
    ;;
esac
