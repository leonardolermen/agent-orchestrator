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
