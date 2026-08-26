"""Configuração: subir sem credencial não pode quebrar."""

from __future__ import annotations

import pytest

from sop.config import Config, ConfiguracaoAusente, carregar_env, exigir


def test_config_vazia_nao_levanta(config_vazia):
    """Importar e instanciar sem .env precisa funcionar."""
    assert config_vazia.telegram_token == ""
    assert config_vazia.anthropic_model == "claude-opus-5"
    assert config_vazia.google_calendar_id == "primary"


def test_diagnostico_lista_o_que_falta(config_vazia):
    diagnostico = config_vazia.diagnostico()
    assert "TELEGRAM_BOT_TOKEN" in diagnostico["telegram"]
    assert "NOTION_TOKEN" in diagnostico["notion"]
    # A IA entra pelo OpenClaw, que é onde o provedor está autenticado. As
    # chaves de API são rotas alternativas, não requisito.
    assert "OPENCLAW_COMANDO" in diagnostico["openclaw"]


def test_pronta_reflete_as_credenciais(config_vazia, config_falsa):
    assert not config_vazia.pronta("notion")
    assert config_falsa.pronta("notion")
    assert config_falsa.pronta("telegram")


def test_exigir_da_mensagem_acionavel(config_vazia):
    with pytest.raises(ConfiguracaoAusente) as erro:
        exigir(config_vazia, "notion")
    texto = str(erro.value)
    assert "NOTION_TOKEN" in texto
    assert ".env.example" in texto  # diz o que fazer, não só o que falta


def test_exigir_passa_quando_configurada(config_falsa):
    exigir(config_falsa, "notion")  # não deve levantar


def test_carregar_env_ignora_comentario_e_vazio(tmp_path):
    arquivo = tmp_path / ".env"
    arquivo.write_text(
        "# comentário\n\nCHAVE=valor\nOUTRA=\"com aspas\"\nsem_igual\n",
        encoding="utf-8",
    )
    valores = carregar_env(arquivo)
    assert valores == {"CHAVE": "valor", "OUTRA": "com aspas"}


def test_carregar_env_inexistente_devolve_vazio(tmp_path):
    assert carregar_env(tmp_path / "nao-existe") == {}


def test_do_ambiente_aceita_valores_extras():
    config = Config.do_ambiente({"NOTION_TOKEN": "abc", "NOTION_DATABASE_ID": "def"})
    assert config.pronta("notion")
