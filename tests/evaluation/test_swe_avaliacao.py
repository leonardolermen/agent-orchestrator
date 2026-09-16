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


# O prompt que o `AgentTask` monta é título + corpo, SEM o id — então o modelo
# falso identifica o item pela marca distintiva de cada issue, do mesmo jeito
# que um modelo de verdade teria de fazer.
_MARCAS = {
    "NullPointerException": "I-1",
    "CSV": "I-2",
    "campo status": "I-3",
    "1.204,97": "I-4",
    "50 mil": "I-5",
}


class _ModeloFalso:
    """Responde JSON válido; opcionalmente pede a ferramenta no 1º turno."""

    model = "claude-haiku-4-5"

    def __init__(self, tipos: dict[str, str], pede_ferramenta: bool = True) -> None:
        self.tipos = tipos
        self.pede_ferramenta = pede_ferramenta

    def complete(self, system, messages, tools):
        texto = "".join(
            str(m.get("content")) for m in messages if m.get("role") == "user"
        )
        iid = next((v for marca, v in _MARCAS.items() if marca in texto), None)
        assert iid, f"o falso não reconheceu a issue; texto={texto[:80]!r}"

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
        return LLMResponse(
            text=json.dumps(
                {
                    "tipo": self.tipos[iid],
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


GABARITO = {"I-1": "BUG", "I-2": "FEATURE", "I-3": "DUVIDA", "I-4": "BUG", "I-5": "FEATURE"}


def test_o_conjunto_curado_e_estavel():
    """A versão é derivada do conteúdo; se alguém mexer nos casos, ela muda —
    e é isso que impede comparar um resultado de hoje com um de outra régua."""
    assert conjunto_versao() == conjunto_versao()
    assert len(avaliacao.conjunto()) == 5


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
    _, economias = _rodar(_ModeloFalso(GABARITO))

    assert economias["com-ferramenta"].usos[0].nome == "contar_palavras"
    assert economias["sem-ferramenta"].usos == ()


def test_com_gabarito_perfeito_os_dois_bracos_acertam_tudo():
    resultado, _ = _rodar(_ModeloFalso(GABARITO))

    for label in ("com-ferramenta", "sem-ferramenta"):
        assert resultado.por_label()[label].proposal_precision == 1.0


def test_o_veredito_NAO_conclui_mais_do_que_cinco_casos_permitem():
    """Com cinco casos, um acerto vale 20 pontos. Dizer "a ferramenta não
    serve" a partir disso seria trocar um palpite por outro com aparência de
    medida — o texto tem de dizer isso."""
    resultado, economias = _rodar(_ModeloFalso(GABARITO))

    saida = avaliacao.render(resultado, economias)

    assert "indício, não prova" in saida or "amostra pequena" in saida


def test_a_ferramenta_aparece_como_CANDIDATO_quando_chamada_em_todo_item():
    _, economias = _rodar(_ModeloFalso(GABARITO))

    (candidato,) = economias["com-ferramenta"].candidatos()
    assert candidato.itens_alcancados == 5


def test_modelo_que_erra_derruba_a_precisao_do_braco_certo():
    """Sanidade do arnês: se ele não distinguisse braço bom de ruim, todos os
    números acima seriam decoração."""
    errado = dict(GABARITO, **{"I-4": "FEATURE", "I-5": "BUG"})

    resultado, _ = _rodar(_ModeloFalso(errado))

    assert resultado.por_label()["com-ferramenta"].proposal_precision < 1.0
