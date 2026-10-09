#!/bin/sh
# Container entrypoint: wire credentials from env (never logged), then exec the worker.
set -eu
umask 077
if [ -n "${GOOGLE_APPLICATION_CREDENTIALS_JSON:-}" ]; then
  printf '%s' "$GOOGLE_APPLICATION_CREDENTIALS_JSON" > /tmp/gcp-sa.json
  export GOOGLE_APPLICATION_CREDENTIALS=/tmp/gcp-sa.json
  unset GOOGLE_APPLICATION_CREDENTIALS_JSON
fi
if [ -n "${GH_TOKEN:-}" ]; then
  gh auth setup-git >/dev/null 2>&1 || true
fi
exec "$@"
