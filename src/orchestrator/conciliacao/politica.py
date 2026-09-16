"""As políticas de conciliação, e o que o domínio sabe que o kernel não sabe.

O kernel não sabe o que vale uma divergência nem quanto custa investigá-la. Ele
sabe chamar um `Callable` e registrar o resultado. As duas funções aqui são
esses callables — e são a razão de `PolicyContext` ter campos em vez de o motor
ter `if`s.
"""

from orchestrator.agent.agent import AgentSpec
from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.policy import (
    Autonomy,
    Budget,
    ExecutionPolicy,
    PolicyContext,
)
from orchestrator.kernel.work import WorkItem
from orchestrator.models import BANCO, CONTABIL

# Câmbio BRL→USD, em micro-centavos de dólar por centavo de real.
#
# Existe porque a regra 7 da política compara DUAS GRANDEZAS EM MOEDAS
# DIFERENTES: `custo_estimado` é o orçamento do agente, em micro-centavos de
# USD; `valor_em_risco` é um lançamento, em centavos de BRL. Comparar os dois
# crus é comparar 4.000.000 com 1.050 — e a regra pularia TODOS os itens,
# sempre, de forma perfeitamente silenciosa.
#
# Medido durante o M3: com a comparação crua, `POLITICA_ECONOMICA` pulou 20 de
# 20 divergências e reportou custo zero. Parecia economia máxima; era unidade
# errada. Num repositório cuja primeira regra é que dinheiro nunca pode estar
# errado, isso precisa de uma constante com nome e não de uma conversão
# implícita.
#
#   1 centavo BRL = 0,01 BRL ÷ 5,20 BRL/USD = 0,001923 USD
#                 = 192.308 µ¢  (1 µ¢ = 1e-8 USD)
#
# Taxa fixa e grosseira DE PROPÓSITO: uma política que muda de comportamento
# com a cotação do dia seria impossível de reproduzir num benchmark. Quando
# precisar ser real, vem de configuração e entra no `input_ref` do run — não
# aqui.
MICROCENTS_POR_CENTAVO_BRL = 192_308


def valor_em_risco(item: WorkItem) -> int | None:
    """Quanto este lançamento vale, em MICRO-CENTAVOS DE USD.

    A unidade é a do custo, não a do domínio, e é o que torna a regra 7
    comparável. Converter aqui — e não no kernel — mantém o kernel sem saber o
    que é moeda.

    Bancário usa o valor absoluto (débito é negativo); contábil usa o líquido,
    que é o que se compara com o extrato — a mesma escolha que `_do_contabil`
    já faz na API.

    Devolve `None` para `kind` desconhecido em vez de zero: zero significaria
    "não vale nada" e faria a regra 7 pular o item sempre; `None` significa "a
    regra não se aplica", que é diferente e é o certo.
    """
    p = item.payload
    if item.kind == BANCO:
        centavos = abs(p.amount)
    elif item.kind == CONTABIL:
        centavos = p.net_amount
    else:
        return None
    return centavos * MICROCENTS_POR_CENTAVO_BRL


def custo_estimado(resolver_name: str, spec: AgentSpec | None = None) -> int:
    """O que investigar um item custaria, em micro-centavos.

    Usa o ORÇAMENTO por item como estimativa, e é deliberado: ele é o teto, e
    decidir com o teto erra para o lado seguro — a política nunca autoriza um
    gasto que o orçamento depois recusaria. Uma estimativa média (medida em
    produção) é mais justa e é trabalho de M4, quando houver histórico de
    custo por item para calcular a média com.
    """
    if resolver_name != "investigador":
        return 0
    return spec.budget_microcents if spec else 4_000_000


def contexto(model: str = "claude-opus-5") -> PolicyContext:
    """O `PolicyContext` da conciliação, com os dois callables ligados."""
    return PolicyContext(
        model=model,
        value_at_risk=valor_em_risco,
        estimated_cost=custo_estimado,
    )


# A política que descreve o comportamento ANTERIOR ao M3, exatamente.
#
# Ela existe para que o motor de política entre sem mudar um número: teto na
# classe mais cara, autonomia PROPOR (o agente propõe, nunca resolve), sem
# predicado e sem razão de custo. Se rodar com ela produzir um resultado
# diferente do de antes, o motor de política tem bug — e há teste que compara.
POLITICA_ATUAL = ExecutionPolicy(
    budget=Budget(per_run_microcents=400_000_000),
    autonomy=Autonomy.PROPOR,
    max_cost_class=CostClass.HUMANO,
)

# O agente só acorda quando vale a pena.
#
# `max_cost_ratio=0.02` diz: no máximo 2% do valor em risco. Com o orçamento
# padrão de US$ 0,04 por item, o limiar sai da conta:
#
#   4.000.000 µ¢ = 0,02 × valor  ->  valor = 200.000.000 µ¢
#                                          = 1.040 centavos = R$ 10,40
#
# Abaixo disso, investigar custa mais de 2% do que está em jogo. É a tese do
# projeto numa linha: não gaste US$ 0,04 para investigar R$ 0,30.
POLITICA_ECONOMICA = ExecutionPolicy(
    budget=Budget(per_run_microcents=400_000_000),
    autonomy=Autonomy.PROPOR,
    max_cost_class=CostClass.HUMANO,
    max_cost_ratio=0.02,
)

# Fechamento: tudo que sobrar vai para humano, sem gastar com agente.
#
# `max_cost_class=REGRA` é o teto; o revisor (HUMANO) fica acima dele e não
# roda. Parece contraintuitivo até lembrar que o revisor APLICA decisões já
# tomadas — num fechamento sem revisão prévia ele não tem o que aplicar.
POLITICA_SEM_AGENTE = ExecutionPolicy(
    budget=Budget(per_run_microcents=400_000_000),
    autonomy=Autonomy.PROPOR,
    max_cost_class=CostClass.REGRA,
)

# Ensaio: registra o que faria, sem gastar um centavo.
#
# É o `--dry-run` da CLI (M5). `Autonomy.OBSERVAR` nunca executa classe acima de
# REGRA, e a garantia é da REGRA 4 do motor — não de uma flag que alguém lembra
# de passar.
POLITICA_ENSAIO = ExecutionPolicy(autonomy=Autonomy.OBSERVAR)
