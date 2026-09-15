"""O investigador: uma divergência entra, uma proposta sai.

Nunca levanta por causa do modelo. Toda falha — JSON quebrado, tipo inventado,
ferramenta inexistente, orçamento estourado, turnos esgotados — vira abstenção
registrada. Um investigador que estoura no meio de um fechamento derruba o
processo inteiro por causa de um item.
"""

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from orchestrator.agent.llm import LLMClient, LLMResponse
from orchestrator.agent.proposal import (
    Confidence,
    Cost,
    InvestigationOutput,
    Proposal,
    TraceEvent,
    TraceKind,
)
from orchestrator.agent.tools import TOOL_SCHEMAS, ToolContext
from orchestrator.models import Divergence
from orchestrator.taxonomy import DivergenceType
from orchestrator.workflow.cost_class import CostClass
from orchestrator.workflow.resolver import ResolverDescription, ResolverOutput
from orchestrator.workflow.workset import WorkSet

if TYPE_CHECKING:
    # Só para o type checker: um import em tempo de execução aqui não seria
    # circular hoje, mas manteria o pacote `agent` dependendo do pacote
    # `review` só para uma anotação — o mesmo cuidado que `matching/engine.py`
    # já toma com `WorkflowDefinition`.
    from orchestrator.review.fila import Fila

# I3: vocabulário fechado de ações. O plano 3 (fila de revisão humana) precisa
# despachar por este campo — texto livre não dá para despachar.
ACOES_VALIDAS = ("conciliar_com", "ajustar", "investigar_manual")

SYSTEM = """Você investiga divergências de conciliação bancária brasileira.

Recebe UMA divergência: lançamentos que as regras determinísticas não
conseguiram casar. Seu trabalho é explicar por quê, usando as ferramentas para
buscar contexto.

Regras:
- Use `calcular_retencao` para qualquer cálculo de imposto. Nunca calcule de cabeça.
- Cite evidência concreta: ids e valores que você de fato consultou.
- Não saber é resposta válida e esperada. Se não houver evidência que sustente
  uma hipótese, responda com tipo NAO_IDENTIFICADO e confiança BAIXA. Uma
  proposta errada com confiança alta custa mais caro que dez abstenções.

Quando tiver concluído, responda APENAS com um objeto JSON — nada de texto
antes ou depois, e NUNCA envolva a resposta em cerca de markdown (```json ou
```):
{"tipo": <um dos tipos>, "explicacao": <texto curto>, "evidencia": [<strings>],
 "confianca": "ALTA"|"MEDIA"|"BAIXA", "acao_sugerida": <uma das três abaixo>}

`acao_sugerida` começa sempre com um destes três: "conciliar_com(<ids>)",
"ajustar(<valor>)" ou "investigar_manual". Qualquer outra coisa é tratada como
investigar_manual.

Tipos válidos: """ + ", ".join(t.value for t in DivergenceType)


def _sem_cerca_markdown(texto: str) -> str:
    """Remove uma cerca ```json ... ``` (ou ``` ... ```) em volta do texto.

    I4: é a falha de formato mais comum do modelo, e cada uma custava um
    turno inteiro de retry antes desta guarda.
    """
    t = texto.strip()
    if not t.startswith("```"):
        return t
    quebra = t.find("\n")
    t = t[quebra + 1 :] if quebra != -1 else t.removeprefix("```")
    return t.removesuffix("```").strip()


@dataclass
class Investigator:
    client: LLMClient
    context: ToolContext
    max_turns: int = 6
    max_tentativas_formato: int = 2

    # CRITICAL 1 — derivação do padrão, não um chute. Medido em código, não
    # suposto (ver `test_orcamento_padrao_admite_um_turno_realista...`):
    #
    #   overhead fixo = len(SYSTEM) + len(json.dumps(TOOL_SCHEMAS))
    #                 = 1363 + 2190 = 3553 chars ≈ 888 tokens de entrada,
    #   pela heurística grosseira de ~4 chars/token.
    #   saída realista por turno ≈ 200 tokens.
    #
    #   1º turno, sem cache, no modelo mais caro (opus-5: 500/2500 µ¢ por
    #   token de entrada/saída):
    #     888*500 + 200*2500 = 944_000 µ¢
    #   turnos 2..6 de `max_turns`, com SYSTEM+TOOL_SCHEMAS cacheados (lidos a
    #   0.1x = 50 µ¢/token em vez de 500):
    #     888*50 + 200*2500 = 544_400 µ¢ cada, x5 turnos = 2_722_000 µ¢
    #   total para os 6 turnos de uma investigação inteira em opus-5:
    #     944_000 + 2_722_000 = 3_666_000 µ¢, arredondado para cima com folga
    #     — a heurística de tokens é grosseira e o histórico de conversa
    #     cresce turno a turno, o que a conta acima não modela — para
    #     4_000_000 µ¢ (US$ 0,04).
    #
    #   Implicação de custo por execução: este valor multiplicado pela
    #   contagem de divergências enviadas ao agente é o teto de gasto real.
    #   Num lote de 100 divergências, pior caso — todas esgotam o orçamento
    #   sem concluir —: 100 * 4_000_000 µ¢ = 400_000_000 µ¢ ≈ US$ 4,00. Na
    #   prática, bem menor: a maioria conclui em 1-2 turnos.
    #
    # `test_orcamento_padrao_admite_um_turno_realista_em_todo_modelo_precificado`
    # pina a invariante que faltava: o padrão precisa admitir pelo menos UM
    # turno de verdade em TODO modelo da tabela de preços, não só no mais
    # barato — e quebra sozinho se o prompt crescer ou os preços mudarem.
    budget_microcents: int = 4_000_000

    # I1 — teto por EXECUÇÃO, além do teto por divergência. O spec exige os
    # dois níveis. Default conservador: cobre um lote de ~100 divergências no
    # pior caso (todas esgotando o orçamento individual), o que já é caro
    # demais para um operador não perceber antes de acontecer de novo.
    budget_total_microcents: int = 400_000_000

    # Idempotência: divergência que já tem proposta na fila não é
    # reinvestigada. O agente roda antes do revisor em toda passagem, então
    # sem isto a passagem 2 pagaria de novo por tudo.
    fila: "Fila | None" = None

    name: str = field(default="investigador", init=False)
    cost_class: CostClass = field(default=CostClass.AGENTE, init=False)

    def __post_init__(self) -> None:
        # `range(max_turns)` com max_turns <= 0 é vazio: o laço de `_uma`
        # nunca chama o modelo e a investigação inteira vira abstenção muda,
        # sem custo e sem trace de erro — um agente que não pode dar nem um
        # turno não é agente, é abstenção disfarçada de configuração válida.
        if self.max_turns < 1:
            raise ValueError(f"max_turns precisa ser pelo menos 1: {self.max_turns}")
        # Orçamento negativo faria a primeira comparação de custo
        # (`custo.microcents(...) > self.budget_microcents`) já nascer
        # estourada: toda divergência abstém no primeiro turno, sem nunca
        # chamar o modelo, e pareceria um agente funcionando com orçamento
        # zerado em vez de uma configuração inválida.
        if self.budget_microcents < 0:
            raise ValueError(f"budget_microcents não pode ser negativo: {self.budget_microcents}")
        if self.budget_total_microcents < 0:
            raise ValueError(
                f"budget_total_microcents não pode ser negativo: {self.budget_total_microcents}"
            )
        # Modelo sem preço conhecido não é abstenção, é erro de configuração.
        # Abster em toda divergência gastaria a execução inteira sem produzir
        # nada, e o custo — que é a métrica central do produto — ficaria
        # incalculável. Falhar aqui, uma vez, é o comportamento certo.
        Cost.zero().microcents(self.client.model)

    def describe(self) -> ResolverDescription:
        return ResolverDescription(
            name=self.name,
            cost_class=self.cost_class,
            summary="investiga o que as regras não resolveram e propõe uma explicação",
        )

    def resolve(self, work: WorkSet) -> ResolverOutput:
        """Investiga o que sobrou. Nunca devolve `matches`: proposta não resolve."""
        saida = self.investigate(work.as_divergences())
        return ResolverOutput(proposals=saida.proposals, cost=saida.cost)

    def investigate(self, divergences: list[Divergence]) -> InvestigationOutput:
        propostas, total = [], Cost.zero()
        for d in divergences:
            # Idempotência: divergência que já tem proposta na fila não é
            # reinvestigada. O agente roda antes do revisor em toda passagem,
            # então sem isto a passagem 2 pagaria de novo por tudo. A guarda
            # vive AQUI, antes do teto por execução, e não dentro de `_uma`
            # — o custo gravado na proposta é o que a investigação ORIGINAL
            # gastou, e precisa ficar de fora de `total`: esta passagem não
            # gastou nada por ela, e somar de volta faria o teto da execução
            # estourar sobre gasto histórico, não sobre gasto desta passagem.
            #
            # É um cache permanente, sem invalidação: uma vez na fila, a
            # divergência nunca mais é reinvestigada, mesmo que o prompt
            # mude, o modelo troque ou um bug do agente seja corrigido.
            # Reprocessar de verdade exige apagar a entrada da fila.
            guardada = self.fila.proposta(d.id) if self.fila is not None else None
            if guardada is not None:
                propostas.append(guardada)
                continue
            if total.microcents(self.client.model) > self.budget_total_microcents:
                # I1: estourar o teto da EXECUÇÃO é evento observável, não
                # exceção — abstém o restante do lote sem nem chamar o
                # modelo, e registra por quê em cada proposta.
                trace = [
                    TraceEvent(
                        kind=TraceKind.OUTCOME, detail={"motivo": "orçamento total"}
                    )
                ]
                propostas.append(
                    Proposal.abstencao(
                        d.id, "orçamento total da execução esgotado", Cost.zero(), trace
                    )
                )
                continue
            p = self._uma(d)
            propostas.append(p)
            total = total + p.cost
        return InvestigationOutput(proposals=propostas, cost=total)

    def _uma(self, divergencia: Divergence) -> Proposal:
        entrada = descrever_divergencia(self.context, divergencia)
        mensagens: list[dict[str, Any]] = [{"role": "user", "content": entrada}]
        custo, tentativas_formato = Cost.zero(), 0
        trace: list[TraceEvent] = [
            TraceEvent(kind=TraceKind.ENTRADA, detail={"divergencia": divergencia.id})
        ]

        for turno in range(1, self.max_turns + 1):
            try:
                resposta = self.client.complete(
                    system=SYSTEM, messages=mensagens, tools=TOOL_SCHEMAS
                )
            except Exception as erro:  # noqa: BLE001
                # A captura envolve SÓ a chamada ao modelo, de propósito.
                # Alargá-la para o corpo do turno inteiro transformaria bug do
                # próprio investigador — um AttributeError, um nome errado — em
                # abstenção plausível com suíte verde, que é a falha oposta e
                # pior da que esta guarda previne.
                #
                # Timeout, rede caída, 500 da API. O SDK já tenta de novo por
                # conta própria; se chegou aqui, acabou. Abster é a saída certa:
                # derrubar o processo inteiro por causa de um item transformaria
                # falha de rede em conciliação não entregue.
                trace.append(
                    TraceEvent(kind=TraceKind.ERRO, detail={"turno": turno, "erro": str(erro)})
                )
                trace.append(
                    TraceEvent(kind=TraceKind.OUTCOME, detail={"motivo": "falha de api"})
                )
                return Proposal.abstencao(
                    divergencia.id, f"falha de API ao investigar: {erro}", custo, trace
                )

            custo = custo + resposta.cost
            trace.append(
                TraceEvent(
                    kind=TraceKind.LLM,
                    detail={
                        "turno": turno,
                        "tokens_entrada": resposta.cost.input_tokens,
                        "tokens_saida": resposta.cost.output_tokens,
                        "ferramentas_pedidas": [c.name for c in resposta.tool_calls],
                        # I8: truncamento (max_tokens), recusa e falha de rede
                        # são três problemas operacionais diferentes que hoje
                        # aparecem idênticos sem este campo.
                        "stop_reason": resposta.stop_reason,
                    },
                )
            )

            if custo.microcents(self.client.model) > self.budget_microcents:
                trace.append(
                    TraceEvent(kind=TraceKind.OUTCOME, detail={"motivo": "orçamento"})
                )
                return Proposal.abstencao(
                    divergencia.id, "orçamento da divergência esgotado", custo, trace
                )

            if resposta.tool_calls:
                resultados = self._executar(resposta.tool_calls)
                for chamada, resultado in zip(resposta.tool_calls, resultados, strict=True):
                    trace.append(
                        TraceEvent(
                            kind=TraceKind.TOOL,
                            detail={
                                "nome": chamada.name,
                                "argumentos": chamada.arguments,
                                # I2: o spec exige argumento E retorno no
                                # rastro — sem o retorno, uma auditoria não
                                # sabe o que a ferramenta respondeu.
                                "resultado": resultado,
                            },
                        )
                    )
                mensagens.append(
                    {"role": "assistant", "content": self._blocos_assistente(resposta)}
                )
                mensagens.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": chamada.id,
                                "content": json.dumps(resultado, ensure_ascii=False, default=str),
                            }
                            for chamada, resultado in zip(
                                resposta.tool_calls, resultados, strict=True
                            )
                        ],
                    }
                )
                continue

            proposta = interpretar_proposta(divergencia.id, resposta.text, custo, trace)
            if proposta is not None:
                return proposta

            tentativas_formato += 1
            if tentativas_formato > self.max_tentativas_formato:
                break
            mensagens.append({"role": "assistant", "content": resposta.text})
            mensagens.append(
                {
                    "role": "user",
                    "content": "Resposta inválida. Responda APENAS o objeto JSON pedido.",
                }
            )

        trace.append(TraceEvent(kind=TraceKind.OUTCOME, detail={"motivo": "sem conclusão"}))
        return Proposal.abstencao(
            divergencia.id,
            "investigação encerrada sem conclusão utilizável",
            custo,
            trace,
        )

    @staticmethod
    def _blocos_assistente(resposta: LLMResponse) -> list[Any]:
        """Blocos de conteúdo do turno do assistente, para ecoar de volta.

        CRITICAL 2 (defeito 3): quando o cliente real preenche `raw_content`,
        devolve os blocos VERBATIM — inclui blocos de thinking, que a API
        exige de volta inalterados. `FakeLLMClient` e `ReplayClient` nunca
        preenchem `raw_content`; para esses, reconstrói um turno mínimo a
        partir de `text`/`tool_calls`, só para que os testes movidos a dublê
        continuem exercitando o laço.
        """
        if resposta.raw_content:
            return resposta.raw_content
        blocos: list[Any] = []
        if resposta.text:
            blocos.append({"type": "text", "text": resposta.text})
        blocos.extend(
            {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
            for c in resposta.tool_calls
        )
        return blocos

    def _executar(self, chamadas: list[Any]) -> list[Any]:
        """Executa as ferramentas pedidas e devolve um resultado por chamada,
        na mesma ordem — necessário para casar cada `tool_result` com o
        `tool_use_id` que ele responde (CRITICAL 2, defeito 2).

        Erro de ferramenta volta para o modelo dentro do resultado, nunca
        como exceção — o modelo consegue se corrigir, o processo não
        consegue se recuperar de um estouro.
        """
        resultados: list[Any] = []
        for c in chamadas:
            metodo = getattr(self.context, c.name, None)
            if metodo is None or c.name not in {s["name"] for s in TOOL_SCHEMAS}:
                resultados.append({"erro": "ferramenta inexistente"})
                continue
            try:
                argumentos = {k: v for k, v in c.arguments.items() if v is not None}
                resultados.append(metodo(**argumentos))
            except Exception as erro:  # noqa: BLE001
                # Aqui a captura larga É o requisito, e é a inversão exata da
                # guarda estreita em volta de `complete`: o spec manda que erro
                # de ferramenta volte ao modelo como texto, sempre. O modelo se
                # corrige sozinho; o processo não se recupera de um estouro.
                resultados.append({"erro": str(erro)})
        return resultados


def interpretar_proposta(
    divergence_id: str, texto: str, custo: Cost, trace: list[TraceEvent]
) -> Proposal | None:
    """Devolve None quando o texto não é uma proposta utilizável."""
    try:
        dados = json.loads(_sem_cerca_markdown(texto))
    except json.JSONDecodeError:
        return None
    if not isinstance(dados, dict):
        return None
    try:
        tipo = DivergenceType(dados.get("tipo", ""))
        confianca = Confidence(dados.get("confianca", ""))
    except ValueError:
        return None

    evidencia_bruta = dados.get("evidencia", [])
    if not isinstance(evidencia_bruta, list):
        # String onde se pediu lista é erro de forma comum do modelo, e
        # iterar sobre ela produz uma lista de CARACTERES. Medido:
        # "l1: bruto 100" virava 13 itens — evidência "não vazia" que não
        # sustenta nada, e que fazia uma confiança ALTA passar sem
        # rebaixamento. Rejeitar manda para o caminho de retry.
        return None
    evidencia = [str(e) for e in evidencia_bruta]
    # Afirmar com confiança sem citar nada acontece. Rebaixar é mais útil
    # que descartar: a hipótese ainda ajuda o humano, com o peso certo.
    if confianca is Confidence.ALTA and not evidencia:
        confianca = Confidence.BAIXA

    # I3: vocabulário fechado. Texto livre não dá para o plano 3
    # despachar; rebaixa para investigar_manual em vez de rejeitar a
    # proposta inteira — o tipo e a evidência continuam válidos.
    acao = str(dados.get("acao_sugerida", "investigar_manual"))
    if not acao.startswith(ACOES_VALIDAS):
        acao = "investigar_manual"

    return Proposal(
        divergence_id=divergence_id,
        tipo=tipo,
        explicacao=str(dados.get("explicacao", "")),
        evidencia=evidencia,
        confianca=confianca,
        acao_sugerida=acao,
        cost=custo,
        trace=[*trace, TraceEvent(kind=TraceKind.OUTCOME, detail={"tipo": tipo.value})],
    )


def descrever_divergencia(context: ToolContext, d: Divergence) -> str:
    banco = [e for e in context.bank if e.id in d.bank_ids]
    contabil = [le for le in context.ledger if le.id in d.ledger_ids]
    return json.dumps(
        {
            "divergencia_id": d.id,
            "lancamentos_bancarios": [
                {
                    "id": e.id,
                    "data": e.date.isoformat(),
                    "valor": e.amount,
                    "descricao": e.description,
                    "contraparte": e.counterparty,
                    "documento": e.document,
                }
                for e in banco
            ],
            "lancamentos_contabeis": [ToolContext.ledger_dict(le) for le in contabil],
        },
        ensure_ascii=False,
    )
