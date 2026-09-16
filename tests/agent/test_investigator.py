import json

import pytest

from orchestrator.agent.investigator import SYSTEM, Investigator
from orchestrator.agent.llm import FakeLLMClient, LLMResponse, ToolCall
from orchestrator.agent.proposal import Confidence, Proposal, TraceKind
from orchestrator.agent.tools import TOOL_SCHEMAS, ToolContext
from orchestrator.kernel.cost import _PRECOS, Cost, CostClass
from orchestrator.models import Divergence, divergencias, pool
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


# Constantes usadas pelos testes de Resolver abaixo — reaproveitam a mesma
# resposta válida e o mesmo contexto que os testes acima já montavam inline.
CONTEXTO_DE_TESTE = _ctx()
RESPOSTA_VALIDA = LLMResponse(text=_proposta_json(), tool_calls=[], cost=Cost(calls=1))


def test_investigador_e_um_resolver_da_classe_agente():
    inv = Investigator(client=FakeLLMClient(respostas=[]), context=CONTEXTO_DE_TESTE)

    assert inv.cost_class is CostClass.AGENTE
    assert inv.describe().name == "investigador"


def test_resolve_recebe_o_workset_e_devolve_propostas_sem_matches():
    # O agente propõe; nunca resolve. `matches` vazio não é detalhe de
    # implementação, é a invariante do produto.
    pares = generate_clean_pairs(seed=2, n=1)
    inv = Investigator(
        client=FakeLLMClient(respostas=[RESPOSTA_VALIDA] * 4),
        context=CONTEXTO_DE_TESTE,
    )
    work = pool(bank=[pares[0].bank], ledger=[])

    saida = inv.resolve(work)

    assert saida.resolutions == []
    assert len(saida.proposals) == 1
    assert saida.cost.calls >= 1


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

    # Sem checar o tipo, uma abstenção também satisfaria a asserção de
    # confiança BAIXA — e o teste deixaria de distinguir "rebaixada" de
    # "rejeitada", que é exatamente o que o nome dele promete.
    assert out.proposals[0].confianca is Confidence.BAIXA
    assert out.proposals[0].tipo is DivergenceType.RETENCAO_IMPOSTO


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
    # Um timeout num item nao pode custar a conciliacao inteira. A mensagem
    # injetada aqui NÃO menciona "API" de propósito: a asserção precisa valer
    # pelo prefixo que o próprio código escreve, não porque o texto do teste
    # contém a palavra que o teste depois procura.
    class _ClienteQueFalha:
        model = "claude-opus-5"

        def complete(self, system, messages, tools):
            raise RuntimeError("o servidor caiu")

    out = Investigator(client=_ClienteQueFalha(), context=_ctx()).investigate([_div()])

    assert out.proposals[0].tipo is DivergenceType.NAO_IDENTIFICADO
    assert out.proposals[0].explicacao.lower().startswith("falha de api ao investigar")
    assert any(e.kind == "erro" for e in out.proposals[0].trace)
    # A saída por erro era o único caminho de retorno sem evento "outcome"
    # terminal — um consumidor não podia contar com "o último evento é
    # outcome" para nenhuma proposta.
    assert out.proposals[0].trace[-1].kind == "outcome"


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

    # I2: o rastro precisa carregar ARGUMENTOS *e* RETORNO de cada ferramenta
    # — sem o retorno, uma auditoria não consegue saber o que a ferramenta
    # respondeu, só o que foi pedido.
    evento_tool = next(e for e in p.trace if e.kind == TraceKind.TOOL)
    assert evento_tool.detail["argumentos"] == {"bruto": 100000, "aliquota_bp": 500}
    assert evento_tool.detail["resultado"] == 5000


def test_modelo_sem_preco_falha_na_construcao():
    # Não é abstenção, é erro de configuração: sem preço o custo por
    # divergência fica incalculável, e ele é a métrica central do produto.
    class _SemPreco:
        model = "modelo-inexistente"

        def complete(self, system, messages, tools):
            raise AssertionError("não deveria chegar aqui")

    with pytest.raises(ValueError):
        Investigator(client=_SemPreco(), context=_ctx())


def test_evidencia_que_nao_e_lista_nao_vira_lista_de_caracteres():
    # Medido antes da guarda: "l1: bruto 100" virava 13 strings de um
    # caractere, evidência "não vazia" o bastante para a confiança ALTA passar.
    ruim = json.dumps(
        {
            "tipo": "RETENCAO_IMPOSTO",
            "explicacao": "ISS",
            "evidencia": "l1: bruto 100",
            "confianca": "ALTA",
            "acao_sugerida": "conciliar",
        }
    )
    cliente = FakeLLMClient(
        [LLMResponse(text=ruim, tool_calls=[], cost=Cost(calls=1))] * 4
    )
    inv = Investigator(client=cliente, context=_ctx(), max_tentativas_formato=2)

    p = inv.investigate([_div()]).proposals[0]

    assert p.tipo is DivergenceType.NAO_IDENTIFICADO
    assert p.evidencia == []


def test_resposta_malformada_nao_derruba_o_lote_inteiro():
    # `investigate` não tem try próprio: uma exceção escapando de uma
    # divergência levaria as outras junto.
    ruim = json.dumps(
        {"tipo": "ESTORNO", "explicacao": "x", "evidencia": 5,
         "confianca": "MEDIA", "acao_sugerida": "y"}
    )
    cliente = FakeLLMClient(
        [LLMResponse(text=ruim, tool_calls=[], cost=Cost(calls=1))] * 12
    )
    inv = Investigator(client=cliente, context=_ctx(), max_tentativas_formato=2)

    out = inv.investigate([_div("d1"), _div("d2")])

    assert len(out.proposals) == 2


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


# ---------------------------------------------------------------------------
# CRITICAL 1 — o orçamento padrão precisa sobreviver a um turno de verdade.
# ---------------------------------------------------------------------------


def test_orcamento_padrao_admite_um_turno_realista_em_todo_modelo_precificado():
    # Antes desta guarda: 100_000 µ¢ pagava só uma fração de UM turno em
    # QUALQUER modelo da tabela — a primeira chamada já estourava o
    # orçamento, e uma avaliação ao vivo gastaria dinheiro e devolveria 100%
    # de abstenção nos três modelos, sem produzir proposta nenhuma. O cálculo
    # abaixo deriva do PRÓPRIO prompt (SYSTEM + TOOL_SCHEMAS): se o prompt
    # crescer ou a tabela de preços mudar, este teste quebra sozinho.
    overhead_chars = len(SYSTEM) + len(json.dumps(TOOL_SCHEMAS))
    tokens_entrada = overhead_chars // 4  # heurística grosseira: ~4 chars/token
    turno_realista = Cost(input_tokens=tokens_entrada, output_tokens=200, calls=1)

    padrao = Investigator.budget_microcents
    for modelo in _PRECOS:
        custo = turno_realista.microcents(modelo)
        assert custo <= padrao, (
            f"orçamento padrão ({padrao} µ¢) não cobre um turno realista em "
            f"{modelo} ({custo} µ¢)"
        )


# ---------------------------------------------------------------------------
# I1 — orçamento por execução, além do orçamento por divergência.
# ---------------------------------------------------------------------------


def test_orcamento_total_da_execucao_interrompe_o_restante():
    resposta = LLMResponse(
        text=_proposta_json(), tool_calls=[], cost=Cost(input_tokens=100, calls=1)
    )
    cliente = FakeLLMClient([resposta, resposta, resposta])
    inv = Investigator(client=cliente, context=_ctx(), budget_total_microcents=1)

    out = inv.investigate([_div("d1"), _div("d2"), _div("d3")])

    # O teto é checado ANTES de cada item, contra o total acumulado ATÉ o
    # item anterior — o primeiro roda porque o total começa em zero.
    assert len(cliente.chamadas) == 1
    assert out.proposals[0].tipo is DivergenceType.RETENCAO_IMPOSTO
    for p in out.proposals[1:]:
        assert p.tipo is DivergenceType.NAO_IDENTIFICADO
        assert "orçamento" in p.explicacao.lower()


# ---------------------------------------------------------------------------
# I3 — acao_sugerida tem vocabulário fechado.
# ---------------------------------------------------------------------------


def test_acao_sugerida_fora_do_vocabulario_e_rebaixada_para_investigar_manual():
    ruim = json.dumps(
        {
            "tipo": "RETENCAO_IMPOSTO",
            "explicacao": "ISS retido",
            "evidencia": ["l1"],
            "confianca": "MEDIA",
            "acao_sugerida": "texto livre que o modelo inventou",
        }
    )
    cliente = FakeLLMClient([LLMResponse(text=ruim, tool_calls=[], cost=Cost(calls=1))])
    inv = Investigator(client=cliente, context=_ctx())

    p = inv.investigate([_div()]).proposals[0]

    assert p.acao_sugerida == "investigar_manual"


@pytest.mark.parametrize("acao", ["conciliar_com(l1,l2)", "ajustar(500)", "investigar_manual"])
def test_acao_sugerida_do_vocabulario_e_preservada(acao):
    valida = json.dumps(
        {
            "tipo": "RETENCAO_IMPOSTO",
            "explicacao": "ISS retido",
            "evidencia": ["l1"],
            "confianca": "MEDIA",
            "acao_sugerida": acao,
        }
    )
    cliente = FakeLLMClient([LLMResponse(text=valida, tool_calls=[], cost=Cost(calls=1))])
    inv = Investigator(client=cliente, context=_ctx())

    p = inv.investigate([_div()]).proposals[0]

    assert p.acao_sugerida == acao


# ---------------------------------------------------------------------------
# I4 — cerca de markdown em volta do JSON não pode custar um turno de retry.
# ---------------------------------------------------------------------------


def test_resposta_envolta_em_cerca_markdown_ainda_e_interpretada():
    envolto = f"```json\n{_proposta_json()}\n```"
    cliente = FakeLLMClient([LLMResponse(text=envolto, tool_calls=[], cost=Cost(calls=1))])
    inv = Investigator(client=cliente, context=_ctx())

    p = inv.investigate([_div()]).proposals[0]

    assert p.tipo is DivergenceType.RETENCAO_IMPOSTO
    assert len(cliente.chamadas) == 1  # não deveria ter gastado um turno de retry


def test_resposta_envolta_em_cerca_sem_linguagem_tambem_e_interpretada():
    envolto = f"```\n{_proposta_json()}\n```"
    cliente = FakeLLMClient([LLMResponse(text=envolto, tool_calls=[], cost=Cost(calls=1))])
    inv = Investigator(client=cliente, context=_ctx())

    p = inv.investigate([_div()]).proposals[0]

    assert p.tipo is DivergenceType.RETENCAO_IMPOSTO


# ---------------------------------------------------------------------------
# CRITICAL 2 — o laço precisa falar o protocolo de tool_use/tool_result.
# ---------------------------------------------------------------------------


def test_turno_so_com_ferramenta_nao_produz_assistente_vazio():
    # Defeito 1: quando o modelo só pede ferramenta, resposta.text é "".
    # Mandar isso como conteúdo do turno do assistente é mensagem vazia, e a
    # API real rejeita mensagem de assistente vazia com 400.
    cliente = FakeLLMClient(
        [
            LLMResponse(
                text="",
                tool_calls=[
                    ToolCall(id="t1", name="historico_fornecedor", arguments={"fornecedor": "X"})
                ],
                cost=Cost(calls=1),
            ),
            LLMResponse(text=_proposta_json(), tool_calls=[], cost=Cost(calls=1)),
        ]
    )
    inv = Investigator(client=cliente, context=_ctx())

    inv.investigate([_div()])

    segunda_chamada = cliente.chamadas[1]["messages"]
    assistente = next(m for m in segunda_chamada if m["role"] == "assistant")
    assert assistente["content"] != ""


def test_resultado_de_ferramenta_volta_como_tool_result_com_id_casado():
    # Defeito 2: o resultado precisa voltar como bloco `tool_result` casado
    # pelo `tool_use_id` da chamada que ele responde — não como texto solto
    # que não referencia chamada nenhuma.
    cliente = FakeLLMClient(
        [
            LLMResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="tool-abc",
                        name="calcular_retencao",
                        arguments={"bruto": 100000, "aliquota_bp": 500},
                    )
                ],
                cost=Cost(calls=1),
            ),
            LLMResponse(text=_proposta_json(), tool_calls=[], cost=Cost(calls=1)),
        ]
    )
    inv = Investigator(client=cliente, context=_ctx())

    inv.investigate([_div()])

    segunda_chamada = cliente.chamadas[1]["messages"]
    msg_resultado = segunda_chamada[-1]
    assert msg_resultado["role"] == "user"
    assert isinstance(msg_resultado["content"], list)
    assert msg_resultado["content"][0]["type"] == "tool_result"
    assert msg_resultado["content"][0]["tool_use_id"] == "tool-abc"
    assert "5000" in msg_resultado["content"][0]["content"]


def test_multiplas_chamadas_de_ferramenta_voltam_em_uma_unica_mensagem():
    # Espalhar resultados de ferramenta em várias mensagens de usuário ensina
    # o modelo, silenciosamente, a parar de pedir ferramentas em paralelo.
    cliente = FakeLLMClient(
        [
            LLMResponse(
                text="",
                tool_calls=[
                    ToolCall(id="t1", name="historico_fornecedor", arguments={"fornecedor": "A"}),
                    ToolCall(id="t2", name="historico_fornecedor", arguments={"fornecedor": "B"}),
                ],
                cost=Cost(calls=1),
            ),
            LLMResponse(text=_proposta_json(), tool_calls=[], cost=Cost(calls=1)),
        ]
    )
    inv = Investigator(client=cliente, context=_ctx())

    inv.investigate([_div()])

    segunda_chamada = cliente.chamadas[1]["messages"]
    mensagens_de_resultado = [
        m for m in segunda_chamada if m["role"] == "user" and isinstance(m["content"], list)
    ]
    assert len(mensagens_de_resultado) == 1
    assert len(mensagens_de_resultado[0]["content"]) == 2
    ids = {b["tool_use_id"] for b in mensagens_de_resultado[0]["content"]}
    assert ids == {"t1", "t2"}


def test_interpretar_proposta_e_funcao_de_modulo_reusavel():
    """O parsing da proposta precisa ser reusável fora do Investigator.

    O investigador movido a assinatura (eval/assinatura.py) roda um laço
    diferente mas tem que produzir EXATAMENTE a mesma Proposal a partir do
    mesmo JSON. Duplicar o parsing significaria dois caminhos divergindo em
    silêncio no dia em que um deles ganhasse uma guarda nova.
    """
    from orchestrator.agent.investigator import interpretar_proposta

    texto = (
        '{"tipo":"DEFASAGEM_TEMPORAL","explicacao":"liquidou depois",'
        '"evidencia":["b1: 2026-01-05"],"confianca":"MEDIA",'
        '"acao_sugerida":"conciliar_com(l1)"}'
    )

    p = interpretar_proposta("d-1", texto, Cost.zero(), [])

    assert p is not None
    assert p.divergence_id == "d-1"
    assert p.tipo is DivergenceType.DEFASAGEM_TEMPORAL
    assert p.confianca is Confidence.MEDIA
    assert p.evidencia == ["b1: 2026-01-05"]
    assert p.acao_sugerida == "conciliar_com(l1)"


def test_descrever_divergencia_e_funcao_de_modulo_reusavel():
    """A entrada do agente também precisa ser compartilhada.

    Se os dois caminhos montarem o texto da divergência por conta própria, o
    agente por assinatura estaria sendo avaliado sobre uma entrada diferente
    da que o caminho pago envia — e a comparação entre eles, que é o motivo
    de existir os dois, não valeria nada.
    """
    import json

    from orchestrator.agent.investigator import descrever_divergencia
    from orchestrator.agent.tools import ToolContext
    from orchestrator.models import Divergence
    from orchestrator.synth.generator import generate_clean_pairs

    pares = generate_clean_pairs(seed=2, n=1)
    ctx = ToolContext(bank=[pares[0].bank], ledger=[pares[0].ledger])
    d = Divergence(
        id="d-1",
        bank_ids=frozenset({pares[0].bank.id}),
        ledger_ids=frozenset(),
    )

    dados = json.loads(descrever_divergencia(ctx, d))

    assert dados["divergencia_id"] == "d-1"
    assert [e["id"] for e in dados["lancamentos_bancarios"]] == [pares[0].bank.id]
    assert dados["lancamentos_contabeis"] == []


# ---------------------------------------------------------------------------
# Idempotência — a guarda contra reinvestigar o que já está na fila.
# ---------------------------------------------------------------------------


def test_divergencia_ja_proposta_nao_chama_o_modelo_de_novo():
    """Idempotência do Tier 1, aplicada à chamada mais cara do sistema.

    O agente é classe AGENTE e o revisor é HUMANO, então o agente roda ANTES
    em toda passagem. Sem esta guarda, a passagem 2 reinvestigaria tudo o que
    a passagem 1 já investigou — e pagaria de novo por respostas que já estão
    na fila.
    """
    from orchestrator.review.fila import Fila

    pares = generate_clean_pairs(seed=2, n=1)
    work = pool(bank=[pares[0].bank], ledger=[])
    ja_proposta = divergencias(work)[0]

    fila = Fila.vazia()
    fila.gravar_proposta(
        Proposal(
            divergence_id=ja_proposta.id,
            tipo=DivergenceType.DEFASAGEM_TEMPORAL,
            explicacao="da passagem anterior",
            evidencia=["e"],
            confianca=Confidence.MEDIA,
            acao_sugerida="conciliar_com(l1)",
        )
    )

    class _ClienteQueAcusa:
        model = "claude-haiku-4-5"

        def complete(self, system, messages, tools):
            raise AssertionError("o agente reinvestigou o que já estava na fila")

    saida = Investigator(
        client=_ClienteQueAcusa(), context=CONTEXTO_DE_TESTE, fila=fila
    ).resolve(work)

    assert len(saida.proposals) == 1
    assert saida.proposals[0].explicacao == "da passagem anterior"
    assert saida.cost.calls == 0


def test_divergencia_sem_proposta_na_fila_e_investigada_normalmente():
    """A guarda precisa ser seletiva por id, não um interruptor de tudo-ou-nada.

    Uma fila que cobre A mas não B: A vem da fila, B é investigado de
    verdade. Um guard que só é exercitado quando a fila cobre 100% do lote
    não testa o caso em que ele de fato precisa discriminar.
    """
    from orchestrator.review.fila import Fila

    fila = Fila.vazia()
    fila.gravar_proposta(
        Proposal(
            divergence_id="a",
            tipo=DivergenceType.DEFASAGEM_TEMPORAL,
            explicacao="da passagem anterior",
            evidencia=["e"],
            confianca=Confidence.MEDIA,
            acao_sugerida="conciliar_com(l1)",
        )
    )

    cliente = FakeLLMClient([RESPOSTA_VALIDA])
    inv = Investigator(client=cliente, context=CONTEXTO_DE_TESTE, fila=fila)

    out = inv.investigate([_div("a"), _div("b")])

    assert len(out.proposals) == 2
    por_id = {p.divergence_id: p for p in out.proposals}
    assert por_id["a"].explicacao == "da passagem anterior"
    assert por_id["b"].tipo is DivergenceType.RETENCAO_IMPOSTO
    # só "b" gerou chamada ao modelo
    assert len(cliente.chamadas) == 1
    assert out.cost.calls == 1


def test_proposta_guardada_com_custo_historico_nao_entra_na_conta_desta_passagem():
    """Regressão do CRITICAL apontado na revisão: `serial.py` persiste os
    cinco campos de `Cost`, então uma proposta vinda do disco carrega o
    gasto REAL da investigação original. Somar esse custo em `total` faria
    o teto por execução estourar sobre gasto histórico — de uma passagem
    que não chamou o modelo nenhuma vez — e inflaria `agent_cost_microcents`
    com dinheiro já contado numa execução anterior.
    """
    from orchestrator.review.fila import Fila

    custo_historico = Cost(input_tokens=90_000, output_tokens=20_000, calls=6)
    fila = Fila.vazia()
    fila.gravar_proposta(
        Proposal(
            divergence_id="a",
            tipo=DivergenceType.DEFASAGEM_TEMPORAL,
            explicacao="da passagem anterior",
            evidencia=["e"],
            confianca=Confidence.MEDIA,
            acao_sugerida="conciliar_com(l1)",
            cost=custo_historico,
        )
    )

    class _ClienteQueAcusa:
        model = "claude-haiku-4-5"

        def complete(self, system, messages, tools):
            raise AssertionError("o agente reinvestigou o que já estava na fila")

    inv = Investigator(client=_ClienteQueAcusa(), context=CONTEXTO_DE_TESTE, fila=fila)
    out = inv.investigate([_div("a")])

    # A passagem não gastou nada: nenhuma chamada ao modelo, custo agregado
    # zerado — mesmo a proposta guardada carregando um custo histórico alto.
    assert out.cost.calls == 0
    assert out.cost.microcents(inv.client.model) == 0
    # O registro de auditoria da proposta em si continua intacto: ela ainda
    # carrega o custo de quando foi de fato investigada.
    assert out.proposals[0].cost == custo_historico
