"""Clientes das APIs externas usadas pelo sistema."""

from .telegram import ClienteTelegram
from .notion import ClienteNotion
from .google_calendar import ClienteGoogleCalendar
from .ia import AdaptadorIA, criar_adaptador

__all__ = [
    "ClienteTelegram",
    "ClienteNotion",
    "ClienteGoogleCalendar",
    "AdaptadorIA",
    "criar_adaptador",
]
