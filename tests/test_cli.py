import pytest

from orchestrator.cli import build_benchmark, main
from orchestrator.conciliacao import reconcile
from orchestrator.metrics import evaluate


def test_benchmark_rejeita_taxa_divergencia_fora_do_intervalo():
    # --taxa-divergencia -1 faz `alvo` ficar negativo, o laço nunca roda, e a
    # CLI imprime "Taxa determinística: 100.0%" com exit code 0 — degradação
    # silenciosa no único lugar onde um humano lê o número.
    with pytest.raises(ValueError):
        build_benchmark(seed=1, n=10, taxa_divergencia=-1.0)
    with pytest.raises(ValueError):
        build_benchmark(seed=1, n=10, taxa_divergencia=1.5)


def test_benchmark_injeta_a_proporcao_pedida():
    ds = build_benchmark(seed=1, n=100, taxa_divergencia=0.2)
    # cada injeção consome um ou mais pares; a contagem é aproximada por desenho
    assert 5 <= len(ds.truth) <= 25


def test_benchmark_cobre_varios_tipos():
    ds = build_benchmark(seed=1, n=200, taxa_divergencia=0.3)
    tipos = {gt.divergence_type for gt in ds.truth}
    assert len(tipos) >= 3


def test_benchmark_e_deterministico():
    a = build_benchmark(seed=5, n=50, taxa_divergencia=0.2)
    b = build_benchmark(seed=5, n=50, taxa_divergencia=0.2)
    assert a.bank == b.bank
    assert [t.divergence_type for t in a.truth] == [t.divergence_type for t in b.truth]


def test_camadas_nao_erram_e_taxa_e_estavel_entre_sementes():
    # Uma semente só faz este teste passar ou falhar por sorte do sorteio: a
    # taxa medida oscila vários pontos entre sementes. Então o teste varre
    # várias e separa o que é invariante do que é distribuição.
    #
    # INVARIANTE (asserção dura, por semente): as camadas não erram. Falso
    # positivo e falso negativo são zero em toda semente medida — 24 execuções
    # entre n=300 e n=500 sem uma única ocorrência. Este é o sinal que importa:
    # casar errado é pior que não casar.
    #
    # DISTRIBUIÇÃO (piso sobre o MÍNIMO, não sobre a média): a taxa medida a
    # n=300 nas sementes 1-5 é 86,8 / 83,0 / 85,3 / 89,7 / 90,1, e em 12
    # sementes vai de 83,0% a 92,3% com média 87,2%.
    #
    # A asserção é sobre o mínimo de propósito. O que um teste de regressão
    # precisa pegar é ALGUMA semente colapsar, e a média esconde exatamente
    # esse caso: uma semente caindo de 85% para 40% mal move a média de cinco.
    # Um piso sobre a média também não falsifica — com 0,85 sobre a média este
    # teste continuaria passando, o que o tornaria decorativo.
    #
    # Piso em 78%, cinco pontos abaixo do mínimo medido de 83,0%: folga para a
    # dispersão observada sem virar teste instável.
    #
    # Estas medições assumem a composição atual do benchmark, e o piso NÃO
    # protege contra essa composição mudar:
    #
    # 1. _FRACAO_AGREGADOS (cli.py) = 0.25 controla que fração das injeções
    #    vira PAGAMENTO_AGREGADO, o único tipo que as camadas resolvem
    #    sozinhas. Variar essa fração de 0.00 a 0.90 move a taxa média de
    #    78,1% a 99,5% — um piso fixo não pega a mistura de agregados
    #    caindo a zero, só uma semente ruim dentro da mistura atual.
    #
    # 2. O benchmark só injeta 4 dos 14 tipos da taxonomia: DEFASAGEM_TEMPORAL,
    #    RETENCAO_IMPOSTO, DEVOLUCAO_FUNDOS e PAGAMENTO_AGREGADO. TARIFA_BANCARIA,
    #    JUROS_MULTA e DESCONTO_ANTECIPACAO são deltas pequenos que a
    #    tolerância de 5 centavos de L2 não absorveria, e DUPLICIDADE criaria
    #    contenção em L1 — os quatro empurrariam a taxa para baixo se
    #    existissem. A taxa medida aqui é sobre uma mistura de 4 em 14 tipos e,
    #    por isso, tende a ser um limite superior otimista, não a taxa que um
    #    dataset com a taxonomia completa produziria.
    taxas = []
    for semente in range(1, 6):
        ds = build_benchmark(seed=semente, n=300, taxa_divergencia=0.15)
        m = evaluate(ds, reconcile(ds.bank, ds.ledger))

        assert m.false_positives == 0, f"semente {semente}: {m.render()}"
        assert m.false_negatives == 0, f"semente {semente}: {m.render()}"
        taxas.append(m.deterministic_rate)

    pior = min(taxas)
    media = sum(taxas) / len(taxas)
    assert pior >= 0.78, (
        f"pior semente {pior:.1%}, média {media:.1%} em {len(taxas)} sementes: "
        f"{[f'{t:.1%}' for t in taxas]}"
    )


def test_main_roda_e_retorna_zero(capsys):
    assert main(["--seed", "1", "--n", "50"]) == 0
    assert "Taxa determinística" in capsys.readouterr().out
