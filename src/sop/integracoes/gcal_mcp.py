"""Servidor MCP da Google Agenda — como a Sábia enxerga a API 2.

Por que MCP e não uma skill de shell: o Notion já entra por MCP, então a agenda
pelo mesmo caminho dá ao agente uma única forma de falar com API externa, e
deixa timeout, retry, checagem de conflito e log dentro do
`ClienteGoogleCalendar` em vez de espalhados em linhas de comando que o modelo
monta na hora.

O servidor não conhece nenhum segredo. Ele recebe do ambiente:

    GOOGLE_SERVICE_ACCOUNT_PATH  caminho da chave (o arquivo fica em 0600, fora do repo)
    SOP_AGENDAS                  rótulos das agendas: "bruna=<id>,wagner=<id>"
    GOOGLE_CALENDAR_ID           agenda padrão quando nenhum rótulo é passado

Os rótulos existem para que nem o repositório nem o prompt do agente precisem
carregar endereço de e-mail de ninguém: a Sábia pede "a agenda da bruna" e o
mapeamento mora na configuração da máquina.

Registro no OpenClaw:

    openclaw mcp add agenda --command scripts/openclaw/gcal_mcp.sh
"""

from __future__ import annotations

import dataclasses
import logging
import os
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer

from ..config import Config
from ..modelos import Item
from .google_calendar import (
    ClienteGoogleCalendar,
    ConflitoDeAgenda,
    ErroGoogleCalendar,
)
from .notion import ClienteNotion

# O transporte é stdio: qualquer print em stdout corromperia o JSON-RPC. Todo
# log vai para stderr, que o OpenClaw coleta.
logging.basicConfig(
    stream=sys.stderr,
    level=os.environ.get("SOP_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("sop.gcal_mcp")

servidor = MCPServer(
    name="agenda",
    version="1.0.0",
    instructions=(
        "Google Agenda das pessoas da operação. Consulte antes de criar. "
        "Todo horário é interpretado no fuso configurado (-03:00). "
        "Nunca apague nem altere compromisso que você não criou nesta conversa."
    ),
)


# ---------------------------------------------------------------------------
# Resolução de agendas
# ---------------------------------------------------------------------------


def agendas_configuradas() -> dict[str, str]:
    """Mapa rótulo -> id de agenda, lido de `SOP_AGENDAS`."""
    mapa: dict[str, str] = {}
    for parte in os.environ.get("SOP_AGENDAS", "").split(","):
        parte = parte.strip()
        if not parte or "=" not in parte:
            continue
        rotulo, identificador = parte.split("=", 1)
        rotulo, identificador = rotulo.strip().lower(), identificador.strip()
        if rotulo and identificador:
            mapa[rotulo] = identificador
    return mapa


def resolver(agenda: str) -> str:
    """Traduz um rótulo em id de agenda, com erro que diz o que existe."""
    mapa = agendas_configuradas()
    escolha = (agenda or "").strip()

    if not escolha:
        padrao = os.environ.get("GOOGLE_CALENDAR_ID", "").strip()
        if padrao and padrao != "primary":
            return padrao
        if len(mapa) == 1:
            return next(iter(mapa.values()))
        raise ValueError(
            "Diga de qual agenda se trata. Disponíveis: "
            + (", ".join(sorted(mapa)) or "nenhuma configurada em SOP_AGENDAS")
        )

    if escolha.lower() in mapa:
        return mapa[escolha.lower()]
    if "@" in escolha or escolha == "primary":
        return escolha  # id explícito
    raise ValueError(
        f"Agenda '{escolha}' não configurada. Disponíveis: "
        + (", ".join(sorted(mapa)) or "nenhuma")
    )


_clientes: dict[str, ClienteGoogleCalendar] = {}


def cliente_de(agenda: str) -> ClienteGoogleCalendar:
    """Cliente por agenda, reaproveitado entre chamadas.

    Reaproveitar importa: o access token vive no cliente, então uma segunda
    pergunta na mesma conversa não paga outra ida ao Google para renovar.
    """
    identificador = resolver(agenda)
    if identificador not in _clientes:
        config = dataclasses.replace(
            Config.do_ambiente(), google_calendar_id=identificador
        )
        _clientes[identificador] = ClienteGoogleCalendar(config)
    return _clientes[identificador]


def _erro(mensagem: str) -> dict[str, Any]:
    """Falha vira resposta legível, não traceback.

    O agente precisa conseguir contar para a pessoa o que deu errado; um stack
    trace de Python no meio de uma conversa no Telegram não serve para nada.
    """
    return {"ok": False, "erro": mensagem}


def _resumir(evento: dict[str, Any]) -> dict[str, Any]:
    inicio = evento.get("start", {})
    fim = evento.get("end", {})
    return {
        "id": evento.get("id", ""),
        "titulo": evento.get("summary", "(sem título)"),
        "inicio": inicio.get("dateTime") or inicio.get("date", ""),
        "fim": fim.get("dateTime") or fim.get("date", ""),
        "link": evento.get("htmlLink", ""),
    }


def registrar_no_notion(
    *,
    titulo: str,
    data: str,
    hora: str,
    duracao_minutos: int,
    descricao: str,
    evento_id: str,
) -> str:
    """Grava o espelho do compromisso no banco no-code.

    A criação fica dentro da mesma tool para a cadeia Telegram -> Agenda ->
    Notion não depender de o modelo lembrar uma segunda chamada. Se esta etapa
    falhar, `agenda_criar` desfaz somente o evento que acabou de criar.
    """
    item = Item(
        titulo=titulo,
        agente="secretaria",
        categoria="compromisso",
        data=data,
        hora=hora or None,
        observacao=descricao,
        extras={
            "duracao_minutos": duracao_minutos,
            "evento_google": evento_id,
            "origem": "Sábia via Telegram",
        },
    )
    return ClienteNotion(Config.do_ambiente()).criar_item(item)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@servidor.tool(
    title="Consultar agenda",
    description=(
        "Lista os compromissos dos próximos dias. Use antes de sugerir horário "
        "e antes de responder qualquer pergunta sobre a agenda de alguém."
    ),
)
def agenda_consultar(agenda: str = "", dias: int = 7) -> dict[str, Any]:
    """Compromissos dos próximos `dias` na agenda indicada."""
    try:
        cliente = cliente_de(agenda)
        eventos = cliente.proximos_dias(dias=max(1, min(dias, 60)))
    except (ErroGoogleCalendar, ValueError) as erro:
        log.warning("agenda_consultar falhou: %s", erro)
        return _erro(str(erro))
    return {
        "ok": True,
        "agenda": cliente.config.google_calendar_id,
        "dias": dias,
        "total": len(eventos),
        "eventos": [_resumir(e) for e in eventos],
    }


@servidor.tool(
    title="Checar conflito de horário",
    description=(
        "Diz se um horário já está ocupado, sem criar nada. "
        "Use quando a pessoa perguntar se pode marcar algo."
    ),
)
def agenda_conflitos(
    data: str, hora: str, duracao_minutos: int = 60, agenda: str = ""
) -> dict[str, Any]:
    """`data` no formato AAAA-MM-DD e `hora` no formato HH:MM."""
    try:
        cliente = cliente_de(agenda)
        ocupados = cliente.conflitos(data, hora, duracao_minutos)
        inicio, fim = cliente.janela(data, hora, duracao_minutos)
    except (ErroGoogleCalendar, ValueError) as erro:
        log.warning("agenda_conflitos falhou: %s", erro)
        return _erro(str(erro))
    return {
        "ok": True,
        "agenda": cliente.config.google_calendar_id,
        "inicio": inicio,
        "fim": fim,
        "livre": not ocupados,
        "ocupados": ocupados,
    }


@servidor.tool(
    title="Criar compromisso",
    description=(
        "Cria um compromisso na agenda e o registro correspondente no Notion. "
        "Consulta conflito antes e recusa se o horário estiver ocupado. "
        "Sem hora, cria evento de dia inteiro. "
        "Confirme data, hora e duração com a pessoa antes de chamar: não adivinhe."
    ),
)
def agenda_criar(
    titulo: str,
    data: str,
    hora: str = "",
    duracao_minutos: int = 60,
    descricao: str = "",
    agenda: str = "",
    permitir_conflito: bool = False,
) -> dict[str, Any]:
    """`data` AAAA-MM-DD, `hora` HH:MM (vazio = dia inteiro)."""
    if not titulo.strip():
        return _erro("Um compromisso precisa de título.")
    try:
        cliente = cliente_de(agenda)
        evento_id = cliente.criar_evento(
            titulo=titulo,
            data=data,
            hora=hora or None,
            duracao_minutos=duracao_minutos,
            descricao=descricao,
            permitir_conflito=permitir_conflito,
        )
    except ConflitoDeAgenda as erro:
        # Não é falha do sistema: é uma decisão que volta para a pessoa.
        return {
            "ok": False,
            "conflito": True,
            "ocupados": erro.ocupados,
            "erro": (
                f"{data} {hora} já está ocupado. Pergunte à pessoa se quer outro "
                "horário ou se quer sobrepor mesmo assim."
            ),
        }
    except (ErroGoogleCalendar, ValueError) as erro:
        log.warning("agenda_criar falhou: %s", erro)
        return _erro(str(erro))

    try:
        pagina_notion = registrar_no_notion(
            titulo=titulo,
            data=data,
            hora=hora,
            duracao_minutos=duracao_minutos,
            descricao=descricao,
            evento_id=evento_id,
        )
    except Exception as erro:  # noqa: BLE001 — clientes levantam erros próprios
        # Atomicidade segura: sem o registro, desfazemos exclusivamente o
        # evento cujo id acabou de voltar do POST. Nunca buscamos por título.
        try:
            cliente.apagar_evento(evento_id)
        except Exception as erro_limpeza:  # noqa: BLE001
            log.error(
                "Notion falhou e não foi possível desfazer o evento %s: %s",
                evento_id,
                erro_limpeza,
            )
            return _erro(
                "O registro no Notion falhou e o evento criado não pôde ser "
                f"desfeito. Evento: {evento_id}. Erro: {erro}"
            )
        log.warning("Notion falhou; evento %s desfeito: %s", evento_id, erro)
        return _erro(
            "O Notion não aceitou o registro; o evento de teste foi desfeito "
            f"com segurança. Erro: {erro}"
        )

    inicio = cliente.janela(data, hora, duracao_minutos)[0] if hora else data
    return {
        "ok": True,
        "id": evento_id,
        "agenda": cliente.config.google_calendar_id,
        "titulo": titulo,
        "inicio": inicio,
        "pagina_notion": pagina_notion,
    }


@servidor.tool(
    title="Apagar compromisso",
    description=(
        "Apaga um compromisso pelo id. Só use com um id que você acabou de "
        "criar ou que a pessoa confirmou explicitamente."
    ),
)
def agenda_apagar(evento_id: str, agenda: str = "") -> dict[str, Any]:
    if not evento_id.strip():
        return _erro("Informe o id do evento a apagar.")
    try:
        cliente = cliente_de(agenda)
        cliente.apagar_evento(evento_id)
    except (ErroGoogleCalendar, ValueError) as erro:
        log.warning("agenda_apagar falhou: %s", erro)
        return _erro(str(erro))
    return {"ok": True, "apagado": evento_id, "agenda": cliente.config.google_calendar_id}


def main() -> None:
    rotulos = ", ".join(sorted(agendas_configuradas())) or "(nenhum)"
    log.info("servidor MCP da agenda no ar; rótulos configurados: %s", rotulos)
    servidor.run(transport="stdio")


if __name__ == "__main__":
    main()
