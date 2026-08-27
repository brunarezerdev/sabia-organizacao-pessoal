"""Cliente da Google Calendar API v3 — a API 2 da arquitetura.

Autenticação: duas rotas, a mesma interface.

1. **Conta de serviço** (`GOOGLE_SERVICE_ACCOUNT_PATH`) — é a rota de produção
   desta instalação. Uma chave de conta de serviço assina um JWT, o Google
   devolve um access token de curta duração e a agenda da pessoa é acessada
   porque ela compartilhou a agenda com o e-mail da conta de serviço. Ninguém
   precisa estar no navegador para renovar nada: é o que permite ao sistema
   rodar 24/7 sem intervenção.
2. **OAuth com refresh token** (`GOOGLE_TOKEN_PATH`) — o fluxo interativo roda
   uma vez via `scripts/autorizar_google.py` e grava `refresh_token`,
   `client_id` e `client_secret`. Continua suportada porque é a rota que um
   avaliador consegue reproduzir na própria conta, sem admin de workspace.

Em nenhuma das duas o segredo entra no repositório ou na configuração do
OpenClaw: o que é versionado é o *caminho* da credencial, lido do ambiente. O
arquivo em si fica em modo 0600 fora da árvore do projeto, e o access token
resultante vive só em memória, com renovação um minuto antes de expirar.

Por que não a biblioteca oficial para as chamadas: são quatro endpoints REST, e
`google-api-python-client` traria o discovery inteiro junto. O que vale a pena
reaproveitar da biblioteca do Google é só a assinatura do JWT (criptografia não
se escreve à mão), e é exatamente isso que `TokenContaDeServico` usa. As
chamadas ficam aqui para que timeout, retry com recuo e log de cada requisição
morem em um lugar só.
"""

from __future__ import annotations

import json
import logging
import random
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import requests

from ..config import Config, exigir

BASE = "https://www.googleapis.com/calendar/v3"
URL_TOKEN = "https://oauth2.googleapis.com/token"
ESCOPO = "https://www.googleapis.com/auth/calendar"

TIMEOUT = 30  # segundos por requisição; nenhuma chamada fica pendurada
MARGEM_EXPIRACAO = 60  # renova o token um minuto antes de expirar

# Recuo exponencial: 1s, 2s, 4s. Só para erro que faz sentido repetir.
TENTATIVAS = 3
ESPERA_BASE = 1.0
ESPERA_MAXIMA = 30.0
STATUS_RETENTAVEIS = frozenset({429, 500, 502, 503, 504})

log = logging.getLogger("sop.google_calendar")


# ---------------------------------------------------------------------------
# Erros
# ---------------------------------------------------------------------------


class ErroGoogleCalendar(RuntimeError):
    """Falha ao falar com a Google Agenda."""


class ErroCredencialGoogle(ErroGoogleCalendar):
    """Credencial ausente, ilegível, incompleta ou recusada pelo Google.

    Repetir não resolve: ou o arquivo não está lá, ou a agenda não foi
    compartilhada com a conta de serviço. A mensagem diz qual dos dois.
    """


class ErroLimiteGoogle(ErroGoogleCalendar):
    """Cota ou limite de requisição estourado (HTTP 429) mesmo após as tentativas."""


class ErroIndisponivelGoogle(ErroGoogleCalendar):
    """A API não respondeu ou devolveu 5xx nas tentativas todas."""


class ConflitoDeAgenda(ErroGoogleCalendar):
    """O horário pedido colide com compromisso que já existe.

    É erro, e não aviso, de propósito: o sistema nunca sobrepõe um compromisso
    da pessoa por conta própria. Quem chamou decide se insiste.
    """

    def __init__(self, ocupados: list[dict[str, str]]) -> None:
        faixas = ", ".join(f"{o.get('start')} até {o.get('end')}" for o in ocupados)
        super().__init__(f"horário ocupado na agenda: {faixas}")
        self.ocupados = ocupados


# ---------------------------------------------------------------------------
# Autenticação
# ---------------------------------------------------------------------------


class Autenticacao(Protocol):
    """O cliente só precisa saber pedir um token válido."""

    descricao: str

    def token(self) -> str: ...


class TokenOAuth:
    """Troca um refresh token por access token. Rota do fluxo interativo."""

    descricao = "oauth-refresh-token"

    def __init__(self, caminho: str, sessao: Any) -> None:
        self.caminho = caminho
        self.sessao = sessao
        self._access_token = ""
        self._expira_em = 0.0

    def _credenciais(self) -> dict[str, Any]:
        caminho = Path(self.caminho)
        if not caminho.is_file():
            raise ErroCredencialGoogle(
                f"Token do Google não encontrado em '{caminho}'. "
                "Rode `python scripts/autorizar_google.py` uma vez para gerá-lo."
            )
        try:
            return json.loads(caminho.read_text(encoding="utf-8"))
        except (ValueError, OSError) as erro:
            raise ErroCredencialGoogle(
                f"Token do Google em '{caminho}' está ilegível: {erro}"
            ) from erro

    def token(self) -> str:
        if self._access_token and time.time() < self._expira_em - MARGEM_EXPIRACAO:
            return self._access_token

        creds = self._credenciais()
        faltando = [
            campo
            for campo in ("refresh_token", "client_id", "client_secret")
            if not creds.get(campo)
        ]
        if faltando:
            raise ErroCredencialGoogle(
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
        if getattr(resposta, "status_code", 200) >= 400:
            # O corpo do erro do Google traz `error_description`, e nunca o
            # segredo enviado — pode ir para a mensagem sem vazar credencial.
            raise ErroCredencialGoogle(
                "O Google recusou o refresh token "
                f"({resposta.status_code}): {resposta.text[:200]}. "
                "Rode `python scripts/autorizar_google.py` para reautorizar."
            )
        corpo = resposta.json()
        self._access_token = corpo["access_token"]
        self._expira_em = time.time() + float(corpo.get("expires_in", 3600))
        return self._access_token


class TokenContaDeServico:
    """Assina um JWT com a chave da conta de serviço e obtém o access token.

    A assinatura RSA vem de `google.oauth2.service_account`, a mesma biblioteca
    que o utilitário `gcal.py` da operação já usa contra esta mesma chave —
    criptografia é o único pedaço que não vale reescrever. O import é preguiçoso
    para o projeto continuar instalável e testável sem `google-auth`.
    """

    descricao = "conta-de-servico"

    def __init__(self, caminho: str) -> None:
        self.caminho = caminho
        self._credenciais: Any | None = None

    def _carregar(self) -> Any:
        if self._credenciais is not None:
            return self._credenciais

        arquivo = Path(self.caminho)
        if not arquivo.is_file():
            raise ErroCredencialGoogle(
                f"Chave da conta de serviço não encontrada em '{arquivo}'. "
                "Aponte GOOGLE_SERVICE_ACCOUNT_PATH para o JSON da conta de serviço."
            )
        try:
            from google.oauth2 import service_account  # type: ignore[import-not-found]
        except ImportError as erro:  # pragma: no cover - depende do ambiente
            raise ErroCredencialGoogle(
                "A rota de conta de serviço precisa da biblioteca google-auth. "
                "Instale com `pip install google-auth` ou use GOOGLE_TOKEN_PATH."
            ) from erro

        try:
            self._credenciais = service_account.Credentials.from_service_account_file(
                str(arquivo), scopes=[ESCOPO]
            )
        except (ValueError, KeyError, OSError) as erro:
            raise ErroCredencialGoogle(
                f"Chave da conta de serviço em '{arquivo}' é inválida: {erro}"
            ) from erro
        return self._credenciais

    def token(self) -> str:
        credenciais = self._carregar()
        if credenciais.valid:
            return str(credenciais.token)

        from google.auth.transport.requests import (  # type: ignore[import-not-found]
            Request,
        )

        try:
            credenciais.refresh(Request())
        except Exception as erro:  # noqa: BLE001 — a lib levanta vários tipos
            raise ErroCredencialGoogle(
                f"O Google recusou a chave da conta de serviço: {erro}. "
                "Confira se a chave não foi revogada e se a Calendar API está "
                "habilitada no projeto."
            ) from erro
        return str(credenciais.token)


def escolher_autenticacao(config: Config, sessao: Any) -> Autenticacao:
    """Conta de serviço quando houver; senão, OAuth.

    A ordem não é arbitrária: a conta de serviço não depende de um humano para
    renovar consentimento, então é ela que sustenta a operação sem supervisão.
    """
    if config.google_service_account_path:
        return TokenContaDeServico(config.google_service_account_path)
    return TokenOAuth(config.google_token_path, sessao)


# ---------------------------------------------------------------------------
# Cliente
# ---------------------------------------------------------------------------


class ClienteGoogleCalendar:
    def __init__(
        self,
        config: Config,
        sessao: Any | None = None,
        autenticacao: Autenticacao | None = None,
        dormir: Any = time.sleep,
    ) -> None:
        exigir(config, "google_calendar")
        self.config = config
        self.sessao = sessao or requests.Session()
        self.auth = autenticacao or escolher_autenticacao(config, self.sessao)
        self._dormir = dormir
        self.fuso = ZoneInfo(config.timezone)

    def token(self) -> str:
        """Access token válido. Mantido no cliente por ser o que os testes olham."""
        return self.auth.token()

    # -- transporte ----------------------------------------------------------

    def _espera(self, tentativa: int, resposta: Any | None) -> float:
        """Recuo exponencial com sorteio, respeitando `Retry-After` quando vier.

        O sorteio (jitter) evita que várias instâncias reiniciadas juntas
        voltem a bater na API no mesmo instante.
        """
        if resposta is not None:
            cabecalho = getattr(resposta, "headers", None) or {}
            bruto = cabecalho.get("Retry-After") or cabecalho.get("retry-after")
            if bruto:
                try:
                    return min(float(bruto), ESPERA_MAXIMA)
                except (TypeError, ValueError):
                    pass
        return min(ESPERA_BASE * (2**tentativa), ESPERA_MAXIMA) + random.uniform(0, 0.3)

    @staticmethod
    def _detalhe(resposta: Any) -> str:
        """Mensagem de erro da API, sem eco de nada que fomos nós que mandamos."""
        try:
            corpo = resposta.json()
        except (ValueError, AttributeError):
            return str(getattr(resposta, "text", ""))[:200]
        erro = corpo.get("error") if isinstance(corpo, dict) else None
        if isinstance(erro, dict):
            return str(erro.get("message", ""))[:200] or json.dumps(erro)[:200]
        return json.dumps(corpo)[:200]

    def _chamar(self, metodo: str, caminho: str, **kwargs: Any) -> dict[str, Any]:
        """Uma chamada REST com timeout, retry com recuo e log.

        O log registra método, caminho, status, duração e tentativa. Nunca
        registra o header `Authorization` nem o corpo da credencial.
        """
        ultima: Exception | None = None

        for tentativa in range(TENTATIVAS):
            inicio = time.monotonic()
            try:
                resposta = self.sessao.request(
                    metodo,
                    f"{BASE}{caminho}",
                    headers={"Authorization": f"Bearer {self.token()}"},
                    timeout=TIMEOUT,
                    **kwargs,
                )
            except requests.RequestException as erro:
                # Timeout, DNS, conexão recusada: a API está inalcançável.
                ultima = ErroIndisponivelGoogle(
                    f"Google Calendar inalcançável em {caminho}: {erro}"
                )
                log.warning(
                    "google_calendar %s %s falhou na rede em %.0fms (tentativa %d/%d): %s",
                    metodo, caminho, (time.monotonic() - inicio) * 1000,
                    tentativa + 1, TENTATIVAS, erro,
                )
                if tentativa + 1 < TENTATIVAS:
                    self._dormir(self._espera(tentativa, None))
                    continue
                raise ultima from erro

            duracao = (time.monotonic() - inicio) * 1000
            status = getattr(resposta, "status_code", 200)
            log.info(
                "google_calendar %s %s -> %s em %.0fms (tentativa %d/%d)",
                metodo, caminho, status, duracao, tentativa + 1, TENTATIVAS,
            )

            if status < 400:
                return resposta.json() if getattr(resposta, "content", None) else {}

            detalhe = self._detalhe(resposta)

            if status in (401, 403):
                # Não adianta repetir: ou a credencial caiu, ou a agenda não
                # foi compartilhada com esta conta de serviço.
                raise ErroCredencialGoogle(
                    f"Google Calendar recusou a credencial ({status}) em {caminho}: "
                    f"{detalhe}. Confira se a agenda foi compartilhada com a conta "
                    "usada e se a Calendar API está habilitada."
                )
            if status == 404:
                raise ErroGoogleCalendar(
                    f"Google Calendar não encontrou o recurso (404) em {caminho}: {detalhe}"
                )
            if status not in STATUS_RETENTAVEIS:
                raise ErroGoogleCalendar(
                    f"Google Calendar respondeu {status} em {caminho}: {detalhe}"
                )

            ultima = (
                ErroLimiteGoogle(
                    f"Limite de requisições do Google Calendar em {caminho}: {detalhe}"
                )
                if status == 429
                else ErroIndisponivelGoogle(
                    f"Google Calendar indisponível ({status}) em {caminho}: {detalhe}"
                )
            )
            if tentativa + 1 < TENTATIVAS:
                self._dormir(self._espera(tentativa, resposta))
                continue
            raise ultima

        assert ultima is not None  # pragma: no cover - o laço sempre decide antes
        raise ultima

    # -- operações -----------------------------------------------------------

    @property
    def _calendario(self) -> str:
        return self.config.google_calendar_id or "primary"

    def _instante(self, data: str, hora: str) -> datetime:
        """Data e hora locais no fuso do sistema, sempre com deslocamento explícito."""
        return datetime.fromisoformat(f"{data}T{hora}:00").replace(tzinfo=self.fuso)

    def janela(self, data: str, hora: str, duracao_minutos: int) -> tuple[str, str]:
        """Início e fim em RFC 3339 com o deslocamento do fuso (ex.: -03:00).

        O deslocamento sai do banco de fusos, não de uma constante: hoje o
        Brasil é UTC-03:00 o ano inteiro, e se o horário de verão voltar a
        janela continua certa sem ninguém lembrar de mudar o código.
        """
        inicio = self._instante(data, hora)
        fim = inicio + timedelta(minutes=duracao_minutos)
        return inicio.isoformat(), fim.isoformat()

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
            inicio, fim = self.janela(data, hora, duracao_minutos)
            corpo["start"] = {"dateTime": inicio, "timeZone": self.config.timezone}
            corpo["end"] = {"dateTime": fim, "timeZone": self.config.timezone}
        else:
            # Dia inteiro no Google é meia-aberto: o fim é o dia seguinte.
            fim = (datetime.fromisoformat(data) + timedelta(days=1)).date().isoformat()
            corpo["start"] = {"date": data}
            corpo["end"] = {"date": fim}
        return corpo

    def ocupados(self, inicio_iso: str, fim_iso: str) -> list[dict[str, str]]:
        """Faixas ocupadas da agenda no intervalo, pelo endpoint freeBusy."""
        resultado = self._chamar(
            "POST",
            "/freeBusy",
            json={
                "timeMin": inicio_iso,
                "timeMax": fim_iso,
                "timeZone": self.config.timezone,
                "items": [{"id": self._calendario}],
            },
        )
        calendarios = resultado.get("calendars", {})
        dados = calendarios.get(self._calendario, {})
        if dados.get("errors"):
            raise ErroGoogleCalendar(
                f"freeBusy recusou a agenda '{self._calendario}': {dados['errors']}"
            )
        return list(dados.get("busy", []))

    def conflitos(
        self, data: str, hora: str, duracao_minutos: int = 60
    ) -> list[dict[str, str]]:
        """Compromissos que colidem com o horário pedido. Lista vazia é caminho livre."""
        inicio, fim = self.janela(data, hora, duracao_minutos)
        return self.ocupados(inicio, fim)

    def criar_evento(
        self,
        titulo: str,
        data: str,
        hora: str | None = None,
        duracao_minutos: int = 60,
        descricao: str = "",
        permitir_conflito: bool = False,
    ) -> str:
        """Cria um evento na agenda e devolve o id.

        Com hora definida, consulta a agenda antes e recusa se o horário já
        estiver ocupado. Evento de dia inteiro não é checado: ele não disputa
        horário com ninguém.
        """
        if hora and not permitir_conflito:
            ocupados = self.conflitos(data, hora, duracao_minutos)
            if ocupados:
                log.warning(
                    "google_calendar recusou criar '%s' em %s %s: %d conflito(s)",
                    titulo, data, hora, len(ocupados),
                )
                raise ConflitoDeAgenda(ocupados)

        corpo = self.montar_evento(titulo, data, hora, duracao_minutos, descricao)
        resultado = self._chamar(
            "POST", f"/calendars/{self._calendario}/events", json=corpo
        )
        evento_id = str(resultado.get("id", ""))
        log.info("google_calendar criou evento %s ('%s' em %s)", evento_id, titulo, data)
        return evento_id

    def listar_eventos(
        self, inicio_iso: str, fim_iso: str, limite: int = 50
    ) -> list[dict[str, Any]]:
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

    def proximos_dias(self, dias: int = 7, limite: int = 50) -> list[dict[str, Any]]:
        """Agenda dos próximos N dias, contados no fuso configurado."""
        agora = datetime.now(self.fuso)
        return self.listar_eventos(
            agora.isoformat(), (agora + timedelta(days=dias)).isoformat(), limite
        )

    def apagar_evento(self, evento_id: str) -> None:
        self._chamar("DELETE", f"/calendars/{self._calendario}/events/{evento_id}")
        log.info("google_calendar apagou evento %s", evento_id)

    def verificar(self) -> bool:
        """Health check: a credencial abre a agenda configurada?"""
        self._chamar("GET", f"/calendars/{self._calendario}")
        return True
