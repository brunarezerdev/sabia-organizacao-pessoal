"""Fila durável: o estado tem que sobreviver ao processo."""

from __future__ import annotations

from sop.fila import Fila


def test_enfileira_e_reserva(tmp_path):
    fila = Fila(tmp_path)
    fila.enfileirar({"texto": "primeira"})
    fila.enfileirar({"texto": "segunda"})

    assert fila.contar("pendente") == 2

    tarefa = fila.reservar()
    assert tarefa is not None
    assert tarefa.payload["texto"] == "primeira"  # FIFO
    assert fila.contar("pendente") == 1
    assert fila.contar("processando") == 1


def test_reservar_fila_vazia_devolve_none(tmp_path):
    assert Fila(tmp_path).reservar() is None


def test_concluir_move_para_concluida(tmp_path):
    fila = Fila(tmp_path)
    fila.enfileirar({"texto": "x"})
    tarefa = fila.reservar()
    fila.concluir(tarefa)

    assert fila.contar("processando") == 0
    assert fila.contar("concluida") == 1


def test_falha_reenfileira_ate_o_limite(tmp_path):
    fila = Fila(tmp_path, max_tentativas=2)
    fila.enfileirar({"texto": "x"})

    tarefa = fila.reservar()
    assert fila.falhar(tarefa, "erro 1") == "pendente"  # tentativa 1 de 2

    tarefa = fila.reservar()
    assert fila.falhar(tarefa, "erro 2") == "falha"  # esgotou

    assert fila.contar("pendente") == 0
    assert fila.contar("falha") == 1


def test_erro_fica_registrado(tmp_path):
    fila = Fila(tmp_path, max_tentativas=1)
    fila.enfileirar({"texto": "x"})
    fila.falhar(fila.reservar(), "notion fora do ar")

    falhas = list(fila.listar("falha"))
    assert falhas[0].erro == "notion fora do ar"


def test_estado_persiste_entre_instancias(tmp_path):
    """O ponto da fila durável: reabrir o diretório recupera tudo."""
    Fila(tmp_path).enfileirar({"texto": "sobrevivi"})

    outra = Fila(tmp_path)
    tarefa = outra.reservar()
    assert tarefa.payload["texto"] == "sobrevivi"


def test_recupera_tarefas_orfas(tmp_path):
    """Processo morreu no meio: a tarefa volta para a fila."""
    fila = Fila(tmp_path)
    fila.enfileirar({"texto": "travada"})
    fila.reservar()  # fica em processando e ninguém conclui

    assert fila.contar("processando") == 1
    recuperadas = fila.recuperar_orfas(idade_segundos=0)

    assert len(recuperadas) == 1
    assert fila.contar("processando") == 0
    assert fila.contar("pendente") == 1


def test_recuperar_orfas_respeita_a_idade(tmp_path):
    fila = Fila(tmp_path)
    fila.enfileirar({"texto": "recente"})
    fila.reservar()

    assert fila.recuperar_orfas(idade_segundos=3600) == []
    assert fila.contar("processando") == 1


def test_estatisticas(tmp_path):
    fila = Fila(tmp_path)
    fila.enfileirar({"texto": "a"})
    fila.concluir(fila.reservar())
    fila.enfileirar({"texto": "b"})

    assert fila.estatisticas() == {
        "pendente": 1,
        "processando": 0,
        "concluida": 1,
        "falha": 0,
    }
