"""Os seis agentes do Jardim e suas definições.

Cada um é uma função cognitiva, não uma página: planejar, executar, guardar,
cuidar, lembrar e avisar. A Sábia orquestra e mora fora do roteamento.
"""

from __future__ import annotations

AGENTES_ESPERADOS = {
    "raposa",
    "abelha",
    "esquilo",
    "cervo",
    "elefante",
    "beija-flor",
}


def test_carrega_exatamente_os_seis_agentes(registro):
    assert set(registro.nomes()) == AGENTES_ESPERADOS


def test_todo_agente_tem_prompt_e_dominio(registro):
    for agente in registro:
        assert agente.dominio, f"{agente.nome} sem domínio"
        assert len(agente.prompt) > 200, f"{agente.nome} com prompt curto demais"
        assert agente.categorias, f"{agente.nome} sem categorias"


def test_todo_agente_tem_o_animal_e_a_palavra_chave(registro):
    """A identidade da Sábia é a arquitetura, não enfeite.

    Cada agente carrega o emoji do seu animal e a palavra-chave da sua função
    cognitiva. Trocar um dos dois sem querer descola a camada de agentes da
    identidade que o resto do sistema apresenta.
    """
    palavras = {
        "raposa": ("🦊", "planejar"),
        "abelha": ("🐝", "fazer"),
        "esquilo": ("🐿️", "guardar"),
        "cervo": ("🦌", "cuidar"),
        "elefante": ("🐘", "lembrar"),
        "beija-flor": ("🐦", "avisar"),
    }
    for nome, (emoji, palavra) in palavras.items():
        agente = registro.obter(nome)
        assert agente is not None, f"{nome} não foi carregado"
        assert agente.emoji == emoji, f"{nome} com emoji errado"
        assert f"**{palavra}**" in agente.prompt, f"{nome} sem a palavra-chave"


def test_categorias_nao_se_sobrepoem(registro):
    """Cada categoria pertence a um único agente, senão o roteamento é ambíguo."""
    vistas: dict[str, str] = {}
    for agente in registro:
        for categoria in agente.categorias:
            assert categoria not in vistas, (
                f"categoria '{categoria}' em {agente.nome} e {vistas[categoria]}"
            )
            vistas[categoria] = agente.nome


def test_agentes_de_agenda_sao_os_esperados(registro):
    com_agenda = {a.nome for a in registro if a.cria_evento}
    assert com_agenda == {"beija-flor", "raposa", "elefante"}


def test_busca_por_categoria(registro):
    assert registro.por_categoria("gasto").nome == "esquilo"
    assert registro.por_categoria("compras").nome == "esquilo"
    assert registro.por_categoria("cardapio").nome == "cervo"
    assert registro.por_categoria("familia").nome == "cervo"
    assert registro.por_categoria("rotina").nome == "abelha"
    assert registro.por_categoria("flashcard").nome == "elefante"
    assert registro.por_categoria("inexistente") is None


def test_registro_suporta_operador_in(registro):
    assert "esquilo" in registro
    assert "juridico" not in registro
