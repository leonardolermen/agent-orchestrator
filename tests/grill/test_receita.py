from datetime import UTC, datetime

import pytest

from orchestrator.grill.receita import (
    Receita,
    ResolverReceita,
    construir,
    de_json,
    para_json,
)
from orchestrator.workflow.cost_class import CostClass


def _receita(*resolvers: ResolverReceita, id: str = "acme") -> Receita:
    return Receita(
        id=id,
        nome="Conciliação Acme",
        justificativa="o parceiro consolida por fornecedor",
        gerado_em=datetime(2026, 9, 15, 12, 0, tzinfo=UTC),
        resolvers=tuple(resolvers),
    )


def test_construir_produz_definicao_com_os_parametros_propostos():
    r = _receita(
        ResolverReceita("L1", {}),
        ResolverReceita("L2", {"max_cents": 10, "max_business_days": 5}),
    )
    d = construir(r)

    assert d.id == "acme"
    assert d.name == "Conciliação Acme"
    cascata = d.stages[0].ordered()
    assert [x.name for x in cascata] == ["L1", "L2"]
    assert cascata[1].max_cents == 10
    assert cascata[1].max_business_days == 5


def test_construir_ordena_por_classe_de_custo_ignorando_a_ordem_proposta():
    # O modelo pode propor [revisor, L1]; o motor roda [L1, revisor]. Regra
    # antiga, não nova — `Stage.ordered()` já fazia isso com a embutida.
    r = _receita(ResolverReceita("revisor", {}), ResolverReceita("L1", {}))
    cascata = construir(r).stages[0].ordered()

    assert [x.name for x in cascata] == ["L1", "revisor"]
    assert [x.cost_class for x in cascata] == [CostClass.REGRA, CostClass.HUMANO]


def test_construir_rejeita_resolver_fora_do_catalogo():
    r = _receita(ResolverReceita("L9", {}))
    with pytest.raises(ValueError, match="L9"):
        construir(r)


def test_construir_rejeita_chave_de_parametro_desconhecida():
    # Ignorar em silêncio entregaria a tolerância default ao parceiro que
    # pediu 10 — e ninguém descobriria olhando a tela.
    r = _receita(ResolverReceita("L2", {"tolerancia": 10}))
    with pytest.raises(ValueError, match="tolerancia"):
        construir(r)


def test_construir_rejeita_resolver_repetido():
    # O segundo L2 roda sobre o pool que o primeiro esvaziou e casa zero: não
    # é erro para o Python, é uma camada de 0% inexplicável na tela.
    r = _receita(ResolverReceita("L2", {}), ResolverReceita("L2", {"max_cents": 9}))
    with pytest.raises(ValueError, match="repetido"):
        construir(r)


def test_construir_rejeita_cascata_vazia():
    with pytest.raises(ValueError, match="pelo menos um"):
        construir(_receita())


def test_construir_propaga_a_mensagem_do_post_init_do_resolver():
    # A validação É a construção: a faixa mora no resolver, e a mensagem dele
    # é o que volta ao modelo para ele corrigir.
    r = _receita(ResolverReceita("L2", {"max_cents": -1}))
    with pytest.raises(ValueError, match="max_cents não pode ser negativo"):
        construir(r)


def test_construir_usa_defaults_inertes():
    # Sem cliente e sem contexto, um workflow com agente ainda CONSTRÓI (logo
    # é desenhável) — e só explode se alguém tentar chamar o modelo.
    r = _receita(ResolverReceita("agente", {}))
    d = construir(r)

    agente = d.stages[0].ordered()[0]
    assert agente.cost_class is CostClass.AGENTE
    with pytest.raises(RuntimeError, match="ClienteAusente"):
        agente.client.complete(system="s", messages=[], tools=[])


def test_round_trip_json():
    r = _receita(
        ResolverReceita("L1", {}),
        ResolverReceita("L3", {"max_group_size": 3}),
    )
    assert de_json(para_json(r)) == r


def test_para_json_preserva_a_ordem_proposta():
    # A receita grava o que o modelo propôs, verbatim; a ordenação por classe
    # acontece na execução. Reordenar na serialização apagaria a intenção.
    r = _receita(ResolverReceita("revisor", {}), ResolverReceita("L1", {}))
    assert [x["nome"] for x in para_json(r)["resolvers"]] == ["revisor", "L1"]
