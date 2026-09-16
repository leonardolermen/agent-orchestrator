"""A colheita: uma decisão humana vira um caso de avaliação.

**A seta que faltava.** O repositório já tinha as duas pontas — o revisor
decide (`review/`) e a avaliação mede (`metrics.py`) — e nada ligava uma à
outra. A consequência é que o produto ficava mais usado sem ficar mais medido:
cada correção humana era consumida uma vez, virava um match, e a informação
morria ali. É a diferença entre um sistema que roda e um que aprende a ser
medido.

**Os três vereditos valem, e cada um por um motivo diferente.**

- `corrigir`  — o humano afirmou um tipo diferente. Sinal mais forte, e
                negativo: é o caso que o agente errou.
- `rejeitar`  — a hipótese estava errada, mas ninguém disse qual é a certa.
                Vira caso de ABSTENÇÃO esperada (`kind=None`), não de erro.
- `aceitar`   — confirmação. Vira caso de REGRESSÃO: o que hoje acerta e não
                pode parar de acertar.

Colher só `corrigir` daria um conjunto só de fracassos, e um benchmark que só
tem caso difícil não detecta regressão no caso fácil — que é onde a regressão
costuma aparecer primeiro, porque é onde ninguém olha.

**Desvio deliberado do §14.3 do spec.** Lá a assinatura é
`harvest(proposal, decision, run)`. `Decision` mora em `review/`, cuja camada
alvo é `human`, e `PERMITIDO["evaluation"]` não inclui `human` — a assinatura do
spec é uma violação de arquitetura. Em vez de relaxar a tabela (que é decisão de
arquitetura, não ajuste de conveniência) ou de inventar um `Protocol` que
copiaria o nome `divergence_id` para dentro desta camada, a função recebe os
campos que usa. Quem desempacota a `Decision` é a fronteira do domínio, que já
conhece as duas palavras.
"""

from dataclasses import dataclass
from datetime import datetime

from orchestrator.kernel.run import Run
from orchestrator.kernel.work import WorkItem

from orchestrator.evaluation.case import EvaluationCase, ExpectedOutcome, Provenance

ACEITAR = "aceitar"
REJEITAR = "rejeitar"
CORRIGIR = "corrigir"
_VEREDITOS = (ACEITAR, REJEITAR, CORRIGIR)


@dataclass(frozen=True)
class NaoColhido:
    """Por que um caso NÃO foi colhido.

    Existe para que a colheita possa recusar sem ficar em silêncio. Um `None`
    solto faria uma fila de mil decisões produzir zero casos sem ninguém notar
    — a mesma classe de falha que `proposals_api_failed` elimina em
    `agent_eval`, e a mesma razão pela qual `render` deixa a coluna vazia em
    vez de imprimir zero.
    """

    item_id: str
    motivo: str


def colher(
    *,
    item_id: str,
    veredito: str,
    tipo_afirmado: str | None,
    snapshot: tuple[WorkItem, ...],
    run: Run,
    quando: datetime,
    autor: str = "",
    tags: frozenset[str] = frozenset(),
) -> EvaluationCase | NaoColhido:
    """Transforma uma decisão humana em caso, ou diz por que não deu.

    `quando` é a hora da DECISÃO, não a de agora: é ela que entra em
    `created_at` e, portanto, na guarda de contaminação. Usar o relógio da
    colheita faria um caso decidido ontem parecer criado hoje, e ele passaria a
    ser elegível para avaliar o run de ontem — que é exatamente a memorização
    que a guarda existe para impedir.
    """
    if veredito not in _VEREDITOS:
        raise ValueError(
            f"veredito desconhecido: {veredito!r}; use um de {_VEREDITOS}. "
            f"um veredito novo precisa de uma decisão sobre o que ele ensina, "
            f"não de um `else` silencioso"
        )
    if quando.tzinfo is None:
        raise ValueError("`quando` precisa de fuso (use UTC)")
    if not snapshot:
        return NaoColhido(item_id, "sem snapshot da entrada")
    if veredito == CORRIGIR and tipo_afirmado is None:
        return NaoColhido(item_id, "corrigir sem tipo afirmado")

    if veredito == CORRIGIR:
        # O humano afirmou. É a verdade mais forte que este sistema produz.
        esperado = ExpectedOutcome(
            kind=tipo_afirmado,
            note=f"corrigido por {autor}" if autor else "corrigido",
        )
        marcas = {"corrigido"}
    elif veredito == ACEITAR:
        esperado = ExpectedOutcome(
            kind=tipo_afirmado,
            note=f"confirmado por {autor}" if autor else "confirmado",
        )
        marcas = {"regressao"}
    else:
        # REJEITAR: sabemos que a hipótese estava errada e NÃO sabemos a certa.
        # `kind=None` é o registro honesto disso — e `medir` não pontua item
        # sem `kind` esperado, então este caso ensina a abster sem punir o
        # agente por um tipo que ninguém estabeleceu.
        esperado = ExpectedOutcome(
            kind=None,
            note=f"hipótese rejeitada por {autor}" if autor else "hipótese rejeitada",
        )
        marcas = {"abstencao"}

    return EvaluationCase(
        id=f"{run.id}:{item_id}",
        input_snapshot=snapshot,
        expected=esperado,
        provenance=Provenance.HUMANO,
        created_at=quando,
        source_run_id=run.id,
        tags=frozenset(marcas) | tags,
    )
