"""A colheita: a seta que ligava o revisor à avaliação e não existia."""

from datetime import UTC, datetime, timedelta

import pytest

from orchestrator.evaluation.case import Provenance
from orchestrator.evaluation.harvest import NaoColhido, colher
from orchestrator.kernel.run import Run, RunState
from orchestrator.kernel.work import WorkItem

AGORA = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
SNAP = (WorkItem(id="i-1", kind="divergencia", payload={"v": 1}),)
RUN = Run(
    id="r-1",
    workflow_id="conciliacao",
    workflow_version="1",
    state=RunState.CONCLUIDO,
    started_at=AGORA - timedelta(hours=2),
    input_ref="",
)


def _colher(veredito, tipo=None, **kw):
    return colher(
        item_id="i-1",
        veredito=veredito,
        tipo_afirmado=tipo,
        snapshot=SNAP,
        run=RUN,
        quando=AGORA,
        **kw,
    )


# -- os três vereditos, e por que cada um vale ------------------------------


def test_CORRIGIR_vira_caso_com_o_tipo_que_o_humano_afirmou():
    caso = _colher("corrigir", tipo="RETENCAO_IMPOSTO", autor="ana")

    assert caso.expected.kind == "RETENCAO_IMPOSTO"
    assert caso.provenance is Provenance.HUMANO
    assert "corrigido" in caso.tags


def test_ACEITAR_vira_caso_de_REGRESSAO():
    """O que hoje acerta e não pode parar de acertar.

    Colher só `corrigir` daria um conjunto só de fracassos, e um benchmark que
    só tem caso difícil não detecta regressão no caso fácil — que é onde ela
    costuma aparecer primeiro, porque é onde ninguém olha.
    """
    caso = _colher("aceitar", tipo="DEVOLUCAO_FUNDOS")

    assert caso.expected.kind == "DEVOLUCAO_FUNDOS"
    assert "regressao" in caso.tags


def test_REJEITAR_vira_caso_SEM_kind():
    """O humano afirmou que a hipótese está errada, não qual é a certa.

    Inventar um tipo aqui criaria verdade que ninguém estabeleceu — e `medir`
    não pontua item sem `kind`, então o caso ensina a abster sem punir o agente
    por um rótulo fabricado.
    """
    caso = _colher("rejeitar")

    assert caso.expected.kind is None
    assert "abstencao" in caso.tags


# -- o relógio --------------------------------------------------------------


def test_created_at_e_a_hora_da_DECISAO_e_nao_a_da_colheita():
    """Usar o relógio de agora faria um caso decidido ontem parecer criado
    hoje — e ele passaria a ser elegível para avaliar o run de ontem, que é
    precisamente a memorização que a guarda impede."""
    ontem = AGORA - timedelta(days=1)

    caso = colher(
        item_id="i-1",
        veredito="aceitar",
        tipo_afirmado="X",
        snapshot=SNAP,
        run=RUN,
        quando=ontem,
    )

    assert caso.created_at == ontem


def test_quando_sem_fuso_e_recusado():
    with pytest.raises(ValueError, match="fuso"):
        colher(
            item_id="i-1",
            veredito="aceitar",
            tipo_afirmado="X",
            snapshot=SNAP,
            run=RUN,
            quando=datetime(2026, 9, 16, 12, 0),
        )


# -- a recusa que NÃO é silenciosa ------------------------------------------


def test_recusa_diz_o_MOTIVO_em_vez_de_devolver_None():
    """Uma fila de mil decisões produzindo zero casos em silêncio é a mesma
    classe de falha que `proposals_api_failed` elimina em `agent_eval`."""
    resultado = _colher("corrigir", tipo=None)

    assert isinstance(resultado, NaoColhido)
    assert "tipo" in resultado.motivo


def test_sem_snapshot_recusa_com_motivo():
    resultado = colher(
        item_id="i-1",
        veredito="aceitar",
        tipo_afirmado="X",
        snapshot=(),
        run=RUN,
        quando=AGORA,
    )

    assert isinstance(resultado, NaoColhido)
    assert "snapshot" in resultado.motivo


def test_veredito_desconhecido_LEVANTA_em_vez_de_cair_num_else():
    """Um veredito novo precisa de uma decisão sobre o que ele ensina."""
    with pytest.raises(ValueError, match="veredito desconhecido"):
        _colher("talvez")


# -- a ponte com `review/`, que é onde o vocabulário mora -------------------


def test_os_vereditos_batem_com_os_do_REVISOR():
    """O desvio do §14.3 (receber campos em vez da `Decision`) só é seguro
    enquanto os dois lados concordarem sobre as palavras. Este teste é o que
    transforma essa concordância de suposição em verificação."""
    from orchestrator.review.decision import Veredito

    from orchestrator.evaluation.harvest import _VEREDITOS

    assert set(_VEREDITOS) == {v.value for v in Veredito}
