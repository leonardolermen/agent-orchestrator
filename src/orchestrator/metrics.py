"""Avaliação do núcleo determinístico e das propostas do agente contra o gabarito.

A métrica central aqui é a taxa de resolução determinística (spec 2.3,
critério F1) e, tão importante quanto, o falso positivo: casar errado é pior
que não casar. Também mede a precisão das propostas do agente contra o mesmo
gabarito — ver `proposals_correct` e `agent_cost_microcents`.
"""

from collections import Counter
from dataclasses import dataclass

from orchestrator.agent.proposal import Cost
from orchestrator.matching.engine import ReconcileResult
from orchestrator.money import format_brl
from orchestrator.synth.dataset import Dataset
from orchestrator.taxonomy import DivergenceType


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
    matches_by_layer: dict[str, int]
    proposals_total: int
    proposals_correct: int
    proposals_abstained: int
    cost_by_resolver_microcents: dict[str, int]
    agent_cost_microcents: int

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
        linhas.append("")
        linhas.append("Resoluções por camada:")
        for camada, n in sorted(self.matches_by_layer.items()):
            linhas.append(f"  {camada:<24} {n}")
        linhas.append("Custo por resolver:")
        for nome, micro in sorted(self.cost_by_resolver_microcents.items()):
            linhas.append(f"  {nome:<24} US$ {micro / 100_000_000:.6f}")
        if self.proposals_total:
            linhas.append("")
            linhas.append(f"Propostas do agente:           {self.proposals_total}")
            linhas.append(f"  corretas contra o gabarito:  {self.proposals_correct}")
            linhas.append(f"  abstenções:                  {self.proposals_abstained}")
            linhas.append(
                f"  custo:                       "
                f"US$ {self.agent_cost_microcents / 100_000_000:.4f}"
            )
        return "\n".join(linhas)


def evaluate(
    dataset: Dataset, result: ReconcileResult, model: str = "claude-opus-5"
) -> Metrics:
    bank_total = len(dataset.bank)
    ids_banco = {e.id for e in dataset.bank}
    ids_contabil = {e.id for e in dataset.ledger}

    # `definition` é um ponto de extensão anunciado (reconcile aceita
    # qualquer WorkflowDefinition, com qualquer Resolver). Um resolver com bug
    # — ou hostil — pode devolver ids que não existem no dataset; sem
    # intersectar, esses ids fantasma inflam o numerador sem limite e a taxa
    # passa de 1.0. A interseção com os ids reais do dataset é a garantia de
    # domínio que o tipo por si só não dá.
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

    # Conta MatchResults, não lançamentos casados — um único MatchResult pode
    # cobrir vários ids de uma vez (ex.: PAGAMENTO_AGREGADO casa 1 bancário +
    # N contábeis num resultado só). Unidade correta, deixada assim de
    # propósito: contar ids infla camadas que resolvem casos agregados.
    por_camada = dict(Counter(m.layer for m in result.matches))

    # A precisão das propostas sai de graça: o gabarito da plano 1 já carrega o
    # tipo de cada divergência injetada. Uma proposta está correta quando o tipo
    # que ela propõe é o tipo que o gabarito registra para algum id que ela toca.
    tipo_por_id: dict[str, DivergenceType] = {}
    for gt in dataset.truth:
        for i in gt.bank_ids | gt.ledger_ids:
            tipo_por_id[i] = gt.divergence_type

    divergencia_por_id = {d.id: (d.bank_ids | d.ledger_ids) for d in result.divergences}
    corretas = abstencoes = 0
    for p in result.proposals:
        if p.tipo is DivergenceType.NAO_IDENTIFICADO:
            abstencoes += 1
            continue
        # Nome diferente da função `ids` acima de propósito: a mesma
        # divergência aqui não é o `gt` que a função recebe, e reusar o nome
        # sombreava a função dentro deste laço.
        ids_tocados = divergencia_por_id.get(p.divergence_id, frozenset())
        if any(tipo_por_id.get(i) is p.tipo for i in ids_tocados):
            corretas += 1

    # Zero custo não precisa de preço: um resolver que não gastou token
    # nenhum converte para 0 microcents em qualquer modelo, e não é justo
    # travar essa conversão porque `model` não está na tabela de preços — a
    # cascata pode ser só de regras, sem agente algum, e nesse caso o
    # chamador nunca deveria precisar de um `model` válido para ler "zero"
    # por resolver. Um resolver que de fato gastou token exige preço de
    # verdade, e `Cost.microcents` continua estourando `ValueError` para ele.
    custos = {
        nome: custo.microcents(model) if custo != Cost.zero() else 0
        for nome, custo in result.cost_by_resolver.items()
    }

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
        matches_by_layer=por_camada,
        proposals_total=len(result.proposals),
        proposals_correct=corretas,
        proposals_abstained=abstencoes,
        cost_by_resolver_microcents=custos,
        # A soma, não um campo próprio: um número que discorda da soma das
        # partes é a pior espécie de métrica.
        agent_cost_microcents=sum(custos.values()),
    )
