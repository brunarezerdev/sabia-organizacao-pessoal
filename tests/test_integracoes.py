"""Clientes das APIs, exercitados com uma sessão HTTP falsa.

Nenhum teste faz requisição real nem usa credencial verdadeira.
"""

from __future__ import annotations

import json

import pytest

from sop.config import Config, ConfiguracaoAusente
from sop.integracoes.google_calendar import ClienteGoogleCalendar
from sop.integracoes.notion import ClienteNotion
from sop.integracoes.telegram import ClienteTelegram


class RespostaFalsa:
    def __init__(self, corpo: dict, status: int = 200) -> None:
        self._corpo = corpo
        self.status_code = status
        self.text = json.dumps(corpo)
        self.content = self.text.encode()

    def json(self) -> dict:
        return self._corpo

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class SessaoFalsa:
    """Devolve respostas na ordem em que foram configuradas."""

    def __init__(self, *respostas: RespostaFalsa) -> None:
        self.respostas = list(respostas)
        self.chamadas: list[dict] = []

    def _proxima(self, **info) -> RespostaFalsa:
        self.chamadas.append(info)
        return self.respostas.pop(0) if self.respostas else RespostaFalsa({})

    def post(self, url, json=None, data=None, timeout=None, headers=None):
        return self._proxima(metodo="POST", url=url, json=json, data=data)

    def request(self, metodo, url, headers=None, json=None, timeout=None, params=None):
        return self._proxima(metodo=metodo, url=url, json=json, params=params, headers=headers)


# -- credenciais ausentes ----------------------------------------------------


@pytest.mark.parametrize(
    "cliente,integracao",
    [
        (ClienteTelegram, "telegram"),
        (ClienteNotion, "notion"),
        (ClienteGoogleCalendar, "google_calendar"),
    ],
)
def test_cliente_sem_credencial_explica(cliente, integracao, config_vazia):
    with pytest.raises(ConfiguracaoAusente) as erro:
        cliente(config_vazia)
    assert integracao in str(erro.value)
    assert ".env" in str(erro.value)


# -- Telegram ----------------------------------------------------------------


def _update(chat_id: str, texto: str, update_id: int = 1) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id * 10,
            "date": 1772000000,
            "chat": {"id": chat_id},
            "from": {"first_name": "Pessoa Exemplo"},
            "text": texto,
        },
    }


def test_telegram_aceita_apenas_o_chat_autorizado(config_falsa):
    cliente = ClienteTelegram(config_falsa, sessao=SessaoFalsa())

    assert cliente.para_mensagem(_update("42", "oi")) is not None
    assert cliente.para_mensagem(_update("99", "oi")) is None  # chat estranho


def test_telegram_converte_update_em_mensagem(config_falsa):
    cliente = ClienteTelegram(config_falsa, sessao=SessaoFalsa())
    mensagem = cliente.para_mensagem(_update("42", "  Comprar café  "))

    assert mensagem.texto == "Comprar café"
    assert mensagem.autor == "Pessoa Exemplo"
    assert mensagem.canal == "telegram"


def test_telegram_ignora_mensagem_sem_texto(config_falsa):
    cliente = ClienteTelegram(config_falsa, sessao=SessaoFalsa())
    update = _update("42", "")
    update["message"]["text"] = ""
    assert cliente.para_mensagem(update) is None


def test_telegram_calcula_o_proximo_offset(config_falsa):
    sessao = SessaoFalsa(
        RespostaFalsa(
            {"ok": True, "result": [_update("42", "a", 5), _update("42", "b", 7)]}
        )
    )
    mensagens, offset = ClienteTelegram(config_falsa, sessao=sessao).mensagens()

    assert len(mensagens) == 2
    assert offset == 8


def test_telegram_propaga_recusa_da_api(config_falsa):
    sessao = SessaoFalsa(RespostaFalsa({"ok": False, "description": "chat not found"}))
    cliente = ClienteTelegram(config_falsa, sessao=sessao)

    with pytest.raises(RuntimeError, match="chat not found"):
        cliente.responder("42", "oi")


def test_token_nao_vaza_no_erro(config_falsa):
    sessao = SessaoFalsa(RespostaFalsa({"ok": False, "description": "falhou"}))
    cliente = ClienteTelegram(config_falsa, sessao=sessao)

    with pytest.raises(RuntimeError) as erro:
        cliente.responder("42", "oi")
    assert config_falsa.telegram_token not in str(erro.value)


# -- Notion ------------------------------------------------------------------


def test_notion_mapeia_item_para_propriedades(config_falsa, item):
    props = ClienteNotion(config_falsa, sessao=SessaoFalsa()).propriedades(item)

    assert props["Titulo"]["title"][0]["text"]["content"] == "Reunião com o time"
    assert props["Agente"]["select"]["name"] == "secretaria"
    assert props["Categoria"]["select"]["name"] == "compromisso"
    assert props["Data"]["date"]["start"] == "2026-03-12T14:00:00"
    assert "duracao_minutos" in props["Detalhes"]["rich_text"][0]["text"]["content"]


def test_notion_data_sem_hora_fica_dia_inteiro(config_falsa, item):
    item.hora = None
    props = ClienteNotion(config_falsa, sessao=SessaoFalsa()).propriedades(item)
    assert props["Data"]["date"]["start"] == "2026-03-12"


def test_notion_item_sem_data_omite_a_propriedade(config_falsa, item):
    item.data = None
    props = ClienteNotion(config_falsa, sessao=SessaoFalsa()).propriedades(item)
    assert "Data" not in props


def test_notion_cria_item_e_devolve_id(config_falsa, item):
    sessao = SessaoFalsa(RespostaFalsa({"id": "pagina-abc"}))
    assert ClienteNotion(config_falsa, sessao=sessao).criar_item(item) == "pagina-abc"

    chamada = sessao.chamadas[0]
    assert chamada["url"].endswith("/pages")
    assert chamada["json"]["parent"]["database_id"] == "database-de-teste"


def test_notion_erro_traz_a_mensagem_da_api(config_falsa, item):
    sessao = SessaoFalsa(RespostaFalsa({"message": "Could not find database"}, 404))
    with pytest.raises(RuntimeError, match="Could not find database"):
        ClienteNotion(config_falsa, sessao=sessao).criar_item(item)


# -- Google Agenda -----------------------------------------------------------


def test_agenda_monta_evento_com_hora(config_falsa):
    cliente = ClienteGoogleCalendar(config_falsa, sessao=SessaoFalsa())
    corpo = cliente.montar_evento("Reunião", "2026-03-12", "14:00", 90)

    assert corpo["start"]["dateTime"] == "2026-03-12T14:00:00"
    assert corpo["end"]["dateTime"] == "2026-03-12T15:30:00"
    assert corpo["start"]["timeZone"] == "America/Sao_Paulo"


def test_agenda_sem_hora_vira_dia_inteiro(config_falsa):
    cliente = ClienteGoogleCalendar(config_falsa, sessao=SessaoFalsa())
    corpo = cliente.montar_evento("Prazo", "2026-03-12")

    assert corpo["start"] == {"date": "2026-03-12"}
    assert "dateTime" not in corpo["start"]


def test_agenda_token_ausente_da_instrucao(config_falsa, tmp_path):
    config = Config(google_token_path=str(tmp_path / "nao-existe.json"))
    cliente = ClienteGoogleCalendar(config, sessao=SessaoFalsa())

    with pytest.raises(RuntimeError, match="autorizar_google.py"):
        cliente.token()


def test_agenda_token_incompleto_da_instrucao(config_falsa, tmp_path):
    caminho = tmp_path / "token.json"
    caminho.write_text(json.dumps({"refresh_token": "x"}), encoding="utf-8")
    config = Config(google_token_path=str(caminho))
    cliente = ClienteGoogleCalendar(config, sessao=SessaoFalsa())

    with pytest.raises(RuntimeError, match="client_id"):
        cliente.token()


def test_agenda_renova_token_e_cria_evento(config_falsa, tmp_path):
    caminho = tmp_path / "token.json"
    caminho.write_text(
        json.dumps(
            {"refresh_token": "r-falso", "client_id": "c-falso", "client_secret": "s-falso"}
        ),
        encoding="utf-8",
    )
    config = Config(google_token_path=str(caminho), google_calendar_id="primary")
    sessao = SessaoFalsa(
        RespostaFalsa({"access_token": "token-temporario", "expires_in": 3600}),
        RespostaFalsa({"id": "evento-xyz"}),
    )
    cliente = ClienteGoogleCalendar(config, sessao=sessao)

    assert cliente.criar_evento("Reunião", "2026-03-12", "14:00") == "evento-xyz"
    assert sessao.chamadas[0]["data"]["grant_type"] == "refresh_token"
    assert sessao.chamadas[1]["headers"]["Authorization"] == "Bearer token-temporario"


def test_agenda_reutiliza_token_valido(config_falsa, tmp_path):
    caminho = tmp_path / "token.json"
    caminho.write_text(
        json.dumps(
            {"refresh_token": "r", "client_id": "c", "client_secret": "s"}
        ),
        encoding="utf-8",
    )
    config = Config(google_token_path=str(caminho))
    sessao = SessaoFalsa(RespostaFalsa({"access_token": "abc", "expires_in": 3600}))
    cliente = ClienteGoogleCalendar(config, sessao=sessao)

    assert cliente.token() == "abc"
    assert cliente.token() == "abc"  # não renova de novo
    assert len(sessao.chamadas) == 1
