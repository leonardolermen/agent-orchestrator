"""Avaliação ao vivo do investigador contra o gabarito sintético.

A terceira e última camada de teste: a única que gasta dinheiro e a única que
diz se o produto presta. Roda modelos diferentes contra o MESMO gabarito, que é
o que transforma escolha de modelo em medição.

O gabarito não precisou ser construído para isto — ele já existe desde a plano 1.
"""

import argparse
from collections.abc import Callable
from dataclasses import dataclass

from orchestrator.agent.investigator import Investigator
from orchestrator.agent.llm import LLMClient
from orchestrator.agent.tools import ToolContext
from orchestrator.cli import build_benchmark
from orchestrator.matching.engine import reconcile
from orchestrator.metrics import evaluate

MODELOS_PADRAO = ("claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5")


@dataclass(frozen=True)
class EvalResult:
    model: str
    divergences: int
    proposals_total: int
    proposals_correct: int
    proposals_abstained: int
    total_microcents: int

    @property
    def precision(self) -> float:
        """Das propostas que arriscaram um tipo, quantas acertaram."""
        arriscadas = self.proposals_total - self.proposals_abstained
        return self.proposals_correct / arriscadas if arriscadas else 0.0

    @property
    def abstention_rate(self) -> float:
        return self.proposals_abstained / self.proposals_total if self.proposals_total else 0.0

    @property
    def microcents_per_divergence(self) -> int:
        return self.total_microcents // self.divergences if self.divergences else 0

    def render(self) -> str:
        return "\n".join(
            [
                f"Modelo:                        {self.model}",
                f"Divergências investigadas:     {self.divergences}",
                f"Precisão (das que arriscaram): {self.precision:.1%}",
                f"Taxa de abstenção:             {self.abstention_rate:.1%}",
                f"Custo total:                   "
                f"US$ {self.total_microcents / 100_000_000:.4f}",
                f"Custo por divergência:         "
                f"US$ {self.microcents_per_divergence / 100_000_000:.6f}",
            ]
        )


def _fabrica_real(model: str) -> Callable[[], LLMClient]:
    def fabrica() -> LLMClient:
        from orchestrator.agent.anthropic_client import AnthropicClient

        return AnthropicClient(model=model)

    return fabrica


def avaliar(
    model: str,
    seed: int,
    n: int,
    taxa_divergencia: float,
    client_factory: Callable[[], LLMClient] | None = None,
) -> EvalResult:
    dataset = build_benchmark(seed=seed, n=n, taxa_divergencia=taxa_divergencia)
    cliente = (client_factory or _fabrica_real(model))()
    investigador = Investigator(
        client=cliente, context=ToolContext(bank=dataset.bank, ledger=dataset.ledger)
    )

    resultado = reconcile(dataset.bank, dataset.ledger, investigator=investigador)
    metricas = evaluate(dataset, resultado, model=cliente.model)

    return EvalResult(
        model=model,
        divergences=len(resultado.divergences),
        proposals_total=metricas.proposals_total,
        proposals_correct=metricas.proposals_correct,
        proposals_abstained=metricas.proposals_abstained,
        total_microcents=metricas.agent_cost_microcents,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Avalia o investigador contra o gabarito sintético. GASTA DINHEIRO."
    )
    parser.add_argument("--model", action="append", default=None,
                        help="pode repetir para comparar modelos")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--taxa-divergencia", type=float, default=0.15)
    args = parser.parse_args(argv)

    modelos = args.model or list(MODELOS_PADRAO)
    print(f"Avaliação ao vivo — GASTA DINHEIRO. Modelos: {', '.join(modelos)}")
    print()
    for modelo in modelos:
        print(avaliar(modelo, args.seed, args.n, args.taxa_divergencia).render())
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
