"""Avaliação do núcleo determinístico contra o gabarito.

Mede o sistema, não o agente — não há agente neste plano. A métrica que
importa aqui é a taxa de resolução determinística (spec 2.3, critério F1) e,
tão importante quanto, o falso positivo: casar errado é pior que não casar.
"""

from collections import Counter
from dataclasses import dataclass

from orchestrator.matching.engine import ReconcileResult
from orchestrator.money import format_brl
from orchestrator.synth.dataset import Dataset


@dataclass(frozen=True)
class Metrics:
    bank_total: int
    ledger_total: int
    bank_matched: int
    deterministic_rate: float
    divergences: int
    truth_divergences: int
    false_positives: int
    false_negatives: int
    matched_amount: int
    divergent_amount: int
    truth_by_type: dict[str, int]

    def render(self) -> str:
        linhas = [
            f"Lançamentos bancários:       {self.bank_total}",
            f"Lançamentos contábeis:       {self.ledger_total}",
            f"Casados deterministicamente: {self.bank_matched}",
            f"Taxa determinística:         {self.deterministic_rate:.1%}",
            f"Divergências apuradas:       {self.divergences}",
            f"Divergências no gabarito:    {self.truth_divergences}",
            f"Falsos positivos:            {self.false_positives}",
            f"Falsos negativos:            {self.false_negatives}",
            "",
            f"Valor conciliado:            {format_brl(self.matched_amount)}",
            f"Valor em divergência:        {format_brl(self.divergent_amount)}",
            "",
            "Gabarito por tipo:",
        ]
        for tipo, n in sorted(self.truth_by_type.items()):
            linhas.append(f"  {tipo:<24} {n}")
        return "\n".join(linhas)


def evaluate(dataset: Dataset, result: ReconcileResult) -> Metrics:
    bank_total = len(dataset.bank)
    casados_banco = {i for m in result.matches for i in m.bank_ids}
    casados_todos = {i for m in result.matches for i in m.bank_ids | m.ledger_ids}

    def foi_casado(gt) -> bool:
        return bool((gt.bank_ids | gt.ledger_ids) & casados_todos)

    # Falso positivo: o gabarito diz que só o agente resolveria, mas alguma
    # camada determinística casou assim mesmo. Casar errado é pior que não casar.
    falsos_positivos = sum(
        1 for gt in dataset.truth if not gt.deterministic_expected and foi_casado(gt)
    )

    # Falso negativo: o gabarito diz que uma camada deveria resolver, e nenhuma
    # resolveu. Isso é trabalho desnecessário empurrado para o agente.
    falsos_negativos = sum(
        1 for gt in dataset.truth if gt.deterministic_expected and not foi_casado(gt)
    )

    # Valor é o que o comprador entende. Contagem de lançamentos não diz se o
    # que sobrou foi R$ 300 ou R$ 300 mil.
    conciliado = sum(abs(e.amount) for e in dataset.bank if e.id in casados_banco)
    divergente = sum(abs(e.amount) for e in dataset.bank if e.id not in casados_banco)

    return Metrics(
        bank_total=bank_total,
        ledger_total=len(dataset.ledger),
        bank_matched=len(casados_banco),
        deterministic_rate=(len(casados_banco) / bank_total) if bank_total else 0.0,
        divergences=len(result.divergences),
        truth_divergences=len(dataset.truth),
        false_positives=falsos_positivos,
        false_negatives=falsos_negativos,
        matched_amount=conciliado,
        divergent_amount=divergente,
        truth_by_type=dict(Counter(str(gt.divergence_type) for gt in dataset.truth)),
    )
