#!/usr/bin/env python3
"""Incorpora o dashboard financeiro DEMO na página Celeiro › Finanças.

A página hoje termina numa lista seca de links para as três bases DEMO. Este
script troca essa lista por uma entrada visual: o dashboard publicado entra como
bloco `embed` logo abaixo do título, e os links diretos continuam existindo
dentro de um toggle discreto, como caminho de fallback quando o embed não abrir.

Executa em três tempos, nesta ordem:

    1. backup  — grava a árvore de blocos da página em `backups/` antes de mexer;
    2. aplica  — insere/atualiza o embed e o toggle, arquiva a lista antiga;
    3. confere — relê a página e exige que o resultado bata com o esperado.

É idempotente: rodar de novo com a mesma URL não duplica nada, e rodar com uma
URL nova atualiza o embed existente no lugar de criar um segundo.

O script nunca toca em ícone, capa, imagens ou nas três bases DEMO. A remoção da
lista antiga é `archive`, que o Notion desfaz pela lixeira.

Uso:
    python3 scripts/embutir_dashboard_notion.py https://<projeto>.vercel.app
    python3 scripts/embutir_dashboard_notion.py --conferir https://<projeto>.vercel.app
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from sop.config import Config  # noqa: E402

BASE = "https://api.notion.com/v1"
VERSAO = "2022-06-28"

# Nenhum id do Notion mora neste arquivo. O README avisa que o repositório pode
# se tornar público, e id de página revela a estrutura do workspace pessoal da
# Bruna sem servir para mais nada aqui: com o token, o script acha tudo sozinho;
# sem o token, o id não abriria porta nenhuma. A descoberta ainda tem a vantagem
# de continuar certa se alguma base for recriada.
PAI = "CELEIRO · Recursos"
FILHA = "Finanças"
# Sobrescreva para ensaiar o roteiro numa página de rascunho antes de encostar
# na página real; sem isso o alvo é sempre a página de verdade.
PAGINA_ENSAIO = os.environ.get("SOP_NOTION_PAGINA_FINANCAS", "")

TITULO_TOGGLE = "Abrir as bases direto no Notion"
LEGENDA = "Somente leitura. Para criar, editar ou excluir, use as bases abaixo."


def chamar(caminho: str, corpo=None, metodo="GET") -> dict:
    token = Config.do_ambiente().notion_token
    if not token:
        raise SystemExit(
            "ERRO: token do Notion ausente. Defina NOTION_TOKEN ou NOTION_TOKEN_PATH."
        )
    req = urllib.request.Request(
        BASE + caminho,
        data=json.dumps(corpo).encode("utf-8") if corpo is not None else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": VERSAO,
            "Content-Type": "application/json",
        },
        method=metodo,
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def filhos(bloco_id: str) -> list[dict]:
    saida, cursor = [], None
    while True:
        sufixo = f"?page_size=100{f'&start_cursor={cursor}' if cursor else ''}"
        d = chamar(f"/blocks/{bloco_id}/children{sufixo}")
        saida.extend(d.get("results", []))
        if not d.get("has_more"):
            return saida
        cursor = d.get("next_cursor")


def arvore(bloco_id: str) -> list[dict]:
    """Árvore de blocos, para o backup ficar restaurável e não só descritivo."""
    saida = []
    for b in filhos(bloco_id):
        item = dict(b)
        if b.get("has_children") and b["type"] not in ("child_page", "child_database"):
            item["_filhos"] = arvore(b["id"])
        saida.append(item)
    return saida


def titulo_da_pagina(pagina: dict) -> str:
    for prop in pagina.get("properties", {}).values():
        if prop.get("type") == "title":
            return "".join(z.get("plain_text", "") for z in prop.get("title", []))
    return ""


def achar_pagina() -> str:
    """Localiza `CELEIRO · Recursos › Finanças` pelo título, sem id no código."""
    achados = []
    for r in chamar("/search", {"query": FILHA, "page_size": 100}, "POST").get("results", []):
        pai = r.get("parent", {})
        if r.get("object") != "page" or titulo_da_pagina(r) != FILHA:
            continue
        if pai.get("type") != "page_id":
            continue
        if titulo_da_pagina(chamar(f"/pages/{pai['page_id']}")) == PAI:
            achados.append(r["id"])
    if len(achados) != 1:
        raise SystemExit(
            f"ERRO: esperava exatamente 1 página '{PAI} › {FILHA}', achei {len(achados)}. "
            "Nada foi alterado."
        )
    return achados[0]


@dataclass
class Alvo:
    pagina: str
    ensaio: bool
    blocos: list
    bases: dict  # id do child_database -> título
    lista_seca: dict | None  # parágrafo antigo com os links diretos


def carregar_alvo() -> Alvo:
    pagina = PAGINA_ENSAIO or achar_pagina()
    blocos = filhos(pagina)
    bases = {
        b["id"]: b["child_database"].get("title", "")
        for b in blocos
        if b["type"] == "child_database"
    }
    # A lista seca é o último parágrafo da página que carrega links.
    lista = None
    for b in blocos:
        if b["type"] == "paragraph" and any(
            z.get("href") for z in b["paragraph"]["rich_text"]
        ):
            lista = b
    return Alvo(pagina, bool(PAGINA_ENSAIO), blocos, bases, lista)


def fazer_backup(alvo: Alvo) -> pathlib.Path:
    destino = RAIZ / "backups"
    destino.mkdir(exist_ok=True)
    carimbo = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    caminho = destino / f"notion-financas-{carimbo}.json"
    caminho.write_text(
        json.dumps(
            {"pagina": chamar(f"/pages/{alvo.pagina}"), "blocos": arvore(alvo.pagina)},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    return caminho


def texto(pedacos) -> list[dict]:
    return [
        {"type": "text", "text": {"content": c, "link": {"url": u} if u else None}}
        for c, u in pedacos
    ]


def recriar(rich_text: list[dict]) -> list[dict]:
    """Reconstrói rich_text da API no formato aceito na escrita, com os links."""
    return texto([(z.get("plain_text", ""), z.get("href")) for z in rich_text])


def bloco_embed(url: str) -> dict:
    return {"object": "block", "type": "embed", "embed": {"url": url}}


def bloco_toggle(alvo: Alvo) -> dict:
    if alvo.lista_seca is None:
        raise SystemExit(
            "ERRO: não achei na página o parágrafo com os links diretos das bases, "
            "e não invento links de fallback. Nada foi alterado."
        )
    return {
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": texto([(TITULO_TOGGLE, None)]),
            "color": "gray",
            "children": [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": texto([(LEGENDA, None)])},
                },
                {
                    "object": "block",
                    "type": "paragraph",
                    # Os links vão preservados como estavam, não reescritos:
                    # o fallback precisa apontar exatamente para onde apontava.
                    "paragraph": {
                        "rich_text": recriar(alvo.lista_seca["paragraph"]["rich_text"])
                    },
                },
            ],
        },
    }


def url_viva(url: str) -> None:
    """Recusa embutir URL que não responde: embed quebrado é pior que lista seca."""
    if not url.startswith("https://"):
        raise SystemExit(f"ERRO: a URL precisa ser https. Recebido: {url}")
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            if r.status != 200:
                raise SystemExit(f"ERRO: {url} respondeu {r.status}, não 200.")
    except urllib.error.URLError as e:
        raise SystemExit(f"ERRO: {url} não respondeu ({e}). Nada foi alterado.")


def eh_toggle_fallback(b: dict) -> bool:
    return b["type"] == "toggle" and TITULO_TOGGLE in "".join(
        z.get("plain_text", "") for z in b["toggle"]["rich_text"]
    )


def aplicar(alvo: Alvo, url: str) -> None:
    embeds = [b for b in alvo.blocos if b["type"] == "embed"]
    if embeds:  # idempotência: atualiza o que já existe em vez de empilhar outro
        for b in embeds:
            chamar(f"/blocks/{b['id']}", {"embed": {"url": url}}, "PATCH")
        print(f"  embed atualizado ({len(embeds)}) para {url}")
    else:
        ancora = alvo.blocos[0]["id"]  # logo abaixo do título "Finanças"
        chamar(
            f"/blocks/{alvo.pagina}/children",
            {"children": [bloco_embed(url)], "after": ancora},
            "PATCH",
        )
        print(f"  embed inserido abaixo do título: {url}")

    atuais = filhos(alvo.pagina)
    if any(eh_toggle_fallback(b) for b in atuais):
        print("  toggle de fallback já existia, mantido")
    else:
        embed_id = next(b["id"] for b in atuais if b["type"] == "embed")
        chamar(
            f"/blocks/{alvo.pagina}/children",
            {"children": [bloco_toggle(alvo)], "after": embed_id},
            "PATCH",
        )
        print("  toggle de fallback criado logo abaixo do embed")

    if alvo.lista_seca is not None:
        chamar(f"/blocks/{alvo.lista_seca['id']}", {"archived": True}, "PATCH")
        print("  lista seca antiga arquivada (recuperável na lixeira do Notion)")
    else:
        print("  lista seca antiga já não estava na página")


def conferir(alvo: Alvo, url: str, icone_antes: dict | None = None) -> bool:
    atuais = filhos(alvo.pagina)
    pagina = chamar(f"/pages/{alvo.pagina}")
    tipos = [b["type"] for b in atuais]
    problemas = []

    embeds = [b for b in atuais if b["type"] == "embed"]
    if len(embeds) != 1:
        problemas.append(f"esperava 1 embed, achei {len(embeds)}")
    elif embeds[0]["embed"].get("url") != url:
        problemas.append(f"embed aponta para {embeds[0]['embed'].get('url')}")

    toggles = [b for b in atuais if eh_toggle_fallback(b)]
    if len(toggles) != 1:
        problemas.append(f"esperava 1 toggle de fallback, achei {len(toggles)}")
    else:
        hrefs = " ".join(
            z.get("href") or ""
            for filho in arvore(toggles[0]["id"])
            for z in filho.get("paragraph", {}).get("rich_text", [])
        ).replace("-", "")
        # Cada base DEMO da página precisa continuar alcançável pelo fallback.
        for bid, nome in alvo.bases.items():
            if bid.replace("-", "") not in hrefs:
                problemas.append(f"toggle não linka a base {nome!r}")
        if not alvo.bases and not hrefs.strip():
            problemas.append("toggle de fallback sem nenhum link")

    presentes = {b["id"] for b in atuais}
    for bid, nome in alvo.bases.items():
        if bid not in presentes:
            problemas.append(f"base DEMO sumiu da página: {nome}")

    if any(b["type"] == "paragraph" and b["id"] == (alvo.lista_seca or {}).get("id") for b in atuais):
        problemas.append("a lista seca antiga ainda está na página")
    if icone_antes is not None and pagina.get("icon") != icone_antes:
        problemas.append("o ícone da página mudou")
    if "image" in tipos:
        print("  aviso: a página tem imagem; o script não a altera")

    print("  ordem final:", " › ".join(tipos))
    print(f"  bases DEMO preservadas: {len(alvo.bases)}")
    for p in problemas:
        print("  FALHA:", p)
    if not problemas:
        print("  conferência OK: embed, toggle de fallback e bases DEMO no lugar")
    return not problemas


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("url", help="URL pública do dashboard DEMO na Vercel")
    ap.add_argument(
        "--conferir",
        action="store_true",
        help="apenas confere o estado da página, sem alterar nada",
    )
    args = ap.parse_args()
    url = args.url.rstrip("/")
    alvo = carregar_alvo()

    if args.conferir:
        return 0 if conferir(alvo, url) else 1

    print(f"1. verificando {url}")
    url_viva(url)
    print("   responde 200")
    print("2. backup da página")
    icone = chamar(f"/pages/{alvo.pagina}").get("icon")
    print("   gravado em", fazer_backup(alvo).relative_to(RAIZ))
    print("3. aplicando")
    aplicar(alvo, url)
    print("4. conferindo")
    return 0 if conferir(alvo, url, icone_antes=icone) else 1


if __name__ == "__main__":
    sys.exit(main())
