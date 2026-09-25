"""Leitura de uma NFC-e de verdade, do jeito que o cupom sai impresso.

O `nota_demo.parsear_texto` só aceita um formato inventado para a
demonstração (`DATA:` e `ITEM: nome | qtd un | R$ total`). Nenhum cupom de
supermercado sai assim, então a foto de uma nota real nunca passava daquele
parser: a leitura morria em "não consegui confirmar data e itens" mesmo quando
o OCR tinha lido a nota inteira.

Este módulo lê o bloco "Detalhe da Venda" da NFC-e, que tem sempre a mesma
estrutura:

    001 0000001097750 ASPARGO BRANCO MERCATTO 205G
    1,000 UN X 22,49                          22,49
    QTD. TOTAL DE ITENS                           2
    VALOR TOTAL R$                            39,47

A regra que dá confiança ao resultado não é o OCR estar bonito, é a nota
**fechar**: a soma das linhas tem que bater com o VALOR TOTAL impresso e a
contagem tem que bater com a QTD. TOTAL DE ITENS. Quando fecha, sabemos que
nenhuma linha foi perdida nem inventada, mesmo que o reconhecimento tenha
errado letras.

O que o OCR **não** garante é o nome do produto. Numa foto de cupom térmico
desbotado os números saem com 0,95 de confiança e a descrição sai como
"HUSTAROA BtHINEK DTTUN". Por isso o nome tem um corte de legibilidade
próprio: item ilegível não vira linha na Despensa com nome chutado, ele volta
para confirmação. Inventar nome de produto é tão grave quanto inventar valor.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from .ocr import Linha

# Abaixo disso a descrição não vira nome de ingrediente. Calibrado na foto real
# da Bruna: os números saem entre 0,87 e 0,98 e as descrições entre 0,69 e 0,78.
LIMIAR_NOME = 0.85

UNIDADES = {"UN": "un", "UND": "un", "UNID": "un", "KG": "kg", "G": "g", "L": "l", "LT": "l", "ML": "ml"}

# 001 <código> <descrição> <qtd> <un> X <unitário> <total>
# Tolerante de propósito: o OCR cola "UN X" em "UNX" e come o "1" de "1,000".
ITEM = re.compile(
    r"^\s*(?P<seq>\d{1,3})\s*[-–.\s]\s*(?P<codigo>\d{6,})\s*"
    r"(?P<descricao>.*?)\s*"
    r"(?P<quantidade>\d*[.,]\d{1,3})\s*"
    r"(?P<unidade>[A-Za-z]{1,4})\s*[Xx]?\s*"
    r"(?P<unitario>\d+[.,]\d{2})\s+"
    r"(?P<total>\d+[.,]\d{2})\s*$"
)

DATA = re.compile(r"\b(\d{2})[/.\-](\d{2})[/.\-](\d{4})\b")
DINHEIRO = re.compile(r"\b\d{1,3}(?:\.\d{3})*[.,]\d{2}\b")
INTEIRO = re.compile(r"\b(\d{1,4})\b")


class NaoEhNFCe(ValueError):
    """As linhas não parecem uma NFC-e; quem chamou deve tentar outro formato."""


def _so_letras(texto: str) -> str:
    base = unicodedata.normalize("NFKD", texto.upper())
    return re.sub(r"[^A-Z]", "", "".join(c for c in base if not unicodedata.combining(c)))


def _decimal(bruto: str) -> Decimal | None:
    try:
        return Decimal(bruto.replace(".", "").replace(",", ".") if bruto.count(",") == 1 and bruto.count(".") >= 1 else bruto.replace(",", "."))
    except InvalidOperation:
        return None


def nome_legivel(descricao: str, confianca: float) -> bool:
    """Diz se dá para confiar nessa descrição como nome de produto."""
    if confianca < LIMIAR_NOME:
        return False
    limpo = descricao.strip()
    if not limpo:
        return False
    # Caractere que não existe em rótulo de produto é sinal de lixo de OCR.
    if re.search(r"[^\w\s./%&+\-°ºª]", limpo, re.UNICODE):
        return False
    letras = len(re.sub(r"[^A-Za-zÀ-ÿ]", "", limpo))
    if letras < 3:
        return False
    return letras / max(1, len(limpo.replace(" ", ""))) >= 0.5


@dataclass(frozen=True)
class ItemLido:
    descricao: str
    quantidade: Decimal
    unidade: str | None
    total: Decimal
    confianca: float

    @property
    def nome_confiavel(self) -> bool:
        return nome_legivel(self.descricao, self.confianca)

    @property
    def legivel(self) -> bool:
        return self.unidade is not None and self.quantidade > 0 and self.nome_confiavel

    def falta(self) -> tuple[str, ...]:
        """O que desta linha não deu para ler."""
        pendencias = []
        if not self.nome_confiavel:
            pendencias.append("nome")
        if self.unidade is None:
            pendencias.append("unidade")
        if self.quantidade <= 0:
            pendencias.append("quantidade")
        return tuple(pendencias)


def _quantidade_pelo_unitario(total: Decimal, unitario: Decimal | None) -> Decimal | None:
    """Deduz a quantidade a partir de dois números que o OCR leu bem.

    Não é chute: preço unitário e total vêm de colunas diferentes do cupom e
    saem com confiança alta mesmo em foto ruim. Se a divisão não der um número
    redondo de três casas, a dedução é descartada em vez de arredondada.
    """
    if not unitario or unitario <= 0:
        return None
    bruta = total / unitario
    arredondada = bruta.quantize(Decimal("0.001"))
    if abs(bruta - arredondada) > Decimal("0.0005") or arredondada <= 0:
        return None
    return arredondada


@dataclass(frozen=True)
class LeituraNFCe:
    data: date | None
    itens: tuple[ItemLido, ...]
    total_declarado: Decimal | None
    itens_declarados: int | None

    @property
    def soma(self) -> Decimal:
        return sum((i.total for i in self.itens), Decimal("0"))

    @property
    def fecha(self) -> bool:
        """A nota bate consigo mesma? É isso que valida a leitura, não o OCR."""
        if self.total_declarado is None or self.itens_declarados is None:
            return False
        return self.soma == self.total_declarado and len(self.itens) == self.itens_declarados

    @property
    def ilegiveis(self) -> tuple[ItemLido, ...]:
        return tuple(i for i in self.itens if not i.legivel)

    def porque_nao_fecha(self) -> str:
        if self.total_declarado is None:
            return "não achei o VALOR TOTAL impresso na nota"
        if self.itens_declarados is None:
            return "não achei a QTD. TOTAL DE ITENS impressa na nota"
        if len(self.itens) != self.itens_declarados:
            return f"a nota diz {self.itens_declarados} itens e eu só consegui ler {len(self.itens)}"
        return f"a soma dos itens deu R$ {self.soma} e a nota diz R$ {self.total_declarado}"


def _extrair_data(linhas: list[Linha]) -> date | None:
    """Data de emissão/autorização. Só aceita quando a nota é coerente consigo."""
    encontradas: list[date] = []
    for linha in linhas:
        for dia, mes, ano in DATA.findall(linha.texto):
            try:
                encontradas.append(date(int(ano), int(mes), int(dia)))
            except ValueError:
                continue
    if not encontradas:
        return None
    # Emissão e autorização são a mesma data no cupom; divergência é ruído de
    # OCR e aí a data mais repetida é a leitura certa.
    return max(set(encontradas), key=encontradas.count)


def _extrair_totais(linhas: list[Linha]) -> tuple[Decimal | None, int | None]:
    total: Decimal | None = None
    quantidade: int | None = None
    for linha in linhas:
        letras = _so_letras(linha.texto)
        if "TOTAL" not in letras:
            continue
        if "ITEN" in letras or "ITEM" in letras:
            numeros = INTEIRO.findall(re.sub(r"\d{6,}", " ", linha.texto))
            if numeros and quantidade is None:
                quantidade = int(numeros[-1])
            continue
        valores = DINHEIRO.findall(linha.texto)
        if valores and total is None:
            total = _decimal(valores[-1])
    return total, quantidade


def parsear(linhas: list[Linha]) -> LeituraNFCe:
    """Lê as linhas de uma NFC-e. Levanta `NaoEhNFCe` se não reconhecer nenhum item."""
    itens: list[ItemLido] = []
    for linha in linhas:
        m = ITEM.match(linha.texto)
        if not m:
            continue
        quantidade = _decimal(m.group("quantidade")) or Decimal("0")
        total = _decimal(m.group("total"))
        if total is None:
            continue
        if quantidade <= 0:
            # O OCR come o "1" de "1,000" com frequência; o unitário salva a linha.
            quantidade = _quantidade_pelo_unitario(total, _decimal(m.group("unitario"))) or Decimal("0")
        unidade = UNIDADES.get(m.group("unidade").upper().rstrip("X"))
        itens.append(ItemLido(
            descricao=re.sub(r"\s+", " ", m.group("descricao")).strip(),
            quantidade=quantidade,
            unidade=unidade,
            total=total,
            confianca=linha.confianca,
        ))
    if not itens:
        raise NaoEhNFCe("nenhuma linha de item no formato de NFC-e")
    total, quantidade_declarada = _extrair_totais(linhas)
    return LeituraNFCe(_extrair_data(linhas), tuple(itens), total, quantidade_declarada)
