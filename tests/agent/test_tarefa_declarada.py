"""A tarefa como DADO: o que `TarefaSpec` exige em função, declarado em campo.

`TarefaSpec` pede `prompt_de` e `transformar` — duas funções Python. Um bloco
de composição é dado: `data/composicoes/*.json` é dado, e o canvas edita dado.
Esta classe é o mesmo movimento que `AgenteDeclarado` fez para o `Agent`, onde
`units`/`parse`/`abstain` deixaram de ser funções e viraram campos.
"""

import pytest

from orchestrator.agent.declarado import TarefaDeclarada


def _decl(**kw) -> TarefaDeclarada:
    base = dict(
        name="escritor",
        system="você escreve a partir de achados",
        kind="achados",
        produz="rascunho",
        prompt="Escreva a partir de: {achados}",
    )
    base.update(kw)
    return TarefaDeclarada(**base)


def test_uma_tarefa_declarada_minima_constroi():
    decl = _decl()

    assert decl.kind == "achados"
    assert decl.produz == "rascunho"
    # Sem `tipos` e sem `abstem_com`: não transformar é a AUSÊNCIA de
    # resolução, e ausência não tem rótulo de domínio para escolher — é o que
    # `tarefa.py::_abster` já diz por escrito.
    assert not hasattr(decl, "tipos")
    assert not hasattr(decl, "abstem_com")


def test_produz_VAZIO_e_recusado():
    """Consumir sem produzir faz o item sumir do run. Para descartar de
    propósito existe o `filtro` — a mesma frase que `condicao.py` usa."""
    with pytest.raises(ValueError, match="produz"):
        _decl(produz="")


def test_produz_IGUAL_ao_kind_e_recusado():
    """O ramo alimentaria a si mesmo: o item sai como `x` e volta como `x`, e o
    degrau roda de novo sobre a própria saída até o teto de rondas."""
    with pytest.raises(ValueError, match="mesmo kind"):
        _decl(kind="rascunho", produz="rascunho")


def test_prompt_que_nao_interpola_NADA_e_recusado():
    """Todo item receberia o mesmo texto, e o modelo transformaria sem ler o
    item. É caro e silencioso: a conta vem, a medida não."""
    with pytest.raises(ValueError, match="interpola"):
        _decl(prompt="escreva alguma coisa")


def test_kind_VAZIO_e_recusado():
    with pytest.raises(ValueError, match="kind"):
        _decl(kind="")


def test_orcamento_negativo_e_recusado():
    with pytest.raises(ValueError, match="negativo"):
        _decl(budget_microcents=-1)


def _fake(respostas: list[str]):
    from orchestrator.agent.llm import FakeLLMClient, LLMResponse
    from orchestrator.kernel.cost import Cost

    return FakeLLMClient(
        [
            LLMResponse(text=t, tool_calls=[], cost=Cost(input_tokens=10, output_tokens=5))
            for t in respostas
        ]
    )


def _pool(kind: str, payload: dict):
    from orchestrator.kernel.work import WorkItem, WorkSet

    return WorkSet(items=(WorkItem(id="i1", kind=kind, payload=payload),))


def test_a_tarefa_declarada_TRANSFORMA_o_item():
    """O texto do modelo vira o payload de um item novo, do kind declarado.

    `payload={produz: texto}` e não texto cru: `_campos` levanta `TypeError`
    para payload que não é dict nem dataclass, então uma string crua quebraria
    o bloco SEGUINTE ao montar o prompt — e encadear é o que este bloco existe
    para permitir.
    """
    from orchestrator.agent.declarado import construir_tarefa

    tarefa = construir_tarefa(_decl(), _fake(["o rascunho pronto"]))

    saida = tarefa.resolve(_pool("achados", {"achados": "tres fatos"}))

    assert len(saida.resolutions) == 1
    assert saida.proposals == []
    (produzido,) = saida.produced
    assert produzido.kind == "rascunho"
    assert produzido.payload == {"rascunho": "o rascunho pronto"}
    assert produzido.id == "i1+rascunho"


def test_o_prompt_INTERPOLA_os_campos_do_item():
    from orchestrator.agent.declarado import construir_tarefa

    cliente = _fake(["pronto"])
    tarefa = construir_tarefa(_decl(), cliente)

    tarefa.resolve(_pool("achados", {"achados": "tres fatos"}))

    assert cliente.chamadas[0]["messages"][0]["content"] == "Escreva a partir de: tres fatos"


def test_texto_VAZIO_nao_vira_item():
    """Texto vazio não é rascunho. `None` pede retry de formato; esgotado o
    retry, o item fica no pool para o próximo degrau em vez de virar um item
    produzido que ninguém consegue usar."""
    from orchestrator.agent.declarado import construir_tarefa

    tarefa = construir_tarefa(_decl(), _fake(["   ", "   ", "   "]))

    saida = tarefa.resolve(_pool("achados", {"achados": "tres fatos"}))

    assert saida.resolutions == []
    assert saida.produced == ()


def test_ferramenta_INEXISTENTE_e_recusada_nomeando_as_que_ha():
    from orchestrator.agent.declarado import construir_tarefa

    with pytest.raises(ValueError, match="ferramenta inexistente"):
        construir_tarefa(_decl(ferramentas=("nao_existe",)), _fake(["x"]))


def test_a_tarefa_so_pega_o_KIND_que_declara():
    """Um degrau pode ter mais de um bloco, e o motor filtra pelo `consome` do
    STAGE — a união. Sem filtrar por kind aqui, a tarefa tentaria transformar o
    item que é do vizinho: `_campos` estouraria, ou pior, o modelo receberia um
    item que não é dele e a conta viria igual."""
    from orchestrator.agent.declarado import construir_tarefa
    from orchestrator.kernel.work import WorkItem, WorkSet

    cliente = _fake(["pronto"])
    tarefa = construir_tarefa(_decl(), cliente)

    saida = tarefa.resolve(
        WorkSet(
            items=(
                WorkItem(id="i1", kind="achados", payload={"achados": "tres fatos"}),
                WorkItem(id="i2", kind="outro", payload={"x": 1}),
            )
        )
    )

    assert len(saida.resolutions) == 1
    assert len(cliente.chamadas) == 1
