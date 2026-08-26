#!/usr/bin/env python3
"""
aplicar_politicas.py — aplica no OpenClaw as políticas por agente da estrutura Sábia.

    python3 sabia/bin/aplicar_politicas.py [--dry-run]

O `openclaw agents add` cria o agente, o workspace e o agentDir, mas não expõe flag pra tools,
nível de raciocínio nem permissão de delegação. Esses campos existem no esquema, dentro de cada
item de `agents.list[]`:

    agents.list[N].tools            { allow, deny }
    agents.list[N].thinkingDefault  off|minimal|low|medium|high|xhigh|adaptive|max
    agents.list[N].subagents        { delegationMode, allowAgents }
    agents.list[N].description

Editar `openclaw.json` na mão não serve: o CLI recusa `config patch` que substitua
`agents.list` inteiro, e a escrita crua pula a validação e o `last-good` que protegem a config.
O caminho suportado é `config set` por caminho indexado, que a 2026.6.5 aceita em notação de
colchete. Usamos `--batch-json`, que faz todas as alterações numa única escrita validada: ou
entra tudo, ou não entra nada.

O índice de cada agente muda conforme agentes entram e saem, então ele é resolvido pelo `id` no
momento da aplicação, nunca fixado.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
DECLARACAO = RAIZ / "sabia" / "agentes-sabia.json"
CONFIG = Path(os.environ.get("OPENCLAW_CONFIG", Path.home() / ".openclaw" / "openclaw.json"))
CLI = RAIZ / "node_modules" / "openclaw" / "dist" / "index.js"


def openclaw(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["node", str(CLI), *args], capture_output=True, text=True, timeout=120, cwd=str(RAIZ)
    )


def indice_por_id(config: dict) -> dict[str, int]:
    return {ag.get("id"): i for i, ag in enumerate(config["agents"]["list"])}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="valida sem escrever")
    args = p.parse_args()

    declaracao = json.loads(DECLARACAO.read_text(encoding="utf-8"))
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    indice = indice_por_id(config)

    principal = declaracao["principal"]
    subagentes = declaracao["subagentes"]
    ids = [ag["id"] for ag in subagentes]

    faltando = [i for i in ids + [principal["id"]] if i not in indice]
    if faltando:
        print(
            f"ERRO: estes agentes não estão registrados no OpenClaw: {', '.join(faltando)}.\n"
            "Rode antes: bash sabia/registrar.sh",
            file=sys.stderr,
        )
        return 1

    ops: list[dict] = []

    # A Sábia: coordena, não executa. `delegationMode: prefer` é o mecanismo do próprio OpenClaw
    # pra um agente coordenador empurrar trabalho não trivial pros subagentes em vez de fazer.
    # `allowAgents` é a lista fechada de quem ela pode acionar.
    #
    # Ela NÃO recebe `tools.allow` restrito de propósito: o perfil global `coding` é o que dá a
    # ela as tools do MCP do Notion, que a rotina diária já usa. Fechar a lista aqui derrubaria
    # aquela rotina em silêncio. O limite da Sábia está na alma dela e no delegationMode.
    n = indice[principal["id"]]
    ops += [
        {"path": f"agents.list[{n}].description", "value": principal["descricao"]},
        {"path": f"agents.list[{n}].thinkingDefault", "value": principal["pensamento"]},
        {
            "path": f"agents.list[{n}].subagents",
            "value": {"delegationMode": "prefer", "allowAgents": ids},
        },
    ]

    for ag in subagentes:
        n = indice[ag["id"]]
        tools: dict[str, list[str]] = {"allow": ag["tools"]}
        if ag["deny"]:
            tools["deny"] = ag["deny"]
        ops += [
            {"path": f"agents.list[{n}].description", "value": ag["descricao"]},
            {"path": f"agents.list[{n}].thinkingDefault", "value": ag["pensamento"]},
            {"path": f"agents.list[{n}].tools", "value": tools},
        ]

    chamada = ["config", "set", "--batch-json", json.dumps(ops, ensure_ascii=False), "--strict-json"]
    if args.dry_run:
        chamada.append("--dry-run")

    r = openclaw(*chamada)
    print(r.stdout.strip())
    if r.stderr.strip():
        print(r.stderr.strip(), file=sys.stderr)
    if r.returncode != 0:
        return r.returncode

    print(f"\n{len(ops)} políticas aplicadas em {len(subagentes) + 1} agentes.")
    print(f"Sábia pode delegar para: {', '.join(ids)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
