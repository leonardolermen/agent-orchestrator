"""O registro de ferramentas: uma fonte para schema e despacho."""

import pytest

from orchestrator.agent.tools.registry import (
    ToolPermission,
    ToolRegistry,
    ToolSpec,
    tool_schema,
)


def _spec(nome="somar", fn=None, **kw) -> ToolSpec:
    return ToolSpec(
        name=nome,
        description="soma dois números",
        input_schema=tool_schema(
            nome, "", {"a": {"type": "integer"}, "b": {"type": "integer"}}, ["a", "b"]
        ),
        fn=fn or (lambda a, b: {"total": a + b}),
        **kw,
    )


def test_o_schema_e_o_despacho_saem_da_MESMA_entrada():
    """O join frágil que este módulo existe para matar.

    Antes havia `ToolContext` (objeto com métodos) e `TOOL_SCHEMAS` (lista
    literal ao lado), e o despacho cruzava os dois. Uma ferramenta podia
    existir num lado e não no outro, e só uma chamada do modelo descobriria.
    """
    r = ToolRegistry([_spec()])

    assert [s["name"] for s in r.schemas()] == list(r.names())
    assert r.call("somar", {"a": 2, "b": 3}).value == {"total": 5}


def test_nome_repetido_e_recusado_no_REGISTRO():
    # Duas com o mesmo nome fariam o despacho depender da ordem de registro.
    with pytest.raises(ValueError, match="repetida"):
        ToolRegistry([_spec(), _spec()])


def test_ferramenta_WRITE_sem_compensadora_e_recusada():
    """Enquanto toda ferramenta for somente-leitura não há o que compensar
    (§6.5). O registry é onde essa condição deixa de ser promessa."""
    with pytest.raises(ValueError, match="compensadora"):
        ToolRegistry([_spec(permission=ToolPermission.WRITE)])

    ok = ToolRegistry([_spec(permission=ToolPermission.WRITE, compensates="desfazer")])
    assert "somar" in ok


def test_timeout_nao_positivo_e_recusado():
    # Config que não faz nada e não avisa é armadilha — a mesma disciplina dos
    # `__post_init__` dos matchers.
    with pytest.raises(ValueError, match="positivo"):
        ToolRegistry([_spec(timeout_s=0)])


def test_ferramenta_inexistente_devolve_erro_e_NAO_levanta():
    """O modelo se corrige sozinho; o processo não se recupera de um estouro.

    Preservado de `Investigator._executar`: erro de ferramenta volta ao modelo
    dentro do resultado, nunca como exceção.
    """
    r = ToolRegistry([_spec()])

    assert r.call("nao_existe", {}).error == "ferramenta inexistente"


def test_ferramenta_que_estoura_devolve_erro_e_NAO_levanta():
    def explode(a, b):
        raise ValueError("argumento inválido")

    r = ToolRegistry([_spec(fn=explode)])

    resultado = r.call("somar", {"a": 1, "b": 2})

    assert resultado.error == "argumento inválido"
    assert resultado.para_modelo() == {"erro": "argumento inválido"}


def test_argumentos_None_somem_antes_da_chamada():
    """O schema declara campos como `["integer", "null"]` para o modelo poder
    omitir logicamente sem quebrar `strict`; quem recebe é uma função Python
    com defaults. Preservado de `Investigator._executar`."""
    vistos = {}
    r = ToolRegistry([_spec(fn=lambda a=None, b=None: vistos.update(a=a, b=b))])

    r.call("somar", {"a": 1, "b": None})

    assert vistos == {"a": 1, "b": None}


def test_mede_latencia_por_chamada():
    """Novo com o registry: antes não havia onde a latência de ferramenta
    morar, e `Cost` só mede token."""
    r = ToolRegistry([_spec()])

    assert r.call("somar", {"a": 1, "b": 1}).duration_ms >= 0


def test_a_ordem_dos_schemas_e_estavel():
    """System prompt e schemas são marcados para cache (`anthropic_client`), e
    cache com ordem instável é cache que nunca acerta."""
    r = ToolRegistry([_spec("a"), _spec("b"), _spec("c")])

    assert [s["name"] for s in r.schemas()] == ["a", "b", "c"]
    assert [s["name"] for s in r.schemas()] == [s["name"] for s in r.schemas()]


def test_palavra_de_schema_que_a_API_recusa_e_barrada_no_REGISTRO():
    """O defeito que custou uma avaliação inteira, agora barrado de graça.

    `"minimum": 1` num campo `integer` fez a Messages API recusar a requisição
    com `tools.0.custom: For 'integer' type, property 'minimum' is not
    supported` — e como a recusa é da requisição INTEIRA, uma ferramenta
    malformada derruba todas as outras junto.
    """
    spec = ToolSpec(
        name="somar",
        description="soma",
        input_schema=tool_schema(
            "somar", "", {"a": {"type": "integer", "minimum": 1}}, ["a"]
        ),
        fn=lambda a: a,
    )

    with pytest.raises(ValueError, match="minimum"):
        ToolRegistry([spec])


def test_a_recusa_diz_ONDE_a_palavra_esta():
    """Um registro com cinco ferramentas e schemas aninhados precisa apontar o
    campo, não só o nome da ferramenta."""
    spec = ToolSpec(
        name="somar",
        description="soma",
        input_schema=tool_schema(
            "somar", "", {"faixa": {"type": "object", "properties":
                {"topo": {"type": "integer", "maximum": 9}}}}, ["faixa"]
        ),
        fn=lambda faixa: faixa,
    )

    with pytest.raises(ValueError, match=r"properties\.faixa\.properties\.topo"):
        ToolRegistry([spec])


def test_as_ferramentas_REAIS_passam_pela_guarda():
    """Regressão do caminho que quebrou: as cinco da conciliação, como o
    modelo as vê. Um teste sobre um schema inventado não teria pego o
    `minimum` que estava em produção."""
    from orchestrator.conciliacao.ferramentas import ToolContext, registry_de

    registry = registry_de(ToolContext(bank=(), ledger=()))

    assert len(registry.names()) == 5
