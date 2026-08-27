#!/usr/bin/env python3
"""Cria no Notion a database de registro que o sistema usa como banco no-code.

O Notion é o banco do projeto, e uma database precisa existir antes da primeira
gravação. Fazer isso à mão dá margem a errar o nome ou o tipo de uma
propriedade, e o erro só aparece na primeira mensagem real — como um 400 sem
explicação. Este script cria a database com o esquema exato que
`sop.integracoes.notion` espera.

É idempotente: se a database já existir sob a página indicada, ele encontra,
confere o esquema e não cria uma segunda.

Uso:

    export NOTION_TOKEN_PATH=~/.secrets/sop-notion.token   # ou NOTION_TOKEN
    python scripts/preparar_notion.py --pagina <id-da-pagina>

A integração precisa ter acesso à página indicada: no Notion, abra a página,
menu "..." no canto superior direito, "Conexões", e escolha a integração. Sem
isso a API responde 404 mesmo com o token certo.

Ao final o script imprime a linha pronta para o `.env`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import requests  # noqa: E402

from sop.agentes import carregar_registro  # noqa: E402
from sop.config import Config  # noqa: E402

BASE = "https://api.notion.com/v1"
VERSAO_API = "2022-06-28"
TIMEOUT = 30

NOME_PADRAO = "Registro do Sistema"

# Cores fixas por agente: a leitura no Notion fica estável entre execuções.
CORES = ("blue", "green", "orange", "purple", "pink", "brown", "yellow", "red")


def chamar(token: str, metodo: str, caminho: str, corpo: dict | None = None) -> dict:
    resposta = requests.request(
        metodo,
        f"{BASE}{caminho}",
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": VERSAO_API,
            "Content-Type": "application/json",
        },
        json=corpo,
        timeout=TIMEOUT,
    )
    if resposta.status_code >= 400:
        try:
            detalhe = resposta.json().get("message", resposta.text[:300])
        except ValueError:
            detalhe = resposta.text[:300]
        raise SystemExit(f"Notion respondeu {resposta.status_code} em {caminho}: {detalhe}")
    return resposta.json()


def esquema() -> dict:
    """As propriedades que `ClienteNotion.propriedades()` grava.

    As opções de select saem do registro de agentes, que é a fonte de verdade:
    acrescentar um agente em `agentes/` e rodar de novo basta para a database
    passar a conhecê-lo.
    """
    registro = carregar_registro()
    agentes = [a.nome for a in registro]
    categorias = sorted({c for a in registro for c in a.categorias})

    return {
        "Titulo": {"title": {}},
        "Agente": {
            "select": {
                "options": [
                    {"name": nome, "color": CORES[i % len(CORES)]}
                    for i, nome in enumerate(agentes)
                ]
            }
        },
        "Categoria": {
            "select": {"options": [{"name": c} for c in categorias]}
        },
        "Data": {"date": {}},
        "Observacao": {"rich_text": {}},
        "Detalhes": {"rich_text": {}},
    }


def procurar(token: str, pagina: str, nome: str) -> str | None:
    """Database com esse nome já filha da página? Devolve o id."""
    resultado = chamar(
        token,
        "POST",
        "/search",
        {"query": nome, "filter": {"property": "object", "value": "database"}},
    )
    for item in resultado.get("results", []):
        titulo = "".join(t.get("plain_text", "") for t in item.get("title", []))
        pai = item.get("parent", {}).get("page_id", "").replace("-", "")
        if titulo == nome and pai == pagina.replace("-", ""):
            return str(item.get("id", ""))
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pagina", required=True, help="id da página que hospeda a database")
    parser.add_argument("--nome", default=NOME_PADRAO, help=f"padrão: {NOME_PADRAO}")
    args = parser.parse_args()

    config = Config.do_ambiente()
    if not config.notion_token:
        raise SystemExit(
            "Sem token do Notion. Defina NOTION_TOKEN ou NOTION_TOKEN_PATH."
        )

    existente = procurar(config.notion_token, args.pagina, args.nome)
    if existente:
        print(f"Já existe: '{args.nome}' ({existente}). Nada foi criado.")
        propriedades = chamar(config.notion_token, "GET", f"/databases/{existente}")
        faltando = [p for p in esquema() if p not in propriedades.get("properties", {})]
        if faltando:
            print(f"AVISO: propriedades ausentes nessa database: {', '.join(faltando)}")
        else:
            print("Esquema conferido: todas as propriedades esperadas estão lá.")
        print(f"\nNOTION_DATABASE_ID={existente}")
        return 0

    criada = chamar(
        config.notion_token,
        "POST",
        "/databases",
        {
            "parent": {"type": "page_id", "page_id": args.pagina},
            "title": [{"type": "text", "text": {"content": args.nome}}],
            "description": [
                {
                    "type": "text",
                    "text": {
                        "content": (
                            "Tudo que entra pelo Telegram e é classificado cai aqui. "
                            "Editar direto no Notion é esperado: esta é a interface."
                        )
                    },
                }
            ],
            "properties": esquema(),
        },
    )
    identificador = str(criada.get("id", ""))
    print(f"Criada: '{args.nome}' ({identificador})")
    print(f"URL: {criada.get('url', '')}")
    print(f"\nNOTION_DATABASE_ID={identificador}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
