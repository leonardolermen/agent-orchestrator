import json

import pytest

from orchestrator.agent.llm import ToolCall
from orchestrator.grill.ferramentas import (
    NOMES,
    Pergunta,
    PropostaBruta,
    Recusa,
    _nomes_de_regra,
    esquemas,
    interpretar,
)


def test_sao_exatamente_tres_ferramentas():
    assert tuple(e["name"] for e in esquemas()) == NOMES


def _bloco_do_schema() -> dict:
    """O sub-schema de UM bloco, de dentro de `etapas`."""
    proposta = next(e for e in esquemas() if e["name"] == "propor_workflow")
    etapa = proposta["input_schema"]["properties"]["etapas"]["items"]
    return etapa["properties"]["blocos"]["items"]


def test_enum_de_regra_vem_do_catalogo():
    # Uma lista literal aqui e outra no catálogo divergiriam, e o modelo
    # poderia propor algo que `construir_composicao` não conhece — ou nunca
    # ficar sabendo de uma regra nova.
    regra = _bloco_do_schema()["properties"]["regra"]
    assert regra["properties"]["nome"]["enum"] == _nomes_de_regra()


def test_o_AGENTE_nao_sai_de_lista_nenhuma():
    """Ele deixou de ser item de cardápio e passou a ser DECLARADO: nome,
    papel, kind, prompt e vocabulário são do parceiro. Um `enum` de agentes
    aqui era exatamente o que fazia o chat só conseguir propor os três prontos
    do catálogo."""
    agente = _bloco_do_schema()["properties"]["agente"]
    assert "enum" not in agente["properties"]["name"]
    assert set(agente["required"]) == {
        "name",
        "system",
        "kind",
        "prompt",
        "tipos",
        "abstem_com",
    }


# `test_o_nome_da_entrada_bate_com_a_chave_do_catalogo` não migra: ela travava
# uma classe de defeito específica do `CATALOGO` do grill — um `dict[str,
# EntradaCatalogo]` cuja CHAVE podia divergir do `.nome` do valor. O catálogo
# PLANO (`Catalogo.bloco`, Task 1) não tem essa segunda fonte de verdade: ele
# procura `r.nome`/`a.name` diretamente nas tuplas `regras`/`agentes`, então a
# divergência que este teste travava deixou de ser uma forma possível de errar.


def test_propor_workflow_nao_aceita_id():
    # O id vem do --id da CLI, validado ANTES do primeiro turno. Deixar o
    # modelo propor um criaria duas fontes de verdade para a mesma chave, e a
    # do modelo só seria conhecida no fim — tarde para recusar sem
    # desperdiçar a conversa do parceiro.
    proposta = next(e for e in esquemas() if e["name"] == "propor_workflow")
    assert "id" not in proposta["input_schema"]["properties"]


def test_descricao_da_proposta_lista_os_parametros_de_cada_resolver():
    # JSON Schema não expressa "as chaves permitidas dependem do valor de
    # `nome`" sem oneOf combinatório. O modelo aprende isso pela descrição.
    proposta = next(e for e in esquemas() if e["name"] == "propor_workflow")
    texto = proposta["description"]
    assert "max_cents" in texto
    assert "max_group_size" in texto
    assert "L1" in texto


def test_esquemas_sao_serializaveis():
    json.dumps(esquemas(), ensure_ascii=False)


def test_interpretar_pergunta():
    r = interpretar(ToolCall(id="1", name="perguntar", arguments={"texto": "qual a data?"}))
    assert r == Pergunta(texto="qual a data?")


def test_interpretar_proposta():
    r = interpretar(
        ToolCall(
            id="1",
            name="propor_workflow",
            arguments={
                "nome": "Conciliação Acme",
                "justificativa": "consolidam por fornecedor",
                "etapas": [
                    {
                        "nome": "casar",
                        "blocos": [
                            {"tipo": "regra", "regra": {"nome": "L1"}},
                            {
                                "tipo": "regra",
                                "regra": {"nome": "L2", "parametros": {"max_cents": 10}},
                            },
                        ],
                    }
                ],
            },
        )
    )
    assert isinstance(r, PropostaBruta)
    assert r.nome == "Conciliação Acme"
    (etapa,) = r.etapas
    assert etapa.nome == "casar"
    assert etapa.blocos[0].nome == "L1"
    assert etapa.blocos[0].parametros == {}
    assert etapa.blocos[1].parametros == {"max_cents": 10}


def test_a_proposta_aceita_DUAS_etapas_com_blocos_de_tipos_diferentes():
    """A forma que o chat não sabia propor: um degrau que transforma e outro
    que consome o que ele produziu."""
    from orchestrator.authoring.composicao import BlocoRegra, BlocoTarefa

    bruta = interpretar(
        ToolCall(
            id="t",
            name="propor_workflow",
            arguments={
                "nome": "Redação",
                "justificativa": "porque sim",
                "etapas": [
                    {
                        "nome": "escrever",
                        "blocos": [
                            {
                                "tipo": "regra",
                                "regra": {"nome": "filtro", "parametros": {"kind": "issue"}},
                            },
                            {
                                "tipo": "tarefa",
                                "tarefa": {
                                    "name": "escritor",
                                    "system": "escreva",
                                    "kind": "issue",
                                    "produz": "rascunho",
                                    "prompt": "Escreva sobre {titulo}",
                                },
                            },
                        ],
                    },
                    {
                        "nome": "revisar",
                        "blocos": [
                            {
                                "tipo": "agente",
                                "agente": {
                                    "name": "revisor",
                                    "system": "revise",
                                    "kind": "rascunho",
                                    "prompt": "Revise {rascunho}",
                                    "tipos": ["APROVADO", "REPROVADO"],
                                    "abstem_com": "NAO_SEI",
                                },
                            }
                        ],
                    },
                ],
                "entrega": ["rascunho"],
            },
        )
    )

    assert [e.nome for e in bruta.etapas] == ["escrever", "revisar"]
    primeira, segunda = bruta.etapas
    assert isinstance(primeira.blocos[0], BlocoRegra)
    assert isinstance(primeira.blocos[1], BlocoTarefa)
    assert primeira.blocos[1].declaracao.produz == "rascunho"
    assert segunda.blocos[0].declaracao.tipos == ("APROVADO", "REPROVADO")
    assert bruta.entrega == ("rascunho",)


def test_bloco_cujo_tipo_nao_traz_o_objeto_correspondente_e_RECUSADO():
    """A conferência que substitui a união discriminada — que não cabe no
    schema porque `oneOf` está fora da lista branca da Messages API. A recusa
    volta ao modelo como `is_error` e ele corrige no turno seguinte."""
    with pytest.raises(ValueError, match="tarefa"):
        interpretar(
            ToolCall(
                id="t",
                name="propor_workflow",
                arguments={
                    "nome": "x",
                    "justificativa": "y",
                    "etapas": [
                        {"nome": "e1", "blocos": [{"tipo": "tarefa", "agente": {"name": "z"}}]}
                    ],
                },
            )
        )


def test_o_parametro_de_regra_aceita_TEXTO_e_LISTA():
    """`ValorDeParametro` é `int | str | tuple[str, ...]` desde que as regras
    genéricas passaram a receber NOME DE CAMPO. A versão antiga recusava tudo
    que não fosse inteiro, e com isso o modelo não conseguia propor `filtro`,
    `condicao`, `tabela` nem `entrada` — os blocos genéricos inteiros."""
    bruta = interpretar(
        ToolCall(
            id="t",
            name="propor_workflow",
            arguments={
                "nome": "x",
                "justificativa": "y",
                "etapas": [
                    {
                        "nome": "e1",
                        "blocos": [
                            {
                                "tipo": "regra",
                                "regra": {
                                    "nome": "igualdade",
                                    "parametros": {
                                        "campos": ["documento", "valor"],
                                        "kind": "banco",
                                    },
                                },
                            }
                        ],
                    }
                ],
            },
        )
    )

    (bloco,) = bruta.etapas[0].blocos
    assert bloco.parametros == {"campos": ("documento", "valor"), "kind": "banco"}


def test_o_schema_NAO_usa_palavra_fora_da_lista_branca():
    """A lista branca é medida contra a Messages API (`_PALAVRAS_DE_SCHEMA`).
    `oneOf` derrubaria a requisição INTEIRA, e a primeira notícia seria uma
    entrevista falhando com dinheiro na mesa — o precedente é o `"minimum": 1`
    de 2026-09-16, que nenhum dos 620 testes de então viu. `minItems` entra na
    permissão porque os esquemas de hoje já o usam em produção."""
    from orchestrator.agent.tools.registry import _PALAVRAS_DE_SCHEMA

    permitidas = set(_PALAVRAS_DE_SCHEMA) | {"minItems"}

    def conferir(no, onde, dentro_de_properties=False):
        if isinstance(no, dict):
            for chave, valor in no.items():
                # As CHAVES de `properties` são nomes de campo, não palavras de
                # schema: quem é schema são os VALORES.
                if not dentro_de_properties:
                    assert chave in permitidas, f"{onde}.{chave} fora da lista branca"
                conferir(valor, f"{onde}.{chave}", dentro_de_properties=(chave == "properties"))
        elif isinstance(no, list):
            for i, item in enumerate(no):
                conferir(item, f"{onde}[{i}]")

    for e in esquemas():
        conferir(e["input_schema"], e["name"])


def test_interpretar_recusa():
    r = interpretar(
        ToolCall(
            id="1",
            name="fora_do_catalogo",
            arguments={
                "motivo": "é cartão, não extrato",
                "o_que_faltaria": "resolver de adquirente",
            },
        )
    )
    assert r == Recusa(motivo="é cartão, não extrato", o_que_faltaria="resolver de adquirente")


def test_interpretar_rejeita_ferramenta_desconhecida():
    with pytest.raises(ValueError, match="pensar"):
        interpretar(ToolCall(id="1", name="pensar", arguments={}))


def test_interpretar_rejeita_argumento_faltando():
    with pytest.raises(ValueError, match="texto"):
        interpretar(ToolCall(id="1", name="perguntar", arguments={}))


def test_interpretar_rejeita_pergunta_vazia():
    # Pergunta em branco travaria o laço esperando resposta a nada.
    with pytest.raises(ValueError, match="vazi"):
        interpretar(ToolCall(id="1", name="perguntar", arguments={"texto": "   "}))


def test_interpretar_rejeita_parametro_FLOAT():
    # Dinheiro e janelas são int. Um 10.5 aqui viraria float silencioso no
    # centavo — a invariante que o projeto inteiro protege. O que passou a ser
    # aceito é TEXTO e LISTA DE TEXTOS (nome de campo), nunca float.
    with pytest.raises(ValueError, match="inteiro, texto ou lista"):
        interpretar(
            ToolCall(
                id="1",
                name="propor_workflow",
                arguments={
                    "nome": "x",
                    "justificativa": "y",
                    "etapas": [
                        {
                            "nome": "e1",
                            "blocos": [
                                {
                                    "tipo": "regra",
                                    "regra": {"nome": "L2", "parametros": {"max_cents": 10.5}},
                                }
                            ],
                        }
                    ],
                },
            )
        )


def test_interpretar_rejeita_parametros_falsy_malformado():
    # `item.get("parametros") or {}` trocaria um `0`/`[]`/`False` malformado
    # por "sem parâmetros" em silêncio, sem nunca chegar no isinstance(dict)
    # que deveria rejeitar. O parceiro que pediu uma tolerância receberia o
    # default sem ninguém avisar.
    with pytest.raises(ValueError, match="objeto"):
        interpretar(
            ToolCall(
                id="1",
                name="propor_workflow",
                arguments={
                    "nome": "x",
                    "justificativa": "y",
                    "etapas": [
                        {
                            "nome": "e1",
                            "blocos": [
                                {"tipo": "regra", "regra": {"nome": "L2", "parametros": 0}}
                            ],
                        }
                    ],
                },
            )
        )


def test_parametro_BOOLEANO_continua_recusado():
    """`isinstance(True, int)` é True em Python: sem exclusão explícita,
    `max_cents=true` viraria 1 em silêncio."""
    with pytest.raises(ValueError, match="booleano"):
        interpretar(
            ToolCall(
                id="1",
                name="propor_workflow",
                arguments={
                    "nome": "x",
                    "justificativa": "y",
                    "etapas": [
                        {
                            "nome": "e1",
                            "blocos": [
                                {
                                    "tipo": "regra",
                                    "regra": {"nome": "L2", "parametros": {"max_cents": True}},
                                }
                            ],
                        }
                    ],
                },
            )
        )
