#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Configura o canal Telegram do OpenClaw.
#
#     TG_BOT_TOKEN="123:AA..." TG_USER_ID="123456789" \
#       bash scripts/openclaw/configurar_telegram.sh
#
# O OpenClaw não tem um `channels add telegram`: o canal mora no
# openclaw.json. Mas esse arquivo NÃO se escreve à mão — na versão 2026.6.5 o
# schema valida na escrita e um bloco escrito manualmente quebra com
# "OpenClaw config is invalid". O caminho certo é `openclaw config patch`.
#
# `dmPolicy: allowlist` + o seu user_id em `allowFrom` é o mesmo controle de
# acesso que o cliente Python já faz com TELEGRAM_CHAT_ID_AUTORIZADO: só você
# fala com o bot. Um bot é endereçável por qualquer um que descubra o nome.
#
# Adaptado de scripts/setup-telegram.sh do repositório de referência (MIT) —
# crédito em README.md.
# ---------------------------------------------------------------------------

set -euo pipefail

if [[ -z "${TG_BOT_TOKEN:-}" || -z "${TG_USER_ID:-}" ]]; then
  echo "ERRO: TG_BOT_TOKEN e TG_USER_ID são obrigatórios."
  echo "Uso: TG_BOT_TOKEN=xxx TG_USER_ID=yyy bash $0"
  echo
  echo "  TG_BOT_TOKEN — o token que o @BotFather devolve"
  echo "  TG_USER_ID   — o seu id numérico, visto em /getUpdates"
  exit 1
fi

command -v openclaw >/dev/null 2>&1 || {
  echo "ERRO: CLI do openclaw não encontrado. Rode scripts/openclaw/instalar.sh"
  exit 1
}

PATCH="$(mktemp)"
# O arquivo temporário carrega o token, então some assim que o patch aplica.
trap 'rm -f "$PATCH"' EXIT
chmod 600 "$PATCH"

cat > "$PATCH" <<JSON
{
  "channels": {
    "telegram": {
      "enabled": true,
      "botToken": "$TG_BOT_TOKEN",
      "dmPolicy": "allowlist",
      "groupPolicy": "allowlist",
      "allowFrom": ["$TG_USER_ID"]
    }
  }
}
JSON

echo "-> aplicando o patch do canal (valida na escrita)"
openclaw config patch --file "$PATCH"

echo "-> gateway.mode=local (obrigatório)"
openclaw config set gateway.mode local
openclaw config validate || true

echo "-> reiniciando o gateway"
systemctl restart openclaw-gateway 2>/dev/null || \
  echo "   (serviço ainda não instalado; veja systemd/openclaw-gateway.service)"

echo "-> diagnóstico"
openclaw doctor || true

echo
echo "OK. Telegram configurado com allowlist. Mande /start para o seu bot."
