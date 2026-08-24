#!/usr/bin/env python3
"""Autorização OAuth do Google Agenda — roda uma única vez.

Abre o navegador, pede consentimento e grava um arquivo de token com o
`refresh_token`. Depois disso o cliente da aplicação renova o acesso sozinho,
sem nova interação.

Pré-requisitos:

  1. No Google Cloud Console, crie um projeto e habilite a Google Calendar API.
  2. Crie uma credencial OAuth 2.0 do tipo "Aplicativo para computador".
  3. Baixe o JSON e aponte GOOGLE_CREDENTIALS_PATH para ele no .env.
  4. Defina GOOGLE_TOKEN_PATH com o caminho onde o token será salvo
     (fora do repositório — .gitignore já bloqueia os padrões comuns).
  5. pip install google-auth-oauthlib

Uso:

    python scripts/autorizar_google.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sop.config import Config  # noqa: E402

ESCOPOS = ["https://www.googleapis.com/auth/calendar"]


def main() -> int:
    config = Config.do_ambiente()

    if not config.google_credentials_path:
        print("Defina GOOGLE_CREDENTIALS_PATH no .env antes de rodar.", file=sys.stderr)
        return 2
    if not config.google_token_path:
        print("Defina GOOGLE_TOKEN_PATH no .env antes de rodar.", file=sys.stderr)
        return 2

    origem = Path(config.google_credentials_path)
    if not origem.is_file():
        print(f"Credencial não encontrada em '{origem}'.", file=sys.stderr)
        return 2

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print(
            "Instale a dependência do fluxo interativo:\n"
            "    pip install google-auth-oauthlib",
            file=sys.stderr,
        )
        return 2

    fluxo = InstalledAppFlow.from_client_secrets_file(str(origem), ESCOPOS)
    credenciais = fluxo.run_local_server(port=0)

    if not credenciais.refresh_token:
        print(
            "O Google não devolveu refresh_token. Revogue o acesso do app em\n"
            "https://myaccount.google.com/permissions e rode de novo.",
            file=sys.stderr,
        )
        return 1

    destino = Path(config.google_token_path)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(
            {
                "refresh_token": credenciais.refresh_token,
                "client_id": credenciais.client_id,
                "client_secret": credenciais.client_secret,
                "scopes": ESCOPOS,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    destino.chmod(0o600)

    print(f"Token gravado em {destino} (permissão 600).")
    print("Confira com: python scripts/verificar_config.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
