#!/usr/bin/env python3
"""Prova a cadeia inteira: Telegram -> classificação -> Google Agenda -> Notion.

Roda contra as APIs de verdade, com as credenciais de verdade, e deixa a
evidência em arquivo. O evento criado é de teste e é APAGADO no fim: o que
sobra é o registro no Notion e o relatório do que aconteceu em cada etapa.

    python scripts/provar_cadeia.py
    python scripts/provar_cadeia.py --texto "..." --agenda <id> --manter

Etapas, na ordem em que uma mensagem real percorre o sistema:

    1. Telegram   confere a credencial do bot (getMe) e passa um update pelo
                  mesmo `para_mensagem` que a captura usa, incluindo a recusa
                  de um chat não autorizado.
    2. IA         classifica com o backend configurado (OpenClaw, rota Codex).
    3. Agenda     checa conflito, cria o evento e lê de volta do Google.
    4. Notion     grava o item e lê a página de volta.
    5. Limpeza    apaga o evento de teste e confirma que sumiu.

Nenhuma mensagem é enviada a ninguém no Telegram: a etapa 1 só valida a
credencial e o caminho de captura. Mandar mensagem para uma pessoa é decisão
dela, não de um script de verificação.

O relatório é higienizado antes de ir para o disco — id de agenda, chat e
tokens são mascarados, porque `docs/` é versionado.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from sop.agentes import carregar_registro  # noqa: E402
from sop.config import Config  # noqa: E402
from sop.integracoes.google_calendar import (  # noqa: E402
    ClienteGoogleCalendar,
    ConflitoDeAgenda,
    ErroGoogleCalendar,
)
from sop.integracoes.ia import criar_adaptador  # noqa: E402
from sop.integracoes.notion import ClienteNotion  # noqa: E402
from sop.integracoes.telegram import ClienteTelegram  # noqa: E402
from sop.modelos import Item, Mensagem  # noqa: E402
from sop.orquestradora import Orquestradora  # noqa: E402

TEXTO_PADRAO = (
    "Marca uma reunião de TESTE DA INTEGRAÇÃO no dia 30 de agosto "
    "às 6 da manhã, meia hora"
)
DIR_EVIDENCIAS = RAIZ / "docs" / "evidencias"

log = logging.getLogger("provar_cadeia")


# ---------------------------------------------------------------------------
# Relatório
# ---------------------------------------------------------------------------


class Relatorio:
    """Acumula as etapas e higieniza antes de escrever."""

    def __init__(self, segredos: list[str]) -> None:
        self.etapas: list[dict] = []
        self.segredos = [s for s in segredos if s and len(s) > 6]

    def mascarar(self, texto: str) -> str:
        for segredo in self.segredos:
            texto = texto.replace(segredo, "<oculto>")
        # Endereços e caminhos de máquina não entram num repositório público.
        texto = re.sub(
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "<agenda>", texto
        )
        texto = re.sub(r"/(opt|home|Users|srv)/[A-Za-z0-9_./-]+", "<caminho>", texto)
        texto = re.sub(r"\b\d{9,}\b", "<id>", texto)
        return texto

    def passo(self, nome: str, ok: bool, **detalhes) -> None:
        self.etapas.append({"etapa": nome, "ok": ok, **detalhes})
        marca = "ok " if ok else "FALHOU"
        print(f"  [{marca}] {nome}")
        for chave, valor in detalhes.items():
            print(f"           {chave}: {valor}")

    @property
    def sucesso(self) -> bool:
        return all(e["ok"] for e in self.etapas)

    def escrever(self, momento: datetime) -> Path:
        DIR_EVIDENCIAS.mkdir(parents=True, exist_ok=True)
        destino = DIR_EVIDENCIAS / f"cadeia-{momento:%Y%m%d-%H%M%S}.md"

        linhas = [
            "# Evidência da cadeia ponta a ponta",
            "",
            f"Execução em {momento:%d/%m/%Y %H:%M:%S %z}.",
            "",
            "Telegram (API 1) -> classificação -> Google Agenda (API 2) -> Notion (banco).",
            "Gerado por `scripts/provar_cadeia.py` contra as APIs de produção.",
            "Identificadores de agenda, chat e credenciais foram mascarados.",
            "",
            f"**Resultado: {'cadeia completa' if self.sucesso else 'FALHOU'}**",
            "",
            "| # | Etapa | Resultado | Detalhes |",
            "| - | ----- | --------- | -------- |",
        ]
        for i, etapa in enumerate(self.etapas, 1):
            detalhes = "; ".join(
                f"{k}={v}" for k, v in etapa.items() if k not in ("etapa", "ok")
            )
            linhas.append(
                f"| {i} | {etapa['etapa']} | {'ok' if etapa['ok'] else 'FALHOU'} "
                f"| {detalhes} |"
            )

        linhas += ["", "## Registro bruto", "", "```json", json.dumps(self.etapas, ensure_ascii=False, indent=2), "```", ""]
        destino.write_text(self.mascarar("\n".join(linhas)), encoding="utf-8")
        return destino


# ---------------------------------------------------------------------------
# Etapas
# ---------------------------------------------------------------------------


def update_telegram(chat_id: str, texto: str) -> dict:
    """Um update no formato exato que a Bot API entrega no getUpdates."""
    return {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "date": int(datetime.now().timestamp()),
            "chat": {"id": chat_id, "type": "private"},
            "from": {"first_name": "Bruna", "is_bot": False},
            "text": texto,
        },
    }


def etapa_telegram(config: Config, rel: Relatorio, texto: str) -> Mensagem:
    cliente = ClienteTelegram(config)

    # getMe prova que o token é válido sem mandar mensagem para ninguém.
    identidade = cliente._chamar("getMe")
    rel.passo(
        "Telegram: credencial do bot aceita",
        bool(identidade.get("username")),
        bot="@" + str(identidade.get("username", "?")),
    )

    autorizado = config.telegram_chat_autorizado
    mensagem = cliente.para_mensagem(update_telegram(autorizado, texto))
    rel.passo(
        "Telegram: mensagem do chat autorizado é aceita",
        mensagem is not None,
        texto=mensagem.texto if mensagem else "",
    )
    if mensagem is None:
        raise SystemExit("A captura recusou a mensagem do chat autorizado.")

    intruso = cliente.para_mensagem(update_telegram("999999", texto))
    rel.passo("Telegram: chat não autorizado é recusado", intruso is None)
    return mensagem


def etapa_classificacao(config: Config, rel: Relatorio, mensagem: Mensagem):
    orquestradora = Orquestradora(criar_adaptador(config), carregar_registro())
    classificacao, item = orquestradora.processar(mensagem)

    rel.passo(
        "IA: mensagem em português vira classificação estruturada",
        bool(classificacao.data),
        origem=classificacao.origem,
        agente=classificacao.agente,
        categoria=classificacao.categoria,
        titulo=classificacao.titulo,
        data=classificacao.data,
        hora=classificacao.hora,
        duracao=classificacao.duracao_minutos,
        confianca=classificacao.confianca,
    )
    if classificacao.origem != "openclaw":
        # Não é motivo para parar, mas precisa ficar registrado: uma queda para
        # o heurístico faria a evidência parecer melhor do que foi.
        print("           AVISO: caiu no classificador heurístico, não no OpenClaw")

    rel.passo(
        "Orquestradora: item pronto para gravação",
        orquestradora.deve_criar_evento(classificacao),
        vira_evento=orquestradora.deve_criar_evento(classificacao),
    )
    return classificacao, item


def etapa_agenda(
    cliente: ClienteGoogleCalendar, rel: Relatorio, classificacao, item: Item
) -> str:
    duracao = classificacao.duracao_minutos or 60
    inicio, fim = cliente.janela(item.data, item.hora, duracao)

    ocupados = cliente.conflitos(item.data, item.hora, duracao)
    rel.passo(
        "Agenda: conflito checado ANTES de criar",
        True,
        janela=f"{inicio} até {fim}",
        conflitos=len(ocupados),
    )
    if ocupados:
        raise SystemExit(
            f"O horário de teste está ocupado ({ocupados}). "
            "Escolha outro com --texto, para não sobrepor compromisso real."
        )

    evento_id = cliente.criar_evento(
        titulo=item.titulo,
        data=item.data,
        hora=item.hora,
        duracao_minutos=duracao,
        descricao="Evento de teste da integração. Apagado automaticamente.",
    )
    rel.passo("Agenda: evento criado", bool(evento_id), evento_id=evento_id)

    try:
        eventos = cliente.listar_eventos(inicio, fim)
        achado = next((e for e in eventos if e.get("id") == evento_id), None)
        rel.passo(
            "Agenda: evento confirmado por leitura de volta",
            achado is not None,
            inicio_no_google=(achado or {}).get("start", {}).get("dateTime", ""),
            fuso_confere=(achado or {})
            .get("start", {})
            .get("dateTime", "")
            .endswith("-03:00"),
        )
    except BaseException:
        # Se a leitura de confirmação cair depois do POST, o chamador ainda não
        # recebeu o id e não teria como limpar. Remover aqui evita deixar lixo
        # na agenda até mesmo quando a prova é interrompida com Ctrl+C.
        cliente.apagar_evento(evento_id)
        raise
    return evento_id


def etapa_notion(config: Config, rel: Relatorio, item: Item, evento_id: str) -> str:
    cliente = ClienteNotion(config)
    item.extras = {**item.extras, "evento_google": evento_id, "origem": "teste de integração"}

    pagina_id = cliente.criar_item(item)
    rel.passo("Notion: registro gravado", bool(pagina_id), pagina=pagina_id)

    pagina = cliente._chamar("GET", f"/pages/{pagina_id}")
    titulo = "".join(
        t.get("plain_text", "")
        for t in pagina.get("properties", {}).get("Titulo", {}).get("title", [])
    )
    rel.passo(
        "Notion: registro confirmado por leitura de volta",
        titulo == item.titulo,
        titulo=titulo,
        url=pagina.get("url", ""),
    )
    return pagina_id


def etapa_limpeza(
    cliente: ClienteGoogleCalendar, rel: Relatorio, evento_id: str, item: Item, duracao: int
) -> None:
    cliente.apagar_evento(evento_id)
    inicio, fim = cliente.janela(item.data, item.hora, duracao)
    restantes = [e.get("id") for e in cliente.listar_eventos(inicio, fim)]
    rel.passo(
        "Limpeza: evento de teste apagado da agenda",
        evento_id not in restantes,
        evento_id=evento_id,
    )


# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--texto", default=TEXTO_PADRAO, help="frase em português")
    parser.add_argument("--agenda", default="", help="id da agenda (padrão: GOOGLE_CALENDAR_ID)")
    parser.add_argument("--manter", action="store_true", help="não apagar o evento de teste")
    parser.add_argument("--verboso", action="store_true", help="mostra o log das chamadas")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verboso else logging.WARNING,
        format="%(levelname)s %(name)s %(message)s",
    )

    config = Config.do_ambiente()
    if args.agenda:
        import dataclasses

        config = dataclasses.replace(config, google_calendar_id=args.agenda)

    for integracao in ("telegram", "notion", "google_calendar"):
        if not config.pronta(integracao):
            raise SystemExit(
                f"'{integracao}' não configurada: falta "
                f"{', '.join(config.faltando(integracao))}. Rode `python -m sop diagnostico`."
            )

    rel = Relatorio(
        segredos=[config.telegram_token, config.notion_token, config.google_calendar_id]
    )
    momento = datetime.now().astimezone()

    print(f"Cadeia ponta a ponta — {momento:%d/%m/%Y %H:%M:%S}")
    print(f'Frase: "{args.texto}"\n')

    mensagem = etapa_telegram(config, rel, args.texto)
    classificacao, item = etapa_classificacao(config, rel, mensagem)

    if not item.data or not item.hora:
        raise SystemExit(
            "A classificação não trouxe data e hora — sem isso não há evento a criar. "
            "Passe uma frase com data e hora explícitas em --texto."
        )

    agenda = ClienteGoogleCalendar(config)
    duracao = classificacao.duracao_minutos or 60
    try:
        evento_id = etapa_agenda(agenda, rel, classificacao, item)
    except ConflitoDeAgenda as erro:
        raise SystemExit(f"Horário de teste ocupado: {erro}") from erro

    try:
        etapa_notion(config, rel, item, evento_id)
    finally:
        # A limpeza acontece mesmo se o Notion falhar: um evento de teste
        # esquecido na agenda de alguém é lixo que aparece no celular dela.
        if args.manter:
            print(f"  [--manter] evento {evento_id} deixado na agenda de propósito")
        else:
            etapa_limpeza(agenda, rel, evento_id, item, duracao)

    destino = rel.escrever(momento)
    print(f"\nEvidência: {destino.relative_to(RAIZ)}")
    print("Cadeia completa." if rel.sucesso else "Alguma etapa falhou — veja acima.")
    return 0 if rel.sucesso else 1


if __name__ == "__main__":
    raise SystemExit(main())
