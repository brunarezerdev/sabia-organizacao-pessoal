"""Ingestão segura de nota de mercado para a demonstração da Sábia.

O módulo só opera quando ``SABIA_DEMO=1`` e recebe explicitamente os ids das
duas fontes Notion. A impressão digital usa apenas data, total e itens
normalizados; chave fiscal, CPF/CNPJ e texto OCR nunca são persistidos.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Protocol

from . import nfce, ocr


UNIDADES = {"UN": "un", "UND": "un", "KG": "kg", "G": "g", "L": "l", "ML": "ml"}
SENSIVEL = re.compile(r"\b(?:cpf|cnpj|chave\s+de\s+acesso|cart[aã]o|endere[cç]o)\b", re.I)
ITEM = re.compile(
    r"^ITEM\s*:\s*(?P<nome>.+?)\s*\|\s*(?P<qtd>\d+(?:[,.]\d+)?)\s*(?P<un>[A-Za-z]+)\s*\|\s*R\$\s*(?P<total>\d+(?:[,.]\d{2})?)$",
    re.I,
)


class NotaAmbigua(ValueError):
    pass


@dataclass(frozen=True)
class ItemNota:
    nome: str
    chave: str
    quantidade: Decimal
    unidade: str
    total: Decimal


@dataclass(frozen=True)
class Nota:
    data: date
    itens: tuple[ItemNota, ...]

    @property
    def total(self) -> Decimal:
        return sum((i.total for i in self.itens), Decimal("0"))

    @property
    def fingerprint(self) -> str:
        seguro = {"data": self.data.isoformat(), "total": str(self.total), "itens": [
            [i.chave, str(i.quantidade), i.unidade, str(i.total)] for i in self.itens
        ]}
        return hashlib.sha256(json.dumps(seguro, sort_keys=True).encode()).hexdigest()[:24]


def normalizar_nome(nome: str) -> tuple[str, str]:
    exibicao = re.sub(r"\s+", " ", nome.strip()).strip("-:;,. ")
    base = unicodedata.normalize("NFKD", exibicao.casefold())
    chave = re.sub(r"[^a-z0-9]+", "-", "".join(c for c in base if not unicodedata.combining(c))).strip("-")
    if len(chave) < 2:
        raise NotaAmbigua(f"nome de item ambíguo: {nome!r}")
    return exibicao, chave


def parsear_texto(texto: str) -> Nota:
    # O formato estruturado é deliberado: OCR pode errar, mas nunca adivinhamos
    # uma linha financeira. Linhas não reconhecidas são ignoradas e não salvas.
    data_nota = None
    itens: list[ItemNota] = []
    for linha in texto.splitlines():
        if SENSIVEL.search(linha):
            continue
        mdata = re.match(r"^DATA\s*:\s*(\d{4}-\d{2}-\d{2})\s*$", linha.strip(), re.I)
        if mdata:
            data_nota = date.fromisoformat(mdata.group(1))
            continue
        m = ITEM.match(linha.strip())
        if not m:
            continue
        nome, chave = normalizar_nome(m.group("nome"))
        un = UNIDADES.get(m.group("un").upper())
        if not un:
            raise NotaAmbigua(f"unidade não reconhecida em {nome}")
        qtd = Decimal(m.group("qtd").replace(",", "."))
        total = Decimal(m.group("total").replace(",", "."))
        if qtd <= 0 or total < 0:
            raise NotaAmbigua(f"quantidade/valor inválido em {nome}")
        itens.append(ItemNota(nome, chave, qtd, un, total))
    if not data_nota or not itens:
        raise NotaAmbigua("não consegui confirmar data e itens; envie foto mais nítida ou confirme os dados")
    chaves = [(i.chave, i.unidade) for i in itens]
    if len(chaves) != len(set(chaves)):
        raise NotaAmbigua("a nota contém linhas repetidas; confirme antes de consolidar")
    return Nota(data_nota, tuple(itens))


def extrair_linhas(arquivo: Path) -> tuple[list[ocr.Linha], str]:
    """Linhas do documento e o motor que as leu, com a confiança de cada uma.

    A leitura em si mora em `sop.ocr`, que escolhe entre texto, PDF e OCR de
    imagem conforme o que existe instalado na máquina. Aqui só traduzimos a
    falha técnica para uma frase que a pessoa consegue agir em cima.
    """
    try:
        return ocr.ler(arquivo)
    except ocr.ErroDeLeitura as erro:
        raise NotaAmbigua(str(erro)) from erro


def extrair_texto(arquivo: Path) -> tuple[str, str]:
    """Versão em texto corrido da leitura, mantida para quem só quer o conteúdo."""
    linhas, motor = extrair_linhas(arquivo)
    return "\n".join(l.texto for l in linhas), motor


class NomesIlegiveis(NotaAmbigua):
    """A nota fecha nos números, mas o nome de um ou mais produtos não foi lido.

    Carrega a leitura inteira para que quem chamou possa perguntar à pessoa os
    nomes que faltam em vez de descartar uma nota que está correta no resto.
    """

    def __init__(self, mensagem: str, leitura: nfce.LeituraNFCe) -> None:
        super().__init__(mensagem)
        self.leitura = leitura


def _parece_formato_demo(linhas: list[ocr.Linha]) -> bool:
    return any(ITEM.match(l.texto.strip()) for l in linhas)


def _conferir_tamanho(rotulo: str, valores: list[str] | None, esperado: int) -> None:
    if valores is not None and len(valores) != esperado:
        raise NotaAmbigua(
            f"a nota tem {esperado} itens e vieram {len(valores)} {rotulo}; "
            f"confirme {rotulo} para cada item, na ordem da nota"
        )


def _nota_de_leitura(
    leitura: nfce.LeituraNFCe,
    nomes: list[str] | None = None,
    unidades: list[str] | None = None,
) -> Nota:
    """Converte a leitura da NFC-e na `Nota` que o restante do fluxo consome."""
    if leitura.data is None:
        raise NotaAmbigua("não achei a data na nota; confirme a data da compra")
    if not leitura.fecha:
        # Nota que não fecha é leitura incompleta, e leitura incompleta não vira
        # lançamento: metade de uma compra no financeiro é pior que nenhuma.
        raise NotaAmbigua(f"a leitura não fechou: {leitura.porque_nao_fecha()}")

    _conferir_tamanho("nomes", nomes, len(leitura.itens))
    _conferir_tamanho("unidades", unidades, len(leitura.itens))

    escolhidos: list[tuple[str, str | None]] = []
    faltando: list[tuple[int, tuple[str, ...]]] = []
    for posicao, item in enumerate(leitura.itens):
        nome = (nomes[posicao].strip() if nomes else "") or (
            item.descricao if item.nome_confiavel else ""
        )
        bruta = (unidades[posicao].strip() if unidades else "")
        unidade = nfce.UNIDADES.get(bruta.upper(), bruta.lower() or None) if bruta else item.unidade
        escolhidos.append((nome, unidade))

        pendencias = [p for p in item.falta() if p != "quantidade"]
        if nome:
            pendencias = [p for p in pendencias if p != "nome"]
        if unidade:
            pendencias = [p for p in pendencias if p != "unidade"]
        if item.quantidade <= 0:
            pendencias.append("quantidade")
        if pendencias:
            faltando.append((posicao, tuple(pendencias)))

    if faltando:
        pendentes = "; ".join(
            f"item {p + 1} de R$ {leitura.itens[p].total} (falta {', '.join(o)})"
            for p, o in faltando
        )
        raise NomesIlegiveis(
            f"os números da nota fecham em R$ {leitura.total_declarado}, mas não "
            f"consegui ler tudo de {len(faltando)} produto(s): {pendentes}. "
            "Confirme o que falta ou reenvie a nota em PDF ou com foto mais nítida.",
            leitura,
        )

    itens: list[ItemNota] = []
    for (nome_bruto, unidade), item in zip(escolhidos, leitura.itens):
        nome, chave = normalizar_nome(nome_bruto)
        if unidade is None:
            raise NotaAmbigua(f"unidade não reconhecida em {nome}")
        if item.quantidade <= 0 or item.total < 0:
            raise NotaAmbigua(f"quantidade/valor inválido em {nome}")
        itens.append(ItemNota(nome, chave, item.quantidade, unidade, item.total))

    chaves = [(i.chave, i.unidade) for i in itens]
    if len(chaves) != len(set(chaves)):
        raise NotaAmbigua("a nota contém linhas repetidas; confirme antes de consolidar")
    return Nota(leitura.data, tuple(itens))


def ler_nota(
    arquivo: Path,
    nomes: list[str] | None = None,
    unidades: list[str] | None = None,
) -> tuple[Nota, str]:
    """Lê o arquivo e devolve a nota mais o método usado.

    Dois formatos são aceitos, nesta ordem: o formato estruturado da
    demonstração, e a NFC-e como ela sai impressa no cupom. A ordem importa
    porque o formato da demonstração é explícito e não precisa de nenhuma
    inferência.
    """
    linhas, motor = extrair_linhas(arquivo)
    if _parece_formato_demo(linhas):
        return parsear_texto("\n".join(l.texto for l in linhas)), motor
    try:
        leitura = nfce.parsear(linhas)
    except nfce.NaoEhNFCe as erro:
        raise NotaAmbigua(
            "não reconheci isso como nota de mercado; confira se a foto pegou o "
            "bloco de itens inteiro, ou envie o PDF da nota"
        ) from erro
    return _nota_de_leitura(leitura, nomes, unidades), motor


class BancoDemo(Protocol):
    def achar_lancamento(self, fingerprint: str) -> dict | None: ...
    def criar_lancamento(self, nota: Nota) -> str: ...
    def achar_ingrediente(self, chave: str) -> dict | None: ...
    def criar_ingrediente(self, item: ItemNota) -> str: ...
    def atualizar_ingrediente(self, pagina: dict, item: ItemNota) -> None: ...
    def restaurar_ingrediente(self, pagina: dict) -> None: ...
    def arquivar(self, pagina_id: str) -> None: ...


def aplicar(nota: Nota, banco: BancoDemo) -> dict[str, Any]:
    existente = banco.achar_lancamento(nota.fingerprint)
    if existente:
        return {"ok": True, "duplicada": True, "fingerprint": nota.fingerprint, "alterados": []}
    criados: list[str] = []
    atualizados: list[dict] = []
    try:
        criados.append(banco.criar_lancamento(nota))
        for item in nota.itens:
            pagina = banco.achar_ingrediente(item.chave)
            if pagina:
                atualizados.append(pagina)
                banco.atualizar_ingrediente(pagina, item)
            else:
                criados.append(banco.criar_ingrediente(item))
    except Exception as erro:
        erros_rollback = []
        for pagina in reversed(atualizados):
            try: banco.restaurar_ingrediente(pagina)
            except Exception as e: erros_rollback.append(str(e))
        for pagina_id in reversed(criados):
            try: banco.arquivar(pagina_id)
            except Exception as e: erros_rollback.append(str(e))
        sufixo = "" if not erros_rollback else "; rollback pendente: " + "; ".join(erros_rollback)
        raise RuntimeError(f"Notion falhou; alterações desfeitas{sufixo}") from erro
    return {"ok": True, "duplicada": False, "fingerprint": nota.fingerprint,
            "total": str(nota.total), "alterados": [i.nome for i in nota.itens]}


def resumo(resultado: dict[str, Any]) -> str:
    if resultado["duplicada"]:
        return "Essa nota DEMO já foi processada. Nada foi duplicado."
    nomes = ", ".join(resultado["alterados"])
    return f"Nota DEMO registrada: R$ {resultado['total']}. Despensa atualizada: {nomes}. Itens correspondentes saíram da Lista de Compras."
