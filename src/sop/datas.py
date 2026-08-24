"""Resolução de datas relativas em português.

Usado pelo classificador heurístico (que roda sem IA) e como normalizador das
datas devolvidas pela camada de IA.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

DIAS_SEMANA = {
    "segunda": 0,
    "terca": 1,
    "terça": 1,
    "quarta": 2,
    "quinta": 3,
    "sexta": 4,
    "sabado": 5,
    "sábado": 5,
    "domingo": 6,
}

_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DIA_MES = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
_HORA = re.compile(r"\b([01]?\d|2[0-3])(?:[:h](\d{2}))?\s*(?:h|hs|horas)?\b")


def resolver_data(texto: str, hoje: date) -> str | None:
    """Devolve uma data ISO (AAAA-MM-DD) encontrada no texto, ou None.

    Reconhece data absoluta (ISO ou DD/MM), "hoje", "amanhã", "depois de
    amanhã" e nomes de dia da semana (sempre o próximo, nunca o passado).
    """
    minusculo = texto.lower()

    achado = _ISO.search(texto)
    if achado:
        ano, mes, dia = (int(g) for g in achado.groups())
        try:
            return date(ano, mes, dia).isoformat()
        except ValueError:
            return None

    achado = _DIA_MES.search(texto)
    if achado:
        dia, mes, ano = achado.group(1), achado.group(2), achado.group(3)
        ano_int = hoje.year if ano is None else int(ano)
        if ano_int < 100:
            ano_int += 2000
        try:
            return date(ano_int, int(mes), int(dia)).isoformat()
        except ValueError:
            return None

    if "depois de amanha" in minusculo or "depois de amanhã" in minusculo:
        return (hoje + timedelta(days=2)).isoformat()
    if "amanha" in minusculo or "amanhã" in minusculo:
        return (hoje + timedelta(days=1)).isoformat()
    if "hoje" in minusculo:
        return hoje.isoformat()

    for nome, indice in DIAS_SEMANA.items():
        if re.search(rf"\b{nome}\b", minusculo):
            adiante = (indice - hoje.weekday()) % 7
            # "sexta" dito numa sexta significa a próxima sexta, não hoje.
            return (hoje + timedelta(days=adiante or 7)).isoformat()

    return None


def resolver_hora(texto: str) -> str | None:
    """Devolve uma hora no formato HH:MM encontrada no texto, ou None."""
    for achado in _HORA.finditer(texto.lower()):
        inteiro, minuto = achado.group(1), achado.group(2)
        contexto = achado.group(0)
        # Só aceita se houver marcador de hora explícito (":", "h" ou "horas").
        if minuto is None and not re.search(r"h", contexto):
            continue
        return f"{int(inteiro):02d}:{int(minuto or 0):02d}"
    return None


def normalizar_data(valor: str | None, hoje: date) -> str | None:
    """Aceita ISO pronta ou expressão relativa e devolve sempre ISO ou None."""
    if not valor:
        return None
    valor = valor.strip()
    if _ISO.fullmatch(valor):
        return valor
    return resolver_data(valor, hoje)
