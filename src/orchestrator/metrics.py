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
    # Lado bancário apenas: numerador e denominador são ambos sobre
    # dataset.bank. O lado contábil nunca entra no denominador, então um
    # órfão contábil puro não move esta taxa.
    deterministic_rate: float
    divergences: int
    truth_divergences: int
    false_positives: int
    false_negatives: int
    matched_amount: int
    # Idem: soma apenas lançamentos bancários. Um órfão contábil contribui
    # R$ 0,00 aqui, mesmo que represente dinheiro real em divergência.
    divergent_amount: int
    truth_deterministic: int
    truth_for_agent: int
    truth_by_type: dict[str, int]

    def render(self) -> str:
        # As duas contagens abaixo medem unidades diferentes: uma conta
        # LANÇAMENTOS sem contrapartida, a outra conta CASOS injetados. Uma
        # única devolução de fundos vira quatro lançamentos órfãos e um caso.
        # Os rótulos dizem isso, porque lado a lado sem dizer o leitor compara
        # os dois e conclui um erro que não existe.
        linhas = [
            f"Lançamentos bancários:         {self.bank_total}",
            f"Lançamentos contábeis:         {self.ledger_total}",
            f"Casados deterministicamente:   {self.bank_matched}",
            f"Taxa determinística (lado bancário): {self.deterministic_rate:.1%}",
            "",
            f"Lançamentos sem contrapartida: {self.divergences}",
            f"Casos injetados no gabarito:   {self.truth_divergences}",
            f"  que as camadas devem resolver: {self.truth_deterministic}",
            f"  reservados ao agente:          {self.truth_for_agent}",
            f"Falsos positivos:              {self.false_positives}",
            f"Falsos negativos:              {self.false_negatives}",
            "",
            f"Valor conciliado:              {format_brl(self.matched_amount)}",
            f"Valor em divergência (lado bancário): {format_brl(self.divergent_amount)}",
            "",
            "Gabarito por tipo:",
        ]
        for tipo, n in sorted(self.truth_by_type.items()):
            linhas.append(f"  {tipo:<24} {n}")
        return "\n".join(linhas)


def evaluate(dataset: Dataset, result: ReconcileResult) -> Metrics:
    bank_total = len(dataset.bank)
    ids_banco = {e.id for e in dataset.bank}
    ids_contabil = {e.id for e in dataset.ledger}

    # `matchers` é um ponto de extensão anunciado (reconcile aceita qualquer
    # lista de Matcher). Um matcher com bug — ou hostil — pode devolver ids
    # que não existem no dataset; sem intersectar, esses ids fantasma inflam
    # o numerador sem limite e a taxa passa de 1.0. A interseção com os ids
    # reais do dataset é a garantia de domínio que o tipo por si só não dá.
    casados_banco = {i for m in result.matches for i in m.bank_ids} & ids_banco
    casados_todos = ({i for m in result.matches for i in m.bank_ids | m.ledger_ids}
                      & (ids_banco | ids_contabil))

    def ids(gt) -> set[str]:
        return set(gt.bank_ids | gt.ledger_ids)

    # A assimetria entre as duas contagens abaixo é deliberada.
    #
    # Falso positivo usa SOBREPOSIÇÃO: o gabarito diz que só o agente
    # resolveria, então qualquer toque de uma camada determinística já é erro.
    # Resolver parcialmente um caso que não deveria ser resolvido é resolver
    # errado do mesmo jeito.
    falsos_positivos = sum(
        1 for gt in dataset.truth
        if not gt.deterministic_expected and ids(gt) & casados_todos
    )

    # Falso negativo usa CONTENÇÃO TOTAL: o gabarito diz que as camadas devem
    # resolver o caso INTEIRO. Um pagamento agregado com dois dos três
    # contábeis casados não foi resolvido — contar "qualquer toque" como
    # resolvido esconderia exatamente a falha parcial que esta métrica existe
    # para expor.
    falsos_negativos = sum(
        1 for gt in dataset.truth
        if gt.deterministic_expected and not ids(gt) <= casados_todos
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
        truth_deterministic=sum(1 for gt in dataset.truth if gt.deterministic_expected),
        truth_for_agent=sum(1 for gt in dataset.truth if not gt.deterministic_expected),
        truth_by_type=dict(Counter(str(gt.divergence_type) for gt in dataset.truth)),
    )
