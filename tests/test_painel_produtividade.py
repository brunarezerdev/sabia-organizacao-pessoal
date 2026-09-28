"""Testes do painel de produtividade.

A parte mais importante deste arquivo não é aritmética: é a garantia de
privacidade. `test_nenhum_texto_pessoal_*` alimenta o painel com títulos que
simulam o conteúdo real da base da Bruna (saúde de criança, nome de médico) e
exige que nenhum pedaço deles apareça no HTML gerado. Se alguém um dia
acrescentar o título a um gráfico ou a uma dica de ferramenta, esse teste cai.
"""

from __future__ import annotations

from datetime import date

import pytest

from sop.painel_html import renderizar
from sop.painel_produtividade import (
    FAIXA_ESTUDO,
    FAIXA_OUTROS,
    FAIXA_TRABALHO,
    INICIO_MEDICAO,
    QUADRANTES,
    SEM_QUADRANTE,
    Compromisso,
    Tarefa,
    blocos_de_estudo,
    carga_por_dia,
    carga_por_periodo,
    compromisso_de_evento,
    compromissos_por_mes,
    conclusao,
    distribuicao_eisenhower,
    faixa_do_titulo,
    giro,
    montar,
    por_onde,
    tarefa_de_pagina,
)

HOJE = date(2026, 9, 28)  # uma segunda-feira

# Textos que nunca podem vazar. São inventados, mas do mesmo tipo do que existe
# de verdade na base: consulta de criança, nome de profissional, exame.
TEXTOS_SENSIVEIS = (
    "Pediatra do Joaquim",
    "Exame de sangue da Lia",
    "Dra. Fulana de Tal",
    "Levar remédio na escola",
)


def pagina(
    titulo: str = "tarefa qualquer",
    criada: str = "2026-09-01T10:00:00.000Z",
    quadrante: str | None = None,
    onde: str | None = None,
    feito: bool = False,
    concluida: str | None = None,
    prazo: str | None = None,
) -> dict:
    """Monta uma página do Notion no formato que a API devolve."""
    return {
        "id": "pagina-1",
        "properties": {
            "Tarefa": {"title": [{"plain_text": titulo}]},
            "Registrada em": {"created_time": criada},
            "Prioridade (Eisenhower)": {
                "select": {"name": quadrante} if quadrante else None
            },
            "Onde": {"select": {"name": onde} if onde else None},
            "Feito": {"checkbox": feito},
            "Concluída em": {"date": {"start": concluida} if concluida else None},
            "prazo": {"date": {"start": prazo} if prazo else None},
        },
    }


def evento(
    titulo: str = "compromisso",
    inicio: str = "2026-09-28T19:00:00-03:00",
    fim: str = "2026-09-28T21:00:00-03:00",
    recorrente: bool = False,
    dia_inteiro: str | None = None,
) -> dict:
    corpo: dict = {"id": "ev-1", "summary": titulo}
    if dia_inteiro:
        corpo["start"] = {"date": dia_inteiro}
        corpo["end"] = {"date": dia_inteiro}
    else:
        corpo["start"] = {"dateTime": inicio}
        corpo["end"] = {"dateTime": fim}
    if recorrente:
        corpo["recurringEventId"] = "rec-1"
    return corpo


# -- classificação de faixa --------------------------------------------------


@pytest.mark.parametrize(
    "titulo,esperado",
    [
        ("Estudo - Rocketseat e projetos", FAIXA_ESTUDO),
        ("Aula ao vivo - UniFECAF", FAIXA_ESTUDO),
        ("AULA AO VIVO - Comunidade Avalanche", FAIXA_ESTUDO),
        ("e-Gig - bloco de trabalho", FAIXA_TRABALHO),
        ("Reunião com cliente", FAIXA_TRABALHO),
        ("Pediatra do Joaquim", FAIXA_OUTROS),
        ("Rematrícula e inscrições da escola", FAIXA_OUTROS),
        ("", FAIXA_OUTROS),
    ],
)
def test_faixa_do_titulo(titulo, esperado):
    assert faixa_do_titulo(titulo) == esperado


def test_faixa_ignora_acento_e_caixa():
    assert faixa_do_titulo("REUNIAO de alinhamento") == FAIXA_TRABALHO
    assert faixa_do_titulo("reunião de alinhamento") == FAIXA_TRABALHO


def test_compromisso_de_saude_nao_e_caracterizado():
    """Consulta médica cai em 'Outros', sem nenhuma etiqueta que a descreva."""
    for texto in TEXTOS_SENSIVEIS:
        assert faixa_do_titulo(texto) == FAIXA_OUTROS


# -- fronteira: nada de texto atravessa --------------------------------------


def test_tarefa_nao_tem_campo_de_texto():
    t = tarefa_de_pagina(pagina(titulo="Pediatra do Joaquim"))
    assert t is not None
    assert "joaquim" not in repr(t).casefold()
    assert not any(
        isinstance(getattr(t, campo), str) and "Joaquim" in getattr(t, campo)
        for campo in t.__dataclass_fields__
    )


def test_compromisso_nao_tem_campo_de_texto():
    c = compromisso_de_evento(evento(titulo="Exame de sangue da Lia"), "America/Sao_Paulo")
    assert c is not None
    assert "lia" not in repr(c).casefold()


def test_tarefa_sem_data_de_registro_e_descartada():
    bruta = pagina()
    bruta["properties"]["Registrada em"] = {"created_time": None}
    assert tarefa_de_pagina(bruta) is None


def test_quadrante_desconhecido_vira_none():
    """Um valor inventado no select não pode virar categoria nova no painel."""
    t = tarefa_de_pagina(pagina(quadrante="Prioridade máxima total"))
    assert t is not None and t.quadrante is None


def test_tarefa_le_quadrante_e_datas():
    t = tarefa_de_pagina(
        pagina(
            criada="2026-09-26T08:00:00.000Z",
            quadrante=QUADRANTES[0],
            onde="Faculdade",
            feito=True,
            concluida="2026-09-28",
            prazo="2026-09-30",
        )
    )
    assert t == Tarefa(
        registrada_em=date(2026, 9, 26),
        quadrante=QUADRANTES[0],
        onde="Faculdade",
        feita=True,
        concluida_em=date(2026, 9, 28),
        prazo=date(2026, 9, 30),
    )
    assert t.giro_em_dias == 2


# -- conversão de compromisso ------------------------------------------------


def test_compromisso_com_hora_vira_duracao_e_periodo():
    c = compromisso_de_evento(evento(), "America/Sao_Paulo")
    assert c.horas == 2.0
    assert c.hora_inicio == 19
    assert c.periodo == "Noite"
    assert c.dia == date(2026, 9, 28)


def test_compromisso_de_dia_inteiro_nao_conta_hora():
    """Lembrete de dia inteiro é compromisso, mas não infla a carga horária."""
    c = compromisso_de_evento(evento(dia_inteiro="2026-10-02"), "America/Sao_Paulo")
    assert c.dia_inteiro is True
    assert c.horas == 0.0
    assert c.periodo is None


def test_compromisso_converte_para_o_fuso_configurado():
    c = compromisso_de_evento(
        evento(inicio="2026-09-29T00:30:00Z", fim="2026-09-29T01:30:00Z"),
        "America/Sao_Paulo",
    )
    assert c.dia == date(2026, 9, 28)  # ainda é dia 28 em São Paulo
    assert c.hora_inicio == 21


def test_evento_sem_data_utilizavel_e_descartado():
    assert compromisso_de_evento({"summary": "x"}, "America/Sao_Paulo") is None


# -- medições ----------------------------------------------------------------


def test_distribuicao_traz_os_cinco_rotulos_sempre():
    d = distribuicao_eisenhower([Tarefa(registrada_em=HOJE)])
    assert list(d) == [*QUADRANTES, SEM_QUADRANTE]
    assert d[SEM_QUADRANTE] == 1
    assert sum(d[q] for q in QUADRANTES) == 0


def test_conclusao_conta_pelo_checkbox():
    tarefas = [
        Tarefa(registrada_em=HOJE, feita=True),
        Tarefa(registrada_em=HOJE),
        Tarefa(registrada_em=HOJE),
    ]
    assert conclusao(tarefas) == {"registradas": 3, "concluidas": 1, "abertas": 2}


def test_giro_sem_data_de_conclusao_devolve_motivo_e_nao_zero():
    """O buraco de medição aparece como explicação, nunca como número."""
    tarefas = [Tarefa(registrada_em=date(2026, 8, 30), feita=True) for _ in range(3)]
    medida = giro(tarefas)
    assert medida.valor is None
    assert not medida.tem_valor
    assert INICIO_MEDICAO.strftime("%d/%m/%Y") in medida.indisponivel
    assert "3 tarefas" in medida.indisponivel


def test_giro_calcula_mediana_quando_as_duas_datas_existem():
    tarefas = [
        Tarefa(
            registrada_em=date(2026, 9, 26),
            feita=True,
            concluida_em=date(2026, 9, 28),
        ),
        Tarefa(
            registrada_em=date(2026, 9, 26),
            feita=True,
            concluida_em=date(2026, 10, 2),
        ),
        Tarefa(registrada_em=date(2026, 9, 26), feita=False),
    ]
    assert giro(tarefas).valor == 4.0


def test_carga_por_dia_e_media_das_semanas():
    compromissos = [
        Compromisso(dia=date(2026, 9, 28), horas=3.0, hora_inicio=9),
        Compromisso(dia=date(2026, 10, 5), horas=3.0, hora_inicio=9),
    ]
    carga = carga_por_dia(compromissos, semanas=2)
    assert carga["Segunda"] == 3.0
    assert carga["Terça"] == 0.0


def test_carga_por_periodo_ignora_dia_inteiro():
    compromissos = [
        Compromisso(dia=HOJE, horas=3.0, hora_inicio=9),
        Compromisso(dia=HOJE, horas=2.0, hora_inicio=19),
        Compromisso(dia=HOJE, horas=0.0, dia_inteiro=True),
    ]
    carga = carga_por_periodo(compromissos, semanas=1)
    assert carga == {"Manhã": 3.0, "Tarde": 0.0, "Noite": 2.0}


def test_por_mes_preenche_os_meses_vazios():
    """Mês sem compromisso entra zerado para o eixo de tempo não ter buraco."""
    compromissos = [
        Compromisso(dia=date(2026, 1, 10)),
        Compromisso(dia=date(2026, 4, 2), recorrente=True),
    ]
    por_mes = compromissos_por_mes(compromissos)
    assert list(por_mes) == ["2026-01", "2026-02", "2026-03", "2026-04"]
    assert por_mes["2026-02"] == {"pontual": 0, "recorrente": 0}
    assert por_mes["2026-04"] == {"pontual": 0, "recorrente": 1}


def test_por_mes_sem_compromisso_devolve_vazio():
    assert compromissos_por_mes([]) == {}


def test_blocos_de_estudo_separa_vivido_de_reservado():
    compromissos = [
        Compromisso(dia=date(2026, 9, 21), faixa=FAIXA_ESTUDO, horas=2.0, hora_inicio=19),
        Compromisso(dia=date(2026, 9, 28), faixa=FAIXA_ESTUDO, horas=3.0, hora_inicio=19),
        Compromisso(dia=date(2026, 10, 5), faixa=FAIXA_ESTUDO, horas=3.0, hora_inicio=19),
        Compromisso(dia=date(2026, 10, 5), faixa=FAIXA_TRABALHO, horas=3.0, hora_inicio=9),
    ]
    e = blocos_de_estudo(compromissos, HOJE)
    assert e["horas_ja_vividas"] == 2.0
    assert e["horas_reservadas"] == 6.0
    assert e["blocos_reservados"] == 2
    assert e["semana_tipica"]["Segunda"] == 3.0
    assert e["ultimo_dia"] == date(2026, 10, 5)


def test_por_onde_rotula_o_que_nao_tem_frente():
    d = por_onde([Tarefa(registrada_em=HOJE, onde="Casa"), Tarefa(registrada_em=HOJE)])
    assert d == {"Casa": 1, "Sem frente": 1}


# -- montagem ----------------------------------------------------------------


def _painel_de_teste():
    tarefas = [
        Tarefa(registrada_em=date(2026, 8, 30), feita=True),
        Tarefa(registrada_em=date(2026, 9, 1), onde="Casa"),
        Tarefa(
            registrada_em=date(2026, 9, 26),
            quadrante=QUADRANTES[1],
            onde="Faculdade",
        ),
    ]
    compromissos = [
        Compromisso(dia=date(2026, 6, 10), horas=1.0, hora_inicio=14),
        Compromisso(dia=HOJE, faixa=FAIXA_ESTUDO, horas=3.0, hora_inicio=19, recorrente=True),
        Compromisso(
            dia=date(2026, 10, 5),
            faixa=FAIXA_ESTUDO,
            horas=3.0,
            hora_inicio=19,
            recorrente=True,
        ),
        Compromisso(
            dia=date(2026, 10, 6), faixa=FAIXA_TRABALHO, horas=3.0, hora_inicio=9
        ),
    ]
    return montar(tarefas, compromissos, HOJE)


def test_montar_separa_passado_de_futuro():
    painel = _painel_de_teste()
    assert painel.compromissos_passados == 1
    assert painel.compromissos_futuros == 3
    assert painel.recorrentes_futuros == 2
    assert painel.gerado_em == HOJE
    assert painel.horas_semana > 0


# -- renderização ------------------------------------------------------------


def test_html_nao_contem_nenhum_texto_pessoal():
    """A garantia central: o conteúdo real não chega ao arquivo gerado."""
    tarefas = [
        t
        for texto in TEXTOS_SENSIVEIS
        if (t := tarefa_de_pagina(pagina(titulo=texto))) is not None
    ]
    compromissos = [
        c
        for texto in TEXTOS_SENSIVEIS
        if (c := compromisso_de_evento(evento(titulo=texto), "America/Sao_Paulo"))
        is not None
    ]
    html = renderizar(montar(tarefas, compromissos, HOJE))
    minusculo = html.casefold()
    for texto in TEXTOS_SENSIVEIS:
        assert texto.casefold() not in minusculo
        for palavra in texto.split():
            if len(palavra) > 4:
                assert palavra.casefold() not in minusculo


def test_html_explica_a_medida_que_nao_existe():
    html = renderizar(_painel_de_teste())
    assert "ainda não" in html.casefold()
    assert INICIO_MEDICAO.strftime("%d/%m/%Y") in html


def test_html_traz_tabela_equivalente_de_cada_grafico():
    """Sem a tabela, um tom de contraste baixo deixaria de ser legível."""
    html = renderizar(_painel_de_teste())
    assert html.count("Ver os números em tabela") >= 6


def test_html_e_autocontido():
    """Nada de CDN, fonte remota ou chamada de rede: o painel abre offline."""
    html = renderizar(_painel_de_teste())
    for proibido in ("http://", "https://", "<script", "@import"):
        assert proibido not in html


def test_html_declara_os_dois_modos_de_cor():
    html = renderizar(_painel_de_teste())
    assert "prefers-color-scheme:dark" in html
    assert "#2a78d6" in html  # slot 1 no modo claro, o tom validado


def test_painel_vazio_nao_quebra():
    html = renderizar(montar([], [], HOJE))
    assert "<html" in html


# -- CLI ---------------------------------------------------------------------


def test_cli_painel_exemplo_gera_arquivo_sem_rede(tmp_path):
    from sop.cli import main

    destino = tmp_path / "painel.html"
    assert main(["painel", "--exemplo", "--hoje", "2026-09-28", "--saida", str(destino)]) == 0
    html = destino.read_text(encoding="utf-8")
    assert "exemplo fictício" in html
    assert "A semana da Bruna" in html
