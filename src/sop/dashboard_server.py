"""Servidor local, somente leitura, do dashboard financeiro DEMO."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import hashlib, json, os, time
from pathlib import Path
from .config import Config
from .integracoes.notion import ClienteNotion
ROOT=Path(__file__).resolve().parents[2]/"dashboard"; TTL=15
def text(p): return "".join(x.get("plain_text","") for x in p.get(p.get("type",""),[]) or [])
def demo(p): return p.get("properties",{}).get("Dados de demonstração",{}).get("checkbox") is True
def carregar(cliente=None,ids=None):
 if os.environ.get("SABIA_DEMO")!="1": raise RuntimeError("ambiente DEMO obrigatório")
 ids=ids or [os.environ.get(x,"") for x in ("NOTION_LANCAMENTOS_DEMO_ID","NOTION_CUSTOS_DEMO_ID","NOTION_ORCAMENTO_DEMO_ID")]
 if not all(ids): raise RuntimeError("fontes DEMO ausentes")
 c=cliente or ClienteNotion(Config.do_ambiente()); grupos=[]
 for db in ids: grupos.append([p for p in c._chamar("POST",f"/databases/{db}/query",{"page_size":100}).get("results",[]) if demo(p)])
 lanc=[]
 for p in grupos[0]:
  x=p["properties"]; lanc.append({"nome":text(x["Lançamento"]),"tipo":(x["Tipo"].get("select")or{}).get("name",""),"data":(x["Data"].get("date")or{}).get("start",""),"categoria":(x["Categoria"].get("select")or{}).get("name","Sem categoria"),"status":(x["Status"].get("select")or{}).get("name",""),"valor":x["Valor"].get("number")or 0})
 custos=[{"nome":text(p["properties"]["Custo fixo / Assinatura"]),"valor":p["properties"]["Valor previsto"].get("number")or 0} for p in grupos[1]]
 orcs=[{"categoria":text(p["properties"]["Categoria"]),"limite":p["properties"]["Limite planejado"].get("number")or 0,"realizado":p["properties"]["Realizado (manual no DEMO)"].get("number")or 0} for p in grupos[2]]
 return {"ambiente":"DEMO","lancamentos":lanc,"custos":custos,"orcamentos":orcs}
class Cache:
 def __init__(self,fonte=carregar,ttl=TTL): self.fonte=fonte; self.ttl=ttl; self.valor=None; self.em=0
 def obter(self,agora=None):
  agora=time.monotonic() if agora is None else agora
  if self.valor is None or agora-self.em>=self.ttl: self.valor=self.fonte(); self.em=agora
  corpo=json.dumps(self.valor,ensure_ascii=False,separators=(",",":")).encode(); return corpo,hashlib.sha256(corpo).hexdigest()
CACHE=Cache()
class Handler(SimpleHTTPRequestHandler):
 def __init__(self,*a,**kw): super().__init__(*a,directory=str(ROOT),**kw)
 def do_GET(self):
  if self.path.split("?",1)[0]!="/api/dashboard": return super().do_GET()
  try: corpo,etag=CACHE.obter()
  except Exception: corpo=b'{"erro":"Dados temporariamente indisponiveis."}'; self.send_response(503)
  else:
   if self.headers.get("If-None-Match")==etag: self.send_response(304); self.end_headers(); return
   self.send_response(200); self.send_header("ETag",etag)
  self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Cache-Control","private, max-age=15"); self.send_header("X-Content-Type-Options","nosniff"); self.send_header("Content-Security-Policy","default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors https://www.notion.so https://notion.so"); self.end_headers(); self.wfile.write(corpo)
def main(): ThreadingHTTPServer(("127.0.0.1",int(os.environ.get("DASHBOARD_PORT","8765"))),Handler).serve_forever()
if __name__=="__main__": main()
