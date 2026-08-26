"""Carrega as definições de agente a partir dos arquivos em `agentes/`.

Cada agente vive em um arquivo Markdown próprio, com um cabeçalho YAML simples
(parseado aqui sem dependência externa) e o prompt no corpo. Adicionar um
agente novo é criar um arquivo — não há lista fixa no código.

O mesmo arquivo alimenta as duas pontas: o roteamento em Python e a declaração
OpenClaw (`src/sop/openclaw.py`), que gera o `SOUL.md` de cada workspace. O
prompt é escrito uma vez só.

Arquivos que começam com `_` são carregados por nome, mas ficam fora do
registro de roteamento. É assim que a orquestradora (`_orquestradora.md`) mora
no mesmo diretório sem virar um sexto agente de domínio.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
DIR_AGENTES = RAIZ / "agentes"


@dataclass(frozen=True)
class AgenteDef:
    """Um agente especializado: identidade, domínio e prompt."""

    nome: str
    titulo: str
    dominio: str
    categorias: tuple[str, ...]
    integracoes: tuple[str, ...]
    cria_evento: bool
    prompt: str
    caminho: Path | None = None
    # Campos que só a camada OpenClaw consome. Ausentes, o agente continua
    # funcionando no roteamento em Python — a declaração é que fica mais pobre.
    emoji: str = ""
    tools: tuple[str, ...] = ()
    modelo: str = ""
    openclaw_ativo: bool = True

    def aceita(self, categoria: str) -> bool:
        return categoria in self.categorias


@dataclass
class Registro:
    """Coleção de agentes, indexada por nome e por categoria."""

    agentes: dict[str, AgenteDef] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.agentes)

    def __iter__(self):
        return iter(self.agentes.values())

    def __contains__(self, nome: object) -> bool:
        return nome in self.agentes

    def obter(self, nome: str) -> AgenteDef | None:
        return self.agentes.get(nome)

    def nomes(self) -> list[str]:
        return sorted(self.agentes)

    def por_categoria(self, categoria: str) -> AgenteDef | None:
        for agente in self.agentes.values():
            if agente.aceita(categoria):
                return agente
        return None

    def categorias(self) -> list[str]:
        vistas: list[str] = []
        for agente in self.agentes.values():
            for categoria in agente.categorias:
                if categoria not in vistas:
                    vistas.append(categoria)
        return vistas


def _ler_frontmatter(conteudo: str) -> tuple[dict[str, object], str]:
    """Parser mínimo de frontmatter YAML: escalares e listas com hífen.

    Suficiente para o formato usado aqui e evita uma dependência a mais em um
    repositório que precisa rodar sem instalação pesada.
    """
    if not conteudo.startswith("---"):
        return {}, conteudo

    partes = conteudo.split("---", 2)
    if len(partes) < 3:
        return {}, conteudo

    cabecalho, corpo = partes[1], partes[2]
    dados: dict[str, object] = {}
    chave_lista: str | None = None

    for linha in cabecalho.splitlines():
        if not linha.strip() or linha.strip().startswith("#"):
            continue
        if linha.lstrip().startswith("- ") and chave_lista:
            item = linha.lstrip()[2:].strip()
            lista = dados.setdefault(chave_lista, [])
            assert isinstance(lista, list)
            lista.append(item)
            continue
        if ":" not in linha:
            continue
        chave, valor = linha.split(":", 1)
        chave, valor = chave.strip(), valor.strip()
        if not valor:
            dados[chave] = []
            chave_lista = chave
        else:
            chave_lista = None
            if valor.lower() in ("true", "false"):
                dados[chave] = valor.lower() == "true"
            else:
                dados[chave] = valor.strip('"').strip("'")

    return dados, corpo.strip()


def carregar_agente(caminho: Path) -> AgenteDef:
    """Lê um arquivo de agente e devolve sua definição."""
    dados, prompt = _ler_frontmatter(caminho.read_text(encoding="utf-8"))
    nome = str(dados.get("nome") or caminho.stem)

    def lista(chave: str) -> tuple[str, ...]:
        valor = dados.get(chave) or []
        return tuple(valor) if isinstance(valor, list) else ()

    return AgenteDef(
        nome=nome,
        titulo=str(dados.get("titulo") or nome.capitalize()),
        dominio=str(dados.get("dominio") or ""),
        categorias=lista("categorias"),
        integracoes=lista("integracoes"),
        cria_evento=bool(dados.get("cria_evento", False)),
        prompt=prompt,
        caminho=caminho,
        emoji=str(dados.get("emoji") or ""),
        tools=lista("tools"),
        modelo=str(dados.get("modelo") or ""),
        openclaw_ativo=bool(dados.get("openclaw_ativo", True)),
    )


def carregar_registro(diretorio: Path | None = None) -> Registro:
    """Carrega os agentes de domínio de um diretório.

    Arquivos prefixados com `_` são ignorados aqui de propósito: eles existem
    para a camada OpenClaw (a orquestradora), não para o roteamento.
    """
    diretorio = diretorio or DIR_AGENTES
    registro = Registro()
    if not diretorio.is_dir():
        return registro
    for caminho in sorted(diretorio.glob("*.md")):
        if caminho.name.startswith("_"):
            continue
        agente = carregar_agente(caminho)
        registro.agentes[agente.nome] = agente
    return registro


def carregar_orquestradora(diretorio: Path | None = None) -> AgenteDef | None:
    """Carrega a definição da orquestradora, o agente principal do OpenClaw."""
    diretorio = diretorio or DIR_AGENTES
    caminho = diretorio / "_orquestradora.md"
    return carregar_agente(caminho) if caminho.is_file() else None
