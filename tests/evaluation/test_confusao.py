"""A matriz de confusão: onde o agente erra, não só quanto."""

from datetime import UTC, datetime

from orchestrator.evaluation.case import (
    EvalDataset,
    EvaluationCase,
    ExpectedOutcome,
    Provenance,
)
from orchestrator.evaluation.confusao import ABSTEVE, AUSENTE, confundir
from orchestrator.kernel.cost import Cost
from orchestrator.kernel.resolution import Confidence, Proposal
from orchestrator.kernel.run import Run, RunState
from orchestrator.kernel.work import WorkItem

AGORA = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
ABSTEM = frozenset({"NAO_SEI"})


def _caso(item, kind) -> EvaluationCase:
    return EvaluationCase(
        id=f"c-{item}",
        input_snapshot=(WorkItem(id=item, kind="issue", payload=None),),
        expected=ExpectedOutcome(kind=kind),
        provenance=Provenance.ESPECIALISTA,
        created_at=AGORA,
    )


def _p(item, tipo) -> Proposal:
    return Proposal(
        item_id=item,
        tipo=tipo,
        explicacao="",
        evidencia=["e"],
        confianca=Confidence.MEDIA,
        acao_sugerida="revisar",
        cost=Cost(input_tokens=10, output_tokens=2, calls=1),
    )


def _run(props) -> Run:
    return Run(
        id="r",
        workflow_id="w",
        workflow_version="1",
        state=RunState.CONCLUIDO,
        started_at=AGORA,
        input_ref="",
        proposals=tuple(props),
    )


def _cenario(pares):
    """`pares` é [(item, esperado, dito)]; `dito=None` = sem proposta."""
    ds = EvalDataset(id="d", cases=tuple(_caso(i, e) for i, e, _ in pares))
    run = _run([_p(i, d) for i, _, d in pares if d is not None])
    return confundir(run, ds, abstem_com=ABSTEM)


# -- o que a matriz responde e a taxa não ----------------------------------


def test_confusao_SISTEMATICA_aparece_como_padrao():
    """Quatro erros todos na mesma direção é uma linha de prompt."""
    c = _cenario(
        [
            ("i1", "DUVIDA", "FEATURE"),
            ("i2", "DUVIDA", "FEATURE"),
            ("i3", "DUVIDA", "FEATURE"),
            ("i4", "BUG", "BUG"),
        ]
    )

    assert c.confusoes_dominantes() == (("DUVIDA", "FEATURE", 3),)
    assert "3x DUVIDA respondido como FEATURE" in c.render()


def test_erros_ESPALHADOS_sao_reportados_como_espalhados():
    """Mesma taxa de erro do teste acima, diagnóstico oposto: sem padrão, o
    apontamento é limite do modelo e não regra faltando."""
    c = _cenario(
        [
            ("i1", "DUVIDA", "FEATURE"),
            ("i2", "BUG", "DUVIDA"),
            ("i3", "FEATURE", "BUG"),
            ("i4", "BUG", "BUG"),
        ]
    )

    assert c.confusoes_dominantes() == ()
    assert "erros estão espalhados" in c.render()


def test_um_erro_isolado_NAO_vira_padrao():
    """`minimo=2` de propósito. Reportar singleton como "confusão dominante"
    transformaria ruído em diagnóstico — o erro que este projeto já cometeu
    duas vezes lendo diferença de um caso como resultado."""
    c = _cenario([("i1", "DUVIDA", "FEATURE"), ("i2", "BUG", "BUG")])

    assert c.confusoes_dominantes() == ()


def test_a_matriz_NOMEIA_os_casos_errados():
    """Sem o id, saber que houve 4 erros não deixa ninguém ir ler as issues."""
    c = _cenario([("i-42", "BUG", "FEATURE"), ("i-7", "BUG", "BUG")])

    assert [e.item_id for e in c.erros] == ["i-42"]
    assert "i-42" in c.render()


# -- abstenção e ausência não são erro de classificação --------------------


def test_abstencao_tem_COLUNA_PROPRIA_e_nao_conta_como_confusao():
    """Abstenção é a recusa de classificar, não uma classificação errada.
    Somá-la aos tipos faria "não sei" competir com "BUG" numa tabela que
    pergunta "confundiu com o quê"."""
    c = _cenario([("i1", "BUG", "NAO_SEI"), ("i2", "BUG", "BUG")])

    assert c.matriz[("BUG", ABSTEVE)] == 1
    assert c.erros == ()
    assert c.confusoes_dominantes() == ()


def test_item_SEM_proposta_vira_coluna_propria_em_vez_de_sumir():
    """Ausência de medição não é zero — a mesma disciplina do resto da camada."""
    c = _cenario([("i1", "BUG", None), ("i2", "BUG", "BUG")])

    assert c.matriz[("BUG", AUSENTE)] == 1
    assert AUSENTE in c.ditos


def test_caso_sem_kind_esperado_NAO_entra():
    """O caso colhido de um `rejeitar`: ninguém estabeleceu a verdade dele."""
    ds = EvalDataset(
        id="d",
        cases=(
            _caso("i1", "BUG"),
            EvaluationCase(
                id="c-i2",
                input_snapshot=(WorkItem(id="i2", kind="issue", payload=None),),
                expected=ExpectedOutcome(kind=None),
                provenance=Provenance.HUMANO,
                created_at=AGORA,
            ),
        ),
    )

    c = confundir(_run([_p("i1", "BUG"), _p("i2", "FEATURE")]), ds, abstem_com=ABSTEM)

    assert c.total == 1
    assert c.erros == ()


# -- estabilidade -----------------------------------------------------------


def test_a_tabela_tem_FORMA_ESTAVEL_entre_leituras():
    """Um diff de relatório que muda sozinho ensina a ignorar diffs."""
    pares = [("i1", "FEATURE", "BUG"), ("i2", "BUG", "NAO_SEI"), ("i3", "DUVIDA", "DUVIDA")]

    assert _cenario(pares).render() == _cenario(pares).render()
    assert _cenario(pares).ditos == ("BUG", "DUVIDA", ABSTEVE)


def test_as_colunas_especiais_ficam_no_FIM():
    c = _cenario([("i1", "BUG", "NAO_SEI"), ("i2", "BUG", None), ("i3", "BUG", "BUG")])

    assert c.ditos[-2:] == (ABSTEVE, AUSENTE)


def test_matriz_vazia_diz_isso_em_vez_de_imprimir_tabela_em_branco():
    ds = EvalDataset(id="d", cases=())
    assert "nenhum caso pontuado" in confundir(_run([]), ds, abstem_com=ABSTEM).render()
