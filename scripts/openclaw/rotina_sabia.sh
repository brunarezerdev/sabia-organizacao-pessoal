#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Rotina diária da Sábia, disparada pelo cron.
#
# Roda um turno do agente principal do OpenClaw contra as bases do Notion
# (Receitas, Planejamento de Refeições, Ingredientes, Regras, Sábia), que o
# agente enxerga pelo servidor MCP `notion`.
#
# Chamado pelo cron do usuário `aria`. O cron entrega um ambiente mínimo, então
# nada aqui depende de PATH herdado: a raiz do projeto sai da posição do
# próprio script e o HOME cai no diretório do usuário quando vier vazio.
#
# O caminho do log é decidido por quem chama (a linha do cron redireciona),
# porque é da máquina e não do projeto.
# ---------------------------------------------------------------------------

set -uo pipefail

export HOME="${HOME:-$(getent passwd "$(id -un)" | cut -d: -f6)}"
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PATH="/usr/bin:/bin:$RAIZ/node_modules/.bin"
CLI="$RAIZ/node_modules/.bin/openclaw"

PROMPT="${SOP_PROMPT:-Bom dia. Consulte as bases da Sábia no Notion pelo MCP e monte o resumo do dia: o planejamento de refeições de hoje e o que estiver faltando na lista de compras (base Ingredientes). Seja direta e curta.}"

echo "===== $(date -Is) | rotina Sábia iniciada ====="

if [ ! -x "$CLI" ]; then
  echo "ERRO: CLI do OpenClaw não encontrado em $CLI"
  exit 1
fi

# --agent main: a orquestradora. O turno sai pelo Gateway já rodando como
# serviço de usuário (openclaw-gateway.service).
"$CLI" agent --agent main -m "$PROMPT"
STATUS=$?

echo "===== $(date -Is) | rotina Sábia terminou (status=$STATUS) ====="
exit "$STATUS"
