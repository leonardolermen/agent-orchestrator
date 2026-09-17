# Execução como grafo — Plano de implementação (X1–X6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dar ao kernel a capacidade de PRODUZIR trabalho, não só consumi-lo, de modo que pipeline, ramificação, laço e tarefa única passem a caber no mesmo motor que já roda a cascata de custo.

**Architecture:** Quadro-negro. `ResolverOutput` ganha `produced`; o motor passa de `work.without(r)` para `work.without(r).com(p)`. `Stage` declara `consome`/`produz`, e o encadeamento entre degraus é derivado do `kind` dos itens — sem `if`, sem predicado, sem contexto global. O laço externo roda até ponto fixo, com teto. Um tipo novo, `Tarefa`, transforma item em item; `Agent` continua só propondo.

**Tech Stack:** Python 3.13, dataclasses congelados, pytest, ruff. Zero dependências novas.

**Spec:** `docs/superpowers/specs/2026-09-17-execucao-como-grafo-design.md`

## Global Constraints

- **Os 844 testes existentes passam sem serem tocados.** Se um teste precisar de edição, o default da peça nova está errado. Esse é o critério de aceite de toda tarefa de kernel (spec §8).
- **`kernel/` não importa nada.** Imposto por `tests/arquitetura/test_camadas.py`. Nenhuma tarefa aqui adiciona import ao kernel além de `kernel → kernel`.
- **Proposta não resolve e não produz.** `Proposal` não entra em `WorkSet.without()` nem em `WorkSet.com()`. A garantia é do tipo, não da disciplina (spec §3).
- **Dinheiro e custo em inteiro de micro-centavos.** Ponto flutuante proibido.
- **Configuração inválida falha alto, na construção.** Nunca vira abstenção silenciosa.
- **Código e comentários em português**, seguindo o repositório. Docstring explica POR QUE, não O QUE.
- Rodar a suíte: `./.venv/Scripts/python.exe -m pytest -q`. Lint: `./.venv/Scripts/python.exe -m ruff check src tests`.

## Estrutura de arquivos

| Arquivo | Responsabilidade | Tarefas |
|---|---|---|
| `src/orchestrator/kernel/work.py` | `WorkItem.origem`, `WorkSet.com()` | 1 |
| `src/orchestrator/kernel/resolver.py` | `ResolverOutput.produced` | 2 |
| `src/orchestrator/kernel/event.py` | `EventKind.ITEM_PRODUZIDO` | 2 |
| `src/orchestrator/runtime/engine.py` | aplicar `produced`, filtrar por kind, laço até ponto fixo | 2, 3, 5 |
| `src/orchestrator/kernel/definition.py` | `Stage.consome`/`produz`, `max_rondas`, `entrega`, guarda de beco sem saída, `version` | 3, 4 |
| `src/orchestrator/kernel/run.py` | `RunState.LIMITE_DE_RONDAS`, `Run.rondas` | 5 |
| `src/orchestrator/agent/conversa.py` **(novo)** | o laço de turnos, extraído e genérico | 6 |
| `src/orchestrator/agent/agent.py` | `Agent` passa a usar o laço extraído | 6 |
| `src/orchestrator/agent/tarefa.py` **(novo)** | `Tarefa`, `TarefaSpec`, `Transformador`, `SaidaDaTarefa` | 7 |
| `src/orchestrator/domains/redacao/workflow.py` **(novo)** | o pipeline que prova o desenho | 8 |

---

### Task 1: `WorkItem.origem` e `WorkSet.com()`

O pool só sabe encolher. Ganha o espelho, e os itens ganham proveniência.

**Files:**
- Modify: `src/orchestrator/kernel/work.py`
- Test: `tests/kernel/test_work.py`

**Interfaces:**
- Consumes: nada (primeira tarefa)
- Produces:
  - `WorkItem(id: str, kind: str, payload: Any, origem: str = "")`
  - `WorkSet.com(self, novos: Iterable[WorkItem]) -> WorkSet`

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar ao fim de `tests/kernel/test_work.py`:

```python
def test_com_acrescenta_preservando_ordem():
    """A ordem é contrato, não estética: o golden de 12 sementes depende dela.

    Item produzido entra no FIM. Entrar no começo faria um item novo ser visto
    antes de itens que já estavam esperando, e a ordem de saída mudaria por
    causa de quem produziu, não de quem chegou.
    """
    pool = _pool("a", "b")

    novo = pool.com([WorkItem(id="c", kind="coisa", payload="c", origem="escritor")])

    assert [i.id for i in novo.items] == ["a", "b", "c"]
    # O pool original não muda: `WorkSet` é imutável de verdade.
    assert [i.id for i in pool.items] == ["a", "b"]


def test_com_vazio_devolve_o_mesmo_pool():
    """Simetria com `without()`, que já devolve `self` quando nada foi
    consumido. Sem isso, uma ronda sem produção alocaria um pool novo por
    stage, e o laço da Task 5 chama isto por stage por ronda."""
    pool = _pool("a")

    assert pool.com([]) is pool


def test_com_recusa_id_que_ja_existe():
    """A guarda de id repetido de `__post_init__` vale para produção também.

    Um resolver que produz um id já presente faria `without()` remover os dois
    ao resolver um — exatamente o defeito que `test_pool_recusa_id_repetido`
    previne na construção.
    """
    pool = _pool("a")

    with pytest.raises(ValueError, match="id repetido"):
        pool.com([WorkItem(id="a", kind="coisa", payload="outro")])


def test_origem_default_e_vazia():
    """Item que veio da fonte não tem origem — ninguém o produziu. String
    vazia, não `None`: o campo é sempre legível, e serializar `None` num
    trace obrigaria todo consumidor a tratar dois casos."""
    assert WorkItem(id="a", kind="coisa", payload=1).origem == ""
    assert WorkItem(id="b", kind="coisa", payload=1, origem="x").origem == "x"
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/kernel/test_work.py -q
```

Esperado: 4 falhas — `AttributeError: 'WorkSet' object has no attribute 'com'` e `TypeError: WorkItem.__init__() got an unexpected keyword argument 'origem'`.

- [ ] **Step 3: Implementar**

Em `src/orchestrator/kernel/work.py`, acrescentar o campo a `WorkItem`, logo após `payload`:

```python
    payload: Any
    # Qual resolver produziu este item. Vazio quando ele veio da fonte.
    #
    # Sem proveniência a cadeia de auditoria quebra no PRIMEIRO salto: com um
    # pool que transforma, "de onde veio este rascunho" deixa de ter resposta
    # assim que existe mais de um produtor, e o replay não consegue
    # reconstruir o caminho. É a mesma razão de `Resolution.produced_by`.
    origem: str = ""
```

E o método, logo após `without()`:

```python
    def com(self, novos: Iterable[WorkItem]) -> "WorkSet":
        """O pool mais os itens que um resolver produziu.

        O espelho de `without()`, e a peça que transforma a cascata em grafo:
        sem produzir, um stage só recebe o que o anterior NÃO resolveu, e não
        existe fluxo de dado para frente.

        Recebe `WorkItem`, NUNCA um `ResolverOutput` — pelo mesmo motivo que
        `without()` recebe `Resolution`. Não existe assinatura pela qual uma
        PROPOSTA chegue aqui, e é isso que mantém "proposta não resolve" como
        coisa que o tipo não sabe expressar, agora que há uma segunda maneira
        de o pool mudar.

        A validação de id repetido não é feita aqui: `__post_init__` já a faz,
        e duplicá-la criaria duas mensagens de erro para a mesma falha.
        """
        novos = tuple(novos)
        if not novos:
            return self
        return WorkSet(items=self.items + novos)
```

- [ ] **Step 4: Rodar os testes**

```bash
./.venv/Scripts/python.exe -m pytest tests/kernel/test_work.py -q
```

Esperado: PASS.

- [ ] **Step 5: Rodar a suíte inteira — nenhum teste pode ter sido tocado**

```bash
./.venv/Scripts/python.exe -m pytest -q
```

Esperado: 848 passed (844 + os 4 novos). Se algum dos 844 falhar, o default de `origem` está errado.

- [ ] **Step 6: Commit**

```bash
git add src/orchestrator/kernel/work.py tests/kernel/test_work.py
git commit -m "feat(kernel): o pool ganha a operacao inversa — WorkSet.com e WorkItem.origem"
```

---

### Task 2: `ResolverOutput.produced` e o motor aplicando produção

O campo, e a única expressão do motor que precisa mudar para o fluxo para frente existir.

**Files:**
- Modify: `src/orchestrator/kernel/resolver.py`
- Modify: `src/orchestrator/kernel/event.py`
- Modify: `src/orchestrator/runtime/engine.py` (a linha `work = work.without(saida.resolutions)`)
- Test: `tests/runtime/test_producao.py` (criar)

**Interfaces:**
- Consumes: `WorkSet.com()` da Task 1
- Produces:
  - `ResolverOutput(resolutions, proposals, produced: tuple[WorkItem, ...] = (), cost)`
  - `EventKind.ITEM_PRODUZIDO`
  - O motor aplica: `work = work.without(saida.resolutions).com(saida.produced)`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/runtime/test_producao.py`:

```python
"""O pool que transforma: um stage vê o que o anterior produziu.

Nenhum teste aqui menciona conciliação, e é o ponto — a mesma disciplina de
`tests/kernel/test_work.py`.
"""

from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.definition import Stage, WorkflowDefinition
from orchestrator.kernel.resolution import Resolution
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.runtime.engine import execute


class Transformador:
    """Consome todo item de um kind e produz um de outro. Resolver de teste."""

    cost_class = CostClass.REGRA

    def __init__(self, name: str, de: str, para: str) -> None:
        self.name = name
        self._de = de
        self._para = para

    def describe(self) -> ResolverDescription:
        return ResolverDescription(self.name, self.cost_class, "teste")

    def resolve(self, work: WorkSet) -> ResolverOutput:
        resolucoes, produzidos = [], []
        for item in work.of_kind(self._de):
            resolucoes.append(
                Resolution(
                    item_ids=frozenset({item.id}),
                    produced_by=self.name,
                    rule="transformou",
                )
            )
            produzidos.append(
                WorkItem(
                    id=f"{item.id}+{self._para}",
                    kind=self._para,
                    payload=f"{item.payload}/{self.name}",
                    origem=self.name,
                )
            )
        return ResolverOutput(
            resolutions=resolucoes, produced=tuple(produzidos), cost=Cost.zero()
        )


def test_produced_default_e_vazio():
    """Todo resolver de hoje devolve `ResolverOutput` sem `produced`. O default
    é o que mantém os 844 testes intocados."""
    assert ResolverOutput().produced == ()


def test_o_stage_seguinte_ve_o_que_o_anterior_produziu():
    """A asserção que não passava antes desta fatia: encadeamento por DADO.

    Sem `produced`, o stage 2 receberia só o que o stage 1 não resolveu — e o
    stage 1 resolveu tudo. O pipeline inteiro devolveria pool vazio.
    """
    d = WorkflowDefinition(
        id="pipeline",
        name="dois passos",
        stages=(
            Stage(
                name="um",
                cascade=(Transformador("um", "a", "b"),),
                produz=frozenset({"b"}),
            ),
            Stage(
                name="dois",
                cascade=(Transformador("dois", "b", "c"),),
                produz=frozenset({"c"}),
            ),
        ),
    )
    pool = WorkSet(items=(WorkItem(id="i", kind="a", payload="x"),))

    r = execute(d, pool)

    # O item atravessou os dois degraus: a -> b -> c.
    assert [i.kind for i in r.unresolved.items] == ["c"]
    assert r.unresolved.items[0].payload == "x/um/dois"
    # Proveniência preservada em cada salto.
    assert r.unresolved.items[0].origem == "dois"
    # Duas resoluções: cada transformação CONSOME o item que leu.
    assert len(r.resolutions) == 2


def test_producao_nao_apaga_a_resolucao_que_a_acompanha():
    """Transformar É resolver: o item lido sai do pool pela porta de sempre."""
    d = WorkflowDefinition(
        id="um",
        name="um passo",
        stages=(
            Stage(
                name="um",
                cascade=(Transformador("um", "a", "b"),),
                produz=frozenset({"b"}),
            ),
        ),
    )
    pool = WorkSet(items=(WorkItem(id="i", kind="a", payload="x"),))

    r = execute(d, pool)

    assert "i" not in r.unresolved.ids()
    assert r.resolutions[0].item_ids == frozenset({"i"})
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/runtime/test_producao.py -q
```

Esperado: `TypeError: ResolverOutput.__init__() got an unexpected keyword argument 'produced'`.

- [ ] **Step 3: Implementar o campo**

Em `src/orchestrator/kernel/resolver.py`, acrescentar o import de `WorkItem` (já importa `WorkSet` do mesmo módulo — `kernel → kernel` é permitido) e o campo:

```python
from orchestrator.kernel.work import WorkItem, WorkSet
```

```python
    resolutions: list[Resolution] = field(default_factory=list)
    proposals: list[Proposal] = field(default_factory=list)
    # O que este resolver CRIOU. Campo separado de `resolutions` pela mesma
    # razão que `proposals` é separado: resolução consome, produção cria, e um
    # tipo único com campo de status transformaria duas garantias de tipo numa
    # convenção que alguém precisa verificar.
    #
    # `proposals` não aparece em nenhuma das duas expressões do motor
    # (`without` e `com`), e é essa ausência — agora que há DUAS maneiras de o
    # pool mudar — que mantém "proposta não resolve" estrutural.
    produced: tuple[WorkItem, ...] = ()
    cost: Cost = field(default_factory=Cost.zero)
```

- [ ] **Step 4: Implementar o evento**

Em `src/orchestrator/kernel/event.py`, acrescentar ao `EventKind`, junto de `ITEM_RESOLVIDO`:

```python
    ITEM_PRODUZIDO = "item.produzido"
```

- [ ] **Step 5: Implementar a mudança no motor**

Em `src/orchestrator/runtime/engine.py`, trocar a linha `work = work.without(saida.resolutions)` e o comentário acima dela por:

```python
            # Só `resolutions` encolhe o pool e só `produced` o aumenta.
            # `saida.proposals` não aparece em nenhuma das duas expressões, e é
            # essa ausência que torna a invariante estrutural em vez de uma
            # regra que alguém precisa lembrar.
            work = work.without(saida.resolutions).com(saida.produced)
```

E emitir o evento, logo após o laço que emite `ITEM_RESOLVIDO`:

```python
            for novo in saida.produced:
                emitir(
                    EventKind.ITEM_PRODUZIDO,
                    resolver=resolver.name,
                    item=novo.id,
                    # `item_kind`, não `kind`: `emitir()` já usa `kind` para o
                    # tipo do evento, e um payload `kind=` colidiria com esse
                    # parâmetro (`TypeError: got multiple values for 'kind'`).
                    item_kind=novo.kind,
                )
```

E acrescentar `produziu=len(saida.produced)` ao payload de `RESOLVER_CONCLUIDO`, junto de `resolveu` e `propos`.

- [ ] **Step 6: Rodar os testes novos**

```bash
./.venv/Scripts/python.exe -m pytest tests/runtime/test_producao.py -q
```

Esperado: PASS.

- [ ] **Step 7: Rodar a suíte inteira**

```bash
./.venv/Scripts/python.exe -m pytest -q
```

Esperado: os 844 originais passam, mais os testes novos deste arquivo. Nenhum dos 844 tocado.

- [ ] **Step 8: Commit**

```bash
git add src/orchestrator/kernel/resolver.py src/orchestrator/kernel/event.py src/orchestrator/runtime/engine.py tests/runtime/test_producao.py
git commit -m "feat(kernel): ResolverOutput.produced — o encadeamento por dado passa a existir"
```

---

### Task 3: `Stage.consome`, `Stage.produz` e o filtro por kind

Ramificação sem `if` no kernel, e a guarda que impede `produz` de virar documentação.

**Files:**
- Modify: `src/orchestrator/kernel/definition.py`
- Modify: `src/orchestrator/runtime/engine.py`
- Test: `tests/runtime/test_producao.py` (acrescentar)

**Interfaces:**
- Consumes: `ResolverOutput.produced` da Task 2
- Produces:
  - `Stage(name, cascade, consome: frozenset[str] = frozenset(), produz: frozenset[str] = frozenset(), policy)`
  - O motor filtra o pool por `consome` antes de chamar os resolvers do stage
  - O motor levanta `ValueError` quando um resolver produz kind fora do `produz` do stage

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar a `tests/runtime/test_producao.py`. **O `import pytest` vai no TOPO
do arquivo, junto dos outros imports** — no meio do módulo ele é `E402` e o
ruff quebra o commit.

```python
# (topo do arquivo, junto dos imports existentes)
import pytest


def test_o_stage_so_ve_os_kinds_que_declara_consumir():
    """`consome` é o que separa dois caminhos num pool heterogêneo."""
    d = WorkflowDefinition(
        id="dois-caminhos",
        name="dois caminhos",
        stages=(
            Stage(
                name="cuida do a",
                cascade=(Transformador("ta", "a", "z"),),
                consome=frozenset({"a"}),
                produz=frozenset({"z"}),
            ),
        ),
    )
    pool = WorkSet(
        items=(
            WorkItem(id="i1", kind="a", payload="x"),
            WorkItem(id="i2", kind="b", payload="y"),
        )
    )

    r = execute(d, pool)

    # O item de kind "b" nunca foi oferecido ao stage, e continua intacto.
    assert {i.id for i in r.unresolved.items} == {"i1+z", "i2"}


def test_o_stage_sem_item_do_seu_kind_nao_roda():
    """A CONDICIONAL do kernel: ausência de item, nunca um predicado.

    É isto que dá ramificação sem o kernel ganhar linguagem de expressão — e
    é por isso que a §10 do spec pode dizer "não vira n8n" e ser verdade.
    """
    d = WorkflowDefinition(
        id="ramo-morto",
        name="ramo morto",
        stages=(
            Stage(
                name="urgente",
                cascade=(Transformador("u", "urgente", "z"),),
                consome=frozenset({"urgente"}),
                produz=frozenset({"z"}),
            ),
        ),
    )
    pool = WorkSet(items=(WorkItem(id="i", kind="normal", payload="x"),))

    r = execute(d, pool)

    assert r.resolutions == ()
    # O resolver não rodou: não há custo registrado para ele.
    assert "u" not in r.cost_by_resolver
    assert [i.id for i in r.unresolved.items] == ["i"]


def test_consome_vazio_continua_vendo_o_pool_inteiro():
    """O default reproduz a semântica de hoje. É o que mantém as 9 definições
    existentes e os 844 testes sem edição."""
    d = WorkflowDefinition(
        id="tudo",
        name="tudo",
        # `consome` fica vazio DE PROPOSITO — e o que este teste prova.
        # `produz` e declarado porque a guarda do motor e incondicional.
        stages=(
            Stage(
                name="um",
                cascade=(Transformador("um", "a", "b"),),
                produz=frozenset({"b"}),
            ),
        ),
    )
    pool = WorkSet(
        items=(
            WorkItem(id="i1", kind="a", payload="x"),
            WorkItem(id="i2", kind="a", payload="y"),
        )
    )

    r = execute(d, pool)

    assert len(r.resolutions) == 2


def test_produzir_kind_nao_declarado_e_erro_alto():
    """`produz` DECLARADO só vale se o runtime o impuser.

    Sem esta guarda, `produz` seria documentação — e documentação que o
    runtime não impõe desatualiza em silêncio, levando a recusa de beco sem
    saída (Task 4) e as arestas do canvas a mentirem juntas.
    """
    d = WorkflowDefinition(
        id="mentiroso",
        name="mentiroso",
        stages=(
            Stage(
                name="um",
                cascade=(Transformador("um", "a", "b"),),
                consome=frozenset({"a"}),
                produz=frozenset({"outro"}),  # promete "outro", entrega "b"
            ),
        ),
    )
    pool = WorkSet(items=(WorkItem(id="i", kind="a", payload="x"),))

    with pytest.raises(ValueError, match="produziu kind não declarado"):
        execute(d, pool)


def test_stages_nao_sao_reordenados_por_custo():
    """Os DOIS EIXOS, e a §5.1 do spec vira asserção aqui.

    Dentro de um stage a ordem é CUSTO — quem tenta primeiro no mesmo
    trabalho. Entre stages a ordem é DADO — quem precisa da saída de quem.
    Ordenar por custo entre stages seria escrever antes de pesquisar.

    O teste monta um pipeline em que o segundo degrau é MAIS BARATO que o
    primeiro. Se alguém algum dia aplicar `ordered()` globalmente, o barato
    rodaria antes, não acharia item do seu kind, e o pipeline devolveria o
    item parado no meio.
    """

    class Caro(Transformador):
        cost_class = CostClass.AGENTE

    d = WorkflowDefinition(
        id="ordem",
        name="ordem",
        stages=(
            Stage(
                name="caro primeiro",
                cascade=(Caro("caro", "a", "b"),),
                consome=frozenset({"a"}),
                produz=frozenset({"b"}),
            ),
            Stage(
                name="barato depois",
                cascade=(Transformador("barato", "b", "c"),),  # REGRA, mais barato
                consome=frozenset({"b"}),
                produz=frozenset({"c"}),
            ),
        ),
    )
    pool = WorkSet(items=(WorkItem(id="i", kind="a", payload="x"),))

    r = execute(d, pool)

    assert [i.kind for i in r.unresolved.items] == ["c"]
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/runtime/test_producao.py -q
```

Esperado: `TypeError: Stage.__init__() got an unexpected keyword argument 'consome'`.

- [ ] **Step 3: Implementar os campos**

Em `src/orchestrator/kernel/definition.py`, em `Stage`, entre `cascade` e `policy`:

```python
    # Quais `kind` de item este degrau consome. VAZIO = o pool inteiro, que é
    # exatamente o comportamento anterior a esta fatia — e é o que mantém as 9
    # definições existentes sem edição.
    #
    # A CONDICIONAL do kernel mora aqui: um stage cujo `consome` não casa com
    # nada simplesmente não roda. É ausência de item, não predicado, e é por
    # isso que o kernel não ganha linguagem de expressão.
    consome: frozenset[str] = frozenset()
    # Quais `kind` este degrau pode produzir. DECLARADO, não observado:
    # a recusa de beco sem saída, as arestas do canvas e a `version` precisam
    # do grafo ANTES da execução, e um grafo que só existe depois de rodar não
    # previne nada e não desenha nada.
    produz: frozenset[str] = frozenset()
```

Acrescentar `Task()` o repasse dos dois, para o açúcar não perder expressividade:

```python
def Task(  # noqa: N802 — é um construtor, e o nome é o do conceito
    name: str,
    *,
    resolver: Resolver | None = None,
    cascade: tuple[Resolver, ...] | list[Resolver] | None = None,
    consome: frozenset[str] = frozenset(),
    produz: frozenset[str] = frozenset(),
    policy: ExecutionPolicy | None = None,
) -> Stage:
```

e, no corpo, passar `consome=consome, produz=produz` para `Stage(...)`.

- [ ] **Step 4: Implementar o filtro e a guarda no motor**

Em `src/orchestrator/runtime/engine.py`, dentro do laço `for stage in definicao.stages:`, logo após `emitir(EventKind.STAGE_INICIADO, ...)`:

```python
        # O que ESTE degrau enxerga. `consome` vazio = o pool inteiro.
        #
        # Guardamos o resto à parte e o recompomos no fim do stage: filtrar
        # sem recompor faria o pool encolher por um caminho que não é
        # `without()`, e a invariante "só resolução consome" cairia sem
        # ninguém notar.
        if stage.consome:
            visivel = WorkSet(
                items=tuple(i for i in work.items if i.kind in stage.consome)
            )
            reservados = tuple(i for i in work.items if i.kind not in stage.consome)
        else:
            visivel, reservados = work, ()
        # `stage.consome and ...`: sem `consome` declarado o degrau roda mesmo
        # com pool vazio, que é a semântica anterior a esta fatia. Três testes
        # entre os 844 (`tests/matching/test_engine.py`) chamam
        # `reconcile([], [], ...)` só para observar a ORDEM de chamada dos
        # resolvers, e um gate incondicional pularia a cascata inteira.
        if stage.consome and not visivel.items:
            # Ramo sem trabalho: o degrau não roda, e isso é a condicional.
            emitir(EventKind.STAGE_CONCLUIDO, stage=stage.name, rodou=False)
            continue
        work = visivel
```

Trocar, no fim do laço de resolvers (após a linha de `work = work.without(...).com(...)`), nada; e ao FIM do laço `for resolver in ...`, ou seja, imediatamente antes de passar ao próximo stage, recompor:

```python
        work = WorkSet(items=work.items + reservados)
        emitir(EventKind.STAGE_CONCLUIDO, stage=stage.name, rodou=True)
```

E a guarda, imediatamente após `saida = resolver.resolve(elegiveis)`:

```python
            # `produz` vazio significa "não produz nada", e um resolver que
            # produz mesmo assim é exatamente o caso que esta guarda pega.
            for novo in saida.produced:
                if novo.kind not in stage.produz:
                    raise ValueError(
                        f"{resolver.name!r} produziu kind não declarado: "
                        f"{novo.kind!r} não está em produz={sorted(stage.produz)} "
                        f"do stage {stage.name!r}"
                    )
```

Acrescentar `STAGE_CONCLUIDO` ao `EventKind` em `kernel/event.py`:

```python
    STAGE_CONCLUIDO = "stage.concluido"
```

- [ ] **Step 5: Rodar os testes novos**

```bash
./.venv/Scripts/python.exe -m pytest tests/runtime/test_producao.py -q
```

Esperado: PASS.

**Nota de ordem:** as definições deste arquivo produzem kinds que ninguém consome (`b`, `c`, `z`). Isso é aceito AGORA e passa a ser recusado pela Task 4. Quando a Task 4 entrar, acrescente `entrega=frozenset({...})` a cada definição deste arquivo — é a declaração que a guarda exige, e o próprio ato de escrevê-la é a prova de que a guarda pega o caso real.

- [ ] **Step 6: Rodar a suíte inteira**

```bash
./.venv/Scripts/python.exe -m pytest -q
```

Esperado: os 844 originais passam mais os testes novos deste arquivo, nenhum dos 844 tocado.

- [ ] **Step 7: Commit**

```bash
git add src/orchestrator/kernel/definition.py src/orchestrator/kernel/event.py src/orchestrator/runtime/engine.py tests/runtime/test_producao.py
git commit -m "feat(kernel): Stage declara consome e produz — ramificacao sem if no kernel"
```

---

### Task 4: `entrega`, a recusa de beco sem saída, e a versão

A guarda entra ANTES da peça que ela guarda. É por isso que esta tarefa vem antes da `Tarefa`.

**Files:**
- Modify: `src/orchestrator/kernel/definition.py`
- Test: `tests/workflow/test_definition.py` (acrescentar)
- Modify: `tests/runtime/test_producao.py` — **obrigatório.** Ligar a guarda quebra as definições criadas nas Tasks 2 e 3, que produzem kinds órfãos (`b`, `c`, `z`). Acrescente `entrega=frozenset({...})` a cada uma. **Isso não é conserto de teste: é a guarda pegando o primeiro caso real**, e ver o próprio arquivo precisar da declaração é a evidência de que ela faz efeito.

**Interfaces:**
- Consumes: `Stage.consome`/`produz` da Task 3
- Produces:
  - `WorkflowDefinition(id, name, stages, max_rondas: int = 1, entrega: frozenset[str] = frozenset())`
  - `WorkflowDefinition.__post_init__` levanta `ValueError` em beco sem saída e em `max_rondas < 1`
  - `version` passa a incluir `consome`, `produz`, `max_rondas`, `entrega`

*(`max_rondas` é declarado aqui e só passa a ter efeito na Task 5 — declarar os dois campos de uma vez evita mexer em `version` duas vezes e produzir dois hashes diferentes no caminho.)*

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar a `tests/workflow/test_definition.py`:

```python
import pytest

from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.definition import Stage, WorkflowDefinition
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkSet


class _Nada:
    name = "nada"
    cost_class = CostClass.REGRA

    def describe(self) -> ResolverDescription:
        return ResolverDescription(self.name, self.cost_class, "teste")

    def resolve(self, work: WorkSet) -> ResolverOutput:
        return ResolverOutput()


def _stage(nome, consome=frozenset(), produz=frozenset()):
    return Stage(name=nome, cascade=(_Nada(),), consome=consome, produz=produz)


def test_recusa_beco_sem_saida():
    """Um kind produzido que ninguém consome é item que fica no pool para
    sempre, sem nunca chegar a um humano.

    Esta é a guarda que impede `Tarefa` (Task 7) de virar a porta dos fundos
    por onde "proposta não resolve" sairia: uma transformação é legítima
    porque o item que ela produz AINDA passa por alguém. Se ninguém o
    consome, ela encerrou o trabalho sem que nada fosse conferido.
    """
    with pytest.raises(ValueError, match="beco sem saída"):
        WorkflowDefinition(
            id="w",
            name="w",
            stages=(_stage("um", consome=frozenset({"a"}), produz=frozenset({"b"})),),
        )


def test_entrega_declara_o_kind_terminal():
    """"Ninguém consome isto" tem de ser afirmação do autor, nunca acidente."""
    d = WorkflowDefinition(
        id="w",
        name="w",
        stages=(_stage("um", consome=frozenset({"a"}), produz=frozenset({"b"})),),
        entrega=frozenset({"b"}),
    )

    assert d.entrega == frozenset({"b"})


def test_kind_consumido_por_outro_stage_basta():
    d = WorkflowDefinition(
        id="w",
        name="w",
        stages=(
            _stage("um", consome=frozenset({"a"}), produz=frozenset({"b"})),
            _stage("dois", consome=frozenset({"b"}), produz=frozenset({"c"})),
        ),
        entrega=frozenset({"c"}),
    )

    assert len(d.stages) == 2


def test_max_rondas_menor_que_um_e_erro():
    """Zero ronda não executa nada e pareceria um workflow que não acha nada,
    em vez de configuração inválida — a mesma falha que `max_turns < 1` já
    recusa em `Agent`."""
    with pytest.raises(ValueError, match="max_rondas"):
        WorkflowDefinition(id="w", name="w", stages=(_stage("um"),), max_rondas=0)


def test_version_muda_com_consome_produz_e_max_rondas():
    """Dois grafos diferentes não podem hashear igual: `Run.workflow_version`
    é o que o benchmark usa para saber que comparou a mesma coisa."""
    base = WorkflowDefinition(
        id="w", name="w", stages=(_stage("um", produz=frozenset({"b"})),),
        entrega=frozenset({"b"}),
    )
    outro_consumo = WorkflowDefinition(
        id="w", name="w",
        stages=(_stage("um", consome=frozenset({"a"}), produz=frozenset({"b"})),),
        entrega=frozenset({"b"}),
    )
    mais_rondas = WorkflowDefinition(
        id="w", name="w", stages=(_stage("um", produz=frozenset({"b"})),),
        entrega=frozenset({"b"}), max_rondas=3,
    )

    assert base.version != outro_consumo.version
    assert base.version != mais_rondas.version
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/workflow/test_definition.py -q
```

Esperado: `TypeError: WorkflowDefinition.__init__() got an unexpected keyword argument 'entrega'`.

- [ ] **Step 3: Implementar**

Em `src/orchestrator/kernel/definition.py`, em `WorkflowDefinition`:

```python
@dataclass(frozen=True)
class WorkflowDefinition:
    id: str
    name: str
    stages: tuple[Stage, ...]
    # Quantas vezes a sequência de stages pode rodar. 1 = a semântica anterior
    # a esta fatia, EXATA: os stages rodam em ordem e um pipeline fecha numa
    # passada. Ronda extra só é necessária para ARESTA DE VOLTA — o revisor
    # reprova e o rascunho volta ao escritor. A complexidade do laço se paga
    # só quando há laço.
    max_rondas: int = 1
    # Os `kind` que SÃO a saída do run. É a única exceção à recusa de beco sem
    # saída, e existe para que "ninguém consome isto" seja afirmação do autor
    # em vez de acidente.
    entrega: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.max_rondas < 1:
            raise ValueError(f"max_rondas precisa ser pelo menos 1: {self.max_rondas}")
        # Beco sem saída: um item produzido que ninguém consome fica no pool
        # para sempre e nunca chega a um revisor. Falha na CONSTRUÇÃO, e aqui
        # — no kernel — e não em `authoring.construir()`: `construir()` é a via
        # de AUTORIA, e os domínios em Python montam `WorkflowDefinition`
        # direto. Uma guarda que só protege o canvas não protege o código, e é
        # o código que roda em produção.
        consumidos: set[str] = set()
        for s in self.stages:
            consumidos |= s.consome
        for s in self.stages:
            orfaos = sorted(s.produz - consumidos - self.entrega)
            if orfaos:
                raise ValueError(
                    f"beco sem saída no stage {s.name!r}: {orfaos} não são "
                    f"consumidos por nenhum stage nem declarados em `entrega`"
                )
```

E, em `version`, trocar a lista `forma` por:

```python
        forma = [
            self.id,
            self.max_rondas,
            sorted(self.entrega),
            [
                [
                    s.name,
                    sorted(s.consome),
                    sorted(s.produz),
                    [[r.name, int(r.cost_class)] for r in s.ordered()],
                ]
                for s in self.stages
            ],
        ]
```

Atualizar o docstring de `version` para registrar que `consome`, `produz`, `max_rondas` e `entrega` entram na forma — e que a POLÍTICA continua fora, pela razão já escrita ali.

- [ ] **Step 4: Rodar os testes novos**

```bash
./.venv/Scripts/python.exe -m pytest tests/workflow/test_definition.py -q
```

Esperado: PASS.

- [ ] **Step 5: Rodar a suíte inteira**

```bash
./.venv/Scripts/python.exe -m pytest -q
```

Esperado: os 844 originais passam mais os testes novos deste arquivo. **Atenção:** `version` mudou de forma, então qualquer teste que fixe um hash literal vai falhar. Se isso acontecer, o teste estava certo e o hash é derivado — atualize o literal e registre no commit que a versão mudou de propósito. Se um teste dos 844 falhar por OUTRO motivo, o default está errado.

- [ ] **Step 6: Commit**

```bash
git add src/orchestrator/kernel/definition.py tests/workflow/test_definition.py
git commit -m "feat(kernel): entrega, recusa de beco sem saida, e a versao que inclui o grafo"
```

---

### Task 5: O laço até ponto fixo

**Files:**
- Modify: `src/orchestrator/runtime/engine.py`
- Modify: `src/orchestrator/kernel/run.py`
- Test: `tests/runtime/test_rondas.py` (criar)

**Interfaces:**
- Consumes: tudo das Tasks 2–4
- Produces:
  - `RunState.LIMITE_DE_RONDAS`
  - `Run.rondas: int = 1`
  - O motor repete a sequência de stages até nenhuma ronda resolver nem produzir, ou bater `max_rondas`

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/runtime/test_rondas.py`:

```python
"""O laço até ponto fixo: aresta de volta, e o teto que a torna segura."""

from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.definition import Stage, WorkflowDefinition
from orchestrator.kernel.resolution import Resolution
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.run import RunState
from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.runtime.engine import execute


class PingPong:
    """Troca `a` por `b` e `b` por `a`, para sempre. Um laço que não converge."""

    cost_class = CostClass.REGRA

    def __init__(self, name: str, de: str, para: str) -> None:
        self.name, self._de, self._para = name, de, para

    def describe(self) -> ResolverDescription:
        return ResolverDescription(self.name, self.cost_class, "teste")

    def resolve(self, work: WorkSet) -> ResolverOutput:
        res, prod = [], []
        for i, item in enumerate(work.of_kind(self._de)):
            res.append(
                Resolution(
                    item_ids=frozenset({item.id}), produced_by=self.name, rule="pingpong"
                )
            )
            prod.append(
                WorkItem(
                    id=f"{item.id}-{self.name}-{i}",
                    kind=self._para,
                    payload=item.payload,
                    origem=self.name,
                )
            )
        return ResolverOutput(resolutions=res, produced=tuple(prod), cost=Cost.zero())


def _pingpong(max_rondas: int) -> WorkflowDefinition:
    return WorkflowDefinition(
        id="pingpong",
        name="pingpong",
        stages=(
            Stage(
                name="ida",
                cascade=(PingPong("ida", "a", "b"),),
                consome=frozenset({"a"}),
                produz=frozenset({"b"}),
            ),
            Stage(
                name="volta",
                cascade=(PingPong("volta", "b", "a"),),
                consome=frozenset({"b"}),
                produz=frozenset({"a"}),
            ),
        ),
        max_rondas=max_rondas,
    )


def test_max_rondas_1_e_exatamente_a_semantica_de_hoje():
    """Uma passada pelos stages, em ordem. O default não muda nada."""
    r = execute(_pingpong(1), WorkSet(items=(WorkItem(id="i", kind="a", payload=1),)))

    assert r.rondas == 1
    assert r.state is RunState.CONCLUIDO
    # ida (a->b) e volta (b->a) rodaram uma vez cada, na mesma ronda.
    assert len(r.resolutions) == 2


def test_bater_o_teto_e_estado_explicito_nunca_silencio():
    """Um run que parou por teto NÃO terminou, e tem de dizer isso.

    Terminar como CONCLUIDO seria a mesma desonestidade que imprimir 100% de
    precisão sobre dois itens — o repositório já revogou duas conclusões por
    isso.
    """
    r = execute(_pingpong(3), WorkSet(items=(WorkItem(id="i", kind="a", payload=1),)))

    assert r.rondas == 3
    assert r.state is RunState.LIMITE_DE_RONDAS


def test_o_laco_para_sozinho_quando_a_ronda_nao_faz_nada():
    """Ponto fixo: sem resolução e sem produção, não há por que rodar de novo.

    O teto alto prova que quem parou o laço foi a convergência, não ele.
    """
    d = WorkflowDefinition(
        id="parado",
        name="parado",
        stages=(
            Stage(
                name="ida",
                cascade=(PingPong("ida", "a", "b"),),
                consome=frozenset({"a"}),
                produz=frozenset({"b"}),
            ),
        ),
        entrega=frozenset({"b"}),
        max_rondas=50,
    )

    r = execute(d, WorkSet(items=(WorkItem(id="i", kind="a", payload=1),)))

    # Ronda 1 transformou; ronda 2 não achou mais nada de kind "a" e parou.
    assert r.rondas == 2
    assert r.state is RunState.CONCLUIDO
    assert len(r.resolutions) == 1
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/runtime/test_rondas.py -q
```

Esperado: `AttributeError: 'Run' object has no attribute 'rondas'`.

- [ ] **Step 3: Implementar o estado e o campo**

Em `src/orchestrator/kernel/run.py`, acrescentar ao `RunState`, depois de `AGUARDANDO_HUMANO`:

```python
    # Bateu `WorkflowDefinition.max_rondas` sem convergir. NÃO é `CONCLUIDO`:
    # o trabalho não acabou, o teto é que chegou. Mesmo espírito de
    # `AGUARDANDO_HUMANO` — a lacuna é declarada, nunca escondida.
    LIMITE_DE_RONDAS = "limite_de_rondas"
```

E a `Run`, junto dos outros campos com default:

```python
    # Quantas vezes a sequência de stages rodou. 1 no caso comum.
    rondas: int = 1
```

- [ ] **Step 4: Implementar o laço**

Em `src/orchestrator/runtime/engine.py`, envolver o `for stage in definicao.stages:` existente num laço externo. O corpo do `for stage` não muda; só ganha um contador e uma condição de saída:

```python
    rondas = 0
    for _ in range(definicao.max_rondas):
        rondas += 1
        antes_resolvidos, antes_itens = len(todos), work.ids()
        emitir(EventKind.RONDA_INICIADA, ronda=rondas, itens=len(work.items))

        for stage in definicao.stages:
            ...  # o corpo de hoje, sem mudança

        # Ponto fixo: a ronda não resolveu nada E não mudou o pool. Rodar de
        # novo daria exatamente o mesmo resultado, porque o motor é puro e o
        # pool é a única entrada que muda entre rondas.
        if len(todos) == antes_resolvidos and work.ids() == antes_itens:
            break
    else:
        # `for/else`: o laço esgotou `max_rondas` sem um `break` — a última
        # ronda ainda estava fazendo coisa, logo não convergiu.
        #
        # `max_rondas == 1` NÃO conta como teto batido, e isso não é
        # conveniência: uma passada só não PROMETE convergência, ela promete
        # uma passada e a entrega. Declarar mais de uma ronda é o que cria a
        # expectativa de ponto fixo — e é só aí que não alcançá-lo é notícia.
        #
        # Sem esta condição, todo workflow de hoje (todos têm max_rondas=1 e
        # todos fazem trabalho) reportaria LIMITE_DE_RONDAS em vez de
        # CONCLUIDO, e os 844 testes cairiam juntos. A §5 do spec é explícita:
        # "1 = a semântica de hoje, EXATA".
        estado_por_teto = definicao.max_rondas > 1
```

Inicializar `estado_por_teto = False` antes do laço, e trocar o cálculo de `estado`:

```python
    tem_humano = any(
        r.cost_class >= CostClass.HUMANO for s in definicao.stages for r in s.cascade
    )
    if estado_por_teto:
        estado = RunState.LIMITE_DE_RONDAS
    elif work.items and tem_humano:
        estado = RunState.AGUARDANDO_HUMANO
    else:
        estado = RunState.CONCLUIDO
```

E passar `rondas=rondas` na construção do `Run`.

Acrescentar `RONDA_INICIADA` ao `EventKind` em `kernel/event.py`:

```python
    RONDA_INICIADA = "ronda.iniciada"
```

- [ ] **Step 5: Rodar os testes novos**

```bash
./.venv/Scripts/python.exe -m pytest tests/runtime/test_rondas.py -q
```

Esperado: PASS.

- [ ] **Step 6: Rodar a suíte inteira**

```bash
./.venv/Scripts/python.exe -m pytest -q
```

Esperado: os 844 originais passam mais os testes novos deste arquivo, nenhum dos 844 tocado (`max_rondas=1` faz o laço externo rodar uma vez, e a segunda iteração nem começa).

- [ ] **Step 7: Commit**

```bash
git add src/orchestrator/runtime/engine.py src/orchestrator/kernel/run.py src/orchestrator/kernel/event.py tests/runtime/test_rondas.py
git commit -m "feat(runtime): laco ate ponto fixo, com teto e estado explicito"
```

---

### Task 6: Extrair o laço de turnos (refatoração pura, zero mudança de comportamento)

`Agent.investigar` é 140 linhas de laço genérico com dois pontos de domínio: `spec.parse` e `spec.abstain`. A `Tarefa` da Task 7 precisa do mesmo laço com outros dois. Duplicá-lo custaria caro — `agent/llm.py` já registra um defeito crítico que foi corrigido numa cópia e não na outra.

**Files:**
- Create: `src/orchestrator/agent/conversa.py`
- Modify: `src/orchestrator/agent/agent.py`
- Test: `tests/agent/test_conversa.py` (criar)

**Interfaces:**
- Consumes: nada das tarefas anteriores
- Produces:

```python
T = TypeVar("T")

Interpretador = Callable[[str, str, Cost, list[TraceEvent]], T | None]
Desistencia   = Callable[[str, str, Cost, list[TraceEvent]], T]

def conversar(
    *,
    client: LLMClient,
    tools: ToolRegistry,
    system: str,
    item_id: str,
    prompt: str,
    max_turns: int,
    max_format_retries: int,
    budget_microcents: int,
    interpretar: Interpretador[T],
    desistir: Desistencia[T],
) -> T: ...
```

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/agent/test_conversa.py`:

```python
"""O laço de turnos, sem saber o que é uma proposta.

Este arquivo é a prova de que a extração é genérica: nada aqui importa
`Proposal`. Se um teste daqui precisar dela, a extração falhou e o laço
continua sabendo o que o agente devolve.
"""

from orchestrator.agent.conversa import conversar
from orchestrator.agent.llm import FakeLLMClient, LLMResponse
from orchestrator.agent.tools.registry import ToolRegistry
from orchestrator.kernel.cost import Cost


def _resposta(texto: str) -> LLMResponse:
    return LLMResponse(text=texto, tool_calls=[], cost=Cost(input_tokens=10, output_tokens=5))


def _sem_ferramentas() -> ToolRegistry:
    # Construtor posicional: `ToolRegistry([spec, ...], contexto=...)`.
    return ToolRegistry([])


def test_devolve_o_que_o_interpretador_produziu():
    """O laço não sabe o tipo de saída — devolve o que lhe derem."""
    cliente = FakeLLMClient([_resposta("ok")])

    r = conversar(
        client=cliente,
        tools=_sem_ferramentas(),
        system="s",
        item_id="i",
        prompt="p",
        max_turns=3,
        max_format_retries=2,
        budget_microcents=10_000_000,
        interpretar=lambda item, texto, custo, trace: {"item": item, "texto": texto},
        desistir=lambda item, motivo, custo, trace: {"desistiu": motivo},
    )

    assert r == {"item": "i", "texto": "ok"}


def test_interpretador_que_devolve_none_dispara_retry_de_formato():
    """`None` é "formato inválido, tente de novo" — nunca "desisti"."""
    cliente = FakeLLMClient([_resposta("lixo"), _resposta("bom")])
    vistos = []

    def interpretar(item, texto, custo, trace):
        vistos.append(texto)
        return None if texto == "lixo" else texto

    r = conversar(
        client=cliente, tools=_sem_ferramentas(), system="s", item_id="i", prompt="p",
        max_turns=3, max_format_retries=2, budget_microcents=10_000_000,
        interpretar=interpretar,
        desistir=lambda item, motivo, custo, trace: "DESISTIU",
    )

    assert vistos == ["lixo", "bom"]
    assert r == "bom"


def test_estourar_o_orcamento_desiste_com_o_custo_acumulado():
    cliente = FakeLLMClient([_resposta("ok")])
    capturado = {}

    def desistir(item, motivo, custo, trace):
        capturado["motivo"] = motivo
        capturado["custo"] = custo
        return "DESISTIU"

    r = conversar(
        client=cliente, tools=_sem_ferramentas(), system="s", item_id="i", prompt="p",
        max_turns=3, max_format_retries=2, budget_microcents=1,
        interpretar=lambda *a: "nunca chega aqui",
        desistir=desistir,
    )

    assert r == "DESISTIU"
    assert "orçamento" in capturado["motivo"]
    assert capturado["custo"] != Cost.zero()
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/agent/test_conversa.py -q
```

Esperado: `ModuleNotFoundError: No module named 'orchestrator.agent.conversa'`.

- [ ] **Step 3: Criar `conversa.py` movendo o corpo de `investigar`**

Criar `src/orchestrator/agent/conversa.py` com o docstring:

```python
"""O laço de turnos, sem saber o que sai dele.

`Agent.investigar` era este laço com dois pontos de domínio costurados no meio:
`spec.parse`, que vira proposta, e `spec.abstain`, que diz "não sei". Tudo à
volta — turnos, orçamento, execução de ferramenta, retry de formato, captura de
falha de API — é genérico e não sabe o que é uma `Proposal`.

Extraído porque a `Tarefa` precisa do MESMO laço com outros dois pontos:
um que vira item produzido e um que abstém. Duplicá-lo seria repetir o erro que
`blocos_assistente` já registra ter custado caro — uma correção crítica aplicada
numa cópia e esquecida na outra.

O que este módulo NÃO faz: decidir. Ele conversa e entrega o texto a quem sabe
interpretá-lo.
"""
```

Mover o corpo de `Agent.investigar` (`agent.py:216–342`) para a função `conversar`, com estas substituições mecânicas e NENHUMA outra:

| No original | Em `conversar` |
|---|---|
| `tarefa.prompt` | `prompt` |
| `tarefa.id` | `item_id` |
| `self.spec.system` | `system` |
| `self.spec.max_turns` | `max_turns` |
| `self.spec.max_format_retries` | `max_format_retries` |
| `self.spec.budget_microcents` | `budget_microcents` |
| `self.client` | `client` |
| `self.tools` | `tools` |
| `self.spec.parse(tarefa.id, resposta.text, custo, trace)` | `interpretar(item_id, resposta.text, custo, trace)` |
| `self.spec.abstain(tarefa.id, <motivo>, custo, trace)` | `desistir(item_id, <motivo>, custo, trace)` |

Todos os comentários existentes viajam junto, verbatim — em especial o bloco que explica por que o `except` envolve SÓ a chamada ao modelo, e o que explica o `tool_result` por `tool_use`.

- [ ] **Step 4: `Agent.investigar` vira a costura fina**

Em `src/orchestrator/agent/agent.py`, substituir o corpo de `investigar` por:

```python
    def investigar(self, tarefa: AgentTask) -> Proposal:
        """Um item, do prompt à proposta.

        O laço mora em `conversa.conversar` desde a extração: aqui ficam só os
        dois pontos que sabem o que é uma proposta. Público desde o M8, porque
        o `Crew` roda o mesmo laço com o prompt enriquecido pelo
        `SharedContext` — e um sublinhado que dois módulos ignoram não protege
        nada, só esconde quem depende de quê.
        """
        return conversar(
            client=self.client,
            tools=self.tools,
            system=self.spec.system,
            item_id=tarefa.id,
            prompt=tarefa.prompt,
            max_turns=self.spec.max_turns,
            max_format_retries=self.spec.max_format_retries,
            budget_microcents=self.spec.budget_microcents,
            interpretar=self.spec.parse,
            desistir=self.spec.abstain,
        )
```

Manter os imports que `agent.py` ainda usa e remover os que só o laço usava (`json`, `blocos_assistente`, provavelmente `TraceKind`) — o ruff aponta.

- [ ] **Step 5: Rodar os testes de agente e crew — é aqui que a refatoração se prova**

```bash
./.venv/Scripts/python.exe -m pytest tests/agent tests/crew tests/grill -q
```

Esperado: PASS, sem nenhuma edição nesses testes. Eles exercitam orçamento, retry de formato, falha de API e execução de ferramenta; passar sem edição é a prova de que a extração não mudou comportamento.

- [ ] **Step 6: Rodar a suíte inteira e o lint**

```bash
./.venv/Scripts/python.exe -m pytest -q && ./.venv/Scripts/python.exe -m ruff check src tests
```

Esperado: os 844 originais passam, mais os testes novos deste arquivo. Ruff limpo.

- [ ] **Step 7: Commit**

```bash
git add src/orchestrator/agent/conversa.py src/orchestrator/agent/agent.py tests/agent/test_conversa.py
git commit -m "refactor(agent): o laco de turnos extraido, sem saber o que sai dele"
```

---

### Task 7: `Tarefa` — o resolver que transforma

**Files:**
- Create: `src/orchestrator/agent/tarefa.py`
- Test: `tests/agent/test_tarefa.py` (criar)

**Interfaces:**
- Consumes: `conversar()` da Task 6; `ResolverOutput.produced` da Task 2
- Produces:

```python
@dataclass(frozen=True)
class SaidaDaTarefa:
    cost: Cost
    trace: tuple[TraceEvent, ...]
    resolution: Resolution | None = None      # None = abstenção
    produced: tuple[WorkItem, ...] = ()

Transformador = Callable[[str, str, Cost, list[TraceEvent]], SaidaDaTarefa | None]

@dataclass(frozen=True)
class TarefaSpec:
    name: str
    system: str
    model: str
    prompt_de: Callable[[WorkItem], str]
    transformar: Transformador
    max_turns: int = 6
    max_format_retries: int = 2
    budget_microcents: int = 4_000_000

@dataclass
class Tarefa:
    spec: TarefaSpec
    client: LLMClient
    tools: ToolRegistry
    # name: str, cost_class: CostClass.AGENTE  (init=False, como em `Agent`)
    def resolve(self, work: WorkSet) -> ResolverOutput: ...
```

**Por que `SaidaDaTarefa` e não `tuple[Resolution, tuple[WorkItem, ...]] | None`:** `None` já significa "formato inválido, tente de novo" no contrato de `conversar`. Uma tupla-ou-None faria abstenção e retry de formato serem o mesmo valor, e o laço tentaria de novo uma tarefa que já desistiu. `resolution=None` diz "não resolvi" sem colidir.

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/agent/test_tarefa.py`:

```python
"""`Tarefa`: transforma item em item. Nunca propõe.

A simetria com `test_agent.py` é o ponto: `Agent` nunca devolve `resolutions`,
`Tarefa` nunca devolve `proposals`, e as duas rodam o mesmo laço.
"""

from orchestrator.agent.llm import FakeLLMClient, LLMResponse
from orchestrator.agent.tarefa import SaidaDaTarefa, Tarefa, TarefaSpec
from orchestrator.agent.tools.registry import ToolRegistry
from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.resolution import Resolution
from orchestrator.kernel.work import WorkItem, WorkSet


def _resposta(texto: str) -> LLMResponse:
    return LLMResponse(text=texto, tool_calls=[], cost=Cost(input_tokens=10, output_tokens=5))


def _transformar(item_id, texto, custo, trace):
    if not texto.strip():
        return None
    return SaidaDaTarefa(
        cost=custo,
        trace=tuple(trace),
        resolution=Resolution(
            item_ids=frozenset({item_id}), produced_by="escritor", rule="escreveu"
        ),
        produced=(
            WorkItem(id=f"{item_id}+r", kind="rascunho", payload=texto, origem="escritor"),
        ),
    )


def _spec(**kw) -> TarefaSpec:
    base = dict(
        name="escritor",
        system="escreva",
        model="claude-opus-5",
        prompt_de=lambda item: f"escreva sobre {item.payload}",
        transformar=_transformar,
    )
    return TarefaSpec(**{**base, **kw})


def _pool() -> WorkSet:
    return WorkSet(items=(WorkItem(id="i", kind="achados", payload="gatos"),))


def test_tarefa_resolve_e_produz():
    t = Tarefa(
        spec=_spec(), client=FakeLLMClient([_resposta("um texto")]),
        tools=ToolRegistry([]),
    )

    saida = t.resolve(_pool())

    assert [r.item_ids for r in saida.resolutions] == [frozenset({"i"})]
    assert [p.kind for p in saida.produced] == ["rascunho"]
    assert saida.produced[0].payload == "um texto"
    # A simetria com `Agent`: uma nunca propõe, a outra nunca resolve.
    assert saida.proposals == []


def test_tarefa_e_classe_agente():
    """Transformar custa uma chamada de modelo. A classe diz isso, e é o que
    põe a `Tarefa` no lugar certo da ordenação por custo."""
    t = Tarefa(spec=_spec(), client=FakeLLMClient([]), tools=ToolRegistry([]))

    assert t.cost_class is CostClass.AGENTE
    assert t.name == "escritor"


def test_desistir_deixa_o_item_no_pool_sem_resolver():
    """Falha após o retry NÃO resolve: o item fica para o próximo degrau.

    Um agente que estoura não derruba o run, e um item não some porque o
    modelo devolveu lixo — ele continua esperando alguém.
    """
    t = Tarefa(
        spec=_spec(max_format_retries=1),
        client=FakeLLMClient([_resposta(" "), _resposta(" ")]),
        tools=ToolRegistry([]),
    )

    saida = t.resolve(_pool())

    assert saida.resolutions == []
    assert saida.produced == ()
    # O custo dos turnos gastos é registrado mesmo sem resolver — senão a
    # cascata reportaria uma tentativa cara como se fosse de graça.
    assert saida.cost != Cost.zero()


def test_custo_de_varios_itens_e_somado():
    pool = WorkSet(
        items=(
            WorkItem(id="i1", kind="achados", payload="a"),
            WorkItem(id="i2", kind="achados", payload="b"),
        )
    )
    t = Tarefa(
        spec=_spec(),
        client=FakeLLMClient([_resposta("t1"), _resposta("t2")]),
        tools=ToolRegistry([]),
    )

    saida = t.resolve(pool)

    assert len(saida.resolutions) == 2
    assert saida.cost.output_tokens == 10
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/agent/test_tarefa.py -q
```

Esperado: `ModuleNotFoundError: No module named 'orchestrator.agent.tarefa'`.

- [ ] **Step 3: Implementar**

Criar `src/orchestrator/agent/tarefa.py`:

```python
"""`Tarefa`: um resolver que TRANSFORMA o item, em vez de julgá-lo.

`Agent` devolve `proposals` e nunca `resolutions` — proposta não resolve, e
isso é o tipo, não disciplina. `Tarefa` devolve `resolutions` e nunca
`proposals`, e a pergunta óbvia é por que isso é legítimo.

Não é "porque não decide". Um triador que produz `kind="urgente"` decide, e é
assim que a ramificação funciona. A distinção é outra:

    Uma `Tarefa` empurra o trabalho para frente DENTRO do run; nunca o
    encerra. O item que ela produz continua no pool e ainda passa por quem
    vier depois — inclusive um HUMANO, se a cascata tiver um. Uma `Proposal`
    que resolvesse faria o item SAIR com um julgamento que ninguém conferiu.

E isso não depende de boa vontade: `WorkflowDefinition.__post_init__` recusa
uma definição em que um kind produzido não seja consumido por ninguém nem
declarado em `entrega`. Beco sem saída é erro de construção.
"""
```

Com os tipos do bloco **Interfaces** acima e este `resolve`:

```python
    def resolve(self, work: WorkSet) -> ResolverOutput:
        """Transforma o que recebeu. NUNCA devolve `proposals`.

        O espelho de `Agent.resolve`, e a assimetria é o contrato: lá o campo
        `resolutions` não é preenchido, aqui é `proposals`.
        """
        resolucoes, produzidos, total = [], [], Cost.zero()
        for item in work.items:
            saida = conversar(
                client=self.client,
                tools=self.tools,
                system=self.spec.system,
                item_id=item.id,
                prompt=self.spec.prompt_de(item),
                max_turns=self.spec.max_turns,
                max_format_retries=self.spec.max_format_retries,
                budget_microcents=self.spec.budget_microcents,
                interpretar=self.spec.transformar,
                desistir=_abster,
            )
            total = total + saida.cost
            # `resolution is None` é abstenção: o item NÃO sai do pool e fica
            # para o próximo degrau. Um agente que estoura não derruba o run,
            # e um item não some porque o modelo devolveu lixo.
            if saida.resolution is not None:
                resolucoes.append(saida.resolution)
                produzidos.extend(saida.produced)
        return ResolverOutput(
            resolutions=resolucoes, produced=tuple(produzidos), cost=total
        )
```

E a desistência, no nível do módulo:

```python
def _abster(item_id: str, motivo: str, custo: Cost, trace: list[TraceEvent]) -> SaidaDaTarefa:
    """Não transformou. Registra por quê e devolve o item ao pool.

    Não é parâmetro da spec — ao contrário de `AgentSpec.abstain`, que precisa
    do rótulo de "não sei" DO DOMÍNIO porque uma proposta de abstenção tem um
    `tipo`. Aqui não há tipo a escolher: não transformar é a ausência de
    resolução, e ausência é a mesma em todo domínio.
    """
    return SaidaDaTarefa(
        cost=custo,
        trace=(*trace, TraceEvent(kind=TraceKind.OUTCOME, detail={"motivo": motivo})),
    )
```

`__post_init__` de `Tarefa` repete as guardas de `Agent`: `max_turns >= 1`, orçamento não negativo, e `Cost.zero().microcents(self.client.model)` para recusar modelo sem preço na construção.

- [ ] **Step 4: Rodar os testes novos**

```bash
./.venv/Scripts/python.exe -m pytest tests/agent/test_tarefa.py -q
```

Esperado: PASS.

- [ ] **Step 5: Verificar a camada**

```bash
./.venv/Scripts/python.exe -m pytest tests/arquitetura -q
```

Esperado: PASS. `agent` pode importar `kernel` e `runtime`; `tarefa.py` não importa mais nada.

- [ ] **Step 6: Suíte inteira e lint**

```bash
./.venv/Scripts/python.exe -m pytest -q && ./.venv/Scripts/python.exe -m ruff check src tests
```

Esperado: os 844 originais passam, mais os testes novos deste arquivo. Ruff limpo.

- [ ] **Step 7: Commit**

```bash
git add src/orchestrator/agent/tarefa.py tests/agent/test_tarefa.py
git commit -m "feat(agent): Tarefa — o resolver que transforma, e por que ele pode resolver"
```

---

### Task 8: O domínio `redacao` — o teste de generalidade de verdade

Procurement e swe acharam dois defeitos de kernel na primeira linha de código de domínio. Este é o quarto domínio, e o primeiro que não é um pool que só encolhe.

**Files:**
- Create: `src/orchestrator/domains/redacao/__init__.py`
- Create: `src/orchestrator/domains/redacao/workflow.py`
- Test: `tests/domains/test_redacao.py` (criar)
- Modify: `src/orchestrator/domains/registro.py` (registrar o domínio)

**Interfaces:**
- Consumes: `Tarefa`/`TarefaSpec` da Task 7; `Stage.consome`/`produz` da Task 3; `entrega` da Task 4
- Produces:
  - `Topico(id: str, assunto: str)`
  - `pool(topicos: list[Topico]) -> WorkSet` — itens de `kind="topico"`
  - `definition(cliente: LLMClient) -> WorkflowDefinition`

**O grafo:**

```
topico --[pesquisar]--> achados --[escrever]--> rascunho --[revisar]--> texto_final
                                                                        (entrega)
```

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/domains/test_redacao.py`:

```python
"""O quarto domínio: um pipeline, não um pool que encolhe.

Procurement e swe provaram que a cascata serve a mais de um domínio. Este prova
outra coisa: que ela serve a um trabalho que não tem "resolvido" no sentido de
conciliação — só tem "pronto". É o caso que a §0.1 do spec anterior recusava.
"""

from orchestrator.agent.llm import FakeLLMClient, LLMResponse
from orchestrator.domains.redacao.workflow import Topico, definition, pool
from orchestrator.kernel.cost import Cost
from orchestrator.kernel.run import RunState
from orchestrator.runtime.engine import execute


def _resposta(texto: str) -> LLMResponse:
    return LLMResponse(text=texto, tool_calls=[], cost=Cost(input_tokens=10, output_tokens=5))


def test_o_topico_atravessa_os_tres_degraus():
    cliente = FakeLLMClient([_resposta("achei X"), _resposta("texto"), _resposta("texto revisado")])

    r = execute(definition(cliente), pool([Topico(id="t1", assunto="gatos")]))

    assert r.state is RunState.CONCLUIDO
    # O que sobra no pool É a entrega: kind terminal, declarado.
    assert [i.kind for i in r.unresolved.items] == ["texto_final"]
    assert r.unresolved.items[0].payload == "texto revisado"
    # Três transformações, uma por degrau.
    assert len(r.resolutions) == 3
    assert [x.produced_by for x in r.resolutions] == ["pesquisador", "escritor", "revisor"]


def test_a_proveniencia_sobrevive_aos_tres_saltos():
    """Sem `origem`, "de onde veio este texto" perde resposta no primeiro
    salto — e o replay não reconstrói o caminho."""
    cliente = FakeLLMClient([_resposta("a"), _resposta("b"), _resposta("c")])

    r = execute(definition(cliente), pool([Topico(id="t1", assunto="x")]))

    assert r.unresolved.items[0].origem == "revisor"


def test_o_custo_e_atribuido_por_degrau_nao_ao_sistema():
    """Custo por resolver é o que permite perguntar qual degrau é o caro — e
    é a pergunta que o laço de promoção vai responder depois."""
    cliente = FakeLLMClient([_resposta("a"), _resposta("b"), _resposta("c")])

    r = execute(definition(cliente), pool([Topico(id="t1", assunto="x")]))

    assert set(r.cost_by_resolver) == {"pesquisador", "escritor", "revisor"}
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/domains/test_redacao.py -q
```

Esperado: `ModuleNotFoundError: No module named 'orchestrator.domains.redacao'`.

- [ ] **Step 3: Implementar o domínio**

Criar `src/orchestrator/domains/redacao/__init__.py` vazio e `workflow.py` com o docstring:

```python
"""Redação: o domínio que não tem "resolvido", só tem "pronto".

Conciliação, procurement e swe são pools que ENCOLHEM: cada item tem uma
decisão e sai. Este é um pool que TRANSFORMA — um tópico vira achados, que
viram rascunho, que vira texto final. Nenhum item é decidido; todos são
trabalhados.

É o caso que a §0.1 do spec anterior recusava, e está aqui como esqueleto
executável pela mesma razão que procurement e swe estão: cada atrito que ele
encontra vira uma correção de um dia em vez de uma descoberta de um mês.
"""
```

Os três degraus são o MESMO código com três parâmetros — escrever três
`transformar` quase idênticos seria a duplicação que `blocos_assistente` já
registra ter custado caro:

```python
def _degrau(
    nome: str, system: str, produz_kind: str, instrucao: Callable[[Any], str]
) -> TarefaSpec:
    """Um degrau do pipeline. Os três só diferem no prompt e no kind de saída.

    `transformar` é fechado sobre `nome` e `produz_kind`, e é por isso que os
    três degraus não precisam de três funções: a forma da transformação — o
    texto do modelo vira o payload do próximo item — é a mesma em todos.
    """

    def transformar(item_id, texto, custo, trace):
        if not texto.strip():
            # Texto vazio não é rascunho. `None` pede retry de formato; se o
            # retry esgotar, `conversar` chama a desistência e o item fica no
            # pool para o próximo degrau.
            return None
        return SaidaDaTarefa(
            cost=custo,
            trace=tuple(trace),
            resolution=Resolution(
                item_ids=frozenset({item_id}), produced_by=nome, rule=nome
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
        lambda item: f"Escreva um texto a partir destes achados:
{item.payload}",
    )


def _revisor() -> TarefaSpec:
    return _degrau(
        "revisor",
        "Você revisa texto. Responda apenas com a versão revisada.",
        "texto_final",
        lambda item: f"Revise este rascunho:
{item.payload}",
    )
```

`Topico` e `pool` são o par de sempre — o dataclass do domínio e a função que o
embrulha em `WorkItem`, exatamente como `procurement.pool` faz:

```python
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
```

E a definição:

```python
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
```

Registrar em `domains/registro.py` seguindo o padrão de `procurement` e `swe`.

- [ ] **Step 4: Rodar os testes novos**

```bash
./.venv/Scripts/python.exe -m pytest tests/domains/test_redacao.py -q
```

Esperado: PASS.

- [ ] **Step 5: Anotar o que o domínio achou**

Se escrever `redacao` encontrou atrito no kernel — um campo que faltou, uma assinatura que não serviu — **isso é o resultado mais valioso desta tarefa**. Acrescentar ao docstring de `tests/domains/test_generalidade.py`, na lista que já registra os dois defeitos que procurement e swe acharam, e abrir uma nota em `docs/superpowers/DECISOES.md`.

Se não achou nada, escrever isso também: um domínio que não encontra atrito é evidência de que o kernel está no lugar certo, e vale registrar.

- [ ] **Step 6: Suíte inteira e lint**

```bash
./.venv/Scripts/python.exe -m pytest -q && ./.venv/Scripts/python.exe -m ruff check src tests
```

Esperado: os 844 originais passam, mais os testes novos deste arquivo. Ruff limpo.

- [ ] **Step 7: Commit**

```bash
git add src/orchestrator/domains/redacao tests/domains/test_redacao.py src/orchestrator/domains/registro.py docs/superpowers/DECISOES.md
git commit -m "feat(domains): redacao — o pipeline que prova o pool que transforma"
```

---

## Fora deste plano (X7–X8)

`AgenteDeclarado.produz`, `Composicao.etapas`, `declarar_etapa` no entrevistador e o canvas com arestas derivadas ganham plano próprio. Duas razões:

1. **São outro subsistema** — autoria declarativa em Python mais React/React Flow, com outro ciclo de teste.
2. **O plano deles fica melhor depois** — `redacao` (Task 8) vai encontrar atrito no kernel, e escrever a via declarativa antes de saber qual atrito é escrever para uma API que ainda vai mudar.

Também fora, e deliberadamente: a limpeza da borda de conciliação (catálogo do grill, `workflows.ID_EMBUTIDO`, `models.py`/`taxonomy.py`/`metrics.py` na raiz). É trabalho real e independente — vale um terceiro plano, e nada aqui depende dele.
