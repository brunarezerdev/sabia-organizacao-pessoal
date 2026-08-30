#!/usr/bin/env python3
"""Processa uma nota já baixada pelo canal Telegram/OpenClaw."""
import argparse, json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sop.config import Config
from sop.integracoes.notion import ClienteNotion
from sop.integracoes.notion_nota_demo import BancoNotionNotaDemo
from sop.nota_demo import aplicar, extrair_texto, parsear_texto, resumo

p = argparse.ArgumentParser(); p.add_argument("arquivo", type=Path); p.add_argument("--json", action="store_true")
a = p.parse_args()
texto, metodo = extrair_texto(a.arquivo)
nota = parsear_texto(texto)
config = Config.do_ambiente()
banco = BancoNotionNotaDemo(ClienteNotion(config), os.environ.get("NOTION_LANCAMENTOS_DEMO_ID", ""), os.environ.get("NOTION_INGREDIENTES_DEMO_ID", ""))
r = aplicar(nota, banco); r["parser"] = metodo
print(json.dumps(r, ensure_ascii=False) if a.json else resumo(r))
