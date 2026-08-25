"""Sistema Operacional Pessoal — organização pessoal assistida por IA.

Arquitetura em quatro camadas:

    captura   -> integracoes/telegram.py
    decisão   -> orquestradora.py + integracoes/ia.py
    execução  -> agentes/ (definições) + fila.py
    registro  -> integracoes/notion.py + integracoes/google_calendar.py

Em cima dessas quatro camadas roda o ciclo semanal:

    regras.py  cruza a agenda da semana com as regras se-então do Notion
    ritual.py  monta o fechamento da semana e a abertura da seguinte
"""

from .config import Config, ConfiguracaoAusente
from .modelos import Classificacao, Item, Mensagem, ResultadoAutomacao
from .orquestradora import Orquestradora
from .automacao import Automacao
from .fila import Fila
from .regras import (
    EventoAgenda,
    ItemEstoque,
    MotorDeRegras,
    Regra,
    TarefaDerivada,
)
from .ritual import PacoteRitual, Ritual

__version__ = "0.1.0"

__all__ = [
    "Config",
    "ConfiguracaoAusente",
    "Mensagem",
    "Classificacao",
    "Item",
    "ResultadoAutomacao",
    "Orquestradora",
    "Automacao",
    "Fila",
    "Regra",
    "MotorDeRegras",
    "EventoAgenda",
    "ItemEstoque",
    "TarefaDerivada",
    "Ritual",
    "PacoteRitual",
    "__version__",
]
