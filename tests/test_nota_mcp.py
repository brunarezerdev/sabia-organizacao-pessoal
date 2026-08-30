from pathlib import Path
import pytest

pytest.importorskip("mcp")
from sop.integracoes import nota_mcp


def test_so_aceita_media_inbound(tmp_path, monkeypatch):
    monkeypatch.setenv("SABIA_WORKSPACE", str(tmp_path))
    fora = tmp_path / "fora.txt"; fora.write_text("x")
    with pytest.raises(PermissionError): nota_mcp._arquivo_permitido(str(fora))
    entrada = tmp_path / "media" / "inbound"; entrada.mkdir(parents=True)
    dentro = entrada / "nota.txt"; dentro.write_text("x")
    assert nota_mcp._arquivo_permitido(str(dentro)) == dentro.resolve()


def test_tool_devolve_resumo_sem_texto_bruto(tmp_path, monkeypatch):
    entrada = tmp_path / "media" / "inbound"; entrada.mkdir(parents=True)
    nota = entrada / "nota.txt"
    nota.write_text("DATA: 2035-01-01\nITEM: Arroz | 1 UN | R$ 10,00\n")
    monkeypatch.setenv("SABIA_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(nota_mcp, "ClienteNotion", lambda _c: object())
    monkeypatch.setattr(nota_mcp, "BancoNotionNotaDemo", lambda *_a: object())
    monkeypatch.setattr(nota_mcp, "aplicar", lambda *_a: {"duplicada": False, "total": "10.00", "alterados": ["Arroz"]})
    resposta = nota_mcp.nota_demo_processar(str(nota))
    assert resposta["ok"] is True and resposta["itens"] == 1
    assert "DATA:" not in str(resposta)
