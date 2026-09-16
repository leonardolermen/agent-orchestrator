"""As políticas de conciliação — e a unidade que quase passou batido."""

from orchestrator.conciliacao.politica import (
    MICROCENTS_POR_CENTAVO_BRL,
    POLITICA_ATUAL,
    POLITICA_ECONOMICA,
    POLITICA_ENSAIO,
    valor_em_risco,
)
from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.policy import Autonomy
from orchestrator.kernel.work import WorkItem
from orchestrator.models import BANCO, CONTABIL, pool
from orchestrator.synth.generator import generate_clean_pairs


def _par():
    return generate_clean_pairs(seed=3, n=1)[0]


def test_valor_em_risco_devolve_MICROCENTS_e_nao_centavos():
    """A unidade é a do CUSTO, não a do domínio, e é o que torna a regra 7
    comparável.

    Este teste existe porque a primeira versão comparava micro-centavos de USD
    contra centavos de BRL crus. Medido durante o M3: `POLITICA_ECONOMICA`
    pulou 20 de 20 divergências e reportou custo zero. Parecia economia máxima;
    era unidade errada — 4.000.000 contra 1.050, e o item perdia sempre.

    Num repositório cuja primeira regra é que dinheiro nunca pode estar errado,
    a conversão precisa de constante com nome, não de aritmética implícita.
    """
    par = _par()
    item = WorkItem(id=par.bank.id, kind=BANCO, payload=par.bank)

    assert valor_em_risco(item) == abs(par.bank.amount) * MICROCENTS_POR_CENTAVO_BRL


def test_o_limiar_da_politica_economica_e_o_que_o_comentario_diz():
    """R$ 10,40: abaixo disso, investigar custa mais de 2% do que está em jogo.

    A conta está no comentário de `POLITICA_ECONOMICA`, e um comentário com
    número é um número que desatualiza. Este teste é o que o prende.
    """
    orcamento = 4_000_000  # µ¢ por item, o default do agente
    limiar_microcents = orcamento / POLITICA_ECONOMICA.max_cost_ratio
    limiar_reais = limiar_microcents / MICROCENTS_POR_CENTAVO_BRL / 100

    assert 10.0 < limiar_reais < 11.0


def test_o_lado_contabil_usa_o_liquido():
    # `net_amount` é o que se compara com o extrato — a mesma escolha que
    # `_do_contabil` já faz na API.
    par = _par()
    item = WorkItem(id=par.ledger.id, kind=CONTABIL, payload=par.ledger)

    assert valor_em_risco(item) == par.ledger.net_amount * MICROCENTS_POR_CENTAVO_BRL


def test_kind_desconhecido_devolve_None_e_nao_zero():
    """Zero significaria "não vale nada" e faria a regra 7 pular o item
    sempre. `None` significa "a regra não se aplica", que é diferente."""
    assert valor_em_risco(WorkItem(id="x", kind="outro", payload=None)) is None


def test_politica_atual_nao_tem_razao_de_custo_nem_predicado():
    """Ela existe para descrever o comportamento ANTERIOR ao M3, exatamente.

    Se ganhar um predicado, o motor de política deixa de entrar sem mudar um
    número — e o teste que compara os dois resultados quebra.
    """
    assert POLITICA_ATUAL.max_cost_ratio is None
    assert POLITICA_ATUAL.skip_when is None
    assert POLITICA_ATUAL.escalate_when is None
    assert POLITICA_ATUAL.autonomy is Autonomy.PROPOR
    assert POLITICA_ATUAL.max_cost_class is CostClass.HUMANO


def test_politica_de_ensaio_nao_deixa_classe_paga_rodar():
    """O `--dry-run` da CLI (M5), garantido pela regra 4 e não por uma flag."""
    assert POLITICA_ENSAIO.autonomy is Autonomy.OBSERVAR


def test_o_pool_de_conciliacao_produz_os_dois_kinds_que_a_politica_le():
    """Se `models.pool` mudar os nomes dos kinds, `valor_em_risco` devolve
    `None` para tudo e a regra 7 some em silêncio. Este teste amarra os dois."""
    par = _par()
    work = pool(bank=[par.bank], ledger=[par.ledger])

    assert {i.kind for i in work.items} == {BANCO, CONTABIL}
    assert all(valor_em_risco(i) is not None for i in work.items)
