"""Congela a medição determinística de 12 sementes.

Rodar UMA vez, antes do refactor da cascata. Depois disso o arquivo é
autoridade: quem o regenera precisa explicar por quê.

Semente 1..12, n=300, taxa 0.15 — a mesma configuração da medição citada no
comentário de `_FRACAO_AGREGADOS` em `orchestrator/cli.py`.
"""

import json
from pathlib import Path

from orchestrator.cli import build_benchmark
from orchestrator.matching.engine import reconcile
from orchestrator.metrics import evaluate

CAMINHO = Path(__file__).parent / "cascata_12_sementes.json"
SEMENTES = tuple(range(1, 13))
N = 300
TAXA = 0.15


def medir() -> dict:
    """A medição bruta, sem arredondamento de conveniência."""
    saida: dict[str, dict] = {}
    for semente in SEMENTES:
        dataset = build_benchmark(seed=semente, n=N, taxa_divergencia=TAXA)
        resultado = reconcile(dataset.bank, dataset.ledger)
        m = evaluate(dataset, resultado)
        saida[str(semente)] = {
            # 12 casas: o suficiente para pegar qualquer mudança real de
            # comportamento e curto o bastante para não pinar ruído de ponto
            # flutuante da última casa.
            "deterministic_rate": round(m.deterministic_rate, 12),
            "bank_matched": m.bank_matched,
            "divergences": m.divergences,
            "false_positives": m.false_positives,
            "false_negatives": m.false_negatives,
            "matched_amount": m.matched_amount,
            "divergent_amount": m.divergent_amount,
            "matches_by_layer": dict(sorted(m.matches_by_layer.items())),
        }
    return saida


def main() -> int:
    CAMINHO.write_text(
        json.dumps(medir(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"golden escrito em {CAMINHO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
