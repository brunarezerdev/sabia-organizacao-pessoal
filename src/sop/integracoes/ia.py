"""Camada de IA: transforma texto livre em uma classificação estruturada.

Quatro backends com a mesma interface, para que o provedor continue trocável:

- `ClassificadorOpenClaw` — despacha para o agente principal rodando dentro do
  OpenClaw, que é onde o provedor escolhido (`openai`, rota Codex) está
  autenticado. É o caminho de produção do projeto.
- `ClassificadorOpenAI` — rota alternativa por API key, para quem preferir
  chamar a API direto em vez de passar pelo OpenClaw. **Não** é a rota Codex:
  o Codex CLI autentica por OAuth e não tem API key.
- `ClassificadorAnthropic` — Messages API com *structured output*, validado
  contra JSON Schema pela própria API.
- `ClassificadorHeuristico` — palavras-chave e expressões regulares, sem rede.
  Existe para que o projeto rode, seja demonstrável e seja testável sem
  nenhuma credencial. É o fallback automático quando não há nada configurado.

A troca é transparente: `criar_adaptador()` escolhe o backend disponível e o
resto do sistema não sabe qual está em uso (só o campo `origem` denuncia).
Trocar de provedor não exige mexer na orquestradora nem nos agentes.
"""

from __future__ import annotations

import json
import re
import subprocess
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
        "pergunta_confirmacao": {"type": ["string", "null"]},
        "lacuna_secundaria": {"type": ["string", "null"]},
        "confianca": {"type": "number"},
    },
    "required": [
        "agente",
        "categoria",
        "titulo",
        "observacao",
        "precisa_confirmacao",
        "pergunta_confirmacao",
        "lacuna_secundaria",
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
    ("esquilo", "meta", (r"\bmeta\b", r"\bjuntar\b", r"\beconomizar\b", r"\bguardar\b.*\breais?\b")),
    ("esquilo", "receita", (r"\brecebi\b", r"\bentrou\b.*\bconta\b", r"\bsal[aá]rio\b", r"\bpagamento recebido\b")),
    ("esquilo", "gasto", (r"\bgastei\b", r"\bpaguei\b", r"\bcustou\b", r"r\$\s*\d", r"\bcomprei\b.*\bpor\b")),
    ("borboleta", "flashcard", (r"\bflashcard\b", r"\bcart[ãa]o de revis[ãa]o\b", r"\brevis[ãa]o espa[çc]ada\b")),
    ("borboleta", "material", (r"\bler\b.*\b(livro|artigo|apostila|cap[íi]tulo)\b", r"\bmaterial\b", r"\bapostila\b")),
    ("borboleta", "curso", (r"\bcurso\b", r"\bmatr[íi]cula\b", r"\bmatricular\b", r"\bcertifica[çc][ãa]o\b", r"\bforma[çc][ãa]o\b", r"\bgradua[çc][ãa]o\b")),
    ("borboleta", "aprendizado", (r"\bdesenvolvimento pessoal\b", r"\baprend(er|izado|izagem)\b", r"\bh[áa]bito(s)? de (estudo|leitura|aprendizado)\b")),
    # A ação "lembrar de entregar" é um aviso, mesmo quando o objeto é um
    # documento. Precisa vir antes do roteamento de arquivo do Elefante.
    ("beija-flor", "lembrete", (r"\blembrar de (entregar|levar|enviar|buscar)\b",)),
    ("elefante", "documento", (r"\bdocumento\b", r"\bgarantia\b", r"\bcontrato\b", r"\bcertid[ãa]o\b", r"\bcomprovante\b")),
    # `registro` é decisão tomada e histórico, não anotação em geral: os padrões
    # são estreitos de propósito para não engolir o resto do roteamento.
    ("elefante", "registro", (r"\bdecis[ãa]o\b", r"\bdecidimos\b", r"\bficou decidido\b", r"\bhist[óo]rico\b")),
    ("borboleta", "estudo", (r"\bestudar\b", r"\bestudo\b", r"\brevisar\b", r"\bdisciplina\b", r"\bprova\b")),
    ("raposa", "metrica", (r"\bm[ée]trica\b", r"\bindicador\b", r"\bkpi\b")),
    ("raposa", "marco", (r"\bentrega\b", r"\bmarco\b", r"\bdeadline\b", r"\bprazo final\b")),
    ("raposa", "tarefa", (r"\bprojeto\b", r"\bkanban\b", r"\btarefa\b", r"\bpr[óo]ximo passo\b", r"\bcarreira\b")),
    ("esquilo", "compras", (r"\bcomprar\b", r"\bacabou\b", r"\blista de (compras|mercado)\b", r"\bfalta\b.*\bcasa\b", r"\bmercado\b")),
    # `estoque` vem depois de `compras` de propósito: "acabou o café" é um
    # pedido de reposição, não uma leitura da despensa.
    ("esquilo", "estoque", (r"\bdespensa\b", r"\bestoque\b", r"\brepor\b", r"\bquantidade m[íi]nima\b")),
    ("cervo", "cardapio", (r"\bcard[áa]pio\b", r"\bjantar\b", r"\balmo[çc]o\b", r"\breceita\b", r"\bcozinhar\b")),
    ("abelha", "limpeza", (r"\blimpar\b", r"\bfaxina\b", r"\blavar\b", r"\barrumar a casa\b", r"\bpassar roupa\b")),
    ("cervo", "familia", (r"\bcrian[çc]as?\b", r"\bescola\b", r"\bfilhos?\b", r"\bpediatra\b")),
    ("abelha", "rotina", (r"\brotina\b", r"\bh[áa]bito\b", r"\btodo dia\b", r"\btoda (semana|manh[ãa]|noite)\b", r"\bcheck ?list\b")),
    ("beija-flor", "mensagem", (r"\bresponder\b", r"\bretornar (a )?liga[çc][ãa]o\b", r"\bmandar mensagem\b", r"\bavisar\b")),
    ("beija-flor", "lembrete", (r"\blembrar\b", r"\blembrete\b", r"\bn[ãa]o esquecer\b")),
    ("beija-flor", "compromisso", (r"\breuni[ãa]o\b", r"\bconsulta\b", r"\bcompromisso\b", r"\bmarcar\b", r"\bencontro\b", r"\bagendar\b")),
)

_VALOR = re.compile(r"r\$\s*([\d.]+,\d{2}|[\d.]+)", re.IGNORECASE)
_NUMERO = re.compile(r"\b\d+(?:[.,]\d+)?\b")
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

        agente, categoria, confianca = "beija-flor", "lembrete", 0.3
        for nome_agente, nome_categoria, padroes in PADROES:
            if any(re.search(p, minusculo) for p in padroes):
                agente, categoria, confianca = nome_agente, nome_categoria, 0.7
                break

        data = resolver_data(texto, hoje)
        hora = resolver_hora(texto) if data else None
        valor = extrair_valor(texto) if agente == "esquilo" else None

        # O fallback também respeita a política de lacunas. Pergunta apenas o
        # dado que impede uma execução útil; detalhes opcionais não viram um
        # interrogatório.
        pergunta_confirmacao = None
        lacuna_secundaria = None
        if agente == "esquilo" and categoria in ("gasto", "receita") and valor is None:
            pergunta_confirmacao = "Qual foi o valor?"
        elif agente == "esquilo" and categoria == "compras" and not _NUMERO.search(texto):
            pergunta_confirmacao = "Qual quantidade devo adicionar?"
        elif agente == "abelha" and categoria == "rotina" and not re.search(
            r"\b(todo dia|toda (semana|manh[ãa]|noite)|di[aá]ri[oa]|semanal|quinzenal|mensal)\b",
            minusculo,
        ):
            pergunta_confirmacao = "Com que frequência essa rotina deve se repetir?"
        elif agente == "borboleta" and categoria == "flashcard" and not re.search(
            r"\bresposta\b|\?\s*.+", texto, re.IGNORECASE
        ):
            pergunta_confirmacao = "Qual é a resposta do flashcard?"
        elif agente == "borboleta" and categoria in ("aprendizado", "estudo") and re.search(
            r"\bh[áa]bito\b", minusculo
        ) and not re.search(
            r"\b(todo dia|toda semana|di[aá]ri[oa]|semanal|\d+\s*(vez|vezes))\b",
            minusculo,
        ):
            pergunta_confirmacao = "Com que frequência você quer praticar?"
        elif agente == "raposa" and categoria == "metrica" and not _NUMERO.search(texto):
            pergunta_confirmacao = "Qual valor devo registrar para essa métrica?"
        elif agente == "elefante" and categoria == "documento" and not re.search(
            r"\b(guardar|arquivar|consultar|buscar|procurar|encontrar)\b", minusculo
        ):
            pergunta_confirmacao = "Você quer guardar esse documento ou consultá-lo?"
        elif agente == "cervo" and categoria == "familia" and not re.search(
            r"\b(meu|minha|filh[oa]s?|crian[çc]as?|m[ãa]e|pai|esposa|marido)\b|"
            r"\b(de|da|do)\s+[A-ZÁÉÍÓÚ][a-záéíóú]+\b",
            texto,
        ):
            pergunta_confirmacao = "De quem da família é esse item?"
        elif agente == "beija-flor" and categoria in ("lembrete", "compromisso"):
            if data is None:
                pergunta_confirmacao = "Para que dia devo programar?"
            elif hora is None and not re.search(r"\bdia inteiro\b", minusculo):
                pergunta_confirmacao = "Em que horário devo avisar?"

        precisa_confirmacao = pergunta_confirmacao is not None

        return Classificacao(
            agente=agente,
            categoria=categoria,
            titulo=resumir_titulo(texto),
            data=data,
            hora=hora,
            duracao_minutos=60 if categoria == "compromisso" and hora else None,
            valor=valor,
            estado="backlog" if agente == "raposa" and categoria == "tarefa" else None,
            observacao="" if len(texto) <= 80 else texto.strip(),
            precisa_confirmacao=precisa_confirmacao,
            pergunta_confirmacao=pergunta_confirmacao,
            lacuna_secundaria=lacuna_secundaria,
            confianca=confianca,
            origem=self.origem,
        )


# ---------------------------------------------------------------------------
# Backend Anthropic (Messages API com structured output)
# ---------------------------------------------------------------------------

# O prompt da orquestradora mora em `agentes/_orquestradora.md`, o mesmo arquivo
# que vira o SOUL.md do agente principal no OpenClaw. Escrito uma vez, usado nas
# duas pontas: se ele mudar, muda para os dois.
_FALLBACK_INSTRUCAO = """Você é a orquestradora de um sistema operacional pessoal.

Leia a mensagem, decida qual agente cuida dela e extraia os campos.

Agentes disponíveis:
{catalogo}

Nunca invente dados. Se faltar informação essencial, marque precisa_confirmacao
e faça uma pergunta curta em pergunta_confirmacao. Se faltar apenas detalhe
secundário, descreva-o em lacuna_secundaria.

Hoje é {hoje}.
"""


def carregar_instrucao_base() -> str:
    """Lê a alma da orquestradora, com os marcadores ainda por preencher."""
    from ..agentes import carregar_orquestradora

    orquestradora = carregar_orquestradora()
    if orquestradora is None or not orquestradora.prompt.strip():
        return _FALLBACK_INSTRUCAO
    return orquestradora.prompt


INSTRUCAO_BASE = carregar_instrucao_base()


def montar_catalogo(registro: Any) -> str:
    """Descreve os agentes disponíveis para o modelo."""
    if registro is None:
        return "- raposa, abelha, esquilo, cervo, elefante, borboleta, beija-flor"
    return "\n".join(
        f"- {agente.nome} ({agente.dominio}) — categorias: {', '.join(agente.categorias)}"
        for agente in registro
    )


def montar_instrucao(registro: Any, hoje: date) -> str:
    return INSTRUCAO_BASE.replace("{catalogo}", montar_catalogo(registro)).replace(
        "{hoje}", hoje.isoformat()
    )


def extrair_json(bruto: str) -> dict[str, Any]:
    """Recupera o objeto JSON de uma saída que pode vir com texto em volta.

    Um agente conversacional às vezes embrulha o JSON em cerca de código ou
    numa frase de cortesia. Exigir saída limpa quebraria na primeira vez que
    isso acontecesse, então o parsing tolera a moldura em vez de estourar.
    """
    texto = bruto.strip()
    if not texto:
        raise ValueError("resposta vazia do modelo")

    cerca = re.search(r"```(?:json)?\s*(.+?)```", texto, re.DOTALL)
    if cerca:
        texto = cerca.group(1).strip()

    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        pass

    inicio, fim = texto.find("{"), texto.rfind("}")
    if inicio == -1 or fim <= inicio:
        raise ValueError(f"nenhum JSON encontrado na resposta: {bruto[:120]!r}")
    return json.loads(texto[inicio : fim + 1])


class _BaseClassificador:
    """Parte comum: instrução, catálogo e conversão do JSON em Classificacao."""

    origem = "ia"

    @staticmethod
    def montar_catalogo(registro: Any) -> str:
        return montar_catalogo(registro)

    def instrucao(self, registro: Any, hoje: date) -> str:
        return montar_instrucao(registro, hoje)

    def _para_classificacao(
        self, dados: dict[str, Any], registro: Any, hoje: date
    ) -> Classificacao:
        agente = str(dados.get("agente", "")).strip()
        categoria = str(dados.get("categoria", "")).strip()

        # Se o modelo devolver um agente que não existe, resolve pela categoria.
        if registro is not None and agente not in registro:
            pela_categoria = registro.por_categoria(categoria)
            agente = pela_categoria.nome if pela_categoria else "beija-flor"

        pergunta_confirmacao = (
            str(dados.get("pergunta_confirmacao") or "").strip() or None
        )
        precisa_confirmacao = bool(dados.get("precisa_confirmacao", False)) or bool(
            pergunta_confirmacao
        )

        return Classificacao(
            agente=agente or "beija-flor",
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
            # `str(None)` viraria a string "None" gravada no Notion. O modelo
            # devolve `null` sempre que não tem observação, então o caso é o
            # comum, não a exceção.
            observacao=str(dados.get("observacao") or ""),
            precisa_confirmacao=precisa_confirmacao,
            pergunta_confirmacao=pergunta_confirmacao,
            lacuna_secundaria=(
                str(dados.get("lacuna_secundaria") or "").strip() or None
            ),
            confianca=float(dados.get("confianca", 0.0)),
            origem=self.origem,
        )


class ClassificadorAnthropic(_BaseClassificador):
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
        return self._para_classificacao(extrair_json(bruto), registro, hoje)


# ---------------------------------------------------------------------------
# Backend OpenClaw (o caminho de produção)
# ---------------------------------------------------------------------------


class ClassificadorOpenClaw(_BaseClassificador):
    """Delega a triagem ao agente principal rodando dentro do OpenClaw.

    O provedor de IA (hoje `openai`, rota Codex) está autenticado no OpenClaw,
    não aqui. Este backend não conhece chave nenhuma: ele monta a instrução,
    entrega ao CLI pela entrada padrão e lê o JSON da saída. Trocar o provedor
    é um `openclaw models set`, sem tocar em uma linha deste arquivo.

    O comando exato vem de `OPENCLAW_COMANDO` porque a invocação não
    interativa do CLI é um ponto a confirmar na máquina onde ele estiver
    instalado (ver docs/openclaw.md). Sem essa variável, o backend se declara
    indisponível e o sistema cai no heurístico em vez de chutar um comando.
    """

    origem = "openclaw"

    def __init__(
        self,
        config: Config,
        executor: Any | None = None,
    ) -> None:
        self.config = config
        self.comando = config.openclaw_comando_partido()
        if not self.comando:
            raise ValueError(
                "OPENCLAW_COMANDO não definido — sem ele não dá para invocar o CLI."
            )
        self._executor = executor or self._rodar
        self._fallback = ClassificadorHeuristico()

    def _rodar(self, comando: list[str], entrada: str) -> str:
        try:
            processo = subprocess.run(
                comando,
                input=entrada,
                capture_output=True,
                text=True,
                timeout=self.config.openclaw_timeout,
                check=False,
            )
        except FileNotFoundError as erro:
            raise RuntimeError(
                f"CLI do OpenClaw não encontrado ({comando[0]}). "
                "Rode scripts/openclaw/instalar.sh."
            ) from erro
        except subprocess.TimeoutExpired as erro:
            raise RuntimeError(
                f"OpenClaw não respondeu em {self.config.openclaw_timeout}s."
            ) from erro

        if processo.returncode != 0:
            detalhe = (processo.stderr or processo.stdout or "").strip()[:300]
            raise RuntimeError(f"OpenClaw saiu com código {processo.returncode}: {detalhe}")
        return processo.stdout

    def classificar(
        self, texto: str, registro: Any = None, hoje: date | None = None
    ) -> Classificacao:
        hoje = hoje or date.today()
        entrada = f"{self.instrucao(registro, hoje)}\n\nMensagem:\n{texto}\n"
        bruto = self._executor(self.comando, entrada)
        try:
            dados = extrair_json(bruto)
        except (ValueError, json.JSONDecodeError):
            # Uma resposta ilegível não pode custar o registro da pessoa: o
            # heurístico assume e o item entra marcado com origem heuristica.
            return self._fallback.classificar(texto, registro, hoje)
        return self._para_classificacao(dados, registro, hoje)


# ---------------------------------------------------------------------------
# Backend OpenAI por API key (rota alternativa, NÃO é o Codex)
# ---------------------------------------------------------------------------


class ClassificadorOpenAI(_BaseClassificador):
    """Chama a API da OpenAI direto, com chave.

    Existe para manter o provedor trocável: se um dia a escolha for uma rota
    com API key em vez do OpenClaw, basta preencher `OPENAI_API_KEY`. Isso
    **não** substitui nem reproduz a rota Codex, que autentica por OAuth e não
    aceita chave de API.
    """

    origem = "openai"

    def __init__(self, config: Config, cliente: Any | None = None) -> None:
        self.config = config
        if cliente is not None:
            self.cliente = cliente
        else:
            import openai  # importado só quando o backend é realmente usado

            self.cliente = openai.OpenAI(api_key=config.openai_api_key)
        self._fallback = ClassificadorHeuristico()

    def classificar(
        self, texto: str, registro: Any = None, hoje: date | None = None
    ) -> Classificacao:
        hoje = hoje or date.today()
        resposta = self.cliente.chat.completions.create(
            model=self.config.openai_model,
            messages=[
                {"role": "system", "content": self.instrucao(registro, hoje)},
                {"role": "user", "content": texto},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "classificacao",
                    "schema": ESQUEMA_CLASSIFICACAO,
                    "strict": False,
                },
            },
        )
        bruto = resposta.choices[0].message.content or ""
        try:
            dados = extrair_json(bruto)
        except (ValueError, json.JSONDecodeError):
            return self._fallback.classificar(texto, registro, hoje)
        return self._para_classificacao(dados, registro, hoje)


# ---------------------------------------------------------------------------
# Escolha do backend
# ---------------------------------------------------------------------------

BACKENDS = ("openclaw", "openai", "anthropic", "heuristica")


def criar_adaptador(config: Config, cliente: Any | None = None) -> AdaptadorIA:
    """Escolhe o backend, respeitando `IA_BACKEND` quando ela está definida.

    Sem escolha explícita, a ordem é a da preferência do projeto: OpenClaw
    primeiro (é onde o provedor está autenticado), depois as rotas por chave e,
    por último, o heurístico — que não precisa de nada e sempre funciona.

    Nenhum caminho aqui levanta exceção por falta de credencial. Não conseguir
    usar IA degrada a precisão; não deve derrubar o sistema.
    """
    if cliente is not None:
        return ClassificadorAnthropic(config, cliente=cliente)

    escolhido = (config.ia_backend or "").strip().lower()
    if escolhido == "heuristica":
        return ClassificadorHeuristico()

    tentativas = [escolhido] if escolhido else ["openclaw", "openai", "anthropic"]
    for backend in tentativas:
        try:
            if backend == "openclaw" and config.openclaw_comando:
                return ClassificadorOpenClaw(config)
            if backend == "openai" and config.openai_api_key:
                return ClassificadorOpenAI(config)
            if backend == "anthropic" and config.anthropic_api_key:
                return ClassificadorAnthropic(config)
        except (ImportError, ValueError):
            continue

    return ClassificadorHeuristico()
