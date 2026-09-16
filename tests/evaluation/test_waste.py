"""Economia de ferramenta, reproduzindo o achado medido no domínio `swe`.

Em 2026-09-16, rodando `swe` contra `claude-haiku-4-5`: `contar_palavras` foi
chamada em 5 de 5 issues e o turno que ela provocou custou mais que o turno
original. Nenhum dos 623 testes viu, porque nenhum olhava para o dinheiro.

Estes testes usam um trace sintético com a MESMA forma da execução real.
"""

from orchestrator.evaluation.waste import medir_ferramentas
from orchestrator.kernel.cost import Cost
from orchestrator.kernel.trace import Span, SpanKind, Trace

MODELO = "claude-haiku-4-5"


def _trace_swe(itens=5, com_ferramenta=True) -> Trace:
    """Um item por issue: turno 1, ferramenta, turno 2 — a forma medida."""
    spans = [Span(id="run", parent_id=None, kind=SpanKind.RUN, name="swe")]
    for n in range(itens):
        iid = f"I-{n + 1}"
        spans.append(Span(id=iid, parent_id="run", kind=SpanKind.ITEM, name=iid))
        spans.append(
            Span(
                id=f"{iid}-llm1",
                parent_id=iid,
                kind=SpanKind.LLM,
                name="turno 1",
                cost=Cost(input_tokens=740, output_tokens=100, calls=1),
            )
        )
        if not com_ferramenta:
            continue
        spans.append(
            Span(
                id=f"{iid}-tool",
                parent_id=iid,
                kind=SpanKind.TOOL,
                name="contar_palavras",
            )
        )
        spans.append(
            Span(
                id=f"{iid}-llm2",
                parent_id=iid,
                kind=SpanKind.LLM,
                name="turno 2",
                cost=Cost(input_tokens=858, output_tokens=152, calls=1),
            )
        )
    return Trace(run_id="r", spans=tuple(spans))


def test_o_achado_do_swe_e_reproduzido():
    """Cinco de cinco itens, e mais da metade do custo no turno provocado."""
    economia = medir_ferramentas(_trace_swe(), model=MODELO)

    (uso,) = economia.usos
    assert uso.nome == "contar_palavras"
    assert uso.chamadas == 5
    assert uso.itens_alcancados == 5
    assert uso.fracao_de(economia.total_microcents) > 0.5


def test_cobertura_total_vira_CANDIDATO_a_braco_de_benchmark():
    """O sinal é a cobertura: uma ferramenta que o prompt oferece como
    condicional e que é chamada em 100% dos itens não está sendo usada
    condicionalmente."""
    economia = medir_ferramentas(_trace_swe(), model=MODELO)

    (candidato,) = economia.candidatos()
    assert candidato.nome == "contar_palavras"
    assert "Compare um braço sem ela" in economia.render()


def test_ferramenta_ESPORADICA_nao_vira_candidato():
    """Chamada em um de cinco é uso condicional funcionando — exatamente o que
    o prompt pediu. Apontá-la seria ruído."""
    trace = _trace_swe(itens=5, com_ferramenta=False)
    extra = (
        Span(id="I-1-tool", parent_id="I-1", kind=SpanKind.TOOL, name="contar_palavras"),
        Span(
            id="I-1-llm2",
            parent_id="I-1",
            kind=SpanKind.LLM,
            name="turno 2",
            cost=Cost(input_tokens=858, output_tokens=152, calls=1),
        ),
    )
    economia = medir_ferramentas(
        Trace(run_id="r", spans=trace.spans + extra), model=MODELO
    )

    assert economia.usos[0].itens_alcancados == 1
    assert economia.candidatos() == ()


def test_ele_NAO_chama_de_desperdicio_o_que_nao_comparou():
    """O módulo mede e aponta; quem julga é o benchmark. Chamar de desperdício
    o que não tem contrafactual seria a mesma classe de erro que relatar custo
    zero quando nada foi medido."""
    saida = medir_ferramentas(_trace_swe(), model=MODELO).render()

    assert "desperdício" not in saida.lower()
    assert "candidato" in saida


def test_pagar_a_ferramenta_e_ainda_assim_abster_e_CONTADO():
    """O caso mais caro que existe: gastou a ida e volta e continuou sem saber."""
    economia = medir_ferramentas(
        _trace_swe(), model=MODELO, abstiveram=frozenset({"I-2", "I-4"})
    )

    assert economia.usos[0].itens_que_abstiveram == 2
    assert "abstiveram mesmo depois" in economia.render()


def test_sem_ferramenta_nenhuma_o_relatorio_diz_isso():
    economia = medir_ferramentas(_trace_swe(com_ferramenta=False), model=MODELO)

    assert economia.usos == ()
    assert "nenhuma ferramenta" in economia.render()


def test_so_o_custo_APOS_a_chamada_e_atribuido_a_ela():
    """O turno 1 acontece antes de qualquer ferramenta e não pode ser cobrado
    dela — senão toda ferramenta pareceria responsável por 100% do custo."""
    economia = medir_ferramentas(_trace_swe(itens=1), model=MODELO)

    turno1 = Cost(input_tokens=740, output_tokens=100, calls=1).microcents(MODELO)
    turno2 = Cost(input_tokens=858, output_tokens=152, calls=1).microcents(MODELO)

    assert economia.usos[0].microcents_provocados == turno2
    assert economia.total_microcents == turno1 + turno2
