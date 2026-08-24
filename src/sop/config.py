"""Carregamento de configuração a partir do ambiente.

Regras deste módulo:

- Nada aqui levanta exceção só por faltar credencial. O projeto precisa subir
  sem `.env` e explicar o que falta, em vez de quebrar com um traceback.
- Nenhum valor padrão é uma credencial real. Ausente é ausente.
"""

from __future__ import annotations

import os
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

    google_credentials_path: str = ""
    google_token_path: str = ""
    google_calendar_id: str = "primary"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5"

    timezone: str = "America/Sao_Paulo"
    fila_dir: str = ".fila"

    # Requisitos por integração: usado por `faltando()` e pelo diagnóstico.
    _REQUISITOS: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: {
            "telegram": ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID_AUTORIZADO"),
            "notion": ("NOTION_TOKEN", "NOTION_DATABASE_ID"),
            "google_calendar": ("GOOGLE_TOKEN_PATH",),
            "ia": ("ANTHROPIC_API_KEY",),
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

        return cls(
            telegram_token=ler("TELEGRAM_BOT_TOKEN"),
            telegram_chat_autorizado=ler("TELEGRAM_CHAT_ID_AUTORIZADO"),
            notion_token=ler("NOTION_TOKEN"),
            notion_database_id=ler("NOTION_DATABASE_ID"),
            google_credentials_path=ler("GOOGLE_CREDENTIALS_PATH"),
            google_token_path=ler("GOOGLE_TOKEN_PATH"),
            google_calendar_id=ler("GOOGLE_CALENDAR_ID", "primary"),
            anthropic_api_key=ler("ANTHROPIC_API_KEY"),
            anthropic_model=ler("ANTHROPIC_MODEL", "claude-opus-5"),
            timezone=ler("TIMEZONE", "America/Sao_Paulo"),
            fila_dir=ler("FILA_DIR", ".fila"),
        )

    # -- diagnóstico ---------------------------------------------------------

    def _valor_de(self, variavel: str) -> str:
        mapa = {
            "TELEGRAM_BOT_TOKEN": self.telegram_token,
            "TELEGRAM_CHAT_ID_AUTORIZADO": self.telegram_chat_autorizado,
            "NOTION_TOKEN": self.notion_token,
            "NOTION_DATABASE_ID": self.notion_database_id,
            "GOOGLE_CREDENTIALS_PATH": self.google_credentials_path,
            "GOOGLE_TOKEN_PATH": self.google_token_path,
            "ANTHROPIC_API_KEY": self.anthropic_api_key,
        }
        return mapa.get(variavel, "")

    def faltando(self, integracao: str) -> list[str]:
        """Variáveis obrigatórias ausentes para uma integração."""
        exigidas = self._REQUISITOS.get(integracao, ())
        return [v for v in exigidas if not self._valor_de(v)]

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
