#!/bin/sh
# Container entrypoint: wire credentials from env (never logged), then exec the worker.
set -eu
umask 077
if [ -n "${GOOGLE_APPLICATION_CREDENTIALS_B64:-}" ]; then
  # base64 keeps the JSON YAML-safe inside an Akash SDL env line
  printf '%s' "$GOOGLE_APPLICATION_CREDENTIALS_B64" | base64 -d > /tmp/gcp-sa.json
  export GOOGLE_APPLICATION_CREDENTIALS=/tmp/gcp-sa.json
  unset GOOGLE_APPLICATION_CREDENTIALS_B64
elif [ -n "${GOOGLE_APPLICATION_CREDENTIALS_JSON:-}" ]; then
  printf '%s' "$GOOGLE_APPLICATION_CREDENTIALS_JSON" > /tmp/gcp-sa.json
  export GOOGLE_APPLICATION_CREDENTIALS=/tmp/gcp-sa.json
  unset GOOGLE_APPLICATION_CREDENTIALS_JSON
fi
if [ -n "${GH_TOKEN:-}" ]; then
  gh auth setup-git >/dev/null 2>&1 || true
fi
exec "$@"
