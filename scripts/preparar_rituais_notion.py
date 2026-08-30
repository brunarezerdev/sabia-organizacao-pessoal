#!/usr/bin/env python3
"""Cria, sem duplicar, a base datada dos rituais de domingo no Notion."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sop.config import Config  # noqa: E402
from sop.integracoes.notion import ClienteNotion  # noqa: E402

NOME = "Rituais semanais"


def esquema(tarefas_database_id: str) -> dict[str, Any]:
    return {
        "Nome": {"title": {}},
        "Domingo": {"date": {}},
        "Semana fechada": {"date": {}},
        "Semana aberta": {"date": {}},
        "Status": {
            "select": {
                "options": [
                    {"name": "Aberto", "color": "green"},
                    {"name": "Fechado", "color": "gray"},
                ]
            }
        },
        "Prioridades concluídas": {
            "relation": {
                "database_id": tarefas_database_id,
                "single_property": {},
            }
        },
    }


def titulo(database: dict[str, Any]) -> str:
    return "".join(p.get("plain_text", "") for p in database.get("title", []))


def procurar(cliente: ClienteNotion, pagina_id: str) -> dict[str, Any] | None:
    resposta = cliente._chamar(
        "POST",
        "/search",
        {"query": NOME, "filter": {"property": "object", "value": "database"}},
    )
    pagina_normalizada = pagina_id.replace("-", "")
    for database in resposta.get("results", []):
        pai = database.get("parent", {}).get("page_id", "").replace("-", "")
        if titulo(database) == NOME and pai == pagina_normalizada:
            return database
    return None


def validar(database: dict[str, Any], tarefas_database_id: str) -> None:
    esperados = {
        "Nome": "title",
        "Domingo": "date",
        "Semana fechada": "date",
        "Semana aberta": "date",
        "Status": "select",
        "Prioridades concluídas": "relation",
    }
    propriedades = database.get("properties", {})
    erros = [
        f"{nome}: esperado {tipo}, encontrado {propriedades.get(nome, {}).get('type', 'ausente')}"
        for nome, tipo in esperados.items()
        if propriedades.get(nome, {}).get("type") != tipo
    ]
    relacao = propriedades.get("Prioridades concluídas", {}).get("relation", {})
    if relacao.get("database_id", "").replace("-", "") != tarefas_database_id.replace("-", ""):
        erros.append("Prioridades concluídas: relação aponta para outra base")
    if erros:
        raise RuntimeError("Esquema incompatível em Rituais semanais: " + "; ".join(erros))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pagina", required=True, help="página que receberá a base")
    parser.add_argument("--tarefas", required=True, help="id da base Prazos e tarefas")
    args = parser.parse_args()

    cliente = ClienteNotion(Config.do_ambiente())
    existente = procurar(cliente, args.pagina)
    if existente:
        completa = cliente._chamar("GET", f"/databases/{existente['id']}")
        validar(completa, args.tarefas)
        print(f"Já existe: {NOME} ({existente['id']}). Esquema conferido.")
        print(f"NOTION_RITUAIS_DATABASE_ID={existente['id']}")
        return 0

    criada = cliente._chamar(
        "POST",
        "/databases",
        {
            "parent": {"type": "page_id", "page_id": args.pagina},
            "title": [{"type": "text", "text": {"content": NOME}}],
            "description": [
                {
                    "type": "text",
                    "text": {
                        "content": (
                            "Um registro por domingo, criado pela integração no plano gratuito. "
                            "O histórico anterior permanece nesta página."
                        )
                    },
                }
            ],
            "properties": esquema(args.tarefas),
        },
    )
    validar(criada, args.tarefas)
    print(f"Criada: {NOME} ({criada['id']})")
    print(f"URL: {criada.get('url', '')}")
    print(f"NOTION_RITUAIS_DATABASE_ID={criada['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
