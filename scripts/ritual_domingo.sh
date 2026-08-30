#!/bin/bash
# Publicação semanal idempotente. O cron da VPS roda em UTC: 22h = 19h em Brasília.
set -eu

exec 9>"${TMPDIR:-/tmp}/sop-pessoal-ritual.lock"
flock -n 9 || exit 0

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
cd "$RAIZ"
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 -m sop ritual --publicar
