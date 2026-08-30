"""Adaptador Notion estritamente limitado às fontes DEMO da nota."""
from __future__ import annotations
from decimal import Decimal
import os
from typing import Any

from .notion import ClienteNotion
from ..nota_demo import ItemNota, Nota


def _texto(prop: dict) -> str:
    seq = prop.get(prop.get("type", ""), []) or []
    return "".join(x.get("plain_text", "") for x in seq)


class BancoNotionNotaDemo:
    def __init__(self, cliente: ClienteNotion, lancamentos_id: str, ingredientes_id: str) -> None:
        if os.environ.get("SABIA_DEMO") != "1":
            raise RuntimeError("nota de mercado bloqueada fora do ambiente DEMO")
        if not lancamentos_id or not ingredientes_id:
            raise RuntimeError("ids das fontes DEMO não configurados")
        self.c = cliente; self.lancamentos = lancamentos_id; self.ingredientes = ingredientes_id

    def _query(self, fonte: str, filtro: dict) -> list[dict]:
        # O cliente compartilhado usa Notion-Version 2022-06-28, portanto os
        # ids configurados aqui são database_ids (não data_source_ids novos).
        return self.c._chamar("POST", f"/databases/{fonte}/query", {"filter": filtro, "page_size": 5}).get("results", [])

    def achar_lancamento(self, fingerprint: str) -> dict | None:
        rows = self._query(self.lancamentos, {"property": "Observação", "rich_text": {"contains": f"fp:{fingerprint}"}})
        return rows[0] if rows else None

    def criar_lancamento(self, nota: Nota) -> str:
        nomes = ", ".join(i.nome for i in nota.itens)
        props = {
            "Lançamento": {"title": [{"text": {"content": f"DEMO — Nota de mercado {nota.data:%d/%m/%Y}"}}]},
            "Tipo": {"select": {"name": "Despesa"}}, "Data": {"date": {"start": nota.data.isoformat()}},
            "Valor": {"number": float(nota.total)}, "Status": {"select": {"name": "Realizado"}},
            "Dados de demonstração": {"checkbox": True},
            "Observação": {"rich_text": [{"text": {"content": f"DEMO — DADO FICTÍCIO. fp:{nota.fingerprint}. Itens: {nomes}"}}]},
        }
        return self.c._chamar("POST", "/pages", {"parent": {"database_id": self.lancamentos}, "properties": props})["id"]

    def achar_ingrediente(self, chave: str) -> dict | None:
        # Correspondência somente por chave exata. Registros antigos sem chave
        # não são fundidos por similaridade.
        rows = self._query(self.ingredientes, {"property": "Chave DEMO", "rich_text": {"equals": chave}})
        return rows[0] if rows else None

    def criar_ingrediente(self, item: ItemNota) -> str:
        props = {"Ingredient": {"title": [{"text": {"content": f"DEMO — {item.nome}"}}]},
                 "Status": {"select": {"name": "No Estoque"}},
                 "Chave DEMO": {"rich_text": [{"text": {"content": item.chave}}]},
                 "Quantidade DEMO": {"number": float(item.quantidade)},
                 "Unidade DEMO": {"select": {"name": item.unidade}},
                 "Dados de demonstração": {"checkbox": True}}
        return self.c._chamar("POST", "/pages", {"parent": {"database_id": self.ingredientes}, "properties": props})["id"]

    def atualizar_ingrediente(self, pagina: dict, item: ItemNota) -> None:
        atual = pagina["properties"].get("Quantidade DEMO", {}).get("number") or 0
        props = {"Quantidade DEMO": {"number": float(Decimal(str(atual)) + item.quantidade)}, "Status": {"select": {"name": "No Estoque"}}}
        self.c._chamar("PATCH", f"/pages/{pagina['id']}", {"properties": props})

    def restaurar_ingrediente(self, pagina: dict) -> None:
        p = pagina["properties"]; status = p.get("Status", {}).get("select")
        props: dict[str, Any] = {"Quantidade DEMO": {"number": p.get("Quantidade DEMO", {}).get("number")}}
        props["Status"] = {"select": {"name": status["name"]} if status else None}
        self.c._chamar("PATCH", f"/pages/{pagina['id']}", {"properties": props})

    def arquivar(self, pagina_id: str) -> None:
        self.c._chamar("PATCH", f"/pages/{pagina_id}", {"archived": True})
