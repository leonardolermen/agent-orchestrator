import inspect

import pytest

from orchestrator.conciliacao.ferramentas import FERRAMENTAS, TOOL_SCHEMAS, ToolContext
from orchestrator.conciliacao.ferramentas.buscar_documento_fiscal import buscar_documento_fiscal
from orchestrator.conciliacao.ferramentas.buscar_lancamentos import buscar_lancamentos
from orchestrator.conciliacao.ferramentas.calcular_retencao import calcular_retencao
from orchestrator.conciliacao.ferramentas.calendario_bancario import calendario_bancario
from orchestrator.conciliacao.ferramentas.historico_fornecedor import historico_fornecedor
from orchestrator.synth.generator import build_dataset, generate_clean_pairs


def _contexto() -> ToolContext:
    ds = build_dataset(generate_clean_pairs(seed=3, n=20), injections=[])
    return ToolContext(bank=ds.bank, ledger=ds.ledger)


def test_busca_lancamento_por_valor():
    ctx = _contexto()
    alvo = ctx.ledger[0]

    achados = buscar_lancamentos(ctx, valor=alvo.net_amount)

    assert any(a["id"] == alvo.id for a in achados)


def test_busca_lancamento_por_fornecedor():
    ctx = _contexto()
    fornecedor = ctx.ledger[0].supplier

    achados = buscar_lancamentos(ctx, fornecedor=fornecedor)

    assert achados
    assert all(a["fornecedor"] == fornecedor for a in achados)


def test_busca_limita_o_numero_de_resultados():
    # O agente recebe só o que pede, e o que ele pede não pode virar o dataset
    # inteiro — isso é custo e é qualidade.
    ctx = _contexto()

    achados = buscar_lancamentos(ctx, limite=3)

    # Sem isto, um resultado sempre vazio também satisfaria "len <= 3" — o
    # teste passaria mesmo se a busca estivesse quebrada e não devolvesse
    # nada.
    assert achados
    assert len(achados) <= 3


def test_limite_invalido_e_rejeitado():
    # Medido antes da guarda: limite=-3 devolvia 197 de 200 lançamentos,
    # porque a fatia `achados[:-3]` devolve tudo menos os últimos três.
    ctx = _contexto()
    with pytest.raises(ValueError):
        buscar_lancamentos(ctx, limite=0)
    with pytest.raises(ValueError):
        buscar_lancamentos(ctx, limite=-3)


def test_limite_maior_que_o_padrao_e_respeitado():
    ctx = _contexto()
    assert len(buscar_lancamentos(ctx, limite=15)) <= 15


def test_busca_sem_criterio_nenhum_e_rejeitada():
    ctx = _contexto()
    with pytest.raises(ValueError):
        buscar_lancamentos(ctx)


def test_busca_documento_fiscal():
    ctx = _contexto()
    doc = ctx.ledger[0].document

    achado = buscar_documento_fiscal(ctx, documento=doc)

    assert achado is not None
    assert achado["documento"] == doc


def test_documento_inexistente_devolve_none():
    assert buscar_documento_fiscal(_contexto(), documento="NF-INEXISTENTE") is None


def test_historico_do_fornecedor_traz_estatistica():
    ctx = _contexto()
    fornecedor = ctx.ledger[0].supplier

    h = historico_fornecedor(ctx, fornecedor=fornecedor)

    assert h["quantidade"] >= 1
    assert h["valor_total"] == sum(
        le.net_amount for le in ctx.ledger if le.supplier == fornecedor
    )


def test_calcular_retencao_e_deterministico_e_inteiro():
    # Cálculo fiscal é ferramenta, não raciocínio do modelo.
    ctx = _contexto()
    assert calcular_retencao(ctx, bruto=100_000, aliquota_bp=500) == 5_000
    assert isinstance(calcular_retencao(ctx, bruto=333, aliquota_bp=500), int)


def test_calendario_conta_dias_uteis():
    r = calendario_bancario(_contexto(), de="2026-09-18", ate="2026-09-21")
    assert r["dias_uteis"] == 1


def test_calendario_rejeita_data_malformada():
    with pytest.raises(ValueError):
        calendario_bancario(_contexto(), de="18/09/2026", ate="2026-09-21")


def test_todo_schema_tem_nome_descricao_e_e_estrito():
    # strict exige additionalProperties false mais required — sem isso o modelo
    # pode inventar argumento e a chamada falha em runtime.
    assert len(TOOL_SCHEMAS) == 5
    for s in TOOL_SCHEMAS:
        assert s["name"]
        assert s["description"]
        assert s["strict"] is True
        assert s["input_schema"]["additionalProperties"] is False
        assert "required" in s["input_schema"]


def test_nome_da_ferramenta_e_o_nome_da_funcao():
    # O único join que sobrou de "uma ferramenta por arquivo": `name` é string e
    # `fn` é função, e em tese podem divergir. Divergir significaria o modelo
    # chamar um nome e o registro executar outra coisa — silencioso, e sobre
    # dados. Os dois estão a dez linhas de distância no mesmo arquivo; isto aqui
    # é o que recusa a distância crescer.
    for spec in FERRAMENTAS:
        assert spec.name == spec.fn.__name__, (
            f"{spec.name!r} despacha para {spec.fn.__name__!r}"
        )


def test_todo_schema_tem_a_assinatura_da_funcao_que_despacha():
    # Só checar que a função existe deixava passar um schema com um campo a
    # mais, a menos, ou com nome diferente do parâmetro real — e uma chamada
    # estrita do modelo falharia em runtime com TypeError, não em teste.
    #
    # O primeiro parâmetro fica de fora: é o CONTEXTO, que o `ToolRegistry`
    # injeta posicionalmente e o modelo nunca vê.
    for spec in FERRAMENTAS:
        parametros = list(inspect.signature(spec.fn).parameters)
        assert parametros, f"{spec.name}: função sem parâmetro de contexto"
        do_modelo = set(parametros[1:])
        propriedades = set(spec.input_schema["properties"])
        assert propriedades == do_modelo, (
            f"{spec.name}: schema declara {propriedades}, função aceita {do_modelo}"
        )
