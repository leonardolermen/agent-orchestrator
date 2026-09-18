"""`"campoEsq=campoDir"` — como a tela diz em quais campos uma regra opera.

Uma regra genérica casa itens de DOIS lados, e os dois lados raramente chamam a
mesma coisa pelo mesmo nome: na conciliação, `document` de um lado é `document`
do outro, mas `amount` corresponde a `net_amount` e `date` a `cash_date`.

O par é uma STRING e não dois campos paralelos (`campos_esquerda` +
`campos_direita`) de propósito: duas listas paralelas podem ficar com tamanhos
diferentes, e o erro aparece como casamento vazio em vez de recusa. É o mesmo
join frágil que o `ToolRegistry` já eliminou uma vez — o que estava em dois
lugares que podem divergir passa a estar num só.

`"document"` sozinho significa `"document=document"`. É o caso comum, e
escrever o nome duas vezes convida a errar um dos dois.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Par:
    """Um campo de cada lado, comparados entre si."""

    esquerda: str
    direita: str

    def __str__(self) -> str:
        return (
            self.esquerda
            if self.esquerda == self.direita
            else f"{self.esquerda}={self.direita}"
        )


def interpretar(texto: str) -> Par:
    """`"a=b"` vira `Par("a", "b")`; `"a"` vira `Par("a", "a")`.

    Recusa na CONSTRUÇÃO, nunca no casamento: uma regra malformada que só
    falhasse ao rodar apareceria como "não casou nada", indistinguível de "não
    havia nada para casar" — e é essa confusão que este repositório trata como
    a pior classe de defeito.
    """
    partes = texto.split("=")
    if len(partes) == 1:
        nome = partes[0].strip()
        if not nome:
            raise ValueError("campo vazio na lista de campos")
        return Par(nome, nome)
    if len(partes) != 2:
        raise ValueError(
            f"campo {texto!r} tem mais de um '='. a forma é "
            f"'campoDaEsquerda=campoDaDireita', ou só o nome quando os dois "
            f"lados o chamam igual"
        )
    esq, dir_ = (p.strip() for p in partes)
    if not esq or not dir_:
        raise ValueError(
            f"campo {texto!r} tem um lado vazio. a forma é "
            f"'campoDaEsquerda=campoDaDireita'"
        )
    return Par(esq, dir_)


def interpretar_todos(textos: tuple[str, ...]) -> tuple[Par, ...]:
    """A lista inteira, ou levanta na primeira malformada."""
    if not textos:
        raise ValueError(
            "a regra precisa de pelo menos um campo: sem campo nenhum ela "
            "casaria qualquer item com qualquer outro"
        )
    pares = tuple(interpretar(t) for t in textos)
    vistos: set[str] = set()
    for p in pares:
        if p.esquerda in vistos:
            raise ValueError(
                f"campo da esquerda repetido: {p.esquerda!r}. o segundo par "
                f"não acrescenta condição nenhuma, e ter os dois sugere que um "
                f"deles era para ser outro campo"
            )
        vistos.add(p.esquerda)
    return pares


__all__ = ["Par", "interpretar", "interpretar_todos"]
