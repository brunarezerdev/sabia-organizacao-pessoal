#!/usr/bin/env python3
"""Gera o snapshot público somente das três bases financeiras DEMO."""
import json, os, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from sop.config import Config
from sop.dashboard_financeiro import validar_demo
from sop.integracoes.notion import ClienteNotion

def text(p): return "".join(x.get("plain_text","") for x in p.get(p.get("type",""),[]) or [])
def rows(c,db): return c._chamar("POST",f"/databases/{db}/query",{"page_size":100}).get("results",[])
def main():
 if os.environ.get("SABIA_DEMO")!="1": raise SystemExit("SABIA_DEMO=1 obrigatório")
 ids=[os.environ.get(x,"") for x in ("NOTION_LANCAMENTOS_DEMO_ID","NOTION_CUSTOS_DEMO_ID","NOTION_ORCAMENTO_DEMO_ID")]
 if not all(ids): raise SystemExit("três ids DEMO obrigatórios")
 c=ClienteNotion(Config.do_ambiente()); grupos=[rows(c,x) for x in ids]
 for grupo in grupos:
  for p in grupo: validar_demo(p)
 lanc=[]
 for p in grupos[0]:
  x=p["properties"]; lanc.append({"nome":text(x["Lançamento"]),"tipo":(x["Tipo"].get("select")or{}).get("name",""),"data":(x["Data"].get("date")or{}).get("start",""),"categoria":(x["Categoria"].get("select")or{}).get("name","Sem categoria"),"status":(x["Status"].get("select")or{}).get("name",""),"valor":x["Valor"].get("number")or 0})
 custos=[]
 for p in grupos[1]:
  x=p["properties"]; custos.append({"nome":text(x["Custo fixo / Assinatura"]),"valor":x["Valor previsto"].get("number")or 0})
 orcs=[]
 for p in grupos[2]:
  x=p["properties"]; orcs.append({"categoria":text(x["Categoria"]),"limite":x["Limite planejado"].get("number")or 0,"realizado":x["Realizado (manual no DEMO)"].get("number")or 0})
 destino=Path(__file__).resolve().parents[1]/"dashboard/data.json"
 destino.write_text(json.dumps({"ambiente":"DEMO","lancamentos":lanc,"custos":custos,"orcamentos":orcs},ensure_ascii=False,separators=(",",":"))+"\n")
 print(f"snapshot DEMO: {len(lanc)} lançamentos, {len(custos)} custos, {len(orcs)} orçamentos")
if __name__=="__main__": main()
