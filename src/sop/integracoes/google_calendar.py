"""Cliente da Google Calendar API v3 — leitura e escrita de eventos.

Autenticação: OAuth 2.0 com refresh token. O fluxo interativo (consentimento no
navegador) roda uma única vez via `scripts/autorizar_google.py` e grava um JSON
com `refresh_token`, `client_id` e `client_secret` no caminho de
`GOOGLE_TOKEN_PATH`. Daqui em diante este cliente troca o refresh token por um
access token de curta duração e o mantém apenas em memória.

Por que não a biblioteca oficial: só precisamos de três chamadas REST, e evitar
`google-api-python-client` mantém a instalação leve. O fluxo interativo, que é
a parte chata de implementar, fica isolado no script de autorização.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

from ..config import Config, exigir

BASE = "https://www.googleapis.com/calendar/v3"
URL_TOKEN = "https://oauth2.googleapis.com/token"
TIMEOUT = 30
MARGEM_EXPIRACAO = 60  # renova o token um minuto antes de expirar


class ClienteGoogleCalendar:
    def __init__(self, config: Config, sessao: Any | None = None) -> None:
        exigir(config, "google_calendar")
        self.config = config
        self.sessao = sessao or requests.Session()
        self._access_token: str = ""
        self._expira_em: float = 0.0

    # -- autenticação --------------------------------------------------------

    def _credenciais(self) -> dict[str, Any]:
        caminho = Path(self.config.google_token_path)
        if not caminho.is_file():
            raise RuntimeError(
                f"Token do Google não encontrado em '{caminho}'. "
                "Rode `python scripts/autorizar_google.py` uma vez para gerá-lo."
            )
        return json.loads(caminho.read_text(encoding="utf-8"))

    def _renovar(self) -> str:
        """Troca o refresh token por um access token válido."""
        creds = self._credenciais()
        faltando = [
            campo
            for campo in ("refresh_token", "client_id", "client_secret")
            if not creds.get(campo)
        ]
        if faltando:
            raise RuntimeError(
                f"O arquivo de token do Google está incompleto (falta: {', '.join(faltando)}). "
                "Rode `python scripts/autorizar_google.py` novamente."
            )
        resposta = self.sessao.post(
            URL_TOKEN,
            data={
                "grant_type": "refresh_token",
                "refresh_token": creds["refresh_token"],
                "client_id": creds["client_id"],
                "client_secret": creds["client_secret"],
            },
            timeout=TIMEOUT,
        )
        resposta.raise_for_status()
        corpo = resposta.json()
        self._access_token = corpo["access_token"]
        self._expira_em = time.time() + float(corpo.get("expires_in", 3600))
        return self._access_token

    def token(self) -> str:
        """Devolve um access token válido, renovando quando necessário."""
        if not self._access_token or time.time() >= self._expira_em - MARGEM_EXPIRACAO:
            return self._renovar()
        return self._access_token

    def _chamar(self, metodo: str, caminho: str, **kwargs: Any) -> dict[str, Any]:
        resposta = self.sessao.request(
            metodo,
            f"{BASE}{caminho}",
            headers={"Authorization": f"Bearer {self.token()}"},
            timeout=TIMEOUT,
            **kwargs,
        )
        if resposta.status_code >= 400:
            raise RuntimeError(
                f"Google Calendar respondeu {resposta.status_code} em {caminho}: "
                f"{resposta.text[:200]}"
            )
        return resposta.json() if resposta.content else {}

    # -- operações -----------------------------------------------------------

    @property
    def _calendario(self) -> str:
        return self.config.google_calendar_id or "primary"

    def montar_evento(
        self,
        titulo: str,
        data: str,
        hora: str | None = None,
        duracao_minutos: int = 60,
        descricao: str = "",
    ) -> dict[str, Any]:
        """Monta o corpo de um evento. Sem hora, vira evento de dia inteiro."""
        corpo: dict[str, Any] = {"summary": titulo}
        if descricao:
            corpo["description"] = descricao

        if hora:
            inicio_h, inicio_m = (int(p) for p in hora.split(":"))
            total = inicio_h * 60 + inicio_m + duracao_minutos
            fim = f"{(total // 60) % 24:02d}:{total % 60:02d}"
            corpo["start"] = {
                "dateTime": f"{data}T{hora}:00",
                "timeZone": self.config.timezone,
            }
            corpo["end"] = {
                "dateTime": f"{data}T{fim}:00",
                "timeZone": self.config.timezone,
            }
        else:
            corpo["start"] = {"date": data}
            corpo["end"] = {"date": data}
        return corpo

    def criar_evento(
        self,
        titulo: str,
        data: str,
        hora: str | None = None,
        duracao_minutos: int = 60,
        descricao: str = "",
    ) -> str:
        """Cria um evento na agenda e devolve o id."""
        corpo = self.montar_evento(titulo, data, hora, duracao_minutos, descricao)
        resultado = self._chamar(
            "POST", f"/calendars/{self._calendario}/events", json=corpo
        )
        return str(resultado.get("id", ""))

    def listar_eventos(self, inicio_iso: str, fim_iso: str, limite: int = 50) -> list[dict[str, Any]]:
        """Lista eventos em um intervalo (timestamps RFC 3339)."""
        resultado = self._chamar(
            "GET",
            f"/calendars/{self._calendario}/events",
            params={
                "timeMin": inicio_iso,
                "timeMax": fim_iso,
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": limite,
            },
        )
        return resultado.get("items", [])

    def apagar_evento(self, evento_id: str) -> None:
        self._chamar("DELETE", f"/calendars/{self._calendario}/events/{evento_id}")
