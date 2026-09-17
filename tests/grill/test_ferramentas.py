import json

import pytest

from orchestrator.agent.llm import ToolCall
from orchestrator.grill.ferramentas import (
    NOMES,
    Pergunta,
    PropostaBruta,
    Recusa,
    _nomes_disponiveis,
    esquemas,
    interpretar,
)


def test_sao_exatamente_tres_ferramentas():
    assert tuple(e["name"] for e in esquemas()) == NOMES


def test_enum_de_resolver_vem_do_catalogo():
    # Uma lista literal aqui e outra no catálogo divergiriam, e o modelo
    # poderia propor algo que `construir` não conhece — ou nunca ficar
    # sabendo de um resolver novo.
    proposta = next(e for e in esquemas() if e["name"] == "propor_workflow")
    item = proposta["input_schema"]["properties"]["resolvers"]["items"]
    assert item["properties"]["nome"]["enum"] == _nomes_disponiveis()


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
                "resolvers": [
                    {"nome": "L1"},
                    {"nome": "L2", "parametros": {"max_cents": 10}},
                ],
            },
        )
    )
    assert isinstance(r, PropostaBruta)
    assert r.nome == "Conciliação Acme"
    assert r.resolvers[0].nome == "L1"
    assert r.resolvers[0].parametros == {}
    assert r.resolvers[1].parametros == {"max_cents": 10}


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


def test_interpretar_rejeita_parametro_nao_inteiro():
    # Dinheiro e janelas são int. Um 10.5 aqui viraria float silencioso no
    # centavo — a invariante que o projeto inteiro protege.
    with pytest.raises(ValueError, match="inteiro"):
        interpretar(
            ToolCall(
                id="1",
                name="propor_workflow",
                arguments={
                    "nome": "x",
                    "justificativa": "y",
                    "resolvers": [{"nome": "L2", "parametros": {"max_cents": 10.5}}],
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
                    "resolvers": [{"nome": "L2", "parametros": 0}],
                },
            )
        )
