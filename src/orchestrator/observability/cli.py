"""`orchestrator-trace`: a árvore de uma execução, no terminal.

Entrada própria, e não subcomando de `orchestrator`, pelo MESMO motivo que
`orchestrator-eval` e `orchestrator-grill`: o `main()` daquele é argparse plano,
e introduzir subcomandos quebraria a invocação de hoje sem ganho. A unificação
em `orchestrator trace <run-id>` é o M5 (DX), onde ela vem com despachante e
alias legado.

NÃO gasta dinheiro: só lê disco. Não existe caminho de código daqui até o
modelo, pela mesma razão que a API não tem — e pelo mesmo teste.
"""

import argparse
import sys
from pathlib import Path

from orchestrator.observability.render import render
from orchestrator.storage.jsonl.run_store import JsonlRunStore
from orchestrator.storage.jsonl.trace_store import JsonlTraceStore

_RAIZ = Path("data")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mostra a árvore de uma execução: custo e latência por nível."
    )
    parser.add_argument("run_id", nargs="?", help="id do run; omita para listar")
    parser.add_argument("--raiz", type=Path, default=_RAIZ)
    parser.add_argument("--model", default="claude-opus-5")
    parser.add_argument(
        "--max-itens",
        type=int,
        default=5,
        help="quantos itens por resolver mostrar; o corte é declarado na saída",
    )
    args = parser.parse_args(argv)

    runs = JsonlRunStore(args.raiz / "runs.jsonl")
    if not args.run_id:
        achados = runs.list(limit=20)
        if not achados:
            print("nenhum run registrado.", file=sys.stderr)
            return 1
        print(f"{'run':<24} {'workflow':<16} {'estado':<20} {'itens':>6}")
        for s in achados:
            print(
                f"{s.id:<24} {s.workflow_id:<16} {s.state.value:<20} "
                f"{s.resolved + s.unresolved:>6}"
            )
        return 0

    trace = JsonlTraceStore(args.raiz).get(args.run_id)
    if trace is None:
        print(f"sem trace para o run {args.run_id!r}.", file=sys.stderr)
        return 1
    print(render(trace, model=args.model, max_itens=args.max_itens))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
