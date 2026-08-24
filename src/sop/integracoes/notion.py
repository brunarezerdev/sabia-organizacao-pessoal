"""Cliente da API do Notion — o banco de dados no-code do sistema.

Autenticação: token de integração interna no header `Authorization: Bearer`,
lido de `NOTION_TOKEN`. A integração precisa ser compartilhada com a database
alvo dentro do próprio Notion, senão a API responde 404 mesmo com token válido.

Escolha de arquitetura: o Notion é o banco porque a pessoa consegue abrir,
filtrar e editar os registros sem passar pelo sistema. Um Postgres seria mais
rápido e completamente inútil para quem não escreve SQL.

Propriedades esperadas na database (crie com estes nomes e tipos):

    Titulo      -> title
    Agente      -> select
    Categoria   -> select
    Data        -> date
    Observacao  -> rich_text
    Detalhes    -> rich_text
"""

from __future__ import annotations

from typing import Any

import requests

from ..config import Config, exigir
from ..modelos import Item

BASE = "https://api.notion.com/v1"
VERSAO_API = "2022-06-28"
TIMEOUT = 30
LIMITE_TEXTO = 2000  # limite de caracteres de um rich_text no Notion


class ClienteNotion:
    def __init__(self, config: Config, sessao: Any | None = None) -> None:
        exigir(config, "notion")
        self.config = config
        self.sessao = sessao or requests.Session()

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.notion_token}",
            "Notion-Version": VERSAO_API,
            "Content-Type": "application/json",
        }

    def _chamar(self, metodo: str, caminho: str, corpo: dict[str, Any] | None = None) -> dict[str, Any]:
        resposta = self.sessao.request(
            metodo,
            f"{BASE}{caminho}",
            headers=self._headers,
            json=corpo,
            timeout=TIMEOUT,
        )
        if resposta.status_code >= 400:
            detalhe = ""
            try:
                detalhe = resposta.json().get("message", "")
            except ValueError:
                detalhe = resposta.text[:200]
            raise RuntimeError(
                f"Notion respondeu {resposta.status_code} em {caminho}: {detalhe}"
            )
        return resposta.json()

    # -- mapeamento ----------------------------------------------------------

    @staticmethod
    def _texto(valor: str) -> dict[str, Any]:
        return {"rich_text": [{"text": {"content": (valor or "")[:LIMITE_TEXTO]}}]}

    def propriedades(self, item: Item) -> dict[str, Any]:
        """Converte um `Item` no formato de propriedades do Notion."""
        props: dict[str, Any] = {
            "Titulo": {"title": [{"text": {"content": item.titulo[:LIMITE_TEXTO]}}]},
            "Agente": {"select": {"name": item.agente}},
            "Categoria": {"select": {"name": item.categoria}},
        }
        if item.data:
            inicio = f"{item.data}T{item.hora}:00" if item.hora else item.data
            props["Data"] = {"date": {"start": inicio}}
        if item.observacao:
            props["Observacao"] = self._texto(item.observacao)
        if item.extras:
            detalhes = "; ".join(f"{k}: {v}" for k, v in sorted(item.extras.items()))
            props["Detalhes"] = self._texto(detalhes)
        return props

    # -- operações -----------------------------------------------------------

    def criar_item(self, item: Item) -> str:
        """Cria uma página na database e devolve o id do registro."""
        corpo = {
            "parent": {"database_id": self.config.notion_database_id},
            "properties": self.propriedades(item),
        }
        resultado = self._chamar("POST", "/pages", corpo)
        return str(resultado.get("id", ""))

    def listar_itens(self, agente: str | None = None, limite: int = 25) -> list[dict[str, Any]]:
        """Consulta a database, opcionalmente filtrando por agente."""
        corpo: dict[str, Any] = {"page_size": min(limite, 100)}
        if agente:
            corpo["filter"] = {"property": "Agente", "select": {"equals": agente}}
        resultado = self._chamar(
            "POST", f"/databases/{self.config.notion_database_id}/query", corpo
        )
        return resultado.get("results", [])

    def verificar(self) -> bool:
        """Confere se o token enxerga a database. Útil como health check."""
        self._chamar("GET", f"/databases/{self.config.notion_database_id}")
        return True
