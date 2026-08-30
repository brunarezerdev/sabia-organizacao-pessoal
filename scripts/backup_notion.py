#!/usr/bin/env python3
"""Exporta tudo que a integração do projeto consegue ler no Notion.

O arquivo preserva metadados completos, propriedades de databases/páginas e a
árvore de blocos. É um backup JSON da superfície compartilhada com a integração;
conteúdo privado que nunca foi compartilhado não é visível para a API.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from sop.config import Config  # noqa: E402
from sop.integracoes.notion import ClienteNotion  # noqa: E402

_LIMITE_LOCK = threading.Lock()
_ULTIMA_CHAMADA = 0.0


def chamar(cliente: ClienteNotion, metodo: str, caminho: str, corpo=None) -> dict[str, Any]:
    # Limite global entre as threads: no máximo dois inícios por segundo, abaixo
    # da média de três publicada pelo Notion. A concorrência esconde a latência
    # das respostas sem produzir rajadas.
    global _ULTIMA_CHAMADA
    with _LIMITE_LOCK:
        agora = time.monotonic()
        espera = max(0.0, 0.5 - (agora - _ULTIMA_CHAMADA))
        if espera:
            time.sleep(espera)
        _ULTIMA_CHAMADA = time.monotonic()
    for tentativa in range(8):
        try:
            return cliente._chamar(metodo, caminho, corpo)
        except RuntimeError as erro:
            if "respondeu 429" not in str(erro) or tentativa == 7:
                raise
            time.sleep(min(5 * (2**tentativa), 30))
    raise AssertionError("laço de retry terminou sem resposta")


def paginar(cliente: ClienteNotion, metodo: str, caminho: str, corpo=None) -> list[dict[str, Any]]:
    resultados: list[dict[str, Any]] = []
    cursor = None
    while True:
        dados = dict(corpo or {})
        dados["page_size"] = 100
        if cursor:
            dados["start_cursor"] = cursor
        resposta = chamar(cliente, metodo, caminho, dados if metodo == "POST" else None)
        resultados.extend(resposta.get("results", []))
        if not resposta.get("has_more"):
            return resultados
        cursor = resposta.get("next_cursor")


def filhos(cliente: ClienteNotion, bloco_id: str) -> list[dict[str, Any]]:
    itens: list[dict[str, Any]] = []
    cursor = None
    while True:
        sufixo = "?page_size=100" + (f"&start_cursor={cursor}" if cursor else "")
        try:
            resposta = chamar(cliente, "GET", f"/blocks/{bloco_id}/children{sufixo}")
        except RuntimeError as erro:
            # Alguns blocos incorporados apontam para conteúdo que não foi
            # compartilhado com a integração. O backup registra a lacuna e
            # continua com todo o restante, em vez de perder o arquivo inteiro.
            return [{"erro_backup": str(erro), "block_id": bloco_id}]
        for bloco in resposta.get("results", []):
            copia = dict(bloco)
            if bloco.get("has_children"):
                copia["children_exportados"] = filhos(cliente, bloco["id"])
            itens.append(copia)
        if not resposta.get("has_more"):
            return itens
        cursor = resposta.get("next_cursor")


def exportar(cliente: ClienteNotion) -> dict[str, Any]:
    encontrados = paginar(cliente, "POST", "/search", {})
    objetos: dict[str, dict[str, Any]] = {item["id"]: item for item in encontrados}

    bases = [item for item in objetos.values() if item.get("object") == "database"]

    def paginas_da_base(database: dict[str, Any]) -> list[dict[str, Any]]:
        return paginar(cliente, "POST", f"/databases/{database['id']}/query", {})

    # Consultar as bases em paralelo evita que uma base grande bloqueie todas
    # as demais; os ids continuam deduplicados antes da exportação dos blocos.
    with ThreadPoolExecutor(max_workers=3) as executor:
        for paginas in executor.map(paginas_da_base, bases):
            for pagina in paginas:
                objetos.setdefault(pagina["id"], pagina)

    def exportar_objeto(item: dict[str, Any]) -> dict[str, Any]:
        # Search e query já devolvem o objeto completo, inclusive propriedades.
        # Não repetir GET aqui reduz pela metade as chamadas sem perder dados.
        completo = dict(item)
        completo["children_exportados"] = filhos(cliente, item["id"])
        return completo

    # Seis chamadas em trânsito escondem a latência; o cliente serializa cada
    # resposta 429 pelo Retry-After caso o workspace atinja o limite médio.
    exportados: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futuros = [executor.submit(exportar_objeto, item) for item in objetos.values()]
        for indice, futuro in enumerate(as_completed(futuros), start=1):
            exportados.append(futuro.result())
            if indice % 25 == 0:
                print(f"{indice}/{len(objetos)} objetos exportados", file=sys.stderr, flush=True)

    return {
        "formato": "notion-api-json",
        "escopo": "todo conteúdo compartilhado com a integração do sop-pessoal",
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "quantidade_objetos": len(exportados),
        "objetos": exportados,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("saida", type=Path)
    args = parser.parse_args()
    config = Config.do_ambiente()
    cliente = ClienteNotion(config)
    dados = exportar(cliente)
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{dados['quantidade_objetos']} objetos salvos em {args.saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
