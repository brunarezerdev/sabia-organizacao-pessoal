"""Fila durável de tarefas em disco.

Por que em disco e não em memória: se o processo morrer no meio de uma
mensagem, a tarefa precisa continuar existindo. Cada tarefa é um arquivo JSON;
a mudança de estado é um `os.rename`, que é atômico dentro do mesmo sistema de
arquivos. Isso dá durabilidade sem exigir banco nem broker.

Estados: pendente -> processando -> concluida | falha
"""

from __future__ import annotations

import itertools
import json
import os
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterator

ESTADOS = ("pendente", "processando", "concluida", "falha")

# O nome do arquivo é a chave de ordenação da fila, então precisa ser
# monotônico. Timestamp em microssegundos resolve entre processos; o contador
# resolve empates dentro do mesmo processo (dois enfileiramentos no mesmo
# microssegundo, que acontece em testes e em rajadas de mensagens).
_SEQUENCIA = itertools.count()


@dataclass
class Tarefa:
    id: str
    payload: dict[str, Any]
    criada_em: float
    tentativas: int = 0
    max_tentativas: int = 3
    erro: str = ""

    def para_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def do_dict(cls, dados: dict[str, Any]) -> "Tarefa":
        return cls(
            id=dados["id"],
            payload=dados.get("payload", {}),
            criada_em=dados.get("criada_em", 0.0),
            tentativas=dados.get("tentativas", 0),
            max_tentativas=dados.get("max_tentativas", 3),
            erro=dados.get("erro", ""),
        )


class Fila:
    """Fila FIFO durável, sem dependências externas."""

    def __init__(self, diretorio: str | Path = ".fila", max_tentativas: int = 3) -> None:
        self.raiz = Path(diretorio)
        self.max_tentativas = max_tentativas
        for estado in ESTADOS:
            (self.raiz / estado).mkdir(parents=True, exist_ok=True)

    # -- escrita -------------------------------------------------------------

    def enfileirar(self, payload: dict[str, Any]) -> Tarefa:
        """Adiciona uma tarefa ao fim da fila e devolve o registro criado."""
        agora = time.time()
        tarefa = Tarefa(
            id=f"{int(agora * 1_000_000):018d}-{next(_SEQUENCIA):06d}-{uuid.uuid4().hex[:8]}",
            payload=payload,
            criada_em=agora,
            max_tentativas=self.max_tentativas,
        )
        self._gravar(tarefa, "pendente")
        return tarefa

    def reservar(self) -> Tarefa | None:
        """Pega a próxima tarefa pendente e a move para `processando`.

        O `rename` é a trava: se dois processos tentarem reservar a mesma
        tarefa, apenas um consegue mover o arquivo — o outro segue para a
        próxima. Não há race de duas execuções da mesma tarefa.
        """
        for caminho in self._listar("pendente"):
            destino = self.raiz / "processando" / caminho.name
            try:
                os.rename(caminho, destino)
            except OSError:
                continue  # outro worker levou esta; tenta a seguinte
            tarefa = self._ler(destino)
            tarefa.tentativas += 1
            self._gravar(tarefa, "processando")
            return tarefa
        return None

    def concluir(self, tarefa: Tarefa) -> None:
        """Marca a tarefa como concluída."""
        self._mover(tarefa, "processando", "concluida")

    def falhar(self, tarefa: Tarefa, erro: str) -> str:
        """Registra falha. Reenfileira se ainda houver tentativa disponível.

        Devolve o estado final: "pendente" (vai tentar de novo) ou "falha".
        """
        tarefa.erro = erro
        destino = "pendente" if tarefa.tentativas < tarefa.max_tentativas else "falha"
        self._mover(tarefa, "processando", destino)
        return destino

    def recuperar_orfas(self, idade_segundos: float = 1800) -> list[Tarefa]:
        """Devolve para `pendente` tarefas travadas em `processando`.

        Cobre o caso de o processo ter morrido no meio. Deve ser chamada na
        inicialização do worker ou por um cron.
        """
        limite = time.time() - idade_segundos
        recuperadas: list[Tarefa] = []
        for caminho in self._listar("processando"):
            if caminho.stat().st_mtime > limite:
                continue
            tarefa = self._ler(caminho)
            destino = (
                "pendente" if tarefa.tentativas < tarefa.max_tentativas else "falha"
            )
            self._mover(tarefa, "processando", destino)
            recuperadas.append(tarefa)
        return recuperadas

    # -- leitura -------------------------------------------------------------

    def contar(self, estado: str) -> int:
        return len(self._listar(estado))

    def listar(self, estado: str) -> Iterator[Tarefa]:
        for caminho in self._listar(estado):
            yield self._ler(caminho)

    def estatisticas(self) -> dict[str, int]:
        return {estado: self.contar(estado) for estado in ESTADOS}

    # -- internos ------------------------------------------------------------

    def _listar(self, estado: str) -> list[Path]:
        if estado not in ESTADOS:
            raise ValueError(f"estado inválido: {estado}")
        return sorted((self.raiz / estado).glob("*.json"))

    def _caminho(self, tarefa: Tarefa, estado: str) -> Path:
        return self.raiz / estado / f"{tarefa.id}.json"

    def _gravar(self, tarefa: Tarefa, estado: str) -> Path:
        destino = self._caminho(tarefa, estado)
        temporario = destino.with_suffix(".json.tmp")
        temporario.write_text(
            json.dumps(tarefa.para_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporario, destino)  # gravação atômica
        return destino

    def _ler(self, caminho: Path) -> Tarefa:
        return Tarefa.do_dict(json.loads(caminho.read_text(encoding="utf-8")))

    def _mover(self, tarefa: Tarefa, de: str, para: str) -> None:
        origem = self._caminho(tarefa, de)
        self._gravar(tarefa, para)
        if origem.exists():
            origem.unlink()
