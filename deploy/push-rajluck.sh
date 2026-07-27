#!/usr/bin/env bash

# Local macOS/Linux release wrapper for the Raj Data Handle ECS.
# It is dry-run by default and enforces non-interactive public-key SSH.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

REMOTE_DIR="/opt/raj_data_handle"
DEPLOYMENT_CONFIG="${RAJLUCK_DEPLOYMENT_CONFIG:-$PROJECT_ROOT/configs/deployments.local.yml}"
DEPLOYMENT_ID="${RAJLUCK_DEPLOYMENT_ID:-raj-data-handle}"
SSH_TARGET_OVERRIDE="${RAJLUCK_DEPLOY_SSH_TARGET:-}"
IDENTITY_FILE="${RAJLUCK_DEPLOY_IDENTITY_FILE:-}"
KNOWN_HOSTS_FILE="${RAJLUCK_DEPLOY_KNOWN_HOSTS_FILE:-}"
APP_SECRETS_FILE="$PROJECT_ROOT/deploy/secrets/raj-data-handle.env"
BRANCH="main"
REMOTE_DEPLOY=false
GIT_PUSH=false
INIT=false
SCHEMA_ONLY=false
UPLOAD_SOURCE=false
SOURCE_ARCHIVE=""

usage() {
    cat <<'EOF'
Usage:
  bash deploy/push-rajluck.sh [options]

This wrapper deploys only to /opt/raj_data_handle. It reads the ECS host from
configs/deployments.local.yml, requires public-key SSH with strict host-key
verification, never uses SSH passwords, and is dry-run by default.

Options:
  --deployment-config PATH   Local target configuration (default: configs/deployments.local.yml).
  --deployment-id ID         Target key in configuration (default: raj-data-handle).
  --app-secrets-file PATH    Local app-only secrets file (default: deploy/secrets/raj-data-handle.env).
  --ssh-target TARGET        Override configured SSH user@host; normally unnecessary.
  --identity-file PATH       Explicit SSH private key; otherwise use SSH Agent/system SSH configuration.
  --known-hosts-file PATH    Explicit pinned known-hosts file; otherwise use verified system known_hosts.
  --branch NAME              Git branch for deployment (default: main).
  --git-push                 Push origin/<branch> before the remote operation.
  --upload-source            Upload a sanitized snapshot of the current local source tree.
  --init                     Initialize /opt/raj_data_handle by clone or uploaded source.
  --remote-deploy            Upload .env and run the remote application rollout.
  --schema-only              Run the separately-gated Alembic migration only.
  -h, --help                 Show this help.

`--schema-only` requires the schema-change approval, target-database check,
and backup/fallback confirmation described in docs/deployment-raj-data-handle.md.
EOF
}

require_value() {
    local option="$1"
    local value="${2:-}"
    [[ -n "$value" ]] || { printf 'Missing value for %s\n' "$option" >&2; exit 2; }
}

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --deployment-config) require_value "$1" "${2:-}"; DEPLOYMENT_CONFIG="$2"; shift 2 ;;
        --deployment-id) require_value "$1" "${2:-}"; DEPLOYMENT_ID="$2"; shift 2 ;;
        --app-secrets-file) require_value "$1" "${2:-}"; APP_SECRETS_FILE="$2"; shift 2 ;;
        --ssh-target) require_value "$1" "${2:-}"; SSH_TARGET_OVERRIDE="$2"; shift 2 ;;
        --identity-file) require_value "$1" "${2:-}"; IDENTITY_FILE="$2"; shift 2 ;;
        --known-hosts-file) require_value "$1" "${2:-}"; KNOWN_HOSTS_FILE="$2"; shift 2 ;;
        --branch) require_value "$1" "${2:-}"; BRANCH="$2"; shift 2 ;;
        --git-push) GIT_PUSH=true; shift ;;
        --upload-source) UPLOAD_SOURCE=true; shift ;;
        --init) INIT=true; shift ;;
        --remote-deploy) REMOTE_DEPLOY=true; shift ;;
        --schema-only) SCHEMA_ONLY=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done

[[ -f "$DEPLOYMENT_CONFIG" ]] || { printf 'Deployment configuration file not found: %s\n' "$DEPLOYMENT_CONFIG" >&2; exit 2; }
[[ -f "$APP_SECRETS_FILE" ]] || { printf 'Application secrets file not found: %s\n' "$APP_SECRETS_FILE" >&2; exit 2; }
[[ -z "$IDENTITY_FILE" || -f "$IDENTITY_FILE" ]] || { printf 'SSH private key not found: %s\n' "$IDENTITY_FILE" >&2; exit 2; }
[[ -z "$KNOWN_HOSTS_FILE" || -f "$KNOWN_HOSTS_FILE" ]] || { printf 'Known-hosts file not found: %s\n' "$KNOWN_HOSTS_FILE" >&2; exit 2; }
[[ "$SCHEMA_ONLY" == false || "$INIT" == false ]] || { printf '%s\n' '--schema-only cannot be combined with --init' >&2; exit 2; }
[[ "$SCHEMA_ONLY" == false || "$UPLOAD_SOURCE" == false ]] || { printf '%s\n' '--schema-only cannot be combined with --upload-source' >&2; exit 2; }
[[ "$GIT_PUSH" == false || "$UPLOAD_SOURCE" == false ]] || { printf '%s\n' '--git-push cannot be combined with --upload-source' >&2; exit 2; }

DEPLOYMENT_SSH_USER=""
DEPLOYMENT_SSH_HOST=""
DEPLOYMENT_SSH_PORT=""
DEPLOYMENT_WEB_ACCESS_MODE=""
DEPLOYMENT_WEB_HOSTNAME=""
DEPLOYMENT_WEB_PORT=""
DEPLOYMENT_HOST_NAME=""
DEPLOYMENT_RDS_HOST=""
DEPLOYMENT_RDS_PORT=""
while IFS='=' read -r key value; do
    case "$key" in
        DEPLOYMENT_ID) DEPLOYMENT_ID="$value" ;;
        DEPLOYMENT_HOST_NAME) DEPLOYMENT_HOST_NAME="$value" ;;
        DEPLOYMENT_SSH_USER) DEPLOYMENT_SSH_USER="$value" ;;
        DEPLOYMENT_SSH_HOST) DEPLOYMENT_SSH_HOST="$value" ;;
        DEPLOYMENT_SSH_PORT) DEPLOYMENT_SSH_PORT="$value" ;;
        DEPLOYMENT_WEB_ACCESS_MODE) DEPLOYMENT_WEB_ACCESS_MODE="$value" ;;
        DEPLOYMENT_WEB_HOSTNAME) DEPLOYMENT_WEB_HOSTNAME="$value" ;;
        DEPLOYMENT_WEB_PORT) DEPLOYMENT_WEB_PORT="$value" ;;
        DEPLOYMENT_RDS_HOST) DEPLOYMENT_RDS_HOST="$value" ;;
        DEPLOYMENT_RDS_PORT) DEPLOYMENT_RDS_PORT="$value" ;;
        *) printf 'Unexpected deployment configuration output key: %s\n' "$key" >&2; exit 2 ;;
    esac
done < <(
    "$PYTHON_BIN" "$PROJECT_ROOT/deploy/read_rajluck_deployment.py" \
        --config "$DEPLOYMENT_CONFIG" \
        --deployment-id "$DEPLOYMENT_ID" \
        --format shell
)
[[ -n "$DEPLOYMENT_SSH_USER" && -n "$DEPLOYMENT_SSH_HOST" && -n "$DEPLOYMENT_SSH_PORT" && -n "$DEPLOYMENT_WEB_ACCESS_MODE" && -n "$DEPLOYMENT_WEB_PORT" ]] || {
    printf '%s\n' 'Deployment configuration did not resolve the SSH target and web port.' >&2
    exit 2
}
SSH_TARGET="${SSH_TARGET_OVERRIDE:-$DEPLOYMENT_SSH_USER@$DEPLOYMENT_SSH_HOST}"

umask 077
RENDERED_ENV="$(mktemp "${TMPDIR:-/tmp}/raj-data-handle-rajluck.XXXXXX")"
cleanup() {
    rm -f "$RENDERED_ENV"
    if [[ -n "$SOURCE_ARCHIVE" ]]; then rm -f "$SOURCE_ARCHIVE"; fi
}
trap cleanup EXIT

"$PYTHON_BIN" "$PROJECT_ROOT/deploy/render_rajluck_env.py" \
    --deployment-config "$DEPLOYMENT_CONFIG" \
    --deployment-id "$DEPLOYMENT_ID" \
    --app-secrets-file "$APP_SECRETS_FILE" \
    --output "$RENDERED_ENV" \
    --summary

SSH_OPTIONS=(
    -p "$DEPLOYMENT_SSH_PORT"
    -o BatchMode=yes
    -o PasswordAuthentication=no
    -o KbdInteractiveAuthentication=no
    -o PreferredAuthentications=publickey
    -o StrictHostKeyChecking=yes
)
if [[ -n "$IDENTITY_FILE" ]]; then SSH_OPTIONS+=(-i "$IDENTITY_FILE"); fi
if [[ -n "$KNOWN_HOSTS_FILE" ]]; then SSH_OPTIONS+=(-o "UserKnownHostsFile=$KNOWN_HOSTS_FILE"); fi
SCP_OPTIONS=(
    -P "$DEPLOYMENT_SSH_PORT"
    -o BatchMode=yes
    -o PasswordAuthentication=no
    -o KbdInteractiveAuthentication=no
    -o PreferredAuthentications=publickey
    -o StrictHostKeyChecking=yes
)
if [[ -n "$IDENTITY_FILE" ]]; then SCP_OPTIONS+=(-i "$IDENTITY_FILE"); fi
if [[ -n "$KNOWN_HOSTS_FILE" ]]; then SCP_OPTIONS+=(-o "UserKnownHostsFile=$KNOWN_HOSTS_FILE"); fi

quote_remote() {
    printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\"'\\\"'/g")"
}

REMOTE_ARGS=()
if [[ "$INIT" == true ]]; then REMOTE_ARGS+=(--init); fi
if [[ "$SCHEMA_ONLY" == true ]]; then REMOTE_ARGS+=(--schema-only); fi
if [[ "$UPLOAD_SOURCE" == true ]]; then REMOTE_ARGS+=(--upload-source); fi
REMOTE_ARG_TEXT="${REMOTE_ARGS[*]:-}"

printf 'Target: raj-data-handle\n'
printf 'Deployment target: %s · %s\n' "$DEPLOYMENT_ID" "$DEPLOYMENT_HOST_NAME"
printf 'Project root: %s\n' "$PROJECT_ROOT"
printf 'Remote directory: %s\n' "$REMOTE_DIR"
printf 'SSH target: %s (public key only, strict host key)\n' "$SSH_TARGET"
if [[ "$DEPLOYMENT_WEB_ACCESS_MODE" == "cloudflare_reverse_proxy" ]]; then
    printf 'External access: https://%s (Cloudflare reverse proxy)\n' "$DEPLOYMENT_WEB_HOSTNAME"
else
    printf 'External access: http://%s:%s\n' "$DEPLOYMENT_SSH_HOST" "$DEPLOYMENT_WEB_PORT"
fi
printf 'Branch: %s\n' "$BRANCH"
printf 'Remote mode: %s\n' "${REMOTE_ARG_TEXT:-(application rollout without schema migration)}"

if [[ "$GIT_PUSH" != true && "$REMOTE_DEPLOY" != true ]]; then
    printf '%s\n' 'DRY RUN: no git push, remote upload, database migration, or service restart was run.'
    exit 0
fi

if [[ "$GIT_PUSH" == true ]]; then
    git -C "$PROJECT_ROOT" push origin "$BRANCH"
fi

if [[ "$REMOTE_DEPLOY" != true ]]; then
    exit 0
fi

ssh "${SSH_OPTIONS[@]}" "$SSH_TARGET" 'true'

if [[ "$INIT" == true && "$UPLOAD_SOURCE" == false ]]; then
    REPOSITORY_URL="$(git -C "$PROJECT_ROOT" config --get remote.origin.url || true)"
    [[ -n "$REPOSITORY_URL" ]] || { printf '%s\n' 'Cannot bootstrap: local origin URL is missing.' >&2; exit 2; }
    REMOTE_BOOTSTRAP="if [ ! -d $(quote_remote "$REMOTE_DIR/.git") ]; then install -d -m 0755 $(quote_remote "$(dirname "$REMOTE_DIR")") && git clone --branch $(quote_remote "$BRANCH") $(quote_remote "$REPOSITORY_URL") $(quote_remote "$REMOTE_DIR"); fi"
    ssh "${SSH_OPTIONS[@]}" "$SSH_TARGET" "$REMOTE_BOOTSTRAP"
fi

if [[ "$UPLOAD_SOURCE" == true ]]; then
    SOURCE_ARCHIVE="$(mktemp "${TMPDIR:-/tmp}/raj-data-handle-source.XXXXXX.tar.gz")"
    tar \
        --no-xattrs \
        --no-mac-metadata \
        --exclude='apps/web/node_modules' \
        --exclude='apps/web/dist' \
        --exclude='**/__pycache__' \
        --exclude='**/*.pyc' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='deploy/secrets/raj-data-handle.env' \
        --exclude='deploy/deployments.local.yml' \
        --exclude='deploy/*.txt' \
        --exclude='._*' \
        --exclude='.DS_Store' \
        -czf "$SOURCE_ARCHIVE" \
        -C "$PROJECT_ROOT" \
        .dockerignore .env.example AGENTS.md README.md alembic.ini \
        apps database deploy packages scripts pyproject.toml requirements.txt
    if tar -tzf "$SOURCE_ARCHIVE" | grep -Eq '(^|/)(\._[^/]*|raj-data-handle\.env|deployments\.local\.yml|data|remote_api_templates|\.git|\.venv|node_modules|dist)(/|$)'; then
        printf '%s\n' 'Sanitized source archive unexpectedly contains a forbidden path.' >&2
        exit 2
    fi
    REMOTE_ARCHIVE="/tmp/raj-data-handle-source.tar.gz"
    scp "${SCP_OPTIONS[@]}" "$SOURCE_ARCHIVE" "$SSH_TARGET:$REMOTE_ARCHIVE"
    REMOTE_EXTRACT="install -d -m 0755 $(quote_remote "$REMOTE_DIR") && find $(quote_remote "$REMOTE_DIR") -type f -name '._*' -delete && tar --no-same-owner --no-xattrs -xzf $(quote_remote "$REMOTE_ARCHIVE") -C $(quote_remote "$REMOTE_DIR") && rm -f $(quote_remote "$REMOTE_ARCHIVE") && test -f $(quote_remote "$REMOTE_DIR/deploy/compose.rajluck.yml") && test ! -f $(quote_remote "$REMOTE_DIR/deploy/secrets/raj-data-handle.env")"
    ssh "${SSH_OPTIONS[@]}" "$SSH_TARGET" "$REMOTE_EXTRACT"
fi

scp "${SCP_OPTIONS[@]}" "$RENDERED_ENV" "$SSH_TARGET:$REMOTE_DIR/.env"
ssh "${SSH_OPTIONS[@]}" "$SSH_TARGET" "chmod 600 $(quote_remote "$REMOTE_DIR/.env")"

REMOTE_COMMAND="cd $(quote_remote "$REMOTE_DIR") && BRANCH=$(quote_remote "$BRANCH") bash deploy/deploy-rajluck.sh"
if [[ "$SCHEMA_ONLY" == true ]]; then
    REMOTE_COMMAND+=" --schema-only"
else
    if [[ "$UPLOAD_SOURCE" == true ]]; then REMOTE_COMMAND+=" --skip-git"; fi
    if [[ "$INIT" == true ]]; then REMOTE_COMMAND+=" --init"; fi
fi
ssh "${SSH_OPTIONS[@]}" "$SSH_TARGET" "$REMOTE_COMMAND"
