import dataclasses

import pytest

from orchestrator.agent.tools import ToolContext
from orchestrator.grill.catalogo import CATALOGO, ClienteAusente, ParametroSpec
from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.review.fila import Fila


def _inerte():
    return {"fila": Fila.vazia(), "cliente": ClienteAusente(), "context": ToolContext([], [])}


def test_toda_entrada_do_catalogo_constroi_com_os_defaults():
    # A propriedade central da fatia: o `enum` da ferramenta sai de
    # CATALOGO.keys(), então tudo que o modelo pode propor precisa construir.
    # É `for` sobre o catálogo, não exemplo: uma entrada nova entra coberta.
    for chave, entrada in CATALOGO.items():
        resolver = entrada.construir({}, **_inerte())
        assert resolver.cost_class is entrada.cost_class, chave


def test_resumo_do_catalogo_bate_com_o_describe_do_resolver():
    # Duas fontes de verdade para a mesma frase divergiriam na primeira
    # mudança, e a tela mostraria uma coisa e o motor outra.
    for chave, entrada in CATALOGO.items():
        resolver = entrada.construir({}, **_inerte())
        assert resolver.describe().summary == entrada.resumo, chave


def test_default_de_parametro_vem_do_proprio_resolver():
    # `max_cents` default 5 mora em ToleranceMatcher. Se alguém mudar lá e o
    # catálogo continuar dizendo 5, o modelo recebe informação falsa.
    from orchestrator.matching.tolerance import ToleranceMatcher

    campos = {f.name: f.default for f in dataclasses.fields(ToleranceMatcher)}
    specs = {p.nome: p.default for p in CATALOGO["L2"].parametros}
    assert specs["max_cents"] == campos["max_cents"]
    assert specs["max_business_days"] == campos["max_business_days"]


def test_parametro_inexistente_no_resolver_explode_na_construcao_do_catalogo():
    from orchestrator.grill.catalogo import _param
    from orchestrator.matching.tolerance import ToleranceMatcher

    with pytest.raises(ValueError, match="não tem campo"):
        _param(ToleranceMatcher, "tolerancia", "campo que não existe")


def test_cliente_ausente_tem_modelo_precificado():
    # `Investigator.__post_init__` chama Cost.zero().microcents(client.model).
    # Um nome inventado faria a construção levantar — e a entrada `agente`
    # deixaria de ser sequer DESENHÁVEL.
    Cost.zero().microcents(ClienteAusente().model)


def test_cliente_ausente_levanta_ao_ser_chamado():
    with pytest.raises(RuntimeError, match="ClienteAusente"):
        ClienteAusente().complete(system="s", messages=[], tools=[])


def test_o_catalogo_cobre_as_tres_classes_de_custo():
    classes = {e.cost_class for e in CATALOGO.values()}
    assert classes == {CostClass.REGRA, CostClass.AGENTE, CostClass.HUMANO}


def test_parametro_spec_e_imutavel():
    p = ParametroSpec(nome="x", default=1, descricao="d")
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.default = 2
