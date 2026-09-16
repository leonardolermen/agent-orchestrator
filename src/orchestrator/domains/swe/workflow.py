"""Software Engineering: "que mudança esta issue pede?"

O CASO DEGENERADO do spec de composição §1.3 — uma cascata **sem nenhum
resolver de classe REGRA**. Não há regra barata que leia uma issue; vai direto
ao agente, e o humano fecha.

Existe para ser o teste mais duro da abstração, não para ser útil. Se o kernel
só souber expressar cascatas que começam com regra, ele não é genérico — é a
conciliação com nomes trocados.

O que ele exercita e nenhum outro domínio exercita:
  - `Stage.ordered()` com uma classe só;
  - `matches_by_class` SEM a chave `REGRA` (a guarda que `metrics` documenta e
    que nunca tinha sido exercida por um domínio real);
  - `WorkSet` de um `kind` só, onde a assimetria da conciliação não existe.
"""

import json
from dataclasses import dataclass, field

from orchestrator.agent.agent import Agent, AgentSpec, AgentTask
from orchestrator.agent.llm import LLMClient
from orchestrator.agent.tools.registry import ToolRegistry, ToolSpec, tool_schema
from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.definition import Stage, Task, WorkflowDefinition
from orchestrator.kernel.resolution import (
    Confidence,
    Proposal,
    TraceEvent,
    TraceKind,
)
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkItem, WorkSet

ISSUE = "issue"


@dataclass(frozen=True)
class Issue:
    """O payload. Congelado, como todo payload de domínio."""

    id: str
    titulo: str
    corpo: str


def pool(issues: list[Issue]) -> WorkSet:
    return WorkSet(items=tuple(WorkItem(id=i.id, kind=ISSUE, payload=i) for i in issues))


@dataclass
class Triador:
    """Classifica a issue. Classe AGENTE, mas sem chamar modelo nenhum.

    É um esqueleto: ele não é um agente de verdade, e dizer que é seria mentir.
    O que ele exercita é a FORMA — um resolver de classe paga que devolve
    `proposals` e nunca `resolutions`, porque proposta não resolve.
    """

    name: str = field(default="triador", init=False)
    cost_class: CostClass = field(default=CostClass.AGENTE, init=False)

    def describe(self) -> ResolverDescription:
        return ResolverDescription(self.name, self.cost_class, "classifica a issue")

    def resolve(self, work: WorkSet) -> ResolverOutput:
        return ResolverOutput(
            proposals=[
                Proposal(
                    item_id=i.id,
                    tipo="BUG" if "erro" in i.payload.titulo.lower() else "FEATURE",
                    explicacao=f"pelo título: {i.payload.titulo!r}",
                    evidencia=[f"issue {i.id}"],
                    confianca=Confidence.BAIXA,
                    acao_sugerida="revisar_manual",
                )
                for i in work.of_kind(ISSUE)
            ],
            cost=Cost.zero(),
        )


def definition() -> WorkflowDefinition:
    """Sem `REGRA`. É o ponto."""
    return WorkflowDefinition(
        id="swe",
        name="Triagem de issue",
        stages=(Stage(name="que mudança esta issue pede?", cascade=(Triador(),)),),
    )


# ---------------------------------------------------------------------------
# O agente DECLARADO — a prova do M2.
#
# O `Triador` acima é um esqueleto: ele não chama modelo nenhum. O que segue é
# um agente de verdade, declarado inteiramente em dados, sem uma linha de laço.
# Se isto precisasse de mais do que uma `AgentSpec`, um `ToolRegistry` e três
# funções de domínio, a extração do `Investigator` teria falhado.
# ---------------------------------------------------------------------------

PROMPT = """Você classifica issues de um repositório de software.

Responda APENAS com um objeto JSON:
{"tipo": "BUG"|"FEATURE"|"DUVIDA"|"NAO_SEI", "explicacao": <texto curto>,
 "evidencia": [<strings>], "confianca": "ALTA"|"MEDIA"|"BAIXA"}

DUVIDA é um TIPO: a issue é uma pergunta, não um defeito nem um pedido.
NAO_SEI é outra coisa: você não conseguiu classificar. Não saber é resposta
válida — responda NAO_SEI com confiança BAIXA, e não DUVIDA.

Use `contar_palavras` se precisar medir o tamanho do corpo."""

TIPOS = ("BUG", "FEATURE", "DUVIDA", "NAO_SEI")
# O rótulo de "não consegui classificar". Separado de `DUVIDA`, que é um
# tipo legítimo — ver a invariante em `evaluation/metrics.medir`.
NAO_SEI = "NAO_SEI"


def _parse(item_id, texto, cost, trace):
    """O JSON do modelo vira `Proposal`, ou `None` para disparar o retry.

    Mesma disciplina de `interpretar_proposta` na conciliação: vocabulário
    fechado, e confiança ALTA sem evidência é rebaixada em vez de descartada —
    a hipótese ainda ajuda, com o peso certo.
    """
    try:
        limpo = texto.strip()
        for cerca in ("```json", "```"):
            limpo = limpo.removeprefix(cerca)
        dados = json.loads(limpo.removesuffix("```").strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(dados, dict) or dados.get("tipo") not in TIPOS:
        return None
    evidencia = dados.get("evidencia", [])
    if not isinstance(evidencia, list):
        return None
    confianca = Confidence(dados.get("confianca", "BAIXA"))
    if confianca is Confidence.ALTA and not evidencia:
        confianca = Confidence.BAIXA
    return Proposal(
        item_id=item_id,
        tipo=dados["tipo"],
        explicacao=str(dados.get("explicacao", "")),
        evidencia=[str(e) for e in evidencia],
        confianca=confianca,
        acao_sugerida="revisar_manual",
        cost=cost,
        trace=[
            *trace,
            TraceEvent(kind=TraceKind.OUTCOME, detail={"tipo": dados["tipo"]}),
        ],
    )


def _abstain(item_id, motivo, cost=None, trace=None):
    """O "não sei" do domínio. Aqui é `NAO_SEI`; na conciliação é
    `NAO_IDENTIFICADO`. O kernel não decide qual.

    Era `DUVIDA` até 2026-09-16, e era defeito: `DUVIDA` também é um tipo
    legítimo ("esta issue é uma pergunta"), então uma classificação CORRETA
    como DUVIDA era contada como abstenção. Com 16 de 50 casos assim, um terço
    do conjunto não era pontuado.
    """
    return Proposal.abstencao(item_id, NAO_SEI, motivo, cost, trace)


def ferramentas() -> ToolRegistry:
    return ToolRegistry(
        [
            ToolSpec(
                name="contar_palavras",
                description="Conta palavras de um texto.",
                input_schema=tool_schema(
                    "contar_palavras", "", {"texto": {"type": "string"}}, ["texto"]
                ),
                fn=lambda texto: {"palavras": len(texto.split())},
            )
        ]
    )


def triador(client: LLMClient) -> Agent:
    """Um agente de verdade em ~15 linhas de declaração."""
    return Agent(
        spec=AgentSpec(
            name="triador-llm",
            system=PROMPT,
            model=client.model,
            units=lambda work: [
                AgentTask(
                    id=i.id,
                    prompt=f"{i.payload.titulo}\n\n{i.payload.corpo}",
                )
                for i in work.of_kind(ISSUE)
            ],
            parse=_parse,
            abstain=_abstain,
            max_turns=3,
        ),
        client=client,
        tools=ferramentas(),
    )


def definition_com_agente(client: LLMClient) -> WorkflowDefinition:
    """A mesma cascata degenerada, com um agente de verdade no lugar do
    esqueleto. Continua sem nenhum resolver de classe REGRA."""
    return WorkflowDefinition(
        id="swe",
        name="Triagem de issue",
        stages=(Task("que mudança esta issue pede?", resolver=triador(client)),),
    )
