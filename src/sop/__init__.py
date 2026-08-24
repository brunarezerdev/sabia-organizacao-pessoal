"""Sistema Operacional Pessoal — organização pessoal assistida por IA.

Arquitetura em quatro camadas:

    captura   -> integracoes/telegram.py
    decisão   -> orquestradora.py + integracoes/ia.py
    execução  -> agentes/ (definições) + fila.py
    registro  -> integracoes/notion.py + integracoes/google_calendar.py
"""

from .config import Config, ConfiguracaoAusente
from .modelos import Classificacao, Item, Mensagem, ResultadoAutomacao
from .orquestradora import Orquestradora
from .automacao import Automacao
from .fila import Fila

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
    "__version__",
]
