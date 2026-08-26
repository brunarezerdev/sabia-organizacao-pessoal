#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Registra a estrutura Sábia no OpenClaw: a orquestradora e os nove agentes.
#
#     python3 sabia/converter.py       # gera as almas e a declaração
#     bash sabia/registrar.sh          # aplica no OpenClaw
#
# Para cada agente de `sabia/agentes-sabia.json`:
#
#   1. registra com `openclaw agents add` (append idempotente, cria o workspace);
#   2. copia a alma gerada para o SOUL.md do workspace dele;
#   3. define nome e emoji com `openclaw agents set-identity`.
#
# Depois chama `sabia/bin/aplicar_politicas.py`, que grava tools, nível de raciocínio e permissão
# de delegação numa única escrita validada.
#
# Por que `agents add` e não editar o JSON: os subagentes vivem em `agents.list[]`, e um
# `config patch` nesse array é recusado pelo CLI com "Refusing to replace agents.list". O
# subcomando dedicado faz append, valida na escrita e cria o workspace.
#
# O script pode rodar quantas vezes for preciso. Agente que já existe não é recriado.
# ---------------------------------------------------------------------------

set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DECLARACAO="$RAIZ/sabia/agentes-sabia.json"
CLI="$RAIZ/node_modules/openclaw/dist/index.js"

openclaw() { node "$CLI" "$@"; }

[ -f "$CLI" ] || { echo "ERRO: OpenClaw não encontrado em $CLI"; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "ERRO: jq não encontrado."; exit 1; }
[ -f "$DECLARACAO" ] || { echo "ERRO: $DECLARACAO não existe. Rode: python3 sabia/converter.py"; exit 1; }

expandir() { echo "${1/#\~/$HOME}"; }

registrar() {
  local id="$1" nome="$2" emoji="$3" modelo="$4" workspace="$5" alma="$6"
  local ws; ws="$(expandir "$workspace")"

  echo
  echo "== $id ($nome $emoji)"

  if [ "$id" != "main" ]; then
    # Já existir não é erro: o script tem que poder rodar de novo.
    openclaw agents add "$id" --non-interactive --workspace "$ws" --model "$modelo" \
      2>&1 | grep -viE "already|^$" || true
  fi

  mkdir -p "$ws"
  if [ -f "$RAIZ/$alma" ]; then
    cp "$RAIZ/$alma" "$ws/SOUL.md"
    echo "   alma: $ws/SOUL.md"
  else
    echo "   AVISO: alma não encontrada em $alma (rode python3 sabia/converter.py)"
  fi

  openclaw agents set-identity --agent "$id" --name "$nome" --emoji "$emoji" \
    >/dev/null 2>&1 || echo "   aviso: set-identity falhou para $id"
}

echo "Registrando a estrutura Sábia a partir de $DECLARACAO"

# Campos separados por TAB, para sobreviver a nome com espaço e descrição com vírgula.
while IFS=$'\t' read -r id nome emoji modelo workspace alma; do
  registrar "$id" "$nome" "$emoji" "$modelo" "$workspace" "$alma"
done < <(jq -r '[.principal] + .subagentes
                | .[]
                | [.id, .nome, .emoji, .modelo, .workspace, .alma]
                | @tsv' "$DECLARACAO")

echo
echo "-> aplicando tools, raciocínio e permissão de delegação"
python3 "$RAIZ/sabia/bin/aplicar_politicas.py"

echo
echo "-> validando"
openclaw config validate || true
openclaw agents list || true

echo
echo "Pronto. Reinicie o gateway para o SOUL.md novo entrar:"
echo "  bash sabia/reiniciar_gateway.sh"
