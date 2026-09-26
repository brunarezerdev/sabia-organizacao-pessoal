"""Contrato da priorização automática das tarefas pessoais."""

from pathlib import Path

import pytest

from sop.prioridades import (
    PROPRIEDADE_CONCLUSAO,
    PROPRIEDADE_EISENHOWER,
    PROPRIEDADE_REGISTRO,
    QUADRANTES,
    preparar_base,
    propriedades_eisenhower,
)


RAIZ = Path(__file__).resolve().parents[1]
ALMA = (RAIZ / "sabia/orquestradora.md").read_text(encoding="utf-8")


def _database() -> dict:
    propriedades = propriedades_eisenhower()
    for valor in propriedades.values():
        valor["type"] = next(iter(valor))
    return {"properties": propriedades}


class NotionFalso:
    def __init__(self, database: dict | None = None) -> None:
        self.database = database or {"properties": {}}
        self.chamadas: list[tuple[str, str, dict | None]] = []

    def _chamar(self, metodo: str, caminho: str, corpo: dict | None = None) -> dict:
        self.chamadas.append((metodo, caminho, corpo))
        if metodo == "PATCH":
            for nome, valor in (corpo or {}).get("properties", {}).items():
                valor = dict(valor)
                valor["type"] = next(iter(valor))
                self.database.setdefault("properties", {})[nome] = valor
        return self.database


def test_esquema_tem_quatro_quadrantes_legiveis_e_duas_datas():
    propriedades = propriedades_eisenhower()
    opcoes = propriedades[PROPRIEDADE_EISENHOWER]["select"]["options"]
    assert tuple(opcao["name"] for opcao in opcoes) == QUADRANTES
    assert propriedades[PROPRIEDADE_REGISTRO] == {"created_time": {}}
    assert propriedades[PROPRIEDADE_CONCLUSAO] == {"date": {}}


def test_preparo_e_idempotente_quando_esquema_ja_existe():
    notion = NotionFalso(_database())
    preparar_base(notion, "tarefas")
    assert [metodo for metodo, _, _ in notion.chamadas] == ["GET", "GET"]


def test_preparo_recusa_sobrescrever_coluna_de_tipo_errado():
    notion = NotionFalso(
        {"properties": {PROPRIEDADE_EISENHOWER: {"type": "rich_text"}}}
    )
    with pytest.raises(RuntimeError, match="tipo incompatível"):
        preparar_base(notion, "tarefas")
    assert all(metodo != "PATCH" for metodo, _, _ in notion.chamadas)


def test_sabia_classifica_no_registro_e_explica_suposição_conservadora():
    for quadrante in QUADRANTES:
        assert f"`{quadrante}`" in ALMA
    assert "pedido explícito para registrar, anotar ou adicionar" in ALMA
    assert "Use o texto original da Bruna" in ALMA
    assert "urgência incerta como urgente" in ALMA
    assert "importância incerta como importante" in ALMA
    assert "Nunca esconda a suposição" in ALMA


def test_correcao_e_conclusao_atualizam_a_mesma_linha():
    assert "atualize a linha existente, sem criar" in ALMA
    assert "`Concluída em` com a data de hoje" in ALMA
    assert "limpe `Concluída em`" in ALMA
    assert "Se mais de uma casar" in ALMA


def test_tarefa_pessoal_nao_vai_para_dashboard_ou_log():
    assert "Nunca copie essas tarefas para o dashboard público" in ALMA
    assert "para memória ou para logs" in ALMA
