#!/usr/bin/env python3
"""
converter.py — traduz a estrutura de agentes do repo `aria-infra` para o formato do OpenClaw.

    python3 sabia/converter.py

Lê:
  sabia/agentes-fonte/*.md   os nove subagentes, no formato do Claude Code
  sabia/orquestradora.md     a alma da Sábia, escrita à mão

Escreve:
  sabia/almas/<id>.md        a alma de cada agente, já no formato que vira SOUL.md
  sabia/agentes-sabia.json   a declaração da estrutura, consumida por registrar.sh

POR QUE NÃO USAMOS O `criar-subagente-openclaw.py` DO PRÓPRIO aria-infra
-----------------------------------------------------------------------
O script existe em .claude/skills/criar-subagente/scripts/ e serve pra criar UM subagente novo
do zero, num ambiente diferente deste. Nesta VPS ele não roda:

  1. Ele escreve direto em openclaw.json com um esquema que a 2026.6.5 não aceita
     (`system_prompt_file`, `channels`, `max_tokens`, `isolation`). O esquema real de
     `agents.list[]` usa `agentDir`, `identity`, `model`, `tools`, `subagents`. Editar o JSON à
     mão também pula a validação e o `last-good` do CLI, que é o que protege a config.
  2. `MODELOS_VALIDOS` só aceita modelo Claude. A estrutura da Bruna roda em `openai/gpt-5.5`
     pelo Codex, então o script aborta com "modelo invalido" antes de escrever qualquer coisa.
  3. Ele assume base em `/root/.openclaw` e reinicia `systemctl restart openclaw-gateway`. Aqui a
     base é `/home/aria/.openclaw` e o gateway roda como processo do usuário `aria`, sem unit
     instalada. O restart falharia e ele seguiria em frente assim mesmo.
  4. A alma que ele gera fixa "equipe Naia" e "reporta pra Naia, nunca fala com o Chefe direto".
     A equipe daqui reporta pra Sábia.

Então: conversão em massa aqui, aplicação pelo CLI oficial em registrar.sh. O script do repo
continua válido pro caso de uso dele (criar um agente novo, noutro ambiente) e não foi alterado.

TRADUÇÃO DE TOOLS
-----------------
O Claude Code nomeia as ferramentas de um jeito e o OpenClaw de outro. O mapa está em TOOLS
abaixo. Dois pontos que não são simétricos:

  - `Grep` e `Glob` não têm equivalente no OpenClaw. Busca textual lá é feita com `read` e, quando
    precisa varrer, com `exec`. Quem tinha Grep/Glob recebe `read`; quem tinha Bash já recebe
    `exec` e continua conseguindo varrer.
  - `Agent` (invocar outro subagente) vira o trio `sessions_spawn`, `subagents` e `agents_list`.
    Só a Juliana tem, igual no original.

TRADUÇÃO DE MODELO
------------------
Os nove nasceram com `model: opus | sonnet`. Aqui todos rodam no mesmo provedor autenticado, o
Codex (`openai/gpt-5.5`), porque é o único que a Bruna escolheu e ligou. O que preserva a
diferença de peso entre eles é o `thinkingDefault`: quem era opus pensa em `high`, quem era
sonnet pensa em `medium`. É o análogo mais próximo que o OpenClaw oferece.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
FONTE = RAIZ / "agentes-fonte"
ALMAS = RAIZ / "almas"
DECLARACAO = RAIZ / "agentes-sabia.json"
ORQUESTRADORA = RAIZ / "orquestradora.md"

MODELO = "openai/gpt-5.5"

# Claude Code -> OpenClaw. Uma tool do Claude pode virar mais de uma do OpenClaw.
TOOLS = {
    "Read": ["read"],
    "Write": ["write"],
    "Edit": ["edit"],
    "Bash": ["exec"],
    "Grep": ["read"],
    "Glob": ["read"],
    "WebFetch": ["web_fetch", "web_search"],
    # `sessions_yield` entra junto: sem ele o agente consegue despachar um filho mas não consegue
    # devolver o turno enquanto espera, e fica preso até o filho terminar. Quem delega precisa dos
    # dois lados.
    "Agent": ["sessions_spawn", "sessions_yield", "subagents", "agents_list"],
}

# Todo agente precisa saber o estado da própria sessão. É o mínimo do perfil `minimal`.
TOOLS_BASE = ["session_status"]

# `disallowedTools` do Claude vira `tools.deny`, com os aliases que dão o mesmo poder.
DENY = {
    "Bash": ["exec", "process", "code_execution"],
    "Edit": ["edit", "apply_patch"],
    "Write": ["write"],
}

# opus e sonnet não existem no Codex; viram nível de raciocínio.
PENSAMENTO = {"opus": "high", "sonnet": "medium", "claude-sonnet-5": "medium"}

# O emoji e o nome de exibição de cada um. Os que já aparecem no corpo do arquivo de origem
# foram mantidos idênticos; os três que não tinham receberam um coerente com a função.
IDENTIDADE = {
    "amanda-crm": ("Amanda", "💬"),
    "denderson-clone": ("Denderson", "🎯"),
    "ethan-projetos": ("Ethan", "📋"),
    "jane-academica": ("Jane", "🎓"),
    "jonathan-copy": ("Jonathan", "✍️"),
    "jordan-sdr": ("Jordan", "🤝"),
    "juliana-ops": ("Juliana", "🎨"),
    "monica-projetos": ("Mônica", "🗂️"),
    "neo-dev": ("Neo", "💻"),
}


def ler_frontmatter(texto: str) -> tuple[dict, str]:
    """Separa o frontmatter YAML do corpo. Só os campos que a conversão usa são lidos."""
    if not texto.startswith("---"):
        return {}, texto
    fim = texto.find("\n---", 3)
    if fim == -1:
        return {}, texto
    bruto = texto[3:fim]
    corpo = texto[fim + 4 :].lstrip("\n")

    meta: dict = {}
    for linha in bruto.splitlines():
        if not linha.strip() or linha.lstrip().startswith("#"):
            continue
        if ":" not in linha or linha.startswith((" ", "\t")):
            continue
        chave, valor = linha.split(":", 1)
        chave, valor = chave.strip(), valor.strip()
        if valor.startswith("[") and valor.endswith("]"):
            meta[chave] = [v.strip() for v in valor[1:-1].split(",") if v.strip()]
        else:
            meta[chave] = valor
    return meta, corpo


def traduzir_tools(lista: list[str]) -> list[str]:
    """Aplica o mapa TOOLS preservando a ordem e sem repetir."""
    saida: list[str] = []
    for nome in list(lista) + TOOLS_BASE:
        for tool in TOOLS.get(nome, [nome]):
            if tool not in saida:
                saida.append(tool)
    return saida


def traduzir_deny(lista: list[str]) -> list[str]:
    saida: list[str] = []
    for nome in lista:
        for tool in DENY.get(nome, [nome]):
            if tool not in saida:
                saida.append(tool)
    return saida


def montar_alma(agente_id: str, nome: str, emoji: str, meta: dict, corpo: str,
                tools: list[str], deny: list[str]) -> str:
    """Gera o SOUL.md: cabeçalho operacional + o corpo original, intacto."""
    cabecalho = [
        f"# SOUL.md — {nome} {emoji}".rstrip(),
        "",
        f"- **id**: `{agente_id}`",
        f"- **modelo**: `{MODELO}` (Codex)",
        f"- **tools**: {', '.join(tools)}",
    ]
    if deny:
        cabecalho.append(f"- **bloqueadas**: {', '.join(deny)}")
    cabecalho += [
        "- **reporta para**: Sábia 🐦, a orquestradora",
        "",
        "---",
        "",
    ]

    lugar_na_estrutura = (
        [
            "Você não fala direto no Telegram. Como executora geral, pode receber e executar",
            "demandas de qualquer domínio que a Sábia delegar, além de coordenar os outros agentes.",
        ]
        if agente_id == "juliana-ops"
        else [
            "Você não fala direto no Telegram e não decide o que é de outro agente: se o pedido não",
            "for seu, diga de quem é e devolva.",
        ]
    )

    rodape = [
        "",
        "---",
        "",
        "## Seu lugar na estrutura",
        "",
        "Quem recebe a mensagem da Bruna é a **Sábia**, a orquestradora. Ela entende o pedido e",
        "despacha para você. Você faz o trabalho e devolve o resultado para ela, que entrega.",
        *lugar_na_estrutura,
        "",
        "## Tools e limites",
        "",
        f"Você tem exatamente estas tools: {', '.join(tools)}. Não há outras.",
    ]
    if deny:
        rodape.append(
            f"Estas estão bloqueadas para você por decisão de segurança: {', '.join(deny)}."
        )
    rodape += [
        "Se a tarefa exigir algo fora dessa lista, diga o que falta em vez de improvisar.",
        "",
        "Nunca invente dado que não esteja no pedido ou nos arquivos. Nunca grave credencial em",
        "arquivo. Português do Brasil acentuado, sem travessões.",
        "",
        "## Origem deste arquivo",
        "",
        "Gerado por `python3 sabia/converter.py` a partir de `sabia/agentes-fonte/"
        f"{agente_id}.md`, que é cópia fiel de `.claude/agents/{agente_id}.md` do repositório",
        "`brunarezerdev/aria-infra`. Não edite aqui: a alteração é sobrescrita na próxima",
        "geração. Edite a fonte e rode o conversor de novo.",
        "",
    ]
    return "\n".join(cabecalho) + corpo.rstrip() + "\n" + "\n".join(rodape)


def converter_um(caminho: Path) -> dict:
    meta, corpo = ler_frontmatter(caminho.read_text(encoding="utf-8"))
    agente_id = meta.get("name") or caminho.stem
    nome, emoji = IDENTIDADE.get(agente_id, (agente_id, "🔹"))

    tools = traduzir_tools(meta.get("tools", []))
    deny = traduzir_deny(meta.get("disallowedTools", []))
    # Uma tool não pode estar nos dois lados. O bloqueio ganha.
    tools = [t for t in tools if t not in deny]

    pensamento = PENSAMENTO.get(str(meta.get("model", "sonnet")).strip(), "medium")

    alma = ALMAS / f"{agente_id}.md"
    alma.write_text(
        montar_alma(agente_id, nome, emoji, meta, corpo, tools, deny), encoding="utf-8"
    )

    return {
        "id": agente_id,
        "nome": nome,
        "emoji": emoji,
        "descricao": meta.get("description", ""),
        "modelo": MODELO,
        "pensamento": pensamento,
        "tools": tools,
        "deny": deny,
        "workspace": f"~/.openclaw/workspace-{agente_id}",
        "alma": f"sabia/almas/{agente_id}.md",
        "origem_claude": {
            "arquivo": f".claude/agents/{agente_id}.md",
            "modelo": meta.get("model", "sonnet"),
            "tools": meta.get("tools", []),
            "disallowedTools": meta.get("disallowedTools", []),
        },
    }


def converter_orquestradora() -> dict:
    meta, corpo = ler_frontmatter(ORQUESTRADORA.read_text(encoding="utf-8"))
    tools = meta.get("tools", [])
    alma = ALMAS / "sabia.md"
    # A alma da Sábia já é escrita no formato final; só ganha o cabeçalho operacional.
    alma.write_text(
        "\n".join(
            [
                f"# SOUL.md — {meta.get('nome', 'Sábia')} {meta.get('emoji', '🐦')}",
                "",
                "- **id**: `main`",
                f"- **modelo**: `{MODELO}` (Codex)",
                f"- **tools**: {', '.join(tools)}",
                "- **papel**: orquestradora da estrutura de agentes, atende no @SabiaAquiBot",
                "",
                "---",
                "",
            ]
        )
        + corpo.rstrip()
        + "\n\n---\n\n## Origem deste arquivo\n\n"
        "Gerado por `python3 sabia/converter.py` a partir de `sabia/orquestradora.md`.\n"
        "Não edite aqui: edite a fonte e rode o conversor de novo.\n",
        encoding="utf-8",
    )
    return {
        "id": "main",
        "nome": meta.get("nome", "Sábia"),
        "emoji": meta.get("emoji", "🐦"),
        "descricao": meta.get("descricao", ""),
        "modelo": MODELO,
        "pensamento": meta.get("thinking", "high"),
        "tools": tools,
        "deny": [],
        "workspace": "~/.openclaw/workspace",
        "alma": "sabia/almas/sabia.md",
    }


def main() -> None:
    ALMAS.mkdir(parents=True, exist_ok=True)

    fontes = sorted(FONTE.glob("*.md"))
    if len(fontes) != 9:
        raise SystemExit(
            f"esperava 9 agentes em {FONTE}, encontrei {len(fontes)}. "
            "Ressincronize com o aria-infra antes de converter."
        )

    principal = converter_orquestradora()
    subagentes = [converter_um(f) for f in fontes]

    declaracao = {
        "_leia": (
            "Declaração da estrutura Sábia, não é o openclaw.json. Gerada por "
            "`python3 sabia/converter.py` a partir de sabia/agentes-fonte/ e "
            "sabia/orquestradora.md. Aplicada no OpenClaw por sabia/registrar.sh. "
            "Não edite à mão. Não confundir com openclaw/agentes.json, que é a estrutura "
            "pessoal antiga e continua preservada."
        ),
        "origem": {
            "repositorio": "brunarezerdev/aria-infra",
            "caminho": ".claude/agents/",
            "commit": "3d259f94e9dcfd7ae74eb12a4db2a65dc6ece43a",
            "data": "2026-08-26",
        },
        "provedor": {
            "provider": "openai",
            "modelo": MODELO,
            "auth": "Codex CLI já autenticado em ~/.codex, pelo plugin nativo do OpenClaw",
        },
        "principal": principal,
        "subagentes": subagentes,
    }

    DECLARACAO.write_text(
        json.dumps(declaracao, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"alma da orquestradora: {ALMAS / 'sabia.md'}")
    for ag in subagentes:
        print(f"  {ag['id']:18} {ag['pensamento']:7} {', '.join(ag['tools'])}")
        if ag["deny"]:
            print(f"  {'':18} bloqueadas: {', '.join(ag['deny'])}")
    print(f"\ndeclaração: {DECLARACAO}")


if __name__ == "__main__":
    main()
