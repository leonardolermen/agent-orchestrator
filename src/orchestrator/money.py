"""Dinheiro em centavos. Ponto flutuante é proibido neste projeto."""

import re

_LIMPEZA = re.compile(r"[R$\s]")


def parse_brl(texto: str) -> int:
    """Converte texto em formato brasileiro para centavos.

    Aceita "R$ 1.234,56", "1234,56", "-R$ 10,00", "R$ 50".
    """
    limpo = _LIMPEZA.sub("", texto)
    if not limpo:
        raise ValueError(f"valor monetário vazio: {texto!r}")

    negativo = limpo.startswith("-")
    limpo = limpo.lstrip("-+")
    limpo = limpo.replace(".", "")

    if "," in limpo:
        inteiros, _, decimais = limpo.partition(",")
        if len(decimais) == 1:
            decimais = decimais + "0"
        elif len(decimais) != 2:
            raise ValueError(f"valor monetário inválido: {texto!r}")
    else:
        inteiros, decimais = limpo, "00"

    if not inteiros.isdigit() or not decimais.isdigit():
        raise ValueError(f"valor monetário inválido: {texto!r}")

    centavos = int(inteiros) * 100 + int(decimais)
    return -centavos if negativo else centavos


def format_brl(centavos: int) -> str:
    """Formata centavos como texto em formato brasileiro."""
    sinal = "-" if centavos < 0 else ""
    inteiros, resto = divmod(abs(centavos), 100)
    inteiros_fmt = f"{inteiros:,}".replace(",", ".")
    return f"{sinal}R$ {inteiros_fmt},{resto:02d}"
