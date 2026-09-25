"""Da leitura da NFC-e até a `Nota` que vai para o Notion.

O que estes testes protegem é a regra de não inventar: uma nota cujos números
fecham mas cujo nome de produto não foi lido não pode virar linha na Despensa
com nome chutado. Ela volta pedindo confirmação, e só depois disso é aplicada.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from sop import nfce, nota_demo
from sop.nota_demo import NomesIlegiveis, NotaAmbigua

from test_nfce import carregar

FIXTURES = Path(__file__).parent / "fixtures"


def leitura(nome: str) -> nfce.LeituraNFCe:
    return nfce.parsear(carregar(nome))


def test_pdf_limpo_vira_nota_sem_perguntar_nada():
    nota = nota_demo._nota_de_leitura(leitura("nfce_pdf.txt"))
    assert nota.data.isoformat() == "2026-04-04"
    assert nota.total == Decimal("39.47")
    assert [i.chave for i in nota.itens] == [
        "aspargo-branco-mercatto-205g",
        "mostarda-hemmer-dijon-200g",
    ]


def test_foto_desbotada_pede_confirmacao_em_vez_de_chutar():
    with pytest.raises(NomesIlegiveis) as erro:
        nota_demo._nota_de_leitura(leitura("nfce_ocr_foto.txt"))
    assert erro.value.leitura.total_declarado == Decimal("39.47")
    assert "39.47" in str(erro.value)
    # O que falta vem discriminado por item, para dar o que perguntar.
    assert "falta nome" in str(erro.value)


def test_confirmacao_destrava_a_mesma_foto():
    nota = nota_demo._nota_de_leitura(
        leitura("nfce_ocr_foto.txt"),
        nomes=["Aspargo Branco Mercatto 205g", "Mostarda Hemmer Dijon 200g"],
        unidades=["UN", "UN"],
    )
    assert nota.total == Decimal("39.47")
    assert [i.unidade for i in nota.itens] == ["un", "un"]
    # A quantidade do item 2 foi deduzida do preço unitário, não inventada.
    assert [i.quantidade for i in nota.itens] == [Decimal("1.000"), Decimal("1.000")]


def test_confirmacao_incompleta_e_recusada():
    with pytest.raises(NotaAmbigua, match="2 itens e vieram 1 nomes"):
        nota_demo._nota_de_leitura(leitura("nfce_ocr_foto.txt"), nomes=["Só um"])


def test_nota_que_nao_fecha_nunca_vira_lancamento():
    linhas = [l for l in carregar("nfce_pdf.txt") if "0000001038809" not in l.texto]
    with pytest.raises(NotaAmbigua, match="não fechou"):
        nota_demo._nota_de_leitura(nfce.parsear(linhas))


def test_ler_nota_ainda_entende_o_formato_da_demonstracao(tmp_path):
    arquivo = tmp_path / "nota.txt"
    arquivo.write_text("DATA: 2035-01-01\nITEM: Arroz | 1 UN | R$ 10,00\n", encoding="utf-8")
    nota, motor = nota_demo.ler_nota(arquivo)
    assert motor == "texto" and nota.total == Decimal("10.00")


def test_ler_nota_entende_nfce_em_texto(tmp_path):
    arquivo = tmp_path / "nfce.txt"
    arquivo.write_text(
        "\n".join(l.texto for l in carregar("nfce_pdf.txt")), encoding="utf-8"
    )
    nota, _ = nota_demo.ler_nota(arquivo)
    assert nota.total == Decimal("39.47") and len(nota.itens) == 2


def test_arquivo_que_nao_e_nota_diz_isso_com_clareza(tmp_path):
    arquivo = tmp_path / "recado.txt"
    arquivo.write_text("oi, lembra de comprar pão", encoding="utf-8")
    with pytest.raises(NotaAmbigua, match="não reconheci isso como nota"):
        nota_demo.ler_nota(arquivo)


def test_tipo_sem_leitor_vira_mensagem_e_nao_excecao_tecnica(tmp_path):
    arquivo = tmp_path / "nota.docx"
    arquivo.write_bytes(b"\x00")
    with pytest.raises(NotaAmbigua, match="não sei ler arquivo"):
        nota_demo.ler_nota(arquivo)


def _inbound(tmp_path, nome: str, conteudo: str) -> Path:
    entrada = tmp_path / "media" / "inbound"
    entrada.mkdir(parents=True, exist_ok=True)
    destino = entrada / nome
    destino.write_text(conteudo, encoding="utf-8")
    return destino


def test_tool_devolve_o_que_falta_para_o_agente_perguntar(tmp_path, monkeypatch):
    pytest.importorskip("mcp")
    from sop.integracoes import nota_mcp

    # Confiança 1,0 no .txt deixaria tudo legível; o que trava aqui é a unidade
    # que o OCR não reconhece, exatamente como na foto da nota real.
    conteudo = "\n".join([
        "Detalhe da Venda",
        "001 0000001097750 ASPARGO BRANCO 205G 1,000 UIRX 22,49 22,49",
        "QTD. TOTAL DE ITENS 1",
        "VALOR TOTAL R$ 22,49",
        "Data de Autorizacao: 04/04/2026 22:07:38",
    ])
    arquivo = _inbound(tmp_path, "nota.txt", conteudo)
    monkeypatch.setenv("SABIA_WORKSPACE", str(tmp_path))

    resposta = nota_mcp.nota_demo_processar(str(arquivo))
    assert resposta["ok"] is False
    assert resposta["precisa_confirmar"] == "nomes"
    assert resposta["total"] == "22.49" and resposta["data"] == "2026-04-04"
    assert resposta["itens"][0]["falta"] == ["unidade"]
    # O texto bruto lido da nota não volta na resposta.
    assert "Detalhe da Venda" not in str(resposta)


def test_tool_recusa_arquivo_grande_com_o_numero_na_mensagem(tmp_path, monkeypatch):
    pytest.importorskip("mcp")
    from sop.integracoes import nota_mcp

    monkeypatch.setenv("SABIA_WORKSPACE", str(tmp_path))
    entrada = tmp_path / "media" / "inbound"
    entrada.mkdir(parents=True)
    grande = entrada / "nota.jpg"
    grande.write_bytes(b"\0" * (nota_mcp.LIMITE_BYTES + 1))
    resposta = nota_mcp.nota_demo_processar(str(grande))
    assert resposta["ok"] is False and "20 MB" in resposta["erro"]
