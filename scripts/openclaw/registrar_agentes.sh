#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Registra os agentes deste projeto no OpenClaw.
#
#     python -m sop openclaw                        # gera a declaração
#     bash scripts/openclaw/registrar_agentes.sh    # aplica no OpenClaw
#
# Lê `openclaw/agentes.json` (a declaração do projeto) e, para cada agente:
#
#   1. registra com `openclaw agents add` — append não destrutivo, idempotente;
#   2. define nome e emoji com `openclaw agents set-identity`;
#   3. copia a alma gerada para o `SOUL.md` do workspace dele.
#
# Por que `agents add` e não editar o JSON: os subagentes vivem em
# `agents.list[]`, e um `config patch` nesse array é recusado pelo CLI com
# "Refusing to replace agents.list". O subcomando dedicado faz append, valida
# na escrita e cria o workspace. É o único caminho que não corrompe a config.
#
# Adaptado da ETAPA 2.8 do SETUP-AGENTE.md do repositório de referência (MIT)
# — crédito em README.md.
# ---------------------------------------------------------------------------

set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DECLARACAO="$RAIZ/openclaw/agentes.json"

command -v openclaw >/dev/null 2>&1 || {
  echo "ERRO: CLI do openclaw não encontrado. Rode scripts/openclaw/instalar.sh"
  exit 1
}
command -v jq >/dev/null 2>&1 || {
  echo "ERRO: jq não encontrado (apt install jq / brew install jq)."
  exit 1
}
[ -f "$DECLARACAO" ] || {
  echo "ERRO: $DECLARACAO não existe. Rode antes: python -m sop openclaw"
  exit 1
}

# `openclaw agents add --tools` não está documentado no roteiro de referência.
# Em vez de assumir que existe, o script pergunta ao próprio CLI. Se a flag não
# existir, as tools continuam declaradas na alma e no agentes.json, e o aviso
# no fim diz o que falta fazer à mão.
SUPORTA_TOOLS=0
if openclaw agents add --help 2>&1 | grep -q -- "--tools"; then
  SUPORTA_TOOLS=1
fi

expandir() { echo "${1/#\~/$HOME}"; }

registrar() {
  local id="$1" nome="$2" emoji="$3" modelo="$4" tools="$5" workspace="$6" alma="$7"
  local ws; ws="$(expandir "$workspace")"

  echo
  echo "== $id ($nome $emoji)"
  echo "   modelo: $modelo"
  echo "   tools:  ${tools:-nenhuma}"

  if [ "$id" != "main" ]; then
    local add=(openclaw agents add "$id" --non-interactive
               --workspace "$ws" --model "$modelo")
    [ "$SUPORTA_TOOLS" -eq 1 ] && [ -n "$tools" ] && add+=(--tools "$tools")
    # Já existir não é erro: o script tem que poder rodar de novo.
    "${add[@]}" 2>&1 | grep -vi "already" || true
  else
    # O agente principal já existe como `main`; só recebe modelo e identidade.
    openclaw models set "$modelo" >/dev/null 2>&1 || true
  fi

  openclaw agents set-identity --agent "$id" --name "$nome" --emoji "$emoji" \
    2>/dev/null || echo "   aviso: set-identity falhou para $id"

  mkdir -p "$ws"
  if [ -f "$RAIZ/$alma" ]; then
    cp "$RAIZ/$alma" "$ws/SOUL.md"
    echo "   alma:   $ws/SOUL.md"
  else
    echo "   aviso: alma não encontrada em $alma (rode python -m sop openclaw)"
  fi
}

echo "Registrando os agentes de $DECLARACAO"

# Cada agente vira uma linha com campos separados por TAB, para sobreviver a
# nome com espaço e a domínio com vírgula.
jq -r '[.principal] + .subagentes
       | .[]
       | [.id, .nome, .emoji, .modelo, (.tools | join(",")), .workspace, .alma]
       | @tsv' "$DECLARACAO" \
| while IFS=$'\t' read -r id nome emoji modelo tools workspace alma; do
    registrar "$id" "$nome" "$emoji" "$modelo" "$tools" "$workspace" "$alma"
  done

echo
echo "-> validando a config"
openclaw config validate || true
openclaw agents list || true

if [ "$SUPORTA_TOOLS" -eq 0 ]; then
  cat <<'AVISO'

AVISO — restrição de tools
  Este CLI não expõe `--tools` em `openclaw agents add`. As tools de cada
  agente estão declaradas em openclaw/agentes.json e no SOUL.md dele, mas não
  foram aplicadas como restrição efetiva na config.

  Confira `openclaw agents add --help` e `openclaw agents --help` na sua
  versão. Ponto anotado como a confirmar em docs/openclaw.md.
AVISO
fi

echo
echo "Pronto. Reinicie o gateway: systemctl restart openclaw-gateway"
