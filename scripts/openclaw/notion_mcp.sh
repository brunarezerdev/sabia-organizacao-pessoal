#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Sobe o servidor MCP oficial do Notion (@notionhq/notion-mcp-server) para o
# OpenClaw, em transporte stdio.
#
# O token da integração "Sábia" NÃO fica na config do OpenClaw nem no repo:
# ele é lido em tempo de execução de um arquivo em modo 0600 e exportado só
# para o processo filho.
#
# O caminho do token é da máquina, não do projeto, então não é fixado aqui
# (o teste de segurança recusa caminho absoluto de host no repo). A ordem é:
#   1. SOP_NOTION_TOKEN_PATH, se definida;
#   2. $SOP_SEGREDOS/sop-notion.token, se SOP_SEGREDOS estiver definida;
#   3. ~/.secrets/sop-notion.token como padrão portátil.
# Na VPS da Ária o caminho real é pinado no `env` do servidor MCP dentro de
# ~/.openclaw/openclaw.json, que fica fora do versionamento.
#
# Registrado no OpenClaw como o servidor MCP `notion`:
#     openclaw mcp add notion --command scripts/openclaw/notion_mcp.sh
# ---------------------------------------------------------------------------

set -euo pipefail

TOKEN_PATH="${SOP_NOTION_TOKEN_PATH:-${SOP_SEGREDOS:-$HOME/.secrets}/sop-notion.token}"
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVIDOR="$RAIZ/node_modules/@notionhq/notion-mcp-server/bin/cli.mjs"

[ -r "$TOKEN_PATH" ] || {
  echo "ERRO: token da integração Notion não encontrado em $TOKEN_PATH" >&2
  exit 1
}
[ -f "$SERVIDOR" ] || {
  echo "ERRO: notion-mcp-server não instalado. Rode: npm install @notionhq/notion-mcp-server" >&2
  exit 1
}

NOTION_TOKEN="$(tr -d '[:space:]' < "$TOKEN_PATH")"
export NOTION_TOKEN

exec /usr/bin/node "$SERVIDOR" "$@"
