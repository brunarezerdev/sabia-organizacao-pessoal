"""Servidor MCP da agenda: resolução de agendas e tradução de falha.

O que se testa aqui é a camada que fica ENTRE o agente e o cliente HTTP: qual
agenda um rótulo resolve, e o que o agente recebe quando algo dá errado. As
chamadas de rede em si são cobertas em `test_integracoes.py`.

Nenhum teste toca em rede nem em credencial real.
"""

from __future__ import annotations

import pytest

mcp_disponivel = pytest.importorskip(
    "mcp", reason="servidor MCP é opcional: `pip install mcp`"
)

from sop.integracoes import gcal_mcp  # noqa: E402
from sop.integracoes.google_calendar import (  # noqa: E402
    ConflitoDeAgenda,
    ErroCredencialGoogle,
    ErroIndisponivelGoogle,
)


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch):
    """Cada teste começa sem agenda configurada e sem cliente em cache."""
    monkeypatch.delenv("SOP_AGENDAS", raising=False)
    monkeypatch.delenv("GOOGLE_CALENDAR_ID", raising=False)
    monkeypatch.setattr(
        gcal_mcp, "registrar_no_notion", lambda **_kwargs: "pagina-nova"
    )
    gcal_mcp._clientes.clear()
    yield
    gcal_mcp._clientes.clear()


# -- resolução de agendas ----------------------------------------------------


def test_le_os_rotulos_do_ambiente(monkeypatch):
    monkeypatch.setenv("SOP_AGENDAS", "bruna=a@exemplo.test, wagner=b@exemplo.test")
    assert gcal_mcp.agendas_configuradas() == {
        "bruna": "a@exemplo.test",
        "wagner": "b@exemplo.test",
    }


def test_ignora_entrada_malformada(monkeypatch):
    monkeypatch.setenv("SOP_AGENDAS", "bruna=a@exemplo.test,lixo,=,x=")
    assert gcal_mcp.agendas_configuradas() == {"bruna": "a@exemplo.test"}


def test_rotulo_nao_diferencia_maiuscula(monkeypatch):
    monkeypatch.setenv("SOP_AGENDAS", "Bruna=a@exemplo.test")
    assert gcal_mcp.resolver("BRUNA") == "a@exemplo.test"


def test_id_explicito_passa_direto(monkeypatch):
    monkeypatch.setenv("SOP_AGENDAS", "bruna=a@exemplo.test")
    assert gcal_mcp.resolver("outra@exemplo.test") == "outra@exemplo.test"


def test_rotulo_desconhecido_lista_os_conhecidos(monkeypatch):
    """A mensagem precisa ensinar o agente a acertar na segunda tentativa."""
    monkeypatch.setenv("SOP_AGENDAS", "bruna=a@exemplo.test,wagner=b@exemplo.test")
    with pytest.raises(ValueError) as erro:
        gcal_mcp.resolver("fulano")
    assert "bruna" in str(erro.value) and "wagner" in str(erro.value)


def test_sem_rotulo_com_duas_agendas_pede_para_escolher(monkeypatch):
    """Com duas pessoas na operação, escolher por conta própria é errar metade."""
    monkeypatch.setenv("SOP_AGENDAS", "bruna=a@exemplo.test,wagner=b@exemplo.test")
    with pytest.raises(ValueError, match="Diga de qual agenda"):
        gcal_mcp.resolver("")


def test_sem_rotulo_com_uma_agenda_so_usa_ela(monkeypatch):
    monkeypatch.setenv("SOP_AGENDAS", "bruna=a@exemplo.test")
    assert gcal_mcp.resolver("") == "a@exemplo.test"


def test_agenda_padrao_do_ambiente_vence_quando_definida(monkeypatch):
    monkeypatch.setenv("SOP_AGENDAS", "bruna=a@exemplo.test,wagner=b@exemplo.test")
    monkeypatch.setenv("GOOGLE_CALENDAR_ID", "padrao@exemplo.test")
    assert gcal_mcp.resolver("") == "padrao@exemplo.test"


def test_primary_nao_conta_como_padrao_util(monkeypatch):
    """`primary` é o default do dataclass, não uma escolha de quem configurou."""
    monkeypatch.setenv("SOP_AGENDAS", "bruna=a@exemplo.test,wagner=b@exemplo.test")
    monkeypatch.setenv("GOOGLE_CALENDAR_ID", "primary")
    with pytest.raises(ValueError, match="Diga de qual agenda"):
        gcal_mcp.resolver("")


# -- as tools devolvem falha legível, não traceback --------------------------


class ClienteFalso:
    """Substituto do cliente HTTP, programado para levantar ou devolver."""

    def __init__(self, erro: Exception | None = None, retorno=None) -> None:
        self.erro = erro
        self.retorno = retorno
        self.apagados = []

        class ConfigFalsa:
            google_calendar_id = "a@exemplo.test"

        self.config = ConfigFalsa()

    def _talvez_falhar(self):
        if self.erro:
            raise self.erro

    def proximos_dias(self, dias=7):
        self._talvez_falhar()
        return self.retorno or []

    def conflitos(self, data, hora, duracao_minutos=60):
        self._talvez_falhar()
        return self.retorno or []

    def janela(self, data, hora, duracao):
        return (f"{data}T{hora}:00-03:00", f"{data}T{hora}:00-03:00")

    def criar_evento(self, **kwargs):
        self._talvez_falhar()
        return "evento-novo"

    def apagar_evento(self, evento_id):
        self._talvez_falhar()
        self.apagados.append(evento_id)


def _com_cliente(monkeypatch, cliente):
    monkeypatch.setattr(gcal_mcp, "cliente_de", lambda _agenda: cliente)


def test_consultar_traduz_credencial_invalida(monkeypatch):
    _com_cliente(monkeypatch, ClienteFalso(ErroCredencialGoogle("chave revogada")))
    resposta = gcal_mcp.agenda_consultar(agenda="bruna")

    assert resposta["ok"] is False
    assert "chave revogada" in resposta["erro"]


def test_consultar_traduz_api_fora_do_ar(monkeypatch):
    _com_cliente(monkeypatch, ClienteFalso(ErroIndisponivelGoogle("503 no Google")))
    resposta = gcal_mcp.agenda_consultar(agenda="bruna")

    assert resposta["ok"] is False
    assert "503" in resposta["erro"]


def test_consultar_resume_os_eventos(monkeypatch):
    evento = {
        "id": "abc",
        "summary": "Ensaio",
        "start": {"dateTime": "2026-08-30T06:00:00-03:00"},
        "end": {"dateTime": "2026-08-30T07:00:00-03:00"},
        "htmlLink": "https://exemplo.test/abc",
    }
    _com_cliente(monkeypatch, ClienteFalso(retorno=[evento]))
    resposta = gcal_mcp.agenda_consultar(agenda="bruna")

    assert resposta["ok"] is True
    assert resposta["total"] == 1
    assert resposta["eventos"][0] == {
        "id": "abc",
        "titulo": "Ensaio",
        "inicio": "2026-08-30T06:00:00-03:00",
        "fim": "2026-08-30T07:00:00-03:00",
        "link": "https://exemplo.test/abc",
    }


def test_conflito_volta_como_decisao_e_nao_como_erro_tecnico(monkeypatch):
    """O agente precisa perguntar à pessoa, não relatar uma falha do sistema."""
    ocupados = [{"start": "2026-08-30T06:00:00-03:00", "end": "2026-08-30T07:00:00-03:00"}]
    _com_cliente(monkeypatch, ClienteFalso(ConflitoDeAgenda(ocupados)))

    resposta = gcal_mcp.agenda_criar("Ensaio", "2026-08-30", "06:00", agenda="bruna")

    assert resposta["ok"] is False
    assert resposta["conflito"] is True
    assert resposta["ocupados"] == ocupados
    assert "outro" in resposta["erro"]


def test_criar_sem_titulo_e_recusado_antes_da_rede(monkeypatch):
    _com_cliente(monkeypatch, ClienteFalso(AssertionError("não deveria chamar a API")))
    resposta = gcal_mcp.agenda_criar("   ", "2026-08-30", "06:00")

    assert resposta["ok"] is False
    assert "título" in resposta["erro"]


def test_criar_devolve_o_id_e_o_inicio_com_fuso(monkeypatch):
    _com_cliente(monkeypatch, ClienteFalso())
    resposta = gcal_mcp.agenda_criar("Ensaio", "2026-08-30", "06:00", agenda="bruna")

    assert resposta["ok"] is True
    assert resposta["id"] == "evento-novo"
    assert resposta["inicio"].endswith("-03:00")
    assert resposta["pagina_notion"] == "pagina-nova"


def test_criar_desfaz_evento_se_notion_falhar(monkeypatch):
    cliente = ClienteFalso()
    _com_cliente(monkeypatch, cliente)

    def falhar(**_kwargs):
        raise RuntimeError("Notion indisponível")

    monkeypatch.setattr(gcal_mcp, "registrar_no_notion", falhar)
    resposta = gcal_mcp.agenda_criar(
        "Ensaio", "2026-08-30", "06:00", agenda="bruna"
    )

    assert resposta["ok"] is False
    assert cliente.apagados == ["evento-novo"]
    assert "desfeito" in resposta["erro"]


def test_apagar_sem_id_e_recusado(monkeypatch):
    _com_cliente(monkeypatch, ClienteFalso(AssertionError("não deveria chamar a API")))
    resposta = gcal_mcp.agenda_apagar("")

    assert resposta["ok"] is False


def test_agenda_desconhecida_nao_derruba_a_tool(monkeypatch):
    """Rótulo errado é erro do agente, e volta como texto que ele entende."""
    monkeypatch.setenv("SOP_AGENDAS", "bruna=a@exemplo.test")
    resposta = gcal_mcp.agenda_consultar(agenda="ninguem")

    assert resposta["ok"] is False
    assert "bruna" in resposta["erro"]
