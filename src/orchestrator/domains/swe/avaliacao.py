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
from orchestrator.domains.swe.casos import CASOS
from orchestrator.domains.swe.workflow import ISSUE, Issue, triador
from orchestrator.evaluation.benchmark import BenchmarkArm, BenchmarkResult
from orchestrator.evaluation.case import (
    EvalDataset,
    EvaluationCase,
    ExpectedOutcome,
    Provenance,
)
from orchestrator.evaluation.waste import EconomiaDeFerramentas
from orchestrator.kernel.definition import Task, WorkflowDefinition
from orchestrator.kernel.work import WorkItem

# A data de curadoria. Fixa, e anterior a qualquer run — a guarda de
# contaminação compara `created_at < run.started_at`, e um `datetime.now()`
# aqui produziria um conjunto que às vezes exclui a si mesmo, dependendo de
# quantos microssegundos o import levou. Já vi bug assim; não é hipotético.
_CURADO_EM = datetime(2026, 9, 16, 0, 0, tzinfo=UTC)

ABSTEM_COM = frozenset({"NAO_SEI"})

def conjunto(dificuldade: str | None = None) -> EvalDataset:
    """Os casos curados, como `EvalDataset`.

    `dificuldade` recorta por marca (`facil` / `adversarial`). O recorte é um
    conjunto DIFERENTE e ganha versão própria — é `EvalDataset.__post_init__`
    quem garante isso, e é o que impede comparar a precisão sobre os fáceis com
    a precisão sobre o conjunto inteiro como se fossem a mesma régua.
    """
    casos = tuple(
        EvaluationCase(
            id=f"swe:{cid}",
            input_snapshot=(
                WorkItem(
                    id=cid,
                    kind=ISSUE,
                    payload=Issue(cid, titulo, corpo),
                ),
            ),
            expected=ExpectedOutcome(kind=esperado),
            provenance=Provenance.ESPECIALISTA,
            created_at=_CURADO_EM,
            tags=frozenset({"curado", marca}),
        )
        for cid, titulo, corpo, esperado, marca in CASOS
        if dificuldade is None or marca == dificuldade
    )
    sufixo = f"-{dificuldade}" if dificuldade else ""
    return EvalDataset(id=f"swe-curado{sufixo}", cases=casos)


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


def por_dificuldade(runs, model: str) -> str:
    """A mesma execução, pontuada contra cada recorte do conjunto.

    Um número agregado de 85% não diz se o agente erra no caso fácil ou no
    adversarial, e os dois diagnósticos são opostos: errar no fácil é
    regressão; errar no adversarial é o limite da abordagem. Custa zero
    chamadas a mais — é o MESMO run medido contra outro recorte.
    """
    from orchestrator.evaluation.metrics import medir

    linhas = [
        f"{'braço':<22} {'estrato':<14} {'n':>4} {'precisão':>9} {'abst.':>7}",
        "-" * 60,
    ]
    for label, run in runs.items():
        for marca in ("facil", "adversarial"):
            recorte = conjunto(marca)
            m = medir(run, recorte, model=model, abstem_com=ABSTEM_COM)
            linhas.append(
                f"{label:<22} {marca:<14} {m.items_total:>4} "
                f"{100 * m.proposal_precision:>8.1f}% "
                f"{100 * m.abstention_rate:>6.1f}%"
            )
    return "\n".join(linhas)


def render(
    resultado: BenchmarkResult,
    economias: dict[str, EconomiaDeFerramentas],
    runs=None,
    model: str = "claude-haiku-4-5",
) -> str:
    partes = [resultado.render(), ""]
    if runs:
        partes += ["--- por dificuldade ---", por_dificuldade(runs, model), ""]
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
    linhas.append(_ressalva(n, ponto, abs(delta)))
    return " ".join(linhas)


def _ressalva(n: int, ponto: float, delta: float) -> str:
    """A ressalva ESCALA com a amostra e com o tamanho do efeito.

    A primeira versão dizia "indica direção, não decide" sempre, e isso custou
    caro de um jeito específico: com n=5 a frase estava certa e eu mesmo a li
    como mais fraca do que era, registrando no P6.81 uma conclusão que os 50
    casos depois REVOGARAM. Com n=50 e nove pontos de diferença, repetir a
    mesma frase seria o erro oposto — hedge onde o dado já fala.

    O corte é o efeito contra o valor de UM acerto. Uma diferença que cabe em
    um ou dois acertos é ruído em qualquer n; uma que passa disso com folga é
    sinal.
    """
    base = f"Com {n} casos, um acerto vale {ponto:.0f} pontos."
    if delta <= 0:
        return (
            f"{base} Empate não é evidência de equivalência: é ausência de "
            f"diferença DETECTÁVEL neste tamanho."
        )
    acertos = delta * n
    if acertos <= 2:
        return (
            f"{base} A diferença cabe em {acertos:.0f} acerto(s) — isto é "
            f"ruído, não resultado."
        )
    if acertos < 5:
        return (
            f"{base} A diferença são {acertos:.0f} acertos: indica direção e "
            f"não decide. Repita sobre um conjunto maior antes de agir."
        )
    return (
        f"{base} A diferença são {acertos:.0f} acertos, bem acima do que um "
        f"caso isolado explica. Isto é resultado — confirme com uma segunda "
        f"execução (o modelo não é determinístico) e aja."
    )
