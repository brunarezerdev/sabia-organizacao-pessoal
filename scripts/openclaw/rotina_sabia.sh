#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Rotina diária da Sábia, disparada pelo cron.
#
# Roda um turno do agente principal do OpenClaw na mesma sessão direta da
# Bruna. Assim, a resposta dela às candidatas continua a combinação iniciada
# no briefing, em vez de cair numa conversa sem contexto.
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
INSTRUCAO="$RAIZ/sabia/briefing-diario.md"
DESTINO="${SOP_BRIEFING_CHAT_ID:-}"

if [ -n "${SOP_PROMPT:-}" ]; then
  PROMPT="$SOP_PROMPT"
elif [ -r "$INSTRUCAO" ]; then
  PROMPT="$(cat "$INSTRUCAO")"
else
  echo "ERRO: instrução do briefing não encontrada em $INSTRUCAO"
  exit 1
fi

echo "===== $(date -Is) | rotina Sábia iniciada ====="

if [ ! -x "$CLI" ]; then
  echo "ERRO: CLI do OpenClaw não encontrado em $CLI"
  exit 1
fi

if [ -z "$DESTINO" ]; then
  echo "ERRO: SOP_BRIEFING_CHAT_ID não configurado"
  exit 1
fi

# O destino também define a sessão: o retorno da Bruna chega nessa mesma
# conversa e permite concluir, trocar ou manter em aberto as prioridades.
"$CLI" agent \
  --agent main \
  --session-key "agent:main:telegram:direct:$DESTINO" \
  --message "$PROMPT" \
  --deliver \
  --reply-channel telegram \
  --reply-to "$DESTINO"
STATUS=$?

echo "===== $(date -Is) | rotina Sábia terminou (status=$STATUS) ====="
exit "$STATUS"
