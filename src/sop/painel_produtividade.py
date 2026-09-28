"""Painel de produtividade — a rotina real, medida com o dado que existe.

Este módulo é o coração do painel e tem uma regra que vale mais que qualquer
funcionalidade: **nenhum texto de tarefa ou de compromisso entra aqui**.

Os dois conversores de fronteira (`tarefa_de_pagina` e `compromisso_de_evento`)
recebem o JSON cru do Notion e da Google Agenda e devolvem registros que não
têm campo de texto nenhum. O título é lido uma única vez, dentro de
`faixa_do_titulo`, apenas para decidir se aquele compromisso é estudo ou
trabalho, e é descartado na mesma expressão. Nada depois da fronteira consegue
vazar conteúdo pessoal porque o conteúdo já não existe mais na memória do
processo.

A classificação por palavra-chave é deliberadamente conservadora: só entra em
"Estudo" ou "Trabalho" o que casa com um termo explícito. Todo o resto cai em
"Outros" sem ser caracterizado — consulta médica, escola das crianças e
compromisso de família viram um número numa categoria neutra, e não uma
etiqueta que descreva a vida de alguém.

Sobre os buracos de medição: parte das perguntas que um painel de produtividade
deveria responder ainda não tem resposta verdadeira, porque o dado passou a ser
gravado em 26/09/2026. Este módulo não preenche esse buraco com estimativa. Ele
devolve `None` e a razão, e a renderização mostra a razão no lugar do número.
"""

from __future__ import annotations

import statistics
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

# A partir desta data a base de tarefas passou a ter quadrante de Eisenhower e
# data de conclusão. Antes disso o dado não existia, e o painel diz isso em vez
# de mostrar caixa vazia.
INICIO_MEDICAO = date(2026, 9, 26)

QUADRANTES = (
    "Urgente e importante",
    "Importante e não urgente",
    "Urgente e não importante",
    "Nem urgente nem importante",
)
SEM_QUADRANTE = "Sem quadrante"

FAIXA_ESTUDO = "Estudo"
FAIXA_TRABALHO = "Trabalho"
FAIXA_OUTROS = "Outros"
FAIXAS = (FAIXA_ESTUDO, FAIXA_TRABALHO, FAIXA_OUTROS)

# Termos que caracterizam a faixa. Curtos e explícitos de propósito: uma lista
# grande erraria mais, e cada erro aqui é um número falso no painel.
TERMOS_ESTUDO = (
    "estudo",
    "aula",
    "rocketseat",
    "unifecaf",
    "avalanche",
    "faculdade",
    "disciplina",
    "prova",
)
TERMOS_TRABALHO = (
    "e-gig",
    "egig",
    "bloco de trabalho",
    "reuniao",
    "cliente",
    "sprint",
)

DIAS_DA_SEMANA = (
    "Segunda",
    "Terça",
    "Quarta",
    "Quinta",
    "Sexta",
    "Sábado",
    "Domingo",
)

PERIODOS = ("Manhã", "Tarde", "Noite")


def _sem_acento(texto: str) -> str:
    decomposto = unicodedata.normalize("NFD", texto.casefold())
    return "".join(c for c in decomposto if unicodedata.category(c) != "Mn")


def faixa_do_titulo(titulo: str) -> str:
    """Única função do projeto autorizada a ler o texto de um compromisso.

    Devolve só a faixa. O título não sai daqui, não é guardado e não é logado.
    """
    normalizado = _sem_acento(titulo or "")
    if any(termo in normalizado for termo in TERMOS_ESTUDO):
        return FAIXA_ESTUDO
    if any(termo in normalizado for termo in TERMOS_TRABALHO):
        return FAIXA_TRABALHO
    return FAIXA_OUTROS


# -- registros anônimos ------------------------------------------------------


@dataclass(frozen=True)
class Tarefa:
    """Uma tarefa sem a tarefa. Só o esqueleto que o painel precisa medir."""

    registrada_em: date
    quadrante: str | None = None
    onde: str | None = None
    feita: bool = False
    concluida_em: date | None = None
    prazo: date | None = None

    @property
    def giro_em_dias(self) -> int | None:
        """Dias entre registrar e concluir, quando as duas datas existem."""
        if self.concluida_em is None:
            return None
        return (self.concluida_em - self.registrada_em).days


@dataclass(frozen=True)
class Compromisso:
    """Um compromisso sem o compromisso: quando, quanto durou, de que faixa."""

    dia: date
    faixa: str = FAIXA_OUTROS
    horas: float = 0.0
    hora_inicio: int | None = None
    recorrente: bool = False
    dia_inteiro: bool = False

    @property
    def periodo(self) -> str | None:
        if self.hora_inicio is None:
            return None
        if self.hora_inicio < 12:
            return "Manhã"
        return "Tarde" if self.hora_inicio < 18 else "Noite"


# -- fronteira: JSON cru -> registro anônimo ---------------------------------


def _data_opcional(valor: Any) -> date | None:
    if not valor:
        return None
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        return None


def tarefa_de_pagina(pagina: dict[str, Any]) -> Tarefa | None:
    """Converte uma página do Notion em `Tarefa`, descartando o título.

    Devolve `None` quando nem a data de registro existe: sem ela o item não
    entra em nenhuma conta, e inventar uma data seria falsear o painel.
    """
    propriedades = pagina.get("properties", {}) or {}

    def select(nome: str) -> str | None:
        valor = (propriedades.get(nome, {}) or {}).get("select") or {}
        return valor.get("name") or None

    def data(nome: str) -> date | None:
        valor = (propriedades.get(nome, {}) or {}).get("date") or {}
        return _data_opcional(valor.get("start"))

    registrada = _data_opcional(
        (propriedades.get("Registrada em", {}) or {}).get("created_time")
    )
    if registrada is None:
        return None

    quadrante = select("Prioridade (Eisenhower)")
    return Tarefa(
        registrada_em=registrada,
        quadrante=quadrante if quadrante in QUADRANTES else None,
        onde=select("Onde"),
        feita=bool((propriedades.get("Feito", {}) or {}).get("checkbox")),
        concluida_em=data("Concluída em"),
        prazo=data("prazo"),
    )


def compromisso_de_evento(evento: dict[str, Any], fuso: str) -> Compromisso | None:
    """Converte um evento da Google Agenda em `Compromisso`, sem o título.

    Evento de dia inteiro não tem duração em horas e entra com `horas=0.0`:
    ele conta como compromisso, mas não infla a carga horária do dia.
    """
    inicio = evento.get("start", {}) or {}
    fim = evento.get("end", {}) or {}
    recorrente = bool(evento.get("recurringEventId"))
    faixa = faixa_do_titulo(evento.get("summary", ""))

    if inicio.get("date"):
        dia = _data_opcional(inicio["date"])
        if dia is None:
            return None
        return Compromisso(
            dia=dia, faixa=faixa, recorrente=recorrente, dia_inteiro=True
        )

    if not inicio.get("dateTime") or not fim.get("dateTime"):
        return None
    try:
        # O sufixo "Z" só é aceito por `fromisoformat` a partir do Python 3.11,
        # e uma agenda configurada em UTC devolve exatamente esse formato.
        abertura = datetime.fromisoformat(inicio["dateTime"].replace("Z", "+00:00"))
        fechamento = datetime.fromisoformat(fim["dateTime"].replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if abertura.tzinfo is None:
        abertura = abertura.replace(tzinfo=ZoneInfo(fuso))
    if fechamento.tzinfo is None:
        fechamento = fechamento.replace(tzinfo=ZoneInfo(fuso))

    zona = ZoneInfo(fuso)
    abertura = abertura.astimezone(zona)
    fechamento = fechamento.astimezone(zona)
    horas = max((fechamento - abertura).total_seconds() / 3600.0, 0.0)
    return Compromisso(
        dia=abertura.date(),
        faixa=faixa,
        horas=round(horas, 2),
        hora_inicio=abertura.hour,
        recorrente=recorrente,
    )


# -- medições ----------------------------------------------------------------


@dataclass(frozen=True)
class Medida:
    """Um número, ou a explicação honesta de por que ele não existe ainda."""

    valor: float | int | None
    sufixo: str = ""
    indisponivel: str = ""

    @property
    def tem_valor(self) -> bool:
        return self.valor is not None


def distribuicao_eisenhower(tarefas: list[Tarefa]) -> dict[str, int]:
    """Contagem por quadrante, com `Sem quadrante` sempre presente."""
    contagem = Counter(t.quadrante or SEM_QUADRANTE for t in tarefas)
    return {nome: contagem.get(nome, 0) for nome in (*QUADRANTES, SEM_QUADRANTE)}


def conclusao(tarefas: list[Tarefa]) -> dict[str, int]:
    """Concluídas contra registradas. `feita` é o checkbox, fato verificável."""
    return {
        "registradas": len(tarefas),
        "concluidas": sum(1 for t in tarefas if t.feita),
        "abertas": sum(1 for t in tarefas if not t.feita),
    }


def giro(tarefas: list[Tarefa]) -> Medida:
    """Mediana de dias entre registrar e concluir.

    Só entra quem tem as DUAS datas. Tarefa marcada como feita antes de a
    coluna de conclusão existir não tem como dizer quando foi feita, e por isso
    fica de fora em vez de virar estimativa.
    """
    giros = [g for t in tarefas if (g := t.giro_em_dias) is not None and g >= 0]
    if not giros:
        feitas_sem_data = sum(1 for t in tarefas if t.feita and t.concluida_em is None)
        motivo = (
            f"A data de conclusão passou a ser gravada em "
            f"{INICIO_MEDICAO.strftime('%d/%m/%Y')}. "
        )
        if feitas_sem_data:
            motivo += (
                f"As {feitas_sem_data} tarefas concluídas antes disso não têm essa "
                "data, então o tempo de giro ainda não pode ser calculado."
            )
        else:
            motivo += "Nenhuma tarefa foi concluída depois dessa data ainda."
        return Medida(valor=None, indisponivel=motivo)
    return Medida(valor=round(statistics.median(giros), 1), sufixo="dias")


def carga_por_dia(
    compromissos: list[Compromisso], semanas: int
) -> dict[str, float]:
    """Horas comprometidas por dia da semana, média nas `semanas` do recorte."""
    horas: dict[str, float] = {nome: 0.0 for nome in DIAS_DA_SEMANA}
    for c in compromissos:
        horas[DIAS_DA_SEMANA[c.dia.weekday()]] += c.horas
    divisor = max(semanas, 1)
    return {nome: round(total / divisor, 2) for nome, total in horas.items()}


def carga_por_periodo(
    compromissos: list[Compromisso], semanas: int
) -> dict[str, float]:
    """Horas por período do dia. Evento de dia inteiro não tem período e sai fora."""
    horas: dict[str, float] = {nome: 0.0 for nome in PERIODOS}
    for c in compromissos:
        if c.periodo:
            horas[c.periodo] += c.horas
    divisor = max(semanas, 1)
    return {nome: round(total / divisor, 2) for nome, total in horas.items()}


def compromissos_por_mes(
    compromissos: list[Compromisso],
) -> dict[str, dict[str, int]]:
    """Pontuais e recorrentes por mês. É o retrato do antes e depois da rotina.

    Mês sem nenhum compromisso entra zerado em vez de sumir: um eixo de tempo
    com buraco faz o leitor comparar meses que não são vizinhos.
    """
    meses: dict[str, dict[str, int]] = {}
    for c in compromissos:
        mes = c.dia.strftime("%Y-%m")
        linha = meses.setdefault(mes, {"pontual": 0, "recorrente": 0})
        linha["recorrente" if c.recorrente else "pontual"] += 1
    if not meses:
        return {}

    chaves = sorted(meses)
    ano, mes = (int(p) for p in chaves[0].split("-"))
    ano_fim, mes_fim = (int(p) for p in chaves[-1].split("-"))
    completo: dict[str, dict[str, int]] = {}
    while (ano, mes) <= (ano_fim, mes_fim):
        chave = f"{ano:04d}-{mes:02d}"
        completo[chave] = meses.get(chave, {"pontual": 0, "recorrente": 0})
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return completo


def blocos_de_estudo(
    compromissos: list[Compromisso], hoje: date
) -> dict[str, Any]:
    """Horas de estudo já vividas e ainda reservadas, e a semana típica."""
    estudo = [c for c in compromissos if c.faixa == FAIXA_ESTUDO and c.horas > 0]
    passados = [c for c in estudo if c.dia < hoje]
    futuros = [c for c in estudo if c.dia >= hoje]
    por_dia: dict[str, float] = {nome: 0.0 for nome in DIAS_DA_SEMANA}
    semanas: set[tuple[int, int]] = set()
    for c in futuros:
        por_dia[DIAS_DA_SEMANA[c.dia.weekday()]] += c.horas
        semanas.add(c.dia.isocalendar()[:2])
    divisor = max(len(semanas), 1)
    return {
        "horas_ja_vividas": round(sum(c.horas for c in passados), 1),
        "horas_reservadas": round(sum(c.horas for c in futuros), 1),
        "blocos_reservados": len(futuros),
        "semanas_reservadas": len(semanas),
        "ultimo_dia": max((c.dia for c in futuros), default=None),
        "semana_tipica": {
            nome: round(total / divisor, 2) for nome, total in por_dia.items()
        },
        "horas_por_semana": round(
            sum(c.horas for c in futuros) / divisor, 1
        ),
    }


def por_onde(tarefas: list[Tarefa]) -> dict[str, int]:
    """Em que frente da vida a tarefa cai. `Onde` é preenchido por ela, não inferido."""
    contagem = Counter(t.onde or "Sem frente" for t in tarefas)
    return dict(sorted(contagem.items(), key=lambda par: (-par[1], par[0])))


# -- montagem ----------------------------------------------------------------


@dataclass
class Painel:
    """Tudo que o painel mostra, já calculado. A renderização não faz conta."""

    gerado_em: date
    origem: str
    janela_dias: int
    semanas_projetadas: int
    eisenhower: dict[str, int] = field(default_factory=dict)
    conclusao: dict[str, int] = field(default_factory=dict)
    giro: Medida = field(default_factory=lambda: Medida(None))
    carga_por_dia: dict[str, float] = field(default_factory=dict)
    carga_por_periodo: dict[str, float] = field(default_factory=dict)
    por_mes: dict[str, dict[str, int]] = field(default_factory=dict)
    estudo: dict[str, Any] = field(default_factory=dict)
    onde: dict[str, int] = field(default_factory=dict)
    compromissos_passados: int = 0
    compromissos_futuros: int = 0
    recorrentes_futuros: int = 0

    @property
    def horas_semana(self) -> float:
        return round(sum(self.carga_por_dia.values()), 1)


def montar(
    tarefas: list[Tarefa],
    compromissos: list[Compromisso],
    hoje: date,
    origem: str = "dados reais",
    janela_dias: int = 365,
) -> Painel:
    """Monta o painel inteiro a partir dos registros já anonimizados."""
    futuros = [c for c in compromissos if c.dia >= hoje]
    passados = [c for c in compromissos if c.dia < hoje]

    dias_projetados = max(
        ((max((c.dia for c in futuros), default=hoje)) - hoje).days, 1
    )
    semanas = max(round(dias_projetados / 7), 1)

    return Painel(
        gerado_em=hoje,
        origem=origem,
        janela_dias=janela_dias,
        semanas_projetadas=semanas,
        eisenhower=distribuicao_eisenhower(tarefas),
        conclusao=conclusao(tarefas),
        giro=giro(tarefas),
        carga_por_dia=carga_por_dia(futuros, semanas),
        carga_por_periodo=carga_por_periodo(futuros, semanas),
        por_mes=compromissos_por_mes(compromissos),
        estudo=blocos_de_estudo(compromissos, hoje),
        onde=por_onde(tarefas),
        compromissos_passados=len(passados),
        compromissos_futuros=len(futuros),
        recorrentes_futuros=sum(1 for c in futuros if c.recorrente),
    )


# -- coleta ------------------------------------------------------------------


def coletar_tarefas(cliente: Any, database_id: str, limite: int = 500) -> list[Tarefa]:
    """Lê a base de tarefas do Notion e devolve só registros anônimos."""
    paginas = cliente.consultar_database(database_id, limite=limite)
    return [t for pagina in paginas if (t := tarefa_de_pagina(pagina)) is not None]


def coletar_compromissos(
    agenda: Any, hoje: date, dias_atras: int = 365, dias_adiante: int = 120
) -> list[Compromisso]:
    """Lê a agenda em janelas de 14 dias e devolve só registros anônimos.

    A janela curta existe porque a API pagina por intervalo e um recorte largo
    demais devolve resultado truncado sem avisar.
    """
    fuso = ZoneInfo(agenda.config.timezone)
    inicio = datetime.combine(hoje - timedelta(days=dias_atras), datetime.min.time())
    fim = datetime.combine(hoje + timedelta(days=dias_adiante), datetime.min.time())
    inicio, fim = inicio.replace(tzinfo=fuso), fim.replace(tzinfo=fuso)

    vistos: dict[str, Compromisso] = {}
    cursor = inicio
    while cursor < fim:
        proximo = min(cursor + timedelta(days=14), fim)
        for evento in agenda.listar_eventos(
            cursor.isoformat(), proximo.isoformat(), limite=2500
        ):
            compromisso = compromisso_de_evento(evento, agenda.config.timezone)
            if compromisso is None:
                continue
            chave = f"{evento.get('id', '')}|{compromisso.dia.isoformat()}"
            vistos[chave] = compromisso
        cursor = proximo
    return list(vistos.values())
