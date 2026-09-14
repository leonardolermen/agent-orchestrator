import json

from orchestrator.agent.investigator import Investigator
from orchestrator.agent.llm import FakeLLMClient, LLMResponse, ToolCall
from orchestrator.agent.proposal import Confidence, Cost
from orchestrator.agent.tools import ToolContext
from orchestrator.models import Divergence
from orchestrator.synth.generator import build_dataset, generate_clean_pairs
from orchestrator.taxonomy import DivergenceType


def _ctx() -> ToolContext:
    ds = build_dataset(generate_clean_pairs(seed=3, n=20), injections=[])
    return ToolContext(bank=ds.bank, ledger=ds.ledger)


def _div(id_: str = "d1") -> Divergence:
    return Divergence(id=id_, bank_ids=frozenset({"b00001"}), ledger_ids=frozenset())


def _proposta_json(tipo="RETENCAO_IMPOSTO", confianca="ALTA", evidencia=("l1: bruto 100",)):
    return json.dumps(
        {
            "tipo": tipo,
            "explicacao": "ISS retido na fonte",
            "evidencia": list(evidencia),
            "confianca": confianca,
            "acao_sugerida": "conciliar_com:l1",
        }
    )


def test_uma_divergencia_vira_uma_proposta():
    cliente = FakeLLMClient(
        [LLMResponse(text=_proposta_json(), tool_calls=[], cost=Cost(input_tokens=100, calls=1))]
    )
    inv = Investigator(client=cliente, context=_ctx())

    out = inv.investigate([_div()])

    assert len(out.proposals) == 1
    assert out.proposals[0].tipo is DivergenceType.RETENCAO_IMPOSTO
    assert out.proposals[0].divergence_id == "d1"


def test_ferramenta_pedida_e_executada_e_devolvida():
    cliente = FakeLLMClient(
        [
            LLMResponse(
                text="",
                tool_calls=[ToolCall(id="t1", name="calcular_retencao",
                                     arguments={"bruto": 100000, "aliquota_bp": 500})],
                cost=Cost(calls=1),
            ),
            LLMResponse(text=_proposta_json(), tool_calls=[], cost=Cost(calls=1)),
        ]
    )
    inv = Investigator(client=cliente, context=_ctx())

    out = inv.investigate([_div()])

    # o resultado da ferramenta precisa ter voltado para o modelo
    segunda_chamada = cliente.chamadas[1]["messages"]
    assert any("5000" in json.dumps(m) for m in segunda_chamada)
    assert len(out.proposals) == 1


def test_ferramenta_inexistente_vira_erro_para_o_modelo_nao_excecao():
    cliente = FakeLLMClient(
        [
            LLMResponse(text="", tool_calls=[ToolCall(id="t1", name="nao_existe", arguments={})],
                        cost=Cost(calls=1)),
            LLMResponse(text=_proposta_json(confianca="BAIXA", evidencia=()), tool_calls=[],
                        cost=Cost(calls=1)),
        ]
    )
    inv = Investigator(client=cliente, context=_ctx())

    out = inv.investigate([_div()])

    assert len(out.proposals) == 1
    assert any("nao_existe" in json.dumps(m) for m in cliente.chamadas[1]["messages"])


def test_json_invalido_vira_abstencao_e_nao_estoura():
    cliente = FakeLLMClient(
        [LLMResponse(text="isto não é json", tool_calls=[], cost=Cost(calls=1))]
        * 3
    )
    inv = Investigator(client=cliente, context=_ctx(), max_tentativas_formato=2)

    out = inv.investigate([_div()])

    assert out.proposals[0].tipo is DivergenceType.NAO_IDENTIFICADO
    assert out.proposals[0].confianca is Confidence.BAIXA


def test_tipo_fora_da_taxonomia_vira_abstencao():
    cliente = FakeLLMClient(
        [LLMResponse(text=_proposta_json(tipo="INVENTADO"), tool_calls=[], cost=Cost(calls=1))] * 3
    )
    inv = Investigator(client=cliente, context=_ctx(), max_tentativas_formato=2)

    out = inv.investigate([_div()])

    assert out.proposals[0].tipo is DivergenceType.NAO_IDENTIFICADO


def test_confianca_alta_sem_evidencia_e_rebaixada_nao_rejeitada():
    # O modelo às vezes afirma sem citar. Perder a proposta inteira seria pior
    # que registrá-la com a confiança que ela de fato merece.
    cliente = FakeLLMClient(
        [LLMResponse(text=_proposta_json(confianca="ALTA", evidencia=()), tool_calls=[],
                     cost=Cost(calls=1))]
    )
    inv = Investigator(client=cliente, context=_ctx())

    out = inv.investigate([_div()])

    assert out.proposals[0].confianca is Confidence.BAIXA


def test_laco_para_no_limite_de_turnos():
    pedido = LLMResponse(
        text="",
        tool_calls=[ToolCall(id="t", name="historico_fornecedor", arguments={"fornecedor": "X"})],
        cost=Cost(calls=1),
    )
    cliente = FakeLLMClient([pedido] * 10)
    inv = Investigator(client=cliente, context=_ctx(), max_turns=3)

    out = inv.investigate([_div()])

    assert len(cliente.chamadas) == 3
    assert out.proposals[0].tipo is DivergenceType.NAO_IDENTIFICADO


def test_orcamento_estourado_interrompe_e_abstem():
    caro = LLMResponse(
        text="",
        tool_calls=[ToolCall(id="t", name="historico_fornecedor", arguments={"fornecedor": "X"})],
        cost=Cost(input_tokens=1_000_000, calls=1),
    )
    cliente = FakeLLMClient([caro] * 10)
    inv = Investigator(client=cliente, context=_ctx(), budget_microcents=1)

    out = inv.investigate([_div()])

    assert out.proposals[0].tipo is DivergenceType.NAO_IDENTIFICADO
    assert "orçamento" in out.proposals[0].explicacao.lower()


def test_custo_total_agrega_o_de_cada_divergencia():
    cliente = FakeLLMClient(
        [LLMResponse(text=_proposta_json(), tool_calls=[],
                     cost=Cost(input_tokens=100, calls=1))] * 2
    )
    inv = Investigator(client=cliente, context=_ctx())

    out = inv.investigate([_div("d1"), _div("d2")])

    assert out.cost.calls == 2
    assert out.cost.input_tokens == 200


def test_erro_de_api_vira_abstencao_e_nao_derruba_o_processo():
    # Um timeout num item nao pode custar a conciliacao inteira.
    class _ClienteQueFalha:
        model = "claude-opus-5"

        def complete(self, system, messages, tools):
            raise RuntimeError("timeout da API")

    out = Investigator(client=_ClienteQueFalha(), context=_ctx()).investigate([_div()])

    assert out.proposals[0].tipo is DivergenceType.NAO_IDENTIFICADO
    assert "api" in out.proposals[0].explicacao.lower()
    assert any(e.kind == "erro" for e in out.proposals[0].trace)


def test_trace_registra_turno_ferramenta_e_desfecho():
    cliente = FakeLLMClient(
        [
            LLMResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="t1",
                        name="calcular_retencao",
                        arguments={"bruto": 100000, "aliquota_bp": 500},
                    )
                ],
                cost=Cost(calls=1),
            ),
            LLMResponse(text=_proposta_json(), tool_calls=[], cost=Cost(calls=1)),
        ]
    )

    p = Investigator(client=cliente, context=_ctx()).investigate([_div()]).proposals[0]

    tipos = [e.kind for e in p.trace]
    assert "entrada" in tipos
    assert "llm" in tipos
    assert "tool" in tipos
    assert tipos[-1] == "outcome"


def test_cada_divergencia_comeca_com_contexto_limpo():
    # Divergências não podem contaminar umas às outras: o histórico de uma não
    # entra no prompt da seguinte.
    cliente = FakeLLMClient(
        [LLMResponse(text=_proposta_json(), tool_calls=[], cost=Cost(calls=1))] * 2
    )
    inv = Investigator(client=cliente, context=_ctx())

    inv.investigate([_div("d1"), _div("d2")])

    assert len(cliente.chamadas[0]["messages"]) == len(cliente.chamadas[1]["messages"])
    assert "d2" in json.dumps(cliente.chamadas[1]["messages"])
    assert "d1" not in json.dumps(cliente.chamadas[1]["messages"])
