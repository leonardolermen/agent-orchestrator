"""O exportador OTel — mão única, e o que ele NÃO consegue carregar."""

from orchestrator.kernel.cost import Cost
from orchestrator.kernel.trace import Span, SpanKind, SpanStatus
from orchestrator.observability.otel import (
    ATRIBUTO_CUSTO,
    ATRIBUTO_STATUS,
    atributos,
    otel_status,
)


def _span(status=SpanStatus.OK, cost=None) -> Span:
    return Span(
        id="a",
        parent_id=None,
        kind=SpanKind.LLM,
        name="turno 1",
        status=status,
        cost=cost or Cost.zero(),
    )


def test_o_custo_vai_como_INTEIRO_em_microcents():
    """Não como float de dólares.

    Um consumidor OTel que queira dólares divide; o inverso perde precisão, e
    perder precisão em dinheiro é o defeito que este projeto recusa desde
    `money.py`. É metade da razão de OTel ser exportador e não modelo (ADR-08).
    """
    a = atributos(_span(cost=Cost(input_tokens=1000, calls=1)), "claude-opus-5")

    assert a[ATRIBUTO_CUSTO] == 500_000
    assert isinstance(a[ATRIBUTO_CUSTO], int)


def test_abstencao_e_pulado_viram_OK_no_status_de_OTel():
    """OTel só tem OK e ERROR. É a outra metade da razão do ADR-08."""
    assert otel_status(_span(SpanStatus.ABSTENCAO)) == "OK"
    assert otel_status(_span(SpanStatus.PULADO)) == "OK"
    assert otel_status(_span(SpanStatus.ERRO)) == "ERROR"


def test_o_status_REAL_vai_num_atributo_proprio():
    """A informação que o status de OTel perde é preservada aqui.

    Sem isto, "o agente absteve" e "o agente respondeu" chegariam idênticos ao
    backend — e a taxa de abstenção, que é métrica de produto, sumiria.
    """
    for status in SpanStatus:
        assert atributos(_span(status), "claude-opus-5")[ATRIBUTO_STATUS] == status.value


def test_span_sem_chamada_nao_reporta_custo():
    """Um resolver de regra não gastou token, e reportar `custo=0` seria
    indistinguível de "não medido" — a distinção que `cost_by_resolver` existe
    para preservar."""
    assert ATRIBUTO_CUSTO not in atributos(_span(), "claude-opus-5")


def test_o_kernel_nao_importa_otel():
    """Dependência de runtime num pacote que tem UMA."""
    import pathlib

    kernel = pathlib.Path("src/orchestrator/kernel")
    for arquivo in kernel.rglob("*.py"):
        assert "opentelemetry" not in arquivo.read_text(encoding="utf-8")
