"""A CSP de produção e o front do dashboard precisam continuar compatíveis.

Estes testes existem por causa de um bug real: as barras dos gráficos eram
desenhadas com `style="width:…"`, e a CSP de produção usa `style-src 'self'`
sem `'unsafe-inline'`. O navegador descartava o estilo silenciosamente e todas
as barras apareciam do mesmo tamanho — sem erro em lugar nenhum, e localmente
não dava para ver, porque o servidor de desenvolvimento não manda CSP.

A regra é o par: ou a CSP libera estilo inline, ou o front não usa estilo
inline. Aqui a escolha é a segunda, e é ela que estes testes trancam.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DASHBOARD = RAIZ / "dashboard"

_spec = importlib.util.spec_from_file_location("api_dashboard", RAIZ / "api" / "dashboard.py")
api = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(api)


def csp_do_vercel_json() -> str:
    regras = json.loads((RAIZ / "vercel.json").read_text(encoding="utf-8"))["headers"]
    for regra in regras:
        for h in regra["headers"]:
            if h["key"] == "Content-Security-Policy":
                return h["value"]
    raise AssertionError("vercel.json não declara Content-Security-Policy")


def test_a_csp_da_plataforma_e_da_funcao_sao_a_mesma():
    """A política está escrita em dois lugares; divergir é bug silencioso.

    A resposta da função sai com os dois cabeçalhos, o do `vercel.json` e o
    dela. Navegador aplica CSPs múltiplas por interseção: se um dia os textos
    divergirem, vale o mais restritivo dos dois, e o embed pode morrer sem que
    ninguém tenha mexido no que parecia ser o arquivo certo.
    """
    assert api.CSP == csp_do_vercel_json()


def test_a_csp_libera_o_embed_no_notion():
    assert "frame-ancestors https://www.notion.so https://notion.so" in api.CSP


def test_a_csp_nao_libera_estilo_inline():
    """Se um dia liberar, o teste abaixo deixa de fazer sentido e some junto."""
    diretiva = re.search(r"style-src([^;]*)", api.CSP)
    assert diretiva, "a CSP precisa declarar style-src explicitamente"
    assert "'unsafe-inline'" not in diretiva.group(1)


def test_o_front_nao_usa_atributo_style_inline():
    """Estilo inline seria descartado em produção sem erro nenhum."""
    culpados = [
        f"{caminho.name}: {trecho[:60]}"
        for caminho in sorted(DASHBOARD.glob("*.html")) + sorted(DASHBOARD.glob("*.js"))
        for trecho in re.findall(r"style\s*=\s*[\"'][^\"']+", caminho.read_text(encoding="utf-8"))
    ]
    assert not culpados, (
        "estilo inline não sobrevive à CSP de produção; "
        f"use element.style via CSSOM. Encontrado em: {culpados}"
    )


def test_o_front_nao_usa_script_nem_estilo_embutido_no_html():
    """`script-src 'self'` também barra <script> e <style> escritos na página."""
    html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\ssrc=)", html), "<script> sem src é bloqueado"
    assert "<style" not in html, "<style> embutido é bloqueado"


def test_a_barra_tem_largura_zero_por_padrao():
    """Falhar visível é melhor que falhar cheia num gráfico financeiro."""
    css = (DASHBOARD / "style.css").read_text(encoding="utf-8")
    regra = re.search(r"\.track i\{([^}]*)\}", css)
    assert regra, "faltou a regra .track i no CSS"
    assert "width:0" in regra.group(1).replace(" ", "")
