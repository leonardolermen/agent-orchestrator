"""O caso e o conjunto: o ativo, e a guarda que impede o benchmark de mentir."""

from datetime import UTC, datetime, timedelta

import pytest

from orchestrator.evaluation.case import (
    EvalDataset,
    EvaluationCase,
    ExpectedOutcome,
    Provenance,
)
from orchestrator.kernel.work import WorkItem

AGORA = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


def caso(cid="c-1", item="i-1", kind="BUG", quando=None, **kw) -> EvaluationCase:
    return EvaluationCase(
        id=cid,
        input_snapshot=(WorkItem(id=item, kind="issue", payload={"t": item}),),
        expected=ExpectedOutcome(kind=kind, **kw),
        provenance=Provenance.SINTETICO,
        created_at=quando or AGORA,
    )


def test_a_versao_e_derivada_do_CONTEUDO():
    a = EvalDataset(id="d", cases=(caso("c-1"), caso("c-2", item="i-2")))
    b = EvalDataset(id="d", cases=(caso("c-1"), caso("c-2", item="i-2")))

    assert a.version == b.version


def test_a_versao_NAO_depende_da_ordem():
    """Reordenar a mesma lista não é um conjunto diferente.

    Sem `sorted` no digest, montar os mesmos casos em outra ordem produziria
    outra versão — e um `BenchmarkResult` acusaria "o dataset mudou" quando o
    que mudou foi um `for`.
    """
    c1, c2 = caso("c-1"), caso("c-2", item="i-2")

    assert EvalDataset(id="d", cases=(c1, c2)).version == (
        EvalDataset(id="d", cases=(c2, c1)).version
    )


def test_a_versao_muda_quando_um_caso_entra():
    antes = EvalDataset(id="d", cases=(caso("c-1"),))
    depois = EvalDataset(id="d", cases=(caso("c-1"), caso("c-2", item="i-2")))

    assert antes.version != depois.version


def test_caso_repetido_e_recusado():
    with pytest.raises(ValueError, match="caso repetido"):
        EvalDataset(id="d", cases=(caso("c-1"), caso("c-1", item="i-2")))


def test_o_MESMO_item_em_dois_casos_e_recusado_na_indexacao():
    """A pontuação é item a item; um item em dois casos seria ambíguo."""
    ds = EvalDataset(id="d", cases=(caso("c-1", item="i-1"), caso("c-2", item="i-1")))

    with pytest.raises(ValueError, match="ambígua"):
        ds.by_item_id()


def test_created_at_sem_fuso_e_recusado():
    """Horário ingênuo não é um instante — e é ele que separa treino de teste."""
    with pytest.raises(ValueError, match="fuso"):
        EvaluationCase(
            id="c",
            input_snapshot=(WorkItem(id="i", kind="k", payload=None),),
            expected=ExpectedOutcome(),
            provenance=Provenance.HUMANO,
            created_at=datetime(2026, 9, 16, 12, 0),
        )


def test_caso_sem_snapshot_e_recusado():
    """Um caso que não carrega a entrada é uma anotação, não um caso."""
    with pytest.raises(ValueError, match="input_snapshot"):
        EvaluationCase(
            id="c",
            input_snapshot=(),
            expected=ExpectedOutcome(),
            provenance=Provenance.HUMANO,
            created_at=AGORA,
        )


# -- a guarda de contaminação ----------------------------------------------


def test_caso_criado_DEPOIS_do_run_e_excluido():
    """O coração do §14.3: um caso colhido de um run não avalia esse run.

    Sem isto, colher e medir viraria um laço fechado — o agente seria pontuado
    contra a correção do erro que acabou de cometer, e o número subiria sozinho
    a cada colheita, sem o sistema ter melhorado em nada.
    """
    velho = caso("velho", item="i-1", quando=AGORA - timedelta(hours=1))
    novo = caso("novo", item="i-2", quando=AGORA + timedelta(hours=1))
    ds = EvalDataset(id="d", cases=(velho, novo))

    elegiveis = ds.elegiveis_para(AGORA)

    assert [c.id for c in elegiveis.cases] == ["velho"]


def test_o_recorte_tem_VERSAO_PROPRIA():
    """O recorte é um conjunto diferente, e dizer que é o mesmo esconderia a
    exclusão — alguém compararia dois resultados de 'mesma versão' medidos
    sobre conjuntos distintos."""
    ds = EvalDataset(
        id="d",
        cases=(
            caso("velho", item="i-1", quando=AGORA - timedelta(hours=1)),
            caso("novo", item="i-2", quando=AGORA + timedelta(hours=1)),
        ),
    )

    assert ds.elegiveis_para(AGORA).version != ds.version


def test_caso_criado_no_INSTANTE_do_run_e_excluido():
    """Estritamente anterior. Empate vai para a exclusão: um caso criado no
    mesmo instante do início do run não tem como ter sido colhido antes dele,
    e a dúvida resolve contra medir memorização."""
    ds = EvalDataset(id="d", cases=(caso("empate", quando=AGORA),))

    assert ds.elegiveis_para(AGORA).cases == ()
