#!/usr/bin/env bash
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TOKEN_PATH="${SOP_NOTION_TOKEN_PATH:-${SOP_SEGREDOS:-$HOME/.secrets}/sop-notion.token}"

[ "${SABIA_DEMO:-}" = "1" ] || { echo "ERRO: SABIA_DEMO=1 é obrigatório" >&2; exit 1; }
[ -r "$TOKEN_PATH" ] || { echo "ERRO: token Notion ausente" >&2; exit 1; }
[ -n "${SABIA_WORKSPACE:-}" ] || { echo "ERRO: SABIA_WORKSPACE ausente" >&2; exit 1; }
[ -n "${NOTION_LANCAMENTOS_DEMO_ID:-}" ] || { echo "ERRO: fonte de lançamentos DEMO ausente" >&2; exit 1; }
[ -n "${NOTION_INGREDIENTES_DEMO_ID:-}" ] || { echo "ERRO: fonte de ingredientes DEMO ausente" >&2; exit 1; }

export NOTION_TOKEN_PATH="$TOKEN_PATH"
export NOTION_DATABASE_ID="$NOTION_LANCAMENTOS_DEMO_ID"
export PYTHONPATH="$RAIZ/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m sop.integracoes.nota_mcp "$@"
