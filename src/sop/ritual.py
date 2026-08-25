"""O ritual de domingo: fecha a semana que terminou e abre a que começa.

São vinte minutos, uma vez por semana, divididos em duas metades:

    FECHAR   o que foi feito, o que não foi e por quê, o que volta, o que morre
    ABRIR    compromissos, os efeitos que eles geram, checklist e 3 prioridades

O que este módulo faz é montar o pacote pronto. Ele lê a agenda dos dois lados
da semana, passa a semana que vem pelo motor de regras e devolve um objeto que
sabe se transformar em texto de Telegram ou em blocos do Notion.

O que ele deliberadamente NÃO faz: dizer o que ela fez ou deixou de fazer. O
sistema não tem como saber isso, então o fechamento entrega os compromissos que
existiram e deixa a marcação para ela, em checkbox. Fingir que sabe seria pior
do que perguntar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Protocol, Sequence

from .regras import EventoAgenda, ItemEstoque, MotorDeRegras, TarefaDerivada

# O checklist fixo do "para a semana começar". Sai igual ao da página do Notion,
# de propósito: o papel e a tela precisam dizer a mesma coisa.
CHECKLIST_ABERTURA = (
    "Agenda da semana olhada de ponta a ponta",
    "Compromissos das crianças conferidos, incluindo o que precisam levar na escola",
    "Dinheiro separado para o que só aceita dinheiro",
    "Cardápio da semana decidido",
    "Lista de compras fechada, com os essenciais que estão acabando",
    "Entregas da faculdade com data conferidas",
)

PERGUNTA_DE_BALANCO = "O que te custou mais energia do que devia esta semana?"


class FonteDeAgenda(Protocol):
    def listar_eventos(
        self, inicio_iso: str, fim_iso: str, limite: int = ...
    ) -> list[dict[str, Any]]: ...


# -- semanas ----------------------------------------------------------------


def domingo_de(hoje: date) -> date:
    """O domingo do ritual: hoje, se hoje for domingo, senão o próximo."""
    return hoje + timedelta(days=(6 - hoje.weekday()) % 7)


def semana_que_terminou(domingo: date) -> tuple[date, date]:
    """Segunda a domingo, terminando no próprio dia do ritual."""
    return domingo - timedelta(days=6), domingo


def semana_que_comeca(domingo: date) -> tuple[date, date]:
    """Segunda a domingo, começando no dia seguinte ao ritual."""
    return domingo + timedelta(days=1), domingo + timedelta(days=7)


def _intervalo_rfc3339(inicio: date, fim: date) -> tuple[str, str]:
    """A Google Calendar API pede timestamps, não datas soltas."""
    return f"{inicio.isoformat()}T00:00:00Z", f"{(fim + timedelta(days=1)).isoformat()}T00:00:00Z"


# -- as duas metades --------------------------------------------------------


@dataclass
class Fechamento:
    inicio: str
    fim: str
    compromissos: list[EventoAgenda] = field(default_factory=list)
    pergunta: str = PERGUNTA_DE_BALANCO

    @property
    def periodo(self) -> str:
        return f"{self.inicio} a {self.fim}"


@dataclass
class Abertura:
    inicio: str
    fim: str
    compromissos: list[EventoAgenda] = field(default_factory=list)
    efeitos: list[TarefaDerivada] = field(default_factory=list)
    alertas_estoque: list[TarefaDerivada] = field(default_factory=list)
    checklist: tuple[str, ...] = CHECKLIST_ABERTURA

    @property
    def periodo(self) -> str:
        return f"{self.inicio} a {self.fim}"


@dataclass
class PacoteRitual:
    """As duas metades juntas, prontas para sair pelo Telegram ou pelo Notion."""

    domingo: str
    fechamento: Fechamento
    abertura: Abertura

    # -- Telegram ------------------------------------------------------------

    def para_telegram(self) -> str:
        f, a = self.fechamento, self.abertura
        linhas = [f"Ritual de domingo, {self.domingo}", ""]

        linhas.append(f"FECHAR A SEMANA ({f.periodo})")
        if f.compromissos:
            linhas.append("Esteve na sua agenda:")
            linhas += [f"  [ ] {e.data}, {e.titulo}" for e in f.compromissos]
            linhas.append("Marque o que aconteceu de verdade. O que não aconteceu, "
                          "escreva por quê em uma linha.")
        else:
            linhas.append("Nenhum compromisso na agenda desta semana.")
        linhas += ["O que volta para a semana que vem: ",
                   "O que morre aqui: ",
                   f"Balanço: {f.pergunta}", ""]

        linhas.append(f"ABRIR A SEMANA ({a.periodo})")
        if a.compromissos:
            linhas.append("Compromissos:")
            linhas += [f"  {e.data}, {e.titulo}" for e in a.compromissos]
        else:
            linhas.append("Nenhum compromisso marcado ainda.")

        if a.efeitos:
            linhas.append("")
            linhas.append("Efeito borboleta, o que esses compromissos geram:")
            for t in a.efeitos:
                marca = "  [ ] " if not t.condicional else "  [ ] se acontecer: "
                prazo = f" (até {t.prazo})" if t.prazo else ""
                linhas.append(f"{marca}{t.titulo}{prazo}")

        if a.alertas_estoque:
            linhas.append("")
            linhas.append("Essenciais acabando:")
            linhas += [f"  [ ] {t.titulo}" for t in a.alertas_estoque]

        linhas.append("")
        linhas.append("Para a semana começar:")
        linhas += [f"  [ ] {item}" for item in a.checklist]
        linhas += ["", "As três prioridades da semana:", "  1. ", "  2. ", "  3. "]
        return "\n".join(linhas)

    # -- Notion --------------------------------------------------------------

    def para_blocos_notion(self) -> list[dict[str, Any]]:
        """Blocos prontos para anexar na página do Ritual de Domingo."""
        f, a = self.fechamento, self.abertura
        blocos: list[dict[str, Any]] = [
            _h2(f"Ritual de {self.domingo}"),
            _callout(
                "Pacote gerado pelo sistema a partir da sua agenda e da base de Regras. "
                "É só marcar, corrigir o que estiver errado e completar as três prioridades.",
                "🤖",
            ),
            _h3(f"Fechar a semana, {f.periodo}"),
        ]
        if f.compromissos:
            blocos += [_todo(f"{e.data}, {e.titulo}") for e in f.compromissos]
        else:
            blocos.append(_p("Nenhum compromisso na agenda desta semana."))
        blocos += [
            _p("O que volta para a semana que vem: [ ]"),
            _p("O que morre aqui: [ ]"),
            _callout(f.pergunta, "❓", "yellow_background"),
            _h3(f"Abrir a semana, {a.periodo}"),
        ]
        if a.compromissos:
            blocos += [_p(f"{e.data}, {e.titulo}") for e in a.compromissos]
        else:
            blocos.append(_p("Nenhum compromisso marcado ainda."))

        if a.efeitos:
            blocos.append(_callout("Efeito borboleta, o que esses compromissos geram.",
                                   "🦋", "purple_background"))
            for t in a.efeitos:
                prefixo = "Se acontecer: " if t.condicional else ""
                prazo = f" (até {t.prazo})" if t.prazo else ""
                blocos.append(_todo(f"{prefixo}{t.titulo}{prazo}, por causa de {t.gatilho}"))

        if a.alertas_estoque:
            blocos.append(_h3("Essenciais acabando"))
            blocos += [_todo(t.titulo) for t in a.alertas_estoque]

        blocos.append(_h3("Para a semana começar"))
        blocos += [_todo(item) for item in a.checklist]
        blocos.append(_h3("As três prioridades da semana"))
        blocos += [_todo("1. "), _todo("2. "), _todo("3. ")]
        return blocos


# -- montagem dos blocos do Notion ------------------------------------------


def _rt(texto: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": texto[:2000]}}]


def _bloco(tipo: str, texto: str, **extra: Any) -> dict[str, Any]:
    conteudo: dict[str, Any] = {"rich_text": _rt(texto)}
    conteudo.update(extra)
    return {"object": "block", "type": tipo, tipo: conteudo}


def _h2(t: str) -> dict[str, Any]:
    return _bloco("heading_2", t)


def _h3(t: str) -> dict[str, Any]:
    return _bloco("heading_3", t)


def _p(t: str) -> dict[str, Any]:
    return _bloco("paragraph", t)


def _todo(t: str) -> dict[str, Any]:
    return _bloco("to_do", t, checked=False)


def _callout(t: str, emoji: str = "💡", cor: str = "gray_background") -> dict[str, Any]:
    return {
        "object": "block",
        "type": "callout",
        "callout": {"rich_text": _rt(t), "icon": {"type": "emoji", "emoji": emoji},
                    "color": cor},
    }


# -- o ritual ---------------------------------------------------------------


class Ritual:
    """Monta o pacote do domingo cruzando agenda, regras e estoque."""

    def __init__(self, motor: MotorDeRegras, agenda: FonteDeAgenda | None = None) -> None:
        self.motor = motor
        self.agenda = agenda

    def _eventos(self, inicio: date, fim: date) -> list[EventoAgenda]:
        """Lê a agenda no intervalo. Sem agenda configurada, devolve vazio."""
        if self.agenda is None:
            return []
        from .regras import eventos_do_google

        inicio_iso, fim_iso = _intervalo_rfc3339(inicio, fim)
        return eventos_do_google(self.agenda.listar_eventos(inicio_iso, fim_iso))

    def fechar(
        self, domingo: date, eventos: Sequence[EventoAgenda] | None = None
    ) -> Fechamento:
        inicio, fim = semana_que_terminou(domingo)
        passados = list(eventos) if eventos is not None else self._eventos(inicio, fim)
        return Fechamento(
            inicio=inicio.isoformat(),
            fim=fim.isoformat(),
            compromissos=sorted(passados, key=lambda e: (e.data, e.titulo)),
        )

    def abrir(
        self,
        domingo: date,
        eventos: Sequence[EventoAgenda] | None = None,
        estoque: Sequence[ItemEstoque] = (),
    ) -> Abertura:
        inicio, fim = semana_que_comeca(domingo)
        futuros = list(eventos) if eventos is not None else self._eventos(inicio, fim)
        futuros.sort(key=lambda e: (e.data, e.titulo))
        return Abertura(
            inicio=inicio.isoformat(),
            fim=fim.isoformat(),
            compromissos=futuros,
            efeitos=self.motor.aplicar_agenda(futuros),
            alertas_estoque=self.motor.aplicar_estoque(
                estoque, em=inicio.isoformat()
            ),
        )

    def pacote(
        self,
        domingo: date,
        eventos_passados: Sequence[EventoAgenda] | None = None,
        eventos_futuros: Sequence[EventoAgenda] | None = None,
        estoque: Sequence[ItemEstoque] = (),
    ) -> PacoteRitual:
        return PacoteRitual(
            domingo=domingo.isoformat(),
            fechamento=self.fechar(domingo, eventos_passados),
            abertura=self.abrir(domingo, eventos_futuros, estoque),
        )
