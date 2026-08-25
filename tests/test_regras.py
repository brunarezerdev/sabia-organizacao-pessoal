"""Testes do motor de regras se-então. Nenhuma API é chamada aqui."""

from __future__ import annotations

from datetime import date

import pytest

from sop.regras import (
    EventoAgenda,
    ItemEstoque,
    MotorDeRegras,
    Regra,
    estoque_de_lista,
    eventos_do_google,
    normalizar,
    regras_de_lista,
    regras_do_notion,
)

REGRA_CONSULTA = Regra(
    nome="Consulta médica pede dinheiro em mãos",
    se="Há uma consulta médica marcada na agenda",
    entao=(
        "Separar o valor em dinheiro antes do dia. "
        "Se o dinheiro não estiver disponível, gerar a tarefa de pedir para alguém sacar."
    ),
    area="Saúde",
    origem="Agenda",
    palavras_chave=("consulta", "pediatra", "dentista"),
    antecedencia_dias=2,
)

REGRA_ESCOLA = Regra(
    nome="Atividade na escola pede item",
    se="Há atividade na escola que exige levar algum item",
    entao="Separar o item com antecedência e deixar pronto para o dia.",
    area="Escola",
    origem="Agenda",
    palavras_chave=("escola", "levar para a escola"),
    antecedencia_dias=1,
)

REGRA_ESTOQUE = Regra(
    nome="Essencial acabando vai para a lista de compras",
    se="Um item essencial da lista de alimentos está acabando",
    entao="Entrar na lista de compras da semana.",
    area="Casa",
    origem="Estoque",
    palavras_chave=("acabando", "acabou", "sobrou pouco"),
)


# -- normalização e casamento de termos -------------------------------------


def test_normalizar_tira_acento_caixa_e_espaco_sobrando():
    assert normalizar("  Consulta   MÉDICA  ") == "consulta medica"


@pytest.mark.parametrize(
    "titulo",
    ["Consulta com a pediatra", "CONSULTA no posto", "consulta médica de rotina"],
)
def test_regra_reconhece_o_gatilho_mesmo_sem_acento_ou_com_caixa(titulo):
    assert REGRA_CONSULTA.casa_com(titulo)


def test_regra_nao_dispara_em_palavra_parecida():
    # "consultoria" contém "consult", mas não é "consulta".
    assert not REGRA_CONSULTA.casa_com("Consultoria de marketing")


def test_termo_com_mais_de_uma_palavra_e_procurado_como_frase():
    # "Nina" é um nome fictício, só para mostrar a diferença entre frase e palavra.
    regra = Regra(nome="x", se="", entao="Fazer.", palavras_chave=("escola da nina",))
    assert regra.casa_com("Escola da Nina, levar garrafa PET")
    assert not regra.casa_com("Aniversário da Nina")


def test_regra_sem_palavra_chave_nunca_dispara():
    regra = Regra(nome="x", se="", entao="Fazer.", palavras_chave=())
    assert not regra.casa_com("qualquer coisa")


# -- quebra do Então em efeitos ---------------------------------------------


def test_cada_frase_do_entao_vira_uma_acao():
    acoes = REGRA_CONSULTA.acoes()
    assert len(acoes) == 2


def test_frase_que_comeca_com_se_e_efeito_de_segunda_ordem():
    acoes = REGRA_CONSULTA.acoes()
    assert acoes[0][1] == 1
    assert acoes[1][1] == 2


def test_entao_vazio_nao_gera_acao():
    assert Regra(nome="x", se="", entao="").acoes() == []


# -- prazos ------------------------------------------------------------------


def test_prazo_recua_pela_antecedencia():
    assert REGRA_CONSULTA.prazo_para(date(2026, 3, 12)) == "2026-03-10"


def test_antecedencia_zero_mantem_o_proprio_dia():
    assert REGRA_ESTOQUE.prazo_para(date(2026, 3, 12)) == "2026-03-12"


# -- o motor cruzando agenda -------------------------------------------------


def test_consulta_na_agenda_gera_as_duas_tarefas_do_efeito_borboleta():
    motor = MotorDeRegras([REGRA_CONSULTA])
    evento = EventoAgenda(titulo="Consulta com a pediatra", data="2026-03-12")

    tarefas = motor.aplicar_agenda([evento])

    assert len(tarefas) == 2
    direta, condicional = tarefas
    assert direta.titulo.startswith("Separar o valor em dinheiro")
    assert direta.prazo == "2026-03-10"
    assert not direta.condicional
    assert condicional.condicional
    assert "sacar" in condicional.titulo
    # As duas apontam de volta para o compromisso que as criou.
    assert direta.gatilho == "Consulta com a pediatra, 2026-03-12"
    assert direta.regra == REGRA_CONSULTA.nome
    assert direta.area == "Saúde"


def test_evento_sem_relacao_nao_gera_tarefa():
    motor = MotorDeRegras([REGRA_CONSULTA, REGRA_ESCOLA])
    evento = EventoAgenda(titulo="Aula de natação", data="2026-03-11")
    assert motor.aplicar_agenda([evento]) == []


def test_regra_desligada_e_ignorada():
    parada = Regra(
        nome="parada", se="", entao="Fazer.", palavras_chave=("consulta",), ativa=False
    )
    motor = MotorDeRegras([parada])
    evento = EventoAgenda(titulo="Consulta com a pediatra", data="2026-03-12")
    assert motor.aplicar_agenda([evento]) == []


def test_a_descricao_do_evento_tambem_e_lida():
    motor = MotorDeRegras([REGRA_ESCOLA])
    evento = EventoAgenda(
        titulo="Feira de ciências",
        data="2026-03-10",
        descricao="Levar para a escola uma garrafa PET",
    )
    assert len(motor.aplicar_agenda([evento])) == 1


def test_tarefas_saem_ordenadas_por_prazo_e_depois_por_ordem_do_efeito():
    motor = MotorDeRegras([REGRA_CONSULTA, REGRA_ESCOLA])
    eventos = [
        EventoAgenda(titulo="Consulta com a pediatra", data="2026-03-12"),
        EventoAgenda(titulo="Escola, levar garrafa PET", data="2026-03-10"),
    ]
    tarefas = motor.aplicar_agenda(eventos)
    assert [t.prazo for t in tarefas] == ["2026-03-09", "2026-03-10", "2026-03-10"]
    assert [t.ordem for t in tarefas] == [1, 1, 2]


# -- o motor cruzando estoque ------------------------------------------------


def test_essencial_acabando_vira_tarefa_de_compra():
    motor = MotorDeRegras([REGRA_ESTOQUE])
    itens = [
        ItemEstoque(nome="Arroz", situacao="acabando"),
        ItemEstoque(nome="Feijão", situacao="ok"),
    ]
    tarefas = motor.aplicar_estoque(itens, em="2026-03-09")
    assert len(tarefas) == 1
    assert tarefas[0].titulo.endswith("Arroz")
    assert tarefas[0].prazo == "2026-03-09"


def test_item_nao_essencial_acabando_nao_alerta():
    motor = MotorDeRegras([REGRA_ESTOQUE])
    itens = [ItemEstoque(nome="Chocolate em pó", situacao="acabou", essencial=False)]
    assert motor.aplicar_estoque(itens) == []


def test_regra_de_estoque_nao_e_aplicada_na_agenda_e_vice_versa():
    motor = MotorDeRegras([REGRA_ESTOQUE, REGRA_CONSULTA])
    evento = EventoAgenda(titulo="Consulta acabando de marcar", data="2026-03-12")
    # A regra de estoque tem origem "Estoque" e não entra no cruzamento de agenda.
    assert {t.regra for t in motor.aplicar_agenda([evento])} == {REGRA_CONSULTA.nome}


def test_aplicar_junta_agenda_e_estoque():
    motor = MotorDeRegras([REGRA_CONSULTA, REGRA_ESTOQUE])
    tarefas = motor.aplicar(
        eventos=[EventoAgenda(titulo="Consulta", data="2026-03-12")],
        estoque=[ItemEstoque(nome="Leite", situacao="sobrou pouco")],
        em="2026-03-09",
    )
    assert len(tarefas) == 3


# -- conversão de formatos externos -----------------------------------------


def test_evento_do_google_com_hora_e_de_dia_inteiro_viram_a_mesma_data():
    com_hora = EventoAgenda.do_google(
        {"summary": "Consulta", "start": {"dateTime": "2026-03-12T14:30:00-03:00"}}
    )
    dia_inteiro = EventoAgenda.do_google(
        {"summary": "Escola", "start": {"date": "2026-03-10"}}
    )
    assert com_hora.data == "2026-03-12"
    assert dia_inteiro.data == "2026-03-10"


def test_evento_sem_titulo_nao_quebra():
    assert EventoAgenda.do_google({"start": {"date": "2026-03-10"}}).titulo == "(sem título)"


def test_evento_sem_data_e_descartado():
    assert eventos_do_google([{"summary": "sem data", "start": {}}]) == []


def test_leitura_de_uma_linha_da_base_de_regras_do_notion():
    pagina = {
        "properties": {
            "Nome": {"type": "title", "title": [{"plain_text": "Consulta médica"}]},
            "Se": {"type": "rich_text", "rich_text": [{"plain_text": "Há consulta"}]},
            "Então": {"type": "rich_text", "rich_text": [{"plain_text": "Separar dinheiro."}]},
            "Área": {"type": "select", "select": {"name": "Saúde"}},
            "Origem": {"type": "select", "select": {"name": "Agenda"}},
            "Palavras-chave": {
                "type": "rich_text",
                "rich_text": [{"plain_text": "consulta, pediatra"}],
            },
            "Antecedência em dias": {"type": "number", "number": 2},
            "Ativa": {"type": "checkbox", "checkbox": True},
            "Observação": {"type": "rich_text", "rich_text": [{"plain_text": "exemplo"}]},
        }
    }
    regra = regras_do_notion([pagina])[0]
    assert regra.nome == "Consulta médica"
    assert regra.palavras_chave == ("consulta", "pediatra")
    assert regra.antecedencia_dias == 2
    assert regra.ativa


def test_coluna_faltando_no_notion_nao_derruba_a_leitura():
    # Uma coluna renomeada à mão não pode quebrar o domingo de ninguém.
    regra = Regra.da_pagina_notion({"properties": {}})
    assert regra.nome == ""
    assert regra.antecedencia_dias == 0
    assert regra.acoes() == []


def test_select_vazio_no_notion_vira_texto_vazio():
    pagina = {"properties": {"Área": {"type": "select", "select": None}}}
    assert Regra.da_pagina_notion(pagina).area == ""


def test_regras_de_lista_aceita_palavras_chave_como_string_ou_lista():
    por_string = regras_de_lista([{"nome": "a", "palavras_chave": "x, y"}])[0]
    por_lista = regras_de_lista([{"nome": "b", "palavras_chave": ["x", "y"]}])[0]
    assert por_string.palavras_chave == por_lista.palavras_chave == ("x", "y")


def test_estoque_de_lista_assume_essencial_por_padrao():
    assert estoque_de_lista([{"nome": "Arroz"}])[0].essencial
