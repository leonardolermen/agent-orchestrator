"""A CLI. `main` é o despachante; `conciliador.main` é a invocação legada.

O re-export mantém `orchestrator.cli:main` — o entry point declarado em
`pyproject.toml` desde o primeiro commit — apontando para o lugar certo sem que
`pyproject` precise mudar junto.
"""

from orchestrator.cli.main import main

__all__ = ["main"]
