"""A regra de igualdade: a mesma lógica do L1, sem saber o que é um lançamento."""

from dataclasses import dataclass

import pytest

from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.regras import CampoAusente, Igualdade


@dataclass(frozen=True)
class Esquerdo:
    documento: str | None
    valor: int


@dataclass(frozen=True)
class Direito:
    documento: str | None
    total: int


def _pool(esquerdos, direitos) -> WorkSet:
    return WorkSet(
        items=tuple(
            [
                WorkItem(id=f"e{i}", kind="esq", payload=p, origem="teste")
                for i, p in enumerate(esquerdos)
            ]
            + [
                WorkItem(id=f"d{i}", kind="dir", payload=p, origem="teste")
                for i, p in enumerate(direitos)
            ]
        )
    )


def _regra(**kw) -> Igualdade:
    base = dict(esquerda="esq", direita="dir", campos=("documento", "valor=total"))
    return Igualdade(**{**base, **kw})


def test_casa_quando_todos_os_campos_batem():
    work = _pool([Esquerdo("NF-1", 100)], [Direito("NF-1", 100)])

    saida = _regra().resolve(work)

    assert len(saida.resolutions) == 1
    assert saida.resolutions[0].item_ids == frozenset({"e0", "d0"})


def test_um_campo_diferente_nao_casa():
    work = _pool([Esquerdo("NF-1", 100)], [Direito("NF-1", 101)])

    assert _regra().resolve(work).resolutions == []


def test_um_item_so_casa_uma_vez():
    # Sem `usados`, dois esquerdos idênticos casariam ambos com o mesmo direito
    # e o pool encolheria menos do que o relatório diz.
    work = _pool([Esquerdo("NF-1", 100), Esquerdo("NF-1", 100)], [Direito("NF-1", 100)])

    saida = _regra().resolve(work)

    assert len(saida.resolutions) == 1


def test_campo_vazio_nao_casa_com_campo_vazio():
    # `None == None` é verdade, e sem a guarda dois itens SEM documento
    # passariam a casar um com o outro por não terem documento — um falso
    # positivo fabricado pela ausência de dado.
    work = _pool([Esquerdo(None, 100)], [Direito(None, 100)])

    assert _regra().resolve(work).resolutions == []


def test_modulo_casa_sinais_opostos():
    # A razão de o L1 não poder ser genérico antes: o banco registra saída como
    # negativa, o contábil registra o mesmo valor como positivo.
    work = _pool([Esquerdo("NF-1", -100)], [Direito("NF-1", 100)])

    assert _regra().resolve(work).resolutions == []
    assert len(_regra(modulo=("valor",)).resolve(work).resolutions) == 1


def test_a_mesma_regra_roda_sobre_dict():
    """O ponto inteiro do pacote: fonte de arquivo entrega dicionário.

    Uma regra tipada (`ExactMatcher` lia `be.document`) estoura com `dict` —
    é a combinação que a API recusa com 422. Esta roda, e é por isso que o L1
    deixou de aparecer naquela recusa.
    """
    work = _pool([{"documento": "NF-1", "valor": 100}], [{"documento": "NF-1", "total": 100}])

    assert len(_regra().resolve(work).resolutions) == 1


def test_campo_inexistente_falha_nomeando_o_campo():
    work = _pool([{"outro": 1}], [{"documento": "NF-1", "total": 100}])

    with pytest.raises(CampoAusente) as erro:
        _regra().resolve(work)

    assert "documento" in str(erro.value)


def test_recusa_na_construcao_e_nao_no_casamento():
    """Regra malformada que só falhasse ao rodar apareceria como "não casou
    nada" — indistinguível de "não havia o que casar"."""
    with pytest.raises(ValueError):
        _regra(campos=())
    with pytest.raises(ValueError):
        _regra(campos=("a=b=c",))
    with pytest.raises(ValueError):
        _regra(modulo=("inexistente",))
    with pytest.raises(ValueError, match="casaria consigo mesmo"):
        _regra(direita="esq")


def test_o_nome_do_par_sem_igual_vale_para_os_dois_lados():
    assert _regra().pares[0].esquerda == _regra().pares[0].direita == "documento"


def test_nao_exige_tipo_e_declara_os_dois_kinds():
    d = _regra().describe()

    # `payloads` vazio é o que permite a mesma regra rodar sobre dataclass e
    # sobre dict — e é o que a borda de `/runs` lê para decidir se recusa.
    assert d.payloads == {}
    assert d.consome == frozenset({"esq", "dir"})


def test_a_ordem_do_resultado_segue_a_ordem_do_pool():
    # O golden de 12 sementes pina contagem por resolver; ordem instável faria
    # o mesmo dado produzir arquivos diferentes.
    work = _pool(
        [Esquerdo("A", 1), Esquerdo("B", 2)], [Direito("B", 2), Direito("A", 1)]
    )

    ids = [sorted(r.item_ids) for r in _regra().resolve(work).resolutions]

    assert ids == [["d1", "e0"], ["d0", "e1"]]


def test_reproduz_o_L1_do_dominio_sobre_o_dataset_de_verdade():
    """A prova de que a regra genérica substitui a específica.

    Não é "parece equivalente": é o MESMO conjunto de pares, na mesma ordem,
    sobre o dataset que o golden usa. Se um dia divergir, o `default_resolvers`
    da conciliação está entregando outra coisa.
    """
    from orchestrator.domains.reconciliation.models import pool
    from orchestrator.domains.reconciliation.resolvers.exact import ExactMatcher
    from orchestrator.domains.reconciliation.synth.generator import (
        build_dataset,
        generate_clean_pairs,
    )
    from orchestrator.domains.reconciliation.workflow import l1_exato

    ds = build_dataset(generate_clean_pairs(seed=1, n=300), injections=[])
    work = pool(ds.bank, ds.ledger)

    do_dominio = [r.item_ids for r in ExactMatcher().resolve(work).resolutions]
    generico = [r.item_ids for r in l1_exato().resolve(work).resolutions]

    assert do_dominio == generico
    assert len(generico) == 300
