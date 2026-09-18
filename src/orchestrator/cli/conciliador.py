"""Execução ponta a ponta do núcleo determinístico.

Gera um benchmark sintético, reconcilia e imprime as métricas. Nenhuma
chamada de LLM: este é o piso contra o qual o agente será medido depois.
"""

import argparse

from orchestrator.domains.reconciliation import reconcile
from orchestrator.domains.reconciliation.synth.benchmark import build_benchmark
from orchestrator.metrics import evaluate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Conciliação determinística sintética")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--n", type=int, default=500)
    parser.add_argument("--taxa-divergencia", type=float, default=0.15)
    args = parser.parse_args(argv)

    dataset = build_benchmark(args.seed, args.n, args.taxa_divergencia)
    resultado = reconcile(dataset.bank, dataset.ledger)
    print(evaluate(dataset, resultado).render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
