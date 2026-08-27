#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Sobe o servidor MCP da Google Agenda para o OpenClaw, em transporte stdio.
#
# Mesma política do notion_mcp.sh: a credencial NÃO fica na config do OpenClaw
# nem no repositório. O que este script recebe é o CAMINHO da chave da conta de
# serviço, e ele confere que o arquivo existe e está legível antes de subir —
# falhar aqui, com mensagem clara, é melhor do que subir um servidor que só vai
# dar erro na primeira pergunta da pessoa.
#
# O caminho é da máquina, não do projeto, então não é fixado aqui. A ordem é:
#   1. GOOGLE_SERVICE_ACCOUNT_PATH, se definida;
#   2. $SOP_SEGREDOS/gcal-service-account.json, se SOP_SEGREDOS estiver definida;
#   3. ~/.secrets/gcal-service-account.json como padrão portátil.
#
# SOP_AGENDAS mapeia rótulo para id de agenda ("bruna=<id>,wagner=<id>") e é
# pinado no `env` do servidor MCP dentro de ~/.openclaw/openclaw.json, que fica
# fora do versionamento — é lá que moram os endereços de e-mail.
#
# Registrado no OpenClaw como o servidor MCP `agenda`:
#     openclaw mcp add agenda --command scripts/openclaw/gcal_mcp.sh
# ---------------------------------------------------------------------------

set -euo pipefail

CHAVE="${GOOGLE_SERVICE_ACCOUNT_PATH:-${SOP_SEGREDOS:-$HOME/.secrets}/gcal-service-account.json}"
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

[ -r "$CHAVE" ] || {
  echo "ERRO: chave da conta de serviço do Google não encontrada em $CHAVE" >&2
  exit 1
}

# Modo do arquivo: uma chave privada legível por todo mundo na máquina é uma
# credencial vazada esperando acontecer.
MODO="$(stat -c '%a' "$CHAVE" 2>/dev/null || echo '?')"
case "$MODO" in
  600|400) ;;
  ?) echo "AVISO: não deu para conferir o modo de $CHAVE" >&2 ;;
  *) echo "AVISO: $CHAVE está com modo $MODO; o esperado é 600 (chmod 600 \"$CHAVE\")" >&2 ;;
esac

export GOOGLE_SERVICE_ACCOUNT_PATH="$CHAVE"
export PYTHONPATH="$RAIZ/src${PYTHONPATH:+:$PYTHONPATH}"

exec python3 -m sop.integracoes.gcal_mcp "$@"
