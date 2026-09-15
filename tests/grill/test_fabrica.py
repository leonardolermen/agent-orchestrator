import inspect
from datetime import UTC, datetime

from orchestrator.api.app import fabrica_de
from orchestrator.grill.receita import Receita, ResolverReceita
from orchestrator.review.fila import Fila


def _r() -> Receita:
    return Receita(
        id="acme",
        nome="Acme",
        justificativa="j",
        gerado_em=datetime(2026, 9, 15, tzinfo=UTC),
        resolvers=(ResolverReceita("L1", {}), ResolverReceita("revisor", {})),
    )


def test_a_fabrica_de_receita_declara_o_parametro_fila():
    # `_construir_definicao` decide repassar a fila olhando o NOME literal
    # `fila` na assinatura. Renomear para `q` deixa tudo verde e faz o
    # workflow gerado servir fila vazia em silêncio.
    assert "fila" in inspect.signature(fabrica_de(_r())).parameters


def test_a_fabrica_repassa_a_fila_ao_revisor():
    fila = Fila.vazia()
    definicao = fabrica_de(_r())(fila)

    revisor = next(r for r in definicao.stages[0].ordered() if r.name == "revisor")
    assert revisor.fila is fila
