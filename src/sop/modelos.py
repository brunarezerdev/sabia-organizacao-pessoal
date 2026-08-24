"""Estruturas de dados que circulam entre as camadas do sistema."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

# Estados possíveis de uma tarefa no kanban de projetos.
ESTADOS_KANBAN = ("backlog", "a_fazer", "em_andamento", "bloqueado", "concluido")


@dataclass(frozen=True)
class Mensagem:
    """Uma mensagem capturada em algum canal de entrada (ex.: Telegram)."""

    id: str
    texto: str
    autor: str = ""
    canal: str = "telegram"
    recebida_em: str = ""  # ISO 8601


@dataclass
class Classificacao:
    """Resultado da camada de IA: para onde vai e o que virou."""

    agente: str
    categoria: str
    titulo: str
    data: str | None = None
    hora: str | None = None
    duracao_minutos: int | None = None
    valor: float | None = None
    projeto: str | None = None
    disciplina: str | None = None
    estado: str | None = None
    recorrencia: str | None = None
    observacao: str = ""
    precisa_confirmacao: bool = False
    confianca: float = 0.0
    origem: str = "heuristica"  # "ia" ou "heuristica"

    def para_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Item:
    """Um registro pronto para gravação no banco no-code."""

    titulo: str
    agente: str
    categoria: str
    data: str | None = None
    hora: str | None = None
    observacao: str = ""
    extras: dict[str, Any] = field(default_factory=dict)
    origem_mensagem_id: str = ""

    @classmethod
    def da_classificacao(cls, c: Classificacao, mensagem: Mensagem) -> "Item":
        extras = {
            chave: valor
            for chave, valor in {
                "duracao_minutos": c.duracao_minutos,
                "valor": c.valor,
                "projeto": c.projeto,
                "disciplina": c.disciplina,
                "estado": c.estado,
                "recorrencia": c.recorrencia,
                "precisa_confirmacao": c.precisa_confirmacao,
            }.items()
            if valor not in (None, "", False)
        }
        return cls(
            titulo=c.titulo,
            agente=c.agente,
            categoria=c.categoria,
            data=c.data,
            hora=c.hora,
            observacao=c.observacao,
            extras=extras,
            origem_mensagem_id=mensagem.id,
        )


@dataclass
class ResultadoAutomacao:
    """O que a automação de ponta a ponta produziu para uma mensagem."""

    mensagem_id: str
    classificacao: Classificacao
    item: Item
    id_no_banco: str | None = None
    id_do_evento: str | None = None
    erros: list[str] = field(default_factory=list)

    @property
    def sucesso(self) -> bool:
        return not self.erros

    def resumo(self) -> str:
        partes = [f"[{self.classificacao.agente}] {self.item.titulo}"]
        if self.item.data:
            quando = self.item.data + (f" {self.item.hora}" if self.item.hora else "")
            partes.append(f"em {quando}")
        if self.id_do_evento:
            partes.append("(evento criado na agenda)")
        if self.classificacao.precisa_confirmacao:
            partes.append("— precisa de confirmação")
        return " ".join(partes)
