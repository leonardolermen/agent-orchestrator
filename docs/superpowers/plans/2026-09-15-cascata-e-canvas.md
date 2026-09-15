# Cascata de Resolução e Canvas Read-Only — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tornar a cascata de resolução um objeto de primeira classe do domínio — regra, agente e humano com a mesma forma — e desenhá-la numa tela alimentada por medição real, sem edição.

**Architecture:** Um protocolo `Resolver` único substitui `Matcher` e `Investigator`. Cada resolver declara uma `CostClass`, e `reconcile` ordena a cascata por ela com `sorted` estável: a ordem entre classes é derivada, a ordem dentro da classe é do especialista. O que resolve remove do pool; o que propõe não. Uma `WorkflowDefinition` guarda os resolvers vivos e é o objeto que o motor executa E que a API serializa, o que torna drift entre desenho e motor impossível. Um app FastAPI serve a definição e uma execução medida; nenhum endpoint consegue chamar o modelo.

**Tech Stack:** Python 3.11+, pytest, ruff (line-length 100), FastAPI + uvicorn como extra opcional `[api]`, front em HTML/CSS/JS sem build step.

**Spec:** [`2026-09-15-cascata-e-canvas-design.md`](../specs/2026-09-15-cascata-e-canvas-design.md)

## Global Constraints

- **Valores monetários são `int` em centavos.** Ponto flutuante em dinheiro é proibido, inclusive em testes. Custo de API é `int` em **micro-cents de USD**.
- **Nenhuma chamada de API em teste.** A suíte roda inteira sem rede e sem credencial. Isto inclui os testes da API HTTP.
- **Nenhum endpoint desta fatia pode gastar dinheiro.** Não é uma flag a desligar: o endpoint de execução não tem caminho de código até o modelo.
- **O refactor não pode mudar um dígito.** O golden da Task 1 é a autoridade. Se ele quebrar, o refactor está errado — não regenere o golden para fazer o teste passar.
- **`proposals` nunca remove do pool.** Nenhuma expressão que calcula o pool restante pode mencionar `proposals`.
- **Comentários e docstrings em português.** Nomes de código em português quando o domínio é brasileiro, seguindo o que já existe.
- **Ruff limpo em tudo que a tarefa toca.** `python -m ruff check <arquivos>` sem erro antes de cada commit.
- **Formatação:** `src/orchestrator/eval/agent_eval.py` e `tests/eval/test_agent_eval.py` já têm drift de formatação anterior a este plano. **Não reformate arquivo que a tarefa não está mudando por outro motivo.**

## Comandos do ambiente

O venv fica em `.venv` e o shell é PowerShell/Git Bash no Windows. Em todos os passos abaixo:

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q
./.venv/Scripts/python.exe -m ruff check src/ tests/
```

---

## Mapa de arquivos

**Criados:**

| Arquivo | Responsabilidade |
|---|---|
| `src/orchestrator/workflow/__init__.py` | pacote |
| `src/orchestrator/workflow/cost_class.py` | `CostClass` — a ordem entre classes |
| `src/orchestrator/workflow/workset.py` | `WorkSet` — o pool não resolvido |
| `src/orchestrator/workflow/resolver.py` | `Resolver`, `ResolverOutput`, `ResolverDescription` |
| `src/orchestrator/workflow/definition.py` | `Stage`, `WorkflowDefinition`, `default_definition()` |
| `src/orchestrator/api/__init__.py` | pacote |
| `src/orchestrator/api/schemas.py` | o contrato JSON, isolado do domínio |
| `src/orchestrator/api/app.py` | o app FastAPI |
| `web/index.html`, `web/style.css`, `web/canvas.js` | o canvas read-only |
| `tests/golden/gerar.py` | gera o golden; roda uma vez, antes de tudo |
| `tests/golden/cascata_12_sementes.json` | a medição congelada |
| `tests/test_golden.py` | exige reprodução dígito a dígito |
| `tests/workflow/test_*.py`, `tests/api/test_*.py` | testes das peças novas |

**Modificados:**

| Arquivo | O que muda |
|---|---|
| `src/orchestrator/matching/exact.py`, `tolerance.py`, `grouping.py` | implementam `Resolver` |
| `src/orchestrator/matching/protocol.py` | `Matcher` é removido |
| `src/orchestrator/matching/engine.py` | `reconcile` roda a cascata |
| `src/orchestrator/agent/investigator.py` | implementa `Resolver` |
| `src/orchestrator/metrics.py` | custo e taxa por resolver |
| `src/orchestrator/cli.py`, `src/orchestrator/eval/agent_eval.py` | chamadores |
| `tests/matching/*`, `tests/synth/test_injectors.py`, `tests/test_metrics.py`, `tests/agent/test_investigator.py` | acompanham as assinaturas |
| `pyproject.toml` | extra `[api]` |

---

## Task 1: Golden da medição atual

**Por que primeiro:** os testes de hoje afirmam *pisos* (mínimo 0,78 entre sementes). Piso não pega refactor que mexe nos números para cima. Sem este arquivo capturado **antes** de tocar em qualquer coisa, não há como provar que o refactor preservou comportamento.

**Files:**
- Create: `tests/golden/__init__.py`, `tests/golden/gerar.py`, `tests/golden/cascata_12_sementes.json`
- Create: `tests/test_golden.py`

**Interfaces:**
- Consumes: `orchestrator.cli.build_benchmark`, `orchestrator.matching.engine.reconcile`, `orchestrator.metrics.evaluate` (todos já existem, inalterados)
- Produces: `tests/golden/cascata_12_sementes.json` — a autoridade de todas as tarefas seguintes

- [ ] **Step 1: Escrever o teste que exige o golden**

`tests/test_golden.py`:

```python
"""O refactor da cascata não pode mudar um dígito.

Os outros testes de taxa afirmam PISOS. Piso não pega refactor que mexe nos
números para cima — e mudança silenciosa para cima é tão errada quanto para
baixo, porque significa que o motor passou a casar coisa que não casava.
"""

import json
from pathlib import Path

from tests.golden.gerar import CAMINHO, medir

MENSAGEM = (
    "A medição mudou. Se você NÃO mexeu na lógica de matching, o refactor está "
    "errado — conserte o código, não o golden. Se você mexeu DE PROPÓSITO, "
    "regenere com `python -m tests.golden.gerar` e explique a mudança no corpo "
    "do commit, número por número."
)


def test_golden_existe():
    assert Path(CAMINHO).exists(), (
        f"golden não encontrado em {CAMINHO}; gere com "
        f"`python -m tests.golden.gerar` ANTES de qualquer refactor"
    )


def test_medicao_reproduz_o_golden_digito_a_digito():
    esperado = json.loads(Path(CAMINHO).read_text(encoding="utf-8"))
    obtido = medir()
    assert obtido == esperado, MENSAGEM
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_golden.py -q
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'tests.golden'`.

- [ ] **Step 3: Escrever o gerador**

`tests/golden/__init__.py` vazio. `tests/golden/gerar.py`:

```python
"""Congela a medição determinística de 12 sementes.

Rodar UMA vez, antes do refactor da cascata. Depois disso o arquivo é
autoridade: quem o regenera precisa explicar por quê.

Semente 1..12, n=300, taxa 0.15 — a mesma configuração da medição citada no
comentário de `_FRACAO_AGREGADOS` em `orchestrator/cli.py`.
"""

import json
from pathlib import Path

from orchestrator.cli import build_benchmark
from orchestrator.matching.engine import reconcile
from orchestrator.metrics import evaluate

CAMINHO = Path(__file__).parent / "cascata_12_sementes.json"
SEMENTES = tuple(range(1, 13))
N = 300
TAXA = 0.15


def medir() -> dict:
    """A medição bruta, sem arredondamento de conveniência."""
    saida: dict[str, dict] = {}
    for semente in SEMENTES:
        dataset = build_benchmark(seed=semente, n=N, taxa_divergencia=TAXA)
        resultado = reconcile(dataset.bank, dataset.ledger)
        m = evaluate(dataset, resultado)
        saida[str(semente)] = {
            # 12 casas: o suficiente para pegar qualquer mudança real de
            # comportamento e curto o bastante para não pinar ruído de ponto
            # flutuante da última casa.
            "deterministic_rate": round(m.deterministic_rate, 12),
            "bank_matched": m.bank_matched,
            "divergences": m.divergences,
            "false_positives": m.false_positives,
            "false_negatives": m.false_negatives,
            "matched_amount": m.matched_amount,
            "divergent_amount": m.divergent_amount,
            "matches_by_layer": dict(sorted(m.matches_by_layer.items())),
        }
    return saida


def main() -> int:
    CAMINHO.write_text(
        json.dumps(medir(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"golden escrito em {CAMINHO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Gerar o golden e conferir que o conteúdo é plausível**

```bash
./.venv/Scripts/python.exe -m tests.golden.gerar
```

Confira à mão antes de commitar: as 12 taxas devem ficar entre 0,83 e 0,93, e **todos** os `false_positives` e `false_negatives` devem ser `0`. Se algum não for, pare — o golden estaria congelando um bug, e nenhuma tarefa seguinte teria autoridade.

- [ ] **Step 5: Rodar o teste e ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_golden.py -q
```

Esperado: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add tests/golden/ tests/test_golden.py
git commit -m "test: congela a medição de 12 sementes antes do refactor da cascata"
```

---

## Task 2: `CostClass` e `WorkSet`

**Files:**
- Create: `src/orchestrator/workflow/__init__.py`, `src/orchestrator/workflow/cost_class.py`, `src/orchestrator/workflow/workset.py`
- Create: `tests/workflow/__init__.py`, `tests/workflow/test_workset.py`

**Interfaces:**
- Consumes: `orchestrator.models.BankEntry`, `LedgerEntry`, `MatchResult`, `Divergence`
- Produces:
  - `CostClass(IntEnum)` com membros `REGRA = 0`, `AGENTE = 1`, `HUMANO = 2`
  - `WorkSet(bank: list[BankEntry], ledger: list[LedgerEntry])`, frozen, com `as_divergences() -> list[Divergence]` e `without(matches: list[MatchResult]) -> WorkSet`

- [ ] **Step 1: Escrever os testes**

`tests/workflow/__init__.py` vazio. `tests/workflow/test_workset.py`:

```python
from orchestrator.models import MatchResult
from orchestrator.synth.generator import generate_clean_pairs
from orchestrator.workflow.cost_class import CostClass
from orchestrator.workflow.workset import WorkSet


def _duas_pontas():
    """Dois lançamentos de cada lado, pelo mesmo gerador que o resto da suíte usa."""
    pares = generate_clean_pairs(seed=2, n=2)
    return [p.bank for p in pares], [p.ledger for p in pares]


def test_ordem_das_classes_de_custo_e_regra_agente_humano():
    # A ordem é o produto, não um detalhe: é ela que impede um agente de
    # rodar antes de uma regra.
    assert CostClass.REGRA < CostClass.AGENTE < CostClass.HUMANO


def test_as_divergences_gera_uma_por_orfao_banco_primeiro():
    banco, contabil = _duas_pontas()
    work = WorkSet(bank=banco[:1], ledger=contabil[:1])

    divergencias = work.as_divergences()

    assert [d.id for d in divergencias] == [
        f"d-b-{banco[0].id}",
        f"d-l-{contabil[0].id}",
    ]
    assert divergencias[0].bank_ids == frozenset({banco[0].id})
    assert divergencias[0].ledger_ids == frozenset()
    assert divergencias[1].bank_ids == frozenset()
    assert divergencias[1].ledger_ids == frozenset({contabil[0].id})


def test_without_remove_os_dois_lados_do_vinculo():
    banco, contabil = _duas_pontas()
    work = WorkSet(bank=banco, ledger=contabil)
    m = MatchResult(
        bank_ids=frozenset({banco[0].id}),
        ledger_ids=frozenset({contabil[0].id}),
        layer="L1",
        rule="teste",
    )

    restante = work.without([m])

    assert [e.id for e in restante.bank] == [banco[1].id]
    assert [e.id for e in restante.ledger] == [contabil[1].id]


def test_without_sem_vinculo_nenhum_devolve_o_mesmo_conteudo():
    banco, contabil = _duas_pontas()

    restante = WorkSet(bank=banco, ledger=contabil).without([])

    assert [e.id for e in restante.bank] == [e.id for e in banco]
    assert [e.id for e in restante.ledger] == [e.id for e in contabil]


def test_without_devolve_objeto_novo_e_nao_muta_o_original():
    # WorkSet é passado de resolver em resolver. Se `without` mutasse, um
    # resolver enxergaria o pool que o próximo já alterou.
    banco, contabil = _duas_pontas()
    work = WorkSet(bank=banco, ledger=contabil)
    m = MatchResult(
        bank_ids=frozenset({banco[0].id}),
        ledger_ids=frozenset({contabil[0].id}),
        layer="L1",
        rule="teste",
    )

    restante = work.without([m])

    assert restante is not work
    assert len(work.bank) == 2
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/workflow/test_workset.py -q
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'orchestrator.workflow'`.

- [ ] **Step 3: Implementar**

`src/orchestrator/workflow/__init__.py` vazio. `src/orchestrator/workflow/cost_class.py`:

```python
"""A ordem entre classes de custo.

Esta enum é o mecanismo que impede a armadilha mais cara do produto: montar
uma cascata que chama inteligência antes de tentar a regra de graça. A ordem
não é uma convenção que alguém segue — é o valor pelo qual a cascata é
ordenada, e não existe entrada que a inverta.
"""

from enum import IntEnum


class CostClass(IntEnum):
    REGRA = 0
    AGENTE = 1
    HUMANO = 2
```

`src/orchestrator/workflow/workset.py`:

```python
"""O que ainda não foi resolvido quando um resolver é chamado."""

from dataclasses import dataclass

from orchestrator.models import BankEntry, Divergence, LedgerEntry, MatchResult


@dataclass(frozen=True)
class WorkSet:
    bank: list[BankEntry]
    ledger: list[LedgerEntry]

    def as_divergences(self) -> list[Divergence]:
        """Uma divergência por lançamento órfão, banco primeiro.

        Esta derivação morava dentro de `reconcile`. Ela vem para cá inteira,
        sem mudança de ordem nem de formato de id, porque o agente recebe
        exatamente esta lista e o golden da Task 1 a pina indiretamente.
        """
        return [
            Divergence(
                id=f"d-b-{e.id}", bank_ids=frozenset({e.id}), ledger_ids=frozenset()
            )
            for e in self.bank
        ] + [
            Divergence(
                id=f"d-l-{e.id}", bank_ids=frozenset(), ledger_ids=frozenset({e.id})
            )
            for e in self.ledger
        ]

    def without(self, matches: list[MatchResult]) -> "WorkSet":
        """O pool sem o que estes vínculos resolveram.

        Recebe `list[MatchResult]`, não `ResolverOutput`, de propósito: assim
        não existe assinatura pela qual uma proposta possa chegar aqui. A
        invariante "proposta não resolve" deixa de ser regra que alguém lembra
        e passa a ser coisa que o tipo não sabe expressar.
        """
        if not matches:
            return WorkSet(bank=list(self.bank), ledger=list(self.ledger))
        casados_banco = {i for m in matches for i in m.bank_ids}
        casados_contabil = {i for m in matches for i in m.ledger_ids}
        return WorkSet(
            bank=[e for e in self.bank if e.id not in casados_banco],
            ledger=[e for e in self.ledger if e.id not in casados_contabil],
        )
```

- [ ] **Step 4: Rodar e ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/workflow/ -q
./.venv/Scripts/python.exe -m ruff check src/orchestrator/workflow/ tests/workflow/
```

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/workflow/ tests/workflow/
git commit -m "feat: CostClass e WorkSet, as duas peças base da cascata"
```

---

## Task 3: O protocolo `Resolver`

**Files:**
- Create: `src/orchestrator/workflow/resolver.py`
- Create: `tests/workflow/test_resolver.py`

**Interfaces:**
- Consumes: `CostClass`, `WorkSet`, `orchestrator.agent.proposal.Cost`, `Proposal`, `orchestrator.models.MatchResult`
- Produces:
  - `ResolverOutput(matches=[], proposals=[], cost=Cost.zero())`, frozen, todos com default
  - `ResolverDescription(name: str, cost_class: CostClass, summary: str)`, frozen
  - `Resolver` Protocol: atributos `name: str`, `cost_class: CostClass`; métodos `resolve(work: WorkSet) -> ResolverOutput` e `describe() -> ResolverDescription`

- [ ] **Step 1: Escrever os testes**

`tests/workflow/test_resolver.py`:

```python
from orchestrator.agent.proposal import Cost
from orchestrator.models import MatchResult
from orchestrator.workflow.cost_class import CostClass
from orchestrator.workflow.resolver import ResolverDescription, ResolverOutput


def test_saida_vazia_e_o_default():
    # Um resolver que não resolveu nada é caso normal, não excepcional: ele
    # devolve ResolverOutput() e não precisa saber montar três coleções.
    saida = ResolverOutput()

    assert saida.matches == []
    assert saida.proposals == []
    assert saida.cost == Cost.zero()


def test_matches_e_proposals_sao_campos_separados():
    # O dia em que virarem um campo só com flag, a garantia de tipo que
    # impede conciliação fantasma some. Este teste existe para quebrar nesse
    # dia.
    m = MatchResult(
        bank_ids=frozenset({"b1"}),
        ledger_ids=frozenset({"l1"}),
        layer="L1",
        rule="teste",
    )
    saida = ResolverOutput(matches=[m])

    assert saida.matches == [m]
    assert saida.proposals == []


def test_descricao_carrega_a_classe_de_custo():
    d = ResolverDescription(
        name="L1", cost_class=CostClass.REGRA, summary="documento, valor e data iguais"
    )

    assert d.cost_class is CostClass.REGRA
    assert d.name == "L1"
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/workflow/test_resolver.py -q
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'orchestrator.workflow.resolver'`.

- [ ] **Step 3: Implementar**

`src/orchestrator/workflow/resolver.py`:

```python
"""O contrato único: regra, agente e humano com a mesma forma.

Antes deste módulo havia dois conceitos — `Matcher`, que casa, e
`Investigator`, que investiga — e por isso `reconcile` tinha dois parâmetros e
não havia cascata nenhuma no código. Ver o §1 do spec desta fatia.
"""

from dataclasses import dataclass, field
from typing import Protocol

from orchestrator.agent.proposal import Cost, Proposal
from orchestrator.models import MatchResult
from orchestrator.workflow.cost_class import CostClass
from orchestrator.workflow.workset import WorkSet


@dataclass(frozen=True)
class ResolverOutput:
    """O que um resolver produziu.

    `matches` e `proposals` são campos separados, e é deliberado: um match
    RESOLVE — sai do pool —, uma proposta apenas explica e o item continua
    divergente até um humano aprovar. Unificar os dois num tipo só com um
    campo de status transformaria uma garantia de tipo numa convenção
    verificada, e um filtro esquecido viraria conciliação fantasma.
    """

    matches: list[MatchResult] = field(default_factory=list)
    proposals: list[Proposal] = field(default_factory=list)
    cost: Cost = field(default_factory=Cost.zero)


@dataclass(frozen=True)
class ResolverDescription:
    """O que a API publica sobre um resolver. Dado, não comportamento."""

    name: str
    cost_class: CostClass
    summary: str


class Resolver(Protocol):
    """Uma tentativa de resolução dentro de uma cascata."""

    name: str
    cost_class: CostClass

    def resolve(self, work: WorkSet) -> ResolverOutput: ...

    def describe(self) -> ResolverDescription: ...
```

- [ ] **Step 4: Rodar e ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/workflow/ -q
./.venv/Scripts/python.exe -m ruff check src/orchestrator/workflow/ tests/workflow/
```

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/workflow/resolver.py tests/workflow/test_resolver.py
git commit -m "feat: protocolo Resolver, com matches e proposals em campos separados"
```

---

## Task 4: As três regras viram `Resolver` e `reconcile` roda a cascata

**Nota de escopo:** esta tarefa é maior que as outras de propósito. `reconcile` chama as três camadas uniformemente; converter uma de cada vez deixaria o repositório vermelho entre commits. Esta é a menor unidade que fecha verde. **O agente continua entrando pelo parâmetro `investigator=` antigo — ele é convertido na Task 5.**

**Files:**
- Modify: `src/orchestrator/matching/exact.py`, `tolerance.py`, `grouping.py`
- Modify: `src/orchestrator/matching/protocol.py` (remove `Matcher`)
- Modify: `src/orchestrator/matching/engine.py`
- Modify: `tests/matching/test_exact.py`, `test_tolerance.py`, `test_grouping.py`, `test_engine.py`, `tests/synth/test_injectors.py`, `tests/test_metrics.py`

**Interfaces:**
- Consumes: `Resolver`, `ResolverOutput`, `ResolverDescription`, `CostClass`, `WorkSet` (Tasks 2 e 3)
- Produces:
  - `ExactMatcher.name == "L1"`, `ToleranceMatcher.name == "L2"`, `GroupingMatcher.name == "L3"`, todas com `cost_class = CostClass.REGRA`
  - `orchestrator.matching.engine.default_resolvers() -> list[Resolver]` devolvendo `[ExactMatcher(), ToleranceMatcher(), GroupingMatcher()]`
  - `reconcile(bank, ledger, resolvers: list[Resolver] | None = None, investigator=None)`

- [ ] **Step 1: Escrever os testes de ordenação, que são o coração da tarefa**

Acrescente em `tests/matching/test_engine.py`:

```python
from orchestrator.workflow.cost_class import CostClass
from orchestrator.workflow.resolver import ResolverDescription, ResolverOutput
from orchestrator.workflow.workset import WorkSet


class _ResolverEspiao:
    """Registra a ordem em que foi chamado. Não resolve nada."""

    def __init__(self, name: str, cost_class: CostClass, registro: list[str]) -> None:
        self.name = name
        self.cost_class = cost_class
        self._registro = registro

    def resolve(self, work: WorkSet) -> ResolverOutput:
        self._registro.append(self.name)
        return ResolverOutput()

    def describe(self) -> ResolverDescription:
        return ResolverDescription(self.name, self.cost_class, "espião")


def test_agente_roda_depois_da_regra_mesmo_declarado_antes():
    # A ordem entre classes de custo é DERIVADA, não escolhida. Não existe
    # lista de entrada que ponha o agente na frente da regra — é isso que faz
    # a armadilha cara deixar de ser um erro possível.
    registro: list[str] = []
    cascata = [
        _ResolverEspiao("agente", CostClass.AGENTE, registro),
        _ResolverEspiao("regra", CostClass.REGRA, registro),
    ]

    reconcile([], [], resolvers=cascata)

    assert registro == ["regra", "agente"]


def test_ordem_dentro_da_mesma_classe_e_preservada():
    # Dentro da mesma classe de custo a ordem é conhecimento de domínio do
    # especialista e tem que sobreviver. Isso depende de `sorted` ser estável.
    registro: list[str] = []
    cascata = [
        _ResolverEspiao("segunda", CostClass.REGRA, registro),
        _ResolverEspiao("primeira", CostClass.REGRA, registro),
    ]

    reconcile([], [], resolvers=cascata)

    assert registro == ["segunda", "primeira"]


def test_proposta_nao_remove_nada_do_pool():
    # Um resolver que só propõe não pode encolher o pool. Se encolher, o item
    # sai de divergente sem ninguém ter aprovado nada.
    from orchestrator.agent.proposal import Confidence, Proposal
    from orchestrator.taxonomy import DivergenceType

    class _SoPropoe:
        name = "propositor"
        cost_class = CostClass.AGENTE

        def resolve(self, work: WorkSet) -> ResolverOutput:
            return ResolverOutput(
                proposals=[
                    Proposal(
                        divergence_id=d.id,
                        tipo=DivergenceType.NAO_IDENTIFICADO,
                        explicacao="",
                        evidencia=[],
                        confianca=Confidence.BAIXA,
                        acao_sugerida="investigar_manual",
                    )
                    for d in work.as_divergences()
                ]
            )

        def describe(self) -> ResolverDescription:
            return ResolverDescription(self.name, self.cost_class, "só propõe")

    sem = reconcile(BANCO_DE_TESTE, CONTABIL_DE_TESTE, resolvers=[])
    com = reconcile(BANCO_DE_TESTE, CONTABIL_DE_TESTE, resolvers=[_SoPropoe()])

    assert len(com.divergences) == len(sem.divergences)
    assert len(com.proposals) == len(sem.divergences)
```

Acrescente no topo do mesmo arquivo as duas constantes que esses testes usam:

```python
from orchestrator.cli import build_benchmark

# Benchmark pequeno com divergências garantidas: n=60 na semente 1 produz 6
# divergências, o suficiente para os testes de pool não serem degenerados.
_DATASET_DE_TESTE = build_benchmark(seed=1, n=60, taxa_divergencia=0.15)
BANCO_DE_TESTE = _DATASET_DE_TESTE.bank
CONTABIL_DE_TESTE = _DATASET_DE_TESTE.ledger
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/matching/test_engine.py -q
```

Esperado: FAIL — `reconcile() got an unexpected keyword argument 'resolvers'`.

- [ ] **Step 3: Converter `ExactMatcher`**

Em `src/orchestrator/matching/exact.py`, troque o cabeçalho da classe e a assinatura. **O corpo do algoritmo não muda uma linha** — só a fonte das listas e o embrulho do retorno:

```python
"""Camada L1: documento, valor e data idênticos."""

from datetime import date

from orchestrator.models import BankEntry, LedgerEntry, MatchResult
from orchestrator.workflow.cost_class import CostClass
from orchestrator.workflow.resolver import ResolverDescription, ResolverOutput
from orchestrator.workflow.workset import WorkSet


class ExactMatcher:
    name = "L1"
    cost_class = CostClass.REGRA

    def describe(self) -> ResolverDescription:
        return ResolverDescription(
            name=self.name,
            cost_class=self.cost_class,
            summary="documento, valor e data coincidem exatamente",
        )

    def resolve(self, work: WorkSet) -> ResolverOutput:
        return ResolverOutput(matches=self._casar(work.bank, work.ledger))

    def _casar(
        self, bank: list[BankEntry], ledger: list[LedgerEntry]
    ) -> list[MatchResult]:
        # corpo IDÊNTICO ao antigo `match`, com uma única troca:
        #   layer=self.layer   →   layer=self.name
        ...
```

Copie o corpo do `match` atual para `_casar` sem nenhuma outra alteração. `MatchResult.layer` continua existindo — é campo de proveniência, e `metrics.matches_by_layer` o consome como taxa por resolver.

- [ ] **Step 4: Converter `ToleranceMatcher` e `GroupingMatcher` do mesmo jeito**

Nos dois, o campo `layer: str = field(default="L2", init=False)` vira:

```python
    name: str = field(default="L2", init=False)
    cost_class: CostClass = field(default=CostClass.REGRA, init=False)
```

(`"L3"` no grouping.) Adicione `describe()` com o resumo respectivo — `"mesmo documento, com folga de valor e dias úteis"` para L2, `"um lançamento bancário cobrindo N contábeis do mesmo fornecedor"` para L3 — e renomeie `match` para `_casar`, acrescentando o `resolve` que embrulha. As validações de `__post_init__` ficam intactas.

- [ ] **Step 5: Remover `Matcher` e reescrever `reconcile`**

`src/orchestrator/matching/protocol.py` deixa de declarar `Matcher`. Se o arquivo ficar vazio, apague-o e remova os imports.

Em `src/orchestrator/matching/engine.py`:

```python
def default_resolvers() -> list[Resolver]:
    """As três regras, da mais barata para a mais cara dentro da classe."""
    return [ExactMatcher(), ToleranceMatcher(), GroupingMatcher()]


def reconcile(
    bank: list[BankEntry],
    ledger: list[LedgerEntry],
    resolvers: list[Resolver] | None = None,
    investigator: Investigator | None = None,
) -> ReconcileResult:
    cascata = default_resolvers() if resolvers is None else resolvers
    work = WorkSet(bank=list(bank), ledger=list(ledger))
    todos: list[MatchResult] = []
    propostas: list[Proposal] = []

    # `sorted` é estável: entre classes a ordem é derivada, dentro da classe a
    # ordem que veio na lista sobrevive. Uma linha entrega as duas regras.
    for resolver in sorted(cascata, key=lambda r: r.cost_class):
        saida = resolver.resolve(work)
        todos.extend(saida.matches)
        propostas.extend(saida.proposals)
        # Só `matches` encolhe o pool. `saida.proposals` não aparece aqui, e
        # é essa ausência que torna a invariante estrutural.
        work = work.without(saida.matches)

    divergencias = work.as_divergences()

    if investigator is None:
        return ReconcileResult(
            matches=todos, divergences=divergencias, proposals=propostas
        )

    saida_agente = investigator.investigate(divergencias)
    return ReconcileResult(
        matches=todos,
        divergences=divergencias,
        proposals=[*propostas, *saida_agente.proposals],
        agent_cost=saida_agente.cost,
    )
```

- [ ] **Step 6: Atualizar os testes que chamam `.match(`**

Em `tests/matching/test_exact.py`, `test_tolerance.py`, `test_grouping.py` e `tests/synth/test_injectors.py`, troque

```python
resultados = ExactMatcher().match(banco, contabil)
```

por

```python
resultados = ExactMatcher().resolve(WorkSet(bank=banco, ledger=contabil)).matches
```

e o import de `Matcher`/`default_matchers` por `default_resolvers`. Em `tests/test_metrics.py`, `default_matchers` → `default_resolvers`. **Não mude nenhuma asserção**: se uma delas precisar mudar de valor, o refactor está errado.

- [ ] **Step 7: Rodar tudo, com o golden como juiz**

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q
./.venv/Scripts/python.exe -m ruff check src/ tests/
```

Esperado: tudo passa, **incluindo `tests/test_golden.py`**. Se o golden falhar, o refactor mudou comportamento: conserte o código. Não regenere o golden.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: as três regras viram Resolver e reconcile roda uma cascata"
```

---

## Task 5: O agente entra na cascata

**Files:**
- Modify: `src/orchestrator/agent/investigator.py`
- Modify: `src/orchestrator/matching/engine.py` (remove o parâmetro `investigator` e o Protocol `Investigator`)
- Modify: `src/orchestrator/eval/agent_eval.py`
- Modify: `tests/agent/test_investigator.py`, `tests/matching/test_engine.py`, `tests/test_metrics.py`, `tests/eval/test_agent_eval.py`

**Interfaces:**
- Consumes: `Resolver`, `ResolverOutput`, `ResolverDescription`, `CostClass`, `WorkSet`
- Produces:
  - `Investigator.cost_class == CostClass.AGENTE`, `Investigator.name == "investigador"` (já é o default hoje)
  - `Investigator.resolve(work: WorkSet) -> ResolverOutput`
  - `reconcile(bank, ledger, resolvers=None)` — o parâmetro `investigator` deixa de existir

- [ ] **Step 1: Escrever o teste**

Em `tests/agent/test_investigator.py`:

```python
def test_investigador_e_um_resolver_da_classe_agente():
    inv = Investigator(client=FakeLLMClient(respostas=[]), context=CONTEXTO_DE_TESTE)

    assert inv.cost_class is CostClass.AGENTE
    assert inv.describe().name == "investigador"


def test_resolve_recebe_o_workset_e_devolve_propostas_sem_matches():
    # O agente propõe; nunca resolve. `matches` vazio não é detalhe de
    # implementação, é a invariante do produto.
    pares = generate_clean_pairs(seed=2, n=1)
    inv = Investigator(
        client=FakeLLMClient(respostas=[RESPOSTA_VALIDA] * 4),
        context=CONTEXTO_DE_TESTE,
    )
    work = WorkSet(bank=[pares[0].bank], ledger=[])

    saida = inv.resolve(work)

    assert saida.matches == []
    assert len(saida.proposals) == 1
    assert saida.cost.calls >= 1
```

`RESPOSTA_VALIDA` e `CONTEXTO_DE_TESTE`: reaproveite os que `tests/agent/test_investigator.py` já monta para os testes existentes — o arquivo tem ambos. Se estiverem inline dentro dos testes, extraia para constantes no topo sem mudar o conteúdo.

E em `tests/matching/test_engine.py`, um teste que pina o efeito do §3.3 do spec:

```python
def test_agente_na_cascata_recebe_as_mesmas_divergencias_que_recebia_por_parametro():
    # Quando o agente roda por último, `work.as_divergences()` produz
    # exatamente a lista que o parâmetro `investigator=` entregava. Este teste
    # é o que autoriza remover o parâmetro.
    registro: list[list[str]] = []

    class _RegistraDivergencias:
        name = "espiao"
        cost_class = CostClass.AGENTE

        def resolve(self, work: WorkSet) -> ResolverOutput:
            registro.append([d.id for d in work.as_divergences()])
            return ResolverOutput()

        def describe(self) -> ResolverDescription:
            return ResolverDescription(self.name, self.cost_class, "espião")

    esperado = reconcile(BANCO_DE_TESTE, CONTABIL_DE_TESTE)
    reconcile(
        BANCO_DE_TESTE,
        CONTABIL_DE_TESTE,
        resolvers=[*default_resolvers(), _RegistraDivergencias()],
    )

    assert registro == [[d.id for d in esperado.divergences]]
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/agent/test_investigator.py tests/matching/test_engine.py -q
```

Esperado: FAIL com `AttributeError: 'Investigator' object has no attribute 'cost_class'`.

- [ ] **Step 3: Converter o `Investigator`**

Em `src/orchestrator/agent/investigator.py`, acrescente ao dataclass:

```python
    name: str = field(default="investigador", init=False)
    cost_class: CostClass = field(default=CostClass.AGENTE, init=False)

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
```

`investigate` continua existindo e mantém a assinatura atual — é onde o laço mora, e os testes dele são muitos. `resolve` é a entrada uniforme.

- [ ] **Step 4: Remover o parâmetro `investigator` do `reconcile`**

Em `engine.py`: apague o Protocol `Investigator`, apague o parâmetro e os dois blocos de retorno condicional. O `reconcile` fica com o laço da Task 4 e um retorno só:

```python
    return ReconcileResult(
        matches=todos, divergences=divergencias, proposals=propostas
    )
```

`agent_cost` sai do retorno aqui — a Task 7 o substitui por `cost_by_resolver`. Até lá, mantenha o campo `agent_cost` em `ReconcileResult` somando o custo dos resolvers, para não quebrar `metrics.py` no meio do caminho:

```python
    custo_total = Cost.zero()
    for ... :            # no mesmo laço
        custo_total = custo_total + saida.cost
```

- [ ] **Step 5: Atualizar os chamadores**

Em `src/orchestrator/eval/agent_eval.py`, a linha

```python
    resultado = reconcile(dataset.bank, dataset.ledger, investigator=investigador)
```

vira

```python
    resultado = reconcile(
        dataset.bank, dataset.ledger, resolvers=[*default_resolvers(), investigador]
    )
```

com o import de `default_resolvers`. Em `tests/matching/test_engine.py` e `tests/test_metrics.py`, mesma troca.

- [ ] **Step 6: Rodar tudo**

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q
./.venv/Scripts/python.exe -m ruff check src/ tests/
```

O golden precisa continuar passando: o agente não muda nenhum número determinístico.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: o agente vira Resolver e o parâmetro investigator sai do reconcile"
```

---

## Task 6: `Stage` e `WorkflowDefinition`

**Files:**
- Create: `src/orchestrator/workflow/definition.py`
- Create: `tests/workflow/test_definition.py`
- Modify: `src/orchestrator/matching/engine.py`, `src/orchestrator/cli.py`, `src/orchestrator/eval/agent_eval.py`

**Interfaces:**
- Consumes: `Resolver`, `default_resolvers()`
- Produces:
  - `Stage(name: str, cascade: tuple[Resolver, ...])`, frozen
  - `WorkflowDefinition(id: str, name: str, stages: tuple[Stage, ...])`, frozen
  - `default_definition() -> WorkflowDefinition` com `id="conciliacao"`, um stage `"conciliar lançamentos"` e as três regras
  - `reconcile(bank, ledger, definition: WorkflowDefinition | None = None)` — `resolvers=` é substituído

- [ ] **Step 1: Escrever os testes**

`tests/workflow/test_definition.py`:

```python
from orchestrator.workflow.cost_class import CostClass
from orchestrator.workflow.definition import Stage, WorkflowDefinition, default_definition


def test_definicao_padrao_tem_as_tres_regras_num_stage():
    d = default_definition()

    assert d.id == "conciliacao"
    assert len(d.stages) == 1
    assert [r.name for r in d.stages[0].cascade] == ["L1", "L2", "L3"]


def test_definicao_padrao_nao_tem_agente():
    # O agente é opcional no conciliador e custa dinheiro. A definição padrão
    # — a que a API serve e a CLI executa — não o inclui, e é por isso que a
    # tela mostra uma LACUNA em vez de um selo sem medição.
    d = default_definition()

    classes = {r.cost_class for s in d.stages for r in s.cascade}
    assert classes == {CostClass.REGRA}


def test_stage_expoe_a_cascata_ordenada_por_classe_de_custo():
    # A ordenação acontece por stage, não global: um stage posterior não pode
    # ter seus resolvers embaralhados com os de um anterior.
    d = default_definition()
    cascata = d.stages[0].ordered()

    assert [r.cost_class for r in cascata] == sorted(r.cost_class for r in cascata)
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/workflow/test_definition.py -q
```

Esperado: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: Implementar**

`src/orchestrator/workflow/definition.py`:

```python
"""A definição de workflow: o objeto que o motor executa E que a API serializa.

Que seja o MESMO objeto nos dois lados é o ponto. Uma definição declarativa
paralela, que descrevesse o que o motor faz, permitiria drift entre o desenho
e a execução — e um desenho que não corresponde ao motor é a decoração que o
§3.5 do spec de composição nomeia como modo de falha.
"""

from dataclasses import dataclass

from orchestrator.matching.engine import default_resolvers
from orchestrator.workflow.resolver import Resolver


@dataclass(frozen=True)
class Stage:
    name: str
    cascade: tuple[Resolver, ...]

    def ordered(self) -> list[Resolver]:
        """A cascata na ordem em que roda.

        `sorted` é estável: a ordem entre classes de custo é derivada, a ordem
        dentro de uma classe é a que o autor da definição escreveu.
        """
        return sorted(self.cascade, key=lambda r: r.cost_class)


@dataclass(frozen=True)
class WorkflowDefinition:
    id: str
    name: str
    stages: tuple[Stage, ...]


def default_definition() -> WorkflowDefinition:
    """O conciliador determinístico.

    Sem agente: o agente é opcional, custa dinheiro, e a definição que a API
    serve precisa ser executável sem gastar um centavo. O que as regras não
    resolvem aparece como LACUNA na tela — que é informação, não omissão.
    """
    return WorkflowDefinition(
        id="conciliacao",
        name="Conciliação bancária",
        stages=(
            Stage(name="conciliar lançamentos", cascade=tuple(default_resolvers())),
        ),
    )
```

- [ ] **Step 4: `reconcile` passa a receber a definição**

Em `engine.py`, troque o parâmetro `resolvers` por `definition`, e o laço passa a ser aninhado:

```python
def reconcile(
    bank: list[BankEntry],
    ledger: list[LedgerEntry],
    definition: "WorkflowDefinition | None" = None,
) -> ReconcileResult:
    # Import local de propósito: `definition.py` importa `default_resolvers`
    # deste módulo, e um import de topo nos dois sentidos seria circular.
    from orchestrator.workflow.definition import default_definition

    definicao = default_definition() if definition is None else definition
    work = WorkSet(bank=list(bank), ledger=list(ledger))
    todos: list[MatchResult] = []
    propostas: list[Proposal] = []
    custo_total = Cost.zero()

    # A ordenação é POR STAGE, não global: um stage posterior não pode ter
    # seus resolvers embaralhados com os de um anterior. Com um stage só — o
    # caso de hoje — os dois dariam no mesmo; com dois, só este está certo.
    for stage in definicao.stages:
        for resolver in stage.ordered():
            saida = resolver.resolve(work)
            todos.extend(saida.matches)
            propostas.extend(saida.proposals)
            custo_total = custo_total + saida.cost
            # Só `matches` encolhe o pool. `saida.proposals` não aparece
            # nesta expressão, e é essa ausência que torna a invariante
            # estrutural em vez de uma regra que alguém precisa lembrar.
            work = work.without(saida.matches)

    return ReconcileResult(
        matches=todos,
        divergences=work.as_divergences(),
        proposals=propostas,
        agent_cost=custo_total,
    )
```

`agent_cost` continua aqui só até a Task 7, que o substitui por `cost_by_resolver`. Não o remova nesta tarefa: `metrics.py` ainda o lê.

- [ ] **Step 5: Atualizar os chamadores**

`cli.py` não muda (chama `reconcile(dataset.bank, dataset.ledger)`). Em `agent_eval.py`:

```python
    definicao = WorkflowDefinition(
        id="conciliacao-com-agente",
        name="Conciliação bancária com investigador",
        stages=(
            Stage(
                name="conciliar lançamentos",
                cascade=(*default_resolvers(), investigador),
            ),
        ),
    )
    resultado = reconcile(dataset.bank, dataset.ledger, definition=definicao)
```

Nos testes que passavam `resolvers=[...]`, monte uma `WorkflowDefinition` de um stage só com a mesma cascata.

- [ ] **Step 6: Rodar tudo**

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q
./.venv/Scripts/python.exe -m ruff check src/ tests/
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: WorkflowDefinition é o objeto que o motor executa"
```

---

## Task 7: Custo e taxa por resolver

**Files:**
- Modify: `src/orchestrator/matching/engine.py` (`ReconcileResult`)
- Modify: `src/orchestrator/metrics.py`
- Modify: `tests/test_metrics.py`, `tests/eval/test_agent_eval.py`

**Interfaces:**
- Consumes: `ReconcileResult`, `Cost`
- Produces:
  - `ReconcileResult.cost_by_resolver: dict[str, Cost]` substituindo `agent_cost`
  - `Metrics.cost_by_resolver_microcents: dict[str, int]`
  - `Metrics.matches_by_layer` continua existindo e é a contagem por resolver
  - `Metrics.agent_cost_microcents` passa a ser a **soma** de `cost_by_resolver_microcents`

- [ ] **Step 1: Escrever os testes**

Em `tests/test_metrics.py`:

```python
def test_custo_e_reportado_por_resolver_nao_so_no_total():
    # Um selo por resolver na tela precisa do custo DAQUELE resolver. Um
    # número só do sistema inteiro não responde "a camada L2 vale o que custa".
    dataset = build_benchmark(seed=1, n=100, taxa_divergencia=0.15)
    investigador = _investigador_falso()
    resultado = reconcile(dataset.bank, dataset.ledger, definition=_com_agente(investigador))

    m = evaluate(dataset, resultado, model="claude-opus-5")

    assert m.cost_by_resolver_microcents["L1"] == 0
    assert m.cost_by_resolver_microcents["investigador"] > 0
    assert m.agent_cost_microcents == sum(m.cost_by_resolver_microcents.values())


def test_resolver_que_nao_custou_nada_aparece_com_zero_e_nao_some():
    # Um resolver ausente do dicionário e um resolver de custo zero são
    # coisas diferentes na tela: um é "não rodou", o outro é "de graça".
    dataset = build_benchmark(seed=1, n=100, taxa_divergencia=0.15)
    resultado = reconcile(dataset.bank, dataset.ledger)

    m = evaluate(dataset, resultado)

    assert set(m.cost_by_resolver_microcents) == {"L1", "L2", "L3"}
    assert all(v == 0 for v in m.cost_by_resolver_microcents.values())
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_metrics.py -q
```

Esperado: FAIL com `AttributeError: 'Metrics' object has no attribute 'cost_by_resolver_microcents'`.

- [ ] **Step 3: Implementar**

Em `engine.py`, `ReconcileResult.agent_cost: Cost` vira:

```python
    # Custo por resolver, não do sistema. Um resolver que rodou e não custou
    # nada aparece com Cost.zero(); um que não rodou não aparece. A diferença
    # importa na tela: "de graça" e "não rodou" são coisas diferentes.
    cost_by_resolver: dict[str, Cost] = field(default_factory=dict)
```

e o laço preenche `custos[resolver.name] = saida.cost`.

Em `metrics.py`, `agent_cost_microcents=result.agent_cost.microcents(model)` vira:

```python
    custos = {
        nome: custo.microcents(model)
        for nome, custo in result.cost_by_resolver.items()
    }
```

e, no `return Metrics(...)` no fim da função, os dois campos passam a ser:

```python
        cost_by_resolver_microcents=custos,
        # A soma, não um campo próprio: um número que discorda da soma das
        # partes é a pior espécie de métrica.
        agent_cost_microcents=sum(custos.values()),
```

Todos os outros argumentos do `Metrics(...)` ficam como estão. Acrescente `cost_by_resolver_microcents: dict[str, int]` aos campos do dataclass, ao lado de `agent_cost_microcents`, e no `render()` uma linha por resolver logo abaixo do bloco "Resoluções por camada":

```python
        linhas.append("Custo por resolver:")
        for nome, micro in sorted(self.cost_by_resolver_microcents.items()):
            linhas.append(f"  {nome:<24} US$ {micro / 100_000_000:.6f}")
```

- [ ] **Step 4: Rodar tudo**

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q
./.venv/Scripts/python.exe -m ruff check src/ tests/
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: custo por resolver, não só do sistema"
```

---

## Task 8: A API serve a definição

**Files:**
- Modify: `pyproject.toml`
- Create: `src/orchestrator/api/__init__.py`, `src/orchestrator/api/schemas.py`, `src/orchestrator/api/app.py`
- Create: `tests/api/__init__.py`, `tests/api/test_definicao.py`

**Interfaces:**
- Consumes: `default_definition()`, `ResolverDescription`, `CostClass`
- Produces:
  - `orchestrator.api.app.app` — instância FastAPI
  - `GET /api/workflows/{workflow_id}` devolvendo `{"id", "name", "stages": [{"name", "cascade": [{"name", "cost_class", "summary"}]}]}`

- [ ] **Step 1: Declarar a dependência como extra**

Em `pyproject.toml`:

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.6", "httpx>=0.27"]
api = ["fastapi>=0.115", "uvicorn>=0.30"]
```

`httpx` entra em `dev` porque o `TestClient` do FastAPI precisa dele. Instale:

```bash
./.venv/Scripts/python.exe -m pip install -e ".[dev,api]"
```

- [ ] **Step 2: Escrever o teste anti-drift, que é o que importa nesta tarefa**

`tests/api/__init__.py` vazio. `tests/api/test_definicao.py`:

```python
from fastapi.testclient import TestClient

from orchestrator.api.app import app
from orchestrator.workflow.definition import default_definition

cliente = TestClient(app)


def test_json_da_definicao_bate_com_a_definicao_real():
    # ANTI-DRIFT. Se alguém hardcodar a cascata no schema, a tela passa a
    # desenhar uma coisa e o motor a executar outra — que é exatamente a
    # decoração do §3.5 do spec de composição. Este teste existe para tornar
    # isso impossível de passar despercebido.
    esperado = default_definition()

    corpo = cliente.get("/api/workflows/conciliacao").json()

    assert corpo["id"] == esperado.id
    assert [s["name"] for s in corpo["stages"]] == [s.name for s in esperado.stages]
    for stage_json, stage in zip(corpo["stages"], esperado.stages, strict=True):
        assert [r["name"] for r in stage_json["cascade"]] == [
            r.name for r in stage.ordered()
        ]


def test_cascata_vem_na_ordem_de_execucao_nao_na_de_declaracao():
    corpo = cliente.get("/api/workflows/conciliacao").json()
    classes = [r["cost_class"] for r in corpo["stages"][0]["cascade"]]

    assert classes == sorted(classes, key=["REGRA", "AGENTE", "HUMANO"].index)


def test_workflow_inexistente_da_404():
    assert cliente.get("/api/workflows/nao-existe").status_code == 404
```

- [ ] **Step 3: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/api/ -q
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'orchestrator.api'`.

- [ ] **Step 4: Implementar os schemas**

`src/orchestrator/api/schemas.py`:

```python
"""O contrato JSON, isolado do domínio.

Os schemas são construídos A PARTIR dos objetos do domínio, nunca escritos à
mão em paralelo a eles — ver o teste anti-drift.
"""

from pydantic import BaseModel

from orchestrator.workflow.definition import Stage, WorkflowDefinition


class ResolverJSON(BaseModel):
    name: str
    cost_class: str
    summary: str


class StageJSON(BaseModel):
    name: str
    cascade: list[ResolverJSON]


class WorkflowJSON(BaseModel):
    id: str
    name: str
    stages: list[StageJSON]


def stage_json(stage: Stage) -> StageJSON:
    return StageJSON(
        name=stage.name,
        cascade=[
            ResolverJSON(
                name=d.name, cost_class=d.cost_class.name, summary=d.summary
            )
            for d in (r.describe() for r in stage.ordered())
        ],
    )


def workflow_json(definicao: WorkflowDefinition) -> WorkflowJSON:
    return WorkflowJSON(
        id=definicao.id,
        name=definicao.name,
        stages=[stage_json(s) for s in definicao.stages],
    )
```

- [ ] **Step 5: Implementar o app**

`src/orchestrator/api/app.py`:

```python
"""O app HTTP do canvas.

Regra que governa este módulo: NENHUM endpoint daqui pode gastar dinheiro.
Não é uma flag a desligar — não existe caminho de código deste arquivo até o
modelo. Ver o §5 do spec desta fatia e o teste em `tests/api/test_execucao.py`.
"""

from fastapi import FastAPI, HTTPException

from orchestrator.api.schemas import WorkflowJSON, workflow_json
from orchestrator.workflow.definition import default_definition

app = FastAPI(title="Agent Orchestrator — canvas")

_WORKFLOWS = {"conciliacao": default_definition}


@app.get("/api/workflows/{workflow_id}", response_model=WorkflowJSON)
def obter_workflow(workflow_id: str) -> WorkflowJSON:
    fabrica = _WORKFLOWS.get(workflow_id)
    if fabrica is None:
        raise HTTPException(status_code=404, detail=f"workflow desconhecido: {workflow_id}")
    return workflow_json(fabrica())
```

- [ ] **Step 6: Rodar e ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/api/ -q
./.venv/Scripts/python.exe -m ruff check src/orchestrator/api/ tests/api/
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: API serve a definição do workflow, com teste anti-drift"
```

---

## Task 9: A execução medida, que não pode gastar dinheiro

**Files:**
- Modify: `src/orchestrator/api/schemas.py`, `src/orchestrator/api/app.py`
- Create: `tests/api/test_execucao.py`

**Interfaces:**
- Consumes: `build_benchmark`, `reconcile`, `evaluate`, `default_definition()`
- Produces: `POST /api/workflows/{workflow_id}/runs` recebendo `{"seed": int, "n": int, "taxa_divergencia": float}` e devolvendo `{"deterministic_rate", "bank_total", "by_resolver": [{"name","cost_class","matches","rate","microcents"}], "gap": {"items", "rate"}}`

- [ ] **Step 1: Escrever o teste do dinheiro, que é o teste mais importante do plano**

`tests/api/test_execucao.py`:

```python
import orchestrator.api.app as modulo_app
from fastapi.testclient import TestClient

from orchestrator.api.app import app

cliente = TestClient(app)


def test_execucao_nao_chama_o_modelo_de_jeito_nenhum(monkeypatch):
    """A promessa do §5.2 do spec, virada teste.

    Um endpoint HTTP apaga todas as barreiras que a CLI tem: um F5, um
    prefetch do navegador, uma aba esquecida aberta. Se algum dia alguém
    ligar o agente aqui, este teste quebra antes da fatura.
    """

    def _explode(*args, **kwargs):
        raise AssertionError("o endpoint tentou falar com o modelo")

    # Qualquer construção de cliente real passa por aqui.
    import orchestrator.agent.anthropic_client as ac

    monkeypatch.setattr(ac.AnthropicClient, "complete", _explode)

    resposta = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"seed": 1, "n": 100, "taxa_divergencia": 0.15},
    )

    assert resposta.status_code == 200


def test_execucao_reporta_taxa_e_custo_por_resolver():
    corpo = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"seed": 1, "n": 300, "taxa_divergencia": 0.15},
    ).json()

    nomes = [r["name"] for r in corpo["by_resolver"]]
    assert nomes == ["L1", "L2", "L3"]
    assert all(r["microcents"] == 0 for r in corpo["by_resolver"])
    assert 0.80 < corpo["deterministic_rate"] < 0.95


def test_a_lacuna_e_reportada_explicitamente():
    # A definição padrão não tem agente. O que as regras não resolvem não
    # some do relatório: vira lacuna com tamanho. É o §3.4 do spec de
    # composição — o ponto mais valioso da tela.
    corpo = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"seed": 1, "n": 300, "taxa_divergencia": 0.15},
    ).json()

    assert corpo["gap"]["items"] > 0
    soma = sum(r["rate"] for r in corpo["by_resolver"]) + corpo["gap"]["rate"]
    assert abs(soma - 1.0) < 1e-9


def test_n_invalido_da_422_em_vez_de_estourar():
    resposta = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"seed": 1, "n": 300, "taxa_divergencia": 5.0},
    )
    assert resposta.status_code == 422
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/api/test_execucao.py -q
```

Esperado: FAIL com 404 — a rota não existe.

- [ ] **Step 3: Implementar**

Acrescente a `schemas.py`:

```python
from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    seed: int = Field(default=1, ge=0)
    n: int = Field(default=300, ge=1, le=5000)
    taxa_divergencia: float = Field(default=0.15, ge=0.0, le=1.0)


class ResolverRunJSON(BaseModel):
    name: str
    cost_class: str
    matches: int
    rate: float
    microcents: int


class GapJSON(BaseModel):
    items: int
    rate: float


class RunJSON(BaseModel):
    seed: int
    n: int
    bank_total: int
    deterministic_rate: float
    by_resolver: list[ResolverRunJSON]
    gap: GapJSON
```

Os limites de `Field` fazem o FastAPI devolver 422 sozinho — é por isso que o teste de `taxa_divergencia=5.0` espera 422 e não 500.

Em `app.py`:

```python
from functools import lru_cache


@app.post("/api/workflows/{workflow_id}/runs", response_model=RunJSON)
def executar(workflow_id: str, pedido: RunRequest) -> RunJSON:
    fabrica = _WORKFLOWS.get(workflow_id)
    if fabrica is None:
        raise HTTPException(status_code=404, detail=f"workflow desconhecido: {workflow_id}")
    return _executar_memoizado(
        workflow_id, pedido.seed, pedido.n, pedido.taxa_divergencia
    )


@lru_cache(maxsize=64)
def _executar_memoizado(workflow_id: str, seed: int, n: int, taxa: float) -> RunJSON:
    """Determinístico por construção, então cacheável.

    A definição servida aqui não tem agente: a execução é pura, sem rede e sem
    custo. É isso que torna seguro um endpoint que qualquer F5 dispara.
    """
    dataset = build_benchmark(seed=seed, n=n, taxa_divergencia=taxa)
    definicao = _WORKFLOWS[workflow_id]()
    resultado = reconcile(dataset.bank, dataset.ledger, definition=definicao)
    m = evaluate(dataset, resultado)

    total = m.bank_total
    por_resolver = [
        ResolverRunJSON(
            name=d.name,
            cost_class=d.cost_class.name,
            matches=m.matches_by_layer.get(d.name, 0),
            rate=m.matches_by_layer.get(d.name, 0) / total if total else 0.0,
            microcents=m.cost_by_resolver_microcents.get(d.name, 0),
        )
        for stage in definicao.stages
        for d in (r.describe() for r in stage.ordered())
    ]
    resolvidos = sum(r.matches for r in por_resolver)
    return RunJSON(
        seed=seed,
        n=n,
        bank_total=total,
        deterministic_rate=m.deterministic_rate,
        by_resolver=por_resolver,
        gap=GapJSON(
            items=total - resolvidos,
            rate=(total - resolvidos) / total if total else 0.0,
        ),
    )
```

- [ ] **Step 4: Rodar tudo**

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q
./.venv/Scripts/python.exe -m ruff check src/ tests/
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: endpoint de execução medida, incapaz de gastar dinheiro"
```

---

## Task 10: O canvas

**Files:**
- Create: `web/index.html`, `web/style.css`, `web/canvas.js`
- Modify: `src/orchestrator/api/app.py` (servir estáticos)
- Create: `tests/api/test_estaticos.py`

**Interfaces:**
- Consumes: `GET /api/workflows/conciliacao`, `POST /api/workflows/conciliacao/runs`
- Produces: `GET /` servindo `web/index.html`

- [ ] **Step 1: Teste de que a página é servida**

`tests/api/test_estaticos.py`:

```python
from fastapi.testclient import TestClient

from orchestrator.api.app import app

cliente = TestClient(app)


def test_a_raiz_serve_a_pagina():
    resposta = cliente.get("/")

    assert resposta.status_code == 200
    assert "text/html" in resposta.headers["content-type"]
    assert "conciliar" in resposta.text.lower()
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/api/test_estaticos.py -q
```

Esperado: FAIL com 404.

- [ ] **Step 3: Servir os estáticos**

Em `app.py`:

```python
from pathlib import Path

from fastapi.staticfiles import StaticFiles

_WEB = Path(__file__).resolve().parents[3] / "web"

app.mount("/", StaticFiles(directory=_WEB, html=True), name="web")
```

O `mount` em `/` precisa vir **depois** das rotas `/api/...`, senão engole todas. Deixe-o como última linha do arquivo, com comentário dizendo isso.

Confira o `parents[3]`: de `src/orchestrator/api/app.py`, `parents[0]` é `api`, `[1]` é `orchestrator`, `[2]` é `src`, `[3]` é a raiz do repositório. Se a contagem estiver errada o teste quebra na hora.

- [ ] **Step 4: Escrever a página**

`web/index.html`:

```html
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Agent Orchestrator — cascata</title>
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <header>
    <h1 id="titulo">carregando…</h1>
    <p class="proveniencia" id="proveniencia"></p>
  </header>
  <main id="stages"></main>
  <script src="/canvas.js"></script>
</body>
</html>
```

`web/canvas.js`:

```js
// O canvas desenha o que a API mediu. Nenhum número é escrito aqui:
// se a API não mediu, a tela diz "não medido" em vez de inventar.
const PEDIDO = { seed: 1, n: 300, taxa_divergencia: 0.15 };

async function carregar() {
  const [definicao, execucao] = await Promise.all([
    fetch("/api/workflows/conciliacao").then((r) => r.json()),
    fetch("/api/workflows/conciliacao/runs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(PEDIDO),
    }).then((r) => r.json()),
  ]);

  document.getElementById("titulo").textContent = definicao.name;
  document.getElementById("proveniencia").textContent =
    `medido em ${execucao.bank_total} lançamentos sintéticos ` +
    `(semente ${execucao.seed}, n=${execucao.n})`;

  const porNome = new Map(execucao.by_resolver.map((r) => [r.name, r]));
  const alvo = document.getElementById("stages");
  alvo.innerHTML = "";

  for (const stage of definicao.stages) {
    const caixa = document.createElement("section");
    caixa.className = "stage";
    caixa.innerHTML = `<h2>${stage.name}</h2>`;

    stage.cascade.forEach((resolver, i) => {
      const medida = porNome.get(resolver.name);
      const linha = document.createElement("div");
      linha.className = "resolver";
      linha.innerHTML = `
        <span class="ordem">${i + 1}</span>
        <span class="nome" title="${resolver.summary}">${resolver.name}</span>
        <span class="classe classe-${resolver.cost_class.toLowerCase()}">${resolver.cost_class}</span>
        <span class="custo">${formatarCusto(medida)}</span>
        <span class="taxa">${formatarTaxa(medida)}</span>`;
      caixa.appendChild(linha);
    });

    caixa.appendChild(lacuna(execucao.gap));
    alvo.appendChild(caixa);
  }
}

function formatarCusto(medida) {
  if (!medida) return "não medido";
  return medida.microcents === 0
    ? "R$ 0"
    : `US$ ${(medida.microcents / 100000000).toFixed(6)}`;
}

function formatarTaxa(medida) {
  return medida ? `${(medida.rate * 100).toFixed(1)}%` : "—";
}

function lacuna(gap) {
  // A lacuna é o ponto mais valioso da tela: é onde o especialista diz
  // "tem regra sim, é o código de retorno do CNAB".
  const el = document.createElement("div");
  el.className = "resolver lacuna";
  el.innerHTML = `
    <span class="ordem">—</span>
    <span class="nome">sem resolver configurado</span>
    <span class="classe classe-lacuna">LACUNA</span>
    <span class="custo">—</span>
    <span class="taxa">${(gap.rate * 100).toFixed(1)}%</span>`;
  return el;
}

carregar().catch((erro) => {
  document.getElementById("titulo").textContent = "falhou ao carregar";
  document.getElementById("proveniencia").textContent = String(erro);
});
```

`web/style.css`:

```css
:root {
  --tinta: #1c1c1c;
  --fundo: #faf9f7;
  --borda: #d8d4cd;
  --regra: #2f7a4d;
  --agente: #a86a10;
  --humano: #2a5d9c;
  --lacuna: #8a6d1f;
  --lacuna-fundo: #fdf6e0;
}

body {
  margin: 0;
  padding: 2rem 1rem;
  background: var(--fundo);
  color: var(--tinta);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
}

header { max-width: 46rem; margin: 0 auto 1.5rem; }
h1 { font-size: 1.4rem; margin: 0 0 .25rem; }
.proveniencia { margin: 0; color: #6b6660; font-size: .85rem; }

main { max-width: 46rem; margin: 0 auto; }

.stage {
  border: 1px solid var(--borda);
  border-radius: 8px;
  background: #fff;
  padding: 1rem 1.25rem 1.25rem;
}
.stage h2 { font-size: 1rem; margin: 0 0 .75rem; font-weight: 600; }

.resolver {
  display: grid;
  grid-template-columns: 2rem 1fr 6rem 8rem 5rem;
  gap: .5rem;
  align-items: center;
  padding: .5rem 0;
  border-top: 1px solid #efece7;
}
.ordem { color: #9b958d; }
.nome { font-weight: 500; }
.custo, .taxa { font-family: ui-monospace, "SF Mono", Menlo, monospace; text-align: right; }

.classe {
  font-size: .7rem;
  letter-spacing: .04em;
  text-align: center;
  padding: .15rem .4rem;
  border-radius: 4px;
  border: 1px solid currentColor;
}
.classe-regra  { color: var(--regra); }
.classe-agente { color: var(--agente); }
.classe-humano { color: var(--humano); }
.classe-lacuna { color: var(--lacuna); }

/* A lacuna não é erro nem ausência: é o ponto da tela onde o especialista
   diz o que falta no catálogo. Ela tem que saltar aos olhos. */
.lacuna {
  background: var(--lacuna-fundo);
  border-top: 1px dashed var(--lacuna);
  margin: .25rem -1.25rem 0;
  padding: .5rem 1.25rem;
}
.lacuna .nome { color: var(--lacuna); }

@media (max-width: 34rem) {
  .resolver { grid-template-columns: 1.5rem 1fr 4.5rem; row-gap: .15rem; }
  .custo, .taxa { grid-column: 2 / 4; text-align: left; font-size: .85rem; }
}
```

- [ ] **Step 5: Ver com os próprios olhos**

```bash
./.venv/Scripts/python.exe -m uvicorn orchestrator.api.app:app --port 8000
```

Abra `http://localhost:8000`. Confira que as taxas dos três resolvers mais a lacuna somam 100%, e que a lacuna aparece marcada. Se algum selo mostrar `NaN` ou `undefined`, conserte antes de commitar.

- [ ] **Step 6: Rodar tudo e commitar**

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q
./.venv/Scripts/python.exe -m ruff check src/ tests/
git add -A
git commit -m "feat: canvas read-only desenhando a cascata medida"
```

---

## Task 11: Verificação final e fechamento

**Files:**
- Modify: `docs/superpowers/specs/2026-09-15-cascata-e-canvas-design.md` (§6)
- Create: `docs/superpowers/DECISOES.md` (acrescentar seção deste plano)
- Modify: `README.md` se existir

**Interfaces:**
- Consumes: tudo
- Produces: nada de código

- [ ] **Step 1: Provar que nenhum número mudou**

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q
./.venv/Scripts/python.exe -m tests.golden.gerar
git diff --exit-code tests/golden/cascata_12_sementes.json
```

O `git diff --exit-code` tem que sair **limpo**. Se sair sujo, o refactor mudou comportamento e o plano não está pronto, por mais verde que a suíte esteja.

- [ ] **Step 2: Rodar a CLI e conferir o número contra o spec**

```bash
./.venv/Scripts/python.exe -m orchestrator.cli --seed 1 --n 500
```

A taxa determinística tem que sair **85,3%**, o mesmo valor registrado no §2.3 do spec pai. Falsos positivos e negativos, zero.

- [ ] **Step 3: Corrigir o §6 do spec desta fatia**

O mock do §6 mostra uma linha `④ investigar AGENTE não medido 12,8%`. A definição padrão **não tem agente** — o que sobra vira LACUNA. Troque o bloco pelo que a tela realmente desenha:

```
┌─ conciliar lançamentos ─────────────────────────────┐
│  ① L1   REGRA    R$0      82,4% ●                   │
│  ② L2   REGRA    R$0       3,1% ●                   │
│  ③ L3   REGRA    R$0       1,7% ●                   │
│  —  sem resolver configurado  LACUNA   12,8% ◌      │
└─────────────────────────────────────────────────────┘
```

E acrescente um parágrafo: a lacuna é mais honesta que um selo de agente sem medição, e é o §3.4 do spec de composição — o ponto onde o especialista diz o que falta no catálogo.

**Mova o §5.3 para o anti-escopo, com gatilho.** A consequência de a definição padrão não ter agente é que o caminho "selo do agente vem de gravação" deixa de ser trabalho desta fatia. Ele continua sendo o desenho certo — não gastar por request e declarar procedência —, mas só tem o que medir quando existir uma segunda definição, com agente, e uma gravação. Acrescente à tabela do §2:

| Não construir agora | Desbloqueia quando |
|---|---|
| Selo do agente por replay de gravação (§5.3) | Houver crédito de API, uma gravação do benchmark, e uma definição `conciliacao-com-agente` para servir |

- [ ] **Step 4: Registrar as decisões tomadas sem consultar**

Acrescente a `docs/superpowers/DECISOES.md` uma seção `## Plano 3 — cascata e canvas`, seguindo o formato das seções dos planos 1 e 2: uma linha por decisão, com a alternativa rejeitada e o custo de estar errado. No mínimo estas: o import local em `reconcile` para evitar ciclo, `investigate()` mantido ao lado de `resolve()`, `MatchResult.layer` não renomeado, `lru_cache` no endpoint de execução, e a lacuna no lugar do selo de agente.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "docs: fecha o plano 3 — golden reproduzido, spec corrigido, decisões registradas"
```

---

## Verificação final do plano

- [ ] `pytest tests/ -q` verde, incluindo `tests/test_golden.py`
- [ ] `git diff --exit-code tests/golden/cascata_12_sementes.json` limpo após regenerar
- [ ] `ruff check src/ tests/` limpo
- [ ] CLI na semente 1, n=500: 85,3%, zero FP, zero FN
- [ ] `grep -rn "proposals" src/orchestrator/matching/engine.py` não mostra `proposals` em nenhuma expressão que calcule o pool restante
- [ ] `grep -rn "Matcher\b" src/` só encontra os nomes de classe `ExactMatcher`/`ToleranceMatcher`/`GroupingMatcher`, nunca o Protocol
- [ ] `tests/api/test_execucao.py::test_execucao_nao_chama_o_modelo_de_jeito_nenhum` passa
- [ ] A página em `http://localhost:8000` desenha três resolvers e uma lacuna, somando 100%
