"""Leitura e cálculos do dashboard financeiro estritamente DEMO."""
from __future__ import annotations
from collections import defaultdict
from typing import Any


def filtrar(linhas: list[dict], mes="", tipo="", categoria="", status="") -> list[dict]:
    return [x for x in linhas if
            (not mes or x.get("data", "").startswith(mes)) and
            (not tipo or x.get("tipo") == tipo) and
            (not categoria or x.get("categoria") == categoria) and
            (not status or x.get("status") == status)]


def resumir(linhas: list[dict], orcamentos: list[dict]) -> dict[str, Any]:
    receitas = sum(x["valor"] for x in linhas if x["tipo"] == "Receita")
    despesas = sum(x["valor"] for x in linhas if x["tipo"] == "Despesa")
    limite = sum(x["limite"] for x in orcamentos)
    categorias: dict[str, float] = defaultdict(float)
    evolucao: dict[str, float] = defaultdict(float)
    for x in linhas:
        if x["tipo"] == "Despesa": categorias[x["categoria"]] += x["valor"]
        evolucao[x["data"][:7]] += x["valor"] * (1 if x["tipo"] == "Receita" else -1)
    return {"receitas": receitas, "despesas": despesas, "saldo": receitas-despesas,
            "orcamento": limite, "categorias": dict(sorted(categorias.items())),
            "evolucao": dict(sorted(evolucao.items()))}


def validar_demo(pagina: dict) -> None:
    if pagina.get("properties", {}).get("Dados de demonstração", {}).get("checkbox") is not True:
        raise PermissionError("registro não DEMO recusado")
