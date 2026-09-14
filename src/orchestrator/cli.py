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

# Fração das injeções que vira PAGAMENTO_AGREGADO — o único tipo injetado que
# L1-L3 conseguem resolver sozinhas. A taxa determinística reportada é uma
# função direta deste número, não só do dataset:
#
#   fração agregados | taxa média | mínimo  | máximo
#   0.00              | 78.1%      | 75.4%   | 80.2%
#   0.25 (valor atual)| 87.2%      | 83.0%   | 92.3%
#   0.50              | 93.2%      | 88.5%   | 96.7%
#   0.90              | 99.5%      | 98.9%   | 100.0%
# (medido em 12 sementes, n=300)
#
# Variação de 21 pontos por causa de um único literal, sem estar documentado
# em lugar nenhum antes desta nota. Qualquer taxa que este benchmark reportar
# é condicional a esta composição — não é uma propriedade do sistema medida
# no vácuo. O piso de regressão em test_cli.py (78%) coincide com a média do
# cenário 0.00: ele não pegaria a mistura de agregados cair a zero.
_FRACAO_AGREGADOS = 0.25


def build_benchmark(seed: int, n: int, taxa_divergencia: float) -> Dataset:
    """Monta um dataset com a proporção pedida de divergências."""
    # Fora de [0, 1] o alvo de injeções vira negativo ou maior que o dataset;
    # com alvo negativo o laço abaixo nunca roda e a CLI imprime "Taxa
    # determinística: 100.0%" com exit code 0 — degradação silenciosa no único
    # lugar onde um humano lê o número. Todo outro módulo deste projeto falha
    # alto em config inválida; a CLI não é exceção.
    if not 0.0 <= taxa_divergencia <= 1.0:
        raise ValueError(
            f"taxa_divergencia precisa estar entre 0.0 e 1.0: {taxa_divergencia}"
        )

    rng = Random(seed)
    pares = generate_clean_pairs(seed=seed, n=n)

    alvo = int(n * taxa_divergencia)
    injecoes: list[InjectionResult] = []
    indice = 0

    while indice < alvo and indice < len(pares):
        if rng.random() < _FRACAO_AGREGADOS and indice + 3 <= len(pares):
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
