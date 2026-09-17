from datetime import UTC, datetime

import pytest

from orchestrator.grill.receita import (
    Receita,
    ResolverReceita,
    construir,
    de_json,
    para_json,
    validar_id,
)
from orchestrator.kernel.cost import CostClass


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
    #
    # `investigador`, não `agente`: o catálogo plano (Task 3) nomeia o bloco
    # AGENTE da conciliação pelo `Resolver.name` que ele sempre teve
    # (`Investigator.name` já era "investigador" antes desta fatia) — o
    # cardápio do grill é que usava a chave `"agente"` só para ele.
    r = _receita(ResolverReceita("investigador", {}))
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


def test_validar_id_aceita_id_valido():
    # Não deve levantar. Também cobre a borda inferior do `{2,39}`: "abc" tem
    # 3 caracteres, o mínimo aceito.
    assert validar_id("abc") is None
    assert validar_id("acme-2") is None


def test_validar_id_aceita_a_borda_superior_do_comprimento():
    # 40 caracteres: 1 (primeiro) + 39 (o teto de `{2,39}`).
    assert validar_id("a" + "b" * 39) is None


def test_validar_id_rejeita_id_curto_demais():
    # 2 caracteres: abaixo do mínimo de 3 (a borda inferior do `{2,39}`).
    with pytest.raises(ValueError, match="inválido"):
        validar_id("ab")


def test_validar_id_rejeita_id_longo_demais():
    # 41 caracteres: acima do teto de 40.
    with pytest.raises(ValueError, match="inválido"):
        validar_id("a" + "b" * 40)


def test_validar_id_rejeita_maiuscula():
    with pytest.raises(ValueError, match="inválido"):
        validar_id("Acme")


def test_validar_id_rejeita_caractere_invalido():
    with pytest.raises(ValueError, match="inválido"):
        validar_id("acme_um")


def test_validar_id_rejeita_path_traversal():
    # Um id com `../` escreveria fora de `data/` se chegasse ao registro sem
    # passar por aqui.
    with pytest.raises(ValueError, match="inválido"):
        validar_id("../etc")


def test_validar_id_rejeita_id_reservado():
    with pytest.raises(ValueError, match="reservado"):
        validar_id("conciliacao")


# `test_construir_rejeita_max_turns_menor_que_um`,
# `test_construir_rejeita_budget_microcents_negativo` e
# `test_construir_rejeita_budget_total_microcents_negativo` não migram: elas
# provavam que o bloco `"agente"` do CARDÁPIO do grill aceitava
# `max_turns`/`budget_microcents`/`budget_total_microcents` como parâmetro da
# RECEITA e repassava para `Investigator.__post_init__` validar. Isso exigia
# uma entrada de catálogo com assinatura própria — exatamente o que
# `EntradaCatalogo.construir(parametros, *, fila, cliente, context)` permitia
# e o que `RegraDisponivel.construir(parametros)` (Task 1) deliberadamente não
# tem espaço para reproduzir.
#
# `AgenteDeclarado` (o "investigador" do catálogo plano) não expõe NENHUM
# parâmetro ajustável — `max_turns`/orçamento são fixados na DECLARAÇÃO do
# domínio (`domains/registro.py`), não na composição — e são validados lá, por
# `AgenteDeclarado.__post_init__`/`Agent.__post_init__`, no import, nunca por
# uma receita. Uma receita que tentasse passar esses nomes hoje é recusada
# como "parâmetro desconhecido" (mesma guarda que já existia para as regras),
# o que é um resultado diferente do que estes três testes mediam — a
# capacidade em si não existe mais para migrar.
