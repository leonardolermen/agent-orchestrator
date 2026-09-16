"""A avaliação ao vivo do domínio `swe`. GASTA DINHEIRO.

**Por que ela existe separada da avaliação da conciliação.** `eval/agent_eval.py`
prova o `Investigator` — o resolver específico de conciliação. Esta prova o
`Agent` GENÉRICO extraído no M2, com outro prompt, outra ferramenta, outro
parser e outro vocabulário de saída. Se a extração tivesse vazado domínio,
quebra aqui e não lá.

**Os dois braços, e o que eles resolvem.** Rodando isto em 2026-09-16 contra
`claude-haiku-4-5`, o agente chamou `contar_palavras` em 5 de 5 issues e o turno
que ela provocou custou mais que o turno original — ~57% do custo numa ida e
volta que não mudou nenhuma classificação. `waste.py` MEDE isso e aponta o
candidato; ele se recusa a chamar de desperdício o que não tem contrafactual.

**Este módulo NÃO executa.** Ele declara os casos, os braços e o vocabulário de
abstenção. Quem liga barramento, coletor e motor é `cli/execucao.py` — a catraca
de arquitetura reprovou a primeira versão, que fazia a fiação aqui, porque
`domains -> observability` é justamente um domínio sabendo como é observado.

O contrafactual é o segundo braço. `sem-ferramenta` roda a mesma cascata, o
mesmo prompt e o mesmo conjunto com um `ToolRegistry` vazio. Se a precisão não
cair, a ferramenta era custo puro — e aí a conclusão é medida, não opinada.

**Por que os casos vivem no código e não num JSONL.** São `Provenance.
ESPECIALISTA`: curados à mão para cobrir os dois erros que importam — a issue
que reclama sem crashar (I-4, erro de resultado) e a que reclama pedindo
funcionalidade (I-5). Um conjunto colhido da operação entra pelo `CaseStore`; um
conjunto curado é código, versionado com o prompt que ele julga.
"""

from datetime import UTC, datetime

from orchestrator.agent.agent import Agent
from orchestrator.agent.llm import LLMClient
from orchestrator.agent.tools.registry import ToolRegistry
from orchestrator.crew import Crew
from orchestrator.evaluation.case import (
    EvalDataset,
    EvaluationCase,
    ExpectedOutcome,
    Provenance,
)
from orchestrator.evaluation.benchmark import BenchmarkArm, BenchmarkResult
from orchestrator.evaluation.waste import EconomiaDeFerramentas
from orchestrator.kernel.definition import Task, WorkflowDefinition
from orchestrator.kernel.work import WorkItem

from orchestrator.domains.swe.workflow import ISSUE, Issue, ferramentas, triador

# A data de curadoria. Fixa, e anterior a qualquer run — a guarda de
# contaminação compara `created_at < run.started_at`, e um `datetime.now()`
# aqui produziria um conjunto que às vezes exclui a si mesmo, dependendo de
# quantos microssegundos o import levou. Já vi bug assim; não é hipotético.
_CURADO_EM = datetime(2026, 9, 16, 0, 0, tzinfo=UTC)

ABSTEM_COM = frozenset({"DUVIDA"})

_CASOS: tuple[tuple[Issue, str], ...] = (
    (
        Issue(
            "I-1",
            "App crasha ao abrir relatório mensal",
            "Stack trace: NullPointerException em ReportBuilder.build(), linha 84. "
            "Acontece toda vez desde a versão 2.3.1.",
        ),
        "BUG",
    ),
    (
        Issue(
            "I-2",
            "Exportar relatório em CSV",
            "Hoje só dá para exportar em PDF. Precisamos de CSV para abrir no "
            "Excel e cruzar com a planilha da controladoria.",
        ),
        "FEATURE",
    ),
    (
        Issue(
            "I-3",
            "Dúvida sobre o campo 'status'",
            "Alguém sabe se o campo status considera pedidos cancelados? Não "
            "achei na documentação.",
        ),
        "DUVIDA",
    ),
    # O primeiro caso difícil: erro de RESULTADO, não de crash. Nada estoura, e
    # um classificador que procura "exception" erra este.
    (
        Issue(
            "I-4",
            "Total do relatório vem 3 centavos menor",
            "O somatório da coluna Valor fecha em R$ 1.204,97 mas a soma manual "
            "dá R$ 1.205,00. Reproduzível com o dataset de setembro.",
        ),
        "BUG",
    ),
    # O segundo: reclamação que é pedido de funcionalidade. Um classificador
    # que procura tom de insatisfação erra este.
    (
        Issue(
            "I-5",
            "A busca é inutilizável com muitos registros",
            "Com 50 mil linhas não dá para achar nada. Não tem filtro por data "
            "nem por fornecedor, só a caixa de texto.",
        ),
        "FEATURE",
    ),
)


def conjunto() -> EvalDataset:
    """Os casos curados, como `EvalDataset`."""
    return EvalDataset(
        id="swe-curado",
        cases=tuple(
            EvaluationCase(
                id=f"swe:{issue.id}",
                input_snapshot=(WorkItem(id=issue.id, kind=ISSUE, payload=issue),),
                expected=ExpectedOutcome(kind=esperado),
                provenance=Provenance.ESPECIALISTA,
                created_at=_CURADO_EM,
                tags=frozenset({"curado"}),
            )
            for issue, esperado in _CASOS
        ),
    )


def bracos(client: LLMClient) -> tuple[BenchmarkArm, ...]:
    """Com e sem a ferramenta — o contrafactual que `waste.py` pede.

    O prompt é o MESMO nos dois. Variar prompt junto com ferramenta mediria as
    duas coisas de uma vez e não responderia nenhuma — é a razão de um
    `BenchmarkArm` variar um eixo por vez.
    """
    return (
        BenchmarkArm(
            label="com-ferramenta",
            workflow=_definicao("swe-com-ferramenta", triador(client)),
            model=client.model,
        ),
        BenchmarkArm(
            label="sem-ferramenta",
            workflow=_definicao("swe-sem-ferramenta", _triador_sem_ferramenta(client)),
            model=client.model,
        ),
    )


def bracos_tripulacao(client: LLMClient) -> tuple[BenchmarkArm, ...]:
    """Um agente contra uma tripulação de dois. A pergunta do M8.

    O §10.5 diz que construir Crew antes do M6 seria construir uma capacidade
    cara sem instrumento para saber se ela melhora alguma coisa. Este é o
    instrumento: mesmo conjunto, mesmo prompt, mesmo modelo — só muda quantos
    agentes olham o item.

    Os dois agentes da tripulação são IDÊNTICOS de propósito. Um time de
    especialistas diferentes mediria "prompt A vs prompt B vs tripulação" de
    uma vez, e não responderia nenhuma. Idênticos, o experimento pergunta uma
    coisa só: uma segunda passada, vendo a conclusão da primeira, muda alguma
    resposta? Se não mudar, `CostClass.CREW` não se paga neste domínio — e
    isso é resultado, não fracasso.
    """
    tripulacao = Crew(
        name="dupla-triagem",
        agents=(triador(client), triador(client)),
        abstem_com=ABSTEM_COM,
    )
    return (
        BenchmarkArm(
            label="agente-sozinho",
            workflow=_definicao("swe-agente", triador(client)),
            model=client.model,
        ),
        BenchmarkArm(
            label="tripulacao-2",
            workflow=_definicao("swe-crew", tripulacao),
            model=client.model,
        ),
    )


def _definicao(wid: str, agente) -> WorkflowDefinition:
    return WorkflowDefinition(
        id=wid,
        name="Triagem de issue",
        stages=(Task("que mudança esta issue pede?", resolver=agente),),
    )


def _triador_sem_ferramenta(client: LLMClient) -> Agent:
    """O mesmo agente, com o registro vazio.

    `Agent` recebe `tools` por construção, então o braço sem ferramenta não
    precisa de flag, de modo de avaliação, nem de `if` dentro do laço. É a
    propriedade que o §14.4 chama de "o runtime não sabe que está sendo
    avaliado", exercitada.
    """
    completo = triador(client)
    return Agent(spec=completo.spec, client=client, tools=ToolRegistry([]))


def render(resultado: BenchmarkResult, economias: dict[str, EconomiaDeFerramentas]) -> str:
    partes = [resultado.render(), ""]
    for label, economia in economias.items():
        partes += [f"--- economia de ferramenta: {label} ---", economia.render(), ""]
    if len(resultado.arms) == 2:
        partes.append(_veredito(resultado, economias))
    return "\n".join(partes)


def _veredito(resultado: BenchmarkResult, economias) -> str:
    """A conclusão que o contrafactual autoriza, e SÓ ela.

    Genérico nos rótulos de propósito. A primeira versão casava por
    `"com-ferramenta"`/`"sem-ferramenta"`, e quando os braços de tripulação
    entraram o veredito simplesmente não saiu — a frase sobre tamanho de
    amostra ficou ausente exatamente no experimento mais fácil de
    sobreinterpretar. Ausência de ressalva lê-se como ausência de ressalva.
    """
    (a_arm, a), (b_arm, b) = resultado.arms
    n = a.items_total
    ponto = 100 / n if n else 0

    def custo(m):
        return m.microcents_per_correct_proposal

    linhas = []
    delta = a.proposal_precision - b.proposal_precision
    if abs(delta) < 1e-9:
        linhas.append(f"MESMA precisão nos dois braços ({100 * a.proposal_precision:.0f}%).")
    else:
        melhor = a_arm.label if delta > 0 else b_arm.label
        linhas.append(
            f"{melhor} acertou {abs(delta) * n:.0f} caso(s) a mais "
            f"({100 * a.proposal_precision:.0f}% x {100 * b.proposal_precision:.0f}%)."
        )
    if a.abstention_rate != b.abstention_rate:
        mais, menos = (
            (a_arm.label, b_arm.label)
            if a.abstention_rate > b.abstention_rate
            else (b_arm.label, a_arm.label)
        )
        linhas.append(
            f"{mais} se absteve mais que {menos} "
            f"({100 * max(a.abstention_rate, b.abstention_rate):.0f}% x "
            f"{100 * min(a.abstention_rate, b.abstention_rate):.0f}%) — abstenção "
            f"a mais é precisão que não foi arriscada, não precisão conquistada."
        )
    if custo(a) and custo(b):
        caro, barato = sorted(
            ((a_arm.label, custo(a)), (b_arm.label, custo(b))), key=lambda x: -x[1]
        )
        linhas.append(
            f"{caro[0]} custa {caro[1] / barato[1]:.1f}x por acerto "
            f"em relação a {barato[0]}."
        )
    linhas.append(
        f"Com {n} casos, um acerto vale {ponto:.0f} pontos. Isto indica "
        f"direção, não decide — a próxima pergunta é o mesmo par sobre um "
        f"conjunto maior."
    )
    return " ".join(linhas)
