"""Carregamento de configuração a partir do ambiente.

Regras deste módulo:

- Nada aqui levanta exceção só por faltar credencial. O projeto precisa subir
  sem `.env` e explicar o que falta, em vez de quebrar com um traceback.
- Nenhum valor padrão é uma credencial real. Ausente é ausente.
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]


def carregar_env(caminho: Path | None = None) -> dict[str, str]:
    """Lê um arquivo `.env` no formato CHAVE=valor.

    Linhas vazias e comentários são ignorados. Não sobrescreve variáveis já
    presentes no ambiente do processo — o ambiente sempre vence.
    """
    caminho = caminho or RAIZ / ".env"
    valores: dict[str, str] = {}
    if not caminho.is_file():
        return valores
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        valores[chave.strip()] = valor.strip().strip('"').strip("'")
    return valores


@dataclass(frozen=True)
class Config:
    """Configuração completa do sistema. Campos vazios significam ausente."""

    telegram_token: str = ""
    telegram_chat_autorizado: str = ""

    notion_token: str = ""
    notion_database_id: str = ""
    notion_regras_database_id: str = ""
    notion_ritual_page_id: str = ""
    notion_rituais_database_id: str = ""
    notion_tarefas_database_id: str = ""

    google_credentials_path: str = ""
    google_token_path: str = ""
    # Conta de serviço: a segunda forma de autenticar na Google Agenda. Não é
    # alternativa "de teste" — é a rota usada em produção nesta instalação,
    # porque não exige um humano no navegador para renovar consentimento.
    # Ver `integracoes/google_calendar.py` para a comparação das duas rotas.
    google_service_account_path: str = ""
    google_calendar_id: str = "primary"

    # -- camada de IA --------------------------------------------------------
    # `ia_backend` força um backend; vazio deixa `criar_adaptador` escolher.
    ia_backend: str = ""

    # OpenClaw: onde o provedor de IA está autenticado. O projeto não guarda
    # credencial do provedor — a rota Codex é OAuth, feita pelo próprio CLI.
    openclaw_base: str = "~/.openclaw"
    openclaw_agente: str = "main"
    openclaw_modelo: str = "openai/gpt-5.5"
    openclaw_comando: str = ""
    openclaw_timeout: int = 120

    # Rota alternativa por API key. NÃO é a rota Codex.
    openai_api_key: str = ""
    openai_model: str = "gpt-5.5"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5"

    timezone: str = "America/Sao_Paulo"
    fila_dir: str = ".fila"

    # Requisitos por integração: usado por `faltando()` e pelo diagnóstico.
    #
    # Um item string é obrigatório. Um item tupla significa "pelo menos uma
    # destas serve" — é o caso da Google Agenda, que aceita duas rotas de
    # autenticação (OAuth com refresh token ou conta de serviço) e está pronta
    # com qualquer uma das duas.
    _REQUISITOS: dict[str, tuple[str | tuple[str, ...], ...]] = field(
        default_factory=lambda: {
            "telegram": ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID_AUTORIZADO"),
            "notion": ("NOTION_TOKEN", "NOTION_DATABASE_ID"),
            "regras": ("NOTION_TOKEN", "NOTION_REGRAS_DATABASE_ID"),
            "google_calendar": (("GOOGLE_TOKEN_PATH", "GOOGLE_SERVICE_ACCOUNT_PATH"),),
            "openclaw": ("OPENCLAW_COMANDO",),
        },
        repr=False,
        compare=False,
    )

    @classmethod
    def do_ambiente(cls, extra: dict[str, str] | None = None) -> "Config":
        """Monta a configuração a partir de `os.environ` + `.env`."""
        base = dict(carregar_env())
        base.update(extra or {})

        def ler(chave: str, padrao: str = "") -> str:
            return os.environ.get(chave) or base.get(chave) or padrao

        def ler_segredo(chave: str) -> str:
            """Valor direto ou, se houver, o conteúdo de `<CHAVE>_PATH`.

            Um segredo em arquivo 0600 é melhor do que o mesmo segredo no
            `.env`: sobrevive a um `cat .env` no meio de uma conversa, não é
            copiado junto quando alguém manda a configuração para outra
            pessoa, e é o mesmo arquivo que os servidores MCP já leem. A
            variável direta continua valendo para quem preferir o caminho
            simples — só não é a rota recomendada.
            """
            direto = ler(chave)
            if direto:
                return direto
            caminho = ler(f"{chave}_PATH")
            if not caminho:
                return ""
            arquivo = Path(caminho).expanduser()
            try:
                return arquivo.read_text(encoding="utf-8").strip()
            except OSError:
                # Coerente com o resto do módulo: faltar credencial não
                # derruba o processo. O diagnóstico é que reporta.
                return ""

        return cls(
            telegram_token=ler_segredo("TELEGRAM_BOT_TOKEN"),
            telegram_chat_autorizado=ler("TELEGRAM_CHAT_ID_AUTORIZADO"),
            notion_token=ler_segredo("NOTION_TOKEN"),
            notion_database_id=ler("NOTION_DATABASE_ID"),
            notion_regras_database_id=ler("NOTION_REGRAS_DATABASE_ID"),
            notion_ritual_page_id=ler("NOTION_RITUAL_PAGE_ID"),
            notion_rituais_database_id=ler("NOTION_RITUAIS_DATABASE_ID"),
            notion_tarefas_database_id=ler("NOTION_TAREFAS_DATABASE_ID"),
            google_credentials_path=ler("GOOGLE_CREDENTIALS_PATH"),
            google_token_path=ler("GOOGLE_TOKEN_PATH"),
            google_service_account_path=ler("GOOGLE_SERVICE_ACCOUNT_PATH"),
            google_calendar_id=ler("GOOGLE_CALENDAR_ID", "primary"),
            ia_backend=ler("IA_BACKEND"),
            openclaw_base=ler("OPENCLAW_BASE", "~/.openclaw"),
            openclaw_agente=ler("OPENCLAW_AGENTE", "main"),
            openclaw_modelo=ler("OPENCLAW_MODELO", "openai/gpt-5.5"),
            openclaw_comando=ler("OPENCLAW_COMANDO"),
            openclaw_timeout=int(ler("OPENCLAW_TIMEOUT", "120") or 120),
            openai_api_key=ler_segredo("OPENAI_API_KEY"),
            openai_model=ler("OPENAI_MODEL", "gpt-5.5"),
            anthropic_api_key=ler_segredo("ANTHROPIC_API_KEY"),
            anthropic_model=ler("ANTHROPIC_MODEL", "claude-opus-5"),
            timezone=ler("TIMEZONE", "America/Sao_Paulo"),
            fila_dir=ler("FILA_DIR", ".fila"),
        )

    # -- OpenClaw ------------------------------------------------------------

    def openclaw_comando_partido(self) -> list[str]:
        """Quebra `OPENCLAW_COMANDO` em argv, respeitando aspas.

        A variável é uma linha de comando escrita por quem instalou, então o
        `{agente}` é substituído aqui pelo id do agente principal.
        """
        if not self.openclaw_comando.strip():
            return []
        bruto = self.openclaw_comando.replace("{agente}", self.openclaw_agente)
        return shlex.split(bruto)

    # -- diagnóstico ---------------------------------------------------------

    def _valor_de(self, variavel: str) -> str:
        mapa = {
            "TELEGRAM_BOT_TOKEN": self.telegram_token,
            "TELEGRAM_CHAT_ID_AUTORIZADO": self.telegram_chat_autorizado,
            "NOTION_TOKEN": self.notion_token,
            "NOTION_DATABASE_ID": self.notion_database_id,
            "NOTION_REGRAS_DATABASE_ID": self.notion_regras_database_id,
            "NOTION_RITUAL_PAGE_ID": self.notion_ritual_page_id,
            "NOTION_RITUAIS_DATABASE_ID": self.notion_rituais_database_id,
            "NOTION_TAREFAS_DATABASE_ID": self.notion_tarefas_database_id,
            "GOOGLE_CREDENTIALS_PATH": self.google_credentials_path,
            "GOOGLE_TOKEN_PATH": self.google_token_path,
            "GOOGLE_SERVICE_ACCOUNT_PATH": self.google_service_account_path,
            "OPENCLAW_COMANDO": self.openclaw_comando,
            "OPENAI_API_KEY": self.openai_api_key,
            "ANTHROPIC_API_KEY": self.anthropic_api_key,
        }
        return mapa.get(variavel, "")

    def faltando(self, integracao: str) -> list[str]:
        """Variáveis obrigatórias ausentes para uma integração.

        Um grupo de alternativas só é reportado quando NENHUMA delas está
        preenchida, e aparece como "A ou B" para a mensagem de erro dizer o que
        de fato resolve, em vez de exigir as duas.
        """
        ausentes: list[str] = []
        for exigida in self._REQUISITOS.get(integracao, ()):
            if isinstance(exigida, tuple):
                if not any(self._valor_de(v) for v in exigida):
                    ausentes.append(" ou ".join(exigida))
            elif not self._valor_de(exigida):
                ausentes.append(exigida)
        return ausentes

    def pronta(self, integracao: str) -> bool:
        return not self.faltando(integracao)

    def diagnostico(self) -> dict[str, list[str]]:
        """Mapa integração -> variáveis faltantes. Vazio significa pronta."""
        return {nome: self.faltando(nome) for nome in self._REQUISITOS}


class ConfiguracaoAusente(RuntimeError):
    """Levantada só quando alguém tenta USAR uma integração sem credencial."""

    def __init__(self, integracao: str, variaveis: list[str]) -> None:
        lista = ", ".join(variaveis)
        super().__init__(
            f"A integração '{integracao}' não está configurada. "
            f"Defina no arquivo .env: {lista}. "
            f"Use .env.example como modelo (cp .env.example .env)."
        )
        self.integracao = integracao
        self.variaveis = variaveis


def exigir(config: Config, integracao: str) -> None:
    """Garante que a integração tem credencial, com mensagem clara se não tiver."""
    faltantes = config.faltando(integracao)
    if faltantes:
        raise ConfiguracaoAusente(integracao, faltantes)
