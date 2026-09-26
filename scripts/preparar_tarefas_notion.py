#!/usr/bin/env python3
"""Acrescenta e valida a Matriz de Eisenhower na base de tarefas do Notion."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sop.config import Config  # noqa: E402
from sop.integracoes.notion import ClienteNotion  # noqa: E402
from sop.prioridades import preparar_base  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tarefas", required=True, help="id da base Prazos e tarefas")
    args = parser.parse_args()

    cliente = ClienteNotion(Config.do_ambiente())
    preparar_base(cliente, args.tarefas)
    print("Base Prazos e tarefas pronta: quadrantes e datas conferidos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
