"""Tool MCP que liga anexos recebidos pela Sábia ao fluxo de nota DEMO."""
from __future__ import annotations
import logging
import os
from pathlib import Path
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer

from ..config import Config
from ..nota_demo import NomesIlegiveis, NotaAmbigua, aplicar, ler_nota, resumo
from .notion import ClienteNotion
from .notion_nota_demo import BancoNotionNotaDemo

# Teto de download da Bot API do Telegram. Arquivo maior que isso nem chega ao
# disco, então recusar aqui é só devolver o motivo certo em vez de um erro solto.
LIMITE_BYTES = 20 * 1024 * 1024
EXTENSOES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".pdf", ".txt"}

logging.basicConfig(stream=sys.stderr, level=os.environ.get("SOP_LOG_LEVEL", "INFO"))
log = logging.getLogger("sop.nota_mcp")

servidor = MCPServer(
    name="nota-demo", version="1.0.0",
    instructions="Processa somente foto/PDF de nota no ambiente DEMO. Nunca use para dados financeiros reais.",
)


def _arquivo_permitido(valor: str) -> Path:
    arquivo = Path(valor).expanduser().resolve()
    raiz = Path(os.environ.get("SABIA_WORKSPACE", "")).expanduser().resolve()
    entrada = (raiz / "media" / "inbound").resolve()
    try:
        arquivo.relative_to(entrada)
    except ValueError as erro:
        raise PermissionError("o arquivo precisa estar em media/inbound do workspace da Sábia") from erro
    if not arquivo.is_file() or arquivo.is_symlink():
        raise FileNotFoundError("anexo não encontrado ou não permitido")
    if arquivo.suffix.lower() not in EXTENSOES:
        raise ValueError(
            f"não sei ler arquivo {arquivo.suffix or 'sem extensão'}; "
            "mande a nota como foto, imagem em arquivo ou PDF"
        )
    tamanho = arquivo.stat().st_size
    if tamanho > LIMITE_BYTES:
        # Falha explícita com o número, nunca em silêncio: quem recebe a
        # mensagem precisa saber o que fazer, não só que deu errado.
        raise ValueError(
            f"o arquivo tem {tamanho / 1024 / 1024:.1f} MB e o limite do Telegram "
            "é 20 MB; reenvie a nota em PDF ou com resolução menor"
        )
    return arquivo


@servidor.tool(
    title="Processar nota de mercado DEMO",
    description=(
        "Use quando uma pessoa autorizada enviar foto, imagem em arquivo ou PDF de "
        "nota de mercado. Passe o caminho local exibido no anexo, em media/inbound. "
        "A ferramenta registra o financeiro DEMO, atualiza a Despensa e tira "
        "correspondências exatas da Lista de Compras de forma idempotente. "
        "Se a resposta vier com `precisa_confirmar`, os valores da nota estão "
        "corretos mas algo de algum produto não foi legível: veja em `itens` o que "
        "falta de cada um, pergunte à pessoa e chame de novo passando `nomes` e, se "
        "for o caso, `unidades` (un, kg, g, l, ml), um para cada item na ordem da nota."
    ),
)
def nota_demo_processar(
    arquivo: str,
    nomes: list[str] | None = None,
    unidades: list[str] | None = None,
) -> dict[str, Any]:
    try:
        caminho = _arquivo_permitido(arquivo)
        nota, parser = ler_nota(caminho, nomes, unidades)
        banco = BancoNotionNotaDemo(
            ClienteNotion(Config.do_ambiente()),
            os.environ.get("NOTION_LANCAMENTOS_DEMO_ID", ""),
            os.environ.get("NOTION_INGREDIENTES_DEMO_ID", ""),
        )
        resultado = aplicar(nota, banco)
        return {"ok": True, "resumo": resumo(resultado), "parser": parser,
                "duplicada": resultado["duplicada"], "itens": len(nota.itens)}
    except NomesIlegiveis as erro:
        # Os números fecham; só o nome do produto não saiu. Devolver a estrutura
        # deixa o agente perguntar em vez de descartar uma nota que está certa.
        log.warning("nota_demo_processar pediu confirmação de nomes: %s", erro)
        return {
            "ok": False,
            "erro": str(erro),
            "precisa_confirmar": "nomes",
            "data": erro.leitura.data.isoformat() if erro.leitura.data else None,
            "total": str(erro.leitura.total_declarado),
            "itens": [
                {"posicao": posicao + 1, "valor": str(item.total),
                 "quantidade": str(item.quantidade), "unidade": item.unidade,
                 "nome_lido": item.descricao if item.nome_confiavel else None,
                 "falta": list(item.falta())}
                for posicao, item in enumerate(erro.leitura.itens)
            ],
        }
    except (NotaAmbigua, PermissionError, FileNotFoundError, ValueError, RuntimeError) as erro:
        log.warning("nota_demo_processar recusou anexo: %s", erro)
        return {"ok": False, "erro": str(erro)}


def main() -> None:
    servidor.run(transport="stdio")


if __name__ == "__main__":
    main()
