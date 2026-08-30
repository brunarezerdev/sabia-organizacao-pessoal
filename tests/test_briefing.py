"""Contrato do briefing diário da Sábia.

Os testes são estáticos de propósito: não mandam Telegram nem alteram as bases
reais. Eles protegem a ordem, a fonte única e, principalmente, a regra de não
escolher prioridades no lugar da Bruna.
"""

from pathlib import Path


RAIZ = Path(__file__).resolve().parents[1]
INSTRUCAO = (RAIZ / "sabia/briefing-diario.md").read_text(encoding="utf-8")
ROTINA = (RAIZ / "scripts/openclaw/rotina_sabia.sh").read_text(encoding="utf-8")
ALMA = (RAIZ / "sabia/orquestradora.md").read_text(encoding="utf-8")


def sem_quebras(texto: str) -> str:
    return " ".join(texto.split())


def test_briefing_preserva_a_ordem_pedida():
    itens = [
        "Previsão do tempo",
        "Agenda do dia",
        "Cardápio do dia",
        "Pendências",
        "Combinação das três prioridades",
    ]
    posicoes = [INSTRUCAO.index(item) for item in itens]
    assert posicoes == sorted(posicoes)


def test_clima_reaproveita_fonte_e_estilo_curto_da_aria():
    assert "wttr.in" in INSTRUCAO
    assert "Caxias está com 19°C e nublado. Máxima de 26°C" in INSTRUCAO
    assert "Não copie os números do exemplo" in INSTRUCAO


def test_fontes_do_cardapio_da_agenda_e_das_pendencias_estao_explicitas():
    assert "agenda `bruna`" in INSTRUCAO
    assert "`Planejamento de Refeições`" in INSTRUCAO
    assert "base `Prazos e tarefas`" in INSTRUCAO


def test_candidatas_vem_de_prazo_hoje_ou_amanha_e_nao_sao_decisao():
    assert "cujo `prazo` seja hoje ou amanhã" in INSTRUCAO
    assert "Isso é uma proposta, não uma decisão" in sem_quebras(INSTRUCAO)
    assert "confirme, troque ou acrescente" in INSTRUCAO


def test_sem_resposta_nao_grava_prioridade():
    assert "Se ela não responder" in INSTRUCAO
    assert "não grave nada" in sem_quebras(INSTRUCAO)
    assert "Se ela não responder, não grave nada" in ALMA


def test_prioridade_combinada_usa_a_mesma_fonte_das_paginas():
    for texto in (INSTRUCAO, ALMA):
        assert "`Prioridade do dia`" in texto
        assert "`Prazos e tarefas`" in texto
        assert "nunca" in texto and "três" in texto
    assert "listas `Prioridades de hoje` no Jardim e nos territórios" in ALMA


def test_rotina_entrega_na_sessao_direta_configurada_da_bruna():
    assert 'DESTINO="${SOP_BRIEFING_CHAT_ID:-}"' in ROTINA
    assert '--session-key "agent:main:telegram:direct:$DESTINO"' in ROTINA
    assert "--deliver" in ROTINA
    assert "--reply-channel telegram" in ROTINA
    assert "--reply-to \"$DESTINO\"" in ROTINA
