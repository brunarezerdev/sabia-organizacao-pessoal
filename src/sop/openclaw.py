"""Declaração OpenClaw: um agente por workspace, tools restritas, modelo por agente.

O OpenClaw guarda a configuração real em `~/.openclaw/openclaw.json`, e esse
arquivo **não é escrito à mão** — na versão 2026.6.5 o schema valida na escrita
e o CLI recusa um `agents.list` substituído por patch. Quem escreve lá é o
próprio CLI (`openclaw config patch`, `openclaw agents add`).

Então este módulo não gera `openclaw.json`. Ele gera duas coisas que o CLI
consome:

1. `openclaw/agentes.json` — a declaração central **do projeto**: qual é o
   agente principal, quais são os subagentes, o modelo e as tools de cada um.
   É a lista que `scripts/openclaw/registrar_agentes.sh` percorre chamando
   `openclaw agents add`.
2. `openclaw/workspaces/<id>/SOUL.md` — a alma de cada agente, copiada para o
   workspace dele durante a instalação.

As duas saídas são derivadas de `agentes/*.md`, que continua sendo a única
fonte de verdade. O prompt é escrito uma vez e serve tanto ao roteamento em
Python quanto ao agente rodando dentro do OpenClaw. `sop openclaw --verificar`
falha se as duas pontas saírem de sincronia.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .agentes import AgenteDef, Registro, carregar_orquestradora, carregar_registro

RAIZ = Path(__file__).resolve().parents[2]
DIR_OPENCLAW = RAIZ / "openclaw"
ARQUIVO_DECLARACAO = DIR_OPENCLAW / "agentes.json"
DIR_WORKSPACES = DIR_OPENCLAW / "workspaces"

# Versão fixada no bootstrap. O repositório de referência avisa que `@latest`
# quebra o polling do Telegram, então o pin é intencional, não descuido.
VERSAO_OPENCLAW = "2026.6.5"

# Provider `openai` + rota Codex pelo plugin nativo. A autenticação é OAuth por
# device-code, contra a assinatura ChatGPT Plus. Não existe API key para essa
# rota — ver docs/openclaw.md.
PROVEDOR_PADRAO = "openai"
MODELO_PADRAO = "openai/gpt-5.5"

BASE_PADRAO = "~/.openclaw"


@dataclass(frozen=True)
class PerfilOpenClaw:
    """Um agente do jeito que o OpenClaw precisa dele."""

    id: str
    nome: str
    emoji: str
    descricao: str
    modelo: str
    tools: tuple[str, ...]
    workspace: str
    alma: str
    principal: bool = False

    def para_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "nome": self.nome,
            "emoji": self.emoji,
            "descricao": self.descricao,
            "modelo": self.modelo,
            "tools": list(self.tools),
            "workspace": self.workspace,
            "alma": self.alma,
        }


@dataclass
class Declaracao:
    """A declaração inteira: ambiente, agente principal e subagentes."""

    principal: PerfilOpenClaw
    subagentes: list[PerfilOpenClaw] = field(default_factory=list)
    base: str = BASE_PADRAO
    modelo: str = MODELO_PADRAO

    def todos(self) -> list[PerfilOpenClaw]:
        return [self.principal, *self.subagentes]

    def para_dict(self) -> dict[str, object]:
        return {
            "_leia": (
                "Declaração do projeto, não é o openclaw.json. O openclaw.json "
                "é escrito pelo próprio CLI (config patch / agents add). "
                "Gerado por `python -m sop openclaw` a partir de agentes/*.md; "
                "não edite à mão."
            ),
            "openclaw": {
                "versao": VERSAO_OPENCLAW,
                "base": self.base,
                "gateway": {"mode": "local"},
                "provedor": {
                    "provider": PROVEDOR_PADRAO,
                    "modelo": self.modelo,
                    "auth": "oauth-device-code",
                    "observacao": (
                        "Rota Codex pelo plugin nativo, autenticada por OAuth "
                        "contra a assinatura ChatGPT Plus. Não usa API key."
                    ),
                },
            },
            "principal": self.principal.para_dict(),
            "subagentes": [perfil.para_dict() for perfil in self.subagentes],
        }

    def para_json(self) -> str:
        return json.dumps(self.para_dict(), ensure_ascii=False, indent=2) + "\n"


# ---------------------------------------------------------------------------
# Montagem
# ---------------------------------------------------------------------------


def _workspace_de(base: str, identificador: str, principal: bool) -> str:
    # O agente principal ocupa o workspace raiz; cada subagente tem o seu.
    sufixo = "workspace" if principal else f"workspace-{identificador}"
    return f"{base}/{sufixo}"


def perfil_de(
    agente: AgenteDef,
    base: str = BASE_PADRAO,
    modelo: str = MODELO_PADRAO,
    principal: bool = False,
) -> PerfilOpenClaw:
    """Converte a definição de um agente no perfil que o OpenClaw registra."""
    identificador = agente.nome
    return PerfilOpenClaw(
        id=identificador,
        nome=agente.titulo,
        emoji=agente.emoji,
        descricao=agente.dominio,
        # Modelo por agente: o do arquivo vence, senão cai no do projeto.
        modelo=agente.modelo or modelo,
        tools=agente.tools,
        workspace=_workspace_de(base, identificador, principal),
        alma=f"openclaw/workspaces/{identificador}/SOUL.md",
        principal=principal,
    )


def montar_declaracao(
    registro: Registro | None = None,
    orquestradora: AgenteDef | None = None,
    base: str = BASE_PADRAO,
    modelo: str = MODELO_PADRAO,
) -> Declaracao:
    """Monta a declaração completa a partir dos arquivos de agente."""
    registro = registro if registro is not None else carregar_registro()
    orquestradora = orquestradora or carregar_orquestradora()
    if orquestradora is None:
        raise RuntimeError(
            "agentes/_orquestradora.md não encontrado. "
            "É a alma do agente principal do OpenClaw."
        )

    return Declaracao(
        principal=perfil_de(orquestradora, base, modelo, principal=True),
        subagentes=[
            perfil_de(agente, base, modelo)
            for agente in registro
            if agente.openclaw_ativo
        ],
        base=base,
        modelo=modelo,
    )


# ---------------------------------------------------------------------------
# Alma (SOUL.md)
# ---------------------------------------------------------------------------


def montar_catalogo(registro: Registro) -> str:
    """Lista de agentes que a orquestradora enxerga, em texto."""
    return "\n".join(
        f"- {agente.nome} ({agente.dominio}) — categorias: {', '.join(agente.categorias)}"
        for agente in registro
        if agente.openclaw_ativo
    )


def montar_alma(
    agente: AgenteDef,
    perfil: PerfilOpenClaw,
    registro: Registro,
) -> str:
    """Gera o SOUL.md que vai para o workspace do agente.

    O corpo é o prompt já escrito em `agentes/<nome>.md`, sem reescrita. O que
    esta função acrescenta é o cabeçalho de identidade e o rodapé de origem.
    """
    corpo = agente.prompt

    # A orquestradora tem dois marcadores no prompt, porque o mesmo texto serve
    # à camada de IA em Python. Na alma estática eles são resolvidos.
    if "{catalogo}" in corpo:
        corpo = corpo.replace("{catalogo}", montar_catalogo(registro))
    if "{hoje}" in corpo:
        corpo = corpo.replace(
            "{hoje}",
            "a data de hoje (consulte o sistema, nunca presuma)",
        )

    tools = ", ".join(perfil.tools) or "nenhuma"
    papel = "Agente principal" if perfil.principal else "Subagente"

    cabecalho = f"""# SOUL.md — {perfil.nome} {perfil.emoji}

- **id**: `{perfil.id}`
- **papel**: {papel} do Sistema Operacional Pessoal
- **domínio**: {perfil.descricao}
- **modelo**: `{perfil.modelo}`
- **tools**: {tools}

"""

    rodape = f"""

---

## Tools e limites

Você tem exatamente estas tools: {tools}. Não há outras. Se uma tarefa exigir
algo fora dessa lista, diga o que falta em vez de improvisar.

Nunca invente dado que não esteja na mensagem. Nunca grave credencial em
arquivo. Trabalhe apenas dentro do seu workspace (`{perfil.workspace}`).

## Origem deste arquivo

Gerado por `python -m sop openclaw` a partir de `{agente.caminho.name if agente.caminho else "agentes/"}`.
Não edite aqui: a alteração é sobrescrita na próxima geração. Edite o arquivo
de origem em `agentes/` e rode o comando de novo.
"""

    return cabecalho + corpo.strip() + rodape


# ---------------------------------------------------------------------------
# Escrita e verificação
# ---------------------------------------------------------------------------


def _fontes(
    registro: Registro | None, orquestradora: AgenteDef | None
) -> tuple[Registro, AgenteDef]:
    registro = registro if registro is not None else carregar_registro()
    orquestradora = orquestradora or carregar_orquestradora()
    if orquestradora is None:
        raise RuntimeError("agentes/_orquestradora.md não encontrado.")
    return registro, orquestradora


def gerar(
    registro: Registro | None = None,
    orquestradora: AgenteDef | None = None,
    base: str = BASE_PADRAO,
    modelo: str = MODELO_PADRAO,
) -> dict[str, str]:
    """Devolve o conteúdo de tudo que seria escrito, sem tocar no disco.

    Chave é o caminho relativo à raiz do repositório. Separar gerar de escrever
    é o que permite ao `--verificar` conferir sem sujar o diretório.
    """
    registro, orquestradora = _fontes(registro, orquestradora)
    declaracao = montar_declaracao(registro, orquestradora, base, modelo)

    saidas: dict[str, str] = {"openclaw/agentes.json": declaracao.para_json()}

    definicoes = {orquestradora.nome: orquestradora}
    definicoes.update({agente.nome: agente for agente in registro})

    for perfil in declaracao.todos():
        agente = definicoes[perfil.id]
        saidas[perfil.alma] = montar_alma(agente, perfil, registro)

    return saidas


def escrever(saidas: dict[str, str], raiz: Path | None = None) -> list[str]:
    """Grava as saídas e devolve o que mudou de fato."""
    raiz = raiz or RAIZ
    alterados: list[str] = []
    for relativo, conteudo in sorted(saidas.items()):
        destino = raiz / relativo
        atual = destino.read_text(encoding="utf-8") if destino.is_file() else None
        if atual == conteudo:
            continue
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(conteudo, encoding="utf-8")
        alterados.append(relativo)
    return alterados


def desatualizados(saidas: dict[str, str], raiz: Path | None = None) -> list[str]:
    """Arquivos que o disco tem diferentes do que seria gerado agora."""
    raiz = raiz or RAIZ
    fora: list[str] = []
    for relativo, conteudo in sorted(saidas.items()):
        destino = raiz / relativo
        if not destino.is_file() or destino.read_text(encoding="utf-8") != conteudo:
            fora.append(relativo)
    return fora
