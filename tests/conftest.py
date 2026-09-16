"""Isolamento global de fila para toda a suíte.

Dois módulos guardam uma raiz de fila em atributo de módulo (`_RAIZ_FILA`) que
por padrão cai em `Path("data")`, relativo ao CWD: `orchestrator.api.app` e
`orchestrator.eval.agent_eval`. Sem isolar essa raiz, qualquer teste que passe
por eles (direto ou via `TestClient`) lê e escreve em `data/fila/`, que é
exatamente onde `orchestrator-eval --fila` e o `/fila.html` de uma sessão
normal do desenvolvedor deixam `*.jsonl` — e tudo sob `data/` é ignorado pelo
`.gitignore` (allowlist, desde esta fatia; antes era a regra `*.jsonl`, que
cobria a fila por acidente do formato), então o CI nunca vê o problema e só a
máquina local falha, sem nada em `git status` para apontar a causa.

Esta fixture é autouse e cobre toda a suíte, não só `tests/api/`: qualquer
teste futuro que chame `avaliar(..., gravar_fila=True)` ou bata numa rota da
API herda o isolamento sem precisar lembrar de pedir.

Desde o PR #7 ela isola também o `RunStore`, que vive sob a MESMA raiz
(`api.app._run_store()`). Sem isso a suíte passaria a escrever
`data/runs.jsonl` na máquina do desenvolvedor — o mesmo defeito que esta
fixture existe para impedir, com um arquivo novo.

O `cache_clear()` do `_executar` sumiu junto com a memoização: não há
mais cache para invalidar.
"""

import pytest


@pytest.fixture(autouse=True)
def _raiz_da_fila_isolada(tmp_path, monkeypatch):
    try:
        import orchestrator.api.app as api_app
    except ImportError:
        # fastapi é extra opcional (`pyproject.toml`, grupo `api`); sem ele,
        # os próprios testes de API já se pulam via `pytest.importorskip`.
        api_app = None
    if api_app is not None:
        monkeypatch.setattr(api_app, "_RAIZ_FILA", tmp_path)

    import orchestrator.eval.agent_eval as agent_eval

    monkeypatch.setattr(agent_eval, "_RAIZ_FILA", tmp_path)

    yield
