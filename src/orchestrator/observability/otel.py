"""Exportador para OpenTelemetry. Mão única, e sob o extra `[otel]`.

**Por que `Span` é modelo próprio e OTel é só saída** (ADR-08):

  - custo em micro-centavos `int` não tem lugar canônico em OTel e viraria
    atributo float. Ponto flutuante em dinheiro é proibido neste projeto, e
    "só no exportador" é exatamente como esse tipo de erro entra;
  - `status="abstencao"` e `status="pulado"` não são OK nem ERROR. São
    desfechos legítimos e comercialmente distintos — abstenção custou dinheiro,
    pulado economizou — e o mapeamento OTel os colapsaria em OK;
  - depender de OTel no kernel adicionaria dependência de runtime a um pacote
    que hoje tem UMA.

Quem quiser Langfuse, Phoenix ou Braintrust escreve um exportador de 40 linhas
sobre `Span`, como este. Quem não quiser não instala nada.
"""

from typing import Any

from orchestrator.kernel.trace import Span, SpanStatus, Trace

# O custo vai como atributo INTEIRO, em micro-centavos, e não como float de
# dólares. Um consumidor OTel que queira dólares divide; o inverso perde
# precisão, e perder precisão em dinheiro é o defeito que este projeto recusa
# desde `money.py`.
ATRIBUTO_CUSTO = "orchestrator.cost.microcents"
ATRIBUTO_STATUS = "orchestrator.status"


def atributos(span: Span, model: str) -> dict[str, Any]:
    """Os atributos OTel de um span, incluindo os que OTel não modela.

    `orchestrator.status` existe porque `abstencao` e `pulado` não cabem no
    status de OTel. Quem lê o trace exportado consegue reconstruir a distinção;
    quem lê só o status de OTel vê `OK` e perde a informação — e é por isso que
    o atributo vai junto.
    """
    base: dict[str, Any] = {
        "orchestrator.kind": span.kind.value,
        ATRIBUTO_STATUS: span.status.value,
    }
    if span.cost.calls:
        base[ATRIBUTO_CUSTO] = span.cost.microcents(model)
        base["orchestrator.tokens.input"] = span.cost.input_tokens
        base["orchestrator.tokens.output"] = span.cost.output_tokens
        base["orchestrator.llm.calls"] = span.cost.calls
    for k, v in span.attributes.items():
        if isinstance(v, str | int | float | bool):
            base[f"orchestrator.{k}"] = v
    return base


def otel_status(span: Span) -> str:
    """OTel só tem OK e ERROR. `abstencao` e `pulado` viram OK — e a informação
    que se perde aí é a que `ATRIBUTO_STATUS` preserva."""
    return "ERROR" if span.status is SpanStatus.ERRO else "OK"


def export(trace: Trace, tracer: Any, model: str = "claude-opus-5") -> None:
    """Exporta a árvore para um `Tracer` de OTel.

    Recebe o `tracer` por parâmetro em vez de construí-lo: configurar OTel é
    decisão de quem hospeda, não deste módulo. É a mesma disciplina de
    `AnthropicClient`, que aceita o SDK injetável para que importar o módulo
    não exija credencial.
    """
    from opentelemetry.trace import SpanContext, set_span_in_context  # noqa: F401

    contextos: dict[str, Any] = {}
    # Pais antes de filhos: `Trace.spans` não garante ordem topológica, e um
    # filho exportado antes do pai ficaria órfão no backend.
    for span in _topologico(trace):
        pai = contextos.get(span.parent_id) if span.parent_id else None
        with tracer.start_as_current_span(
            f"{span.kind.value}:{span.name}",
            context=pai,
            attributes=atributos(span, model),
        ) as otel_span:
            otel_span.set_status(otel_status(span))
            if span.error:
                otel_span.record_exception(RuntimeError(span.error))
            contextos[span.id] = set_span_in_context(otel_span)


def _topologico(trace: Trace) -> list[Span]:
    """Raiz primeiro, depois cada nível. Sem recursão: a árvore é rasa (run →
    stage → resolver → item → llm/tool), e uma fila é mais fácil de ler."""
    por_pai: dict[str | None, list[Span]] = {}
    for s in trace.spans:
        por_pai.setdefault(s.parent_id, []).append(s)
    ordenados: list[Span] = []
    fila = list(por_pai.get(None, []))
    while fila:
        atual = fila.pop(0)
        ordenados.append(atual)
        fila.extend(por_pai.get(atual.id, []))
    return ordenados
