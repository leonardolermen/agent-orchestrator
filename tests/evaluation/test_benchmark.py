"""O benchmark: fixar o conjunto, variar um braço, medir — sem tocar no motor."""

from datetime import UTC, datetime, timedelta

import pytest

from orchestrator.evaluation.benchmark import BenchmarkArm, BenchmarkResult, rodar
from orchestrator.evaluation.case import (
    EvalDataset,
    EvaluationCase,
    ExpectedOutcome,
    Provenance,
)
from orchestrator.kernel.cost import Cost
from orchestrator.kernel.definition import Task, WorkflowDefinition
from orchestrator.kernel.resolution import Confidence, Proposal
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.run import Run, RunState
from orchestrator.kernel.work import WorkItem

AGORA = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
MODELO = "claude-haiku-4-5"


class _ResolverInerte:
    name = "inerte"
    cost_class = CostClass.AGENTE

    def describe(self) -> ResolverDescription:
        return ResolverDescription(self.name, self.cost_class, "")

    def resolve(self, work):
        return ResolverOutput()


def _definicao(nome: str) -> WorkflowDefinition:
    return WorkflowDefinition(
        id=nome, name=nome, stages=(Task("único", resolver=_ResolverInerte()),)
    )


def _caso(item, kind="BUG", quando=None) -> EvaluationCase:
    return EvaluationCase(
        id=f"c-{item}",
        input_snapshot=(WorkItem(id=item, kind="issue", payload=None),),
        expected=ExpectedOutcome(kind=kind),
        provenance=Provenance.SINTETICO,
        created_at=quando or AGORA - timedelta(days=1),
    )


def _run(iniciado=AGORA, propostas=(), custo=None) -> Run:
    return Run(
        id="r",
        workflow_id="w",
        workflow_version="1",
        state=RunState.CONCLUIDO,
        started_at=iniciado,
        input_ref="",
        proposals=tuple(propostas),
        cost_by_resolver={"a": custo or Cost(input_tokens=1000, output_tokens=100)},
    )


def _proposta(item, tipo) -> Proposal:
    return Proposal(
        item_id=item,
        tipo=tipo,
        explicacao="",
        evidencia=["e"],
        confianca=Confidence.MEDIA,
        acao_sugerida="revisar",
        cost=Cost(input_tokens=1000, output_tokens=100, calls=1),
    )


DS = EvalDataset(id="d", cases=(_caso("i-1"), _caso("i-2")))


def test_dois_bracos_sobre_o_MESMO_conjunto():
    def executor(arm, dataset):
        certas = 2 if arm.label == "bom" else 0
        propostas = [
            _proposta(f"i-{n + 1}", "BUG" if n < certas else "FEATURE") for n in range(2)
        ]
        return _run(propostas=propostas), None

    r = rodar(
        (
            BenchmarkArm(label="bom", workflow=_definicao("a")),
            BenchmarkArm(label="ruim", workflow=_definicao("b")),
        ),
        DS,
        executor,
        model=MODELO,
        abstem_com=frozenset({"DUVIDA"}),
        agora=AGORA,
    )

    assert r.por_label()["bom"].proposal_precision == 1.0
    assert r.por_label()["ruim"].proposal_precision == 0.0
    assert r.dataset_version == DS.version


def test_o_vencedor_e_o_de_menor_custo_por_ACERTO():
    """Não o mais barato. Aqui o braço caro gasta 50% a mais e acerta o DOBRO:
    o total dele é maior e o custo por acerto é menor, que é o que o produto
    quer. (Gastar 4x para acertar 2x seria o contrário — e o teste
    `test_braco_sem_acerto_nenhum_NAO_concorre` cobre o extremo disso.)"""
    def executor(arm, dataset):
        if arm.label == "caro-e-certeiro":
            custo = Cost(input_tokens=1500, output_tokens=150)
            props = [_proposta("i-1", "BUG"), _proposta("i-2", "BUG")]
        else:
            custo = Cost(input_tokens=1000, output_tokens=100)
            props = [_proposta("i-1", "BUG"), _proposta("i-2", "FEATURE")]
        return _run(propostas=props, custo=custo), None

    r = rodar(
        (
            BenchmarkArm(label="caro-e-certeiro", workflow=_definicao("a")),
            BenchmarkArm(label="barato-e-torto", workflow=_definicao("b")),
        ),
        DS,
        executor,
        model=MODELO,
        abstem_com=frozenset(),
        agora=AGORA,
    )

    melhor, _ = r.melhor_por_custo_efetivo()
    assert melhor.label == "caro-e-certeiro"


def test_braco_sem_acerto_nenhum_NAO_concorre():
    """Custo por acerto indefinido tratado como zero o faria vencer sempre —
    o braço que não acerta nada seria eleito o mais eficiente."""
    def executor(arm, dataset):
        certo = arm.label == "acerta"
        return _run(propostas=[_proposta("i-1", "BUG" if certo else "X")]), None

    r = rodar(
        (
            BenchmarkArm(label="acerta", workflow=_definicao("a")),
            BenchmarkArm(label="nunca-acerta", workflow=_definicao("b")),
        ),
        DS,
        executor,
        model=MODELO,
        abstem_com=frozenset(),
        agora=AGORA,
    )

    melhor, _ = r.melhor_por_custo_efetivo()
    assert melhor.label == "acerta"


def test_a_guarda_de_contaminacao_vale_DENTRO_do_benchmark():
    """Um caso criado depois do run não pode pontuá-lo, nem aqui."""
    ds = EvalDataset(
        id="d",
        cases=(
            _caso("i-1", quando=AGORA - timedelta(days=1)),
            _caso("i-2", quando=AGORA + timedelta(days=1)),
        ),
    )

    def executor(arm, dataset):
        return _run(propostas=[_proposta("i-1", "BUG"), _proposta("i-2", "X")]), None

    r = rodar(
        (BenchmarkArm(label="a", workflow=_definicao("a")),),
        ds,
        executor,
        model=MODELO,
        abstem_com=frozenset(),
        agora=AGORA,
    )

    (_, metricas) = r.arms[0]
    assert metricas.items_total == 1  # o i-2 foi excluído
    assert metricas.proposal_precision == 1.0


def test_conjunto_TODO_posterior_ao_run_LEVANTA_em_vez_de_medir_nada():
    ds = EvalDataset(id="d", cases=(_caso("i-1", quando=AGORA + timedelta(days=1)),))

    with pytest.raises(ValueError, match="memorização"):
        rodar(
            (BenchmarkArm(label="a", workflow=_definicao("a")),),
            ds,
            lambda arm, dataset: (_run(), None),
            model=MODELO,
            abstem_com=frozenset(),
            agora=AGORA,
        )


def test_rotulo_repetido_e_recusado():
    """A tabela de resultado é indexada por rótulo; dois iguais esconderiam um."""
    with pytest.raises(ValueError, match="rótulo repetido"):
        rodar(
            (
                BenchmarkArm(label="a", workflow=_definicao("a")),
                BenchmarkArm(label="a", workflow=_definicao("b")),
            ),
            DS,
            lambda arm, dataset: (_run(), None),
            model=MODELO,
            abstem_com=frozenset(),
            agora=AGORA,
        )


def test_benchmark_sem_braco_e_recusado():
    with pytest.raises(ValueError, match="sem braço"):
        rodar((), DS, lambda a, d: (_run(), None), model=MODELO,
              abstem_com=frozenset(), agora=AGORA)


def test_o_modelo_do_braco_vence_o_do_benchmark():
    """É o que permite comparar modelos; sem isso, `--model a --model b` mediria
    os dois com o preço de um só."""
    arm = BenchmarkArm(label="x", workflow=_definicao("a"), model="claude-opus-5")

    assert arm.modelo_efetivo(MODELO) == "claude-opus-5"
    assert BenchmarkArm(label="y", workflow=_definicao("b")).modelo_efetivo(
        MODELO
    ) == MODELO


def test_o_render_nao_inventa_custo_por_acerto_inexistente():
    r = BenchmarkResult(dataset_id="d", dataset_version="v", at=AGORA)

    assert "sem braço" in r.render()
