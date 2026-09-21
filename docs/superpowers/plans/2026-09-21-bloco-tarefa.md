# Bloco Tarefa Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tornar `Tarefa` — o resolver que TRANSFORMA o item em vez de julgá-lo — declarável como bloco de composição, para que a cadeia escritor→revisor seja montável por dado em vez de cabeada em Python.

**Architecture:** `TarefaDeclarada` nasce ao lado de `AgenteDeclarado` e deriva as duas funções que `TarefaSpec` exige (`prompt_de`, `transformar`), do mesmo jeito que `AgenteDeclarado` já deriva `units`/`parse`/`abstain`. `Tarefa` passa a declarar `consome`/`produz` em `describe()`, sem o que o grafo derivado por `construir_composicao` sairia vazio. O bloco entra como QUARTO tipo da união discriminada, nunca como campo opcional de um bloco existente.

**Tech Stack:** Python 3.11+, dataclasses, pytest, FastAPI/Pydantic na borda. Nenhuma dependência nova.

**Spec:** `docs/superpowers/specs/2026-09-21-bloco-tarefa-design.md`

## Global Constraints

- **Português** no código e na prosa (`ferramentas`, `receita`, `divergencia`). Commits: `tipo(escopo): frase em minúscula`, assunto sem acento, corpo com o porquê e a evidência.
- **Comentário registra POR QUÊ, com evidência** — a alternativa rejeitada, o defeito evitado ou um número medido. Comentário que parafraseia o código é ruído.
- **TDD**: nenhum código de produção sem um teste que falhou antes.
- Suíte: `.venv/Scripts/python.exe -m pytest -q` (~25s). Lint: `.venv/Scripts/python.exe -m ruff check src tests`. **`ruff format` não roda e não deve rodar.**
- Teste que importa extra opcional (`fastapi`) precisa de `pytest.importorskip("fastapi")` **no topo, antes do import** — sem ele o arquivo derruba a coleta na instalação `[dev]` do CI.
- Nenhum teste fala com a rede: `tests/conftest.py::_rede_proibida` é autouse. Modelo só via `FakeLLMClient`.
- Arquivo de módulo NOVO exige entrada em `tests/arquitetura/camadas.py::DESTINO`. **Este plano não cria módulo novo** — tudo entra em arquivos existentes, de propósito.
- Ao final de cada tarefa: suíte inteira verde + `ruff check` limpo.
- Critério global do produto: `.venv/Scripts/orchestrator.exe --seed 1 --n 500` diz `85.3%`, zero falso positivo, zero falso negativo.

---

### Task 1: `TarefaDeclarada` — a tarefa como dado

**Files:**
- Modify: `src/orchestrator/agent/declarado.py` (acrescenta a dataclass depois de `AgenteDeclarado`, que termina na linha ~112)
- Test: `tests/agent/test_tarefa_declarada.py` (criar)

**Interfaces:**
- Consumes: nada de tarefas anteriores.
- Produces: `TarefaDeclarada(name: str, system: str, kind: str, produz: str, prompt: str, ferramentas: tuple[str, ...] = (), model: str = "", max_turns: int = 6, max_format_retries: int = 2, budget_microcents: int = 4_000_000, budget_total_microcents: int = 400_000_000)` — dataclass frozen, levanta `ValueError` na construção.

- [ ] **Step 1: Write the failing tests**

Criar `tests/agent/test_tarefa_declarada.py`:

```python
"""A tarefa como DADO: o que `TarefaSpec` exige em função, declarado em campo.

`TarefaSpec` pede `prompt_de` e `transformar` — duas funções Python. Um bloco
de composição é dado: `data/composicoes/*.json` é dado, e o canvas edita dado.
Esta classe é o mesmo movimento que `AgenteDeclarado` fez para o `Agent`, onde
`units`/`parse`/`abstain` deixaram de ser funções e viraram campos.
"""

import pytest

from orchestrator.agent.declarado import TarefaDeclarada


def _decl(**kw) -> TarefaDeclarada:
    base = dict(
        name="escritor",
        system="você escreve a partir de achados",
        kind="achados",
        produz="rascunho",
        prompt="Escreva a partir de: {achados}",
    )
    base.update(kw)
    return TarefaDeclarada(**base)


def test_uma_tarefa_declarada_minima_constroi():
    decl = _decl()

    assert decl.kind == "achados"
    assert decl.produz == "rascunho"
    # Sem `tipos` e sem `abstem_com`: não transformar é a AUSÊNCIA de
    # resolução, e ausência não tem rótulo de domínio para escolher — é o que
    # `tarefa.py::_abster` já diz por escrito.
    assert not hasattr(decl, "tipos")
    assert not hasattr(decl, "abstem_com")


def test_produz_VAZIO_e_recusado():
    """Consumir sem produzir faz o item sumir do run. Para descartar de
    propósito existe o `filtro` — a mesma frase que `condicao.py` usa."""
    with pytest.raises(ValueError, match="produz"):
        _decl(produz="")


def test_produz_IGUAL_ao_kind_e_recusado():
    """O ramo alimentaria a si mesmo: o item sai como `x` e volta como `x`, e o
    degrau roda de novo sobre a própria saída até o teto de rondas."""
    with pytest.raises(ValueError, match="mesmo kind"):
        _decl(kind="rascunho", produz="rascunho")


def test_prompt_que_nao_interpola_NADA_e_recusado():
    """Todo item receberia o mesmo texto, e o modelo transformaria sem ler o
    item. É caro e silencioso: a conta vem, a medida não."""
    with pytest.raises(ValueError, match="interpola"):
        _decl(prompt="escreva alguma coisa")


def test_kind_VAZIO_e_recusado():
    with pytest.raises(ValueError, match="kind"):
        _decl(kind="")


def test_orcamento_negativo_e_recusado():
    with pytest.raises(ValueError, match="negativo"):
        _decl(budget_microcents=-1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/agent/test_tarefa_declarada.py -q`
Expected: FAIL na coleta com `ImportError: cannot import name 'TarefaDeclarada'`.

- [ ] **Step 3: Write minimal implementation**

Em `src/orchestrator/agent/declarado.py`, logo após a classe `AgenteDeclarado` (antes de `def _campos`):

```python
@dataclass(frozen=True)
class TarefaDeclarada:
    """Tudo que uma TAREFA é, como dado serializável. O irmão do
    `AgenteDeclarado` para o resolver que transforma.

    **Por que não um campo `produz` no `AgenteDeclarado`.** Foi o que a §6.2 do
    spec de 2026-09-17 propôs, e o formato mudou desde então: com `produz`
    preenchido, `tipos` e `abstem_com` deixam de significar qualquer coisa —
    uma transformação não tem vocabulário de julgamento a rotular —, e um
    agente com os três é um dos cruzamentos que a união discriminada de
    `api/schemas.py` existe para recusar antes do handler rodar. O sintoma
    seria um bloco onde metade dos campos é ignorada em silêncio conforme
    outro campo.

    Sem `tipos` e sem `abstem_com`, então, e a ausência é a mesma que
    `tarefa.py::_abster` já justifica: "não há tipo a escolher: não
    transformar é a ausência de resolução, e ausência é a mesma em todo
    domínio".
    """

    name: str
    system: str
    # O que consome. Mesmo papel do `kind` do agente declarado.
    kind: str
    # O kind que SAI. É o que liga este bloco ao próximo: o degrau seguinte
    # declara `consome={produz}` e só roda quando houver item dele.
    produz: str
    # Template sobre o payload do item, como no agente declarado.
    prompt: str
    ferramentas: tuple[str, ...] = ()
    model: str = ""
    max_turns: int = 6
    max_format_retries: int = 2
    budget_microcents: int = 4_000_000
    budget_total_microcents: int = 400_000_000

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("tarefa sem nome: o trace não teria como atribuí-la")
        if not self.kind.strip():
            raise ValueError(
                f"{self.name!r} não declara `kind`. sem ele a tarefa pegaria o "
                f"pool inteiro, inclusive itens de outra natureza, e tentaria "
                f"transformar coisa que não sabe ler"
            )
        if not self.produz.strip():
            raise ValueError(
                f"{self.name!r}: `produz` vazio. a tarefa consumiria o item sem "
                f"entregá-lo a ninguém — o item sumiria do run, e para "
                f"descartar de propósito existe o `filtro`"
            )
        if self.produz == self.kind:
            raise ValueError(
                f"{self.name!r}: produz o mesmo kind que consome ({self.kind!r}). "
                f"o ramo alimentaria a si mesmo, e o degrau rodaria sobre a "
                f"própria saída até o teto de rondas"
            )
        if "{" not in self.prompt:
            raise ValueError(
                f"{self.name!r}: o prompt não interpola campo nenhum do payload "
                f"({self.prompt[:40]!r}...). todo item receberia o MESMO texto, "
                f"e o modelo transformaria sem ler o item"
            )
        if self.max_turns < 1:
            raise ValueError(f"max_turns precisa ser >= 1: {self.max_turns}")
        for nome, valor in (
            ("budget_microcents", self.budget_microcents),
            ("budget_total_microcents", self.budget_total_microcents),
        ):
            if valor < 0:
                raise ValueError(f"{nome} negativo ({valor}) nasceria estourado")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/agent/test_tarefa_declarada.py -q`
Expected: 6 passed.

- [ ] **Step 5: Suíte e lint**

Run: `.venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m ruff check src tests`
Expected: tudo verde, `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add src/orchestrator/agent/declarado.py tests/agent/test_tarefa_declarada.py
git commit -m "feat(agent): TarefaDeclarada — a tarefa como dado"
```

Corpo do commit: por que não é um campo `produz` no `AgenteDeclarado` (os cruzamentos sem sentido), e por que não tem `tipos`/`abstem_com`.

---

### Task 2: `construir_tarefa` — as duas funções, derivadas

**Files:**
- Modify: `src/orchestrator/agent/declarado.py` (extrai `_prompt_do_item` e `_ferramentas_de`; acrescenta `_transformar` e `construir_tarefa`; `_units` e `construir_agente` passam a usar os extraídos)
- Test: `tests/agent/test_tarefa_declarada.py` (acrescentar)

**Interfaces:**
- Consumes: `TarefaDeclarada` (Task 1).
- Produces:
  - `construir_tarefa(decl: TarefaDeclarada, client: LLMClient, ferramentas: ToolRegistry | None = None) -> Tarefa`
  - `_prompt_do_item(nome: str, template: str, item: WorkItem) -> str` (privado, compartilhado com `_units`)
  - `_ferramentas_de(nome: str, declaradas: tuple[str, ...], registro: ToolRegistry) -> ToolRegistry` (privado, compartilhado com `construir_agente`)

- [ ] **Step 1: Write the failing tests**

Acrescentar a `tests/agent/test_tarefa_declarada.py`:

```python
def _fake(respostas: list[str]):
    from orchestrator.agent.llm import FakeLLMClient, LLMResponse
    from orchestrator.kernel.cost import Cost

    return FakeLLMClient(
        [
            LLMResponse(text=t, tool_calls=[], cost=Cost(input_tokens=10, output_tokens=5))
            for t in respostas
        ]
    )


def _pool(kind: str, payload: dict):
    from orchestrator.kernel.work import WorkItem, WorkSet

    return WorkSet(items=(WorkItem(id="i1", kind=kind, payload=payload),))


def test_a_tarefa_declarada_TRANSFORMA_o_item():
    """O texto do modelo vira o payload de um item novo, do kind declarado.

    `payload={produz: texto}` e não texto cru: `_campos` levanta `TypeError`
    para payload que não é dict nem dataclass, então uma string crua quebraria
    o bloco SEGUINTE ao montar o prompt — e encadear é o que este bloco existe
    para permitir.
    """
    from orchestrator.agent.declarado import construir_tarefa

    tarefa = construir_tarefa(_decl(), _fake(["o rascunho pronto"]))

    saida = tarefa.resolve(_pool("achados", {"achados": "tres fatos"}))

    assert len(saida.resolutions) == 1
    assert saida.proposals == []
    (produzido,) = saida.produced
    assert produzido.kind == "rascunho"
    assert produzido.payload == {"rascunho": "o rascunho pronto"}
    assert produzido.id == "i1+rascunho"


def test_o_prompt_INTERPOLA_os_campos_do_item():
    from orchestrator.agent.declarado import construir_tarefa

    cliente = _fake(["pronto"])
    tarefa = construir_tarefa(_decl(), cliente)

    tarefa.resolve(_pool("achados", {"achados": "tres fatos"}))

    assert cliente.chamadas[0]["messages"][0]["content"] == "Escreva a partir de: tres fatos"


def test_texto_VAZIO_nao_vira_item():
    """Texto vazio não é rascunho. `None` pede retry de formato; esgotado o
    retry, o item fica no pool para o próximo degrau em vez de virar um item
    produzido que ninguém consegue usar."""
    from orchestrator.agent.declarado import construir_tarefa

    tarefa = construir_tarefa(_decl(), _fake(["   ", "   ", "   "]))

    saida = tarefa.resolve(_pool("achados", {"achados": "tres fatos"}))

    assert saida.resolutions == []
    assert saida.produced == ()


def test_ferramenta_INEXISTENTE_e_recusada_nomeando_as_que_ha():
    from orchestrator.agent.declarado import construir_tarefa

    with pytest.raises(ValueError, match="ferramenta inexistente"):
        construir_tarefa(_decl(ferramentas=("nao_existe",)), _fake(["x"]))


def test_a_tarefa_so_pega_o_KIND_que_declara():
    """Um degrau pode ter mais de um bloco, e o motor filtra pelo `consome` do
    STAGE — a união. Sem filtrar por kind aqui, a tarefa tentaria transformar o
    item que é do vizinho: `_campos` estouraria, ou pior, o modelo receberia um
    item que não é dele e a conta viria igual."""
    from orchestrator.agent.declarado import construir_tarefa
    from orchestrator.kernel.work import WorkItem, WorkSet

    cliente = _fake(["pronto"])
    tarefa = construir_tarefa(_decl(), cliente)

    saida = tarefa.resolve(
        WorkSet(
            items=(
                WorkItem(id="i1", kind="achados", payload={"achados": "tres fatos"}),
                WorkItem(id="i2", kind="outro", payload={"x": 1}),
            )
        )
    )

    assert len(saida.resolutions) == 1
    assert len(cliente.chamadas) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/agent/test_tarefa_declarada.py -q`
Expected: FAIL com `ImportError: cannot import name 'construir_tarefa'`.

- [ ] **Step 3: Extrair o que é comum**

Em `src/orchestrator/agent/declarado.py`, logo depois de `_campos`:

```python
def _prompt_do_item(nome: str, template: str, item: WorkItem) -> str:
    """O template do autor, preenchido com os campos do item.

    EXTRAÍDO de `_units` em vez de copiado para a tarefa: duas cópias divergem,
    e a que divergir é a que ninguém testa. A mensagem de campo ausente é a
    parte que não pode se perder — ela nomeia o campo E lista os disponíveis,
    que é o que permite corrigir o prompt sem abrir o payload.
    """
    campos = _campos(item.payload)
    try:
        return template.format_map(campos)
    except KeyError as erro:
        # Falha ALTO e nomeia o que falta. A alternativa — um `defaultdict` que
        # devolve vazio — produziria um prompt com buracos silenciosos, e o
        # modelo responderia sobre um item que não leu inteiro.
        raise KeyError(
            f"{nome!r}: o prompt cita {erro} e o payload de {item.id!r} não tem "
            f"esse campo. disponíveis: {sorted(campos)}"
        ) from erro


def _ferramentas_de(
    nome: str, declaradas: tuple[str, ...], registro: ToolRegistry
) -> ToolRegistry:
    """As ferramentas que a declaração pede, recortadas do registro.

    `recortar` e NÃO `ToolRegistry([registro.spec(n) for n in ...])`: a segunda
    forma perde o contexto em silêncio, e como `call` nunca levanta, toda
    ferramenta volta como erro, o laço continua e a conta cresce.
    """
    desconhecidas = sorted(set(declaradas) - set(registro.names()))
    if desconhecidas:
        raise ValueError(
            f"{nome!r} declara ferramenta inexistente: {desconhecidas}. "
            f"disponíveis: {sorted(registro.names())}"
        )
    return registro.recortar(declaradas)
```

`_units` passa a usar o primeiro (o corpo do `try/except KeyError` sai de lá):

```python
def _units(decl: AgenteDeclarado):
    def units(work: WorkSet) -> list[AgentTask]:
        return [
            AgentTask(id=item.id, prompt=_prompt_do_item(decl.name, decl.prompt, item))
            for item in work.of_kind(decl.kind)
        ]

    return units
```

E em `construir_agente`, as linhas que checam `desconhecidas` e chamam `recortar` viram:

```python
    escolhidas = _ferramentas_de(decl.name, decl.ferramentas, registro)
```

Imports a acrescentar no topo do módulo: `WorkItem` em `from orchestrator.kernel.work import WorkItem, WorkSet`.

- [ ] **Step 4: Rodar a suíte para provar que a extração não mudou nada**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: os testes de `tests/agent/test_declarado.py` continuam passando; só os novos de tarefa falham.

- [ ] **Step 5: Write `construir_tarefa`**

Ainda em `declarado.py`, depois de `construir_agente`:

```python
def _transformar(decl: TarefaDeclarada):
    """Como o texto do modelo vira o item do próximo degrau.

    É a MESMA forma que `domains/redacao/_degrau` escreve três vezes à mão —
    generalizada aqui porque, declarada, ela é sempre esta: o texto final vira
    o payload de um item novo do kind declarado.
    """

    def transformar(
        item_id: str, texto: str, custo: Cost, trace: list[TraceEvent]
    ) -> SaidaDaTarefa | None:
        if not texto.strip():
            # Texto vazio não é transformação. `None` dispara o retry de
            # formato de `conversar`; esgotado, o item fica no pool para o
            # próximo degrau.
            return None
        rastro = tuple(trace)
        return SaidaDaTarefa(
            cost=custo,
            trace=rastro,
            resolution=Resolution(
                item_ids=frozenset({item_id}),
                produced_by=decl.name,
                rule=decl.name,
                # Sem o rastro esta resolução é uma afirmação sem fonte — a
                # mesma regra que `kernel/resolution.py` aplica à proposta.
                evidence={"trace": rastro},
            ),
            produced=(
                WorkItem(
                    id=f"{item_id}+{decl.produz}",
                    kind=decl.produz,
                    # Chaveado pelo NOME DO KIND, não por um "texto" fixo: dois
                    # ramos de um `Parallel` que se reúnem num `Merge` trariam
                    # `texto` os dois, e quem lê não distinguiria de qual ramo
                    # veio. E dict, nunca string crua: `_campos` recusa payload
                    # que não seja dict ou dataclass, então texto cru quebraria
                    # o bloco seguinte ao montar o prompt.
                    payload={decl.produz: texto.strip()},
                    origem=decl.name,
                ),
            ),
        )

    return transformar


def construir_tarefa(
    decl: TarefaDeclarada,
    client: LLMClient,
    ferramentas: ToolRegistry | None = None,
) -> Tarefa:
    """A declaração vira uma `Tarefa` de verdade. VALIDA CONSTRUINDO.

    O espelho de `construir_agente`, e a `Tarefa` resultante é a MESMA que
    `domains/redacao` monta à mão — mesmo laço, mesmo orçamento em dois níveis,
    mesmo retry de formato. O que muda é de onde vêm `prompt_de` e
    `transformar`.
    """
    registro = ToolRegistry([]) if ferramentas is None else ferramentas
    escolhidas = _ferramentas_de(decl.name, decl.ferramentas, registro)

    return Tarefa(
        spec=TarefaSpec(
            name=decl.name,
            system=decl.system,
            model=decl.model or client.model,
            prompt_de=lambda item: _prompt_do_item(decl.name, decl.prompt, item),
            transformar=_transformar(decl),
            kind=decl.kind,
            produz=decl.produz,
            max_turns=decl.max_turns,
            max_format_retries=decl.max_format_retries,
            budget_microcents=decl.budget_microcents,
            budget_total_microcents=decl.budget_total_microcents,
        ),
        client=client,
        tools=escolhidas,
    )
```

Imports a acrescentar no topo de `declarado.py`:

```python
from orchestrator.agent.tarefa import SaidaDaTarefa, Tarefa, TarefaSpec
from orchestrator.kernel.resolution import Resolution
```

`kind`/`produz` em `TarefaSpec` e o filtro por kind em `Tarefa.resolve` são da Task 3 — os dois testes que dependem deles (`test_a_tarefa_so_pega_o_KIND_que_declara` e a derivação do grafo) só passam lá. Até então, `TarefaSpec(...)` com esses dois argumentos levanta `TypeError`.

- [ ] **Step 6: Rodar — e esperar TypeError, não sucesso**

Run: `.venv/Scripts/python.exe -m pytest tests/agent/test_tarefa_declarada.py -q`
Expected: FAIL com `TypeError: TarefaSpec.__init__() got an unexpected keyword argument 'kind'`. É o handoff para a Task 3; não invente os campos aqui.

---

### Task 3: `Tarefa` declara o grafo

**Files:**
- Modify: `src/orchestrator/agent/tarefa.py` (`TarefaSpec` ganha `kind`/`produz`; `describe()` os publica; `resolve()` filtra por kind)
- Modify: `src/orchestrator/domains/redacao/workflow.py` (`_degrau` passa `kind`/`produz`; os três `Stage` param de repetir `consome`/`produz`)
- Test: `tests/agent/test_tarefa.py` (acrescentar)

**Interfaces:**
- Consumes: `construir_tarefa` (Task 2).
- Produces: `TarefaSpec(..., kind: str = "", produz: str = "")`; `Tarefa.describe()` devolvendo `ResolverDescription(consome=frozenset({kind}), produz=frozenset({produz}))` quando declarados.

- [ ] **Step 1: Write the failing tests**

Acrescentar a `tests/agent/test_tarefa.py`:

```python
def test_a_tarefa_DECLARA_o_que_consome_e_o_que_produz():
    """Sem isto, `consome_de`/`produz_de` derivam conjuntos VAZIOS para uma
    tarefa composta — e `consome` vazio significa "vejo o pool inteiro". O
    sintoma seria a composição passar na tela e a execução recusar com
    "produziu kind não declarado", sobre uma escolha que a tela acabou de
    aceitar: exatamente o defeito que `produz_de` foi escrita para matar.
    """
    from orchestrator.agent.declarado import TarefaDeclarada, construir_tarefa

    tarefa = construir_tarefa(
        TarefaDeclarada(
            name="escritor",
            system="escreva",
            kind="achados",
            produz="rascunho",
            prompt="{achados}",
        ),
        _cliente_falso(["pronto"]),
    )

    d = tarefa.describe()

    assert d.consome == frozenset({"achados"})
    assert d.produz == frozenset({"rascunho"})


def test_uma_TarefaSpec_sem_kind_descreve_como_sempre():
    """Default vazio mantém a mudança retrocompatível: `domains/redacao` e
    qualquer spec escrita à mão continuam descrevendo o que descreviam."""
    spec = TarefaSpec(
        name="x", system="s", model="claude-opus-5",
        prompt_de=lambda item: "p", transformar=lambda *a: None,
    )
    tarefa = Tarefa(spec=spec, client=_cliente_falso([]), tools=ToolRegistry([]))

    d = tarefa.describe()

    assert d.consome == frozenset()
    assert d.produz == frozenset()
```

`_cliente_falso` já existe no arquivo? Se não existir, acrescentar:

```python
def _cliente_falso(textos: list[str]):
    from orchestrator.agent.llm import FakeLLMClient, LLMResponse
    from orchestrator.kernel.cost import Cost

    return FakeLLMClient(
        [
            LLMResponse(text=t, tool_calls=[], cost=Cost(input_tokens=10, output_tokens=5))
            for t in textos
        ]
    )
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/agent/test_tarefa.py -q`
Expected: FAIL com `TypeError: TarefaSpec.__init__() got an unexpected keyword argument 'kind'`.

- [ ] **Step 3: Implementar em `tarefa.py`**

Em `TarefaSpec`, depois de `transformar`:

```python
    # O GRAFO, declarado. Default vazio porque `domains/redacao` escrevia
    # `consome`/`produz` no `Stage` à mão, e uma spec que não os declara
    # precisa continuar descrevendo o que descrevia.
    #
    # Declarado e não inferido, pela mesma razão que `Stage.produz`: o canvas
    # desenha a aresta ANTES de rodar, e a recusa de beco sem saída do kernel
    # depende de saber o que sai daqui sem executar nada.
    kind: str = ""
    produz: str = ""
```

`describe()`:

```python
    def describe(self) -> ResolverDescription:
        return ResolverDescription(
            name=self.name,
            cost_class=self.cost_class,
            summary=f"tarefa {self.spec.model}",
            consome=frozenset({self.spec.kind}) if self.spec.kind else frozenset(),
            produz=frozenset({self.spec.produz}) if self.spec.produz else frozenset(),
        )
```

`resolve()` — a primeira linha do laço:

```python
        # O que ESTA tarefa pega. O motor filtra pelo `consome` do STAGE, que é
        # a UNIÃO dos blocos do degrau: num degrau com dois blocos de kinds
        # diferentes, iterar `work.items` faria esta tarefa tentar transformar
        # o item do vizinho — `_campos` estouraria, ou o modelo receberia um
        # item que não é dele e a conta viria igual. É o mesmo recorte que
        # `_units` faz para o agente, com `work.of_kind`.
        alvo = work.of_kind(self.spec.kind) if self.spec.kind else work.items
        for item in alvo:
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/agent/test_tarefa.py tests/agent/test_tarefa_declarada.py -q`
Expected: todos passam, inclusive os cinco da Task 2.

- [ ] **Step 5: `domains/redacao` para de repetir a declaração**

Em `_degrau`, o `return TarefaSpec(...)` ganha os dois campos:

```python
    return TarefaSpec(
        name=nome,
        system=system,
        model="claude-opus-5",
        prompt_de=instrucao,
        transformar=transformar,
        kind=consome_kind,
        produz=produz_kind,
    )
```

`_degrau` passa a receber `consome_kind` como parâmetro (`def _degrau(nome, system, consome_kind, produz_kind, instrucao)`), e as três chamadas passam `"topico"`, `"achados"` e `"rascunho"`. Nos três `Stage` de `definition`, apagar `consome=` e `produz=` e derivar:

```python
            Stage(
                name="pesquisar",
                cascade=(pesquisador,),
                consome=consome_de((pesquisador,)),
                produz=produz_de((pesquisador,)),
            ),
```

com `from orchestrator.kernel.definition import Stage, WorkflowDefinition, consome_de, produz_de` e cada `Tarefa` atribuída a uma variável antes. **A mesma afirmação em dois lugares é o join frágil de sempre**, e agora um dos dois é derivável.

- [ ] **Step 6: Os testes de `redacao` passam SEM serem tocados**

Run: `.venv/Scripts/python.exe -m pytest tests/domains -q`
Expected: PASS. Se algum teste de `redacao` precisar de edição, a derivação não reproduz o que estava escrito — volte ao passo 5 em vez de editar o teste.

- [ ] **Step 7: Suíte, lint e commit**

```bash
.venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m ruff check src tests
git add src/orchestrator/agent tests/agent src/orchestrator/domains/redacao/workflow.py
git commit -m "feat(agent): construir_tarefa, e a Tarefa passa a declarar o grafo"
```

Corpo: a lacuna do `describe()` sem `consome`/`produz` (composição passa, execução recusa) e por que o default é vazio.

---

### Task 4: `BlocoTarefa` no formato de composição

**Files:**
- Modify: `src/orchestrator/authoring/composicao.py` (`BlocoTarefa`, união `Bloco`, `nome_do_bloco`, `_degrau`, `_blocos_para_json`, `_blocos_de_json`, `__all__`)
- Test: `tests/authoring/test_bloco_tarefa.py` (criar)

**Interfaces:**
- Consumes: `TarefaDeclarada`, `construir_tarefa` (Tasks 1–2), grafo declarado (Task 3).
- Produces: `BlocoTarefa(declaracao: TarefaDeclarada)`; `Bloco = BlocoRegra | BlocoAgente | BlocoCrew | BlocoTarefa`; JSON `{"tipo": "tarefa", "declaracao": {...}}`.

- [ ] **Step 1: Write the failing tests**

Criar `tests/authoring/test_bloco_tarefa.py`:

```python
"""O bloco que transforma, no formato que a tela grava."""

import pytest

from orchestrator.authoring.composicao import (
    BlocoTarefa,
    Composicao,
    Etapa,
    agora,
    construir_composicao,
    de_json,
    para_json,
)
from orchestrator.agent.declarado import TarefaDeclarada


def _tarefa(nome="escritor", kind="issue", produz="rascunho") -> BlocoTarefa:
    return BlocoTarefa(
        declaracao=TarefaDeclarada(
            name=nome,
            system="escreva",
            kind=kind,
            produz=produz,
            prompt="{titulo}" if kind == "issue" else "{" + kind + "}",
        )
    )


def _composicao(*blocos, entrega=("texto_final",), etapas=None) -> Composicao:
    return Composicao(
        id="c1",
        nome="cadeia",
        gerado_em=agora(),
        etapas=etapas or (Etapa(nome="escrever", blocos=blocos),),
        entrega=entrega,
    )


def test_uma_cascata_com_bloco_TAREFA_constroi():
    definicao = construir_composicao(_composicao(_tarefa(), entrega=("rascunho",)))

    (stage,) = definicao.stages
    (resolver,) = stage.cascade
    assert resolver.name == "escritor"


def test_o_degrau_DERIVA_consome_e_produz_do_bloco():
    """É o que a Task 3 destrava: sem `describe()` publicando os dois, o stage
    sairia com conjuntos vazios e a execução recusaria o kind produzido."""
    definicao = construir_composicao(_composicao(_tarefa(), entrega=("rascunho",)))

    (stage,) = definicao.stages
    assert stage.consome == frozenset({"issue"})
    assert stage.produz == frozenset({"rascunho"})


def test_duas_etapas_ENCADEIAM_pelo_kind():
    """A cadeia que o produto não sabia montar: o revisor consome o que o
    escritor produz."""
    c = _composicao(
        etapas=(
            Etapa(nome="escrever", blocos=(_tarefa(),)),
            Etapa(
                nome="revisar",
                blocos=(_tarefa("revisor", kind="rascunho", produz="texto_final"),),
            ),
        )
    )

    definicao = construir_composicao(c)

    primeiro, segundo = definicao.stages
    assert primeiro.produz == frozenset({"rascunho"})
    assert segundo.consome == frozenset({"rascunho"})


def test_o_bloco_tarefa_SOBREVIVE_ao_disco():
    c = _composicao(_tarefa(), entrega=("rascunho",))

    voltou = de_json(para_json(c))

    assert voltou.blocos == c.blocos
    # A versão é derivada do conteúdo: dois workflows diferentes não podem
    # alegar a mesma, senão dois resultados de benchmark passam a dizer que
    # mediram a mesma cascata.
    assert voltou.version == c.version


def test_uma_composicao_de_bloco_tarefa_NAO_gasta_ao_ser_validada():
    """Compor é grátis: o cliente default é `ClienteDeValidacao`, a tranca que
    constrói o resolver e recusa falar com modelo."""
    definicao = construir_composicao(_composicao(_tarefa(), entrega=("rascunho",)))

    from orchestrator.kernel.cost import CostClass

    (stage,) = definicao.stages
    assert stage.cascade[0].cost_class is CostClass.AGENTE
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/authoring/test_bloco_tarefa.py -q`
Expected: FAIL na coleta com `ImportError: cannot import name 'BlocoTarefa'`.

- [ ] **Step 3: Implementar em `composicao.py`**

Depois de `BlocoCrew`:

```python
@dataclass(frozen=True)
class BlocoTarefa:
    """Um agente que TRANSFORMA: consome um kind e produz outro.

    O quarto tipo da união, e não um campo `produz` no `BlocoAgente` — ver o
    docstring de `TarefaDeclarada` para o porquê. O `tipo` do JSON passa a
    dizer qual CONTRATO o bloco honra: `agente` propõe e nunca resolve,
    `tarefa` resolve e nunca propõe.
    """

    declaracao: TarefaDeclarada


Bloco = BlocoRegra | BlocoAgente | BlocoCrew | BlocoTarefa
```

`nome_do_bloco` **não ganha ramo novo**: o `return b.declaracao.name` final já serve à tarefa, porque `TarefaDeclarada.name` tem o mesmo nome de campo. Acrescente só a frase ao docstring dela, para que a próxima pessoa não procure o ramo que falta:

```python
    """A IDENTIDADE de um bloco, qualquer que seja o tipo dele.

    ...

    `BlocoAgente` e `BlocoTarefa` caem no mesmo `return`: os dois carregam uma
    declaração cujo campo de nome se chama `name`. Um ramo a mais para a tarefa
    seria uma quarta cópia da mesma leitura.
    """
```

Em `_degrau`, o `elif` novo antes do `else`:

```python
        elif isinstance(bloco, BlocoTarefa):
            resolvers.append(construir_tarefa(bloco.declaracao, cliente, ferramentas))
```

Serialização — em `_blocos_para_json`:

```python
        elif isinstance(b, BlocoTarefa):
            saida.append(
                {"tipo": "tarefa", "declaracao": _tarefa_para_json(b.declaracao)}
            )
```

e em `_blocos_de_json`:

```python
        elif b["tipo"] == "tarefa":
            blocos.append(BlocoTarefa(declaracao=_tarefa_de_json(b["declaracao"])))
```

com o `else` final passando a listar os quatro: `use 'regra', 'agente', 'crew' ou 'tarefa'`.

As duas funções de tradução, ao lado de `_agente_para_json`/`_agente_de_json`:

```python
def _tarefa_para_json(t: TarefaDeclarada) -> dict[str, Any]:
    return {
        "name": t.name,
        "system": t.system,
        "kind": t.kind,
        "produz": t.produz,
        "prompt": t.prompt,
        "ferramentas": list(t.ferramentas),
        "model": t.model,
        "max_turns": t.max_turns,
        "max_format_retries": t.max_format_retries,
        "budget_microcents": t.budget_microcents,
        "budget_total_microcents": t.budget_total_microcents,
    }


def _tarefa_de_json(d: dict[str, Any]) -> TarefaDeclarada:
    return TarefaDeclarada(
        name=d["name"],
        system=d["system"],
        kind=d["kind"],
        produz=d["produz"],
        prompt=d["prompt"],
        ferramentas=tuple(d.get("ferramentas", ())),
        model=d.get("model", ""),
        max_turns=d.get("max_turns", 6),
        max_format_retries=d.get("max_format_retries", 2),
        budget_microcents=d.get("budget_microcents", 4_000_000),
        budget_total_microcents=d.get("budget_total_microcents", 400_000_000),
    )
```

Imports no topo: `TarefaDeclarada` e `construir_tarefa` de `orchestrator.agent.declarado`. E `"BlocoTarefa"` em `__all__`.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/authoring -q`
Expected: PASS, inclusive `test_tipo_de_bloco_desconhecido_LEVANTA_em_vez_de_sumir` em `tests/authoring/test_composicao.py`.

- [ ] **Step 5: Suíte, lint e commit**

```bash
.venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m ruff check src tests
git add src/orchestrator/authoring/composicao.py tests/authoring/test_bloco_tarefa.py
git commit -m "feat(authoring): BlocoTarefa — o quarto tipo, e a cadeia por kind"
```

---

### Task 5: A borda HTTP, e a cadeia escritor→revisor medida

**Files:**
- Modify: `src/orchestrator/api/schemas.py` (`TarefaDeclaradaJSON`, `BlocoTarefaJSON`, união `BlocoJSON`)
- Modify: `src/orchestrator/api/app.py` (`_declaracao_de_tarefa`, ramo em `_blocos_de`)
- Test: `tests/api/test_bloco_tarefa.py` (criar)

**Interfaces:**
- Consumes: tudo das Tasks 1–4.
- Produces: `POST /api/composicoes` aceitando `{"tipo": "tarefa", "declaracao": {...}}`; nenhuma mudança em rota existente.

- [ ] **Step 1: Write the failing tests**

Criar `tests/api/test_bloco_tarefa.py`:

```python
"""A cadeia escritor→revisor, montada por HTTP e MEDIDA.

É o §0 da spec invertido. Antes desta fatia, uma composição de duas etapas com
dois blocos de modelo fazia a etapa 2 receber os itens ORIGINAIS: medido, 4
chamadas sobre as mesmas issues, porque um agente declarado propõe e nunca
produz. Aqui o revisor precisa receber o texto do escritor.
"""

import json

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from orchestrator.api.app import app

cliente = TestClient(app)


@pytest.fixture(autouse=True)
def _raizes_isoladas(tmp_path, monkeypatch):
    import orchestrator.api.app as api_app
    from orchestrator.authoring import composicao as composicao_mod

    monkeypatch.setattr(composicao_mod, "_RAIZ_PADRAO", tmp_path / "padrao-vazia")
    monkeypatch.setattr(api_app, "_RAIZ_COMPOSICOES", tmp_path / "composicoes")
    monkeypatch.setattr(api_app, "_RAIZ_RECEITAS", tmp_path / "receitas")
    monkeypatch.setattr(api_app, "_RAIZ_FILA", tmp_path / "dados")
    monkeypatch.setattr(api_app, "_tem_chave", lambda: True)
    raiz = tmp_path / "entradas"
    raiz.mkdir()
    (raiz / "issues.csv").write_text("numero,titulo\n1,login quebra\n", encoding="utf-8")
    monkeypatch.setattr(api_app, "_RAIZ_ENTRADAS", raiz)


def _fake(monkeypatch, textos):
    import orchestrator.api.app as api_app
    from orchestrator.agent.llm import FakeLLMClient, LLMResponse
    from orchestrator.agent.teto import ClienteComTeto
    from orchestrator.kernel.cost import Cost

    fake = FakeLLMClient(
        [
            LLMResponse(text=t, tool_calls=[], cost=Cost(input_tokens=100, output_tokens=50))
            for t in textos
        ]
    )
    monkeypatch.setattr(
        api_app,
        "_cliente_de_execucao",
        lambda teto: ClienteComTeto(fake, teto_microcents=teto),
    )
    return fake


def _tarefa_json(nome, kind, produz, prompt):
    return {
        "tipo": "tarefa",
        "declaracao": {
            "name": nome,
            "system": "trabalhe o texto",
            "kind": kind,
            "produz": produz,
            "prompt": prompt,
            "ferramentas": [],
            "max_turns": 1,
            "budget_microcents": 4_000_000,
        },
    }


_FONTE = {"tipo": "arquivo", "caminho": "issues.csv", "kind": "issue", "campo_id": "numero"}


def test_a_cadeia_escritor_revisor_MONTA_e_o_revisor_le_o_escritor(monkeypatch):
    fake = _fake(monkeypatch, ["rascunho do escritor", "versao revisada"])
    corpo = {
        "id": "cadeia",
        "nome": "cadeia",
        "etapas": [
            {"nome": "escrever", "blocos": [
                _tarefa_json("escritor", "issue", "rascunho", "Escreva sobre: {titulo}")]},
            {"nome": "revisar", "blocos": [
                _tarefa_json("revisor", "rascunho", "texto_final", "Revise: {rascunho}")]},
        ],
        "entrega": ["texto_final"],
    }
    assert cliente.post("/api/composicoes", json=corpo).status_code == 201

    r = cliente.post(
        "/api/workflows/cadeia/runs",
        json={"fonte": _FONTE, "teto_microcents": 10_000_000},
    )

    assert r.status_code == 200, r.text
    # A prova: o prompt do SEGUNDO degrau carrega a saída do primeiro.
    assert fake.chamadas[-1]["messages"][0]["content"] == "Revise: rascunho do escritor"


def test_o_run_da_cadeia_RESOLVE_em_vez_de_so_propor(monkeypatch):
    """Um agente declarado propõe e o item fica no pool; uma tarefa resolve. É a
    diferença que o `por_resolver` do run mostra."""
    _fake(monkeypatch, ["rascunho do escritor", "versao revisada"])
    corpo = {
        "id": "cadeia2",
        "nome": "cadeia",
        "etapas": [
            {"nome": "escrever", "blocos": [
                _tarefa_json("escritor", "issue", "rascunho", "Escreva sobre: {titulo}")]},
            {"nome": "revisar", "blocos": [
                _tarefa_json("revisor", "rascunho", "texto_final", "Revise: {rascunho}")]},
        ],
        "entrega": ["texto_final"],
    }
    assert cliente.post("/api/composicoes", json=corpo).status_code == 201

    r = cliente.post(
        "/api/workflows/cadeia2/runs",
        json={"fonte": _FONTE, "teto_microcents": 10_000_000},
    )

    corpo_run = r.json()
    por_nome = {p["name"]: p for p in corpo_run["por_resolver"]}
    assert por_nome["escritor"]["matches"] == 1
    assert por_nome["revisor"]["matches"] == 1
    assert corpo_run["propostas_por_tipo"] == {}


def test_produz_igual_ao_kind_vira_422_com_o_MOTIVO(monkeypatch):
    """A recusa de domínio atravessa como 422 com o texto escrito para ser
    lido, não como "field required" do Pydantic."""
    corpo = {
        "id": "ruim",
        "nome": "ruim",
        "blocos": [_tarefa_json("ciclo", "issue", "issue", "{titulo}")],
    }

    r = cliente.post("/api/composicoes", json=corpo)

    assert r.status_code == 422, r.text
    assert "mesmo kind" in r.json()["detail"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_bloco_tarefa.py -q`
Expected: FAIL — o Pydantic recusa `"tipo": "tarefa"` na união discriminada, com 422 nomeando os três tipos que ele conhece.

- [ ] **Step 3: Implementar o schema**

Em `src/orchestrator/api/schemas.py`, depois de `AgenteDeclaradoJSON`:

```python
class TarefaDeclaradaJSON(BaseModel):
    """Uma tarefa como dado. Sem `tipos` e sem `abstem_com`, e a ausência é o
    contrato: transformar não tem vocabulário de julgamento a rotular."""

    name: str
    system: str
    kind: str
    produz: str
    prompt: str
    ferramentas: list[str]
    max_turns: int
    budget_microcents: int
```

e depois de `BlocoCrewJSON`:

```python
class BlocoTarefaJSON(BaseModel):
    tipo: Literal["tarefa"]
    declaracao: TarefaDeclaradaJSON


BlocoJSON = Annotated[
    BlocoRegraJSON | BlocoAgenteJSON | BlocoCrewJSON | BlocoTarefaJSON,
    Field(discriminator="tipo"),
]
```

- [ ] **Step 4: Implementar a tradução na borda**

Em `src/orchestrator/api/app.py`, ao lado de `_declaracao`:

```python
def _declaracao_de_tarefa(d: TarefaDeclaradaJSON) -> TarefaDeclarada:
    """Um `TarefaDeclarada` a partir do JSON. Levanta `ValueError` do DOMÍNIO —
    prompt que não interpola, `produz` vazio, `produz == kind` —, e é
    `_blocos_de` quem o transforma em 422 com o texto de lá."""
    return TarefaDeclarada(
        name=d.name,
        system=d.system,
        kind=d.kind,
        produz=d.produz,
        prompt=d.prompt,
        ferramentas=tuple(d.ferramentas),
        max_turns=d.max_turns,
        budget_microcents=d.budget_microcents,
    )
```

Em `_blocos_de`, antes do trecho que trata o agente:

```python
        if b.tipo == "tarefa":
            try:
                blocos.append(BlocoTarefa(declaracao=_declaracao_de_tarefa(b.declaracao)))
            except ValueError as erro:
                raise HTTPException(status_code=422, detail=str(erro)) from erro
            continue
```

Imports: `TarefaDeclarada` de `orchestrator.agent.declarado`, `BlocoTarefa` de `orchestrator.authoring.composicao`, `TarefaDeclaradaJSON` do bloco de `orchestrator.api.schemas` (mantendo a lista em ordem alfabética, senão `ruff` reclama de `I001`).

- [ ] **Step 5: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_bloco_tarefa.py -q`
Expected: 3 passed.

- [ ] **Step 6: Suíte, lint, número do produto**

```bash
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check src tests
.venv/Scripts/orchestrator.exe --seed 1 --n 500
```
Expected: suíte verde, lint limpo, `85.3%` com zero falso positivo e zero falso negativo.

- [ ] **Step 7: Commit**

```bash
git add src/orchestrator/api tests/api/test_bloco_tarefa.py
git commit -m "feat(api): o bloco tarefa chega na borda, e a cadeia e medida"
```

Corpo: a medição do §0 da spec invertida — o revisor recebendo o texto do escritor, em vez das mesmas issues.

---

## Fora deste plano, de propósito

- **Canvas** (paleta, editor do bloco em `web-app/src`, `npx tsc --noEmit`, bundle de `web/` commitado): fatia seguinte, commit próprio. É também onde entra publicar o tipo novo em `GET /api/catalogo` — sem a tela, uma lista de tarefas prontas seria cerimônia sobre uma lista vazia.
- **Ramificação por tipo** (`Mapping[str, str]` da §6.2 do spec de 2026-09-17): `condicao` já roteia.
- **A lacuna do teto silencioso** de `Tarefa.resolve`: declarada em `tarefa.py`, exige canal novo em `ResolverOutput`.
