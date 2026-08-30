import json
from sop.dashboard_server import Cache, carregar

def prop(t,v): return {"type":t,t:v}
def page(title="X",demo=True):
 return {"properties":{"Dados de demonstração":{"checkbox":demo},"Lançamento":prop("title",[{"plain_text":title}]),"Tipo":{"select":{"name":"Despesa"}},"Data":{"date":{"start":"2035-01-01"}},"Categoria":{"select":{"name":"Demo"}},"Status":{"select":{"name":"Realizado"}},"Valor":{"number":10}}}
class Client:
 def __init__(self): self.n=0
 def _chamar(self,_m,path,_b):
  self.n+=1
  if "lanc" in path:return {"results":[page(),page("REAL",False)]}
  if "cust" in path:return {"results":[]}
  return {"results":[]}
def test_endpoint_omite_nao_demo(monkeypatch):
 monkeypatch.setenv("SABIA_DEMO","1"); d=carregar(Client(),["lanc","cust","orc"])
 assert len(d["lancamentos"])==1 and d["lancamentos"][0]["nome"]=="X"
def test_cache_curto_e_etag_estavel():
 calls=[]; c=Cache(lambda:(calls.append(1) or {"ambiente":"DEMO"}),ttl=15)
 a,e1=c.obter(1); b,e2=c.obter(10); c.obter(20)
 assert len(calls)==2 and a==b and e1==e2 and json.loads(a)["ambiente"]=="DEMO"
