"""O armazém de casos: append-only, e a razão é mais forte que a da fila."""

from datetime import UTC, datetime, timedelta

import pytest

from orchestrator.evaluation.case import (
    EvaluationCase,
    ExpectedOutcome,
    Provenance,
)
from orchestrator.evaluation.store import CaseStore, caminho_do_conjunto
from orchestrator.kernel.work import WorkItem

AGORA = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


def caso(cid="c-1", item="i-1", kind="BUG", quando=None, proc=Provenance.HUMANO):
    return EvaluationCase(
        id=cid,
        input_snapshot=(WorkItem(id=item, kind="issue", payload={"titulo": "ç ã"}),),
        expected=ExpectedOutcome(kind=kind, note="revisado"),
        provenance=proc,
        created_at=quando or AGORA,
        source_run_id="r-1",
        tags=frozenset({"corrigido"}),
    )


def test_o_que_gravou_volta_igual(tmp_path):
    loja = CaseStore(caminho_do_conjunto("d", tmp_path))
    loja.acrescentar(caso())

    relido = CaseStore(caminho_do_conjunto("d", tmp_path))

    assert relido.dataset().cases == loja.dataset().cases


def test_acentos_sobrevivem_a_ida_e_volta(tmp_path):
    """`ensure_ascii=False`, como na fila e pelo mesmo motivo — e aqui com um
    a mais: o payload é a entrada que o agente vai reler."""
    caminho = caminho_do_conjunto("d", tmp_path)
    CaseStore(caminho).acrescentar(caso())

    assert "ç ã" in caminho.read_text(encoding="utf-8")


def test_id_repetido_e_RECUSADO(tmp_path):
    """Substituir um caso mudaria retroativamente o significado de todo
    benchmark que já o mediu."""
    loja = CaseStore(caminho_do_conjunto("d", tmp_path))
    loja.acrescentar(caso("c-1"))

    with pytest.raises(ValueError, match="já existe"):
        loja.acrescentar(caso("c-1", kind="OUTRO"))


def test_gravar_nao_reescreve_o_arquivo(tmp_path):
    """Append-only de verdade: a primeira linha continua byte a byte igual."""
    caminho = caminho_do_conjunto("d", tmp_path)
    loja = CaseStore(caminho)
    loja.acrescentar(caso("c-1"))
    primeira = caminho.read_text(encoding="utf-8").splitlines()[0]

    loja.acrescentar(caso("c-2", item="i-2"))

    assert caminho.read_text(encoding="utf-8").splitlines()[0] == primeira


def test_created_at_sem_fuso_NO_DISCO_e_recusado_na_leitura(tmp_path):
    """Assumir UTC seria silencioso, e a guarda de contaminação depende de
    saber o instante de verdade."""
    caminho = caminho_do_conjunto("d", tmp_path)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        '{"id":"c","input_snapshot":[{"id":"i","kind":"k","payload":null}],'
        '"expected":{"kind":null,"should_resolve_deterministically":false,'
        '"resolves_with":[],"note":""},"provenance":"humano",'
        '"created_at":"2026-09-16T12:00:00","source_run_id":null,"tags":[]}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="sem fuso"):
        CaseStore(caminho)


def test_a_listagem_e_ESTAVEL_entre_leituras(tmp_path):
    """Um diff de relatório que muda sozinho ensina a ignorar diffs."""
    loja = CaseStore(caminho_do_conjunto("d", tmp_path))
    loja.acrescentar(caso("c-2", item="i-2", quando=AGORA))
    loja.acrescentar(caso("c-1", item="i-1", quando=AGORA - timedelta(hours=1)))

    ids = [c.id for c in CaseStore(caminho_do_conjunto("d", tmp_path)).dataset().cases]

    assert ids == ["c-1", "c-2"]


def test_o_resumo_avisa_quantos_casos_NAO_pontuam_tipo(tmp_path):
    """Quem lê "200 casos" precisa saber que 40 deles vieram de `rejeitar` e
    não entram no denominador da precisão."""
    loja = CaseStore(caminho_do_conjunto("d", tmp_path))
    loja.acrescentar(caso("c-1", item="i-1"))
    loja.acrescentar(caso("c-2", item="i-2", kind=None))

    resumo = loja.resumo()

    assert "sem tipo esperado: 1" in resumo
    assert "não entram na precisão" in resumo


def test_o_resumo_separa_por_PROCEDENCIA(tmp_path):
    """Sintético tem gabarito perfeito e domínio estreito; humano tem a
    ambiguidade real. Misturar sem saber qual é qual dá um número que não
    significa nada."""
    loja = CaseStore(caminho_do_conjunto("d", tmp_path))
    loja.acrescentar(caso("c-1", item="i-1", proc=Provenance.HUMANO))
    loja.acrescentar(caso("c-2", item="i-2", proc=Provenance.SINTETICO))

    assert "humano" in loja.resumo() and "sintetico" in loja.resumo()
    assert len(loja.por_procedencia(Provenance.HUMANO)) == 1


def test_conjunto_inexistente_abre_vazio_em_vez_de_estourar(tmp_path):
    loja = CaseStore(caminho_do_conjunto("nunca-existiu", tmp_path))

    assert len(loja) == 0
    assert "vazio" in loja.resumo()
