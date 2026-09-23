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


class Orcamento:
    """O teto de UMA requisição, e o gasto acumulado dela.

    **Por que o acumulador saiu do cliente.** Ele guardava `gasto` como `Cost` e
    o convertia com `self.model` — um modelo só, porque havia um cliente só.
    Com `model` por bloco, uma cascata tem VÁRIOS clientes, e um acumulador por
    cliente daria vários tetos: o pedido que autorizou gastar X gastaria X por
    modelo, sem ninguém pedir.

    **O acumulado é em MICRO-CENTAVOS, e não em tokens.** Com dois modelos,
    tokens não somam: mil de haiku e mil de opus não são dois mil de coisa
    nenhuma. O teto é sobre dinheiro, então a moeda é µ¢ — e é a mesma razão
    pela qual `Cost` continua sem preço: cada lado guarda a unidade em que ele
    é verdade.
    """

    def __init__(self, teto_microcents: int | None = None) -> None:
        if teto_microcents is not None and teto_microcents < 0:
            # Teto negativo nasceria estourado e faria TODO item abster sem
            # nunca chamar o modelo — pareceria um agente funcionando com
            # orçamento zerado, em vez de configuração inválida. Mesma guarda
            # de `Agent.__post_init__` e de `Budget.__post_init__`.
            raise ValueError(
                f"teto_microcents não pode ser negativo: {teto_microcents}"
            )
        self.teto_microcents = teto_microcents
        self._gasto = 0
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
        return self._gasto

    def pode_gastar(self) -> bool:
        """O teto é conferido ANTES de cada chamada, nunca depois: não há como
        saber o custo de uma chamada sem fazê-la, então a última pode
        ultrapassá-lo por um turno."""
        return self.teto_microcents is None or self._gasto < self.teto_microcents

    def registrar(self, cost: Cost, model: str) -> None:
        """Soma no PREÇO do modelo que gastou.

        `Cost.zero()` não consulta a tabela: uma execução que não gastou nada
        não deve exigir preço para ler zero — a mesma guarda de
        `metrics.evaluate` e de `Run.custo_total_microcents`.
        """
        if cost != Cost.zero():
            self._gasto += cost.microcents(model)

    def barrar(self) -> None:
        self.recusas += 1


class ClienteComTeto:
    """`LLMClient` que embrulha outro, acumula o gasto e para no teto.

    Uma instância por REQUISIÇÃO e por MODELO, dividindo um `Orcamento` com os
    demais — e é essa vida curta que dá sentido ao teto: um acumulador por
    processo somaria requisições de pessoas diferentes.
    """

    def __init__(
        self,
        interno: LLMClient,
        *,
        teto_microcents: int | None = None,
        orcamento: Orcamento | None = None,
    ) -> None:
        # Sem `orcamento`, ele cria o seu — é a forma que todo chamador de hoje
        # escreve, e ela continua significando "um teto para este cliente". Com
        # `orcamento`, vários clientes de modelos diferentes dividem o mesmo
        # teto, que é o que a requisição autorizou.
        if orcamento is not None and teto_microcents is not None:
            raise ValueError(
                "passe `orcamento` OU `teto_microcents`, não os dois: o teto "
                "mora no orçamento, e dois valores seriam duas respostas para "
                "a mesma pergunta"
            )
        self.interno = interno
        self.orcamento = (
            orcamento if orcamento is not None else Orcamento(teto_microcents)
        )
        # O MODELO é o do cliente de dentro, e é com ele que ESTE embrulho
        # precifica o que ELE gastou. Copiado uma vez, e não delegado por
        # property, porque `AgentSpec.model` é fixado na construção do agente:
        # um modelo que mudasse no meio da execução converteria custo com uma
        # tabela de preços e cobraria com outra.
        self.model = interno.model

    @property
    def teto_microcents(self) -> int | None:
        """O teto mora no orçamento. A property fica porque quem lê o teto lê do
        CLIENTE — era atributo dele até esta fatia."""
        return self.orcamento.teto_microcents

    @property
    def recusas(self) -> int:
        """Idem: `api/app.py` lê `cliente.recusas` para dizer `teto_atingido`, e
        com vários clientes a resposta tem de vir do acumulador dividido."""
        return self.orcamento.recusas

    def gasto_microcents(self) -> int:
        """O gasto DA REQUISIÇÃO, em micro-centavos.

        Vem do orçamento, que já somou cada chamada no preço do modelo que a
        fez. Era `self.gasto.microcents(self.model)` — um modelo só para tudo,
        o que deixou de ser verdade quando o bloco passou a escolher o seu.
        """
        return self.orcamento.gasto_microcents()

    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        if not self.orcamento.pode_gastar():
            self.orcamento.barrar()
            raise TetoDaExecucaoEstourado(
                f"teto desta execução esgotado: "
                f"{self.orcamento.gasto_microcents()} µ¢ gastos de um teto de "
                f"{self.orcamento.teto_microcents} µ¢"
            )
        resposta = self.interno.complete(system=system, messages=messages, tools=tools)
        self.orcamento.registrar(resposta.cost, self.model)
        return resposta
