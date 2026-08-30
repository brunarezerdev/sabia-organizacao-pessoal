"""Cliente da Bot API do Telegram — canal de captura de mensagens.

Autenticação: token de bot no caminho da URL, obtido do @BotFather e lido de
`TELEGRAM_BOT_TOKEN`. O token nunca aparece em log — o método `_url` é o único
lugar que o toca.

Segurança: só mensagens vindas do `chat_id` autorizado são convertidas em
`Mensagem`. Qualquer outra origem é descartada silenciosamente, porque um bot
do Telegram é endereçável por qualquer pessoa que descubra seu nome.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from pathlib import Path

import requests

from ..config import Config, exigir
from ..modelos import Mensagem

BASE = "https://api.telegram.org"
TIMEOUT = 30


class ClienteTelegram:
    def __init__(self, config: Config, sessao: Any | None = None) -> None:
        exigir(config, "telegram")
        self.config = config
        self.sessao = sessao or requests.Session()

    def _url(self, metodo: str) -> str:
        return f"{BASE}/bot{self.config.telegram_token}/{metodo}"

    def _chamar(self, metodo: str, **params: Any) -> dict[str, Any]:
        resposta = self.sessao.post(self._url(metodo), json=params, timeout=TIMEOUT)
        resposta.raise_for_status()
        corpo = resposta.json()
        if not corpo.get("ok"):
            # A descrição do Telegram não contém o token; é seguro propagar.
            raise RuntimeError(f"Telegram recusou {metodo}: {corpo.get('description')}")
        return corpo.get("result", {})

    # -- leitura -------------------------------------------------------------

    def buscar_atualizacoes(self, offset: int | None = None, timeout: int = 25) -> list[dict[str, Any]]:
        """Long polling: devolve as atualizações desde `offset`."""
        params: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        resultado = self._chamar("getUpdates", **params)
        return resultado if isinstance(resultado, list) else []

    def autorizada(self, update: dict[str, Any]) -> bool:
        """Só o chat configurado pode falar com o sistema."""
        chat_id = str(
            update.get("message", {}).get("chat", {}).get("id", "")
        )
        return bool(chat_id) and chat_id == str(self.config.telegram_chat_autorizado)

    def para_mensagem(self, update: dict[str, Any]) -> Mensagem | None:
        """Converte um update do Telegram em `Mensagem`, se for autorizado."""
        if not self.autorizada(update):
            return None
        bruta = update.get("message", {})
        texto = (bruta.get("text") or bruta.get("caption") or "").strip()
        if not texto:
            return None
        instante = bruta.get("date")
        recebida = (
            datetime.fromtimestamp(instante, tz=timezone.utc).isoformat()
            if isinstance(instante, (int, float))
            else ""
        )
        return Mensagem(
            id=str(bruta.get("message_id", update.get("update_id", ""))),
            texto=texto,
            autor=str(bruta.get("from", {}).get("first_name", "")),
            canal="telegram",
            recebida_em=recebida,
        )

    def mensagens(self, offset: int | None = None) -> tuple[list[Mensagem], int | None]:
        """Busca atualizações e devolve as mensagens válidas + o próximo offset."""
        atualizacoes = self.buscar_atualizacoes(offset=offset)
        mensagens = [
            m for m in (self.para_mensagem(u) for u in atualizacoes) if m is not None
        ]
        proximo = (
            max(u["update_id"] for u in atualizacoes) + 1 if atualizacoes else offset
        )
        return mensagens, proximo

    # -- escrita -------------------------------------------------------------

    def responder(self, chat_id: str | int, texto: str, responder_a: int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"chat_id": chat_id, "text": texto}
        if responder_a is not None:
            params["reply_to_message_id"] = responder_a
        return self._chamar("sendMessage", **params)

    def confirmar(self, texto: str) -> dict[str, Any]:
        """Responde no chat autorizado — usado para devolver o resultado."""
        return self.responder(self.config.telegram_chat_autorizado, texto)

    def baixar_anexo(self, update: dict[str, Any], destino: Path) -> Path:
        """Baixa foto/PDF de update autorizado sem registrar URL nem token."""
        if not self.autorizada(update):
            raise PermissionError("origem do anexo não autorizada")
        msg = update.get("message", {})
        documento = msg.get("document") or {}
        fotos = msg.get("photo") or []
        if documento and documento.get("mime_type") not in {"application/pdf", "image/jpeg", "image/png"}:
            raise ValueError("tipo de anexo não aceito")
        file_id = documento.get("file_id") or (fotos[-1].get("file_id") if fotos else "")
        if not file_id:
            raise ValueError("mensagem sem foto ou PDF")
        info = self._chamar("getFile", file_id=file_id)
        caminho = info.get("file_path", "")
        if not caminho:
            raise RuntimeError("Telegram não devolveu o caminho do anexo")
        resposta = self.sessao.get(f"{BASE}/file/bot{self.config.telegram_token}/{caminho}", timeout=TIMEOUT)
        resposta.raise_for_status()
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(resposta.content)
        return destino
