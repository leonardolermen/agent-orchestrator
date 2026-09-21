"""Como um item sabe de onde veio quando se abre em ramos.

Um bloco que ramifica consome o item e produz outro, com kind diferente. O
produzido precisa de id PRÓPRIO — `WorkSet` recusa id repetido —, e `{origem}+
{ramo}` é a forma que `agent/tarefa.py` já usava (`f"{item_id}+r"`) desde antes
destes blocos existirem.

**Isto é um CONTRATO, e por isso mora num lugar só.** Enquanto só `condicao` e
`tabela` produziam, a convenção podia ficar escrita numa f-string dentro de cada
um: ninguém precisava desfazê-la. `Juncao` precisa — ela reúne os ramos de um
mesmo item, e a única coisa que diz que `p1+fraude` e `p1+kyc` são o mesmo
pedido é esta regra. Uma f-string em três arquivos e um `split` num quarto é a
definição de acoplamento invisível: o dia em que alguém trocasse o separador,
a junção pararia de casar e não haveria erro nenhum — só itens que nunca se
encontram.
"""

_SEPARADOR = "+"


def id_no_ramo(origem: str, ramo: str) -> str:
    """O id do item produzido para `ramo` a partir de `origem`."""
    return f"{origem}{_SEPARADOR}{ramo}"


def origem_do_ramo(item_id: str) -> str:
    """De que item este veio. O próprio id quando ele nunca ramificou.

    `rsplit` e não `split`: um id de origem pode conter o separador (um item
    que já ramificou antes, `p1+fraude+revisado`), e quebrar no PRIMEIRO
    devolveria `p1` — reunindo itens que não são o mesmo. O último é sempre o
    ramo mais recente.
    """
    return item_id.rsplit(_SEPARADOR, 1)[0]


__all__ = ["id_no_ramo", "origem_do_ramo"]
