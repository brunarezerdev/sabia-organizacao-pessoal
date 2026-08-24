"""Os cinco agentes de organização pessoal e suas definições."""

from __future__ import annotations

AGENTES_ESPERADOS = {
    "secretaria",
    "lifestyle",
    "financeira",
    "projetos",
    "educacional",
}


def test_carrega_exatamente_os_cinco_agentes(registro):
    assert set(registro.nomes()) == AGENTES_ESPERADOS


def test_todo_agente_tem_prompt_e_dominio(registro):
    for agente in registro:
        assert agente.dominio, f"{agente.nome} sem domínio"
        assert len(agente.prompt) > 200, f"{agente.nome} com prompt curto demais"
        assert agente.categorias, f"{agente.nome} sem categorias"


def test_categorias_nao_se_sobrepoem(registro):
    """Cada categoria pertence a um único agente — senão o roteamento é ambíguo."""
    vistas: dict[str, str] = {}
    for agente in registro:
        for categoria in agente.categorias:
            assert categoria not in vistas, (
                f"categoria '{categoria}' em {agente.nome} e {vistas[categoria]}"
            )
            vistas[categoria] = agente.nome


def test_agentes_de_agenda_sao_os_esperados(registro):
    com_agenda = {a.nome for a in registro if a.cria_evento}
    assert com_agenda == {"secretaria", "projetos", "educacional"}


def test_busca_por_categoria(registro):
    assert registro.por_categoria("gasto").nome == "financeira"
    assert registro.por_categoria("compras").nome == "lifestyle"
    assert registro.por_categoria("flashcard").nome == "educacional"
    assert registro.por_categoria("inexistente") is None


def test_registro_suporta_operador_in(registro):
    assert "financeira" in registro
    assert "juridico" not in registro
