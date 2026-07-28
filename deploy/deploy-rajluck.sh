#!/usr/bin/env bash

# Remote deployment entrypoint for Raj Data Handle on the RajLuck analysis ECS.
# Application rollout and database schema upgrade are intentionally separate.

set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/raj_data_handle}"
BRANCH="${BRANCH:-main}"
ENV_FILE="${ENV_FILE:-.env}"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/compose.rajluck.yml}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-raj-data-handle}"
INIT=false
SKIP_GIT=false
SCHEMA_ONLY=false

log() { printf '[RAJ-DATA-DEPLOY] %s\n' "$1"; }
err() { printf '[RAJ-DATA-DEPLOY][ERROR] %s\n' "$1" >&2; exit 1; }

usage() {
    cat <<'EOF'
Usage:
  bash deploy/deploy-rajluck.sh [--init] [--skip-git] [--schema-only]

Options:
  --init         First application rollout after the repository has been cloned.
  --skip-git     Use the current remote working tree without fetch/reset.
  --schema-only  Run Alembic only. Requires the approved schema-change risk gate.
  -h, --help     Show this help.

Normal application rollout never runs schema migrations automatically. For a
schema-changing release, deploy application code first, then run --schema-only
once only after the approved RDS backup/fallback plan is confirmed.
EOF
}

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --init) INIT=true ;;
        --skip-git) SKIP_GIT=true ;;
        --schema-only) SCHEMA_ONLY=true ;;
        -h|--help) usage; exit 0 ;;
        *) err "unknown argument: $1" ;;
    esac
    shift
done

[[ "$PROJECT_DIR" == "/opt/raj_data_handle" ]] || err "unexpected project directory: $PROJECT_DIR"
[[ -d "$PROJECT_DIR" ]] || err "project directory does not exist: $PROJECT_DIR"

cd "$PROJECT_DIR"
[[ -f "$COMPOSE_FILE" ]] || err "missing production compose file: $COMPOSE_FILE"
[[ -f "$ENV_FILE" ]] || err "missing runtime environment file: $ENV_FILE"

read_env_value() {
    local key="$1"
    local line
    line=$(grep -E "^${key}=" "$ENV_FILE" | tail -n 1 || true)
    line="${line#*=}"
    if [[ "$line" == "'"*"'" ]]; then
        line="${line:1:${#line}-2}"
        line="${line//\\\'/\'}"
    fi
    printf '%s' "$line"
}

require_env_value() {
    local key="$1"
    local value
    value="$(read_env_value "$key")"
    [[ -n "$value" ]] || err "$key is required in $ENV_FILE"
    [[ "$value" != CHANGE_ME* ]] || err "$key still contains a placeholder"
}

validate_runtime_env() {
    local database_url cookie_secure
    for key in RAJ_DATABASE_URL RAJ_SECRET_KEY RAJ_CREDENTIAL_ENCRYPTION_KEY RAJ_CORS_ORIGINS; do
        require_env_value "$key"
    done
    database_url="$(read_env_value RAJ_DATABASE_URL)"
    [[ "$database_url" == *"/data_handle"* ]] || err "RAJ_DATABASE_URL must target database data_handle"
    [[ "$database_url" != *"@postgres:"* ]] || err "RAJ_DATABASE_URL must target external RDS, not a Compose postgres service"
    cookie_secure="$(read_env_value RAJ_SESSION_COOKIE_SECURE)"
    [[ "$cookie_secure" == "true" || "$cookie_secure" == "false" ]] || {
        err "RAJ_SESSION_COOKIE_SECURE must be true or false in production"
    }
}

dc() {
    docker compose --project-name "$COMPOSE_PROJECT_NAME" -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"
}

validate_runtime_env

if [[ "$SCHEMA_ONLY" == true ]]; then
    [[ "$INIT" == false ]] || err "--init cannot be combined with --schema-only"
    log "Running Alembic schema upgrade against data_handle RDS only..."
    dc build api
    dc run --rm --no-deps api alembic upgrade head
    log "Schema upgrade completed."
    exit 0
fi

if [[ "$SKIP_GIT" == true ]]; then
    log "Using current remote working tree because --skip-git was supplied."
elif [[ -d .git ]]; then
    log "Fetching origin/$BRANCH ..."
    git fetch origin "$BRANCH"
    git reset --hard "origin/$BRANCH"
else
    err "remote project is not a Git checkout; rerun with --skip-git only after manual verification"
fi

[[ -f "$COMPOSE_FILE" ]] || err "production compose file is missing after code update: $COMPOSE_FILE"
validate_runtime_env

if [[ "$INIT" == true ]]; then
    mkdir -p runtime/uploads
    log "Initial application rollout (database migration remains separately gated)."
else
    log "Rolling out application code (database migration remains separately gated)."
fi

# Images are tagged as `latest`; without an explicit recreate Compose may keep
# a running container that still references the previously built image.
dc up -d --build --force-recreate --remove-orphans
dc ps
log "Application rollout completed without running a schema migration."
