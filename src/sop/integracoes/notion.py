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

Existe uma segunda database, a de Regras (`NOTION_REGRAS_DATABASE_ID`), que é a
configuração do motor de regras se-então e é editada à mão por quem usa:

    Nome                  -> title
    Se                    -> rich_text
    Então                 -> rich_text
    Área                  -> select
    Origem                -> select (Agenda ou Estoque)
    Palavras-chave        -> rich_text (termos separados por vírgula)
    Antecedência em dias  -> number
    Ativa                 -> checkbox
    Observação            -> rich_text
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

    # -- base de Regras e página do ritual -----------------------------------

    def consultar_database(
        self, database_id: str, filtro: dict[str, Any] | None = None, limite: int = 100
    ) -> list[dict[str, Any]]:
        """Consulta qualquer database, paginando até o limite pedido.

        Existe separado de `listar_itens` porque a base de Regras tem outro
        esquema e outro id: ela é a configuração do sistema, não o registro.
        """
        paginas: list[dict[str, Any]] = []
        cursor: str | None = None
        while len(paginas) < limite:
            corpo: dict[str, Any] = {"page_size": min(100, limite - len(paginas))}
            if filtro:
                corpo["filter"] = filtro
            if cursor:
                corpo["start_cursor"] = cursor
            resultado = self._chamar("POST", f"/databases/{database_id}/query", corpo)
            paginas.extend(resultado.get("results", []))
            if not resultado.get("has_more"):
                break
            cursor = resultado.get("next_cursor")
        return paginas

    def regras(self, somente_ativas: bool = True) -> list[dict[str, Any]]:
        """Devolve as linhas cruas da base de Regras.

        A conversão para `Regra` fica em `sop.regras`, para o cliente HTTP não
        precisar saber o que é uma regra.
        """
        exigir(self.config, "regras")
        filtro = {"property": "Ativa", "checkbox": {"equals": True}} if somente_ativas else None
        return self.consultar_database(self.config.notion_regras_database_id, filtro)

    def anexar_blocos(self, page_id: str, blocos: list[dict[str, Any]]) -> int:
        """Acrescenta blocos ao fim de uma página, em lotes de 100.

        Só acrescenta. Nada aqui apaga ou reescreve o que já estava na página.
        """
        enviados = 0
        for inicio in range(0, len(blocos), 100):
            lote = blocos[inicio : inicio + 100]
            self._chamar("PATCH", f"/blocks/{page_id}/children", {"children": lote})
            enviados += len(lote)
        return enviados
