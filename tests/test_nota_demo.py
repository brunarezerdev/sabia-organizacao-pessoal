from decimal import Decimal
from pathlib import Path
import pytest

from sop.nota_demo import NotaAmbigua, aplicar, extrair_texto, parsear_texto, resumo

FIXTURE = Path(__file__).parent / "fixtures" / "nota_demo.txt"


class Banco:
    def __init__(self, falhar=False):
        self.lancamentos = {}
        self.ingredientes = {"arroz-integral": {"id": "arroz", "quantidade": Decimal("1"), "status": "Lista de Compras"}}
        self.falhar = falhar
        self.arquivados = []
    def achar_lancamento(self, fp): return self.lancamentos.get(fp)
    def criar_lancamento(self, nota): self.lancamentos[nota.fingerprint] = {"id": "lanc"}; return "lanc"
    def achar_ingrediente(self, chave): return self.ingredientes.get(chave)
    def criar_ingrediente(self, item):
        if self.falhar: raise OSError("falha simulada")
        self.ingredientes[item.chave] = {"id": item.chave, "quantidade": item.quantidade, "status": "No Estoque"}; return item.chave
    def atualizar_ingrediente(self, pagina, item): pagina["quantidade"] += item.quantidade; pagina["status"] = "No Estoque"
    def restaurar_ingrediente(self, pagina): pagina.update(quantidade=Decimal("1"), status="Lista de Compras")
    def arquivar(self, pagina_id): self.arquivados.append(pagina_id); self.lancamentos.clear()


def test_fixture_privacidade_normalizacao_e_resumo():
    texto, metodo = extrair_texto(FIXTURE)
    nota = parsear_texto(texto)
    assert metodo == "texto" and nota.total == Decimal("32.00")
    assert [i.chave for i in nota.itens] == ["arroz-integral", "banana-prata"]
    assert "000" not in nota.fingerprint
    banco = Banco(); resultado = aplicar(nota, banco)
    assert banco.ingredientes["arroz-integral"]["quantidade"] == 3
    assert banco.ingredientes["arroz-integral"]["status"] == "No Estoque"
    assert "R$ 32.00" in resumo(resultado)
    assert aplicar(nota, banco)["duplicada"] is True


def test_rollback_compensa_lancamento_e_estoque():
    nota = parsear_texto(FIXTURE.read_text())
    banco = Banco(falhar=True)
    with pytest.raises(RuntimeError, match="alterações desfeitas"):
        aplicar(nota, banco)
    assert not banco.lancamentos
    assert banco.ingredientes["arroz-integral"] == {"id": "arroz", "quantidade": Decimal("1"), "status": "Lista de Compras"}


def test_recusa_unidade_ambigua():
    with pytest.raises(NotaAmbigua):
        parsear_texto("DATA: 2035-01-01\nITEM: Leite | 1 CAIXA | R$ 5,00")
