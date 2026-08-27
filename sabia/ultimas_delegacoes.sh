#!/usr/bin/env bash
# Mostra as últimas delegações da Sábia para os nove agentes.
#
# Existe porque o `sessions tail` rotula o `sessions_spawn` como "error" mesmo quando o
# trabalho terminou bem: aquele erro é o encerramento do turno da mãe, não o resultado da
# filha. Quem guarda o resultado de verdade é a tabela `subagent_runs`.
#
# O cliente `sqlite3` não está instalado nesta VPS, então lemos pelo Python, somente leitura.
set -euo pipefail

BANCO="${OPENCLAW_STATE_DB:-$HOME/.openclaw/state/openclaw.sqlite}"
QUANTAS="${1:-5}"

if [ ! -f "$BANCO" ]; then
  echo "banco do OpenClaw não encontrado em $BANCO" >&2
  exit 1
fi

BANCO="$BANCO" QUANTAS="$QUANTAS" python3 - <<'PY'
import json
import os
import sqlite3

banco = os.environ["BANCO"]
quantas = int(os.environ["QUANTAS"])

con = sqlite3.connect(f"file:{banco}?mode=ro", uri=True)
linhas = con.execute(
    """
    select child_session_key, task_name, outcome_json, ended_reason, frozen_result_text
      from subagent_runs
     order by rowid desc
     limit ?
    """,
    (quantas,),
).fetchall()

if not linhas:
    print("nenhuma delegação registrada ainda")

for chave, nome, outcome, motivo, resultado in linhas:
    agente = chave.split(":")[1] if chave and ":" in chave else "?"
    try:
        estado = json.loads(outcome or "{}").get("status", "?")
    except json.JSONDecodeError:
        estado = "?"
    print(f"agente:    {agente}")
    print(f"tarefa:    {nome or '-'}")
    print(f"situação:  {estado} ({motivo or '-'})")
    texto = (resultado or "").strip() or "-"
    if len(texto) > 300:
        texto = texto[:300] + "..."
    print("resposta:  " + texto.replace("\n", "\n           "))
    print("-" * 60)
PY
