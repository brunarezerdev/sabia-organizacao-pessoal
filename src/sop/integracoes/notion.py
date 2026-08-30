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

from datetime import date, datetime
import time
from typing import Any
from zoneinfo import ZoneInfo

import requests

from ..config import Config, exigir
from ..modelos import Item
from ..ritual import PacoteRitual, semana_que_comeca, semana_que_terminou

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
        for tentativa in range(4):
            resposta = self.sessao.request(
                metodo,
                f"{BASE}{caminho}",
                headers=self._headers,
                json=corpo,
                timeout=TIMEOUT,
            )
            if resposta.status_code != 429 or tentativa == 3:
                break
            espera = float(resposta.headers.get("Retry-After", "1") or "1")
            time.sleep(min(max(espera, 0.1), 5.0))
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
            if item.hora:
                local = datetime.fromisoformat(
                    f"{item.data}T{item.hora}:00"
                ).replace(tzinfo=ZoneInfo(self.config.timezone))
                inicio = local.isoformat()
            else:
                inicio = item.data
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

    # -- registros datados do ritual semanal --------------------------------

    def prioridades_concluidas_na_semana(self, domingo: date) -> list[str]:
        """Devolve os ids das tarefas feitas cujo prazo cai na semana fechada.

        A base atual não registra a data em que o checkbox foi marcado. Por isso
        o filtro usa o prazo, fato verificável, e não afirma quando a tarefa foi
        concluída. Os ids alimentam uma relação do Notion; nenhum dado da tarefa
        é copiado para o registro do ritual.
        """
        if not self.config.notion_tarefas_database_id:
            return []
        inicio, fim = semana_que_terminou(domingo)
        filtro = {
            "and": [
                {"property": "Feito", "checkbox": {"equals": True}},
                {"property": "prazo", "date": {"on_or_after": inicio.isoformat()}},
                {"property": "prazo", "date": {"on_or_before": fim.isoformat()}},
            ]
        }
        paginas = self.consultar_database(self.config.notion_tarefas_database_id, filtro)
        return sorted({str(pagina["id"]) for pagina in paginas if pagina.get("id")})

    def buscar_ritual(self, domingo: date) -> dict[str, Any] | None:
        if not self.config.notion_rituais_database_id:
            return None
        paginas = self.consultar_database(
            self.config.notion_rituais_database_id,
            {"property": "Domingo", "date": {"equals": domingo.isoformat()}},
            limite=1,
        )
        return paginas[0] if paginas else None

    def fechar_rituais_anteriores(self, domingo: date) -> int:
        """Marca registros anteriores como fechados; nunca arquiva nem apaga páginas."""
        filtro = {
            "and": [
                {"property": "Domingo", "date": {"before": domingo.isoformat()}},
                {"property": "Status", "select": {"does_not_equal": "Fechado"}},
            ]
        }
        paginas = self.consultar_database(self.config.notion_rituais_database_id, filtro)
        for pagina in paginas:
            self._chamar(
                "PATCH",
                f"/pages/{pagina['id']}",
                {"properties": {"Status": {"select": {"name": "Fechado"}}}},
            )
        return len(paginas)

    def criar_registro_ritual(
        self, pacote: PacoteRitual, prioridades_concluidas: list[str] | None = None
    ) -> tuple[str, bool]:
        """Cria uma página datada uma única vez e devolve (id, foi_criada)."""
        if not self.config.notion_rituais_database_id:
            raise RuntimeError("NOTION_RITUAIS_DATABASE_ID não está configurado.")
        domingo = date.fromisoformat(pacote.domingo)
        existente = self.buscar_ritual(domingo)
        if existente:
            return str(existente["id"]), False
        inicio_fechada, fim_fechada = semana_que_terminou(domingo)
        inicio_aberta, fim_aberta = semana_que_comeca(domingo)
        nome = f"Ritual de domingo, {domingo.strftime('%d/%m/%Y')}"
        blocos = pacote.para_blocos_notion()
        # A automação não cria arte. Os callouts continuam funcionais, mas sem
        # ícone; capas, imagens e ilustrações também não entram no payload.
        for bloco in blocos:
            if bloco.get("type") == "callout":
                bloco.get("callout", {}).pop("icon", None)
        corpo = {
            "parent": {"database_id": self.config.notion_rituais_database_id},
            "properties": {
                "Nome": {"title": [{"text": {"content": nome}}]},
                "Domingo": {"date": {"start": pacote.domingo}},
                "Status": {"select": {"name": "Aberto"}},
                "Semana fechada": {
                    "date": {
                        "start": inicio_fechada.isoformat(),
                        "end": fim_fechada.isoformat(),
                    }
                },
                "Semana aberta": {
                    "date": {
                        "start": inicio_aberta.isoformat(),
                        "end": fim_aberta.isoformat(),
                    }
                },
                "Prioridades concluídas": {
                    "relation": [
                        {"id": pagina_id}
                        for pagina_id in (prioridades_concluidas or [])
                    ]
                },
            },
            "children": blocos[:100],
        }
        pagina = self._chamar("POST", "/pages", corpo)
        blocos_restantes = blocos[100:]
        if blocos_restantes:
            self.anexar_blocos(str(pagina["id"]), blocos_restantes)
        return str(pagina["id"]), True
