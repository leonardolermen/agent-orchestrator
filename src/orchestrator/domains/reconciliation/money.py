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

    if "," in limpo:
        inteiros_bruto, _, decimais = limpo.partition(",")
        if len(decimais) == 1:
            decimais = decimais + "0"
        elif len(decimais) != 2:
            raise ValueError(f"valor monetário inválido: {texto!r}")
    else:
        inteiros_bruto, decimais = limpo, "00"

    inteiros = _remover_separador_de_milhar(inteiros_bruto, texto)

    if not inteiros.isdigit() or not decimais.isdigit():
        raise ValueError(f"valor monetário inválido: {texto!r}")

    centavos = int(inteiros) * 100 + int(decimais)
    return -centavos if negativo else centavos


def _remover_separador_de_milhar(inteiros: str, original: str) -> str:
    """Remove pontos de milhar, depois de validar o agrupamento de três.

    Sem validar, "10.5" (decimal americano, US$ 10,50) seria lido como
    R$ 1.050,00 — a mesma classe de corrupção silenciosa de dinheiro que este
    módulo existe para recusar, não adivinhar.
    """
    if "." not in inteiros:
        return inteiros

    grupos = inteiros.split(".")
    primeiro_valido = 1 <= len(grupos[0]) <= 3
    resto_valido = all(len(g) == 3 for g in grupos[1:])
    if not primeiro_valido or not resto_valido:
        raise ValueError(f"valor monetário inválido: {original!r}")

    return "".join(grupos)


def format_brl(centavos: int) -> str:
    """Formata centavos como texto em formato brasileiro."""
    sinal = "-" if centavos < 0 else ""
    inteiros, resto = divmod(abs(centavos), 100)
    inteiros_fmt = f"{inteiros:,}".replace(",", ".")
    return f"{sinal}R$ {inteiros_fmt},{resto:02d}"
