#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Adaptador entre o backend `openclaw` do sop e o CLI do OpenClaw.
#
#     echo "<instrução>" | bash scripts/openclaw/classificar.sh main
#
# POR QUE ESTE ARQUIVO EXISTE
#
#   O backend em src/sop/integracoes/ia.py entrega a instrução pela entrada
#   padrão e espera ler o JSON da classificação na saída padrão. O CLI da
#   2026.6.5 não faz nem uma coisa nem outra:
#
#     - `openclaw agent` NÃO lê stdin. Sem `-m/--message` ele sai com
#       "Missing required option -m, --message <text>".
#     - com `--json`, o que sai é o envelope do CLI, e a resposta do agente
#       fica aninhada dentro dele. Entregar esse envelope cru ao Python faria
#       o extrair_json() devolver o envelope em vez da classificação, e toda
#       mensagem cairia no heurístico sem ninguém perceber.
#
#   Este script é a costura: lê stdin, passa por --message, e devolve só o
#   texto que o agente produziu. Assim o Python continua com o contrato que os
#   testes dele descrevem, e o CLI continua sendo chamado do jeito que ele
#   aceita. Trocar de versão de CLI mexe aqui, não no código.
#
# O envelope tem dois formatos, e os dois aparecem na prática:
#   - rota gateway  ->  .result.payloads[].text
#   - queda para o agente embutido  ->  .payloads[].text
# O jq abaixo aceita os dois.
# ---------------------------------------------------------------------------

set -euo pipefail

AGENTE="${1:-${OPENCLAW_AGENTE:-main}}"
TIMEOUT="${OPENCLAW_TIMEOUT:-120}"
OPENCLAW_BIN="${OPENCLAW_BIN:-openclaw}"

command -v "$OPENCLAW_BIN" >/dev/null 2>&1 || {
  echo "ERRO: CLI do openclaw não encontrado ($OPENCLAW_BIN)." >&2
  exit 1
}

MENSAGEM="$(cat)"
[ -n "${MENSAGEM//[[:space:]]/}" ] || {
  echo "ERRO: nada chegou pela entrada padrão." >&2
  exit 1
}

# Sessão nova a cada chamada. Sem isso o CLI reaproveita a sessão principal do
# agente, e cada classificação carregaria as anteriores: o custo por mensagem
# cresce sem parar e a triagem de uma mensagem passa a ser influenciada pela
# mensagem de ontem. Classificação é sem memória por definição.
CHAVE="agent:${AGENTE}:sop-$(date +%s)-${RANDOM}"

BRUTO="$("$OPENCLAW_BIN" agent \
  --agent "$AGENTE" \
  --session-key "$CHAVE" \
  --message "$MENSAGEM" \
  --timeout "$TIMEOUT" \
  --json 2>/dev/null)"

# O envelope pode vir precedido de linhas de aviso quando o CLI cai para o
# agente embutido; recorta do primeiro `{` em diante antes de entregar ao jq.
echo "$BRUTO" \
  | sed -n '/^{/,$p' \
  | jq -r '[(.result.payloads // .payloads // [])[]?.text | select(. != null)] | join("\n")'
