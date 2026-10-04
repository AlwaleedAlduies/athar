#!/bin/sh
# Run from any directory on the deployment host. Briefly stops web writes so
# PostgreSQL and uploaded files belong to the same backup window.
set -eu
umask 077
cd "$(dirname "$0")/.."
compose() { docker compose --env-file production.env -f compose.production.yaml "$@"; }
target="deploy-backups/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$target"
trap 'compose start web' EXIT
trap 'exit 130' HUP INT TERM
compose stop web
compose exec -T db pg_dump -U athar -d athar --format=custom > "$target/database.dump"
mkdir "$target/media"
compose cp web:/app/media/. "$target/media/"
cp production.env "$target/production.env"
printf '%s\n' 'Backup complete. Copy this private directory to a separate secure location.'
printf '%s\n' "$target"
