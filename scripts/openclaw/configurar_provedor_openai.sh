#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Configura o provedor de IA: OpenAI, rota Codex.
#
#     bash scripts/openclaw/configurar_provedor_openai.sh
#
# COMO A AUTENTICAÇÃO FUNCIONA, e por que não tem chave:
#
#   No OpenClaw o provider chama-se `openai`. A rota Codex roda pelo plugin
#   codex nativo e autentica por OAuth com device-code, consumindo a cota da
#   assinatura ChatGPT Plus.
#
#   NÃO existe API key para o Codex CLI. Se você procurar por uma, não vai
#   achar — e nenhum passo deste projeto pede uma. A variável OPENAI_API_KEY
#   do .env.example serve a OUTRA coisa: a rota alternativa por API, que é
#   opcional e independente desta aqui.
#
# Adaptado de scripts/configure-gpt-codex.sh do repositório de referência
# (MIT) — crédito em README.md.
# ---------------------------------------------------------------------------

set -euo pipefail

MODELO="${OPENCLAW_MODELO:-openai/gpt-5.5}"

command -v openclaw >/dev/null 2>&1 || {
  echo "ERRO: CLI do openclaw não encontrado."
  echo "Rode antes: bash scripts/openclaw/instalar.sh"
  exit 1
}

cat <<'TXT'
== Login OAuth no provider openai (device-code, feito para VPS sem navegador) ==

Como funciona:
  1. O comando abaixo imprime uma URL e um código.
  2. Abra a URL no navegador do seu computador, já logado no ChatGPT Plus.
  3. Digite o código e autorize.
  4. O CLI da máquina detecta sozinho. Você não cola nada de volta aqui.

Não procure por "API key do Codex". Não existe: só OAuth pela assinatura.

TXT

read -r -p "Pressione ENTER para iniciar o login... " _

openclaw models auth login --provider openai --device-code || true

echo
echo "-> gateway.mode=local (obrigatório: sem isso o gateway não sobe)"
openclaw config set gateway.mode local
openclaw config validate || true

echo "-> definindo $MODELO como modelo primário"
openclaw models set "$MODELO"

echo "-> reiniciando o gateway"
systemctl restart openclaw-gateway 2>/dev/null || \
  echo "   (serviço ainda não instalado; veja systemd/openclaw-gateway.service)"

echo "-> validando"
openclaw models status --probe || true

echo
echo "OK. Provedor: openai · modelo: $MODELO · auth: OAuth (sem API key)."
echo "Para trocar de provedor depois, use 'openclaw models set <provider>/<modelo>'."
echo "O código deste projeto não precisa mudar: o backend de IA é intercambiável."
