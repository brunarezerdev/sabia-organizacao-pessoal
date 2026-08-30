"""Garantias da função pública do dashboard DEMO na Vercel.

Nenhum teste aqui toca a rede: a leitura do Notion é sempre injetada.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "api_dashboard", RAIZ / "api" / "dashboard.py"
)
api = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(api)


# -- fixtures de página do Notion -------------------------------------------


def _prop(tipo, valor):
    return {"type": tipo, tipo: valor}


def lancamento(nome="Feira", demo=True, valor=10):
    return {
        "id": "pagina-secreta-0001",
        "properties": {
            "Dados de demonstração": {"checkbox": demo},
            "Lançamento": _prop("title", [{"plain_text": nome}]),
            "Tipo": {"select": {"name": "Despesa"}},
            "Data": {"date": {"start": "2035-01-01"}},
            "Categoria": {"select": {"name": "Demo"}},
            "Status": {"select": {"name": "Realizado"}},
            "Valor": {"number": valor},
        },
    }


def custo(demo=True):
    return {
        "id": "pagina-secreta-0002",
        "properties": {
            "Dados de demonstração": {"checkbox": demo},
            "Custo fixo / Assinatura": _prop("title", [{"plain_text": "Streaming"}]),
            "Valor previsto": {"number": 30},
        },
    }


def orcamento(demo=True):
    return {
        "id": "pagina-secreta-0003",
        "properties": {
            "Dados de demonstração": {"checkbox": demo},
            "Categoria": _prop("title", [{"plain_text": "Casa"}]),
            "Limite planejado": {"number": 500},
            "Realizado (manual no DEMO)": {"number": 120},
        },
    }


FONTES = {
    "lanc": [lancamento(), lancamento("REAL DO WAGNER", demo=False, valor=9999)],
    "cust": [custo(), custo(demo=False)],
    "orc": [orcamento(), orcamento(demo=False)],
}
IDS = ("lanc", "cust", "orc")


def consultar_falso(database_id, _token):
    """Substitui a chamada HTTP, já aplicando o filtro DEMO como o real faz."""
    return [p for p in FONTES[database_id] if api._e_demo(p)]


@pytest.fixture
def ambiente(monkeypatch):
    monkeypatch.setenv("SABIA_DEMO", "1")
    monkeypatch.setenv("NOTION_TOKEN", "token-de-teste")
    for nome, valor in zip(api.FONTES, IDS):
        monkeypatch.setenv(nome, valor)


# -- filtragem e formato -----------------------------------------------------


def test_omite_toda_linha_sem_marcacao_demo(ambiente):
    dados = api.carregar(consultar_falso)
    assert [x["nome"] for x in dados["lancamentos"]] == ["Feira"]
    assert len(dados["custos"]) == 1 and len(dados["orcamentos"]) == 1
    assert "REAL DO WAGNER" not in json.dumps(dados, ensure_ascii=False)


@pytest.mark.parametrize("checkbox", [False, None, "sim", 1])
def test_so_checkbox_verdadeiro_passa(checkbox):
    pagina = {"properties": {"Dados de demonstração": {"checkbox": checkbox}}}
    assert api._e_demo(pagina) is (checkbox is True)


def test_propriedade_demo_ausente_reprova():
    assert api._e_demo({"properties": {}}) is False
    assert api._e_demo({}) is False


def test_payload_nao_vaza_id_interno(ambiente):
    corpo = json.dumps(api.carregar(consultar_falso), ensure_ascii=False)
    assert "pagina-secreta" not in corpo and "id" not in json.loads(corpo)


def test_ambiente_sempre_marcado_como_demo(ambiente):
    assert api.carregar(consultar_falso)["ambiente"] == "DEMO"


# -- paridade com o servidor local ------------------------------------------


def test_mesma_saida_do_servidor_local(ambiente, monkeypatch):
    """As duas implementações não podem divergir na regra de filtragem."""
    from sop import dashboard_server

    class ClienteFalso:
        def _chamar(self, _metodo, caminho, _corpo):
            chave = next(k for k in FONTES if k in caminho)
            return {"results": FONTES[chave]}

    monkeypatch.setenv("SABIA_DEMO", "1")
    local = dashboard_server.carregar(ClienteFalso(), list(IDS))
    assert api.carregar(consultar_falso) == local


# -- recusas de configuração -------------------------------------------------


def test_recusa_fora_do_ambiente_demo(ambiente, monkeypatch):
    monkeypatch.setenv("SABIA_DEMO", "0")
    with pytest.raises(RuntimeError, match="DEMO"):
        api.carregar(consultar_falso)


def test_recusa_sem_token(ambiente, monkeypatch):
    monkeypatch.delenv("NOTION_TOKEN")
    with pytest.raises(RuntimeError, match="incompleta"):
        api.carregar(consultar_falso)


def test_recusa_com_fonte_faltando(ambiente, monkeypatch):
    monkeypatch.setenv("NOTION_ORCAMENTO_DEMO_ID", "")
    with pytest.raises(RuntimeError, match="incompleta"):
        api.carregar(consultar_falso)


# -- superfície HTTP ---------------------------------------------------------


class Resposta:
    """Handler instanciado sem socket, para inspecionar status e cabeçalhos."""

    def __init__(self, cabecalhos_da_requisicao=None):
        self.h = api.handler.__new__(api.handler)
        self.h.headers = cabecalhos_da_requisicao or {}
        self.status = None
        self.cabecalhos = {}
        self.corpo = b""
        self.h.send_response = lambda codigo, *_: setattr(self, "status", codigo)
        self.h.send_header = lambda chave, valor: self.cabecalhos.__setitem__(
            chave, valor
        )
        self.h.end_headers = lambda: None
        self.h.wfile = self

    def write(self, dados):
        self.corpo += dados

    def json(self):
        return json.loads(self.corpo.decode("utf-8"))


def test_get_responde_com_selo_de_seguranca(ambiente, monkeypatch):
    monkeypatch.setattr(api, "carregar", lambda *a: {"ambiente": "DEMO", "x": 1})
    r = Resposta()
    r.h.do_GET()
    assert r.status == 200
    csp = r.cabecalhos["Content-Security-Policy"]
    assert "frame-ancestors https://www.notion.so https://notion.so" in csp
    assert "default-src 'self'" in csp
    assert r.cabecalhos["X-Content-Type-Options"] == "nosniff"
    assert r.cabecalhos["Cache-Control"] == "public, max-age=0, s-maxage=15"
    assert r.json()["ambiente"] == "DEMO"


def test_etag_devolve_304(ambiente, monkeypatch):
    monkeypatch.setattr(api, "carregar", lambda *a: {"ambiente": "DEMO"})
    _, etag = api.corpo_e_etag({"ambiente": "DEMO"})
    r = Resposta({"If-None-Match": etag})
    r.h.do_GET()
    assert r.status == 304 and r.corpo == b""


def test_erro_do_notion_nao_vaza_detalhe(ambiente, monkeypatch):
    def explodir(*_a):
        raise RuntimeError("Notion respondeu 401 em /databases/abc123: token inválido")

    monkeypatch.setattr(api, "carregar", explodir)
    r = Resposta()
    r.h.do_GET()
    assert r.status == 503
    assert r.json() == api.INDISPONIVEL
    texto = r.corpo.decode("utf-8")
    assert "401" not in texto and "abc123" not in texto and "token" not in texto


@pytest.mark.parametrize("metodo", ["do_POST", "do_PUT", "do_PATCH", "do_DELETE"])
def test_escrita_publica_recusada(metodo, ambiente, monkeypatch):
    """Nenhum método de escrita pode existir na superfície pública."""

    def nao_deveria_ler(*_a):
        raise AssertionError("método de escrita não pode consultar o Notion")

    monkeypatch.setattr(api, "carregar", nao_deveria_ler)
    r = Resposta()
    getattr(r.h, metodo)()
    assert r.status == 405 and r.cabecalhos["Allow"] == "GET"


def test_nao_registra_log_com_dado_de_requisicao():
    assert api.handler.log_message(None, "%s", "/api/dashboard?token=x") is None
