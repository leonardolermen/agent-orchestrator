"""Execução ponta a ponta do núcleo determinístico.

Gera um benchmark sintético, reconcilia e imprime as métricas. Nenhuma
chamada de LLM: este é o piso contra o qual o agente será medido depois.
"""

import argparse
from random import Random

from orchestrator.matching.engine import reconcile
from orchestrator.metrics import evaluate
from orchestrator.synth.dataset import Dataset, InjectionResult
from orchestrator.synth.generator import build_dataset, generate_clean_pairs
from orchestrator.synth.injectors import (
    DefasagemTemporal,
    DevolucaoFundos,
    PagamentoAgregado,
    RetencaoImposto,
)

_INJETORES_SIMPLES = [DefasagemTemporal(), RetencaoImposto(), DevolucaoFundos()]


def build_benchmark(seed: int, n: int, taxa_divergencia: float) -> Dataset:
    """Monta um dataset com a proporção pedida de divergências."""
    rng = Random(seed)
    pares = generate_clean_pairs(seed=seed, n=n)

    alvo = int(n * taxa_divergencia)
    injecoes: list[InjectionResult] = []
    indice = 0

    while indice < alvo and indice < len(pares):
        if rng.random() < 0.25 and indice + 3 <= len(pares):
            lote = pares[indice : indice + 3]
            injecoes.append(PagamentoAgregado().apply_many(rng, lote))
            indice += 3
        else:
            injetor = rng.choice(_INJETORES_SIMPLES)
            injecoes.append(injetor.apply(rng, pares[indice]))
            indice += 1

    return build_dataset(pares, injecoes)


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
