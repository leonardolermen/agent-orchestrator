"""Aritmética de dias úteis.

Trata apenas fins de semana. Feriados nacionais e municipais não são
considerados neste plano — quando forem, entram como uma tabela de datas
consultada por estas mesmas funções, sem mudar as assinaturas.
"""

from datetime import date, timedelta


def _e_dia_util(d: date) -> bool:
    return d.weekday() < 5


def business_days_between(a: date, b: date) -> int:
    """Conta dias úteis entre duas datas, em qualquer ordem."""
    if a > b:
        a, b = b, a
    dias = 0
    atual = a
    while atual < b:
        atual += timedelta(days=1)
        if _e_dia_util(atual):
            dias += 1
    return dias


def add_business_days(d: date, n: int) -> date:
    """Avança n dias úteis a partir de d."""
    if n < 0:
        raise ValueError(f"n não pode ser negativo: {n}")
    atual = d
    restantes = n
    while restantes > 0:
        atual += timedelta(days=1)
        if _e_dia_util(atual):
            restantes -= 1
    return atual
