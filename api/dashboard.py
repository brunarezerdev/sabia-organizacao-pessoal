"""Endpoint público, somente leitura, do dashboard financeiro DEMO.

Porte do `src/sop/dashboard_server.py` para a superfície serverless da Vercel.
O servidor local continua existindo para desenvolvimento; este módulo é o que
roda em produção, e por isso repete as garantias em vez de importá-las:

    - Só responde GET. Qualquer outro método devolve 405 sem tocar no Notion.
    - Só roda com `SABIA_DEMO=1`. Sem isso, recusa antes de ler qualquer fonte.
    - Descarta toda linha que não tenha `Dados de demonstração` marcado.
    - Nunca escreve. As únicas chamadas ao Notion são consultas de leitura.
    - Não devolve id de página, cursor nem mensagem de erro crua do Notion.
    - Lê o token só de variável de ambiente do projeto na Vercel. O token nunca
      chega ao browser, nunca entra no repositório e nunca vai na URL.

Só depende da biblioteca padrão, de propósito: a superfície pública não deve
arrastar `requests`, `google-auth` nem `mcp` para dentro do bundle.

A duplicação da regra de filtragem em relação a `sop.dashboard_server` é
coberta por `tests/test_api_dashboard.py`, que roda a mesma fixture nas duas
implementações e exige saída idêntica.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import hashlib
import json
import os
import urllib.error
import urllib.request
from typing import Any

BASE = "https://api.notion.com/v1"
VERSAO_API = "2022-06-28"
TIMEOUT = 5  # segundos por consulta; três consultas cabem no limite da função
PAGINAS_MAX = 5  # teto defensivo: a base DEMO tem dezenas de linhas, não milhares
FRESCOR = 15  # segundos de cache na borda, o mesmo TTL do servidor local

FONTES = (
    "NOTION_LANCAMENTOS_DEMO_ID",
    "NOTION_CUSTOS_DEMO_ID",
    "NOTION_ORCAMENTO_DEMO_ID",
)

CSP = (
    "default-src 'self'; style-src 'self'; script-src 'self'; "
    "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
    "form-action 'none'; object-src 'none'; "
    "frame-ancestors https://www.notion.so https://notion.so"
)

INDISPONIVEL = {"erro": "Dados temporariamente indisponíveis."}


# -- leitura do Notion -------------------------------------------------------


def _texto(propriedade: dict[str, Any]) -> str:
    """Concatena o texto de uma propriedade title/rich_text."""
    tipo = propriedade.get("type", "")
    return "".join(p.get("plain_text", "") for p in propriedade.get(tipo, []) or [])


def _e_demo(pagina: dict[str, Any]) -> bool:
    """Só passa quem tem `Dados de demonstração` explicitamente marcado.

    Ausente, nulo ou desmarcado reprova. A checagem é `is True` para que um
    valor inesperado da API nunca seja lido como permissão.
    """
    propriedades = pagina.get("properties", {})
    return propriedades.get("Dados de demonstração", {}).get("checkbox") is True


def _consultar(database_id: str, token: str) -> list[dict[str, Any]]:
    """Consulta uma database e devolve apenas as linhas DEMO."""
    paginas: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(PAGINAS_MAX):
        corpo: dict[str, Any] = {"page_size": 100}
        if cursor:
            corpo["start_cursor"] = cursor
        requisicao = urllib.request.Request(
            f"{BASE}/databases/{database_id}/query",
            data=json.dumps(corpo).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": VERSAO_API,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(requisicao, timeout=TIMEOUT) as resposta:
            dados = json.loads(resposta.read().decode("utf-8"))
        paginas.extend(p for p in dados.get("results", []) if _e_demo(p))
        if not dados.get("has_more"):
            break
        cursor = dados.get("next_cursor")
    return paginas


def carregar(consultar=_consultar) -> dict[str, Any]:
    """Monta o payload do dashboard a partir das três bases DEMO."""
    if os.environ.get("SABIA_DEMO") != "1":
        raise RuntimeError("ambiente DEMO obrigatório")
    token = os.environ.get("NOTION_TOKEN", "")
    ids = [os.environ.get(nome, "") for nome in FONTES]
    if not token or not all(ids):
        raise RuntimeError("configuração DEMO incompleta")

    lancamentos_crus, custos_crus, orcamentos_crus = [
        consultar(fonte, token) for fonte in ids
    ]

    lancamentos = []
    for pagina in lancamentos_crus:
        p = pagina["properties"]
        lancamentos.append(
            {
                "nome": _texto(p["Lançamento"]),
                "tipo": (p["Tipo"].get("select") or {}).get("name", ""),
                "data": (p["Data"].get("date") or {}).get("start", ""),
                "categoria": (p["Categoria"].get("select") or {}).get(
                    "name", "Sem categoria"
                ),
                "status": (p["Status"].get("select") or {}).get("name", ""),
                "valor": p["Valor"].get("number") or 0,
            }
        )
    custos = [
        {
            "nome": _texto(p["properties"]["Custo fixo / Assinatura"]),
            "valor": p["properties"]["Valor previsto"].get("number") or 0,
        }
        for p in custos_crus
    ]
    orcamentos = [
        {
            "categoria": _texto(p["properties"]["Categoria"]),
            "limite": p["properties"]["Limite planejado"].get("number") or 0,
            "realizado": p["properties"]["Realizado (manual no DEMO)"].get("number")
            or 0,
        }
        for p in orcamentos_crus
    ]
    return {
        "ambiente": "DEMO",
        "lancamentos": lancamentos,
        "custos": custos,
        "orcamentos": orcamentos,
    }


def corpo_e_etag(dados: dict[str, Any]) -> tuple[bytes, str]:
    corpo = json.dumps(dados, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return corpo, hashlib.sha256(corpo).hexdigest()


# -- superfície HTTP ---------------------------------------------------------


class handler(BaseHTTPRequestHandler):  # noqa: N801 — nome exigido pela Vercel
    def _cabecalhos(self, corpo: bytes, etag: str | None) -> None:
        if etag:
            self.send_header("ETag", etag)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        # max-age=0 no browser, 15 s na borda: o mesmo frescor do servidor local.
        self.send_header("Cache-Control", f"public, max-age=0, s-maxage={FRESCOR}")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self) -> None:  # noqa: N802
        try:
            corpo, etag = corpo_e_etag(carregar())
        except Exception:
            # Nada do erro original sai daqui: nem status do Notion, nem id de
            # base, nem traceback. Quem depura olha o log da função.
            corpo, _ = corpo_e_etag(INDISPONIVEL)
            self.send_response(503)
            self._cabecalhos(corpo, None)
            return
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", f"public, max-age=0, s-maxage={FRESCOR}")
            self.end_headers()
            return
        self.send_response(200)
        self._cabecalhos(corpo, etag)

    def _recusar(self) -> None:
        corpo, _ = corpo_e_etag({"erro": "Método não permitido."})
        self.send_response(405)
        self.send_header("Allow", "GET")
        self._cabecalhos(corpo, None)

    # O painel é somente leitura. Todo CRUD continua no Notion.
    do_POST = do_PUT = do_PATCH = do_DELETE = _recusar

    def log_message(self, *_args: Any) -> None:
        """Silencia o log padrão para não gravar caminho ou cabeçalho de request."""
