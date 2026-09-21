"""A regra de tolerância: chave exata, mais uma folga que se aceita."""

from dataclasses import dataclass
from datetime import date

import pytest

from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.regras import Tolerancia


@dataclass(frozen=True)
class Esquerdo:
    documento: str
    valor: int
    quando: date


@dataclass(frozen=True)
class Direito:
    documento: str
    total: int
    liquidado: date


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


def _regra(**kw) -> Tolerancia:
    base = dict(
        esquerda="esq",
        direita="dir",
        chave=("documento",),
        numerico="valor=total",
        max_diferenca=5,
    )
    return Tolerancia(**{**base, **kw})


def test_diferenca_dentro_da_folga_casa():
    work = _pool(
        [Esquerdo("NF-1", 100, date(2026, 1, 5))],
        [Direito("NF-1", 103, date(2026, 1, 5))],
    )

    saida = _regra().resolve(work)

    assert len(saida.resolutions) == 1
    assert saida.resolutions[0].evidence["diferenca"] == 3


def test_diferenca_acima_da_folga_nao_casa():
    work = _pool(
        [Esquerdo("NF-1", 100, date(2026, 1, 5))],
        [Direito("NF-1", 106, date(2026, 1, 5))],
    )

    assert _regra().resolve(work).resolutions == []


def test_a_chave_precisa_bater_exatamente():
    # Folga é desempate, não critério: sem a chave, dois itens sem relação
    # nenhuma casariam só por terem valores parecidos.
    work = _pool(
        [Esquerdo("NF-1", 100, date(2026, 1, 5))],
        [Direito("NF-2", 100, date(2026, 1, 5))],
    )

    assert _regra().resolve(work).resolutions == []


def test_folga_de_dias_quando_pedida():
    work = _pool(
        [Esquerdo("NF-1", 100, date(2026, 1, 5))],
        [Direito("NF-1", 100, date(2026, 1, 8))],
    )

    assert len(_regra(data="quando=liquidado", max_dias=3).resolve(work).resolutions) == 1
    assert _regra(data="quando=liquidado", max_dias=2).resolve(work).resolutions == []


def test_sem_campo_de_data_a_condicao_temporal_nao_existe():
    # O default não pode impor uma condição que ninguém pediu: `max_dias=0`
    # com data ausente casaria só datas idênticas e pareceria bug.
    work = _pool(
        [Esquerdo("NF-1", 100, date(2026, 1, 5))],
        [Direito("NF-1", 100, date(2030, 12, 31))],
    )

    assert len(_regra().resolve(work).resolutions) == 1


def test_modulo_compara_magnitudes():
    work = _pool(
        [Esquerdo("NF-1", -100, date(2026, 1, 5))],
        [Direito("NF-1", 102, date(2026, 1, 5))],
    )

    assert _regra().resolve(work).resolutions == []
    assert len(_regra(modulo=True).resolve(work).resolutions) == 1


def test_folga_negativa_e_recusada_na_construcao():
    # Folga negativa não casaria nada e pareceria uma regra que simplesmente
    # não encontrou nada — a mesma recusa que `ToleranceMatcher` já fazia.
    with pytest.raises(ValueError):
        _regra(max_diferenca=-1)
    with pytest.raises(ValueError):
        _regra(data="quando=liquidado", max_dias=-1)


def test_um_item_so_casa_uma_vez():
    work = _pool(
        [Esquerdo("NF-1", 100, date(2026, 1, 5)), Esquerdo("NF-1", 100, date(2026, 1, 5))],
        [Direito("NF-1", 100, date(2026, 1, 5))],
    )

    assert len(_regra().resolve(work).resolutions) == 1


def test_roda_sobre_dict_igual_roda_sobre_dataclass():
    work = _pool(
        [{"documento": "NF-1", "valor": 100}],
        [{"documento": "NF-1", "total": 102}],
    )

    assert len(_regra().resolve(work).resolutions) == 1


def test_NAO_substitui_o_L2_porque_dia_util_nao_e_campo():
    """O limite honesto desta regra, cobrado por teste.

    O L2 da conciliação conta DIAS ÚTEIS: uma sexta e a segunda seguinte
    distam 1 dia útil e 3 corridos. Esta regra só sabe contar corridos, porque
    feriado e fim de semana são conhecimento de domínio e não configuração de
    campo. Com a folga de 1 que o L2 aceitaria, ela recusa — e é por isso que o
    L2 continua no domínio.
    """
    sexta, segunda = date(2026, 1, 2), date(2026, 1, 5)
    work = _pool([Esquerdo("NF-1", 100, sexta)], [Direito("NF-1", 100, segunda)])

    from orchestrator.domains.reconciliation.dates import business_days_between

    assert business_days_between(sexta, segunda) == 1
    assert (segunda - sexta).days == 3
    assert _regra(data="quando=liquidado", max_dias=1).resolve(work).resolutions == []
