"""O agente como DADO: a peça que torna a plataforma geral.

O teste que mais importa aqui é `test_reproduz_o_triador_do_swe`: ele monta, só
com declaração, o agente que hoje existe como quinze linhas de Python no
domínio `swe`, e exige o mesmo comportamento. Se a declaração não alcançasse um
agente que já existe, ela seria uma abstração desenhada a partir de nada.
"""

import json
from dataclasses import dataclass

import pytest

from orchestrator.agent.declarado import (
    AgenteDeclarado,
    construir_agente,
)
from orchestrator.agent.llm import FakeLLMClient, LLMResponse, ToolCall
from orchestrator.agent.tools.registry import ToolRegistry, ToolSpec, tool_schema
from orchestrator.kernel.cost import Cost
from orchestrator.kernel.resolution import Confidence
from orchestrator.kernel.work import WorkItem, WorkSet

MODELO = "claude-haiku-4-5"


@dataclass(frozen=True)
class Issue:
    id: str
    titulo: str
    corpo: str


def _decl(**kw) -> AgenteDeclarado:
    base = dict(
        name="triador",
        system="classifique a issue",
        kind="issue",
        prompt="{titulo}\n\n{corpo}",
        tipos=("BUG", "FEATURE", "DUVIDA"),
        abstem_com="NAO_SEI",
    )
    return AgenteDeclarado(**{**base, **kw})


def _pool(*issues: Issue) -> WorkSet:
    return WorkSet(
        items=tuple(WorkItem(id=i.id, kind="issue", payload=i) for i in issues)
    )


def _texto(tipo, evidencia=("pista",), confianca="MEDIA") -> LLMResponse:
    return LLMResponse(
        text=json.dumps(
            {
                "tipo": tipo,
                "explicacao": "porque sim",
                "evidencia": list(evidencia),
                "confianca": confianca,
            }
        ),
        tool_calls=[],
        cost=Cost(input_tokens=100, output_tokens=20, calls=1),
    )


def _contar_palavras() -> ToolRegistry:
    return ToolRegistry(
        [
            ToolSpec(
                name="contar_palavras",
                description="Conta palavras.",
                input_schema=tool_schema(
                    "contar_palavras", "", {"texto": {"type": "string"}}, ["texto"]
                ),
                fn=lambda texto: {"palavras": len(texto.split())},
            ),
            ToolSpec(
                name="outra",
                description="Outra coisa.",
                input_schema=tool_schema("outra", "", {}, []),
                fn=lambda: {"ok": True},
            ),
        ]
    )


# -- a prova de que a declaração alcança um agente que já existe ------------


def test_reproduz_o_triador_do_swe():
    """Declaração pura chega ao mesmo resultado das quinze linhas de Python.

    Se não chegasse, a declaração seria uma abstração desenhada a partir de
    nada — que é exatamente o que a regra dos três usos existe para impedir.
    """
    agente = construir_agente(_decl(), FakeLLMClient([_texto("BUG")]))

    (p,) = agente.resolve(_pool(Issue("i-1", "Crasha ao salvar", "NPE na linha 84"))).proposals

    assert p.item_id == "i-1"
    assert p.tipo == "BUG"
    assert p.confianca is Confidence.MEDIA


def test_o_prompt_e_um_TEMPLATE_sobre_o_payload():
    cliente = FakeLLMClient([_texto("FEATURE")])
    agente = construir_agente(_decl(), cliente)

    agente.resolve(_pool(Issue("i-1", "Exportar CSV", "hoje só tem PDF")))

    # O que o modelo VIU: título e corpo interpolados, nesta ordem.
    assert cliente.chamadas[0]["messages"][0]["content"] == "Exportar CSV\n\nhoje só tem PDF"


def test_so_pega_itens_do_KIND_declarado():
    """Sem `kind`, o agente proporia sobre coisa que não sabe ler."""
    pool = WorkSet(
        items=(
            WorkItem(id="i-1", kind="issue", payload=Issue("i-1", "a", "b")),
            WorkItem(id="r-9", kind="requisicao", payload={"item": "papel"}),
        )
    )
    agente = construir_agente(_decl(), FakeLLMClient([_texto("BUG")]))

    propostas = agente.resolve(pool).proposals

    assert [p.item_id for p in propostas] == ["i-1"]


# -- o vocabulário fechado --------------------------------------------------


def test_tipo_FORA_do_vocabulario_dispara_retry_e_acaba_em_abstencao():
    inventado = LLMResponse(
        text='{"tipo":"INVENTADO","explicacao":"x","evidencia":[],"confianca":"BAIXA"}',
        tool_calls=[],
        cost=Cost(input_tokens=10, output_tokens=5, calls=1),
    )
    agente = construir_agente(_decl(), FakeLLMClient([inventado] * 5))

    (p,) = agente.resolve(_pool(Issue("i-1", "a", "b"))).proposals

    assert p.tipo == "NAO_SEI"


def test_o_rotulo_de_ABSTENCAO_e_resposta_valida_e_nao_erro_de_formato():
    """O modelo PODE dizer que não sabe — e isso não pode gastar os retries."""
    cliente = FakeLLMClient([_texto("NAO_SEI", evidencia=())])
    agente = construir_agente(_decl(), cliente)

    (p,) = agente.resolve(_pool(Issue("i-1", "a", "b"))).proposals

    assert p.tipo == "NAO_SEI"
    assert len(cliente.chamadas) == 1, "não devia ter tentado de novo"


def test_confianca_ALTA_sem_evidencia_e_REBAIXADA_e_nao_descartada():
    """A hipótese ainda ajuda, com o peso certo. É regra do PRODUTO — vale na
    conciliação e no `swe` —, por isso mora no parser genérico."""
    agente = construir_agente(
        _decl(), FakeLLMClient([_texto("BUG", evidencia=(), confianca="ALTA")])
    )

    (p,) = agente.resolve(_pool(Issue("i-1", "a", "b"))).proposals

    assert p.tipo == "BUG"
    assert p.confianca is Confidence.BAIXA


# -- ferramentas: o RECORTE -------------------------------------------------


def test_o_agente_recebe_so_as_ferramentas_que_DECLARA():
    """Sem o recorte, acrescentar uma ferramenta a um domínio mudaria o custo e
    o comportamento de todo agente dele, sem ninguém pedir."""
    agente = construir_agente(
        _decl(ferramentas=("contar_palavras",)),
        FakeLLMClient([_texto("BUG")]),
        _contar_palavras(),
    )

    assert agente.tools.names() == ("contar_palavras",)


def test_ferramenta_INEXISTENTE_e_recusada_na_construcao():
    with pytest.raises(ValueError, match="ferramenta inexistente"):
        construir_agente(
            _decl(ferramentas=("nao_existe",)),
            FakeLLMClient([]),
            _contar_palavras(),
        )


def test_sem_declarar_ferramenta_o_agente_fica_SEM_nenhuma():
    agente = construir_agente(_decl(), FakeLLMClient([]), _contar_palavras())

    assert agente.tools.names() == ()


def test_a_ferramenta_declarada_FUNCIONA_no_laco():
    chamada = LLMResponse(
        text="",
        tool_calls=[ToolCall(id="t", name="contar_palavras", arguments={"texto": "a b c"})],
        cost=Cost(input_tokens=10, output_tokens=5, calls=1),
    )
    agente = construir_agente(
        _decl(ferramentas=("contar_palavras",)),
        FakeLLMClient([chamada, _texto("BUG")]),
        _contar_palavras(),
    )

    (p,) = agente.resolve(_pool(Issue("i-1", "a", "b"))).proposals

    assert p.tipo == "BUG"


# -- o que a declaração RECUSA ---------------------------------------------


def test_o_rotulo_de_abstencao_NO_vocabulario_e_recusado():
    """A invariante do P6.86, agora estrutural.

    No `swe`, `DUVIDA` era tipo E "não sei" ao mesmo tempo: 16 de 50 casos
    saíam do denominador da precisão. Lá a colisão foi descoberta MEDINDO;
    aqui é recusada na construção.
    """
    with pytest.raises(ValueError, match="rótulo de abstenção E"):
        _decl(tipos=("BUG", "DUVIDA"), abstem_com="DUVIDA")


def test_prompt_que_NAO_interpola_nada_e_recusado():
    """Todo item receberia o mesmo texto, e o agente responderia sem ler o
    item — gastando por item e decidindo sem ele."""
    with pytest.raises(ValueError, match="não interpola"):
        _decl(prompt="classifique esta issue")


def test_campo_AUSENTE_no_payload_falha_ALTO_e_nomeia_o_que_falta():
    """Um `defaultdict` que devolvesse vazio produziria prompt com buracos
    silenciosos, e o modelo responderia sobre um item que não leu inteiro."""
    agente = construir_agente(_decl(prompt="{titulo} {inexistente}"), FakeLLMClient([]))

    with pytest.raises(KeyError, match="disponíveis"):
        agente.resolve(_pool(Issue("i-1", "a", "b")))


def test_payload_NAO_interpolavel_diz_o_porque():
    agente = construir_agente(_decl(), FakeLLMClient([]))
    pool = WorkSet(items=(WorkItem(id="i-1", kind="issue", payload="uma string"),))

    with pytest.raises(TypeError, match="dataclass ou um dict"):
        agente.resolve(pool)


def test_vocabulario_VAZIO_e_recusado():
    with pytest.raises(ValueError, match="sem vocabulário"):
        _decl(tipos=())


def test_agente_sem_KIND_e_recusado():
    with pytest.raises(ValueError, match="`kind`"):
        _decl(kind="  ")


# -- o cliente de validação e o registro ------------------------------------


def test_o_cliente_de_validacao_se_recusa_a_FALAR_com_modelo():
    """Ele existe para checar declaração, não para executar. Se alguém o
    executasse, o erro precisa dizer isso — e não virar uma chamada de rede."""
    from orchestrator.agent.declarado import ClienteDeValidacao

    with pytest.raises(RuntimeError, match="não fala com modelo"):
        ClienteDeValidacao().complete("", [], [])


def test_o_agente_construido_HERDA_o_registro_LIGADO_do_dominio():
    """O defeito mais caro que este arquivo já escondeu.

    `construir_agente` recortava as ferramentas declaradas com
    `ToolRegistry([registro.spec(n) for n in ...])`, que perde o contexto. Todo
    agente composto sobre um domínio ligado a dados saía com um registro
    DESLIGADO: `call` devolvia "registro não ligado" em vez de levantar, o laço
    seguia, o modelo insistia, e a conta crescia sem sintoma nenhum.

    Nenhum teste viu porque todos usam `FakeLLMClient`, que nunca pede
    ferramenta. Foi encontrado lendo o código para escrever a tela.
    """
    ligado = _contar_palavras().com_contexto("os dados")

    agente = construir_agente(_decl(ferramentas=("contar_palavras",)), FakeLLMClient([]), ligado)

    assert agente.tools.ligado
    assert agente.tools.names() == ("contar_palavras",)


def test_o_agente_construido_sobre_um_CATALOGO_continua_desligado():
    """O outro sentido: construir para VALIDAR não pode ligar nada a dados que
    não existem. É o que `Catalogo.__post_init__` faz na importação."""
    agente = construir_agente(
        _decl(ferramentas=("contar_palavras",)), FakeLLMClient([]), _contar_palavras()
    )

    assert not agente.tools.ligado


def test_o_resolver_DECLARA_com_que_modelo_roda():
    """A borda precisa precificar CADA linha da tabela de custo com o modelo
    daquela linha. Sem isto ela converte tudo com um modelo só — medido contra
    uma API real: um bloco declarado em `claude-haiku-4-5` apareceu com
    4.494.000 µ¢, que é preço de opus, 5x o que a chamada deveria custar.

    Declarado no RESOLVER e não numa tabela de nomes na borda, pela mesma razão
    que `consome`, `produz` e `payloads`: a lista paralela apodrece no dia em
    que alguém escreve o próximo resolver.
    """
    from orchestrator.agent.declarado import AgenteDeclarado, construir_agente
    from orchestrator.agent.llm import FakeLLMClient

    declarado = AgenteDeclarado(
        name="triador",
        system="classifique",
        kind="issue",
        prompt="{titulo}",
        tipos=("BUG",),
        abstem_com="NAO_SEI",
        model="claude-haiku-4-5",
    )

    agente = construir_agente(declarado, FakeLLMClient([], model="claude-opus-5"))

    assert agente.describe().model == "claude-haiku-4-5"


def test_um_resolver_que_NAO_fala_com_modelo_declara_vazio():
    """Regra não tem modelo, e vazio é a resposta certa — não o padrão do
    servidor, que faria uma linha de 0 µ¢ parecer precificada."""
    from orchestrator.kernel.cost import CostClass
    from orchestrator.kernel.resolver import ResolverDescription

    d = ResolverDescription(name="L1", cost_class=CostClass.REGRA, summary="x")

    assert d.model == ""
