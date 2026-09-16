"""`orchestrator`: o despachante de subcomandos, com a invocação antiga intacta.

Até o M5 havia três entradas separadas (`orchestrator`, `orchestrator-eval`,
`orchestrator-grill`), e `grill/cli.py` documentava por quê: *"o `main()` de lá é
argparse plano e introduzir subcomandos quebraria a invocação de hoje sem
ganho"*. Com três comandos isso estava certo. Com nove, deixa de estar.

**A invocação antiga continua valendo, e não por gentileza.** O job
`conciliador` do CI roda `orchestrator --seed 1 --n 500` e faz `grep` da linha
`Taxa determinística (lado bancário): 85.3%`. Quebrar isso seria apagar o único
check que transforma uma regressão de qualidade em CI vermelho.

A regra do despachante é uma linha: **se o primeiro argumento começa com `-`, é
a invocação legada.** Não há lista de nomes antigos para manter em sincronia, e
um subcomando novo nunca colide com uma flag antiga.
"""

import argparse
import sys

_LEGADO = """Invocação antiga (mantida): `orchestrator --seed 1 --n 500` roda o
benchmark do conciliador. É o que o job `conciliador` do CI exercita."""


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="orchestrator",
        description="Runtime para trabalho inteligente.",
        epilog=_LEGADO,
    )
    sub = p.add_subparsers(dest="comando", metavar="<comando>")

    b = sub.add_parser("bench", help="roda o benchmark sintético do conciliador")
    b.add_argument("--seed", type=int, default=1)
    b.add_argument("--n", type=int, default=500)
    b.add_argument("--taxa-divergencia", type=float, default=0.15)

    r = sub.add_parser("runs", help="histórico de execuções")
    r.add_argument("--limit", type=int, default=20)

    t = sub.add_parser("trace", help="a árvore de uma execução")
    t.add_argument("run_id", nargs="?")
    t.add_argument("--max-itens", type=int, default=5)

    w = sub.add_parser("workflows", help="os workflows disponíveis")
    w.add_argument("workflow_id", nargs="?", help="omita para listar")

    i = sub.add_parser("init", help="cria um projeto novo")
    i.add_argument("nome")

    sub.add_parser("version", help="a versão instalada")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # A REGRA: primeiro argumento começando com `-` é invocação legada. Sem
    # lista de nomes para manter em sincronia, e sem colisão possível entre
    # subcomando novo e flag antiga.
    #
    # `--help` é a exceção: ele passa a mostrar os subcomandos, o que é
    # melhoria e não quebra — quem roda `--help` está procurando o que existe.
    if argv and argv[0].startswith("-") and argv[0] not in ("-h", "--help"):
        from orchestrator.cli.conciliador import main as legado

        return legado(argv)
    # Sem argumento nenhum também é legado: `orchestrator` sozinho sempre rodou
    # o benchmark com os defaults, e há quem tenha isso num script.
    if not argv:
        from orchestrator.cli.conciliador import main as legado

        return legado([])

    args = _parser().parse_args(argv)
    from orchestrator.cli import comandos

    despacho = {
        "bench": comandos.bench,
        "runs": comandos.runs,
        "trace": comandos.trace,
        "workflows": comandos.workflows,
        "init": comandos.init,
        "version": comandos.version,
    }
    return despacho[args.comando](args)


if __name__ == "__main__":
    raise SystemExit(main())
