#!/usr/bin/env python3
"""Verifica a configuração e testa a conexão com cada API configurada.

Diferente de `python -m sop diagnostico`, que só olha as variáveis, este script
efetivamente bate nas APIs para confirmar que as credenciais funcionam.

    python scripts/verificar_config.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sop.agentes import carregar_registro  # noqa: E402
from sop.config import Config  # noqa: E402


def verificar_telegram(config: Config) -> tuple[bool, str]:
    from sop.integracoes.telegram import ClienteTelegram

    cliente = ClienteTelegram(config)
    info = cliente._chamar("getMe")
    return True, f"conectado como @{info.get('username', '?')}"


def verificar_notion(config: Config) -> tuple[bool, str]:
    from sop.integracoes.notion import ClienteNotion

    cliente = ClienteNotion(config)
    cliente.verificar()
    return True, "database acessível pela integração"


def verificar_google(config: Config) -> tuple[bool, str]:
    from sop.integracoes.google_calendar import ClienteGoogleCalendar

    cliente = ClienteGoogleCalendar(config)
    cliente.token()
    return True, f"token válido para o calendário '{config.google_calendar_id}'"


def verificar_ia(config: Config) -> tuple[bool, str]:
    from sop.integracoes.ia import ClassificadorAnthropic, criar_adaptador

    adaptador = criar_adaptador(config)
    if not isinstance(adaptador, ClassificadorAnthropic):
        return False, "sem chave ou sem o pacote `anthropic` — usando heurística"
    return True, f"modelo {config.anthropic_model}"


VERIFICADORES = {
    "telegram": verificar_telegram,
    "notion": verificar_notion,
    "google_calendar": verificar_google,
    "ia": verificar_ia,
}


def main() -> int:
    config = Config.do_ambiente()
    print("Verificando as integrações do Sistema Operacional Pessoal\n")

    problemas = 0
    for nome, verificador in VERIFICADORES.items():
        faltantes = config.faltando(nome)
        if faltantes:
            print(f"  [ ] {nome:<16} não configurada — falta {', '.join(faltantes)}")
            continue
        try:
            ok, detalhe = verificador(config)
        except Exception as erro:  # noqa: BLE001
            print(f"  [!] {nome:<16} configurada mas falhou: {erro}")
            problemas += 1
            continue
        marca = "x" if ok else " "
        print(f"  [{marca}] {nome:<16} {detalhe}")

    registro = carregar_registro()
    print(f"\n  agentes: {len(registro)} carregados ({', '.join(registro.nomes())})")

    if problemas:
        print(f"\n{problemas} integração(ões) com credencial inválida.")
        return 1
    print("\nNenhuma credencial inválida encontrada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
