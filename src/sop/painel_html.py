"""Renderização do painel de produtividade em um HTML autocontido.

Um arquivo só, sem CDN, sem fonte remota e sem chamada de rede: o painel abre
com clique duplo, funciona offline e pode ser mostrado numa gravação de tela
sem depender de servidor no ar.

A renderização não faz conta nenhuma. Tudo que aparece aqui já chegou calculado
em `painel_produtividade.Painel`. Quando uma medida não existe, chega como
`Medida(valor=None, indisponivel="motivo")` e o motivo é impresso no lugar do
número — o painel nunca mostra caixa vazia sem explicação.

Cada gráfico traz uma tabela equivalente logo abaixo, dobrável. Isso não é
enfeite: é o caminho de leitura de quem não distingue as cores e de quem lê por
leitor de tela, e é o que permite usar tons que não alcançam 3:1 de contraste
com o fundo.
"""

from __future__ import annotations

import html
from datetime import date
from typing import Sequence

from .painel_produtividade import (
    DIAS_DA_SEMANA,
    INICIO_MEDICAO,
    PERIODOS,
    QUADRANTES,
    SEM_QUADRANTE,
    Painel,
)

# Paleta validada pelo verificador de contraste e de visão de cores nos dois
# modos (adjacente e todos os pares). Trocar um tom aqui exige rodar de novo.
CORES = {
    "serie1": ("#2a78d6", "#3987e5"),
    "serie2": ("#eb6834", "#d95926"),
    "serie3": ("#1baf7a", "#199e70"),
    "bom": ("#0ca30c", "#0ca30c"),
}

MESES_CURTOS = (
    "jan", "fev", "mar", "abr", "mai", "jun",
    "jul", "ago", "set", "out", "nov", "dez",
)

FOLGA = 2.0  # o vão de 2px na cor do fundo que separa marcas encostadas


def _e(valor: object) -> str:
    return html.escape(str(valor), quote=True)


def _numero(valor: float) -> str:
    """Número em português, sem casa decimal inútil."""
    if float(valor) == int(valor):
        return f"{int(valor)}"
    return f"{valor:.1f}".replace(".", ",")


def _mes_legivel(chave: str) -> str:
    ano, mes = chave.split("-")
    return f"{MESES_CURTOS[int(mes) - 1]}/{ano[2:]}"


def _dia_curto(nome: str) -> str:
    return nome[:3]


# -- primitivas de marca -----------------------------------------------------


def _coluna(x: float, base: float, largura: float, altura: float, cor: str) -> str:
    """Coluna com topo arredondado em 4px e pé quadrado na linha de base."""
    if altura <= 0:
        return ""
    raio = min(4.0, altura)
    topo = base - altura
    return (
        f'<rect x="{x:.1f}" y="{topo:.1f}" width="{largura:.1f}" '
        f'height="{altura:.1f}" rx="4" fill="{cor}"/>'
        f'<rect x="{x:.1f}" y="{base - raio:.1f}" width="{largura:.1f}" '
        f'height="{raio:.1f}" fill="{cor}"/>'
    )


def _barra(x: float, y: float, largura: float, altura: float, cor: str) -> str:
    """Barra horizontal: ponta arredondada à direita, pé quadrado à esquerda."""
    if largura <= 0:
        return ""
    raio = min(4.0, largura)
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{largura:.1f}" '
        f'height="{altura:.1f}" rx="4" fill="{cor}"/>'
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{raio:.1f}" '
        f'height="{altura:.1f}" fill="{cor}"/>'
    )


def _tabela(cabecalho: Sequence[str], linhas: Sequence[Sequence[str]]) -> str:
    """A tabela equivalente ao gráfico. Todo valor do painel é legível aqui."""
    ths = "".join(f"<th>{_e(c)}</th>" for c in cabecalho)
    trs = "".join(
        "<tr>" + "".join(f"<td>{_e(c)}</td>" for c in linha) + "</tr>"
        for linha in linhas
    )
    return (
        '<details class="tabela"><summary>Ver os números em tabela</summary>'
        f"<table><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table></details>"
    )


def _cartao(titulo: str, subtitulo: str, corpo: str, tabela: str = "") -> str:
    sub = f'<p class="sub">{_e(subtitulo)}</p>' if subtitulo else ""
    return (
        f'<article class="cartao"><h3>{_e(titulo)}</h3>{sub}'
        f"{corpo}{tabela}</article>"
    )


def _legenda(itens: Sequence[tuple[str, str]]) -> str:
    """Legenda sempre presente a partir de duas séries. Cor nunca fica sozinha."""
    partes = "".join(
        f'<span class="chave"><i style="background:{cor}"></i>{_e(nome)}</span>'
        for nome, cor in itens
    )
    return f'<div class="legenda">{partes}</div>'


def _vazio(motivo: str) -> str:
    return f'<p class="vazio">{_e(motivo)}</p>'


# -- gráficos ----------------------------------------------------------------


def _grafico_por_mes(painel: Painel) -> str:
    dados = painel.por_mes
    if not dados:
        return _vazio("Nenhum compromisso na janela consultada.")

    meses = list(dados.items())
    largura, altura = 760.0, 240.0
    margem_e, margem_b, margem_t = 36.0, 34.0, 16.0
    base = altura - margem_b
    util = altura - margem_b - margem_t
    faixa = (largura - margem_e - 12) / max(len(meses), 1)
    col = min(24.0, faixa - 10)

    teto = max((v["pontual"] + v["recorrente"]) for _, v in meses) or 1
    escala = util / teto

    marcas: list[str] = []
    rotulos: list[str] = []
    for i, (mes, valores) in enumerate(meses):
        x = margem_e + faixa * i + (faixa - col) / 2
        pontual = valores["pontual"] * escala
        recorrente = valores["recorrente"] * escala
        # Recorrente embaixo (é o piso da rotina), pontual em cima.
        if recorrente > 0:
            marcas.append(_coluna(x, base, col, recorrente, CORES["serie2"][0]))
        if pontual > 0:
            # O vão de 2px na cor do fundo é o que separa os dois segmentos;
            # nenhuma borda é desenhada em volta das marcas.
            topo_rec = base - recorrente - (FOLGA if recorrente > 0 else 0)
            marcas.append(_coluna(x, topo_rec, col, pontual, CORES["serie1"][0]))
        rotulos.append(
            f'<text class="tick" x="{x + col / 2:.1f}" y="{base + 18:.0f}" '
            f'text-anchor="middle">{_e(_mes_legivel(mes))}</text>'
        )

    grade = "".join(
        f'<line class="grade" x1="{margem_e}" x2="{largura - 8}" '
        f'y1="{base - util * f:.1f}" y2="{base - util * f:.1f}"/>'
        f'<text class="tick" x="{margem_e - 8}" y="{base - util * f + 4:.1f}" '
        f'text-anchor="end">{int(teto * f)}</text>'
        for f in (0.5, 1.0)
    )

    svg = (
        f'<svg viewBox="0 0 {largura:.0f} {altura:.0f}" role="img" '
        f'aria-label="Compromissos por mês, separados entre pontuais e recorrentes">'
        f"{grade}"
        f'<line class="eixo" x1="{margem_e}" x2="{largura - 8}" '
        f'y1="{base}" y2="{base}"/>'
        f"{''.join(marcas)}{''.join(rotulos)}</svg>"
    )

    tabela = _tabela(
        ("Mês", "Pontuais", "Recorrentes", "Total"),
        [
            (
                _mes_legivel(mes),
                str(v["pontual"]),
                str(v["recorrente"]),
                str(v["pontual"] + v["recorrente"]),
            )
            for mes, v in meses
        ],
    )
    legenda = _legenda(
        [("Pontual", CORES["serie1"][0]), ("Recorrente", CORES["serie2"][0])]
    )
    return _cartao(
        "A agenda antes e depois",
        "Compromisso pontual é o que apareceu e teve que ser encaixado. "
        "Recorrente é o que ela reservou e se repete sozinho.",
        legenda + f'<div class="plot">{svg}</div>',
        tabela,
    )


def _colunas_simples(
    dados: dict[str, float],
    rotulo_curto,
    cor: str,
    descricao: str,
    unidade: str = "h",
) -> str:
    largura, altura = 760.0, 210.0
    margem_e, margem_b, margem_t = 24.0, 30.0, 26.0
    base = altura - margem_b
    util = altura - margem_b - margem_t
    itens = list(dados.items())
    faixa = (largura - margem_e - 12) / max(len(itens), 1)
    col = min(24.0, faixa - 16)
    teto = max(dados.values()) or 1
    escala = util / teto

    partes: list[str] = []
    for i, (nome, valor) in enumerate(itens):
        x = margem_e + faixa * i + (faixa - col) / 2
        h = valor * escala
        partes.append(_coluna(x, base, col, h, cor))
        centro = x + col / 2
        if valor > 0:
            partes.append(
                f'<text class="valor" x="{centro:.1f}" y="{base - h - 8:.1f}" '
                f'text-anchor="middle">{_e(_numero(valor) + unidade)}</text>'
            )
        partes.append(
            f'<text class="tick" x="{centro:.1f}" y="{base + 18:.0f}" '
            f'text-anchor="middle">{_e(rotulo_curto(nome))}</text>'
        )

    return (
        f'<div class="plot"><svg viewBox="0 0 {largura:.0f} {altura:.0f}" '
        f'role="img" aria-label="{_e(descricao)}">'
        f'<line class="eixo" x1="{margem_e}" x2="{largura - 8}" y1="{base}" y2="{base}"/>'
        f"{''.join(partes)}</svg></div>"
    )


def _barras_rotuladas(
    dados: dict[str, float | int],
    cor_padrao: str,
    descricao: str,
    unidade: str = "",
    cor_por_item: dict[str, str] | None = None,
) -> str:
    largura = 760.0
    alto_linha, vao = 22.0, 14.0
    altura = len(dados) * (alto_linha + vao) + 12
    rotulo = 210.0
    teto = max([float(v) for v in dados.values()] + [1.0])
    escala = (largura - rotulo - 70) / teto

    partes: list[str] = []
    for i, (nome, valor) in enumerate(dados.items()):
        y = 6 + i * (alto_linha + vao)
        cor = (cor_por_item or {}).get(nome, cor_padrao)
        comprimento = float(valor) * escala
        partes.append(
            f'<text class="rotulo" x="{rotulo - 12:.0f}" y="{y + 18:.0f}" '
            f'text-anchor="end">{_e(nome)}</text>'
        )
        partes.append(_barra(rotulo, y, comprimento, alto_linha, cor))
        partes.append(
            f'<text class="valor" x="{rotulo + comprimento + 10:.1f}" '
            f'y="{y + 18:.0f}">{_e(_numero(float(valor)) + unidade)}</text>'
        )

    return (
        f'<div class="plot"><svg viewBox="0 0 {largura:.0f} {altura:.0f}" '
        f'role="img" aria-label="{_e(descricao)}">{"".join(partes)}</svg></div>'
    )


def _medidor(feito: int, total: int) -> str:
    """Um medidor fino: trilho num passo claro da mesma rampa, preenchido no tom cheio."""
    largura, altura = 760.0, 16.0
    cheio = largura * ((feito / total) if total else 0.0)
    return (
        f'<div class="plot"><svg viewBox="0 0 {largura:.0f} {altura:.0f}" '
        f'role="img" aria-label="{feito} de {total} tarefas concluídas">'
        f'<rect x="0" y="0" width="{largura:.0f}" height="{altura:.0f}" rx="4" '
        f'class="trilho"/>'
        f"{_barra(0, 0, cheio, altura, CORES['serie1'][0])}</svg></div>"
    )


# -- página ------------------------------------------------------------------

ESTILO = """
:root{color-scheme:light;
--plano:#f9f9f7;--superficie:#fcfcfb;--tinta:#0b0b0b;--tinta2:#52514e;
--mudo:#898781;--grade:#e1e0d9;--eixo:#c3c2b7;--borda:rgba(11,11,11,.10);
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--bom:#0ca30c;--trilho:#e8eef7}
@media (prefers-color-scheme:dark){:root:where(:not([data-tema="claro"])){
color-scheme:dark;
--plano:#0d0d0d;--superficie:#1a1a19;--tinta:#fff;--tinta2:#c3c2b7;
--mudo:#898781;--grade:#2c2c2a;--eixo:#383835;--borda:rgba(255,255,255,.10);
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--bom:#0ca30c;--trilho:#22303f}}
*{box-sizing:border-box}
body{margin:0;padding:28px 20px 56px;background:var(--plano);color:var(--tinta);
font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
.folha{max-width:880px;margin:0 auto}
header h1{font-size:26px;margin:0 0 6px;letter-spacing:-.01em}
header .linha{color:var(--tinta2);margin:0 0 4px}
.aviso{margin:14px 0 0;padding:12px 14px;border:1px solid var(--borda);
border-radius:10px;background:var(--superficie);color:var(--tinta2);font-size:13.5px}
.heroi{margin:26px 0 8px;padding:22px 24px;background:var(--superficie);
border:1px solid var(--borda);border-radius:14px}
.heroi b{display:block;font-size:52px;line-height:1;font-weight:650;
letter-spacing:-.02em}
.heroi span{display:block;margin-top:8px;color:var(--tinta2);max-width:52ch}
.tiles{display:flex;flex-wrap:wrap;margin:12px -6px 4px}
.tile{flex:1 1 168px;margin:6px;background:var(--superficie);
border:1px solid var(--borda);border-radius:12px;padding:14px 16px}
.tile small{display:block;color:var(--tinta2);font-size:12.5px;margin-bottom:6px}
.tile b{font-size:28px;font-weight:650;letter-spacing:-.01em}
.tile i{display:block;font-style:normal;color:var(--mudo);font-size:12.5px;
margin-top:3px}
.cartao{background:var(--superficie);border:1px solid var(--borda);
border-radius:14px;padding:18px 20px;margin-top:16px}
.cartao h3{margin:0 0 4px;font-size:16px}
.cartao .sub{margin:0 0 12px;color:var(--tinta2);font-size:13.5px;max-width:70ch}
.plot{margin:4px 0 2px}
.plot svg{width:100%;height:auto;display:block;overflow:visible}
.grade{stroke:var(--grade);stroke-width:1}
.eixo{stroke:var(--eixo);stroke-width:1}
.trilho{fill:var(--trilho)}
text{font:12px system-ui,-apple-system,"Segoe UI",sans-serif}
.tick{fill:var(--mudo);font-variant-numeric:tabular-nums}
.rotulo{fill:var(--tinta2);font-size:13px}
.valor{fill:var(--tinta);font-size:12.5px;font-weight:600}
.legenda{margin:0 0 12px;color:var(--tinta2);font-size:13px}
.chave{display:inline-block;margin-right:20px}
.chave i{width:11px;height:11px;border-radius:3px;display:inline-block;
margin-right:7px;vertical-align:baseline}
.vazio{color:var(--tinta2);margin:6px 0;font-size:13.5px}
.lacuna{border-left:3px solid var(--eixo);padding:2px 0 2px 14px;
color:var(--tinta2);font-size:13.5px;max-width:70ch}
.lacuna b{display:block;color:var(--tinta);font-size:14px;margin-bottom:3px}
.tabela{margin-top:12px}
.tabela summary{cursor:pointer;color:var(--tinta2);font-size:13px}
.tabela table{border-collapse:collapse;margin-top:10px;width:100%;font-size:13px}
.tabela th,.tabela td{text-align:left;padding:6px 10px 6px 0;
border-bottom:1px solid var(--grade)}
.tabela td{font-variant-numeric:tabular-nums;color:var(--tinta2)}
.tabela th{color:var(--mudo);font-weight:600}
footer{margin-top:28px;color:var(--mudo);font-size:12.5px;max-width:74ch}
@media print{body{background:#fff}.cartao,.heroi,.tile{break-inside:avoid}}
"""


def _tiles(painel: Painel) -> str:
    c = painel.conclusao
    estudo = painel.estudo
    itens = [
        (
            "Horas comprometidas por semana",
            _numero(painel.horas_semana) + "h",
            "média das próximas "
            f"{painel.semanas_projetadas} semanas",
        ),
        (
            "Tarefas registradas",
            str(c.get("registradas", 0)),
            f"{c.get('concluidas', 0)} concluídas",
        ),
        (
            "Compromissos no último ano",
            str(painel.compromissos_passados),
            "o que já aconteceu",
        ),
        (
            "Compromissos reservados à frente",
            str(painel.compromissos_futuros),
            f"{painel.recorrentes_futuros} são recorrentes",
        ),
    ]
    if estudo.get("ultimo_dia"):
        itens[0] = (
            "Horas comprometidas por semana",
            _numero(painel.horas_semana) + "h",
            f"média até {estudo['ultimo_dia'].strftime('%d/%m/%Y')}",
        )
    partes = "".join(
        f'<div class="tile"><small>{_e(rot)}</small><b>{_e(val)}</b>'
        f"<i>{_e(nota)}</i></div>"
        for rot, val, nota in itens
    )
    return f'<div class="tiles">{partes}</div>'


def _cartao_eisenhower(painel: Painel) -> str:
    dados: dict[str, float | int] = {
        nome: painel.eisenhower.get(nome, 0) for nome in QUADRANTES
    }
    dados[SEM_QUADRANTE] = painel.eisenhower.get(SEM_QUADRANTE, 0)
    classificadas = sum(painel.eisenhower.get(q, 0) for q in QUADRANTES)
    total = sum(painel.eisenhower.values())

    corpo = _barras_rotuladas(
        dados,
        CORES["serie1"][0],
        "Tarefas por quadrante da Matriz de Eisenhower",
        cor_por_item={SEM_QUADRANTE: "var(--eixo)"},
    )
    if classificadas == 0:
        corpo += (
            '<p class="lacuna"><b>Ainda não há tarefa classificada.</b>'
            f"A coluna de quadrante existe na base desde "
            f"{INICIO_MEDICAO.strftime('%d/%m/%Y')}; as {total} tarefas do "
            "gráfico foram registradas antes disso e por isso aparecem sem "
            "quadrante. A partir da próxima tarefa registrada pela Sábia, o "
            "quadrante vem preenchido e a barra cinza para de crescer.</p>"
        )
    tabela = _tabela(
        ("Quadrante", "Tarefas"),
        [(nome, str(int(valor))) for nome, valor in dados.items()],
    )
    return _cartao(
        "O que é urgente e o que é importante",
        "Cada tarefa cai em um quadrante da Matriz de Eisenhower quando ela "
        "registra pela Sábia. Cinza é o que entrou antes de a classificação existir.",
        corpo,
        tabela,
    )


def _cartao_conclusao(painel: Painel) -> str:
    c = painel.conclusao
    total, feitas = c.get("registradas", 0), c.get("concluidas", 0)
    corpo = _medidor(feitas, total)
    corpo += (
        f'<p class="sub">{feitas} de {total} tarefas registradas estão '
        f"marcadas como concluídas. {c.get('abertas', 0)} continuam abertas.</p>"
    )
    if not painel.giro.tem_valor:
        corpo += (
            '<p class="lacuna"><b>Tempo entre registrar e concluir: ainda não '
            f"mensurável.</b>{_e(painel.giro.indisponivel)}</p>"
        )
    else:
        corpo += (
            f'<p class="lacuna"><b>{_numero(float(painel.giro.valor or 0))} '
            "dias</b>é a mediana entre registrar uma tarefa e concluí-la.</p>"
        )
    tabela = _tabela(
        ("Situação", "Tarefas"),
        [("Concluídas", str(feitas)), ("Abertas", str(c.get("abertas", 0)))],
    )
    return _cartao(
        "Quanto do que entra realmente sai",
        "Registrar é fácil, concluir é o que conta.",
        corpo,
        tabela,
    )


def _cartao_semana(painel: Painel) -> str:
    corpo = _colunas_simples(
        painel.carga_por_dia,
        _dia_curto,
        CORES["serie1"][0],
        "Horas comprometidas por dia da semana",
    )
    tabela = _tabela(
        ("Dia", "Horas por semana"),
        [(nome, _numero(v) + "h") for nome, v in painel.carga_por_dia.items()],
    )
    return _cartao(
        "Como a semana dela está cheia",
        "Horas já comprometidas em agenda, na média das próximas "
        f"{painel.semanas_projetadas} semanas. O que sobra é o que existe para "
        "imprevisto, casa e descanso.",
        corpo,
        tabela,
    )


def _cartao_periodo(painel: Painel) -> str:
    corpo = _barras_rotuladas(
        {nome: painel.carga_por_periodo.get(nome, 0.0) for nome in PERIODOS},
        CORES["serie1"][0],
        "Horas comprometidas por período do dia",
        unidade="h",
    )
    tabela = _tabela(
        ("Período", "Horas por semana"),
        [
            (nome, _numero(painel.carga_por_periodo.get(nome, 0.0)) + "h")
            for nome in PERIODOS
        ],
    )
    return _cartao(
        "A que horas o dia dela acontece",
        "Manhã até meio-dia, tarde até 18h, noite depois disso. "
        "É aqui que aparece em que turno a rotina realmente pesa.",
        corpo,
        tabela,
    )


def _cartao_estudo(painel: Painel) -> str:
    e = painel.estudo
    if not e.get("blocos_reservados"):
        return _cartao(
            "As janelas de estudo",
            "",
            _vazio("Nenhum bloco de estudo reservado na janela consultada."),
        )
    corpo = _barras_rotuladas(
        e["semana_tipica"],
        CORES["serie3"][0],
        "Horas de estudo reservadas por dia da semana",
        unidade="h",
    )
    ate = e["ultimo_dia"].strftime("%d/%m/%Y") if e.get("ultimo_dia") else ""
    corpo += (
        f'<p class="lacuna"><b>{_numero(e["horas_reservadas"])} horas '
        f"reservadas em {e['blocos_reservados']} blocos até {ate}.</b>"
        f"O painel mostra o que está reservado, não o que foi cumprido: a "
        f"agenda não registra presença. Quanto dessas horas virou estudo de "
        f"verdade só passa a ser mensurável quando ela fecha a tarefa pela "
        f"Sábia, e essa contagem começa agora.</p>"
    )
    tabela = _tabela(
        ("Dia", "Horas de estudo por semana"),
        [(nome, _numero(v) + "h") for nome, v in e["semana_tipica"].items()],
    )
    return _cartao(
        "As janelas de estudo",
        f"{_numero(e['horas_por_semana'])} horas por semana, sempre depois das "
        "19h, com as crianças cobertas pela avó de segunda a quarta e pelo "
        "Wagner na quinta. É a janela que o sistema inteiro existe para proteger.",
        corpo,
        tabela,
    )


def _cartao_onde(painel: Painel) -> str:
    if not painel.onde:
        return ""
    dados: dict[str, float | int] = dict(painel.onde)
    corpo = _barras_rotuladas(
        dados, CORES["serie1"][0], "Tarefas por frente da vida"
    )
    tabela = _tabela(
        ("Frente", "Tarefas"),
        [(nome, str(valor)) for nome, valor in painel.onde.items()],
    )
    return _cartao(
        "Em que frente a tarefa cai",
        "Faculdade, casa, trabalho e pessoal disputam a mesma pessoa e a "
        "mesma semana.",
        corpo,
        tabela,
    )


def renderizar(painel: Painel) -> str:
    """Monta a página inteira. Recebe tudo calculado e não faz conta."""
    e = painel.estudo
    horas_estudo = e.get("horas_por_semana") or 0
    gerado = painel.gerado_em.strftime("%d/%m/%Y")

    heroi = (
        f'<section class="heroi"><b>{_numero(horas_estudo)}h</b>'
        "<span>por semana de janela protegida para estudar, todas entre 19h e "
        "22h. Esse é o tempo que a rotina dela deixa, e é em cima dele que "
        "todo o resto do sistema foi desenhado.</span></section>"
    )

    aviso = (
        '<p class="aviso">Este painel mostra contagem, quadrante, horário e '
        "data. Ele não mostra, não guarda e não exporta o texto de nenhuma "
        "tarefa nem de nenhum compromisso: o título é lido uma vez para "
        "decidir se aquilo é estudo ou trabalho e descartado em seguida. "
        f"A medição de quadrante e de data de conclusão começou em "
        f"{INICIO_MEDICAO.strftime('%d/%m/%Y')}, então o que é anterior a essa "
        "data aparece marcado como sem medição, e não como zero.</p>"
    )

    corpo = "".join(
        [
            heroi,
            _tiles(painel),
            _grafico_por_mes(painel),
            _cartao_semana(painel),
            _cartao_periodo(painel),
            _cartao_estudo(painel),
            _cartao_eisenhower(painel),
            _cartao_conclusao(painel),
            _cartao_onde(painel),
        ]
    )

    return (
        "<!doctype html>\n"
        '<html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>A semana da Bruna — painel de produtividade</title>"
        f"<style>{ESTILO}</style></head><body><div class=\"folha\">"
        "<header><h1>A semana da Bruna</h1>"
        '<p class="linha">Painel de produtividade da rotina real: onde as horas '
        "caem, o que foi priorizado e o que ainda não dá para medir.</p>"
        f'<p class="linha">Gerado em {_e(gerado)} · fonte: {_e(painel.origem)}'
        "</p>"
        f"{aviso}</header>"
        f"<main>{corpo}</main>"
        "<footer>Tarefas vêm da base do Notion alimentada pela Sábia no "
        "Telegram; compromissos vêm da Google Agenda. Nenhum número desta "
        "página é estimado: o que não pode ser calculado com dado real aparece "
        "escrito como não mensurável, com o motivo.</footer>"
        "</div></body></html>\n"
    )
