"""Leitura local de texto em foto e PDF, sem serviço pago e sem enviar imagem para fora.

Por que este módulo existe: `nota_demo.extrair_texto` chamava `tesseract` e
`pdftotext` por subprocess. Nenhum dos dois está instalado nesta VPS e não há
root para instalar pacote de sistema, então toda foto de nota morria com
`FileNotFoundError` antes de chegar ao parser. Aqui a leitura passa a depender
de bibliotecas Python instaláveis no diretório do usuário, e os binários de
sistema viram um caminho opcional, usado só quando existem.

O retorno é uma lista de `Linha`, não uma string solta, porque a nota fiscal é
um documento em colunas: o motor de OCR devolve pedaços soltos e é a
reconstrução por posição vertical que recompõe "001 <código> <descrição>" numa
linha só. A confiança de cada linha viaja junto porque o parser da nota precisa
saber o que ele leu bem e o que ele só chutou.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

IMAGENS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}

# Acima disso a imagem é reduzida antes do OCR: foto de celular moderna passa
# de 4000px de largura e o detector não ganha nada com isso, só tempo.
LARGURA_MAXIMA = 2200
# Abaixo disso a imagem é ampliada: cupom fiscal fotografado de longe tem
# letra pequena demais para o reconhecedor.
LARGURA_MINIMA = 1100


class ErroDeLeitura(RuntimeError):
    """Não deu para extrair texto do arquivo."""


@dataclass(frozen=True)
class Linha:
    texto: str
    confianca: float

    def __str__(self) -> str:  # pragma: no cover - conveniência de depuração
        return self.texto


# ---------------------------------------------------------------------------
# Texto e PDF
# ---------------------------------------------------------------------------


def _do_texto(arquivo: Path) -> list[Linha]:
    conteudo = arquivo.read_text(encoding="utf-8", errors="replace")
    return [Linha(l, 1.0) for l in conteudo.splitlines()]


def _pdf_por_binario(arquivo: Path) -> str:
    if not shutil.which("pdftotext"):
        return ""
    try:
        r = subprocess.run(
            ["pdftotext", "-layout", str(arquivo), "-"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout if r.returncode == 0 else ""


def _pdf_por_biblioteca(arquivo: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        leitor = PdfReader(str(arquivo))
        return "\n".join((pagina.extract_text() or "") for pagina in leitor.pages)
    except Exception:  # PDF corrompido ou protegido: cai para o OCR da imagem
        return ""


def _pdf_para_imagem(arquivo: Path, destino: Path) -> Path | None:
    """Rasteriza a primeira página para OCR quando o PDF não tem camada de texto."""
    try:
        import fitz
    except ImportError:
        return None
    try:
        with fitz.open(str(arquivo)) as doc:
            if not doc.page_count:
                return None
            # 200 dpi: o suficiente para cupom, sem estourar a memória do OCR.
            pagina = doc.load_page(0)
            pagina.get_pixmap(dpi=200).save(str(destino))
    except Exception:
        return None
    return destino if destino.is_file() else None


# ---------------------------------------------------------------------------
# Imagem
# ---------------------------------------------------------------------------


def _preparar_imagem(arquivo: Path):
    import cv2

    imagem = cv2.imread(str(arquivo))
    if imagem is None:
        raise ErroDeLeitura("não consegui abrir a imagem; o arquivo pode estar corrompido")
    altura, largura = imagem.shape[:2]
    if largura > LARGURA_MAXIMA:
        fator = LARGURA_MAXIMA / largura
        imagem = cv2.resize(imagem, None, fx=fator, fy=fator, interpolation=cv2.INTER_AREA)
    elif largura < LARGURA_MINIMA:
        fator = LARGURA_MINIMA / largura
        imagem = cv2.resize(imagem, None, fx=fator, fy=fator, interpolation=cv2.INTER_CUBIC)
    return imagem


def _agrupar_em_linhas(blocos: list[tuple[list, str, float]]) -> list[Linha]:
    """Recompõe as linhas do documento a partir das caixas soltas do detector.

    Duas caixas pertencem à mesma linha quando seus centros verticais estão a
    menos de meia altura de distância. Dentro da linha, a ordem é a horizontal.
    """
    registros = []
    for caixa, texto, confianca in blocos:
        texto = (texto or "").strip()
        if not texto:
            continue
        ys = [p[1] for p in caixa]
        xs = [p[0] for p in caixa]
        registros.append({
            "centro": (min(ys) + max(ys)) / 2,
            "altura": max(1.0, max(ys) - min(ys)),
            "x": min(xs),
            "texto": texto,
            "confianca": float(confianca),
        })
    registros.sort(key=lambda r: r["centro"])

    linhas: list[list[dict]] = []
    for registro in registros:
        if linhas:
            atual = linhas[-1]
            referencia = sum(r["centro"] for r in atual) / len(atual)
            tolerancia = max(r["altura"] for r in atual) * 0.6
            if abs(registro["centro"] - referencia) <= tolerancia:
                atual.append(registro)
                continue
        linhas.append([registro])

    saida = []
    for grupo in linhas:
        grupo.sort(key=lambda r: r["x"])
        texto = " ".join(r["texto"] for r in grupo)
        saida.append(Linha(texto, min(r["confianca"] for r in grupo)))
    return saida


def _ocr_rapidocr(arquivo: Path) -> list[Linha] | None:
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return None
    imagem = _preparar_imagem(arquivo)
    resultado, _ = RapidOCR()(imagem)
    if not resultado:
        return []
    return _agrupar_em_linhas(resultado)


def _ocr_tesseract(arquivo: Path) -> list[Linha] | None:
    if not shutil.which("tesseract"):
        return None
    import tempfile

    with tempfile.TemporaryDirectory(prefix="sabia-nota-") as tmp:
        saida = Path(tmp) / "ocr"
        for idioma in (["-l", "por"], []):
            r = subprocess.run(
                ["tesseract", str(arquivo), str(saida), *idioma],
                capture_output=True, text=True, timeout=60,
            )
            if r.returncode == 0:
                texto = saida.with_suffix(".txt").read_text(encoding="utf-8", errors="replace")
                # O tesseract não devolve confiança nesta chamada; 0.8 é um
                # meio-termo honesto: passa no corte de legibilidade, mas não
                # se disfarça de leitura perfeita.
                return [Linha(l, 0.8) for l in texto.splitlines() if l.strip()]
    return None


# ---------------------------------------------------------------------------
# Entrada única
# ---------------------------------------------------------------------------


def ler(arquivo: Path) -> tuple[list[Linha], str]:
    """Devolve as linhas do documento e o nome do motor que as leu."""
    sufixo = arquivo.suffix.lower()

    if sufixo == ".txt":
        return _do_texto(arquivo), "texto"

    if sufixo == ".pdf":
        texto = _pdf_por_binario(arquivo) or _pdf_por_biblioteca(arquivo)
        if texto.strip():
            return [Linha(l, 1.0) for l in texto.splitlines() if l.strip()], "pdf-texto"
        import tempfile

        with tempfile.TemporaryDirectory(prefix="sabia-nota-") as tmp:
            pagina = _pdf_para_imagem(arquivo, Path(tmp) / "pagina.png")
            if pagina is None:
                raise ErroDeLeitura(
                    "esse PDF não tem texto e não consegui transformar a página em imagem"
                )
            linhas, motor = _ler_imagem(pagina)
            return linhas, f"pdf-imagem+{motor}"

    if sufixo in IMAGENS:
        return _ler_imagem(arquivo)

    raise ErroDeLeitura(f"não sei ler arquivo do tipo {sufixo or 'desconhecido'}")


def _ler_imagem(arquivo: Path) -> tuple[list[Linha], str]:
    linhas = _ocr_rapidocr(arquivo)
    if linhas is not None:
        return linhas, "ocr-rapidocr"
    linhas = _ocr_tesseract(arquivo)
    if linhas is not None:
        return linhas, "ocr-tesseract"
    raise ErroDeLeitura(
        "não há motor de OCR instalado nesta máquina "
        "(instale rapidocr-onnxruntime, ou o binário tesseract)"
    )
