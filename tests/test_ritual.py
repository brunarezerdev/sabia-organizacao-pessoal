"""Testes do ritual de domingo. Nenhuma API é chamada aqui."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from sop.regras import EventoAgenda, ItemEstoque, MotorDeRegras, regras_de_lista
from sop.ritual import (
    CHECKLIST_ABERTURA,
    Ritual,
    domingo_de,
    semana_que_comeca,
    semana_que_terminou,
)

RAIZ = Path(__file__).resolve().parents[1]

DOMINGO = date(2026, 3, 8)  # 2026-03-08 é domingo


@pytest.fixture
def motor():
    dados = json.loads((RAIZ / "exemplos" / "regras.json").read_text(encoding="utf-8"))
    return MotorDeRegras(regras_de_lista(dados))


class AgendaFalsa:
    """Substituto do Google Agenda: devolve eventos por intervalo pedido."""

    def __init__(self, por_intervalo):
        self.por_intervalo = por_intervalo
        self.chamadas = []

    def listar_eventos(self, inicio_iso, fim_iso, limite=50):
        self.chamadas.append((inicio_iso, fim_iso))
        return self.por_intervalo.get(inicio_iso[:10], [])


# -- limites das semanas -----------------------------------------------------


def test_semana_que_terminou_vai_de_segunda_ao_proprio_domingo():
    assert semana_que_terminou(DOMINGO) == (date(2026, 3, 2), DOMINGO)


def test_semana_que_comeca_vai_da_segunda_seguinte_ao_domingo_seguinte():
    assert semana_que_comeca(DOMINGO) == (date(2026, 3, 9), date(2026, 3, 15))


def test_domingo_de_devolve_o_proprio_dia_quando_ja_e_domingo():
    assert domingo_de(DOMINGO) == DOMINGO


def test_domingo_de_devolve_o_proximo_domingo_nos_outros_dias():
    assert domingo_de(date(2026, 3, 4)) == DOMINGO  # quarta


# -- fechamento --------------------------------------------------------------


def test_fechamento_lista_os_compromissos_da_semana_que_passou(motor):
    eventos = [
        EventoAgenda(titulo="Reunião do grupo", data="2026-03-05"),
        EventoAgenda(titulo="Entrega parcial", data="2026-03-03"),
    ]
    fechamento = Ritual(motor).fechar(DOMINGO, eventos)

    assert fechamento.periodo == "2026-03-02 a 2026-03-08"
    # Sai em ordem de data, não na ordem em que a agenda devolveu.
    assert [e.data for e in fechamento.compromissos] == ["2026-03-03", "2026-03-05"]
    assert fechamento.pergunta


def test_fechamento_nao_inventa_o_que_foi_feito(motor):
    """O sistema não sabe o que ela cumpriu, então não afirma nada sobre isso."""
    eventos = [EventoAgenda(titulo="Reunião do grupo", data="2026-03-05")]
    texto = Ritual(motor).pacote(DOMINGO, eventos_passados=eventos).para_telegram()
    assert "[ ] 2026-03-05, Reunião do grupo" in texto


# -- abertura ----------------------------------------------------------------


def test_abertura_gera_os_efeitos_dos_compromissos_da_semana(motor):
    eventos = [EventoAgenda(titulo="Consulta com a pediatra", data="2026-03-12")]
    abertura = Ritual(motor).abrir(DOMINGO, eventos)

    assert abertura.periodo == "2026-03-09 a 2026-03-15"
    assert len(abertura.efeitos) == 2
    assert any(t.condicional for t in abertura.efeitos)


def test_abertura_alerta_essenciais_acabando_com_prazo_na_segunda(motor):
    abertura = Ritual(motor).abrir(
        DOMINGO, [], estoque=[ItemEstoque(nome="Arroz", situacao="acabando")]
    )
    assert len(abertura.alertas_estoque) == 1
    assert abertura.alertas_estoque[0].prazo == "2026-03-09"


def test_checklist_de_abertura_e_sempre_o_mesmo(motor):
    assert Ritual(motor).abrir(DOMINGO, []).checklist == CHECKLIST_ABERTURA


# -- leitura da agenda -------------------------------------------------------


def test_ritual_le_a_agenda_nos_dois_intervalos_da_semana(motor):
    agenda = AgendaFalsa(
        {
            "2026-03-02": [{"summary": "Semana passada", "start": {"date": "2026-03-05"}}],
            "2026-03-09": [
                {"summary": "Consulta com a pediatra", "start": {"date": "2026-03-12"}}
            ],
        }
    )
    pacote = Ritual(motor, agenda=agenda).pacote(DOMINGO)

    assert len(agenda.chamadas) == 2
    assert pacote.fechamento.compromissos[0].titulo == "Semana passada"
    assert pacote.abertura.compromissos[0].titulo == "Consulta com a pediatra"
    assert pacote.abertura.efeitos


def test_intervalo_pedido_a_agenda_inclui_o_ultimo_dia_inteiro(motor):
    agenda = AgendaFalsa({})
    Ritual(motor, agenda=agenda).fechar(DOMINGO)
    inicio, fim = agenda.chamadas[0]
    assert inicio.startswith("2026-03-02")
    # O fim é exclusivo na API do Google, então precisa ser o dia seguinte.
    assert fim.startswith("2026-03-09")


def test_sem_agenda_configurada_o_ritual_sai_vazio_e_nao_quebra(motor):
    pacote = Ritual(motor).pacote(DOMINGO)
    assert pacote.fechamento.compromissos == []
    assert pacote.abertura.compromissos == []
    assert "Nenhum compromisso" in pacote.para_telegram()


# -- saídas ------------------------------------------------------------------


@pytest.fixture
def pacote(motor):
    return Ritual(motor).pacote(
        DOMINGO,
        eventos_passados=[EventoAgenda(titulo="Reunião do grupo", data="2026-03-05")],
        eventos_futuros=[EventoAgenda(titulo="Consulta com a pediatra", data="2026-03-12")],
        estoque=[ItemEstoque(nome="Arroz", situacao="acabando")],
    )


def test_texto_do_telegram_tem_as_duas_metades_e_as_tres_prioridades(pacote):
    texto = pacote.para_telegram()
    assert "FECHAR A SEMANA" in texto
    assert "ABRIR A SEMANA" in texto
    assert "Efeito borboleta" in texto
    assert "Essenciais acabando" in texto
    assert texto.rstrip().endswith("3.")


def test_texto_do_telegram_nao_usa_travessao(pacote):
    assert "—" not in pacote.para_telegram()


def test_blocos_do_notion_sao_validos_e_usam_checkbox_de_verdade(pacote):
    blocos = pacote.para_blocos_notion()
    tipos = {b["type"] for b in blocos}

    assert tipos <= {"heading_2", "heading_3", "paragraph", "to_do", "callout"}
    for bloco in blocos:
        conteudo = bloco[bloco["type"]]
        assert conteudo["rich_text"][0]["text"]["content"] is not None
    assert sum(1 for b in blocos if b["type"] == "to_do") >= len(CHECKLIST_ABERTURA) + 3


def test_blocos_do_notion_marcam_o_efeito_condicional(pacote):
    textos = [
        b["to_do"]["rich_text"][0]["text"]["content"]
        for b in pacote.para_blocos_notion()
        if b["type"] == "to_do"
    ]
    assert any(t.startswith("Se acontecer:") for t in textos)
    assert any("por causa de Consulta com a pediatra" in t for t in textos)


def test_texto_muito_longo_e_cortado_no_limite_do_notion(motor):
    longo = "x" * 5000
    pacote = Ritual(motor).pacote(
        DOMINGO, eventos_passados=[EventoAgenda(titulo=longo, data="2026-03-05")]
    )
    for bloco in pacote.para_blocos_notion():
        conteudo = bloco[bloco["type"]]["rich_text"][0]["text"]["content"]
        assert len(conteudo) <= 2000
