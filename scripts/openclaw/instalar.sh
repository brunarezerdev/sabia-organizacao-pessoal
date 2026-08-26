#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Instala o OpenClaw CLI e prepara a pasta de configuração.
#
#     bash scripts/openclaw/instalar.sh
#
# Roda uma vez por máquina. Em Ubuntu/Debian precisa de root (instala pacotes
# de sistema); em macOS roda como usuário normal.
#
# Adaptado de bootstrap.sh do repositório de referência (MIT) — ver o crédito
# em README.md. O que mudou: só a instalação do runtime, sem baixar agentes de
# outro projeto. Os agentes deste sistema vêm de `agentes/`, neste repositório.
# ---------------------------------------------------------------------------

set -euo pipefail

# Pin FIXO de propósito: o repositório de referência registra que `@latest`
# quebra o polling do Telegram. Não troque para `@latest` sem testar.
VERSAO_OPENCLAW="${VERSAO_OPENCLAW:-2026.6.5}"
OPENCLAW_BASE="${OPENCLAW_BASE:-$HOME/.openclaw}"

if [[ "$OSTYPE" == "darwin"* ]]; then
  SO="macos"
elif [[ -f /etc/os-release ]] && grep -qiE "ubuntu|debian" /etc/os-release; then
  SO="ubuntu"
else
  echo "ERRO: sistema não suportado. Precisa de Ubuntu/Debian ou macOS."
  echo "      O OpenClaw roda em Node; instale Node 22+ e rode:"
  echo "      npm install -g openclaw@$VERSAO_OPENCLAW"
  exit 1
fi

echo "== Instalando OpenClaw $VERSAO_OPENCLAW ($SO) =="

if [[ "$SO" == "ubuntu" ]]; then
  if [[ "$EUID" -ne 0 ]]; then
    echo "ERRO: no Ubuntu este script precisa de root."
    echo "Tente: sudo bash scripts/openclaw/instalar.sh"
    exit 1
  fi
  echo "-> pacotes de sistema"
  apt-get update -qq
  apt-get install -y -qq curl git jq ca-certificates python3 python3-venv
fi

if [[ "$SO" == "macos" ]]; then
  if [[ "$EUID" -eq 0 ]]; then
    echo "ERRO: no macOS NÃO rode como root."
    exit 1
  fi
  command -v brew >/dev/null || {
    echo "ERRO: Homebrew não encontrado. Instale em https://brew.sh"
    exit 1
  }
  brew install -q jq python@3.11 2>/dev/null || true
fi

# O OpenClaw exige Node 22.19 ou superior.
if ! command -v node >/dev/null 2>&1 || [[ "$(node -v)" != v2[2-9]* ]]; then
  echo "-> Node 22 via nvm"
  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
  export NVM_DIR="$HOME/.nvm"
  # shellcheck source=/dev/null
  [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
  nvm install 22
  nvm alias default 22
fi

echo "-> openclaw@$VERSAO_OPENCLAW"
npm install -g "openclaw@$VERSAO_OPENCLAW"

# systemd e cron não enxergam o PATH do nvm; o symlink resolve.
if [[ "$SO" == "ubuntu" ]]; then
  NPM_BIN="$(npm config get prefix)/bin"
  [ -x "$NPM_BIN/openclaw" ] && ln -sf "$NPM_BIN/openclaw" /usr/local/bin/openclaw
  [ -x "$NPM_BIN/../bin/node" ] && ln -sf "$(command -v node)" /usr/local/bin/node
fi

mkdir -p "$OPENCLAW_BASE"
chmod 700 "$OPENCLAW_BASE"

echo
echo "== Instalado =="
node --version     | xargs echo "  Node:    "
openclaw --version 2>/dev/null | head -1 | xargs echo "  OpenClaw:"
echo "  Config:   $OPENCLAW_BASE"
echo
echo "Próximos passos, nesta ordem:"
echo "  1. bash scripts/openclaw/configurar_provedor_openai.sh"
echo "  2. TG_BOT_TOKEN=... TG_USER_ID=... bash scripts/openclaw/configurar_telegram.sh"
echo "  3. python -m sop openclaw"
echo "  4. bash scripts/openclaw/registrar_agentes.sh"
echo
echo "Documentação oficial: https://docs.openclaw.ai"
