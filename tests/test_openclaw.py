"""A camada OpenClaw: declaração, almas e o backend que fala com o CLI.

Nenhum teste aqui instala, chama ou depende do OpenClaw estar na máquina. O
subprocesso é substituído por uma função que devolve texto.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from sop import openclaw as oc
from sop.agentes import carregar_orquestradora, carregar_registro
from sop.config import Config
from sop.integracoes.ia import (
    ClassificadorHeuristico,
    ClassificadorOpenClaw,
    criar_adaptador,
    extrair_json,
)

RAIZ = Path(__file__).resolve().parents[1]
HOJE = date(2026, 3, 10)


@pytest.fixture
def declaracao(registro):
    return oc.montar_declaracao(registro, carregar_orquestradora(RAIZ / "agentes"))


# -- declaração --------------------------------------------------------------


def test_declara_a_orquestradora_e_os_cinco_agentes(declaracao):
    assert declaracao.principal.id == "main"
    assert {p.id for p in declaracao.subagentes} == {
        "secretaria",
        "lifestyle",
        "financeira",
        "projetos",
        "educacional",
    }


def test_orquestradora_nao_vira_um_sexto_agente_de_dominio(registro):
    """`_orquestradora.md` mora em agentes/, mas fora do roteamento."""
    assert "main" not in registro
    assert len(registro) == 5


def test_cada_agente_tem_workspace_proprio(declaracao):
    workspaces = [p.workspace for p in declaracao.todos()]
    assert len(set(workspaces)) == len(workspaces)
    # O principal ocupa o workspace raiz; os subagentes, um sufixado.
    assert declaracao.principal.workspace.endswith("/workspace")
    for perfil in declaracao.subagentes:
        assert perfil.workspace.endswith(f"/workspace-{perfil.id}")


def test_todo_agente_tem_tools_declaradas(declaracao):
    for perfil in declaracao.todos():
        assert perfil.tools, f"{perfil.id} sem tools"


def test_tools_sao_do_vocabulario_do_openclaw(declaracao):
    """Tools do OpenClaw são `dominio.acao`, não os nomes do Claude Code."""
    validas = {
        "fs.read",
        "fs.write",
        "fs.edit",
        "shell.exec",
        "web.fetch",
        "web.search",
        "grep",
        "glob",
        "agent.invoke",
    }
    for perfil in declaracao.todos():
        desconhecidas = set(perfil.tools) - validas
        assert not desconhecidas, f"{perfil.id}: {desconhecidas}"


def test_so_a_orquestradora_delega(declaracao):
    """`agent.invoke` em especialista abre caminho para loop de delegação."""
    assert "agent.invoke" in declaracao.principal.tools
    for perfil in declaracao.subagentes:
        assert "agent.invoke" not in perfil.tools


def test_nenhum_agente_de_dominio_executa_shell(declaracao):
    for perfil in declaracao.todos():
        assert "shell.exec" not in perfil.tools


def test_modelo_por_agente_cai_no_do_projeto(declaracao):
    for perfil in declaracao.todos():
        assert perfil.modelo == oc.MODELO_PADRAO


def test_modelo_do_arquivo_vence_o_do_projeto(registro):
    """Um agente pode pedir outro modelo sem mudar o resto."""
    from dataclasses import replace

    agente = replace(registro.obter("financeira"), modelo="openai/gpt-5.5-mini")
    perfil = oc.perfil_de(agente, modelo="openai/gpt-5.5")
    assert perfil.modelo == "openai/gpt-5.5-mini"


def test_declaracao_nao_e_o_openclaw_json(declaracao):
    """O openclaw.json é escrito pelo CLI. Nós declaramos, ele aplica."""
    dados = declaracao.para_dict()
    assert "agents" not in dados  # o formato interno do OpenClaw não é nosso
    assert dados["openclaw"]["gateway"]["mode"] == "local"
    assert dados["openclaw"]["provedor"]["provider"] == "openai"
    assert dados["openclaw"]["provedor"]["auth"] == "oauth-device-code"


def test_declaracao_nao_carrega_credencial(declaracao):
    """A rota Codex é OAuth: nada de chave dentro da declaração."""
    import re

    texto = declaracao.para_json().lower()
    # Com fronteira de palavra: "secretaria" é o nome de um agente, não um segredo.
    for proibido in ("api_key", "apikey", "token", "secret", "senha", "bearer"):
        assert not re.search(rf"\b{proibido}\b", texto), proibido


# -- almas -------------------------------------------------------------------


def test_alma_preserva_o_prompt_original(registro, declaracao):
    agente = registro.obter("financeira")
    perfil = next(p for p in declaracao.subagentes if p.id == "financeira")
    alma = oc.montar_alma(agente, perfil, registro)
    # Uma frase distintiva do prompt escrito à mão precisa sobreviver.
    trecho = agente.prompt.strip().splitlines()[2]
    assert trecho in alma


def test_alma_da_orquestradora_resolve_os_marcadores(registro):
    orquestradora = carregar_orquestradora(RAIZ / "agentes")
    perfil = oc.perfil_de(orquestradora, principal=True)
    alma = oc.montar_alma(orquestradora, perfil, registro)
    assert "{catalogo}" not in alma and "{hoje}" not in alma
    # O catálogo resolvido lista os agentes de verdade.
    for nome in registro.nomes():
        assert nome in alma


def test_alma_declara_as_tools_do_agente(registro, declaracao):
    perfil = next(p for p in declaracao.subagentes if p.id == "educacional")
    alma = oc.montar_alma(registro.obter("educacional"), perfil, registro)
    assert "web.fetch" in alma
    assert "shell.exec" not in alma


def test_geracao_e_deterministica(registro):
    orquestradora = carregar_orquestradora(RAIZ / "agentes")
    assert oc.gerar(registro, orquestradora) == oc.gerar(registro, orquestradora)


def test_declaracao_versionada_esta_em_dia():
    """Editar agentes/ sem regerar deixa o repositório inconsistente."""
    fora = oc.desatualizados(oc.gerar())
    assert not fora, f"rode `python -m sop openclaw`: {fora}"


def test_escrever_e_idempotente(tmp_path, registro):
    saidas = oc.gerar(registro, carregar_orquestradora(RAIZ / "agentes"))
    assert oc.escrever(saidas, raiz=tmp_path)  # primeira vez, escreve tudo
    assert oc.escrever(saidas, raiz=tmp_path) == []  # segunda, não mexe em nada


# -- backend que fala com o CLI ----------------------------------------------

RESPOSTA_BOA = """{
  "agente": "financeira", "categoria": "gasto", "titulo": "Mercado",
  "data": null, "hora": null, "valor": 82.5,
  "observacao": "", "precisa_confirmacao": false, "confianca": 0.9
}"""


def config_openclaw(**extra) -> Config:
    return Config(openclaw_comando="openclaw agents run {agente}", **extra)


def test_comando_e_partido_e_recebe_o_agente():
    config = Config(openclaw_comando="openclaw agents run {agente} --json")
    assert config.openclaw_comando_partido() == [
        "openclaw", "agents", "run", "main", "--json",
    ]


def test_comando_vazio_nao_vira_backend():
    assert Config().openclaw_comando_partido() == []
    with pytest.raises(ValueError):
        ClassificadorOpenClaw(Config())


def test_classifica_pela_saida_do_cli(registro):
    chamadas = []

    def executor(comando, entrada):
        chamadas.append((comando, entrada))
        return RESPOSTA_BOA

    classificador = ClassificadorOpenClaw(config_openclaw(), executor=executor)
    c = classificador.classificar("gastei 82,50 no mercado", registro, HOJE)

    assert c.agente == "financeira"
    assert c.valor == 82.5
    assert c.origem == "openclaw"
    # A instrução mandada ao CLI carrega o catálogo e a mensagem.
    _, entrada = chamadas[0]
    assert "secretaria" in entrada and "mercado" in entrada


def test_saida_ilegivel_cai_na_heuristica_em_vez_de_estourar(registro):
    """Perder o registro da pessoa é pior do que classificar com menos precisão."""
    classificador = ClassificadorOpenClaw(
        config_openclaw(), executor=lambda c, e: "deu ruim aqui, sem JSON"
    )
    c = classificador.classificar("reunião amanhã às 10h", registro, HOJE)
    assert c.origem == "heuristica"
    assert c.agente == "secretaria"


def test_agente_inventado_pelo_modelo_e_resgatado_pela_categoria(registro):
    resposta = '{"agente": "juridico", "categoria": "compras", "titulo": "Arroz"}'
    classificador = ClassificadorOpenClaw(
        config_openclaw(), executor=lambda c, e: resposta
    )
    assert classificador.classificar("comprar arroz", registro, HOJE).agente == "lifestyle"


def test_erro_do_cli_propaga(registro):
    def executor(comando, entrada):
        raise RuntimeError("OpenClaw saiu com código 1")

    classificador = ClassificadorOpenClaw(config_openclaw(), executor=executor)
    with pytest.raises(RuntimeError):
        classificador.classificar("qualquer coisa", registro, HOJE)


# -- extração do JSON --------------------------------------------------------


@pytest.mark.parametrize(
    "bruto",
    [
        '{"agente": "financeira"}',
        '```json\n{"agente": "financeira"}\n```',
        'Claro! Segue:\n\n{"agente": "financeira"}\n\nQualquer coisa é só falar.',
        '```\n{"agente": "financeira"}\n```',
    ],
)
def test_extrai_json_apesar_da_moldura(bruto):
    assert extrair_json(bruto)["agente"] == "financeira"


@pytest.mark.parametrize("bruto", ["", "   ", "sem json nenhum aqui"])
def test_extrai_json_recusa_o_que_nao_tem(bruto):
    with pytest.raises(ValueError):
        extrair_json(bruto)


# -- escolha do backend ------------------------------------------------------


def test_sem_nada_configurado_usa_a_heuristica():
    assert isinstance(criar_adaptador(Config()), ClassificadorHeuristico)


def test_openclaw_tem_precedencia_sobre_as_chaves():
    config = config_openclaw(anthropic_api_key="chave-de-teste")
    assert criar_adaptador(config).origem == "openclaw"


def test_backend_pode_ser_forcado_para_heuristica():
    config = config_openclaw(ia_backend="heuristica")
    assert isinstance(criar_adaptador(config), ClassificadorHeuristico)


def test_backend_indisponivel_nao_derruba_o_sistema():
    """Pedir um backend sem ter como usá-lo degrada, não quebra."""
    config = Config(ia_backend="openclaw")  # sem OPENCLAW_COMANDO
    assert isinstance(criar_adaptador(config), ClassificadorHeuristico)
