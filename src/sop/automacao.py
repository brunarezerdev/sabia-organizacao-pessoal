"""Automação de ponta a ponta.

O fluxo demonstrável do projeto, em uma frase: uma mensagem no Telegram vira um
item classificado no Notion e, se tiver data, um evento na Google Agenda.

    Telegram  ->  Orquestradora  ->  IA (classifica)  ->  Notion (grava)
                                                      \\-> Google Agenda (se tiver data)

Falha parcial não derruba o fluxo: se a agenda estiver fora do ar, o item ainda
é gravado no Notion e o erro aparece em `ResultadoAutomacao.erros`. Perder o
registro seria pior do que perder o evento.
"""

from __future__ import annotations

from typing import Any, Protocol

from .modelos import Item, Mensagem, ResultadoAutomacao
from .orquestradora import Orquestradora


class DestinoBanco(Protocol):
    def criar_item(self, item: Item) -> str: ...


class DestinoAgenda(Protocol):
    def criar_evento(
        self,
        titulo: str,
        data: str,
        hora: str | None = ...,
        duracao_minutos: int = ...,
        descricao: str = ...,
    ) -> str: ...


class Automacao:
    """Costura orquestradora, banco no-code e agenda em um único fluxo."""

    def __init__(
        self,
        orquestradora: Orquestradora,
        banco: DestinoBanco | None = None,
        agenda: DestinoAgenda | None = None,
        notificar: Any | None = None,
    ) -> None:
        self.orquestradora = orquestradora
        self.banco = banco
        self.agenda = agenda
        self.notificar = notificar

    def executar(self, mensagem: Mensagem) -> ResultadoAutomacao:
        """Processa uma mensagem do começo ao fim."""
        classificacao, item = self.orquestradora.processar(mensagem)
        resultado = ResultadoAutomacao(
            mensagem_id=mensagem.id, classificacao=classificacao, item=item
        )

        # Informação essencial ausente interrompe a execução: primeiro se faz
        # a pergunta objetiva, depois uma nova mensagem completa o registro.
        # Assim a lacuna não vira silenciosamente dado incompleto no Notion ou
        # evento inexequível na agenda.
        if self.banco is not None and not classificacao.precisa_confirmacao:
            try:
                resultado.id_no_banco = self.banco.criar_item(item)
            except Exception as erro:  # noqa: BLE001 — o erro vai para o relatório
                resultado.erros.append(f"notion: {erro}")

        # 2. Cria o evento, se o item tiver data e o agente trabalhar com agenda.
        if (
            self.agenda is not None
            and not classificacao.precisa_confirmacao
            and self.orquestradora.deve_criar_evento(classificacao)
        ):
            try:
                resultado.id_do_evento = self.agenda.criar_evento(
                    titulo=item.titulo,
                    data=item.data or "",
                    hora=item.hora,
                    duracao_minutos=classificacao.duracao_minutos or 60,
                    descricao=item.observacao,
                )
            except Exception as erro:  # noqa: BLE001
                resultado.erros.append(f"google_calendar: {erro}")

        # 3. Devolve a confirmação para quem mandou a mensagem.
        if self.notificar is not None:
            try:
                self.notificar(self.montar_resposta(resultado))
            except Exception as erro:  # noqa: BLE001
                resultado.erros.append(f"telegram: {erro}")

        return resultado

    @staticmethod
    def montar_resposta(resultado: ResultadoAutomacao) -> str:
        """Texto curto de confirmação, do jeito que chega no Telegram."""
        c = resultado.classificacao
        if c.precisa_confirmacao:
            pergunta = (
                c.pergunta_confirmacao
                or c.observacao
                or "Qual informação falta para completar?"
            )
            linhas = [f"Antes de registrar: {pergunta}"]
        else:
            linhas = [f"Anotado em *{c.agente}* ({c.categoria}): {resultado.item.titulo}"]

        if resultado.item.data:
            quando = resultado.item.data
            if resultado.item.hora:
                quando += f" às {resultado.item.hora}"
            linhas.append(f"Data: {quando}")

        if resultado.id_do_evento:
            linhas.append("Evento criado na agenda.")

        if c.lacuna_secundaria:
            linhas.append(f"Ficou sem: {c.lacuna_secundaria}")

        for erro in resultado.erros:
            linhas.append(f"Falhou: {erro}")

        return "\n".join(linhas)

    def processar_fila(self, limite: int = 10) -> list[ResultadoAutomacao]:
        """Consome a fila durável: usado pelo worker assíncrono."""
        fila = self.orquestradora.fila
        if fila is None:
            raise RuntimeError("Automação sem fila configurada.")

        resultados: list[ResultadoAutomacao] = []
        for _ in range(limite):
            tarefa = fila.reservar()
            if tarefa is None:
                break
            dados = tarefa.payload
            mensagem = Mensagem(
                id=str(dados.get("mensagem_id", tarefa.id)),
                texto=dados.get("texto", ""),
                autor=dados.get("autor", ""),
                canal=dados.get("canal", "telegram"),
                recebida_em=dados.get("recebida_em", ""),
            )
            try:
                resultado = self.executar(mensagem)
            except Exception as erro:  # noqa: BLE001
                fila.falhar(tarefa, str(erro))
                continue
            fila.concluir(tarefa)
            resultados.append(resultado)
        return resultados
