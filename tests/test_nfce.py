"""A nota que fecha é a nota em que se pode confiar.

As fixtures são as duas leituras reais do mesmo cupom: a foto de celular de um
cupom térmico desbotado (números bons, nomes ilegíveis) e a versão vinda de
PDF com camada de texto (tudo legível). O que separa "registra" de "pergunta"
não é o OCR parecer bom, é a soma dos itens bater com o total impresso.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from sop import nfce
from sop.ocr import Linha

FIXTURES = Path(__file__).parent / "fixtures"


def carregar(nome: str) -> list[Linha]:
    linhas = []
    for bruta in (FIXTURES / nome).read_text(encoding="utf-8").splitlines():
        if not bruta.strip() or bruta.startswith("#"):
            continue
        confianca, _, texto = bruta.partition("|")
        linhas.append(Linha(texto, float(confianca)))
    return linhas


def test_foto_desbotada_fecha_mas_nao_arrisca_os_nomes():
    leitura = nfce.parsear(carregar("nfce_ocr_foto.txt"))
    assert leitura.data.isoformat() == "2026-04-04"
    assert leitura.total_declarado == Decimal("39.47")
    assert leitura.soma == Decimal("39.47")
    assert leitura.itens_declarados == 2 and len(leitura.itens) == 2
    # A nota fecha: nenhuma linha foi perdida nem inventada.
    assert leitura.fecha is True
    # Mas nenhum dos nomes é confiável, então nenhum vira ingrediente.
    assert len(leitura.ilegiveis) == 2


def test_pdf_limpo_libera_os_nomes():
    leitura = nfce.parsear(carregar("nfce_pdf.txt"))
    assert leitura.fecha is True
    assert leitura.ilegiveis == ()
    assert [i.descricao for i in leitura.itens] == [
        "ASPARGO BRANCO MERCATTO 205G",
        "MOSTARDA HEMMER DIJON 200G",
    ]
    assert [i.unidade for i in leitura.itens] == ["un", "un"]
    assert leitura.itens[0].quantidade == Decimal("1.000")


def test_nota_que_nao_soma_nao_fecha_e_diz_o_porque():
    linhas = carregar("nfce_pdf.txt")
    adulterada = [
        Linha(l.texto.replace("VALOR TOTAL R$ 39,47", "VALOR TOTAL R$ 49,47"), l.confianca)
        for l in linhas
    ]
    leitura = nfce.parsear(adulterada)
    assert leitura.fecha is False
    assert "39.47" in leitura.porque_nao_fecha() and "49.47" in leitura.porque_nao_fecha()


def test_item_faltando_nao_fecha():
    linhas = [l for l in carregar("nfce_pdf.txt") if "0000001038809" not in l.texto]
    leitura = nfce.parsear(linhas)
    assert leitura.fecha is False
    assert "2 itens" in leitura.porque_nao_fecha()


def test_texto_sem_itens_nao_e_nfce():
    with pytest.raises(nfce.NaoEhNFCe):
        nfce.parsear([Linha("Oi, isso aqui não é uma nota", 1.0)])


@pytest.mark.parametrize(
    "descricao, confianca, esperado",
    [
        ("ASPARGO BRANCO MERCATTO 205G", 1.0, True),
        ("S1# #E D 200G", 0.9, False),      # caractere impossível em rótulo
        ("U8A102054", 0.95, False),          # quase só dígito, não é nome
        ("ARROZ", 0.7, False),               # legível, mas o motor não confia
        ("", 1.0, False),
    ],
)
def test_corte_de_legibilidade_do_nome(descricao, confianca, esperado):
    assert nfce.nome_legivel(descricao, confianca) is esperado
