"""O teto de uma EXECUÇÃO, e o gasto que sobrevive a ela.

`AgentSpec` já tem dois tetos — por item (`budget_microcents`) e por execução
do agente (`budget_total_microcents`) — e os dois são do AGENTE: quem os
escolhe é quem declarou o bloco no catálogo, uma vez, para todo mundo. Falta o
terceiro, que é de quem MANDA executar: *"nesta requisição, não gaste mais que
isto"*.

Ele não cabe em `AgentSpec` porque a spec é dado congelado do catálogo, e não
cabe na política porque `ExecutionPolicy.budget` é por STAGE — uma cascata com
dois agentes em degraus diferentes teria dois tetos que não somam. Cabe no
CLIENTE, que é o único objeto que toda chamada paga atravessa, qualquer que
seja o agente, o degrau ou o item.

**Por que o mesmo objeto carrega o gasto.** `Run.cost_by_resolver` só existe se
`execute()` retornar. Uma cascata que gasta e depois levanta perde o número
junto com a exceção — dinheiro queimado que nunca aparece em resposta nenhuma.
O embrulho é do CHAMADOR, vive fora do motor, e por isso `gasto` continua
legível depois de qualquer falha lá dentro. É a guarda 2 de
`api/entrevista.py` ("o custo volta em cada desfecho") aplicada ao caminho de
execução.

**O teto é conferido ANTES de cada chamada, nunca depois.** Não há como saber o
custo de uma chamada sem fazê-la, então a última pode ultrapassar o teto por um
turno. É exatamente a forma do orçamento por item em `agent/conversa.py`, e
está dita aqui para que ninguém leia "teto" como "limite exato".

**Não existe valor que signifique "sem teto".** `teto_microcents=None` não
desliga limite nenhum: significa que o limite operante é o do próprio agente
(`AgentSpec.budget_total_microcents`), que sempre existe e sempre é finito. Um
agente sem teto é um agente que gasta até o fim da fila.
"""

from typing import Any

from orchestrator.agent.llm import LLMClient, LLMResponse
from orchestrator.kernel.cost import Cost


class TetoDaExecucaoEstourado(RuntimeError):
    """O teto desta requisição acabou. Levanta de dentro de `complete`.

    Levantar — em vez de devolver uma resposta vazia — é o que faz
    `agent/conversa.py` tratar isto como o que é: o fim do caminho para este
    item, registrado no trace e virando abstenção, sem inventar um turno que
    não aconteceu. A captura de lá é ESTREITA (só em volta de
    `client.complete`), então nada mais é engolido junto.
    """


class ClienteComTeto:
    """`LLMClient` que embrulha outro, acumula o gasto e para no teto.

    Uma instância por REQUISIÇÃO, e é essa vida curta que dá sentido ao teto:
    um acumulador por processo somaria requisições de pessoas diferentes.
    """

    def __init__(
        self, interno: LLMClient, *, teto_microcents: int | None = None
    ) -> None:
        if teto_microcents is not None and teto_microcents < 0:
            # Teto negativo nasceria estourado e faria TODO item abster sem
            # nunca chamar o modelo — pareceria um agente funcionando com
            # orçamento zerado, em vez de configuração inválida. Mesma guarda
            # de `Agent.__post_init__` e de `Budget.__post_init__`.
            raise ValueError(
                f"teto_microcents não pode ser negativo: {teto_microcents}"
            )
        self.interno = interno
        self.teto_microcents = teto_microcents
        # O MODELO é o do cliente de dentro. Copiado uma vez, e não delegado
        # por property, porque `AgentSpec.model` é fixado na construção do
        # agente: um modelo que mudasse no meio da execução converteria custo
        # com uma tabela de preços e cobraria com outra.
        self.model = interno.model
        self.gasto = Cost.zero()
        # Quantas chamadas este teto RECUSOU. Contado aqui e em lugar nenhum
        # mais, porque aqui é onde a recusa acontece.
        #
        # Sem este número, parar no teto e a API cair são o MESMO desfecho para
        # quem lê a resposta: os dois viram abstenção por `agent/conversa.py`,
        # com o mesmo `TraceKind.ERRO` e o mesmo texto. "Não achamos nada",
        # "paramos no teto" e "a API falhou" são três coisas diferentes, e num
        # endpoint que gasta a diferença é o que decide se vale a pena tentar de
        # novo. Inferir uma da outra por subtração seria um join frágil; contar
        # na origem não é.
        self.recusas = 0

    def gasto_microcents(self) -> int:
        """O gasto acumulado, em micro-centavos do modelo deste cliente.

        `Cost.zero()` converte para zero em qualquer modelo — a mesma guarda de
        `metrics.evaluate` e de `Run.custo_total_microcents`, para que uma
        execução que não gastou nada não exija tabela de preços para ler zero.
        """
        return self.gasto.microcents(self.model) if self.gasto != Cost.zero() else 0

    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        gasto = self.gasto_microcents()
        if self.teto_microcents is not None and gasto >= self.teto_microcents:
            self.recusas += 1
            raise TetoDaExecucaoEstourado(
                f"teto desta execução esgotado: {gasto} µ¢ gastos de um teto de "
                f"{self.teto_microcents} µ¢"
            )
        resposta = self.interno.complete(system=system, messages=messages, tools=tools)
        self.gasto = self.gasto + resposta.cost
        return resposta
