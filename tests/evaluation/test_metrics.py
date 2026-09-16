"""As métricas genéricas, e as três coisas que elas se recusam a inventar."""

from datetime import UTC, datetime

import pytest

from orchestrator.evaluation.case import (
    EvalDataset,
    EvaluationCase,
    ExpectedOutcome,
    Provenance,
)
from orchestrator.evaluation.metrics import medir
from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.resolution import Confidence, Proposal, Resolution
from orchestrator.kernel.run import Run, RunState
from orchestrator.kernel.work import WorkItem

AGORA = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
MODELO = "claude-haiku-4-5"
DUVIDA = frozenset({"DUVIDA"})


def _caso(item, kind, deterministico=False) -> EvaluationCase:
    return EvaluationCase(
        id=f"c-{item}",
        input_snapshot=(WorkItem(id=item, kind="issue", payload=None),),
        expected=ExpectedOutcome(
            kind=kind, should_resolve_deterministically=deterministico
        ),
        provenance=Provenance.SINTETICO,
        created_at=AGORA,
    )


def _proposta(item, tipo, evidencia=("e",)) -> Proposal:
    return Proposal(
        item_id=item,
        tipo=tipo,
        explicacao="",
        evidencia=list(evidencia),
        confianca=Confidence.MEDIA,
        acao_sugerida="revisar_manual",
        cost=Cost(input_tokens=1000, output_tokens=100, calls=1),
    )


def _run(propostas=(), por_classe=None, custo=None) -> Run:
    return Run(
        id="r-1",
        workflow_id="w",
        workflow_version="1",
        state=RunState.CONCLUIDO,
        started_at=AGORA,
        input_ref="",
        proposals=tuple(propostas),
        resolutions_by_class=por_classe or {},
        cost_by_resolver={"agente": custo or Cost(input_tokens=1000, output_tokens=100)},
    )


# -- o que o módulo se recusa a inventar ------------------------------------


def test_custo_por_acerto_e_None_e_NAO_zero_quando_nao_houve_acerto():
    """Zero se leria como "de graça", que é o oposto do que aconteceu: gastou
    e não acertou nada. Mesma disciplina de `EvalResult.custo_medido`."""
    ds = EvalDataset(id="d", cases=(_caso("i-1", "BUG"),))
    run = _run(propostas=[_proposta("i-1", "FEATURE")])

    metricas = medir(run, ds, model=MODELO, abstem_com=DUVIDA)

    assert metricas.microcents_per_correct_proposal is None
    assert metricas.microcents_total > 0
    assert "não definido" in metricas.render()


def test_sem_trace_a_latencia_e_None_e_NAO_zero():
    ds = EvalDataset(id="d", cases=(_caso("i-1", "BUG"),))

    metricas = medir(_run(), ds, model=MODELO, abstem_com=DUVIDA)

    assert metricas.p50_latency_ms is None
    assert "Latência" not in metricas.render()


def test_dataset_vazio_e_recusado_em_vez_de_render_0_por_cento():
    with pytest.raises(ValueError, match="divisão por zero"):
        medir(_run(), EvalDataset(id="vazio"), model=MODELO, abstem_com=DUVIDA)


# -- o vocabulário de abstenção é do DOMÍNIO --------------------------------


def test_o_MESMO_run_pontua_diferente_com_outro_vocabulario_de_abstencao():
    """É a prova de que a camada não sabe o que é "não sei".

    `orchestrator/metrics.py` compara contra `DivergenceType.NAO_IDENTIFICADO`
    direto, e essa linha é a violação `metrics -> taxonomy` da catraca. Aqui o
    vocabulário entra pela chamada, e trocá-lo muda o resultado — o que só é
    possível porque nada está fixo dentro.
    """
    ds = EvalDataset(id="d", cases=(_caso("i-1", "BUG"),))
    run = _run(propostas=[_proposta("i-1", "DUVIDA", evidencia=())])

    como_abstencao = medir(run, ds, model=MODELO, abstem_com=DUVIDA)
    como_resposta = medir(run, ds, model=MODELO, abstem_com=frozenset())

    assert como_abstencao.proposals_abstained == 1
    assert como_resposta.proposals_abstained == 0
    assert como_resposta.proposals_correct == 0  # respondeu DUVIDA, esperado BUG


# -- item sem verdade estabelecida ------------------------------------------


def test_item_sem_kind_esperado_NAO_conta_como_erro():
    """O caso colhido de um REJEITAR: sabemos que a hipótese antiga estava
    errada e não sabemos a certa.

    Contá-lo como erro faria a precisão CAIR ao colher casos de rejeição —
    exatamente quando o conjunto está ficando melhor.
    """
    sem_verdade = EvaluationCase(
        id="c-2",
        input_snapshot=(WorkItem(id="i-2", kind="issue", payload=None),),
        expected=ExpectedOutcome(kind=None),
        provenance=Provenance.HUMANO,
        created_at=AGORA,
    )
    ds = EvalDataset(id="d", cases=(_caso("i-1", "BUG"), sem_verdade))
    run = _run(propostas=[_proposta("i-1", "BUG"), _proposta("i-2", "FEATURE")])

    metricas = medir(run, ds, model=MODELO, abstem_com=DUVIDA)

    assert metricas.proposals_correct == 1
    assert metricas.proposal_precision == 1.0  # o i-2 não entra no denominador


# -- falso positivo e falso negativo, na forma genérica ---------------------


def test_falso_positivo_e_resolucao_deterministica_que_nao_deveria_existir():
    ds = EvalDataset(id="d", cases=(_caso("i-1", "BUG", deterministico=False),))
    run = _run(
        por_classe={
            CostClass.REGRA: [
                Resolution(item_ids=frozenset({"i-1"}), produced_by="L1", rule="exata")
            ]
        }
    )

    metricas = medir(run, ds, model=MODELO, abstem_com=DUVIDA)

    assert metricas.false_positives == 1
    assert metricas.false_negatives == 0


def test_falso_negativo_e_o_que_deveria_fechar_de_graca_e_nao_fechou():
    ds = EvalDataset(id="d", cases=(_caso("i-1", "BUG", deterministico=True),))

    metricas = medir(_run(), ds, model=MODELO, abstem_com=DUVIDA)

    assert metricas.false_negatives == 1
    assert metricas.false_positives == 0


def test_escalada_para_humano_entra_na_taxa_propria():
    ds = EvalDataset(id="d", cases=(_caso("i-1", "BUG"), _caso("i-2", "BUG")))
    run = _run(
        por_classe={
            CostClass.HUMANO: [
                Resolution(item_ids=frozenset({"i-1"}), produced_by="revisor", rule="ok")
            ]
        }
    )

    metricas = medir(run, ds, model=MODELO, abstem_com=DUVIDA)

    assert metricas.escalation_rate == 0.5
    assert metricas.deterministic_rate == 0.0  # humano não é determinístico


def test_itens_fora_do_dataset_nao_contaminam_a_conta():
    """Um run pode cobrir mais itens do que o conjunto avalia — o recorte de
    contaminação produz exatamente isso. Os de fora são ignorados, não
    contados como erro."""
    ds = EvalDataset(id="d", cases=(_caso("i-1", "BUG"),))
    run = _run(propostas=[_proposta("i-1", "BUG"), _proposta("i-999", "FEATURE")])

    metricas = medir(run, ds, model=MODELO, abstem_com=DUVIDA)

    assert metricas.proposals_total == 1
    assert metricas.proposal_precision == 1.0
