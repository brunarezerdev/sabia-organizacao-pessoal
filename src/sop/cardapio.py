"""Gera a lista de compras a partir do cardápio semanal do Notion.

Ingredientes são registros únicos. A automação altera o estado do registro já
existente em vez de criar cópias, por isso reexecutar a mesma semana é
idempotente. O checkbox ``Gerado pelo cardápio`` separa os itens administrados
por esta rotina dos itens que alguém acrescentou manualmente à lista.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


PROP_RECEITAS_PLANEJADAS = "📝 Recipes"
PROP_INGREDIENTES = "🥕 Ingredients"
PROP_DATA = "Date"
PROP_STATUS = "Status"
PROP_AUTOMATICO = "Gerado pelo cardápio"
STATUS_ESTOQUE = "No Estoque"
STATUS_COMPRAS = "Lista de Compras"
STATUS_FORA = "Fora de Estoque"


@dataclass(frozen=True)
class ResultadoListaCompras:
    inicio_semana: str
    fim_semana: str
    planejamentos: int
    receitas: int
    ingredientes_necessarios: int
    em_estoque: int
    para_comprar: int
    adicionados: int
    removidos: int


def _relacoes(pagina: dict[str, Any], propriedade: str) -> set[str]:
    valor = pagina.get("properties", {}).get(propriedade, {})
    return {str(item["id"]) for item in valor.get("relation", []) if item.get("id")}


def _status(pagina: dict[str, Any]) -> str | None:
    selecionado = pagina.get("properties", {}).get(PROP_STATUS, {}).get("select")
    return selecionado.get("name") if selecionado else None


def _automatico(pagina: dict[str, Any]) -> bool:
    return bool(
        pagina.get("properties", {}).get(PROP_AUTOMATICO, {}).get("checkbox", False)
    )


class BaseNaoCompartilhada(RuntimeError):
    """A base existe no Notion mas não foi compartilhada com a integração.

    O Notion responde 404 tanto para base inexistente quanto para base sem
    permissão, então a mensagem crua não distingue os dois casos e manda a
    pessoa procurar um id errado. Só quem tem a conta resolve, pela interface.
    """


def _exigir_acesso(cliente: Any, database_id: str, rotulo: str) -> dict[str, Any]:
    """Lê a base e, se o Notion negar, explica o que destrava."""
    try:
        return cliente._chamar("GET", f"/databases/{database_id}")
    except RuntimeError as erro:
        if "404" not in str(erro):
            raise
        raise BaseNaoCompartilhada(
            f"A base {rotulo} ({database_id}) não está compartilhada com a "
            "integração. No Notion, abra a base, clique nos três pontinhos, "
            "vá em Conexões e adicione a integração usada por esta rotina."
        ) from erro


def sincronizar_lista_compras(
    cliente: Any,
    planejamento_database_id: str,
    receitas_database_id: str,
    ingredientes_database_id: str,
    referencia: date | None = None,
) -> ResultadoListaCompras:
    """Sincroniza a semana de ``referencia`` e devolve contagens auditáveis."""
    _exigir_acesso(cliente, planejamento_database_id, "Planejamento de Refeições")
    _exigir_acesso(cliente, receitas_database_id, "Receitas")
    referencia = referencia or date.today()
    inicio = referencia - timedelta(days=referencia.weekday())
    fim_exclusivo = inicio + timedelta(days=7)
    filtro = {
        "and": [
            {"property": PROP_DATA, "date": {"on_or_after": inicio.isoformat()}},
            {"property": PROP_DATA, "date": {"before": fim_exclusivo.isoformat()}},
        ]
    }
    planejamentos = cliente.consultar_database(
        planejamento_database_id, filtro=filtro, limite=1000
    )
    receitas_ids: set[str] = set()
    for pagina in planejamentos:
        receitas_ids.update(_relacoes(pagina, PROP_RECEITAS_PLANEJADAS))

    receitas = cliente.consultar_database(receitas_database_id, limite=1000)
    ingredientes_ids: set[str] = set()
    for receita in receitas:
        if str(receita.get("id")) in receitas_ids:
            ingredientes_ids.update(_relacoes(receita, PROP_INGREDIENTES))

    database = _exigir_acesso(cliente, ingredientes_database_id, "Ingredientes")
    propriedades = database.get("properties", {})
    if PROP_AUTOMATICO not in propriedades:
        cliente._chamar(
            "PATCH",
            f"/databases/{ingredientes_database_id}",
            {"properties": {PROP_AUTOMATICO: {"checkbox": {}}}},
        )
    elif propriedades[PROP_AUTOMATICO].get("type") != "checkbox":
        raise RuntimeError(f"A propriedade {PROP_AUTOMATICO!r} existe e não é checkbox.")

    ingredientes = cliente.consultar_database(ingredientes_database_id, limite=1000)
    por_id = {str(item["id"]): item for item in ingredientes}
    em_estoque = {
        item_id for item_id in ingredientes_ids
        if item_id in por_id and _status(por_id[item_id]) == STATUS_ESTOQUE
    }
    comprar = {item_id for item_id in ingredientes_ids if item_id in por_id} - em_estoque

    adicionados = removidos = 0
    for item_id, item in por_id.items():
        status_atual = _status(item)
        automatico = _automatico(item)
        if item_id in comprar:
            if status_atual != STATUS_COMPRAS:
                cliente._chamar(
                    "PATCH",
                    f"/pages/{item_id}",
                    {"properties": {
                        PROP_STATUS: {"select": {"name": STATUS_COMPRAS}},
                        PROP_AUTOMATICO: {"checkbox": True},
                    }},
                )
                adicionados += 1
        elif automatico:
            propriedades = {PROP_AUTOMATICO: {"checkbox": False}}
            # Se alguém registrou a compra ou corrigiu o estoque, essa edição
            # humana vence. Só retiramos da lista o status que a própria
            # automação havia colocado.
            if status_atual == STATUS_COMPRAS:
                propriedades[PROP_STATUS] = {"select": {"name": STATUS_FORA}}
            cliente._chamar(
                "PATCH",
                f"/pages/{item_id}",
                {"properties": propriedades},
            )
            removidos += 1

    return ResultadoListaCompras(
        inicio_semana=inicio.isoformat(),
        fim_semana=(fim_exclusivo - timedelta(days=1)).isoformat(),
        planejamentos=len(planejamentos),
        receitas=len(receitas_ids),
        ingredientes_necessarios=len(ingredientes_ids),
        em_estoque=len(em_estoque),
        para_comprar=len(comprar),
        adicionados=adicionados,
        removidos=removidos,
    )
