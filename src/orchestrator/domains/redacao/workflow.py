"""Redação: o domínio que não tem "resolvido", só tem "pronto".

Conciliação, procurement e swe são pools que ENCOLHEM: cada item tem uma
decisão e sai. Este é um pool que TRANSFORMA — um tópico vira achados, que
viram rascunho, que vira texto final. Nenhum item é decidido; todos são
trabalhados.

É o caso que a §0.1 do spec anterior recusava, e está aqui como esqueleto
executável pela mesma razão que procurement e swe estão: cada atrito que ele
encontra vira uma correção de um dia em vez de uma descoberta de um mês.
"""

from collections.abc import Callable
from dataclasses import dataclass

from orchestrator.agent.llm import LLMClient
from orchestrator.agent.tarefa import SaidaDaTarefa, Tarefa, TarefaSpec
from orchestrator.agent.tools.registry import ToolRegistry
from orchestrator.kernel.cost import Cost
from orchestrator.kernel.definition import Stage, WorkflowDefinition
from orchestrator.kernel.resolution import Resolution, TraceEvent
from orchestrator.kernel.work import WorkItem, WorkSet


def _degrau(
    nome: str, system: str, produz_kind: str, instrucao: Callable[[WorkItem], str]
) -> TarefaSpec:
    """Um degrau do pipeline. Os três só diferem no prompt e no kind de saída.

    `transformar` é fechado sobre `nome` e `produz_kind`, e é por isso que os
    três degraus não precisam de três funções: a forma da transformação — o
    texto do modelo vira o payload do próximo item — é a mesma em todos.
    """

    def transformar(
        item_id: str, texto: str, custo: Cost, trace: list[TraceEvent]
    ) -> SaidaDaTarefa | None:
        if not texto.strip():
            # Texto vazio não é rascunho. `None` pede retry de formato; se o
            # retry esgotar, `conversar` chama a desistência e o item fica no
            # pool para o próximo degrau.
            return None
        rastro = tuple(trace)
        return SaidaDaTarefa(
            cost=custo,
            trace=rastro,
            resolution=Resolution(
                item_ids=frozenset({item_id}),
                produced_by=nome,
                rule=nome,
                # O rastro da conversa inteira, não só o resultado — sem ele
                # esta resolução é uma afirmação sem fonte (mesma regra que
                # `kernel/resolution.py` aplica a `Proposal`). `Tarefa` não
                # anexa por conta própria: é o `transformar` de cada domínio
                # que decide se o rastro sobrevive, e aqui ele sobrevive.
                evidence={"trace": rastro},
            ),
            produced=(
                WorkItem(
                    id=f"{item_id}+{produz_kind}",
                    kind=produz_kind,
                    payload=texto,
                    origem=nome,
                ),
            ),
        )

    return TarefaSpec(
        name=nome,
        system=system,
        model="claude-opus-5",
        prompt_de=instrucao,
        transformar=transformar,
    )


def _pesquisador() -> TarefaSpec:
    return _degrau(
        "pesquisador",
        "Você levanta fatos. Responda apenas com os achados, em texto corrido.",
        "achados",
        lambda item: f"Levante o que se sabe sobre: {item.payload.assunto}",
    )


def _escritor() -> TarefaSpec:
    return _degrau(
        "escritor",
        "Você escreve a partir de achados. Responda apenas com o texto.",
        "rascunho",
        lambda item: f"Escreva um texto a partir destes achados:\n{item.payload}",
    )


def _revisor() -> TarefaSpec:
    return _degrau(
        "revisor",
        "Você revisa texto. Responda apenas com a versão revisada.",
        "texto_final",
        lambda item: f"Revise este rascunho:\n{item.payload}",
    )


@dataclass(frozen=True)
class Topico:
    id: str
    assunto: str


def pool(topicos: list[Topico]) -> WorkSet:
    """Os tópicos como itens de kind `topico`. Um lado só — o caso degenerado
    de `WorkSet.kind`, igual a `domains/swe`."""
    return WorkSet(
        items=tuple(
            WorkItem(id=t.id, kind="topico", payload=t) for t in topicos
        )
    )


def definition(cliente: LLMClient) -> WorkflowDefinition:
    """O pipeline. Três degraus, ligados por `kind` — nenhuma fiação.

    `consome`/`produz` são o que o motor usa para filtrar e o que o canvas usa
    para desenhar. As duas leituras vêm do MESMO objeto que executa: uma
    declaração paralela permitiria drift entre o desenho e a execução.
    """
    return WorkflowDefinition(
        id="redacao",
        name="Redação de texto",
        stages=(
            Stage(
                name="pesquisar",
                cascade=(Tarefa(spec=_pesquisador(), client=cliente, tools=ToolRegistry([])),),
                consome=frozenset({"topico"}),
                produz=frozenset({"achados"}),
            ),
            Stage(
                name="escrever",
                cascade=(Tarefa(spec=_escritor(), client=cliente, tools=ToolRegistry([])),),
                consome=frozenset({"achados"}),
                produz=frozenset({"rascunho"}),
            ),
            Stage(
                name="revisar",
                cascade=(Tarefa(spec=_revisor(), client=cliente, tools=ToolRegistry([])),),
                consome=frozenset({"rascunho"}),
                produz=frozenset({"texto_final"}),
            ),
        ),
        entrega=frozenset({"texto_final"}),
    )
