"""Clientes das APIs, exercitados com uma sessão HTTP falsa.

Nenhum teste faz requisição real nem usa credencial verdadeira.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
import requests

from sop.config import Config, ConfiguracaoAusente
from sop.integracoes.google_calendar import (
    ClienteGoogleCalendar,
    ConflitoDeAgenda,
    ErroCredencialGoogle,
    ErroGoogleCalendar,
    ErroIndisponivelGoogle,
    ErroLimiteGoogle,
)
from sop.integracoes.notion import ClienteNotion
from sop.integracoes.telegram import ClienteTelegram
from sop.regras import EventoAgenda, ItemEstoque, MotorDeRegras, Regra
from sop.ritual import CHECKLIST_ABERTURA, Ritual


class RespostaFalsa:
    def __init__(
        self, corpo: dict, status: int = 200, headers: dict | None = None
    ) -> None:
        self._corpo = corpo
        self.status_code = status
        self.text = json.dumps(corpo)
        self.content = self.text.encode()
        self.headers = headers or {}

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
    assert props["Agente"]["select"]["name"] == "beija-flor"
    assert props["Categoria"]["select"]["name"] == "compromisso"
    assert props["Data"]["date"]["start"] == "2026-03-12T14:00:00-03:00"
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


def test_notion_cria_um_registro_datado_do_ritual_sem_duplicar(config_falsa):
    config = Config(
        notion_token=config_falsa.notion_token,
        notion_database_id=config_falsa.notion_database_id,
        notion_rituais_database_id="rituais-db",
    )
    motor = MotorDeRegras(
        [
            Regra(
                nome="Preparar consulta",
                se="Quando houver consulta",
                entao="Separar documentos",
                origem="Agenda",
                palavras_chave=("consulta",),
            ),
            Regra(
                nome="Repor essencial",
                se="Quando um essencial estiver acabando",
                entao="Comprar o essencial",
                origem="Estoque",
                palavras_chave=("acabando",),
            ),
        ]
    )
    pacote = Ritual(motor).pacote(
        date(2026, 3, 8),
        eventos_passados=[EventoAgenda("Aula", "2026-03-03")],
        eventos_futuros=[EventoAgenda("Consulta", "2026-03-12")],
        estoque=[ItemEstoque("Arroz", "acabando")],
    )
    sessao = SessaoFalsa(
        RespostaFalsa({"results": [], "has_more": False}),
        RespostaFalsa({"id": "ritual-2026-03-08"}),
    )

    pagina_id, criada = ClienteNotion(config, sessao=sessao).criar_registro_ritual(
        pacote, ["tarefa-1"]
    )

    assert (pagina_id, criada) == ("ritual-2026-03-08", True)
    corpo = sessao.chamadas[1]["json"]
    assert corpo["properties"]["Domingo"]["date"]["start"] == "2026-03-08"
    assert corpo["properties"]["Status"]["select"]["name"] == "Aberto"
    assert corpo["properties"]["Nome"]["title"][0]["text"]["content"] == (
        "Ritual de domingo, 08/03/2026"
    )
    assert corpo["properties"]["Semana fechada"]["date"] == {
        "start": "2026-03-02", "end": "2026-03-08"
    }
    assert corpo["properties"]["Semana aberta"]["date"] == {
        "start": "2026-03-09", "end": "2026-03-15"
    }
    assert corpo["properties"]["Prioridades concluídas"]["relation"] == [
        {"id": "tarefa-1"}
    ]
    assert all(
        "icon" not in bloco.get("callout", {}) for bloco in corpo["children"]
    )
    textos = [
        bloco[bloco["type"]]["rich_text"][0]["text"]["content"]
        for bloco in corpo["children"]
    ]
    assert any("2026-03-03, Aula" in texto for texto in textos)
    assert any("2026-03-12, Consulta" in texto for texto in textos)
    assert any("Separar documentos" in texto for texto in textos)
    assert any("Comprar o essencial" in texto for texto in textos)
    assert all(item in textos for item in CHECKLIST_ABERTURA)
    assert {"1. ", "2. ", "3. "} <= set(textos)


def test_notion_nao_duplica_ritual_da_mesma_data(config_falsa):
    config = Config(
        notion_token=config_falsa.notion_token,
        notion_database_id=config_falsa.notion_database_id,
        notion_rituais_database_id="rituais-db",
    )
    pacote = Ritual(MotorDeRegras([])).pacote(
        date(2026, 3, 8), eventos_passados=[], eventos_futuros=[]
    )
    sessao = SessaoFalsa(
        RespostaFalsa({"results": [{"id": "ja-existe"}], "has_more": False})
    )

    assert ClienteNotion(config, sessao=sessao).criar_registro_ritual(pacote) == (
        "ja-existe", False
    )
    assert len(sessao.chamadas) == 1


def test_notion_filtra_tarefas_feitas_pelo_prazo_da_semana(config_falsa):
    config = Config(
        notion_token=config_falsa.notion_token,
        notion_database_id=config_falsa.notion_database_id,
        notion_tarefas_database_id="tarefas-db",
    )
    sessao = SessaoFalsa(
        RespostaFalsa(
            {
                "results": [
                    {"id": "tarefa-1"},
                    {"id": "tarefa-1"},
                ],
                "has_more": False,
            }
        )
    )

    assert ClienteNotion(config, sessao=sessao).prioridades_concluidas_na_semana(
        date(2026, 3, 8)
    ) == ["tarefa-1"]
    filtro = sessao.chamadas[0]["json"]["filter"]["and"]
    assert {item["property"] for item in filtro} == {"Feito", "prazo"}


def test_notion_fecha_rituais_anteriores_sem_apagar(config_falsa):
    config = Config(
        notion_token=config_falsa.notion_token,
        notion_database_id=config_falsa.notion_database_id,
        notion_rituais_database_id="rituais-db",
    )
    sessao = SessaoFalsa(
        RespostaFalsa(
            {
                "results": [{"id": "ritual-antigo-1"}, {"id": "ritual-antigo-2"}],
                "has_more": False,
            }
        ),
        RespostaFalsa({"id": "ritual-antigo-1"}),
        RespostaFalsa({"id": "ritual-antigo-2"}),
    )

    fechados = ClienteNotion(config, sessao=sessao).fechar_rituais_anteriores(
        date(2026, 3, 8)
    )

    assert fechados == 2
    filtro = sessao.chamadas[0]["json"]["filter"]["and"]
    assert filtro == [
        {"property": "Domingo", "date": {"before": "2026-03-08"}},
        {"property": "Status", "select": {"does_not_equal": "Fechado"}},
    ]
    assert [chamada["metodo"] for chamada in sessao.chamadas] == [
        "POST",
        "PATCH",
        "PATCH",
    ]
    assert all(
        chamada["json"]
        == {"properties": {"Status": {"select": {"name": "Fechado"}}}}
        for chamada in sessao.chamadas[1:]
    )


# -- Google Agenda -----------------------------------------------------------


class AuthFalsa:
    """Autenticação já resolvida: isola o transporte da obtenção do token."""

    descricao = "falsa"

    def __init__(self, valor: str = "token-temporario") -> None:
        self.valor = valor

    def token(self) -> str:
        return self.valor


def _livre() -> RespostaFalsa:
    """Resposta de freeBusy sem nenhuma faixa ocupada."""
    return RespostaFalsa({"calendars": {"primary": {"busy": []}}})


def _agenda(config, *respostas: RespostaFalsa):
    """Cliente com sessão programada, autenticação falsa e sem espera real."""
    sessao = SessaoFalsa(*respostas)
    cliente = ClienteGoogleCalendar(
        config, sessao=sessao, autenticacao=AuthFalsa(), dormir=lambda _s: None
    )
    return cliente, sessao


def test_agenda_monta_evento_com_hora(config_falsa):
    cliente, _ = _agenda(config_falsa)
    corpo = cliente.montar_evento("Reunião", "2026-03-12", "14:00", 90)

    # O deslocamento vai explícito no payload, e sai do banco de fusos.
    assert corpo["start"]["dateTime"] == "2026-03-12T14:00:00-03:00"
    assert corpo["end"]["dateTime"] == "2026-03-12T15:30:00-03:00"
    assert corpo["start"]["timeZone"] == "America/Sao_Paulo"


def test_agenda_atravessa_a_meia_noite_sem_voltar_no_tempo(config_falsa):
    """O fim de um evento das 23h30 é no dia seguinte, não às 00h30 do mesmo dia."""
    cliente, _ = _agenda(config_falsa)
    corpo = cliente.montar_evento("Virada", "2026-03-12", "23:30", 60)

    assert corpo["end"]["dateTime"] == "2026-03-13T00:30:00-03:00"


def test_agenda_sem_hora_vira_dia_inteiro(config_falsa):
    cliente, _ = _agenda(config_falsa)
    corpo = cliente.montar_evento("Prazo", "2026-03-12")

    # Dia inteiro no Google é intervalo meio-aberto: o fim é o dia seguinte.
    assert corpo["start"] == {"date": "2026-03-12"}
    assert corpo["end"] == {"date": "2026-03-13"}
    assert "dateTime" not in corpo["start"]


# -- autenticação ------------------------------------------------------------


def test_agenda_token_ausente_da_instrucao(tmp_path):
    config = Config(google_token_path=str(tmp_path / "nao-existe.json"))
    cliente = ClienteGoogleCalendar(config, sessao=SessaoFalsa())

    with pytest.raises(ErroCredencialGoogle, match="autorizar_google.py"):
        cliente.token()


def test_agenda_token_incompleto_da_instrucao(tmp_path):
    caminho = tmp_path / "token.json"
    caminho.write_text(json.dumps({"refresh_token": "x"}), encoding="utf-8")
    config = Config(google_token_path=str(caminho))
    cliente = ClienteGoogleCalendar(config, sessao=SessaoFalsa())

    with pytest.raises(ErroCredencialGoogle, match="client_id"):
        cliente.token()


def test_agenda_refresh_token_recusado_manda_reautorizar(tmp_path):
    caminho = tmp_path / "token.json"
    caminho.write_text(
        json.dumps({"refresh_token": "r", "client_id": "c", "client_secret": "s"}),
        encoding="utf-8",
    )
    config = Config(google_token_path=str(caminho))
    sessao = SessaoFalsa(RespostaFalsa({"error": "invalid_grant"}, 400))
    cliente = ClienteGoogleCalendar(config, sessao=sessao)

    with pytest.raises(ErroCredencialGoogle, match="reautorizar"):
        cliente.token()


def test_agenda_conta_de_servico_ausente_explica(tmp_path):
    config = Config(google_service_account_path=str(tmp_path / "nao-existe.json"))
    cliente = ClienteGoogleCalendar(config, sessao=SessaoFalsa())

    with pytest.raises(ErroCredencialGoogle, match="GOOGLE_SERVICE_ACCOUNT_PATH"):
        cliente.token()


def test_agenda_conta_de_servico_tem_prioridade(tmp_path):
    """Com as duas rotas configuradas, vence a que não precisa de humano."""
    config = Config(
        google_token_path=str(tmp_path / "token.json"),
        google_service_account_path=str(tmp_path / "conta.json"),
    )
    cliente = ClienteGoogleCalendar(config, sessao=SessaoFalsa())
    assert cliente.auth.descricao == "conta-de-servico"


def test_agenda_qualquer_uma_das_rotas_deixa_a_integracao_pronta(tmp_path):
    assert not Config().pronta("google_calendar")
    assert Config(google_token_path="/tmp/t.json").pronta("google_calendar")
    assert Config(google_service_account_path="/tmp/c.json").pronta("google_calendar")


def test_agenda_sem_nenhuma_rota_cita_as_duas(config_vazia):
    with pytest.raises(ConfiguracaoAusente) as erro:
        ClienteGoogleCalendar(config_vazia)
    assert "GOOGLE_TOKEN_PATH ou GOOGLE_SERVICE_ACCOUNT_PATH" in str(erro.value)


def test_agenda_reutiliza_token_valido(tmp_path):
    caminho = tmp_path / "token.json"
    caminho.write_text(
        json.dumps({"refresh_token": "r", "client_id": "c", "client_secret": "s"}),
        encoding="utf-8",
    )
    config = Config(google_token_path=str(caminho))
    sessao = SessaoFalsa(RespostaFalsa({"access_token": "abc", "expires_in": 3600}))
    cliente = ClienteGoogleCalendar(config, sessao=sessao)

    assert cliente.token() == "abc"
    assert cliente.token() == "abc"  # não renova de novo
    assert len(sessao.chamadas) == 1


# -- criação e conflito ------------------------------------------------------


def test_agenda_checa_conflito_antes_de_criar(config_falsa):
    cliente, sessao = _agenda(
        config_falsa, _livre(), RespostaFalsa({"id": "evento-xyz"})
    )

    assert cliente.criar_evento("Reunião", "2026-03-12", "14:00") == "evento-xyz"

    # Primeiro freeBusy, só então a criação.
    assert sessao.chamadas[0]["url"].endswith("/freeBusy")
    assert sessao.chamadas[0]["json"]["timeMin"] == "2026-03-12T14:00:00-03:00"
    assert sessao.chamadas[1]["url"].endswith("/events")
    assert sessao.chamadas[1]["headers"]["Authorization"] == "Bearer token-temporario"


def test_agenda_recusa_horario_ocupado(config_falsa):
    ocupado = RespostaFalsa(
        {
            "calendars": {
                "primary": {
                    "busy": [
                        {
                            "start": "2026-03-12T14:00:00-03:00",
                            "end": "2026-03-12T15:00:00-03:00",
                        }
                    ]
                }
            }
        }
    )
    cliente, sessao = _agenda(config_falsa, ocupado)

    with pytest.raises(ConflitoDeAgenda) as erro:
        cliente.criar_evento("Reunião", "2026-03-12", "14:00")

    assert "14:00" in str(erro.value)
    # Nada foi criado: a única chamada foi a consulta.
    assert len(sessao.chamadas) == 1


def test_agenda_permite_sobrepor_quando_pedido(config_falsa):
    """Sobrepor é possível, mas só de propósito — nunca por omissão."""
    cliente, sessao = _agenda(config_falsa, RespostaFalsa({"id": "evento-2"}))

    evento = cliente.criar_evento(
        "Reunião", "2026-03-12", "14:00", permitir_conflito=True
    )

    assert evento == "evento-2"
    assert len(sessao.chamadas) == 1  # nem consultou


def test_agenda_dia_inteiro_nao_checa_conflito(config_falsa):
    cliente, sessao = _agenda(config_falsa, RespostaFalsa({"id": "evento-3"}))

    assert cliente.criar_evento("Prazo", "2026-03-12") == "evento-3"
    assert sessao.chamadas[0]["url"].endswith("/events")


# -- tratamento de erro ------------------------------------------------------


def test_agenda_repete_quando_estoura_o_limite(config_falsa):
    """429 é retentável: recua e tenta de novo antes de desistir."""
    cliente, sessao = _agenda(
        config_falsa,
        RespostaFalsa({"error": {"message": "Rate Limit Exceeded"}}, 429, {"Retry-After": "0"}),
        RespostaFalsa({"calendars": {"primary": {"busy": []}}}),
        RespostaFalsa({"id": "evento-ok"}),
    )

    assert cliente.criar_evento("Reunião", "2026-03-12", "14:00") == "evento-ok"
    assert len(sessao.chamadas) == 3  # a primeira falhou e foi repetida


def test_agenda_desiste_do_limite_depois_das_tentativas(config_falsa):
    cliente, sessao = _agenda(
        config_falsa, *[RespostaFalsa({"error": {"message": "Rate Limit"}}, 429)] * 3
    )

    with pytest.raises(ErroLimiteGoogle, match="Limite de requisições"):
        cliente.proximos_dias()
    assert len(sessao.chamadas) == 3


def test_agenda_repete_quando_a_api_esta_fora(config_falsa):
    cliente, sessao = _agenda(
        config_falsa, *[RespostaFalsa({"error": {"message": "Backend Error"}}, 503)] * 3
    )

    with pytest.raises(ErroIndisponivelGoogle, match="indisponível"):
        cliente.proximos_dias()
    assert len(sessao.chamadas) == 3


def test_agenda_nao_repete_credencial_invalida(config_falsa):
    """403 não melhora com insistência: falha na primeira e diz o que fazer."""
    cliente, sessao = _agenda(
        config_falsa,
        RespostaFalsa({"error": {"message": "Insufficient Permission"}}, 403),
    )

    with pytest.raises(ErroCredencialGoogle, match="compartilhada"):
        cliente.proximos_dias()
    assert len(sessao.chamadas) == 1


def test_agenda_timeout_de_rede_vira_erro_de_indisponibilidade(config_falsa):
    class SessaoQueCai:
        def __init__(self) -> None:
            self.chamadas = 0

        def request(self, *a, **k):
            self.chamadas += 1
            raise requests.Timeout("tempo esgotado")

    sessao = SessaoQueCai()
    cliente = ClienteGoogleCalendar(
        config_falsa, sessao=sessao, autenticacao=AuthFalsa(), dormir=lambda _s: None
    )

    with pytest.raises(ErroIndisponivelGoogle, match="inalcançável"):
        cliente.proximos_dias()
    assert sessao.chamadas == 3


def test_agenda_erro_nao_vaza_o_token(config_falsa):
    cliente, _ = _agenda(
        config_falsa, RespostaFalsa({"error": {"message": "Not Found"}}, 404)
    )

    with pytest.raises(ErroGoogleCalendar) as erro:
        cliente.proximos_dias()
    assert "token-temporario" not in str(erro.value)


def test_agenda_toda_chamada_leva_timeout(config_falsa):
    """Nenhuma requisição pode ficar pendurada sem limite."""
    class SessaoQueOlhaTimeout:
        def __init__(self) -> None:
            self.timeouts: list = []

        def request(self, metodo, url, headers=None, json=None, timeout=None, params=None):
            self.timeouts.append(timeout)
            return RespostaFalsa({"items": []})

    sessao = SessaoQueOlhaTimeout()
    cliente = ClienteGoogleCalendar(
        config_falsa, sessao=sessao, autenticacao=AuthFalsa()
    )
    cliente.proximos_dias()

    assert sessao.timeouts and all(t and t > 0 for t in sessao.timeouts)
