from random import Random

from orchestrator.domains.reconciliation.models import lados, pool
from orchestrator.domains.reconciliation.resolvers.grouping import GroupingMatcher
from orchestrator.domains.reconciliation.synth.generator import generate_clean_pairs
from orchestrator.domains.reconciliation.synth.injectors import DevolucaoFundos, PagamentoAgregado


def test_casa_pagamento_agregado_de_tres_notas():
    pares = generate_clean_pairs(seed=6, n=3)
    inj = PagamentoAgregado().apply_many(Random(0), pares)

    work = pool(bank=inj.bank, ledger=inj.ledger)

    r = GroupingMatcher().resolve(work).resolutions

    assert len(r) == 1
    # O lado vem do POOL, não do campo: `Resolution` guarda um `item_ids` só.
    assert lados(work, r[0].item_ids)[1] == frozenset(le.id for le in inj.ledger)
    assert r[0].produced_by == "L3"


def test_nao_casa_grupo_maior_que_o_limite():
    pares = generate_clean_pairs(seed=6, n=6)
    inj = PagamentoAgregado().apply_many(Random(0), pares)

    assert (
        GroupingMatcher(max_group_size=4)
        .resolve(pool(bank=inj.bank, ledger=inj.ledger))
        .resolutions
        == []
    )


def test_nao_resolve_devolucao_de_fundos():
    # Devolução é caso do agente, não das camadas determinísticas. Ver spec 4.5.
    par = generate_clean_pairs(seed=6, n=1)[0]
    inj = DevolucaoFundos().apply(Random(0), par)

    assert GroupingMatcher().resolve(pool(bank=inj.bank, ledger=inj.ledger)).resolutions == []


def test_registra_as_parcelas_na_evidencia():
    pares = generate_clean_pairs(seed=6, n=2)
    inj = PagamentoAgregado().apply_many(Random(0), pares)

    r = GroupingMatcher().resolve(pool(bank=inj.bank, ledger=inj.ledger)).resolutions[0]

    assert r.evidence["quantidade"] == 2
    assert r.evidence["soma"] == abs(inj.bank[0].amount)


def test_evidencia_registra_o_valor_de_cada_documento_agrupado():
    # A soma sozinha não é a metade não óbvia da alegação de L3: "estes N
    # valores somam este total" só é auditável se os N valores individuais
    # estiverem na evidência, não só o total. Spec 4.3: a trilha de auditoria
    # é subproduto do matching, não algo a reconstruir depois.
    pares = generate_clean_pairs(seed=6, n=2)
    inj = PagamentoAgregado().apply_many(Random(0), pares)

    r = GroupingMatcher().resolve(pool(bank=inj.bank, ledger=inj.ledger)).resolutions[0]

    valores = r.evidence["valores_por_documento"]
    for le in inj.ledger:
        chave = le.document or le.id
        assert chave in valores
        assert valores[chave] == le.net_amount
    assert sum(valores.values()) == r.evidence["soma"]


def test_nao_agrupa_fornecedores_diferentes():
    from dataclasses import replace

    pares = generate_clean_pairs(seed=6, n=2)
    inj = PagamentoAgregado().apply_many(Random(0), pares)
    contabeis = [inj.ledger[0], replace(inj.ledger[1], supplier="OUTRO FORNECEDOR SA")]

    assert GroupingMatcher().resolve(pool(bank=inj.bank, ledger=contabeis)).resolutions == []


def test_rejeita_configuracao_que_nunca_agrupa():
    # Tamanho 1 esvazia o range de combinações: a camada nunca agruparia nada,
    # sem erro e sem aviso.
    import pytest

    with pytest.raises(ValueError):
        GroupingMatcher(max_group_size=1)
    with pytest.raises(ValueError):
        GroupingMatcher(max_business_days=-1)
    with pytest.raises(ValueError):
        GroupingMatcher(max_candidates=2, max_group_size=4)


def test_ignora_pool_de_candidatos_grande_demais():
    # Sem teto, o custo é O(C^max_group_size) e os dois botões da camada não
    # limitam nada. Estourou o teto, o lançamento vira divergência.
    #
    # O pool aqui tem 6 candidatos e CONTÉM o trio que soma, com max_group_size
    # no padrão — então o teto é a única coisa que pode causar o retorno vazio.
    # Um pool menor que o grupo máximo provaria o tamanho do grupo, não o teto.
    from dataclasses import replace

    pares = generate_clean_pairs(seed=6, n=6)
    inj = PagamentoAgregado().apply_many(Random(0), pares[:3])
    fornecedor = inj.ledger[0].supplier
    data = inj.ledger[0].cash_date
    ruido = [replace(p.ledger, supplier=fornecedor, cash_date=data) for p in pares[3:]]
    contabeis = inj.ledger + ruido

    assert (
        GroupingMatcher(max_candidates=4).resolve(pool(bank=inj.bank, ledger=contabeis)).resolutions
        == []
    )
    assert (
        GroupingMatcher(max_candidates=6).resolve(pool(bank=inj.bank, ledger=contabeis)).resolutions
        != []
    )


def test_ignora_creditos():
    # A camada casa PAGAMENTOS agregados. Um crédito é recebimento e não
    # deveria procurar faturas a pagar — é assim que a perna de crédito de uma
    # devolução entrava na busca.
    from dataclasses import replace

    pares = generate_clean_pairs(seed=6, n=3)
    inj = PagamentoAgregado().apply_many(Random(0), pares)
    credito = [replace(inj.bank[0], amount=abs(inj.bank[0].amount))]

    assert GroupingMatcher().resolve(pool(bank=credito, ledger=inj.ledger)).resolutions == []


def test_nao_consome_o_contabil_de_uma_devolucao_vizinha():
    # Regressão do caso real: devolução e uma fatura limpa do mesmo fornecedor
    # liquidando na mesma janela. Com valores que não coincidem, L3 não pode
    # tocar o contábil da devolução.
    from dataclasses import replace

    pares = generate_clean_pairs(seed=6, n=2)
    fornecedor = pares[0].ledger.supplier
    vizinho = replace(
        pares[1].ledger, supplier=fornecedor, cash_date=pares[0].ledger.cash_date
    )
    inj = DevolucaoFundos().apply(Random(0), pares[0])

    work = pool(bank=inj.bank, ledger=[inj.ledger[0], vizinho])

    r = GroupingMatcher().resolve(work).resolutions

    consumidos = {i for m in r for i in lados(work, m.item_ids)[1]}
    assert inj.ledger[0].id not in consumidos
