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

from orchestrator.agent.llm import LLMClient
from orchestrator.agent.proposal import Cost
from orchestrator.grill.ferramentas import (
    Pergunta,
    PropostaBruta,
    Recusa,
    esquemas,
    interpretar,
)
from orchestrator.grill.prompt import SYSTEM
from orchestrator.grill.receita import Receita, construir, validar_id

# Derivação (rodada em 2026-09-15, ver Step 1 da Task 4):
#
#   overhead fixo = len(SYSTEM) + len(json.dumps(esquemas()))
#                 = 3851 chars ≈ 962 tokens de entrada,
#   pela heurística grosseira de ~4 chars/token.
#   saída realista por turno ≈ 200 tokens.
#
#   1 turno em opus-5, sem cache (500/2500 µ¢ por token de entrada/saída):
#     962*500 + 200*2500 = 981_000 µ¢
#
#   x max_turnos (12): 981_000 * 12 = 11_772_000 µ¢
#   +50% de folga para o histórico que cresce turno a turno (não modelado
#   acima, porque cada mensagem anterior — perguntas, respostas, erros de
#   formato — volta inteira a cada chamada seguinte):
#     11_772_000 * 1.5 = 17_658_000 µ¢
#
#   Arredondado para cima até um número limpo: 20_000_000 µ¢ (US$ 0,20 por
#   entrevista de até 12 turnos em opus-5). Ordem de grandeza esperada pelo
#   brief: dezenas de milhões de µ¢ — bate.
ORCAMENTO_PADRAO = 20_000_000


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
    receita: Receita
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
            resposta = self.client.complete(
                system=SYSTEM, messages=mensagens, tools=ferramentas
            )
            total = total + resposta.cost
            if total.microcents(self.client.model) > self.budget_microcents:
                raise EntrevistaFalhou(
                    "orçamento da entrevista esgotado", tuple(transcricao)
                )

            mensagens.append(self._turno_do_assistente(resposta))

            if not resposta.tool_calls:
                erro = "todo turno precisa terminar numa ferramenta; nenhuma foi chamada"
                mensagens.append(self._erro(None, erro))
                tentativas += 1
            else:
                chamada = resposta.tool_calls[0]
                try:
                    interpretada = interpretar(chamada)
                except ValueError as e:
                    mensagens.append(self._erro(chamada.id, str(e)))
                    tentativas += 1
                else:
                    if isinstance(interpretada, Pergunta):
                        transcricao.append(f"[maestro] {interpretada.texto}")
                        dita = responder(interpretada.texto)
                        transcricao.append(f"[parceiro] {dita}")
                        mensagens.append(self._resultado(chamada.id, dita))
                        continue
                    if isinstance(interpretada, Recusa):
                        return RecusaFinal(
                            motivo=interpretada.motivo,
                            o_que_faltaria=interpretada.o_que_faltaria,
                            cost=total,
                            transcricao=tuple(transcricao),
                        )
                    receita = self._receita(workflow_id, interpretada)
                    try:
                        # VALIDAR É CONSTRUIR. Se constrói, roda.
                        construir(receita)
                    except ValueError as e:
                        mensagens.append(self._erro(chamada.id, str(e)))
                        tentativas += 1
                    else:
                        return Proposta(
                            receita=receita, cost=total, transcricao=tuple(transcricao)
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
    def _receita(workflow_id: str, bruta: PropostaBruta) -> Receita:
        return Receita(
            id=workflow_id,
            nome=bruta.nome,
            justificativa=bruta.justificativa,
            gerado_em=datetime.now(UTC),
            resolvers=bruta.resolvers,
        )

    @staticmethod
    def _turno_do_assistente(resposta: Any) -> dict[str, Any]:
        """Devolve `raw_content` VERBATIM quando existe: é o único jeito de
        preservar blocos de raciocínio e de dar ao SDK real o mesmo objeto que
        ele emitiu. `FakeLLMClient` não preenche, e aí reconstruímos o mínimo.
        """
        if resposta.raw_content:
            return {"role": "assistant", "content": resposta.raw_content}
        blocos: list[dict[str, Any]] = []
        if resposta.text:
            blocos.append({"type": "text", "text": resposta.text})
        for c in resposta.tool_calls:
            blocos.append(
                {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
            )
        return {"role": "assistant", "content": blocos}

    @staticmethod
    def _resultado(tool_use_id: str, conteudo: str) -> dict[str, Any]:
        return {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tool_use_id, "content": conteudo}
            ],
        }

    @staticmethod
    def _erro(tool_use_id: str | None, mensagem: str) -> dict[str, Any]:
        if tool_use_id is None:
            return {"role": "user", "content": f"erro: {mensagem}"}
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "is_error": True,
                    "content": f"erro: {mensagem}",
                }
            ],
        }
