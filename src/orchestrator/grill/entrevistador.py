"""O laço da entrevista.

Fala com `LLMClient` e nada mais — nunca com um SDK. É isso que permite provar
teto de turnos, retry de formato, orçamento e os três caminhos de saída com
`FakeLLMClient`: sem rede, sem um centavo. O adaptador de assinatura (a última
tarefa do plano) é uma classe substituível atrás deste protocolo.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from orchestrator.agent.llm import LLMClient, ToolCall, blocos_assistente
from orchestrator.authoring.composicao import Composicao, construir_composicao
from orchestrator.grill.ferramentas import (
    Pergunta,
    PropostaBruta,
    Recusa,
    esquemas,
    interpretar,
)
from orchestrator.grill.prompt import SYSTEM
from orchestrator.grill.receita import validar_id
from orchestrator.kernel.cost import Cost

# Derivação ORIGINAL (2026-09-15), preservada porque o número novo só se lê
# contra ela:
#
#   overhead fixo = len(SYSTEM) + len(json.dumps(esquemas(), ensure_ascii=False))
#                 = 1421 + 2430 = 3851 chars ≈ 962 tokens de entrada,
#   (o kwarg não é detalhe: sem ele, os acentos do schema viram `\uXXXX` e a
#   mesma conta dá 1421 + 2680 = 4101 — a derivação precisa ser reproduzível,
#   §9.2, e é `ensure_ascii=False` o que o teste que a pina de fato mede.)
#   saída realista por turno ≈ 200 tokens.
#   1 turno em opus-5: 962*500 + 200*2500 = 981_000 µ¢
#   x12 turnos = 11_772_000; +50% de folga para o histórico = 17_658_000
#   Arredondado: 20_000_000 µ¢ (US$ 0,20).
#
# REMEDIDO em 2026-09-21, quando a entrevista passou a propor `Composicao`:
#
#   prompt  2171 chars (eram 1421: entraram as regras de etapa, de declaração
#           e a de PERGUNTAR os campos do item)
#   schema 10485 chars (eram 2430: o bloco deixou de ser `{nome, parametros}` e
#           passou a carregar as declarações inteiras de agente e de tarefa)
#   => 3164 tokens de entrada por turno, contra 962.
#
#   1 turno: 3164*500 + 200*2500 = 2_082_000 µ¢ — o DOBRO de antes, e a razão é
#   estrutural: o que o modelo recebe agora é o formulário de uma automação
#   inteira, não uma lista de nomes.
#
#   x12 turnos = 24_984_000; +50% de folga pelo mesmo motivo de antes
#   (o histórico volta inteiro a cada chamada) = 37_476_000
#
#   Arredondado para cima até um número limpo: 40_000_000 µ¢ (US$ 0,40 por
#   entrevista de até 12 turnos em opus-5).
#
# **Este número é o TETO, não o gasto esperado.** Uma entrevista que resolve em
# três turnos custa perto de US$ 0,06. O teto existe para o caso ruim, e o
# teste `test_orcamento_padrao_cobre_uma_entrevista_realista` é a catraca: se o
# prompt ou os schemas crescerem de novo, ele quebra sozinho e obriga esta
# conta a ser refeita em vez de o teto cortar uma conversa no meio.
ORCAMENTO_PADRAO = 40_000_000


class EntrevistaFalhou(Exception):
    """A entrevista não chegou a um desfecho. Nada é gravado.

    Carrega a transcrição: a conversa do parceiro não pode se perder por erro
    nosso.
    """

    def __init__(self, mensagem: str, transcricao: tuple[str, ...]) -> None:
        super().__init__(mensagem)
        self.transcricao = transcricao


@dataclass(frozen=True)
class Proposta:
    # `composicao` e não `receita`: o formato GERAL, com etapas, agente
    # declarado na hora, tarefa e tripulação. Enquanto era `Receita`, o que a
    # entrevista sabia propor era uma fileira de nomes prontos num degrau só —
    # e o chat ficou sendo a porta mais pobre do produto.
    composicao: Composicao
    cost: Cost
    transcricao: tuple[str, ...]


@dataclass(frozen=True)
class RecusaFinal:
    motivo: str
    o_que_faltaria: str
    cost: Cost
    transcricao: tuple[str, ...]


@dataclass
class Entrevistador:
    client: LLMClient
    # Teto, não meta: uma entrevista que resolve em três turnos é melhor que
    # uma que usa os doze.
    max_turnos: int = 12
    max_tentativas_formato: int = 2
    budget_microcents: int = ORCAMENTO_PADRAO

    def __post_init__(self) -> None:
        # Mesmo padrão de guardas do `Investigator.__post_init__`: um
        # `max_turnos` não positivo faria o `range` do laço ficar vazio e a
        # entrevista inteira viraria uma `EntrevistaFalhou` muda por turnos
        # esgotados, sem nunca consultar o modelo — configuração inválida
        # disfarçada de comportamento.
        if self.max_turnos < 1:
            raise ValueError(f"max_turnos precisa ser pelo menos 1: {self.max_turnos}")
        # Orçamento negativo faria a primeira comparação de custo já nascer
        # estourada: toda entrevista falharia no primeiro turno, e pareceria
        # um laço quebrado em vez de uma configuração inválida.
        if self.budget_microcents < 0:
            raise ValueError(
                f"budget_microcents não pode ser negativo: {self.budget_microcents}"
            )
        # Modelo sem preço conhecido não pode ser descoberto DEPOIS de uma
        # chamada já paga: nesse ponto o erro cru derrubaria o laço e a
        # transcrição do parceiro se perderia sem nunca virar
        # `EntrevistaFalhou`. Falhar aqui, uma vez, na construção, é o
        # comportamento certo — e é o mesmo padrão do `Investigator`.
        Cost.zero().microcents(self.client.model)

    def entrevistar(
        self,
        workflow_id: str,
        descricao: str,
        responder: Callable[[str], str],
    ) -> Proposta | RecusaFinal:
        # ANTES do primeiro turno: descobrir um id inválido no fim
        # desperdiçaria a conversa inteira do parceiro. A checagem em si mora
        # em `receita.validar_id` — o registro chama a MESMA função.
        validar_id(workflow_id)

        ferramentas = esquemas()
        mensagens: list[dict[str, Any]] = [{"role": "user", "content": descricao}]
        transcricao: list[str] = [f"[parceiro] {descricao}"]
        total = Cost.zero()
        tentativas = 0

        for _ in range(self.max_turnos):
            try:
                resposta = self.client.complete(
                    system=SYSTEM, messages=mensagens, tools=ferramentas
                )
            except Exception as erro:  # noqa: BLE001
                # A captura envolve SÓ a chamada ao modelo, o mesmo cuidado
                # do `Investigator`: alargá-la para o corpo do turno inteiro
                # transformaria bug do próprio entrevistador — um
                # AttributeError, um nome errado — em `EntrevistaFalhou`
                # plausível, escondendo o defeito atrás de uma suíte verde.
                # Timeout, rede caída, 500 da API: a conversa do parceiro não
                # pode se perder por causa disso — por isso vira
                # `EntrevistaFalhou` com a transcrição, e não uma exceção
                # crua.
                raise EntrevistaFalhou(
                    f"falha ao consultar o modelo: {erro}", tuple(transcricao)
                ) from erro

            total = total + resposta.cost
            if total.microcents(self.client.model) > self.budget_microcents:
                raise EntrevistaFalhou(
                    "orçamento da entrevista esgotado", tuple(transcricao)
                )

            mensagens.append({"role": "assistant", "content": blocos_assistente(resposta)})

            if not resposta.tool_calls:
                mensagem_erro = (
                    "todo turno precisa terminar numa ferramenta; nenhuma foi chamada"
                )
                mensagens.append(self._erro_sem_ferramenta(mensagem_erro))
                tentativas += 1
            else:
                chamada = resposta.tool_calls[0]
                try:
                    interpretada = interpretar(chamada)
                except ValueError as e:
                    mensagens.append(
                        self._mensagem_resultado(
                            resposta.tool_calls, self._bloco_erro(chamada.id, str(e))
                        )
                    )
                    tentativas += 1
                else:
                    if isinstance(interpretada, Pergunta):
                        transcricao.append(f"[maestro] {interpretada.texto}")
                        try:
                            dita = responder(interpretada.texto)
                        except Exception as erro:  # noqa: BLE001
                            # Mesma disciplina estreita: só a chamada a
                            # `responder` (stdin no adaptador real). Um
                            # EOFError ou um Ctrl+D no meio da entrevista não
                            # pode apagar a conversa que já aconteceu.
                            raise EntrevistaFalhou(
                                f"falha ao obter resposta do parceiro: {erro}",
                                tuple(transcricao),
                            ) from erro
                        if not dita.strip():
                            # A API recusa `tool_result` de conteúdo vazio.
                            # `ferramentas._texto` aplica a mesma disciplina
                            # no sentido inverso (rejeita texto vazio vindo
                            # do modelo); aqui é o texto vindo do parceiro.
                            dita = "(sem resposta)"
                        transcricao.append(f"[parceiro] {dita}")
                        mensagens.append(
                            self._mensagem_resultado(
                                resposta.tool_calls,
                                self._bloco_resultado(chamada.id, dita),
                            )
                        )
                        # Reseta: só formato inválido SEGUIDO mata a
                        # entrevista. Sem isto, erros nos turnos 1, 4 e 6 —
                        # com perguntas respondidas normalmente no meio —
                        # somariam 3 e a mensagem de erro diria "seguidas"
                        # sobre uma contagem que não é.
                        tentativas = 0
                        continue
                    if isinstance(interpretada, Recusa):
                        return RecusaFinal(
                            motivo=interpretada.motivo,
                            o_que_faltaria=interpretada.o_que_faltaria,
                            cost=total,
                            transcricao=tuple(transcricao),
                        )
                    composicao = self._composicao(workflow_id, interpretada)
                    try:
                        # VALIDAR É CONSTRUIR. Se constrói, roda.
                        construir_composicao(composicao)
                    except ValueError as e:
                        mensagens.append(
                            self._mensagem_resultado(
                                resposta.tool_calls, self._bloco_erro(chamada.id, str(e))
                            )
                        )
                        tentativas += 1
                    else:
                        return Proposta(
                            composicao=composicao, cost=total, transcricao=tuple(transcricao)
                        )

            if tentativas > self.max_tentativas_formato:
                raise EntrevistaFalhou(
                    f"formato inválido {tentativas} vezes seguidas", tuple(transcricao)
                )

        raise EntrevistaFalhou(
            f"a entrevista esgotou {self.max_turnos} turnos sem desfecho",
            tuple(transcricao),
        )

    @staticmethod
    def _composicao(workflow_id: str, bruta: PropostaBruta) -> Composicao:
        """A proposta do modelo mais o que só o chamador sabe: o id e o relógio.

        O id vem do `--id` da CLI ou do WebSocket, validado ANTES do primeiro
        turno — deixar o modelo propor um criaria duas fontes de verdade para a
        mesma chave, e a do modelo só seria conhecida no fim, tarde para
        recusar sem desperdiçar a conversa do parceiro.
        """
        return Composicao(
            id=workflow_id,
            nome=bruta.nome,
            justificativa=bruta.justificativa,
            gerado_em=datetime.now(UTC),
            etapas=bruta.etapas,
            entrega=bruta.entrega,
            max_rondas=bruta.max_rondas,
        )

    @staticmethod
    def _mensagem_resultado(
        tool_calls: list[ToolCall], bloco_principal: dict[str, Any]
    ) -> dict[str, Any]:
        """Fecha o turno com um `tool_result` por `tool_use` pedido.

        A Messages API exige exatamente um `tool_result` por `tool_use` do
        turno anterior — uma chamada paralela (`tool_calls` com mais de um
        item) que recebesse só um `tool_result` deixaria a(s) outra(s)
        órfã(s), e a PRÓXIMA chamada ao modelo voltaria com 400. O protocolo
        do grill não suporta ferramentas em paralelo, então só a primeira
        (`tool_calls[0]`, tratada pelo chamador) é de fato honrada — mas
        todas as demais ainda geraram um bloco `tool_use` e precisam de
        resposta. Cada uma recebe `is_error: True` avisando que foi
        ignorada, tudo numa ÚNICA mensagem de usuário (a API não aceita
        `tool_result`s do mesmo turno espalhados em mensagens diferentes —
        ver o mesmo cuidado em `Investigator._uma`, que zipa resultado por
        chamada quando executa todas).
        """
        blocos = [bloco_principal]
        for extra in tool_calls[1:]:
            blocos.append(
                {
                    "type": "tool_result",
                    "tool_use_id": extra.id,
                    "is_error": True,
                    "content": "erro: só uma ferramenta por turno é honrada; chamada ignorada",
                }
            )
        return {"role": "user", "content": blocos}

    @staticmethod
    def _bloco_resultado(tool_use_id: str, conteudo: str) -> dict[str, Any]:
        return {"type": "tool_result", "tool_use_id": tool_use_id, "content": conteudo}

    @staticmethod
    def _bloco_erro(tool_use_id: str, mensagem: str) -> dict[str, Any]:
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "is_error": True,
            "content": f"erro: {mensagem}",
        }

    @staticmethod
    def _erro_sem_ferramenta(mensagem: str) -> dict[str, Any]:
        # Só usado quando NENHUMA ferramenta foi chamada no turno — não há
        # `tool_use` para casar, então a mensagem é texto solto, não
        # `tool_result`.
        return {"role": "user", "content": f"erro: {mensagem}"}
