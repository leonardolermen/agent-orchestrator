"""A avaliação do `swe`: os dois braços, sem gastar um centavo.

`FakeLLMClient` no lugar do `AnthropicClient` — a mesma troca de uma linha que o
scaffold documenta. O que estes testes provam é a MONTAGEM: que os dois braços
diferem só na ferramenta, que a economia é medida por braço, e que o veredito
não afirma mais do que cinco casos autorizam.
"""

import json
from datetime import UTC, datetime

from orchestrator.agent.llm import FakeLLMClient, LLMResponse
from orchestrator.cli.execucao import avaliar as executar
from orchestrator.domains.swe import avaliacao
from orchestrator.kernel.cost import Cost

AGORA = datetime(2026, 9, 17, tzinfo=UTC)


# O prompt que o `AgentTask` monta é título + corpo. O título é único em cada
# caso, então o falso identifica o item por ele — e o gabarito sai do PRÓPRIO
# conjunto, não de uma cópia que envelheceria a cada caso novo.
from orchestrator.domains.swe.casos import CASOS

_POR_TITULO = {titulo: (cid, esperado) for cid, titulo, _, esperado, _ in CASOS}


class _ModeloFalso:
    """Responde JSON válido; opcionalmente pede a ferramenta no 1º turno."""

    model = "claude-haiku-4-5"

    def __init__(self, erra: frozenset[str] = frozenset(), pede_ferramenta: bool = True) -> None:
        # `erra` são ids que o falso responde ERRADO de propósito.
        self.erra = erra
        self.pede_ferramenta = pede_ferramenta

    def complete(self, system, messages, tools):
        texto = "".join(
            str(m.get("content")) for m in messages if m.get("role") == "user"
        )
        achado = next(
            ((c, e) for t, (c, e) in _POR_TITULO.items() if t in texto), None
        )
        assert achado, f"o falso não reconheceu a issue; texto={texto[:80]!r}"
        cid, esperado = achado

        # Primeiro turno com ferramenta disponível: pede a ferramenta. É a
        # forma medida na execução real — o modelo chamou em 5 de 5.
        if self.pede_ferramenta and tools and len(messages) == 1:
            from orchestrator.agent.llm import ToolCall

            return LLMResponse(
                text="",
                tool_calls=[
                    ToolCall(id="t1", name="contar_palavras", arguments={"texto": "a b"})
                ],
                cost=Cost(input_tokens=740, output_tokens=100, calls=1),
            )
        tipo = esperado
        if cid in self.erra:
            tipo = "FEATURE" if esperado != "FEATURE" else "BUG"
        return LLMResponse(
            text=json.dumps(
                {
                    "tipo": tipo,
                    "explicacao": "porque sim",
                    "evidencia": ["trecho"],
                    "confianca": "ALTA",
                }
            ),
            tool_calls=[],
            cost=Cost(input_tokens=858, output_tokens=152, calls=1),
        )



def _rodar(cliente):
    return executar(
        avaliacao.conjunto(),
        avaliacao.bracos(cliente),
        cliente,
        abstem_com=avaliacao.ABSTEM_COM,
        agora=AGORA,
    )


def test_o_conjunto_curado_e_estavel():
    """A versão é derivada do conteúdo; se alguém mexer nos casos, ela muda —
    e é isso que impede comparar um resultado de hoje com um de outra régua."""
    assert conjunto_versao() == conjunto_versao()
    assert len(avaliacao.conjunto()) == 50


def conjunto_versao():
    return avaliacao.conjunto().version


def test_a_data_de_curadoria_e_FIXA_e_nao_datetime_now():
    """Um `now()` no módulo produziria um conjunto que às vezes exclui a si
    mesmo, dependendo de quantos microssegundos o import levou."""
    primeiro = avaliacao.conjunto().cases[0].created_at
    segundo = avaliacao.conjunto().cases[0].created_at

    assert primeiro == segundo
    assert primeiro.tzinfo is not None


def test_os_dois_bracos_diferem_SO_na_ferramenta():
    """Variar prompt junto com ferramenta mediria as duas coisas de uma vez e
    não responderia nenhuma."""
    com, sem = avaliacao.bracos(FakeLLMClient(respostas=[]))

    assert com.workflow.stages[0].cascade[0].spec.system == (
        sem.workflow.stages[0].cascade[0].spec.system
    )
    assert com.workflow.stages[0].cascade[0].tools.names() == ("contar_palavras",)
    assert sem.workflow.stages[0].cascade[0].tools.names() == ()


def test_a_economia_sai_por_BRACO_e_o_sem_ferramenta_vem_vazio():
    """A verificação mais barata de que o braço sem ferramenta rodou mesmo sem
    ela: se `contar_palavras` aparecesse ali, os dois braços seriam o mesmo."""
    _, economias, _ = _rodar(_ModeloFalso())

    assert economias["com-ferramenta"].usos[0].nome == "contar_palavras"
    assert economias["sem-ferramenta"].usos == ()


def test_com_gabarito_perfeito_os_dois_bracos_acertam_tudo():
    resultado, _, _ = _rodar(_ModeloFalso())

    for label in ("com-ferramenta", "sem-ferramenta"):
        assert resultado.por_label()[label].proposal_precision == 1.0


def test_o_veredito_NAO_conclui_mais_do_que_cinco_casos_permitem():
    """Com cinco casos, um acerto vale 20 pontos. Dizer "a ferramenta não
    serve" a partir disso seria trocar um palpite por outro com aparência de
    medida — o texto tem de dizer isso."""
    resultado, economias, _ = _rodar(_ModeloFalso())

    saida = avaliacao.render(resultado, economias)

    assert "Com 50 casos, um acerto vale 2 pontos" in saida
    assert "indica direção, não decide" in saida


def test_a_ferramenta_aparece_como_CANDIDATO_quando_chamada_em_todo_item():
    _, economias, _ = _rodar(_ModeloFalso())

    (candidato,) = economias["com-ferramenta"].candidatos()
    assert candidato.itens_alcancados == 50


def test_modelo_que_erra_derruba_a_precisao_do_braco_certo():
    """Sanidade do arnês: se ele não distinguisse braço bom de ruim, todos os
    números acima seriam decoração."""
    resultado, _, _ = _rodar(_ModeloFalso(erra=frozenset({"I-11", "I-28"})))

    assert resultado.por_label()["com-ferramenta"].proposal_precision < 1.0


def test_o_veredito_sai_para_QUALQUER_par_de_bracos():
    """A primeira versão casava pelos rótulos `com-ferramenta`/`sem-ferramenta`,
    e quando os braços de tripulação entraram o veredito simplesmente não saiu
    — a ressalva sobre tamanho de amostra ficou ausente justamente no
    experimento mais fácil de sobreinterpretar.

    Ausência de ressalva lê-se como ausência de ressalva.
    """
    cliente = _ModeloFalso()
    resultado, economias, _ = executar(
        avaliacao.conjunto(),
        avaliacao.bracos_tripulacao(cliente),
        cliente,
        abstem_com=avaliacao.ABSTEM_COM,
        agora=AGORA,
    )

    saida = avaliacao.render(resultado, economias)

    assert "Com 50 casos" in saida
    assert "agente-sozinho" in saida or "tripulacao-2" in saida


def test_o_veredito_avisa_que_abstencao_a_mais_NAO_e_precisao_conquistada():
    """Medido ao vivo: a tripulação chegou a 100% de precisão abstendo em 40%
    dos casos, contra 20% do agente sozinho. Ler só a coluna de precisão faria
    parecer que ela ganhou."""
    from orchestrator.domains.swe.avaliacao import _veredito
    from orchestrator.evaluation.benchmark import BenchmarkArm, BenchmarkResult

    def m(precisao, abst, por_acerto):
        from orchestrator.evaluation.metrics import EvalMetrics

        return EvalMetrics(
            dataset_version="v", items_total=5, deterministic_rate=0.0,
            resolution_rate=0.0, false_positives=0, false_negatives=0,
            proposal_precision=precisao, abstention_rate=abst,
            microcents_total=1, microcents_per_item=1,
            microcents_per_correct_proposal=por_acerto, escalation_rate=0.0,
            api_failures=0, proposals_total=5, proposals_correct=3,
            proposals_abstained=2,
        )

    arm = BenchmarkArm(label="x", workflow=avaliacao.bracos(_ModeloFalso())[0].workflow)
    arm2 = BenchmarkArm(label="y", workflow=arm.workflow)
    r = BenchmarkResult(
        dataset_id="d", dataset_version="v", at=AGORA,
        arms=((arm, m(1.0, 0.4, 1000)), (arm2, m(1.0, 0.2, 400))),
    )

    assert "não foi arriscada, não precisão conquistada" in _veredito(r, {})
