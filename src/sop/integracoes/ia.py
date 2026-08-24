"""Camada de IA: transforma texto livre em uma classificação estruturada.

Dois backends com a mesma interface:

- `ClassificadorAnthropic` — usa a Messages API com *structured output*, então
  a resposta é validada contra um JSON Schema pela própria API. Não há parsing
  frágil de texto do modelo.
- `ClassificadorHeuristico` — palavras-chave e expressões regulares, sem rede.
  Existe para que o projeto rode, seja demonstrável e seja testável sem
  nenhuma credencial. É o fallback automático quando não há chave de API.

A troca é transparente: `criar_adaptador()` escolhe o backend disponível e o
resto do sistema não sabe qual está em uso (só o campo `origem` denuncia).
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Protocol

from ..config import Config
from ..datas import normalizar_data, resolver_data, resolver_hora
from ..modelos import Classificacao

# JSON Schema entregue à API — garante que a resposta já venha no formato certo.
ESQUEMA_CLASSIFICACAO: dict[str, Any] = {
    "type": "object",
    "properties": {
        "agente": {"type": "string"},
        "categoria": {"type": "string"},
        "titulo": {"type": "string"},
        "data": {"type": ["string", "null"]},
        "hora": {"type": ["string", "null"]},
        "duracao_minutos": {"type": ["integer", "null"]},
        "valor": {"type": ["number", "null"]},
        "projeto": {"type": ["string", "null"]},
        "disciplina": {"type": ["string", "null"]},
        "estado": {"type": ["string", "null"]},
        "recorrencia": {"type": ["string", "null"]},
        "observacao": {"type": "string"},
        "precisa_confirmacao": {"type": "boolean"},
        "confianca": {"type": "number"},
    },
    "required": [
        "agente",
        "categoria",
        "titulo",
        "observacao",
        "precisa_confirmacao",
        "confianca",
    ],
    "additionalProperties": False,
}


class AdaptadorIA(Protocol):
    """Interface mínima que a orquestradora consome."""

    origem: str

    def classificar(self, texto: str, registro: Any, hoje: date) -> Classificacao: ...


# ---------------------------------------------------------------------------
# Backend heurístico (sem rede, sem credencial)
# ---------------------------------------------------------------------------

# Ordem importa: a primeira categoria cujo padrão casar é a escolhida.
PADROES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("financeira", "meta", (r"\bmeta\b", r"\bjuntar\b", r"\beconomizar\b", r"\bguardar\b.*\breais?\b")),
    ("financeira", "receita", (r"\brecebi\b", r"\bentrou\b.*\bconta\b", r"\bsal[aá]rio\b", r"\bpagamento recebido\b")),
    ("financeira", "gasto", (r"\bgastei\b", r"\bpaguei\b", r"\bcustou\b", r"r\$\s*\d", r"\bcomprei\b.*\bpor\b")),
    ("educacional", "flashcard", (r"\bflashcard\b", r"\bcart[ãa]o de revis[ãa]o\b", r"\brevis[ãa]o espa[çc]ada\b")),
    ("educacional", "material", (r"\bler\b.*\b(livro|artigo|apostila|cap[íi]tulo)\b", r"\bmaterial\b", r"\bapostila\b")),
    ("educacional", "estudo", (r"\bestudar\b", r"\bestudo\b", r"\brevisar\b", r"\bdisciplina\b", r"\bprova\b")),
    ("projetos", "metrica", (r"\bm[ée]trica\b", r"\bindicador\b", r"\bkpi\b")),
    ("projetos", "marco", (r"\bentrega\b", r"\bmarco\b", r"\bdeadline\b", r"\bprazo final\b")),
    ("projetos", "tarefa", (r"\bprojeto\b", r"\bkanban\b", r"\btarefa\b", r"\bpr[óo]ximo passo\b", r"\bcarreira\b")),
    ("lifestyle", "compras", (r"\bcomprar\b", r"\bacabou\b", r"\blista de (compras|mercado)\b", r"\bfalta\b.*\bcasa\b", r"\bmercado\b")),
    ("lifestyle", "cardapio", (r"\bcard[áa]pio\b", r"\bjantar\b", r"\balmo[çc]o\b", r"\breceita\b", r"\bcozinhar\b")),
    ("lifestyle", "limpeza", (r"\blimpar\b", r"\bfaxina\b", r"\blavar\b", r"\barrumar a casa\b", r"\bpassar roupa\b")),
    ("lifestyle", "rotina_familiar", (r"\bcrian[çc]as?\b", r"\bescola\b", r"\brotina da casa\b", r"\bfilhos?\b")),
    ("secretaria", "mensagem", (r"\bresponder\b", r"\bretornar (a )?liga[çc][ãa]o\b", r"\bmandar mensagem\b", r"\bavisar\b")),
    ("secretaria", "lembrete", (r"\blembrar\b", r"\blembrete\b", r"\bn[ãa]o esquecer\b")),
    ("secretaria", "compromisso", (r"\breuni[ãa]o\b", r"\bconsulta\b", r"\bcompromisso\b", r"\bmarcar\b", r"\bencontro\b", r"\bagendar\b")),
)

_VALOR = re.compile(r"r\$\s*([\d.]+,\d{2}|[\d.]+)", re.IGNORECASE)
_RUIDO_INICIAL = re.compile(
    r"^(preciso de|preciso|tenho que|tenho de|lembrar de|lembra de|me lembra de|"
    r"por favor|anota(r| a[ií])?|adiciona(r)?|coloca(r)?)\s+",
    re.IGNORECASE,
)


def extrair_valor(texto: str) -> float | None:
    """Extrai um valor monetário do texto. Sem número, devolve None.

    Nunca inventa: a regra financeira do projeto é que valor ausente vira
    pedido de confirmação, não um palpite.
    """
    achado = _VALOR.search(texto)
    if not achado:
        return None
    bruto = achado.group(1)
    if "," in bruto:
        bruto = bruto.replace(".", "").replace(",", ".")
    try:
        return float(bruto)
    except ValueError:
        return None


def resumir_titulo(texto: str, limite: int = 80) -> str:
    """Reduz a mensagem a um título curto e legível."""
    limpo = " ".join(texto.split())
    limpo = _RUIDO_INICIAL.sub("", limpo).strip()
    limpo = limpo[0].upper() + limpo[1:] if limpo else limpo
    return limpo if len(limpo) <= limite else limpo[: limite - 1].rstrip() + "…"


class ClassificadorHeuristico:
    """Classificação por palavras-chave. Roda offline e sem credencial."""

    origem = "heuristica"

    def classificar(self, texto: str, registro: Any = None, hoje: date | None = None) -> Classificacao:
        hoje = hoje or date.today()
        minusculo = texto.lower()

        agente, categoria, confianca = "secretaria", "lembrete", 0.3
        for nome_agente, nome_categoria, padroes in PADROES:
            if any(re.search(p, minusculo) for p in padroes):
                agente, categoria, confianca = nome_agente, nome_categoria, 0.7
                break

        data = resolver_data(texto, hoje)
        hora = resolver_hora(texto) if data else None
        valor = extrair_valor(texto) if agente == "financeira" else None

        # Regra do agente Financeira: sem valor explícito, ninguém adivinha.
        precisa_confirmacao = agente == "financeira" and categoria in ("gasto", "receita") and valor is None

        return Classificacao(
            agente=agente,
            categoria=categoria,
            titulo=resumir_titulo(texto),
            data=data,
            hora=hora,
            duracao_minutos=60 if categoria == "compromisso" and hora else None,
            valor=valor,
            estado="backlog" if agente == "projetos" and categoria == "tarefa" else None,
            observacao="" if len(texto) <= 80 else texto.strip(),
            precisa_confirmacao=precisa_confirmacao,
            confianca=confianca,
            origem=self.origem,
        )


# ---------------------------------------------------------------------------
# Backend Anthropic (Messages API com structured output)
# ---------------------------------------------------------------------------

INSTRUCAO_BASE = """Você é a orquestradora de um sistema operacional pessoal.

Sua função é ler uma mensagem em linguagem natural e decidir qual agente
especializado deve cuidar dela, extraindo os campos estruturados.

Agentes disponíveis:
{catalogo}

Regras inegociáveis:
- Extraia apenas o que está no texto. Nunca invente data, hora, valor, nome de
  projeto ou disciplina.
- Datas sempre no formato AAAA-MM-DD; horas sempre HH:MM em 24 horas.
- Se a mensagem admitir leituras diferentes que mudem o resultado, marque
  precisa_confirmacao como true e explique a dúvida em observacao.
- O título deve ser curto, direto e sem preâmbulo.
- confianca vai de 0 a 1 e reflete o quanto a escolha do agente é evidente.

Hoje é {hoje}. Use essa data para resolver expressões relativas.
"""


class ClassificadorAnthropic:
    """Classificação via Messages API, com resposta validada por JSON Schema."""

    origem = "ia"

    def __init__(self, config: Config, cliente: Any | None = None) -> None:
        self.config = config
        if cliente is not None:
            self.cliente = cliente
        else:
            import anthropic  # importado só quando o backend é realmente usado

            self.cliente = anthropic.Anthropic(api_key=config.anthropic_api_key)
        self._fallback = ClassificadorHeuristico()

    @staticmethod
    def montar_catalogo(registro: Any) -> str:
        if registro is None:
            return "- secretaria, lifestyle, financeira, projetos, educacional"
        linhas = []
        for agente in registro:
            categorias = ", ".join(agente.categorias)
            linhas.append(f"- {agente.nome} ({agente.dominio}) — categorias: {categorias}")
        return "\n".join(linhas)

    def instrucao(self, registro: Any, hoje: date) -> str:
        return INSTRUCAO_BASE.format(
            catalogo=self.montar_catalogo(registro), hoje=hoje.isoformat()
        )

    def classificar(self, texto: str, registro: Any = None, hoje: date | None = None) -> Classificacao:
        hoje = hoje or date.today()
        resposta = self.cliente.messages.create(
            model=self.config.anthropic_model,
            max_tokens=2000,
            system=self.instrucao(registro, hoje),
            output_config={
                "format": {"type": "json_schema", "schema": ESQUEMA_CLASSIFICACAO}
            },
            messages=[{"role": "user", "content": texto}],
        )

        if getattr(resposta, "stop_reason", None) == "refusal":
            return self._fallback.classificar(texto, registro, hoje)

        bruto = next(
            (bloco.text for bloco in resposta.content if bloco.type == "text"), ""
        )
        dados = json.loads(bruto)
        return self._para_classificacao(dados, registro, hoje)

    def _para_classificacao(self, dados: dict[str, Any], registro: Any, hoje: date) -> Classificacao:
        agente = str(dados.get("agente", "")).strip()
        categoria = str(dados.get("categoria", "")).strip()

        # Se o modelo devolver um agente que não existe, resolve pela categoria.
        if registro is not None and agente not in registro:
            pela_categoria = registro.por_categoria(categoria)
            agente = pela_categoria.nome if pela_categoria else "secretaria"

        return Classificacao(
            agente=agente or "secretaria",
            categoria=categoria or "lembrete",
            titulo=str(dados.get("titulo", "")).strip() or "(sem título)",
            data=normalizar_data(dados.get("data"), hoje),
            hora=dados.get("hora") or None,
            duracao_minutos=dados.get("duracao_minutos"),
            valor=dados.get("valor"),
            projeto=dados.get("projeto") or None,
            disciplina=dados.get("disciplina") or None,
            estado=dados.get("estado") or None,
            recorrencia=dados.get("recorrencia") or None,
            observacao=str(dados.get("observacao", "")),
            precisa_confirmacao=bool(dados.get("precisa_confirmacao", False)),
            confianca=float(dados.get("confianca", 0.0)),
            origem=self.origem,
        )


def criar_adaptador(config: Config, cliente: Any | None = None) -> AdaptadorIA:
    """Escolhe o backend disponível.

    Com chave de API e o pacote `anthropic` instalado, usa a IA. Sem isso, cai
    no heurístico — o sistema continua funcionando, apenas com menos precisão.
    """
    if cliente is not None:
        return ClassificadorAnthropic(config, cliente=cliente)
    if not config.anthropic_api_key:
        return ClassificadorHeuristico()
    try:
        return ClassificadorAnthropic(config)
    except ImportError:
        return ClassificadorHeuristico()
