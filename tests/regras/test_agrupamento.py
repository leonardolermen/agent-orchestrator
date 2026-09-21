"""Um item cobrindo N do outro lado, sem saber que N são lançamentos."""

from dataclasses import dataclass

import pytest

from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.regras.agrupamento import Agrupamento


@dataclass(frozen=True)
class Pago:
    fornecedor: str
    valor: int


@dataclass(frozen=True)
class Fatura:
    fornecedor: str
    total: int


def _pool(pagos, faturas) -> WorkSet:
    return WorkSet(
        items=tuple(
            [
                WorkItem(id=f"p{i}", kind="pago", payload=x, origem="t")
                for i, x in enumerate(pagos)
            ]
            + [
                WorkItem(id=f"f{i}", kind="fatura", payload=x, origem="t")
                for i, x in enumerate(faturas)
            ]
        )
    )


def _regra(**kw) -> Agrupamento:
    base = dict(
        esquerda="pago", direita="fatura", chave=("fornecedor",), soma="valor=total"
    )
    return Agrupamento(**{**base, **kw})


def test_agrupa_o_que_soma():
    work = _pool(
        [Pago("ACME", 300)], [Fatura("ACME", 100), Fatura("ACME", 200)]
    )

    saida = _regra().resolve(work)

    assert len(saida.resolutions) == 1
    assert saida.resolutions[0].item_ids == frozenset({"p0", "f0", "f1"})


def test_nao_agrupa_o_que_nao_soma():
    work = _pool([Pago("ACME", 999)], [Fatura("ACME", 100), Fatura("ACME", 200)])

    assert _regra().resolve(work).resolutions == []


def test_a_chave_separa_os_candidatos():
    # Sem a chave, a soma sozinha casaria itens sem relação nenhuma.
    work = _pool([Pago("ACME", 300)], [Fatura("ACME", 100), Fatura("OUTRA", 200)])

    assert _regra().resolve(work).resolutions == []


def test_a_folga_vale_para_a_soma():
    work = _pool([Pago("ACME", 302)], [Fatura("ACME", 100), Fatura("ACME", 200)])

    assert _regra().resolve(work).resolutions == []
    assert len(_regra(max_diferenca=5).resolve(work).resolutions) == 1


def test_prefere_o_MENOR_grupo():
    """Entre dois grupos que somam igual, o de dois itens é mais provavelmente
    o agrupamento real; o de quatro tem mais chance de ser coincidência
    aritmética."""
    work = _pool(
        [Pago("ACME", 100)],
        [Fatura("ACME", 50), Fatura("ACME", 50), Fatura("ACME", 25), Fatura("ACME", 75)],
    )

    saida = _regra().resolve(work)

    assert len(saida.resolutions[0].item_ids) == 3  # o pago mais DOIS


def test_um_item_so_entra_em_um_grupo():
    work = _pool(
        [Pago("ACME", 300), Pago("ACME", 300)],
        [Fatura("ACME", 100), Fatura("ACME", 200)],
    )

    assert len(_regra().resolve(work).resolutions) == 1


def test_o_teto_de_candidatos_barra_a_explosao():
    """A busca é combinatória. Sem teto, algumas centenas de candidatos travam
    o run — e pool maior é mais oportunidade de uma soma coincidir por acaso."""
    faturas = [Fatura("ACME", 1) for _ in range(30)]
    work = _pool([Pago("ACME", 2)], faturas)

    assert _regra(max_candidatos=10).resolve(work).resolutions == []
    assert len(_regra(max_candidatos=40).resolve(work).resolutions) == 1


def test_modulo_para_quem_registra_com_sinal_invertido():
    work = _pool([Pago("ACME", -300)], [Fatura("ACME", 100), Fatura("ACME", 200)])

    assert _regra().resolve(work).resolutions == []
    assert len(_regra(modulo=True).resolve(work).resolutions) == 1


def test_configuracao_impossivel_e_recusada_na_construcao():
    with pytest.raises(ValueError, match="pelo menos 2"):
        _regra(max_itens=1)
    with pytest.raises(ValueError, match="teto de candidatos"):
        _regra(max_itens=10, max_candidatos=5)
    with pytest.raises(ValueError, match="consigo mesmo"):
        _regra(direita="pago")


def test_roda_sobre_dict():
    work = _pool(
        [{"fornecedor": "ACME", "valor": 300}],
        [{"fornecedor": "ACME", "total": 100}, {"fornecedor": "ACME", "total": 200}],
    )

    assert len(_regra().resolve(work).resolutions) == 1
