"""Ler um campo de um payload que a regra não conhece.

`WorkItem.payload` é `Any`, e o kernel nunca o inspeciona — ele só move ids
(`kernel/work.py`). Uma regra de domínio contorna isso conhecendo o tipo:
`ExactMatcher` lê `be.document` porque sabe que ali vem um `BankEntry`.

Uma regra GENÉRICA não pode saber. Ela recebe o nome do campo de quem a
configurou na tela, e o payload pode chegar como dataclass (fonte sintética) ou
como `dict` (fonte de arquivo, banco ou API). O contrato já previa este caso:
o default de `ResolverDescription.payloads` é documentado como "não inspeciono
o payload: um resolver que só move ids, **ou que trata o payload como mapa de
campos**, roda sobre qualquer fonte".

`getattr`/`[]` direto em vez de `dataclasses.asdict` (que é o que
`agent/declarado.py` usa para interpolar prompt): `asdict` copia a estrutura
inteira em profundidade, e uma regra de casamento lê campo de cada item contra
cada candidato — num pool de centenas, a cópia domina o tempo do casamento
inteiro.
"""

from collections.abc import Mapping
from typing import Any

_AUSENTE = object()


class CampoAusente(ValueError):
    """O payload não tem o campo que a regra foi configurada para ler.

    Erro PRÓPRIO, e não o `AttributeError`/`KeyError` cru, porque a causa quase
    nunca está onde a exceção nasce: alguém escolheu na tela um campo que a
    fonte não entrega, e o `AttributeError: 'dict' object has no attribute
    'documento'` que sairia daqui não diz isso — é o modo de falha que o
    comentário de `ResolverDescription.payloads` descreve, "um erro de servidor
    sobre uma escolha do cliente".
    """


def valor_do_campo(payload: Any, campo: str) -> Any:
    """O valor de `campo` no payload, seja ele dataclass ou mapa."""
    if isinstance(payload, Mapping):
        achado = payload.get(campo, _AUSENTE)
    else:
        achado = getattr(payload, campo, _AUSENTE)
    if achado is _AUSENTE:
        raise CampoAusente(
            f"o payload não tem o campo {campo!r}. disponíveis: "
            f"{sorted(nomes_de_campo(payload))}"
        )
    return achado


def nomes_de_campo(payload: Any) -> frozenset[str]:
    """Os campos que este payload oferece. Para mensagem de erro e validação."""
    if isinstance(payload, Mapping):
        return frozenset(payload)
    return frozenset(v for v in vars(payload)) if hasattr(payload, "__dict__") else frozenset()


__all__ = ["CampoAusente", "nomes_de_campo", "valor_do_campo"]
