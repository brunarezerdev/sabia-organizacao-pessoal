"""Contrato da Matriz de Eisenhower na base pessoal de tarefas.

O modelo faz a classificação semântica a partir da mensagem. Este módulo cuida
somente do esquema verificável do Notion, sem ler nem registrar conteúdo das
tarefas.
"""

from __future__ import annotations

from typing import Any, Protocol


PROPRIEDADE_EISENHOWER = "Prioridade (Eisenhower)"
PROPRIEDADE_REGISTRO = "Registrada em"
PROPRIEDADE_CONCLUSAO = "Concluída em"

QUADRANTES = (
    "Urgente e importante",
    "Importante e não urgente",
    "Urgente e não importante",
    "Nem urgente nem importante",
)

CORES = ("red", "blue", "orange", "gray")


class ClienteNotionEsquema(Protocol):
    def _chamar(
        self, metodo: str, caminho: str, corpo: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...


def propriedades_eisenhower() -> dict[str, Any]:
    """Propriedades adicionadas sem tocar nas colunas já existentes."""
    return {
        PROPRIEDADE_EISENHOWER: {
            "select": {
                "options": [
                    {"name": nome, "color": cor}
                    for nome, cor in zip(QUADRANTES, CORES, strict=True)
                ]
            }
        },
        # created_time é retroativo e imutável: também dá uma data de registro
        # verdadeira às tarefas antigas, sem inventar um backfill.
        PROPRIEDADE_REGISTRO: {"created_time": {}},
        PROPRIEDADE_CONCLUSAO: {"date": {}},
    }


def validar_esquema(database: dict[str, Any]) -> None:
    """Recusa tipos errados e opções incompletas antes de declarar sucesso."""
    propriedades = database.get("properties", {})
    tipos = {
        PROPRIEDADE_EISENHOWER: "select",
        PROPRIEDADE_REGISTRO: "created_time",
        PROPRIEDADE_CONCLUSAO: "date",
    }
    erros = [
        f"{nome}: esperado {tipo}, encontrado "
        f"{propriedades.get(nome, {}).get('type', 'ausente')}"
        for nome, tipo in tipos.items()
        if propriedades.get(nome, {}).get("type") != tipo
    ]

    opcoes = propriedades.get(PROPRIEDADE_EISENHOWER, {}).get("select", {}).get(
        "options", []
    )
    nomes = {opcao.get("name") for opcao in opcoes}
    faltantes = [quadrante for quadrante in QUADRANTES if quadrante not in nomes]
    if faltantes:
        erros.append("quadrantes ausentes: " + ", ".join(faltantes))

    if erros:
        raise RuntimeError("Esquema incompatível em Prazos e tarefas: " + "; ".join(erros))


def preparar_base(cliente: ClienteNotionEsquema, database_id: str) -> dict[str, Any]:
    """Adiciona o esquema de modo idempotente e o relê para validar."""
    atual = cliente._chamar("GET", f"/databases/{database_id}")
    propriedades = atual.get("properties", {})
    tipos_esperados = {
        PROPRIEDADE_EISENHOWER: "select",
        PROPRIEDADE_REGISTRO: "created_time",
        PROPRIEDADE_CONCLUSAO: "date",
    }
    conflitos = [
        nome
        for nome, tipo in tipos_esperados.items()
        if nome in propriedades and propriedades[nome].get("type") != tipo
    ]
    if conflitos:
        raise RuntimeError(
            "Não alterei propriedades com tipo incompatível: " + ", ".join(conflitos)
        )

    completo = True
    try:
        validar_esquema(atual)
    except RuntimeError:
        completo = False

    if not completo:
        cliente._chamar(
            "PATCH",
            f"/databases/{database_id}",
            {"properties": propriedades_eisenhower()},
        )

    conferida = cliente._chamar("GET", f"/databases/{database_id}")
    validar_esquema(conferida)
    return conferida
