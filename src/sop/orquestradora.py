"""A orquestradora: recebe a mensagem, decide quem cuida e despacha.

É a peça central da arquitetura. Não executa trabalho de domínio — não grava no
Notion, não cria evento, não formata nada. Só entende, decide e entrega para o
agente certo. Toda a lógica específica de cada domínio mora na definição do
agente (em `agentes/*.md`) e no destino que a automação usa.

Esse desenho é o que permite acrescentar um agente novo sem tocar no código:
basta criar o arquivo de definição.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

from .agentes import AgenteDef, Registro, carregar_registro
from .fila import Fila
from .modelos import Classificacao, Item, Mensagem

AGENTE_PADRAO = "beija-flor"


class Orquestradora:
    def __init__(
        self,
        adaptador_ia: Any,
        registro: Registro | None = None,
        fila: Fila | None = None,
        hoje: Callable[[], date] = date.today,
    ) -> None:
        self.ia = adaptador_ia
        self.registro = registro if registro is not None else carregar_registro()
        self.fila = fila
        self._hoje = hoje

    # -- decisão -------------------------------------------------------------

    def classificar(self, mensagem: Mensagem) -> Classificacao:
        """Pede à camada de IA a leitura estruturada da mensagem."""
        classificacao = self.ia.classificar(
            mensagem.texto, self.registro, self._hoje()
        )
        return self._validar(classificacao)

    def _validar(self, c: Classificacao) -> Classificacao:
        """Garante que a classificação aponta para um agente que existe."""
        if c.agente in self.registro:
            agente = self.registro.obter(c.agente)
            assert agente is not None
            if not agente.aceita(c.categoria):
                # Agente certo, categoria estranha: usa a primeira do agente.
                c.categoria = agente.categorias[0] if agente.categorias else c.categoria
                c.precisa_confirmacao = True
            return c

        # Agente desconhecido: tenta resgatar pela categoria antes de desistir.
        pela_categoria = self.registro.por_categoria(c.categoria)
        if pela_categoria is not None:
            c.agente = pela_categoria.nome
            return c

        c.agente = AGENTE_PADRAO
        c.precisa_confirmacao = True
        return c

    def agente_de(self, classificacao: Classificacao) -> AgenteDef | None:
        return self.registro.obter(classificacao.agente)

    # -- despacho ------------------------------------------------------------

    def processar(self, mensagem: Mensagem) -> tuple[Classificacao, Item]:
        """Classifica e monta o item pronto para gravação."""
        classificacao = self.classificar(mensagem)
        item = Item.da_classificacao(classificacao, mensagem)
        return classificacao, item

    def despachar(self, mensagem: Mensagem) -> str:
        """Coloca a mensagem na fila durável e devolve o id da tarefa.

        Usado no modo assíncrono: a captura responde na hora e o processamento
        acontece em outro processo, sem segurar quem mandou a mensagem.
        """
        if self.fila is None:
            raise RuntimeError(
                "Esta orquestradora foi criada sem fila. "
                "Passe uma instância de Fila para usar o despacho assíncrono."
            )
        tarefa = self.fila.enfileirar(
            {
                "mensagem_id": mensagem.id,
                "texto": mensagem.texto,
                "autor": mensagem.autor,
                "canal": mensagem.canal,
                "recebida_em": mensagem.recebida_em,
            }
        )
        return tarefa.id

    def deve_criar_evento(self, classificacao: Classificacao) -> bool:
        """Um item vira evento na agenda quando tem data e o agente permite."""
        agente = self.agente_de(classificacao)
        return bool(agente and agente.cria_evento and classificacao.data)
