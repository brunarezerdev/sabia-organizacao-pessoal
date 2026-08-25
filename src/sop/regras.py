"""Motor de regras se-então: o efeito borboleta do sistema.

A ideia, na linguagem de quem pediu: todo compromisso gera efeito. Se tem
consulta médica, precisa ter dinheiro na mão. Se o dinheiro não está na mão,
alguém precisa sacar, e isso vira outro compromisso. Uma coisa puxa a outra.

Aqui isso vira código em três peças:

    Regra          o se-então, escrito por ela no Notion, sem programar
    Gatilho        um evento da agenda da semana ou um item de estoque acabando
    TarefaDerivada o que nasce do cruzamento dos dois

O motor não decide nada sozinho: ele só cruza. Toda a inteligência do que
acontece está na base de Regras, que é editável por quem usa. Acrescentar uma
regra nova não exige tocar neste arquivo.

Efeito de primeira e de segunda ordem
-------------------------------------
Cada frase do campo "Então" vira uma tarefa. Frases que começam com "Se" são
efeitos de segunda ordem: dependem de uma checagem humana antes de existirem de
verdade. É exatamente o caso do exemplo dela, em que a falta do dinheiro é que
cria a tarefa de pedir para sacar.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable, Sequence

# Origens possíveis de um gatilho. "Agenda" cruza com os eventos da semana,
# "Estoque" cruza com a lista de essenciais da casa.
ORIGEM_AGENDA = "Agenda"
ORIGEM_ESTOQUE = "Estoque"

# Palavras que marcam um item como acabando, quando ela não usa checkbox.
MARCAS_DE_FALTA = ("acabando", "acabou", "ultimo", "ultima", "sobrou pouco", "falta")

_FIM_DE_FRASE = re.compile(r"(?<=[.;])\s+")


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento e sem espaço sobrando.

    A comparação precisa funcionar com o texto real da agenda, que vem digitado
    com pressa, às vezes sem acento e com maiúscula onde der.
    """
    decomposto = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento.lower()).strip()


def _casa_termo(texto_normalizado: str, termo: str) -> bool:
    """Procura um termo inteiro no texto, respeitando limite de palavra.

    Termo com mais de uma palavra é procurado como frase, o que permite escrever
    "escola da nina" sem que todo evento com a palavra "nina" dispare. Nina é um
    nome fictício, usado só como exemplo.
    """
    termo = normalizar(termo)
    if not termo:
        return False
    padrao = r"\b" + r"\s+".join(re.escape(p) for p in termo.split()) + r"\b"
    return re.search(padrao, texto_normalizado) is not None


# -- gatilhos ---------------------------------------------------------------


@dataclass(frozen=True)
class EventoAgenda:
    """Um compromisso da agenda, já reduzido ao que o motor precisa."""

    titulo: str
    data: str  # ISO, AAAA-MM-DD
    descricao: str = ""
    id: str = ""

    @property
    def texto(self) -> str:
        return f"{self.titulo} {self.descricao}".strip()

    @property
    def quando(self) -> date:
        return date.fromisoformat(self.data)

    @classmethod
    def do_google(cls, bruto: dict[str, Any]) -> "EventoAgenda":
        """Converte o JSON da Google Calendar API v3.

        Evento de dia inteiro vem em `start.date`, evento com hora vem em
        `start.dateTime`. Os dois viram a mesma data ISO aqui.
        """
        inicio = bruto.get("start", {}) or {}
        bruta = inicio.get("date") or inicio.get("dateTime", "")
        return cls(
            titulo=bruto.get("summary", "") or "(sem título)",
            data=bruta[:10],
            descricao=bruto.get("description", "") or "",
            id=str(bruto.get("id", "")),
        )


@dataclass(frozen=True)
class ItemEstoque:
    """Um item da lista de essenciais da casa."""

    nome: str
    situacao: str = ""  # texto livre: "acabando", "sobrou pouco", "ok"
    essencial: bool = True

    @property
    def texto(self) -> str:
        return f"{self.nome} {self.situacao}".strip()

    @property
    def acabando(self) -> bool:
        normal = normalizar(self.situacao)
        return any(_casa_termo(normal, marca) for marca in MARCAS_DE_FALTA)


# -- regra ------------------------------------------------------------------


@dataclass(frozen=True)
class Regra:
    """Uma linha da base de Regras do Notion."""

    nome: str
    se: str
    entao: str
    area: str = ""
    origem: str = ORIGEM_AGENDA
    palavras_chave: tuple[str, ...] = ()
    antecedencia_dias: int = 0
    ativa: bool = True
    observacao: str = ""

    def casa_com(self, texto: str) -> bool:
        """A regra reconhece este gatilho?

        Os termos são alternativas, basta um casar. Preferimos gerar uma tarefa
        a mais, que ela desmarca em um clique, do que deixar a criança sair sem
        o material que a escola pediu.
        """
        if not self.palavras_chave:
            return False
        normalizado = normalizar(texto)
        return any(_casa_termo(normalizado, termo) for termo in self.palavras_chave)

    def acoes(self) -> list[tuple[str, int]]:
        """Quebra o "Então" em ações, com a ordem do efeito de cada uma.

        Devolve pares (texto, ordem), em que ordem 1 é o efeito direto e ordem 2
        é o efeito que só existe se uma condição for verdadeira.
        """
        partes = [p.strip(" .;") for p in _FIM_DE_FRASE.split(self.entao or "")]
        acoes: list[tuple[str, int]] = []
        for parte in partes:
            if not parte:
                continue
            ordem = 2 if normalizar(parte).startswith("se ") else 1
            acoes.append((parte, ordem))
        return acoes

    def prazo_para(self, quando: date) -> str:
        return (quando - timedelta(days=max(self.antecedencia_dias, 0))).isoformat()

    # -- leitura do Notion ---------------------------------------------------

    @staticmethod
    def _texto(prop: dict[str, Any]) -> str:
        tipo = prop.get("type", "")
        if tipo in ("title", "rich_text"):
            return "".join(p.get("plain_text", "") for p in prop.get(tipo) or [])
        if tipo == "select":
            return (prop.get("select") or {}).get("name", "")
        if tipo == "number":
            valor = prop.get("number")
            return "" if valor is None else str(valor)
        if tipo == "checkbox":
            return "sim" if prop.get("checkbox") else ""
        return ""

    @classmethod
    def da_pagina_notion(cls, pagina: dict[str, Any]) -> "Regra":
        """Converte uma linha da base de Regras.

        Nomes de propriedade ausentes viram vazio em vez de estourar: a base é
        editada à mão, e uma coluna renomeada não pode derrubar o domingo dela.
        """
        props = pagina.get("properties", {}) or {}

        def ler(nome: str) -> str:
            prop = props.get(nome)
            return cls._texto(prop) if prop else ""

        bruto = props.get("Antecedência em dias", {}) or {}
        antecedencia = bruto.get("number")
        ativa_prop = props.get("Ativa", {}) or {}

        return cls(
            nome=ler("Nome"),
            se=ler("Se"),
            entao=ler("Então"),
            area=ler("Área"),
            origem=ler("Origem") or ORIGEM_AGENDA,
            palavras_chave=tuple(
                t.strip() for t in ler("Palavras-chave").split(",") if t.strip()
            ),
            antecedencia_dias=int(antecedencia or 0),
            ativa=bool(ativa_prop.get("checkbox", True)),
            observacao=ler("Observação"),
        )

    @classmethod
    def de_dict(cls, dados: dict[str, Any]) -> "Regra":
        """Constrói a partir de um dicionário simples, usado pelos exemplos."""
        chaves = dados.get("palavras_chave", [])
        if isinstance(chaves, str):
            chaves = [t.strip() for t in chaves.split(",") if t.strip()]
        return cls(
            nome=dados.get("nome", ""),
            se=dados.get("se", ""),
            entao=dados.get("entao", ""),
            area=dados.get("area", ""),
            origem=dados.get("origem", ORIGEM_AGENDA),
            palavras_chave=tuple(chaves),
            antecedencia_dias=int(dados.get("antecedencia_dias", 0) or 0),
            ativa=bool(dados.get("ativa", True)),
            observacao=dados.get("observacao", ""),
        )


# -- saída ------------------------------------------------------------------


@dataclass
class TarefaDerivada:
    """O que nasceu do cruzamento de uma regra com um gatilho."""

    titulo: str
    area: str
    regra: str
    gatilho: str
    prazo: str | None = None
    ordem: int = 1  # 1 = efeito direto, 2 = efeito condicional
    observacao: str = ""

    @property
    def condicional(self) -> bool:
        return self.ordem >= 2

    def linha(self) -> str:
        """Uma linha pronta para checkbox, no Telegram ou no Notion."""
        partes = [self.titulo]
        if self.prazo:
            partes.append(f"até {self.prazo}")
        partes.append(f"({self.gatilho})")
        return " ".join(partes)


class MotorDeRegras:
    """Cruza as regras com os gatilhos da semana."""

    def __init__(self, regras: Iterable[Regra]) -> None:
        self.regras = [r for r in regras]

    def __len__(self) -> int:
        return len(self.regras)

    def ativas(self, origem: str) -> list[Regra]:
        return [r for r in self.regras if r.ativa and r.origem == origem]

    def aplicar_agenda(self, eventos: Sequence[EventoAgenda]) -> list[TarefaDerivada]:
        """Cada evento da semana passa por todas as regras de agenda."""
        tarefas: list[TarefaDerivada] = []
        for evento in eventos:
            for regra in self.ativas(ORIGEM_AGENDA):
                if not regra.casa_com(evento.texto):
                    continue
                gatilho = f"{evento.titulo}, {evento.data}"
                for texto, ordem in regra.acoes():
                    tarefas.append(
                        TarefaDerivada(
                            titulo=texto,
                            area=regra.area,
                            regra=regra.nome,
                            gatilho=gatilho,
                            prazo=regra.prazo_para(evento.quando),
                            ordem=ordem,
                            observacao=regra.observacao,
                        )
                    )
        return self._ordenar(tarefas)

    def aplicar_estoque(
        self, itens: Sequence[ItemEstoque], em: str | None = None
    ) -> list[TarefaDerivada]:
        """Itens essenciais acabando viram tarefa de compra."""
        tarefas: list[TarefaDerivada] = []
        for item in itens:
            if not (item.essencial and item.acabando):
                continue
            for regra in self.ativas(ORIGEM_ESTOQUE):
                if not regra.casa_com(item.texto):
                    continue
                for texto, ordem in regra.acoes():
                    tarefas.append(
                        TarefaDerivada(
                            titulo=f"{texto}: {item.nome}",
                            area=regra.area,
                            regra=regra.nome,
                            gatilho=f"{item.nome}, {item.situacao}".strip(", "),
                            prazo=em,
                            ordem=ordem,
                            observacao=regra.observacao,
                        )
                    )
        return self._ordenar(tarefas)

    def aplicar(
        self,
        eventos: Sequence[EventoAgenda] = (),
        estoque: Sequence[ItemEstoque] = (),
        em: str | None = None,
    ) -> list[TarefaDerivada]:
        return self._ordenar(
            self.aplicar_agenda(eventos) + self.aplicar_estoque(estoque, em=em)
        )

    @staticmethod
    def _ordenar(tarefas: list[TarefaDerivada]) -> list[TarefaDerivada]:
        """Mais urgente primeiro, e o efeito direto antes do condicional."""
        return sorted(tarefas, key=lambda t: (t.prazo or "9999-12-31", t.ordem, t.titulo))


# -- carregamento -----------------------------------------------------------


def regras_de_lista(dados: Iterable[dict[str, Any]]) -> list[Regra]:
    return [Regra.de_dict(d) for d in dados]


def regras_do_notion(paginas: Iterable[dict[str, Any]]) -> list[Regra]:
    return [Regra.da_pagina_notion(p) for p in paginas]


def eventos_do_google(brutos: Iterable[dict[str, Any]]) -> list[EventoAgenda]:
    eventos = [EventoAgenda.do_google(b) for b in brutos]
    return [e for e in eventos if e.data]


def estoque_de_lista(dados: Iterable[dict[str, Any]]) -> list[ItemEstoque]:
    return [
        ItemEstoque(
            nome=d.get("nome", ""),
            situacao=d.get("situacao", ""),
            essencial=bool(d.get("essencial", True)),
        )
        for d in dados
    ]
