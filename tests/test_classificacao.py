"""Camada de IA: roteamento, extração e o fallback sem credencial."""

from __future__ import annotations

import json

import pytest

from sop.config import Config
from sop.datas import resolver_data, resolver_hora
from sop.integracoes.ia import (
    ClassificadorAnthropic,
    ClassificadorHeuristico,
    criar_adaptador,
    extrair_valor,
    resumir_titulo,
)

from conftest import HOJE


# -- datas -------------------------------------------------------------------


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("reunião hoje", "2026-03-10"),
        ("entregar amanhã", "2026-03-11"),
        ("depois de amanhã", "2026-03-12"),
        ("na quinta", "2026-03-12"),
        ("dia 25/12", "2026-12-25"),
        ("em 2026-07-04", "2026-07-04"),
        ("sem data nenhuma", None),
    ],
)
def test_resolve_data(texto, esperado):
    assert resolver_data(texto, HOJE) == esperado


def test_dia_da_semana_corrente_vai_para_a_proxima():
    """'terça' dito numa terça significa a próxima, não hoje."""
    assert resolver_data("na terça", HOJE) == "2026-03-17"


@pytest.mark.parametrize(
    "texto,esperado",
    [("às 14h", "14:00"), ("às 9:30", "09:30"), ("20h00", "20:00"), ("sem hora", None)],
)
def test_resolve_hora(texto, esperado):
    assert resolver_hora(texto) == esperado


# -- extração ----------------------------------------------------------------


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("gastei R$ 45,90", 45.90),
        ("custou R$ 1.250,00", 1250.00),
        ("paguei R$ 30", 30.0),
        ("gastei no posto", None),
    ],
)
def test_extrai_valor(texto, esperado):
    assert extrair_valor(texto) == esperado


def test_titulo_remove_ruido_inicial():
    assert resumir_titulo("preciso de comprar café") == "Comprar café"
    assert resumir_titulo("lembrar de pagar a conta") == "Pagar a conta"


def test_titulo_longo_e_truncado():
    titulo = resumir_titulo("a" * 200, limite=40)
    assert len(titulo) == 40 and titulo.endswith("…")


# -- roteamento heurístico ---------------------------------------------------


@pytest.mark.parametrize(
    "texto,agente,categoria",
    [
        ("Reunião com o time na quinta às 14h", "beija-flor", "compromisso"),
        ("Lembrar de renovar a assinatura", "beija-flor", "lembrete"),
        ("Acabou o café, comprar no mercado", "esquilo", "compras"),
        ("Conferir a despensa no sábado", "esquilo", "estoque"),
        ("Cardápio de terça: macarrão", "cervo", "cardapio"),
        ("Buscar as crianças na escola", "cervo", "familia"),
        ("Faxina da cozinha no sábado", "abelha", "limpeza"),
        ("Rotina da casa de segunda", "abelha", "rotina"),
        ("Gastei R$ 45,90 no almoço", "esquilo", "gasto"),
        ("Meta de juntar 3000 reais", "esquilo", "meta"),
        ("Projeto do portfólio: escrever a home", "raposa", "tarefa"),
        ("Entrega do relatório em 30/09", "raposa", "marco"),
        ("Guardar a garantia da geladeira", "elefante", "documento"),
        ("Registrar a decisão de trocar de banco", "elefante", "registro"),
        ("Estudar integração de APIs na sexta", "borboleta", "estudo"),
        ("Ler o artigo sobre agentes", "borboleta", "material"),
        ("Curso de análise de dados começa em abril", "borboleta", "curso"),
        ("Fazer flashcard de anatomia", "borboleta", "flashcard"),
        ("Criar um hábito de aprendizado", "borboleta", "aprendizado"),
        ("Quero aprender italiano", "borboleta", "aprendizado"),
    ],
)
def test_heuristica_roteia_para_o_agente_certo(texto, agente, categoria, registro):
    c = ClassificadorHeuristico().classificar(texto, registro, HOJE)
    assert (c.agente, c.categoria) == (agente, categoria)


def test_gasto_sem_valor_pede_confirmacao(registro):
    """Regra do Esquilo: nunca inventar um número."""
    c = ClassificadorHeuristico().classificar("Gastei no posto ontem", registro, HOJE)
    assert c.agente == "esquilo"
    assert c.valor is None
    assert c.precisa_confirmacao is True
    assert c.pergunta_confirmacao == "Qual foi o valor?"


@pytest.mark.parametrize(
    ("texto", "agente", "pergunta"),
    [
        ("Criar hábito de estudar inglês", "borboleta", "frequência"),
        ("Adicionar café à lista de compras", "esquilo", "quantidade"),
        ("Lembrar de entregar um documento na sexta", "beija-flor", "horário"),
        ("Criar uma métrica de conversão", "raposa", "valor"),
        ("Criar rotina de alongamento", "abelha", "frequência"),
        ("Documento passaporte", "elefante", "guardar"),
    ],
)
def test_heuristica_pergunta_dado_essencial(texto, agente, pergunta, registro):
    c = ClassificadorHeuristico().classificar(texto, registro, HOJE)
    assert c.agente == agente
    assert c.precisa_confirmacao is True
    assert pergunta in (c.pergunta_confirmacao or "").lower()


def test_gasto_com_valor_nao_pede_confirmacao(registro):
    c = ClassificadorHeuristico().classificar("Gastei R$ 45,90 hoje", registro, HOJE)
    assert c.valor == 45.90
    assert c.precisa_confirmacao is False


def test_categoria_pertence_ao_agente(registro):
    """Toda classificação heurística cai numa categoria válida do agente."""
    for texto in ["reunião amanhã", "comprar arroz", "gastei R$ 10", "estudar hoje"]:
        c = ClassificadorHeuristico().classificar(texto, registro, HOJE)
        assert registro.obter(c.agente).aceita(c.categoria)


# -- escolha de backend ------------------------------------------------------


def test_sem_chave_cai_na_heuristica(config_vazia):
    assert isinstance(criar_adaptador(config_vazia), ClassificadorHeuristico)


def test_com_cliente_injetado_usa_a_ia(config_falsa):
    adaptador = criar_adaptador(config_falsa, cliente=object())
    assert isinstance(adaptador, ClassificadorAnthropic)


# -- backend Anthropic com cliente falso ------------------------------------


class _Bloco:
    def __init__(self, texto: str) -> None:
        self.type = "text"
        self.text = texto


class _Resposta:
    def __init__(self, dados: dict, stop_reason: str = "end_turn") -> None:
        self.content = [_Bloco(json.dumps(dados))]
        self.stop_reason = stop_reason


class ClienteFalso:
    """Imita a Messages API. Registra os parâmetros para inspeção."""

    def __init__(self, dados: dict, stop_reason: str = "end_turn") -> None:
        self.dados = dados
        self.stop_reason = stop_reason
        self.chamadas: list[dict] = []
        self.messages = self

    def create(self, **params):
        self.chamadas.append(params)
        return _Resposta(self.dados, self.stop_reason)


def test_ia_pede_saida_estruturada(registro, config_falsa):
    """A resposta é validada pela API via JSON Schema, sem parsing frágil."""
    cliente = ClienteFalso(
        {
            "agente": "beija-flor",
            "categoria": "compromisso",
            "titulo": "Consulta médica",
            "data": "2026-03-12",
            "hora": "09:00",
            "observacao": "",
            "precisa_confirmacao": False,
            "confianca": 0.95,
        }
    )
    c = ClassificadorAnthropic(config_falsa, cliente=cliente).classificar(
        "consulta na quinta às 9", registro, HOJE
    )

    assert c.agente == "beija-flor"
    assert c.data == "2026-03-12"
    assert c.origem == "ia"

    params = cliente.chamadas[0]
    assert params["model"] == "claude-opus-5"
    assert params["output_config"]["format"]["type"] == "json_schema"
    assert "agente" in params["output_config"]["format"]["schema"]["properties"]


def test_ia_recebe_o_catalogo_de_agentes(registro, config_falsa):
    cliente = ClienteFalso(
        {
            "agente": "esquilo",
            "categoria": "compras",
            "titulo": "Café",
            "observacao": "",
            "precisa_confirmacao": False,
            "confianca": 0.9,
        }
    )
    ClassificadorAnthropic(config_falsa, cliente=cliente).classificar(
        "acabou o café", registro, HOJE
    )
    instrucao = cliente.chamadas[0]["system"]
    for nome in registro.nomes():
        assert nome in instrucao
    assert HOJE.isoformat() in instrucao


def test_agente_inexistente_e_resolvido_pela_categoria(registro, config_falsa):
    """Se o modelo alucinar um agente, a categoria salva o roteamento."""
    cliente = ClienteFalso(
        {
            "agente": "juridico",
            "categoria": "gasto",
            "titulo": "Multa",
            "observacao": "",
            "precisa_confirmacao": False,
            "confianca": 0.5,
        }
    )
    c = ClassificadorAnthropic(config_falsa, cliente=cliente).classificar(
        "multa de trânsito", registro, HOJE
    )
    assert c.agente == "esquilo"


def test_recusa_do_modelo_cai_na_heuristica(registro, config_falsa):
    """stop_reason 'refusal' não pode virar exceção nem resposta vazia."""
    cliente = ClienteFalso({}, stop_reason="refusal")
    c = ClassificadorAnthropic(config_falsa, cliente=cliente).classificar(
        "comprar arroz", registro, HOJE
    )
    assert c.origem == "heuristica"
    assert c.agente == "esquilo"


def test_data_relativa_da_ia_e_normalizada(registro, config_falsa):
    cliente = ClienteFalso(
        {
            "agente": "beija-flor",
            "categoria": "lembrete",
            "titulo": "Pagar conta",
            "data": "amanhã",
            "observacao": "",
            "precisa_confirmacao": False,
            "confianca": 0.8,
        }
    )
    c = ClassificadorAnthropic(config_falsa, cliente=cliente).classificar(
        "pagar conta amanhã", registro, HOJE
    )
    assert c.data == "2026-03-11"
