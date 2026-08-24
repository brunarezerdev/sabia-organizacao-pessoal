"""Fluxo de ponta a ponta, com o Notion e a Agenda substituídos por mocks."""

from __future__ import annotations

from sop.automacao import Automacao
from sop.fila import Fila
from sop.integracoes.ia import ClassificadorHeuristico
from sop.modelos import Mensagem
from sop.orquestradora import Orquestradora

from conftest import HOJE


def montar(registro, banco=None, agenda=None, fila=None, notificar=None):
    orquestradora = Orquestradora(
        ClassificadorHeuristico(), registro, fila, hoje=lambda: HOJE
    )
    return Automacao(orquestradora, banco=banco, agenda=agenda, notificar=notificar)


# -- fluxo principal ---------------------------------------------------------


def test_mensagem_com_data_grava_e_cria_evento(registro, banco, agenda):
    automacao = montar(registro, banco, agenda)
    resultado = automacao.executar(
        Mensagem(id="m1", texto="Reunião com o time na quinta às 14h")
    )

    assert resultado.sucesso
    assert resultado.id_no_banco == "pagina-1"
    assert resultado.id_do_evento == "evento-1"
    assert banco.itens[0].agente == "secretaria"
    assert agenda.eventos[0]["data"] == "2026-03-12"
    assert agenda.eventos[0]["hora"] == "14:00"


def test_item_sem_data_nao_vira_evento(registro, banco, agenda):
    automacao = montar(registro, banco, agenda)
    resultado = automacao.executar(Mensagem(id="m2", texto="Acabou o café, comprar"))

    assert resultado.id_no_banco == "pagina-1"
    assert resultado.id_do_evento is None
    assert agenda.eventos == []


def test_agente_sem_agenda_nao_cria_evento(registro, banco, agenda):
    """Financeira tem cria_evento: false — mesmo com data, não vai à agenda."""
    automacao = montar(registro, banco, agenda)
    resultado = automacao.executar(Mensagem(id="m3", texto="Gastei R$ 45,90 hoje"))

    assert resultado.item.data == HOJE.isoformat()
    assert resultado.id_do_evento is None
    assert agenda.eventos == []


# -- resiliência -------------------------------------------------------------


def test_falha_na_agenda_nao_perde_o_registro(registro, banco):
    """Perder o evento é ruim; perder o item seria pior."""
    from conftest import AgendaFalsa

    automacao = montar(registro, banco, AgendaFalsa(falhar=True))
    resultado = automacao.executar(Mensagem(id="m4", texto="Reunião amanhã às 10h"))

    assert resultado.id_no_banco == "pagina-1"  # gravou mesmo assim
    assert not resultado.sucesso
    assert any("google_calendar" in e for e in resultado.erros)


def test_falha_no_banco_e_reportada(registro, agenda):
    from conftest import BancoFalso

    automacao = montar(registro, BancoFalso(falhar=True), agenda)
    resultado = automacao.executar(Mensagem(id="m5", texto="Comprar arroz"))

    assert resultado.id_no_banco is None
    assert any("notion" in e for e in resultado.erros)


def test_sem_integracao_configurada_ainda_classifica(registro):
    """Sem Notion e sem Agenda, o fluxo roda e devolve a classificação."""
    resultado = montar(registro).executar(Mensagem(id="m6", texto="Estudar amanhã"))

    assert resultado.classificacao.agente == "educacional"
    assert resultado.id_no_banco is None
    assert resultado.sucesso  # não gravar não é erro quando não há destino


# -- resposta ao usuário -----------------------------------------------------


def test_resposta_menciona_agente_e_evento(registro, banco, agenda):
    automacao = montar(registro, banco, agenda)
    resultado = automacao.executar(Mensagem(id="m7", texto="Reunião amanhã às 10h"))
    texto = Automacao.montar_resposta(resultado)

    assert "secretaria" in texto
    assert "2026-03-11" in texto
    assert "Evento criado na agenda." in texto


def test_resposta_sinaliza_confirmacao_pendente(registro, banco):
    automacao = montar(registro, banco)
    resultado = automacao.executar(Mensagem(id="m8", texto="Gastei no posto ontem"))

    assert "confirmação" in Automacao.montar_resposta(resultado)


def test_notificacao_recebe_a_resposta(registro, banco):
    enviadas: list[str] = []
    automacao = montar(registro, banco, notificar=enviadas.append)
    automacao.executar(Mensagem(id="m9", texto="Comprar leite"))

    assert len(enviadas) == 1
    assert "lifestyle" in enviadas[0]


# -- fila --------------------------------------------------------------------


def test_despacha_e_processa_pela_fila(registro, banco, agenda, tmp_path):
    fila = Fila(tmp_path)
    automacao = montar(registro, banco, agenda, fila=fila)

    automacao.orquestradora.despachar(Mensagem(id="m10", texto="Comprar café"))
    automacao.orquestradora.despachar(Mensagem(id="m11", texto="Reunião amanhã às 9h"))
    assert fila.contar("pendente") == 2

    resultados = automacao.processar_fila()

    assert len(resultados) == 2
    assert fila.contar("concluida") == 2
    assert len(banco.itens) == 2
    assert len(agenda.eventos) == 1  # só a reunião tem data


def test_despachar_sem_fila_explica_o_problema(registro):
    import pytest

    automacao = montar(registro)
    with pytest.raises(RuntimeError, match="sem fila"):
        automacao.orquestradora.despachar(Mensagem(id="m12", texto="oi"))
