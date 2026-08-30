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
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Protocol


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


def extrair_texto(arquivo: Path) -> tuple[str, str]:
    """PDF textual primeiro, OCR local gratuito como fallback.

    QR/NFC-e é tratado como pista, não como dado persistente. Quando zbarimg
    existe, a URL detectada pode ser consumida por um adaptador de SEFAZ; sem
    ele, seguimos para OCR sem serviço pago e sem guardar a URL/chave.
    """
    sufixo = arquivo.suffix.lower()
    if sufixo == ".txt":
        return arquivo.read_text(encoding="utf-8"), "texto"
    if sufixo == ".pdf":
        r = subprocess.run(["pdftotext", str(arquivo), "-"], capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout, "pdf-texto"
        raise NotaAmbigua("PDF sem camada de texto; converta a página em imagem para OCR")
    with tempfile.TemporaryDirectory(prefix="sabia-nota-") as tmp:
        saida = Path(tmp) / "ocr"
        r = subprocess.run(["tesseract", str(arquivo), str(saida), "-l", "por"], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            r = subprocess.run(["tesseract", str(arquivo), str(saida)], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise NotaAmbigua("OCR local falhou; envie outra foto")
        return saida.with_suffix(".txt").read_text(encoding="utf-8"), "ocr-tesseract"


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
