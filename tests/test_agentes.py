"""Os sete agentes do Jardim e suas definições.

Cada um é uma função cognitiva, não uma página: planejar, executar, guardar,
cuidar, lembrar, crescer e avisar. A Sábia orquestra e mora fora do roteamento.
"""

from __future__ import annotations

AGENTES_ESPERADOS = {
    "raposa",
    "abelha",
    "esquilo",
    "cervo",
    "elefante",
    "borboleta",
    "beija-flor",
}


def test_carrega_exatamente_os_sete_agentes(registro):
    assert set(registro.nomes()) == AGENTES_ESPERADOS


def test_todo_agente_tem_prompt_e_dominio(registro):
    for agente in registro:
        assert agente.dominio, f"{agente.nome} sem domínio"
        assert len(agente.prompt) > 200, f"{agente.nome} com prompt curto demais"
        assert agente.categorias, f"{agente.nome} sem categorias"


def test_os_oito_agentes_nao_inventam_nem_silenciam_lacunas(registro):
    from sop.agentes import carregar_orquestradora

    agentes = [*registro, carregar_orquestradora()]
    assert len(agentes) == 8
    for agente in agentes:
        prompt = " ".join(agente.prompt.lower().split())
        assert "nunca invente" in prompt, agente.nome
        assert "lacuna" in prompt, agente.nome
        assert "pergunt" in prompt, agente.nome
        assert "uma ou duas perguntas" in prompt, agente.nome


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
        "borboleta": ("🦋", "crescer"),
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
    """Bloco de estudo virou evento da Borboleta; o Elefante saiu da agenda.

    Sem estudo, o Elefante não tem nada com hora marcada: documento e registro
    entram no banco, não no calendário.
    """
    com_agenda = {a.nome for a in registro if a.cria_evento}
    assert com_agenda == {"beija-flor", "raposa", "borboleta"}


def test_busca_por_categoria(registro):
    assert registro.por_categoria("gasto").nome == "esquilo"
    assert registro.por_categoria("compras").nome == "esquilo"
    assert registro.por_categoria("cardapio").nome == "cervo"
    assert registro.por_categoria("familia").nome == "cervo"
    assert registro.por_categoria("rotina").nome == "abelha"
    assert registro.por_categoria("flashcard").nome == "borboleta"
    assert registro.por_categoria("inexistente") is None


def test_aprendizado_e_da_borboleta_e_memoria_e_do_elefante(registro):
    """A divisão pedida pela Bruna em 29/08/2026: crescer separado de lembrar.

    Antes o Elefante acumulava as duas funções. Educação, estudo e curso são da
    Borboleta; documento, decisão e histórico ficam com o Elefante.
    """
    for categoria in ("estudo", "material", "flashcard", "curso", "aprendizado"):
        assert registro.por_categoria(categoria).nome == "borboleta", categoria

    for categoria in ("documento", "registro"):
        assert registro.por_categoria(categoria).nome == "elefante", categoria

    elefante = registro.obter("elefante")
    assert not any(
        elefante.aceita(c)
        for c in ("estudo", "material", "flashcard", "curso", "aprendizado")
    )
    assert "estudo" not in elefante.dominio


def test_registro_suporta_operador_in(registro):
    assert "esquilo" in registro
    assert "juridico" not in registro
