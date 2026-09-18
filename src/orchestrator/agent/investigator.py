"""O investigador de conciliação: uma divergência entra, uma proposta sai.

Desde o M2 este módulo é DOMÍNIO, não runtime. O laço — turnos, orçamento em
dois níveis, retry de formato, erro de ferramenta voltando ao modelo, abstenção
como saída — mora em `agent/agent.py` e é o mesmo para qualquer agente. O que
sobra aqui é o que só a conciliação sabe: o prompt, como uma divergência vira
pergunta, como o JSON do modelo vira `Proposal`, e o cache de idempotência na
fila.

`Investigator` continua existindo com a mesma assinatura pública porque 714
linhas de teste dependem dela — e é exatamente isso que prova que a extração não
perdeu nada.
"""

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from orchestrator.agent.agent import Agent, AgentSpec, AgentTask
from orchestrator.agent.llm import LLMClient
from orchestrator.conciliacao.ferramentas import ToolContext, registry_de
from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.resolution import (
    Confidence,
    InvestigationOutput,
    Proposal,
    TraceEvent,
    TraceKind,
)
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkSet
from orchestrator.models import PAYLOADS, Divergence, abstencao, divergencias
from orchestrator.taxonomy import DivergenceType

if TYPE_CHECKING:
    from orchestrator.review.fila import Fila

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


def spec_de_conciliacao(
    context: ToolContext,
    model: str,
    max_turns: int,
    max_tentativas_formato: int,
    budget_microcents: int,
    budget_total_microcents: int,
) -> AgentSpec:
    """A `AgentSpec` do investigador. Tudo que o laço genérico não sabe.

    Os cinco campos de domínio: o prompt, as unidades (uma divergência por
    lançamento órfão), o parser do JSON, o "não sei" da taxonomia, e o modelo.
    """
    return AgentSpec(
        name="investigador",
        system=SYSTEM,
        model=model,
        units=lambda work: [
            AgentTask(id=d.id, prompt=descrever_divergencia(context, d))
            for d in divergencias(work)
        ],
        # Lê os DOIS lados de uma vez: `divergencias(work)` pareia banco e
        # contábil. As chaves de PAYLOADS são exatamente esses dois kinds.
        consome=frozenset(PAYLOADS),
        parse=interpretar_proposta,
        abstain=abstencao,
        max_turns=max_turns,
        max_format_retries=max_tentativas_formato,
        budget_microcents=budget_microcents,
        budget_total_microcents=budget_total_microcents,
    )


@dataclass
class Investigator:
    """O agente de conciliação. Casca fina sobre `Agent`.

    Guarda duas coisas que o laço genérico não tem por quê ter: a fila (cache
    de idempotência, que é do domínio humano) e o método `investigate`, que
    recebe divergências prontas em vez de um `WorkSet` — a porta que
    `eval/agent_eval.py` usa.
    """

    client: LLMClient
    context: ToolContext
    max_turns: int = 6
    max_tentativas_formato: int = 2
    budget_microcents: int = 4_000_000
    budget_total_microcents: int = 400_000_000

    # Idempotência: divergência que já tem proposta na fila não é
    # reinvestigada. O agente roda antes do revisor em toda passagem, então
    # sem isto a passagem 2 pagaria de novo por tudo.
    #
    # É um cache permanente, SEM invalidação: uma vez na fila, a divergência
    # nunca mais é reinvestigada, mesmo que o prompt mude, o modelo troque ou
    # um bug do agente seja corrigido. `AgentSpec.version` já existe e é a
    # metade da chave que falta; fechar é o PR #11.
    fila: "Fila | None" = None

    name: str = field(default="investigador", init=False)
    cost_class: CostClass = field(default=CostClass.AGENTE, init=False)

    def __post_init__(self) -> None:
        self._agent = Agent(
            spec=spec_de_conciliacao(
                self.context,
                self.client.model,
                self.max_turns,
                self.max_tentativas_formato,
                self.budget_microcents,
                self.budget_total_microcents,
            ),
            client=self.client,
            tools=registry_de(self.context),
        )

    def describe(self) -> ResolverDescription:
        return ResolverDescription(
            name=self.name,
            cost_class=self.cost_class,
            summary="investiga o que as regras não resolveram e propõe uma explicação",
            payloads=PAYLOADS,
        )

    def resolve(self, work: WorkSet) -> ResolverOutput:
        """Investiga o que sobrou. Nunca devolve `resolutions`."""
        saida = self.investigate(divergencias(work))
        return ResolverOutput(proposals=saida.proposals, cost=saida.cost)

    def investigate(self, divergences: list[Divergence]) -> InvestigationOutput:
        """Investiga uma lista de divergências, pulando as que já têm proposta.

        A guarda de idempotência vive AQUI, antes do teto por execução, e não
        dentro do laço — o custo gravado na proposta é o que a investigação
        ORIGINAL gastou, e precisa ficar de fora de `total`: esta passagem não
        gastou nada por ela, e somar de volta faria o teto da execução estourar
        sobre gasto histórico, não sobre gasto desta passagem.
        """
        propostas, total = [], Cost.zero()
        for d in divergences:
            guardada = self.fila.proposta(d.id) if self.fila is not None else None
            if guardada is not None:
                propostas.append(guardada)
                continue
            if total.microcents(self.client.model) > self.budget_total_microcents:
                trace = [
                    TraceEvent(
                        kind=TraceKind.OUTCOME, detail={"motivo": "orçamento total"}
                    )
                ]
                propostas.append(
                    abstencao(
                        d.id,
                        "orçamento total da execução esgotado",
                        Cost.zero(),
                        trace,
                    )
                )
                continue
            p = self._agent.investigar(
                AgentTask(id=d.id, prompt=descrever_divergencia(self.context, d))
            )
            propostas.append(p)
            total = total + p.cost
        return InvestigationOutput(proposals=propostas, cost=total)


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
        item_id=divergence_id,
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
