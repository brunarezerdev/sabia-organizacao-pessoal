import pytest
from sop.dashboard_financeiro import filtrar, resumir, validar_demo
LINHAS=[{"data":"2035-01-01","tipo":"Receita","categoria":"A","status":"Realizado","valor":100},{"data":"2035-01-02","tipo":"Despesa","categoria":"B","status":"Previsto","valor":30}]
def test_calculos_e_filtros():
 assert resumir(LINHAS,[{"limite":80}]) == {"receitas":100,"despesas":30,"saldo":70,"orcamento":80,"categorias":{"B":30.0},"evolucao":{"2035-01":70.0}}
 assert filtrar(LINHAS,tipo="Despesa",status="Previsto") == [LINHAS[1]]
def test_recusa_nao_demo():
 with pytest.raises(PermissionError): validar_demo({"properties":{"Dados de demonstração":{"checkbox":False}}})
 validar_demo({"properties":{"Dados de demonstração":{"checkbox":True}}})
