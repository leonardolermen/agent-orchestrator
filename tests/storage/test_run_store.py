"""O store de runs. Substitui o `lru_cache` que fingia ser cache."""

from datetime import UTC, datetime

import pytest

from orchestrator.kernel.cost import Cost
from orchestrator.kernel.run import Run, RunState
from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.storage.jsonl.run_store import JsonlRunStore


def _run(rid: str, *, state=RunState.CONCLUIDO, wf="w", custo=None) -> Run:
    agora = datetime.now(UTC)
    return Run(
        id=rid,
        workflow_id=wf,
        workflow_version="v1",
        state=state,
        started_at=agora,
        finished_at=agora,
        input_ref="synth:s1",
        unresolved=WorkSet(items=(WorkItem(id="x", kind="k", payload=1),)),
        cost_by_resolver=custo or {"L1": Cost(input_tokens=10, calls=1)},
        resolved_by_resolver={"L1": 3},
    )


def test_salva_e_le_de_volta(tmp_path):
    store = JsonlRunStore(tmp_path / "runs.jsonl")
    store.save(_run("1789000000000-aaaa"))

    lido = store.get("1789000000000-aaaa")

    assert lido is not None
    assert lido.workflow_id == "w"
    assert lido.state is RunState.CONCLUIDO
    assert lido.unresolved == 1


def test_os_cinco_campos_de_custo_sobrevivem_a_ida_e_volta(tmp_path):
    """Perder um faz o store reportar custo menor que o real.

    É o defeito que P2.15 já corrigiu uma vez em `Cost`, e que só reaparece por
    descuido de serialização campo a campo — que é exatamente como este store
    serializa, de propósito (mesmo idioma de `review/serial.py`).
    """
    store = JsonlRunStore(tmp_path / "runs.jsonl")
    cheio = Cost(
        input_tokens=1,
        output_tokens=2,
        cached_tokens=3,
        cache_creation_tokens=4,
        calls=5,
    )
    store.save(_run("1789000000000-aaaa", custo={"agente": cheio}))

    assert store.get("1789000000000-aaaa").cost_by_resolver["agente"] == cheio


def test_lista_mais_recentes_primeiro_sem_indice(tmp_path):
    store = JsonlRunStore(tmp_path / "runs.jsonl")
    for rid in ("1789000000001-a", "1789000000003-c", "1789000000002-b"):
        store.save(_run(rid))

    assert [s.id for s in store.list()] == [
        "1789000000003-c",
        "1789000000002-b",
        "1789000000001-a",
    ]


def test_filtra_por_workflow_e_por_estado(tmp_path):
    store = JsonlRunStore(tmp_path / "runs.jsonl")
    store.save(_run("1789000000001-a", wf="conciliacao"))
    store.save(_run("1789000000002-b", wf="swe", state=RunState.AGUARDANDO_HUMANO))

    assert [s.id for s in store.list(workflow_id="swe")] == ["1789000000002-b"]
    assert [s.id for s in store.list(state=RunState.CONCLUIDO)] == ["1789000000001-a"]


def test_salvar_de_novo_o_mesmo_run_e_a_ultima_versao_que_vale(tmp_path):
    """ÚLTIMA vence — a mesma semântica que a `Fila` aplica a decisão.

    Um run é salvo de novo quando é retomado (M7). O log guarda as duas
    linhas — é ele a auditoria —, mas o ESTADO é o mais recente.
    """
    store = JsonlRunStore(tmp_path / "runs.jsonl")
    store.save(_run("1789000000001-a", state=RunState.AGUARDANDO_HUMANO))
    store.save(_run("1789000000001-a", state=RunState.CONCLUIDO))

    assert store.get("1789000000001-a").state is RunState.CONCLUIDO
    assert len(store.list()) == 1


def test_registro_corrompido_diz_qual_linha(tmp_path):
    """Quem lê isso é alguém investigando um run que sumiu, não um dev com o
    traceback do parser na cabeça. Mesma disciplina da `Fila`."""
    caminho = tmp_path / "runs.jsonl"
    caminho.write_text('{"id": "a"}\nnão é json\n', encoding="utf-8")

    with pytest.raises(ValueError, match="linha 1"):
        JsonlRunStore(caminho).list()


def test_arquivo_inexistente_devolve_vazio_em_vez_de_levantar(tmp_path):
    assert JsonlRunStore(tmp_path / "nunca-escrito.jsonl").list() == []
