"""`orchestrator init`: um projeto que roda no primeiro comando.

O scaffold é um WORKFLOW COMPLETO e executável, não um esqueleto com `TODO`.
Ele tem uma regra barata, um agente (com cliente falso, para rodar sem chave) e
um revisor humano — a cascata inteira, com os três degraus de custo.

**Por que um projeto que roda em vez de um que precisa ser preenchido:** o
primeiro feedback que alguém tem do framework é se ele executa. Um scaffold com
`raise NotImplementedError` transfere para a primeira hora do usuário o trabalho
de descobrir a forma — e com a regra dos três usos suspensa (§1.3), feedback de
quem chega de fora é o substituto que sobrou para validar a abstração.

**Diferença deliberada do scaffold do CrewAI:** existe uma pasta `dominio/`.
Lá o scaffold é `agents.yaml` + `tasks.yaml`, porque o domínio é o texto do
prompt. Aqui o domínio é código tipado, e a pasta existe para dizer, na
estrutura, que o que é determinístico não mora num YAML de prompt.
"""

from pathlib import Path

_CONFIG = '''# Configuração do projeto. Tudo é opcional — sem este arquivo, tudo é default.
#
# TOML e não YAML: `tomllib` é stdlib desde o Python 3.11, e YAML custaria uma
# dependência de runtime. Ver `orchestrator/cli/config.py`.

workflow = "triagem"

[providers.anthropic]
default_model = "claude-sonnet-5"

[storage]
raiz = "data"

[observability]
spans = true
'''

_DOMINIO = '''"""O domínio: o que é seu, e o que o runtime nunca precisa saber.

`payload` é um dataclass CONGELADO. O kernel nunca o inspeciona — ele só move
ids —, e é isso que mantém as garantias daqui (tipos, imutabilidade, unidades)
sem que o runtime precise conhecê-las.
"""

from dataclasses import dataclass

from orchestrator import WorkItem, WorkSet

CHAMADO = "chamado"


@dataclass(frozen=True)
class Chamado:
    id: str
    titulo: str
    corpo: str
    urgente: bool = False


def pool(chamados: list[Chamado]) -> WorkSet:
    """A entrada do runtime. Um `WorkItem` por unidade de trabalho."""
    return WorkSet(
        items=tuple(WorkItem(id=c.id, kind=CHAMADO, payload=c) for c in chamados)
    )
'''

_REGRA = '''"""A regra barata: resolve o que não precisa de inteligência.

Ela roda PRIMEIRO porque é `CostClass.REGRA`, e a ordem não é convenção — é o
valor pelo qual `Stage.ordered()` ordena. Não existe configuração que faça o
agente rodar antes dela.
"""

from dataclasses import dataclass, field

from orchestrator import (
    CostClass,
    Resolution,
    ResolverDescription,
    ResolverOutput,
    WorkSet,
)

from dominio.modelo import CHAMADO


@dataclass
class PorPalavraChave:
    """Se o título tem uma palavra conhecida, resolve de graça."""

    name: str = field(default="palavra-chave", init=False)
    cost_class: CostClass = field(default=CostClass.REGRA, init=False)

    def describe(self) -> ResolverDescription:
        return ResolverDescription(self.name, self.cost_class, "palavra conhecida no título")

    def resolve(self, work: WorkSet) -> ResolverOutput:
        return ResolverOutput(
            resolutions=[
                Resolution(
                    item_ids=frozenset({i.id}),
                    produced_by=self.name,
                    rule="título contém 'senha'",
                    evidence={"titulo": i.payload.titulo},
                )
                for i in work.of_kind(CHAMADO)
                if "senha" in i.payload.titulo.lower()
            ]
        )
'''

_AGENTE = '''"""O agente: acorda só no que a regra não resolveu.

Ele PROPÕE e nunca resolve — `ResolverOutput.proposals` e `.resolutions` são
campos separados, e `WorkSet.without()` só aceita o segundo. A invariante não é
disciplina, é o tipo.
"""

import json

from orchestrator import (
    Agent,
    AgentSpec,
    AgentTask,
    Confidence,
    Proposal,
    ToolRegistry,
    ToolSpec,
    tool_schema,
)

from dominio.modelo import CHAMADO

PROMPT = """Classifique o chamado de suporte.

Responda APENAS com um objeto JSON:
{"tipo": "BUG"|"DUVIDA"|"PEDIDO", "explicacao": <curto>,
 "evidencia": [<strings>], "confianca": "ALTA"|"MEDIA"|"BAIXA"}

Não saber é resposta válida: responda DUVIDA com confiança BAIXA."""

TIPOS = ("BUG", "DUVIDA", "PEDIDO")


def _parse(item_id, texto, cost, trace):
    """O texto do modelo vira `Proposal`, ou `None` para disparar o retry.

    Confiança ALTA sem evidência é REBAIXADA, não descartada: a hipótese ainda
    ajuda, com o peso certo. É a guarda que mais protege a credibilidade.
    """
    try:
        dados = json.loads(texto.strip().strip("`"))
    except json.JSONDecodeError:
        return None
    if not isinstance(dados, dict) or dados.get("tipo") not in TIPOS:
        return None
    evidencia = dados.get("evidencia") or []
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
        trace=list(trace),
    )


def _abstain(item_id, motivo, cost=None, trace=None):
    """Qual é o rótulo de "não sei" é decisão SUA, não do kernel."""
    return Proposal.abstencao(item_id, "DUVIDA", motivo, cost, trace)


def ferramentas() -> ToolRegistry:
    return ToolRegistry(
        [
            ToolSpec(
                name="contar_palavras",
                description="Conta palavras de um texto.",
                input_schema=tool_schema(
                    "contar_palavras", "", {"texto": {"type": "string"}}, ["texto"]
                ),
                fn=lambda _ctx, texto: {"palavras": len(texto.split())},
            )
        ]
    )


def triador(client) -> Agent:
    return Agent(
        spec=AgentSpec(
            name="triador",
            system=PROMPT,
            model=client.model,
            units=lambda work: [
                AgentTask(id=i.id, prompt=f"{i.payload.titulo}: {i.payload.corpo}")
                for i in work.of_kind(CHAMADO)
            ],
            parse=_parse,
            abstain=_abstain,
            max_turns=3,
        ),
        client=client,
        tools=ferramentas(),
    )
'''

_WORKFLOW = '''"""O workflow inteiro, executável com `python -m workflows.triagem`.

`-m` e não o caminho do arquivo: `python workflows/triagem.py` poria
`workflows/` no `sys.path[0]` e os imports de `dominio` e `regras` falhariam.

Usa `FakeLLMClient` para rodar sem chave de API. Trocar por
`AnthropicClient(model=...)` é uma linha — e aí passa a gastar dinheiro, o que
é decisão sua e não efeito colateral de rodar o exemplo.
"""

from orchestrator import (
    Autonomy,
    Budget,
    Cost,
    EventBus,
    ExecutionPolicy,
    FakeLLMClient,
    LLMResponse,
    Task,
    Workflow,
    execute,
)
from orchestrator.observability.collector import SpanCollector
from orchestrator.observability.render import render

from agentes.triador import triador
from dominio.modelo import Chamado, pool
from regras.palavra_chave import PorPalavraChave

# A política: o agente propõe, nunca resolve, e há teto de gasto por execução.
POLITICA = ExecutionPolicy(
    budget=Budget(per_run_microcents=50_000_000),  # US$ 0,50
    autonomy=Autonomy.PROPOR,
)


def cliente_de_exemplo(quantos: int) -> FakeLLMClient:
    """Respostas preparadas, para o exemplo rodar sem chave e sem custo."""
    resposta = LLMResponse(
        text='{"tipo": "BUG", "explicacao": "erro reproduzível",'
        ' "evidencia": ["stack trace"], "confianca": "ALTA"}',
        tool_calls=[],
        cost=Cost(input_tokens=400, output_tokens=60, calls=1),
    )
    return FakeLLMClient([resposta] * quantos, model="claude-sonnet-5")


def workflow(client) -> Workflow:
    return Workflow(
        id="triagem",
        name="Triagem de chamados",
        stages=(
            Task(
                "classificar chamado",
                cascade=[PorPalavraChave(), triador(client)],
                policy=POLITICA,
            ),
        ),
    )


def main() -> None:
    chamados = [
        Chamado("c1", "Resetar senha", "não consigo entrar"),
        Chamado("c2", "Erro ao salvar", "stack trace no anexo"),
        Chamado("c3", "Exportar relatório", "seria útil ter CSV"),
    ]

    bus = EventBus()
    coletor = SpanCollector().subscribe(bus)
    run = execute(workflow(cliente_de_exemplo(len(chamados))), pool(chamados), bus=bus)

    print(render(coletor.trace(run)))
    print()
    print(f"estado: {run.state.value}")
    print(f"resolvido de graça: {run.resolved_by_resolver.get('palavra-chave', 0)}")
    print(f"proposto pelo agente: {len(run.proposals)}")


if __name__ == "__main__":
    main()
'''

_TESTE = '''"""O teste que prova que a cascata faz o que promete, sem gastar nada."""

from workflows.triagem import cliente_de_exemplo, workflow

from dominio.modelo import Chamado, pool
from orchestrator import execute


def test_a_regra_barata_resolve_antes_do_agente():
    """A ordem não é convenção: `Stage.ordered()` ordena pelo valor de
    `CostClass`, e não há configuração que a inverta."""
    chamados = [Chamado("c1", "Resetar senha", "x"), Chamado("c2", "Erro", "y")]

    run = execute(workflow(cliente_de_exemplo(2)), pool(chamados))

    assert run.resolved_by_resolver["palavra-chave"] == 1
    # O agente só viu o que sobrou.
    assert [p.item_id for p in run.proposals] == ["c2"]


def test_o_agente_propoe_e_NUNCA_resolve():
    """`ResolverOutput.proposals` e `.resolutions` são campos separados, e
    `WorkSet.without()` só aceita o segundo. Não é disciplina, é o tipo."""
    run = execute(
        workflow(cliente_de_exemplo(1)), pool([Chamado("c1", "Erro", "stack")])
    )

    assert run.proposals
    assert run.resolutions == ()
    assert len(run.unresolved.items) == 1
'''

_PYPROJECT = '''[project]
name = "{nome}"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["orchestrator"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
'''

_README = """# {nome}

Projeto do Agent Orchestrator.

```bash
python -m pip install -e .
python -m workflows.triagem     # roda a cascata inteira, sem gastar nada
pytest                          # prova que ela faz o que promete
```

## A forma

```
dominio/     o que é seu — dataclasses congelados, sem runtime dentro
regras/      resolvers de classe REGRA: resolvem de graça
agentes/     resolvers de classe AGENTE: propõem, nunca resolvem
workflows/   a cascata, e a política que decide até onde subir
```

A ordem entre as classes de custo é imposta pelo motor, não por você:
`REGRA -> AGENTE -> CREW -> HUMANO`. Não existe configuração que a inverta.

Trocar `FakeLLMClient` por `AnthropicClient(model=...)` em
`workflows/triagem.py` liga o modelo de verdade — e aí passa a gastar dinheiro.
"""

_ARQUIVOS = {
    "orchestrator.toml": _CONFIG,
    "dominio/__init__.py": "",
    "dominio/modelo.py": _DOMINIO,
    "regras/__init__.py": "",
    "regras/palavra_chave.py": _REGRA,
    "agentes/__init__.py": "",
    "agentes/triador.py": _AGENTE,
    "workflows/__init__.py": "",
    "workflows/triagem.py": _WORKFLOW,
    "tests/__init__.py": "",
    "tests/test_triagem.py": _TESTE,
    "avaliacoes/casos/.gitkeep": "",
}


def criar(nome: str, raiz: Path | None = None) -> Path:
    """Cria o projeto. Recusa sobrescrever — o mesmo cuidado de
    `gravar_receita`, que não deixa um id existente ser substituído."""
    destino = (raiz or Path.cwd()) / nome
    if destino.exists():
        raise FileExistsError(f"{destino} já existe. escolha outro nome.")

    for caminho, conteudo in _ARQUIVOS.items():
        arquivo = destino / caminho
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(conteudo, encoding="utf-8")

    (destino / "pyproject.toml").write_text(
        _PYPROJECT.format(nome=nome), encoding="utf-8"
    )
    (destino / "README.md").write_text(_README.format(nome=nome), encoding="utf-8")
    # `data/` guarda runs, traces e filas. NÃO versionado: é saída, não fonte.
    # `avaliacoes/casos/` é o contrário — é o ativo, e vai para o git.
    (destino / ".gitignore").write_text("data/\n__pycache__/\n", encoding="utf-8")
    return destino
