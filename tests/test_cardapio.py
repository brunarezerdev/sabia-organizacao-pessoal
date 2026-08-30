from datetime import date

import pytest

from sop.cardapio import (
    PROP_AUTOMATICO,
    BaseNaoCompartilhada,
    sincronizar_lista_compras,
)


def pagina(item_id, propriedades):
    return {"id": item_id, "properties": propriedades}


class NotionFalso:
    def __init__(self):
        self.bases = {
            "planejamento": [pagina("p1", {
                "Date": {"date": {"start": "2026-08-31"}},
                "📝 Recipes": {"relation": [{"id": "r1"}]},
            })],
            "receitas": [pagina("r1", {
                "🥕 Ingredients": {"relation": [{"id": "i1"}, {"id": "i2"}]},
            })],
            "ingredientes": [
                pagina("i1", {"Status": {"select": {"name": "Fora de Estoque"}}}),
                pagina("i2", {"Status": {"select": {"name": "No Estoque"}}}),
                pagina("i3", {
                    "Status": {"select": {"name": "Lista de Compras"}},
                    PROP_AUTOMATICO: {"checkbox": True},
                }),
            ],
        }
        self.propriedades = {"Status": {"type": "select"}}
        self.patches = []

    def consultar_database(self, database_id, filtro=None, limite=100):
        return self.bases[database_id]

    def _chamar(self, metodo, caminho, corpo=None):
        if metodo == "GET" and caminho in ("/databases/planejamento", "/databases/receitas"):
            return {"properties": {}}
        if metodo == "GET" and caminho == "/databases/ingredientes":
            return {"properties": self.propriedades}
        if metodo == "PATCH" and caminho == "/databases/ingredientes":
            self.propriedades[PROP_AUTOMATICO] = {"type": "checkbox"}
            return {"properties": self.propriedades}
        if metodo == "PATCH" and caminho.startswith("/pages/"):
            item_id = caminho.rsplit("/", 1)[-1]
            item = next(x for x in self.bases["ingredientes"] if x["id"] == item_id)
            item["properties"].update(corpo["properties"])
            self.patches.append((item_id, corpo))
            return item
        raise AssertionError((metodo, caminho, corpo))


def test_base_sem_compartilhamento_explica_o_que_fazer():
    """O 404 do Notion não distingue base inexistente de base sem permissão."""
    notion = NotionFalso()
    original = notion._chamar

    def negar(metodo, caminho, corpo=None):
        if metodo == "GET" and caminho == "/databases/receitas":
            raise RuntimeError("Notion respondeu 404 em /databases/receitas: ...")
        return original(metodo, caminho, corpo)

    notion._chamar = negar

    with pytest.raises(BaseNaoCompartilhada) as erro:
        sincronizar_lista_compras(
            notion, "planejamento", "receitas", "ingredientes", date(2026, 9, 2)
        )

    assert "Receitas" in str(erro.value)
    assert "Conexões" in str(erro.value)
    assert notion.patches == []


def test_erro_que_nao_e_de_permissao_sobe_intacto():
    notion = NotionFalso()
    original = notion._chamar

    def falhar(metodo, caminho, corpo=None):
        if metodo == "GET" and caminho == "/databases/planejamento":
            raise RuntimeError("Notion respondeu 500 em /databases/planejamento: ...")
        return original(metodo, caminho, corpo)

    notion._chamar = falhar

    with pytest.raises(RuntimeError) as erro:
        sincronizar_lista_compras(
            notion, "planejamento", "receitas", "ingredientes", date(2026, 9, 2)
        )

    assert not isinstance(erro.value, BaseNaoCompartilhada)


def test_lista_consolida_receitas_considera_estoque_e_remove_item_antigo():
    notion = NotionFalso()

    resultado = sincronizar_lista_compras(
        notion, "planejamento", "receitas", "ingredientes", date(2026, 9, 2)
    )

    assert resultado.para_comprar == 1
    assert resultado.em_estoque == 1
    assert resultado.adicionados == 1
    assert resultado.removidos == 1
    assert [item_id for item_id, _ in notion.patches] == ["i1", "i3"]
    assert notion.bases["ingredientes"][0]["properties"][PROP_AUTOMATICO]["checkbox"]
    assert notion.bases["ingredientes"][1]["properties"]["Status"]["select"]["name"] == "No Estoque"
    assert notion.bases["ingredientes"][2]["properties"]["Status"]["select"]["name"] == "Fora de Estoque"


def test_rodar_duas_vezes_nao_duplica_nem_regrava():
    notion = NotionFalso()
    sincronizar_lista_compras(
        notion, "planejamento", "receitas", "ingredientes", date(2026, 9, 2)
    )
    notion.patches.clear()

    resultado = sincronizar_lista_compras(
        notion, "planejamento", "receitas", "ingredientes", date(2026, 9, 2)
    )

    assert resultado.para_comprar == 1
    assert resultado.adicionados == 0
    assert resultado.removidos == 0
    assert notion.patches == []


def test_estoque_editado_por_pessoa_nao_e_desfeito():
    notion = NotionFalso()
    item = notion.bases["ingredientes"][2]
    item["properties"]["Status"] = {"select": {"name": "No Estoque"}}

    sincronizar_lista_compras(
        notion, "planejamento", "receitas", "ingredientes", date(2026, 9, 2)
    )

    assert item["properties"]["Status"]["select"]["name"] == "No Estoque"
    assert item["properties"][PROP_AUTOMATICO]["checkbox"] is False


def test_item_ja_colocado_manualmente_na_lista_nao_muda_de_dono():
    notion = NotionFalso()
    item = notion.bases["ingredientes"][0]
    item["properties"]["Status"] = {"select": {"name": "Lista de Compras"}}

    sincronizar_lista_compras(
        notion, "planejamento", "receitas", "ingredientes", date(2026, 9, 2)
    )

    assert PROP_AUTOMATICO not in item["properties"]
    assert all(item_id != "i1" for item_id, _ in notion.patches)
