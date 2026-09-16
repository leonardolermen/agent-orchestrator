"""Persistência de trace e a CLI que o lê."""

from datetime import UTC, datetime

import pytest

from orchestrator.kernel.cost import Cost
from orchestrator.kernel.trace import Span, SpanKind, Trace
from orchestrator.observability import cli
from orchestrator.storage.jsonl.trace_store import JsonlTraceStore


def _trace(run_id="r1") -> Trace:
    return Trace(
        run_id=run_id,
        spans=(
            Span(
                id="run-0",
                parent_id=None,
                kind=SpanKind.RUN,
                name="conciliacao@abc",
                started_at=datetime.now(UTC),
                duration_ms=1200,
                attributes={"estado": "concluido"},
            ),
            Span(
                id="llm-1",
                parent_id="run-0",
                kind=SpanKind.LLM,
                name="turno 1",
                cost=Cost(
                    input_tokens=1,
                    output_tokens=2,
                    cached_tokens=3,
                    cache_creation_tokens=4,
                    calls=5,
                ),
            ),
        ),
    )


def test_ida_e_volta_preserva_os_CINCO_campos_de_custo(tmp_path):
    """Perder um faria o trace reportar custo menor que o real — o defeito que
    P2.15 já corrigiu uma vez em `Cost`, e que só reaparece por descuido de
    serialização campo a campo (que é como este store serializa, de propósito)."""
    store = JsonlTraceStore(tmp_path)
    store.save(_trace())

    lido = store.get("r1")

    assert lido is not None
    llm = lido.por_kind(SpanKind.LLM)[0]
    assert llm.cost == Cost(
        input_tokens=1,
        output_tokens=2,
        cached_tokens=3,
        cache_creation_tokens=4,
        calls=5,
    )


def test_preserva_a_estrutura_da_arvore(tmp_path):
    store = JsonlTraceStore(tmp_path)
    store.save(_trace())

    lido = store.get("r1")

    assert lido.raiz().name == "conciliacao@abc"
    assert lido.raiz().duration_ms == 1200
    assert [s.id for s in lido.filhos("run-0")] == ["llm-1"]


def test_um_arquivo_POR_RUN(tmp_path):
    """Um arquivo único faria `orchestrator-trace <id>` varrer o histórico
    inteiro para achar um. `RunStore` pode ser um arquivo só porque guarda uma
    linha por run; aqui a cardinalidade é outra."""
    store = JsonlTraceStore(tmp_path)
    store.save(_trace("r1"))
    store.save(_trace("r2"))

    assert (tmp_path / "traces" / "r1.jsonl").exists()
    assert (tmp_path / "traces" / "r2.jsonl").exists()
    assert store.get("r1").run_id == "r1"


def test_run_sem_trace_devolve_None_em_vez_de_levantar(tmp_path):
    assert JsonlTraceStore(tmp_path).get("nunca-existiu") is None


def test_span_corrompido_diz_qual_linha(tmp_path):
    caminho = tmp_path / "traces" / "r1.jsonl"
    caminho.parent.mkdir(parents=True)
    caminho.write_text('{"id":"a"}\nnão é json\n', encoding="utf-8")

    with pytest.raises(ValueError, match="linha 1"):
        JsonlTraceStore(tmp_path).get("r1")


def test_a_cli_renderiza_a_arvore(tmp_path, capsys):
    JsonlTraceStore(tmp_path).save(_trace())

    assert cli.main(["r1", "--raiz", str(tmp_path)]) == 0

    saida = capsys.readouterr().out
    assert "conciliacao@abc" in saida
    assert "custo total" in saida


def test_a_cli_reclama_de_run_sem_trace(tmp_path, capsys):
    assert cli.main(["nao-existe", "--raiz", str(tmp_path)]) == 1
    assert "sem trace" in capsys.readouterr().err


def test_a_cli_nao_tem_caminho_ate_o_modelo():
    """A mesma regra da API, e pelo mesmo teste: não é flag, é ausência de
    caminho de código. Um `orchestrator-trace` que gastasse dinheiro seria a
    pior surpresa possível numa ferramenta de leitura."""
    import ast
    import pathlib

    fonte = pathlib.Path(cli.__file__).read_text(encoding="utf-8")
    importados = {
        n.module
        for n in ast.walk(ast.parse(fonte))
        if isinstance(n, ast.ImportFrom) and n.module
    }

    assert not any("anthropic" in m or "agent" in m for m in importados)
