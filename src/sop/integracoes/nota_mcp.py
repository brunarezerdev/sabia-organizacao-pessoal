"""Tool MCP que liga anexos recebidos pela Sábia ao fluxo de nota DEMO."""
from __future__ import annotations
import logging
import os
from pathlib import Path
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer

from ..config import Config
from ..nota_demo import NotaAmbigua, aplicar, extrair_texto, parsear_texto, resumo
from .notion import ClienteNotion
from .notion_nota_demo import BancoNotionNotaDemo

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
    if arquivo.stat().st_size > 12 * 1024 * 1024:
        raise ValueError("anexo excede 12 MB")
    return arquivo


@servidor.tool(
    title="Processar nota de mercado DEMO",
    description=(
        "Use quando uma pessoa autorizada enviar foto ou PDF de nota de mercado. "
        "Passe o caminho local exibido no anexo, em media/inbound. A ferramenta "
        "registra o financeiro DEMO, atualiza a Despensa e tira correspondências "
        "exatas da Lista de Compras de forma idempotente."
    ),
)
def nota_demo_processar(arquivo: str) -> dict[str, Any]:
    try:
        caminho = _arquivo_permitido(arquivo)
        texto, parser = extrair_texto(caminho)
        nota = parsear_texto(texto)
        banco = BancoNotionNotaDemo(
            ClienteNotion(Config.do_ambiente()),
            os.environ.get("NOTION_LANCAMENTOS_DEMO_ID", ""),
            os.environ.get("NOTION_INGREDIENTES_DEMO_ID", ""),
        )
        resultado = aplicar(nota, banco)
        return {"ok": True, "resumo": resumo(resultado), "parser": parser,
                "duplicada": resultado["duplicada"], "itens": len(nota.itens)}
    except (NotaAmbigua, PermissionError, FileNotFoundError, ValueError, RuntimeError) as erro:
        log.warning("nota_demo_processar recusou anexo: %s", erro)
        return {"ok": False, "erro": str(erro)}


def main() -> None:
    servidor.run(transport="stdio")


if __name__ == "__main__":
    main()
