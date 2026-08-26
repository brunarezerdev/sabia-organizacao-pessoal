#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Reinicia o gateway do OpenClaw e espera ele voltar a atender.
#
#     bash sabia/reiniciar_gateway.sh
#
# O gateway roda como serviço do usuário `aria`, não do sistema:
#
#     ~/.config/systemd/user/openclaw-gateway.service   (enabled, Restart=always)
#
# Ou seja: NÃO precisa de root, e `sudo systemctl restart openclaw-gateway` não acha a unit.
# O que precisa é do barramento do usuário. Uma sessão não interativa (cron, tmux herdado,
# subagente) chega sem XDG_RUNTIME_DIR e sem DBUS_SESSION_BUS_ADDRESS, e aí o systemctl falha
# com "Failed to connect to bus". As duas linhas abaixo resolvem isso.
#
# Reiniciar é necessário depois de trocar SOUL.md ou identidade: o gateway lê a alma no início
# da sessão e mantém em memória.
#
# Atenção: systemd/openclaw-gateway.service, na raiz do repositório, é OUTRO arquivo. É um
# modelo de unit de sistema, apontando pra /root, que nunca foi instalado nesta VPS. Quem manda
# aqui é a unit de usuário acima.
# ---------------------------------------------------------------------------

set -euo pipefail

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$RAIZ/node_modules/openclaw/dist/index.js"
PORTA="${OPENCLAW_GATEWAY_PORT:-18789}"

echo "-> reiniciando openclaw-gateway (serviço do usuário $(id -un))"
systemctl --user restart openclaw-gateway

# Restart=always faz o systemd devolver o controle antes do gateway estar pronto pra atender.
# Sem esta espera, o comando seguinte bate numa porta que ainda não escuta.
echo -n "-> esperando o gateway atender em 127.0.0.1:$PORTA "
for _ in $(seq 1 40); do
  if node "$CLI" health >/dev/null 2>&1; then
    echo " ok"
    node "$CLI" health
    exit 0
  fi
  echo -n "."
  sleep 1
done

echo " TEMPO ESGOTADO"
echo
echo "O gateway não voltou a atender em 40s. Diagnóstico:"
echo "  systemctl --user status openclaw-gateway"
echo "  journalctl --user -u openclaw-gateway -n 50 --no-pager"
exit 1
