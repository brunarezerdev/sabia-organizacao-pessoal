"""Fixtures compartilhadas. Nenhum teste toca em rede ou em credencial real."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from sop.agentes import carregar_registro  # noqa: E402
from sop.config import Config  # noqa: E402
from sop.modelos import Item, Mensagem  # noqa: E402

# Data fixa para que os testes de data relativa não dependam de "hoje".
# 2026-03-10 é uma terça-feira.
HOJE = date(2026, 3, 10)


@pytest.fixture
def registro():
    return carregar_registro(RAIZ / "agentes")


@pytest.fixture
def config_vazia():
    """Configuração sem nenhuma credencial — o estado de quem acabou de clonar."""
    return Config()


@pytest.fixture
def config_falsa():
    """Credenciais fictícias, só para exercitar caminhos que exigem config."""
    return Config(
        telegram_token="000:token-de-teste",
        telegram_chat_autorizado="42",
        notion_token="token-de-teste",
        notion_database_id="database-de-teste",
        google_token_path="/tmp/token-de-teste.json",
        anthropic_api_key="chave-de-teste",
    )


@pytest.fixture
def mensagem():
    return Mensagem(id="m1", texto="Reunião com o time na quinta às 14h", canal="teste")


@pytest.fixture
def item():
    return Item(
        titulo="Reunião com o time",
        agente="secretaria",
        categoria="compromisso",
        data="2026-03-12",
        hora="14:00",
        observacao="",
        extras={"duracao_minutos": 60},
        origem_mensagem_id="m1",
    )


class BancoFalso:
    """Substituto do Notion. Guarda os itens em memória."""

    def __init__(self, falhar: bool = False) -> None:
        self.itens: list[Item] = []
        self.falhar = falhar

    def criar_item(self, item: Item) -> str:
        if self.falhar:
            raise RuntimeError("banco indisponível")
        self.itens.append(item)
        return f"pagina-{len(self.itens)}"


class AgendaFalsa:
    """Substituto do Google Agenda. Guarda os eventos em memória."""

    def __init__(self, falhar: bool = False) -> None:
        self.eventos: list[dict] = []
        self.falhar = falhar

    def criar_evento(self, titulo, data, hora=None, duracao_minutos=60, descricao=""):
        if self.falhar:
            raise RuntimeError("agenda indisponível")
        self.eventos.append(
            {
                "titulo": titulo,
                "data": data,
                "hora": hora,
                "duracao_minutos": duracao_minutos,
                "descricao": descricao,
            }
        )
        return f"evento-{len(self.eventos)}"


@pytest.fixture
def banco():
    return BancoFalso()


@pytest.fixture
def agenda():
    return AgendaFalsa()
