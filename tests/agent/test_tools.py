import pytest

from orchestrator.agent.tools import TOOL_SCHEMAS, ToolContext
from orchestrator.synth.generator import build_dataset, generate_clean_pairs


def _contexto() -> ToolContext:
    ds = build_dataset(generate_clean_pairs(seed=3, n=20), injections=[])
    return ToolContext(bank=ds.bank, ledger=ds.ledger)


def test_busca_lancamento_por_valor():
    ctx = _contexto()
    alvo = ctx.ledger[0]

    achados = ctx.buscar_lancamentos(valor=alvo.net_amount)

    assert any(a["id"] == alvo.id for a in achados)


def test_busca_lancamento_por_fornecedor():
    ctx = _contexto()
    fornecedor = ctx.ledger[0].supplier

    achados = ctx.buscar_lancamentos(fornecedor=fornecedor)

    assert achados
    assert all(a["fornecedor"] == fornecedor for a in achados)


def test_busca_limita_o_numero_de_resultados():
    # O agente recebe só o que pede, e o que ele pede não pode virar o dataset
    # inteiro — isso é custo e é qualidade.
    ctx = _contexto()

    achados = ctx.buscar_lancamentos(limite=3)

    assert len(achados) <= 3


def test_limite_invalido_e_rejeitado():
    # Medido antes da guarda: limite=-3 devolvia 197 de 200 lançamentos,
    # porque a fatia `achados[:-3]` devolve tudo menos os últimos três.
    ctx = _contexto()
    with pytest.raises(ValueError):
        ctx.buscar_lancamentos(limite=0)
    with pytest.raises(ValueError):
        ctx.buscar_lancamentos(limite=-3)


def test_limite_maior_que_o_padrao_e_respeitado():
    ctx = _contexto()
    assert len(ctx.buscar_lancamentos(limite=15)) <= 15


def test_busca_sem_criterio_nenhum_e_rejeitada():
    ctx = _contexto()
    with pytest.raises(ValueError):
        ctx.buscar_lancamentos()


def test_busca_documento_fiscal():
    ctx = _contexto()
    doc = ctx.ledger[0].document

    achado = ctx.buscar_documento_fiscal(documento=doc)

    assert achado is not None
    assert achado["documento"] == doc


def test_documento_inexistente_devolve_none():
    assert _contexto().buscar_documento_fiscal(documento="NF-INEXISTENTE") is None


def test_historico_do_fornecedor_traz_estatistica():
    ctx = _contexto()
    fornecedor = ctx.ledger[0].supplier

    h = ctx.historico_fornecedor(fornecedor=fornecedor)

    assert h["quantidade"] >= 1
    assert h["valor_total"] == sum(
        le.net_amount for le in ctx.ledger if le.supplier == fornecedor
    )


def test_calcular_retencao_e_deterministico_e_inteiro():
    # Cálculo fiscal é ferramenta, não raciocínio do modelo.
    ctx = _contexto()
    assert ctx.calcular_retencao(bruto=100_000, aliquota_bp=500) == 5_000
    assert isinstance(ctx.calcular_retencao(bruto=333, aliquota_bp=500), int)


def test_calendario_conta_dias_uteis():
    ctx = _contexto()
    r = ctx.calendario_bancario(de="2026-09-18", ate="2026-09-21")
    assert r["dias_uteis"] == 1


def test_calendario_rejeita_data_malformada():
    ctx = _contexto()
    with pytest.raises(ValueError):
        ctx.calendario_bancario(de="18/09/2026", ate="2026-09-21")


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


def test_todo_schema_tem_metodo_correspondente_no_contexto():
    ctx = _contexto()
    for s in TOOL_SCHEMAS:
        assert callable(getattr(ctx, s["name"]))
