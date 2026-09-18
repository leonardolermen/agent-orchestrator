# A composição do canvas roda por `/runs` — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Uma composição feita no canvas aparece no seletor, roda por `/runs` sobre um arquivo do usuário com teto, e um `kind` que a fonte não entrega é recusado **antes de gastar**, nomeando o bloco.

**Architecture:** Todo resolver declara o que consome (`ResolverDescription.consome`, `AgentSpec.consome`); `consome_de(cascade)` deriva `Stage.consome` nos três construtores; a borda do `/runs` recusa por resolver sobre os kinds do pool carregado; `_de_composicao` entra no `registry()` ao lado de `_de_receita`; o canvas entrega para a tela de execução. O `investigador` do catálogo, cego desde o rename, é consertado antes de a guarda existir.

**Tech Stack:** Python 3.13, FastAPI, pydantic, pytest, ruff; React 18 + Vite + Tailwind (`web-app/`), bundle commitado em `web/`.

**Spec:** `docs/superpowers/specs/2026-09-19-canvas-para-runs-design.md`

**Desvio declarado da spec (§3.2):** `consome_de` mora em `src/orchestrator/kernel/definition.py`, ao lado de `Stage`, e **não** em `workflows.py`. Motivo: a Task 5 faz `workflows.py` importar `authoring.composicao`, e `construir_composicao` precisa chamar `consome_de` — em `workflows.py` isso seria um ciclo. `consome_de` só lê `Resolver.describe()`; é conhecimento de kernel.

**Ordem que importa:** a Task 3 (conserto do `investigador`) vem **antes** da Task 4 (a borda). Invertida, a borda recusaria com 422 toda receita existente com `investigador` sobre a fonte sintética — e os testes que hoje rodam esse agente cego quebrariam por acidente em vez de por decisão.

## Global Constraints

- Nenhum teste chama API paga. A tranca de rede de `tests/conftest.py::_rede_proibida` continua e **não é tocada**. Rodar a suíte com `ANTHROPIC_API_KEY` de lixo tem que dar o mesmo resultado.
- `ClienteAusente` continua o default de `grill.receita.construir`; `ClienteDeValidacao`, o de `construir_composicao`. `ctx.cliente` é repassado verbatim, inclusive `None`.
- Configuração inválida falha alto; nunca fallback silencioso.
- AUSENTE, não zero — nunca um número com cara de medido sobre o que não foi medido. Nenhum caminho devolve 200 sobre um pool que ninguém leu.
- Dinheiro em inteiro de micro-centavos.
- Código, comentários e docstrings em **português**; docstring explica POR QUE, não O QUE.
- `consome` é **declarado**, nunca inferido de `payloads` nem derivado dentro do kernel. Vazio = "vê o pool inteiro" — o mesmo significado do default de `Stage.consome`.
- Rodar: `./.venv/Scripts/python.exe -m pytest -q`. Lint: `./.venv/Scripts/python.exe -m ruff check .`. Front: `cd web-app && npx tsc --noEmit && npm run build` (o `--prefix` do npx **não** typechecka) e **commitar o bundle** (`web/assets/*`, `web/index.html`) junto com a fonte.
- Baseline ao começar: **977 passed, 1 skipped, 1 xfailed**. O skip é o teste de symlink (privilégio que o Windows não dá); o xfail é `strict=True` e deliberado (a lacuna do produtor). Nenhum dos dois muda de estado nesta fatia.

## Estrutura de arquivos

| Arquivo | Responsabilidade | Task |
|---|---|---|
| `src/orchestrator/kernel/resolver.py` | `ResolverDescription.consome` | 1 |
| `src/orchestrator/agent/agent.py` | `AgentSpec.consome`; `Agent.describe()` a repassa | 1 |
| `src/orchestrator/agent/declarado.py` | `construir_agente` declara `{decl.kind}` | 1 |
| `src/orchestrator/agent/investigator.py` | o investigador em Python declara `frozenset(PAYLOADS)` | 1 |
| `src/orchestrator/matching/{exact,grouping,tolerance}.py`, `review/revisor.py`, `domains/procurement/workflow.py` | regras declaram `frozenset(PAYLOADS)` | 1 |
| `tests/domains/test_registro.py` | a tabela que pina `consome` de todo bloco | 1, 3 |
| `src/orchestrator/kernel/definition.py` | `consome_de(cascade)` | 2 |
| `src/orchestrator/authoring/composicao.py`, `grill/receita.py`, `conciliacao/workflow.py` | os três construtores populam `Stage.consome` | 2 |
| `tests/test_fiacao_derivada.py` **(novo)** | `consome_de` e os três construtores | 2 |
| `src/orchestrator/domains/registro.py` | `investigador` sobre `banco`, prompt sobre `BankEntry` | 3 |
| `src/orchestrator/api/app.py` | `_conferir_kinds`; `registry(..., _RAIZ_COMPOSICOES)`; 409; `gerado_em` | 4, 5 |
| `src/orchestrator/workflows.py` | `_de_composicao`; `registry`/`descrever` com raiz de composições | 5 |
| `tests/api/test_execucao.py` | a borda; os dois testes que viram; o fim-a-fim via composição | 4, 5 |
| `tests/test_workflows.py` | registry: ordem, colisão, pulo-com-aviso | 5 |
| `web-app/src/App.tsx`, `Painel.tsx` | hand-off; cópia; painel de resultado sai | 6 |
| `tests/api/test_compor.py` | asserções de bundle | 6 |
| `README.md`, `authoring/composicao.py` (cabeçalho), `docs/superpowers/DECISOES.md` | os textos que diziam "aberta" | 7 |

---

### Task 1: O contrato `consome` — declarado em todo resolver

**Files:**
- Modify: `src/orchestrator/kernel/resolver.py` (após o campo `payloads` de `ResolverDescription`)
- Modify: `src/orchestrator/agent/agent.py` (`AgentSpec`, `Agent.describe`)
- Modify: `src/orchestrator/agent/declarado.py` (`construir_agente`, o `AgentSpec(`)
- Modify: `src/orchestrator/agent/investigator.py` (o `AgentSpec(`)
- Modify: `src/orchestrator/matching/exact.py`, `matching/grouping.py`, `matching/tolerance.py`, `review/revisor.py`, `domains/procurement/workflow.py` (cada `describe()`)
- Test: `tests/domains/test_registro.py`

**Interfaces:**
- Produces: `ResolverDescription.consome: frozenset[str]` (default `frozenset()`); `AgentSpec.consome: frozenset[str]` (default `frozenset()`), repassado por `Agent.describe()`.

**Nada lê `consome` ainda.** Esta task só declara. A suíte inteira continua com o mesmo resultado — é o critério de aceite dela.

- [ ] **Step 1: A tabela que falha**

Em `tests/domains/test_registro.py`, ao lado de `test_TODO_bloco_do_catalogo_declara_o_payload_que_exige`. Reusa dois helpers que o arquivo já tem: `_blocos()`, que devolve pares `(nome, bloco)` para regras e agentes, e `_construir(bloco)`:

```python
# O que cada bloco do CATALOGO declara CONSUMIR. Pinado em tabela, e não
# derivado de `payloads`, porque são perguntas diferentes: `payloads` é "que
# TIPO exijo deste kind"; `consome` é "que KINDS pego do pool". O `triador` lê
# dicionário e não exige tipo nenhum, mas consome `issue` — sem esta tabela
# ele passaria como "vê o pool inteiro" por default, e a borda do `/runs` não
# teria como dizer que um CSV de lançamentos não é para ele.
CONSOME_ESPERADO: dict[str, frozenset[str]] = {
    "L1": frozenset({"banco", "contabil"}),
    "L2": frozenset({"banco", "contabil"}),
    "L3": frozenset({"banco", "contabil"}),
    "revisor": frozenset({"banco", "contabil"}),
    "preferido": frozenset({"requisicao", "fornecedor"}),
    "anteriores": frozenset({"requisicao", "fornecedor"}),
    # `lancamento` é o que ele DECLARA hoje — e nenhuma fonte produz. A Task 3
    # deste plano corrige o bloco e troca esta linha para {"banco"}.
    "investigador": frozenset({"lancamento"}),
    "triador": frozenset({"issue"}),
    "buscador": frozenset({"requisicao"}),
}


def test_TODO_bloco_do_catalogo_declara_o_que_CONSOME():
    """Bloco sem entrada aqui falha ALTO: quem escreve o próximo resolver
    decide o que ele consome, em vez de herdar "tudo" por default e ficar
    invisível para a guarda da borda."""
    for nome, bloco in _blocos():
        assert nome in CONSOME_ESPERADO, (
            f"{nome!r} não está na tabela CONSOME_ESPERADO. Decida quais kinds "
            f"ele pega do pool e acrescente a linha."
        )
        assert _construir(bloco).describe().consome == CONSOME_ESPERADO[nome], nome


def test_a_tabela_de_consumo_nao_tem_bloco_FANTASMA():
    """O outro lado, igual ao de `payloads`: um nome que saiu do catálogo e
    ficou na tabela protegeria um bloco que não existe mais."""
    assert set(CONSOME_ESPERADO) == {nome for nome, _ in _blocos()}


def test_agente_DECLARADO_consome_exatamente_o_kind_que_declara():
    """O kind de um `AgenteDeclarado` era APAGADO na construção — virava a
    closure de `units` — e `Agent.describe()` não tinha de onde lê-lo. Agora a
    spec o carrega, e é isso que a borda lê."""
    from orchestrator.agent.declarado import ClienteDeValidacao, construir_agente

    triador = next(a for a in CATALOGO.agentes if a.name == "triador")
    agente = construir_agente(triador, ClienteDeValidacao(), CATALOGO.ferramentas)
    assert agente.describe().consome == frozenset({"issue"})
```

Confira o nome do atributo dos blocos de regra (`nome`) e dos agentes (`name`) contra o que `test_a_tabela_de_exigencias_nao_tem_bloco_FANTASMA` já usa no mesmo arquivo, e use exatamente o mesmo.

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/domains/test_registro.py -q -k "CONSOME or consumo or DECLARADO_consome"
```

Esperado: `AttributeError: 'ResolverDescription' object has no attribute 'consome'` (ou `TypeError` no `AgentSpec`).

- [ ] **Step 3: O campo no kernel**

Em `src/orchestrator/kernel/resolver.py`, logo depois de `payloads: dict[str, type] = field(default_factory=dict)`:

```python
    # Quais `WorkItem.kind` este resolver PEGA do pool. Vazio — o default — é
    # "vejo o pool inteiro", o MESMO significado do default de `Stage.consome`.
    #
    # Não é derivado de `payloads`, de propósito: `payloads` diz que TIPO exijo
    # de um kind; `consome` diz que KINDS pego. O `investigador` lê objetos
    # tipados por ferramentas; o `triador` lê dicionário e não exige tipo — e
    # ambos consomem um kind só. Amarrar as duas perguntas obrigaria um agente
    # a declarar um tipo para dizer o que consome, e a borda de `payloads`
    # passaria a recusar fonte válida.
    #
    # DECLARADO, pela mesma razão de `payloads` e de `Stage.produz`: quem
    # compõe precisa da recusa ANTES de executar. Quem lê é `consome_de`
    # (`kernel/definition.py`), que popula `Stage.consome`, e a borda do
    # `/runs`, que confere cada resolver contra os kinds da fonte.
    consome: frozenset[str] = frozenset()
```

- [ ] **Step 4: A spec do agente carrega o que consome**

Em `src/orchestrator/agent/agent.py`, na `AgentSpec`, logo depois de `max_format_retries: int = 2`:

```python
    # Quais `WorkItem.kind` este agente pega do pool. Vazio = o pool inteiro.
    # Mora na SPEC porque o kind de um `AgenteDeclarado` é apagado na
    # construção — vira a closure de `units` — e `describe()` não teria de
    # onde lê-lo. A spec é a declaração; `describe()` a repassa.
    consome: frozenset[str] = frozenset()
```

E em `Agent.describe()`:

```python
    def describe(self) -> ResolverDescription:
        return ResolverDescription(
            name=self.name,
            cost_class=self.cost_class,
            summary=f"agente {self.spec.model}",
            consome=self.spec.consome,
        )
```

- [ ] **Step 5: Quem constrói agente declara**

Em `src/orchestrator/agent/declarado.py`, no `AgentSpec(` de `construir_agente`, logo depois de `units=_units(decl),`:

```python
            # Um kind só, porque `AgenteDeclarado.kind: str`. É o mesmo kind
            # que `_units` filtra com `work.of_kind(decl.kind)`.
            consome=frozenset({decl.kind}),
```

Em `src/orchestrator/agent/investigator.py`, no `AgentSpec(`, logo depois de `units=lambda work: [...],`:

```python
        # Lê os DOIS lados de uma vez: `divergencias(work)` pareia banco e
        # contábil. As chaves de PAYLOADS são exatamente esses dois kinds.
        consome=frozenset(PAYLOADS),
```

(`PAYLOADS` já é importado nesse módulo.)

- [ ] **Step 6: Toda regra declara**

Em cada `describe()` que já passa `payloads=PAYLOADS`, acrescente `consome=frozenset(PAYLOADS)`:

`src/orchestrator/matching/exact.py`, `matching/grouping.py`, `matching/tolerance.py`, `review/revisor.py`:

```python
            payloads=PAYLOADS,
            consome=frozenset(PAYLOADS),
```

`src/orchestrator/domains/procurement/workflow.py` (três `describe()`, chamada posicional):

```python
        return ResolverDescription(
            self.name, self.cost_class, "fornecedor preferido",
            payloads=PAYLOADS, consome=frozenset(PAYLOADS),
        )
```

(idem para `"compras anteriores"` e `"busca fornecedor novo"`).

- [ ] **Step 7: Rodar os novos e a suíte**

```bash
./.venv/Scripts/python.exe -m pytest tests/domains/test_registro.py -q
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m ruff check .
```

Esperado: os novos passam; suíte **977 + 3 passed**, 1 skipped, 1 xfailed. Nada mudou de comportamento.

- [ ] **Step 8: Commit**

```bash
git add src/orchestrator tests/domains/test_registro.py
git commit -m "feat(kernel,agent): todo resolver declara o que CONSOME — irma de payloads, lida pela borda"
```

---

### Task 2: `consome_de`, e os três construtores populam `Stage.consome`

**Files:**
- Modify: `src/orchestrator/kernel/definition.py` (nova função, após `Stage`)
- Modify: `src/orchestrator/authoring/composicao.py` (o `return WorkflowDefinition(` de `construir_composicao`)
- Modify: `src/orchestrator/grill/receita.py` (o `return WorkflowDefinition(` de `construir`)
- Modify: `src/orchestrator/conciliacao/workflow.py` (`default_definition`)
- Modify: `tests/api/test_composicoes.py` (o docstring do teste que pina o comportamento inerte)
- Test: `tests/test_fiacao_derivada.py` (novo)

**Interfaces:**
- Consumes: `ResolverDescription.consome` (Task 1).
- Produces: `consome_de(cascade: Iterable[Resolver]) -> frozenset[str]` em `orchestrator.kernel.definition`.

**Efeito no motor, esperado:** um stage com `consome` populado **reserva** os itens de outros kinds (`runtime/engine.py:108–112`) e não roda se não enxergar nenhum (`:115`). Os testes que rodam a conciliação sobre um CSV de kind `lancamento`/`k` continuam devolvendo 200 com lacuna de 100% nesta task — antes os resolvers viam os itens e não casavam nada; agora não os veem. Eles viram 422 só na Task 4.

- [ ] **Step 1: Os testes que falham**

`tests/test_fiacao_derivada.py`:

```python
"""A fiação derivada: `consome_de` e os três construtores que a usam.

Uma função, três chamadas explícitas — e não uma derivação dentro de
`Stage.__post_init__`. Popular `consome` no kernel trocaria em silêncio o
significado do default vazio ("vê o pool inteiro") para toda definição escrita
em Python. Aqui cada construtor decide, e o kernel não muda de semântica.
"""

from datetime import UTC, datetime

from orchestrator.agent.declarado import AgenteDeclarado
from orchestrator.authoring.composicao import (
    BlocoAgente,
    BlocoRegra,
    Composicao,
    construir_composicao,
)
from orchestrator.conciliacao import default_definition
from orchestrator.domains.registro import CATALOGO
from orchestrator.grill.receita import Receita, ResolverReceita, construir
from orchestrator.kernel.definition import consome_de


def _regra(nome):
    return next(r for r in CATALOGO.regras if r.nome == nome).construir({})


def test_consome_de_e_a_UNIAO_do_que_cada_resolver_declara():
    assert consome_de([_regra("L1"), _regra("preferido")]) == frozenset(
        {"banco", "contabil", "requisicao", "fornecedor"}
    )


def test_consome_de_cascata_vazia_e_vazio_e_nao_levanta():
    assert consome_de([]) == frozenset()


def test_a_conciliacao_EMBUTIDA_consome_banco_e_contabil():
    (stage,) = default_definition().stages
    assert stage.consome == frozenset({"banco", "contabil"})


def test_uma_RECEITA_consome_a_uniao_dos_blocos():
    receita = Receita(
        id="r", nome="r", justificativa="", gerado_em=datetime.now(UTC),
        resolvers=(ResolverReceita(nome="L1", parametros={}),),
    )
    (stage,) = construir(receita).stages
    assert stage.consome == frozenset({"banco", "contabil"})


def test_uma_COMPOSICAO_consome_os_kinds_dos_blocos_inclusive_do_agente():
    """A ponta que o cabeçalho de `authoring/composicao.py` chamava de X7:
    `construir_composicao` passa a POPULAR `consome` a partir dos blocos."""
    decl = AgenteDeclarado(
        name="meu-triador", system="classifique", kind="issue",
        prompt="{titulo}", tipos=("BUG",), abstem_com="NAO_SEI",
    )
    c = Composicao(
        id="c", nome="c", gerado_em=datetime.now(UTC),
        blocos=(BlocoRegra(nome="L1", parametros={}), BlocoAgente(declaracao=decl)),
    )
    (stage,) = construir_composicao(c).stages
    assert stage.consome == frozenset({"banco", "contabil", "issue"})
```

Confira as assinaturas de `Receita`/`ResolverReceita` (`grill/receita.py:45–57`) e de `Composicao` (`authoring/composicao.py:97`) e ajuste os campos obrigatórios se algum nome divergir — o teste tem que construir objetos válidos, não fantasias.

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_fiacao_derivada.py -q
```

Esperado: `ImportError: cannot import name 'consome_de'`.

- [ ] **Step 3: `consome_de` no kernel**

Em `src/orchestrator/kernel/definition.py`, logo depois da classe `Stage`:

```python
def consome_de(cascade: Iterable[Resolver]) -> frozenset[str]:
    """A união do que cada resolver da cascata declara consumir.

    Mora aqui, e não em `workflows.py`, por um motivo mecânico e um de
    desenho. O mecânico: `authoring/composicao.py` precisa chamar isto, e
    `workflows.py` importa `authoring/composicao.py` — em `workflows.py` seria
    um ciclo. O de desenho: esta função só lê `Resolver.describe()`; é
    conhecimento de kernel, sem domínio.

    E é uma FUNÇÃO chamada por cada construtor, não uma derivação em
    `Stage.__post_init__`: popular `consome` no kernel trocaria em silêncio o
    significado do default vazio ("vê o pool inteiro") para toda definição
    escrita em Python. Cada construtor decide; o kernel não muda de semântica.
    """
    return frozenset().union(*(r.describe().consome for r in cascade))
```

Acrescente `from collections.abc import Iterable` aos imports do módulo se ainda não existir. `Resolver` já é importado (a `Stage` o usa).

- [ ] **Step 4: Os três construtores**

`src/orchestrator/authoring/composicao.py`, no `return WorkflowDefinition(` de `construir_composicao`:

```python
        stages=(
            Stage(
                name=c.nome,
                cascade=tuple(resolvers),
                # A fiação DESTE degrau, derivada dos blocos — a ponta X7 que
                # o cabeçalho deste módulo dizia faltar. `produz` continua no
                # default: nenhum bloco do catálogo produz item.
                consome=consome_de(resolvers),
            ),
        ),
```

com `from orchestrator.kernel.definition import Stage, WorkflowDefinition, consome_de`.

`src/orchestrator/grill/receita.py`, no `return WorkflowDefinition(` de `construir`:

```python
        stages=(
            Stage(
                name="conciliar lançamentos",
                cascade=tuple(resolvers),
                consome=consome_de(resolvers),
            ),
        ),
```

com o mesmo import.

`src/orchestrator/conciliacao/workflow.py`, em `default_definition`:

```python
    revisor = RevisorHumano(fila=fila if fila is not None else Fila.vazia())
    cascata = (*default_resolvers(), revisor)
    return WorkflowDefinition(
        id="conciliacao",
        name="Conciliação bancária",
        stages=(
            Stage(
                name="conciliar lançamentos",
                cascade=cascata,
                consome=consome_de(cascata),
                policy=policy or POLITICA_ATUAL,
            ),
        ),
    )
```

com `consome_de` importado de `orchestrator.kernel.definition` ao lado de `Stage`.

- [ ] **Step 5: O teste que pinava o comportamento inerte**

Em `tests/api/test_composicoes.py`, no teste cujo docstring diz *"Para uma composição desta rota, a do grafo está inerte — `construir_composicao` devolve um stage com `consome`/`produz` no default e não os popula"* (por volta da linha 159): **mantenha a asserção `assert r.status_code == 201`** e substitua o parágrafo *"O que este teste NÃO afirma"* por:

```
    **O que este teste afirma, e o que não afirma.** Afirma que a composição
    é ACEITA ao salvar: ela não conhece a fonte, e "valida construindo"
    continua sendo a garantia. NÃO afirma que `lancamento` é um kind que
    alguma fonte produz — hoje nenhuma produz. A guarda que pega isso mora na
    BORDA do `/runs`, por resolver, contra os kinds da fonte que vai rodar
    (`tests/api/test_execucao.py::test_a_borda_recusa_bloco_que_a_fonte_NAO_alimenta`),
    e `Stage.consome` passou a carregar o kind para ela ler
    (`tests/test_fiacao_derivada.py`). A guarda antiga — partição de catálogo
    — saiu porque recusava cascata válida; esta compara o grafo que VAI
    rodar com a fonte que VAI rodar.
```

- [ ] **Step 6: Suíte, lint**

```bash
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m ruff check .
```

Esperado: tudo verde (**980 + 5 passed**). Se algum teste de `tests/api/test_execucao.py` mudar de resultado aqui, **pare e leia**: nesta task nenhum 200 deve virar 422 — isso é a Task 4.

- [ ] **Step 7: Commit**

```bash
git add src/orchestrator tests/test_fiacao_derivada.py tests/api/test_composicoes.py
git commit -m "feat(kernel): consome_de — os tres construtores populam Stage.consome a partir dos blocos"
```

---

### Task 3: O `investigador` do catálogo deixa de ser cego

**Files:**
- Modify: `src/orchestrator/domains/registro.py` (o `AgenteDeclarado(name="investigador", ...)`)
- Modify: `tests/domains/test_registro.py` (a linha `"investigador"` de `CONSOME_ESPERADO`)
- Test: `tests/domains/test_investigador_do_catalogo.py` (novo)

**Interfaces:**
- Consumes: `construir_agente`, `CATALOGO`, `SyntheticSource`.
- Produces: `investigador` do catálogo com `kind="banco"` e prompt sobre os campos de `BankEntry`.

**Por que antes da borda.** A fonte sintética emite `banco` e `contabil` (`models.py:113–114`); o bloco declara `lancamento`, que nenhuma fonte produz; e o prompt `"Divergência {id}: {descricao}"` cita um campo que `BankEntry` não tem. `grill.receita.construir` constrói agentes a partir desta declaração, então `pago.json` está cego desde o rename. Com a borda da Task 4 no lugar, toda receita com `investigador` sobre a sintética viraria 422 — corretamente. Consertar antes faz a guarda nascer sem quebrar nada por acidente.

- [ ] **Step 1: O teste que prova a cegueira, e que falha**

`tests/domains/test_investigador_do_catalogo.py`:

```python
"""O `investigador` DECLARADO do catálogo — não o de `agent/investigator.py`.

Ele estava cego desde o rename do domínio: declarava `kind="lancamento"`, que
nenhuma fonte produz, e um prompt sobre `{descricao}`, campo que `BankEntry`
não tem. Compor `L1 + investigador` rodava com o agente sem ver item nenhum —
o modo de falha que o cabeçalho de `authoring/composicao.py` descreve, dentro
do próprio catálogo.
"""

from orchestrator.agent.declarado import construir_agente
from orchestrator.agent.llm import FakeLLMClient
from orchestrator.domains.registro import CATALOGO
from orchestrator.synth.benchmark import SyntheticSource


def _investigador():
    return next(a for a in CATALOGO.agentes if a.name == "investigador")


def test_o_investigador_do_catalogo_consome_um_kind_que_a_fonte_PRODUZ():
    kinds = {i.kind for i in SyntheticSource(seed=1, n=30, taxa_divergencia=0.15).load().items}
    assert _investigador().kind in kinds


def test_o_investigador_do_catalogo_VE_itens_e_o_prompt_RENDERIZA():
    """Sem estas duas linhas, um agente cego e um agente que vê são iguais
    para a suíte: nenhum dos dois falha. `units` vazio é o sintoma da
    cegueira; `KeyError` no prompt seria o sintoma de trocar só o kind."""
    pool = SyntheticSource(seed=1, n=30, taxa_divergencia=0.15).load()
    agente = construir_agente(_investigador(), FakeLLMClient([]), CATALOGO.ferramentas)

    tarefas = agente.spec.units(pool)

    assert tarefas, "o investigador não montou tarefa nenhuma: continua cego"
    assert all("{" not in t.prompt for t in tarefas), "campo sem interpolar no prompt"
    assert agente.describe().consome == frozenset({"banco"})
```

`FakeLLMClient` é o de `orchestrator.agent.llm` — o mesmo que `tests/agent/test_declarado.py` usa. **Nunca** um cliente de verdade.

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/domains/test_investigador_do_catalogo.py -q
```

Esperado: o primeiro falha (`lancamento` não está em `{banco, contabil}`); o segundo falha em `assert tarefas`.

- [ ] **Step 3: O conserto**

Em `src/orchestrator/domains/registro.py`, no `AgenteDeclarado(name="investigador", ...)`:

```python
        AgenteDeclarado(
            name="investigador",
            system=_PROMPT_INVESTIGADOR,
            # `banco`, não `lancamento`: `lancamento` era o kind do domínio
            # antigo, renomeado para banco/contabil sem este bloco acompanhar.
            # Nenhuma fonte o produz, e o agente rodava sem ver item nenhum.
            # Um kind só, como todo `AgenteDeclarado`: ele parte de UM
            # lançamento bancário por tarefa e usa as ferramentas para ver o
            # lado contábil.
            kind="banco",
            # Os campos que `_campos` (asdict) expõe de um `BankEntry`. O
            # prompt antigo citava `{descricao}`, de uma `Divergence` que a
            # fonte não entrega, e levantaria KeyError no primeiro item.
            prompt=(
                "Lançamento bancário {id} de {date}: {description}. "
                "Valor {amount}, contraparte {counterparty}, documento {document}. "
                "Investigue a divergência com o lado contábil."
            ),
            tipos=(
                "DEFASAGEM_TEMPORAL",
                "DEVOLUCAO_FUNDOS",
                "PAGAMENTO_AGREGADO",
                "RETENCAO_IMPOSTO",
            ),
            abstem_com="NAO_IDENTIFICADO",
            ferramentas=catalogo_de_ferramentas().names(),
            max_turns=6,
        ),
```

E em `tests/domains/test_registro.py`, `CONSOME_ESPERADO["investigador"]` passa a `frozenset({"banco"})`, apagando o comentário que apontava para esta task.

- [ ] **Step 4: Rodar os novos, e a suíte INTEIRA — leia as falhas**

```bash
./.venv/Scripts/python.exe -m pytest tests/domains -q
./.venv/Scripts/python.exe -m pytest -q
```

Os novos passam. **Espere falhas na suíte.** Receitas com `investigador` aparecem em `tests/api/test_execucao.py`, `test_workflows_gerados.py`, `test_dinheiro_workflow_gerado.py` e `test_compor.py`; até aqui esse agente nunca via item, e qualquer asserção de "zero propostas", "custo zero" ou "o cliente não foi chamado" estava verde **por acidente**. Regra para cada falha:

1. Leia o teste e decida se ele afirmava o comportamento real ou o acidente.
2. Se afirmava o acidente: **reescreva a asserção para o comportamento real** (o agente agora vê N itens, chama o cliente N vezes, propõe), e explique no docstring por que mudou. Não apague o teste.
3. Se afirmava algo que ainda vale (o teto chega ao cliente; a chave é exigida) e só quebrou porque agora o cliente falso precisa de respostas: dê as respostas (`FakeLLMClient([_resposta()] * N)`) e mantenha a asserção.
4. Um teste que gaste de verdade não existe — se algum passou a construir cliente real, a tranca de `conftest.py` o derruba; isso é defeito seu, não do teste.

Liste no relatório cada teste tocado e em qual dos casos ele caiu.

- [ ] **Step 5: Suíte verde, lint, commit**

```bash
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m ruff check .
git add src/orchestrator/domains/registro.py tests/
git commit -m "fix(catalogo): o investigador consome banco e le os campos de BankEntry — estava cego desde o rename"
```

---

### Task 4: A borda — `/runs` recusa, por resolver, o que a fonte não alimenta

**Files:**
- Modify: `src/orchestrator/api/app.py` (nova `_conferir_kinds`, chamada em `_executar` logo depois de `_conferir_payload`)
- Modify: `tests/api/test_execucao.py` (três testes novos; dois existentes reescritos)

**Interfaces:**
- Consumes: `ResolverDescription.consome` (Task 1); `Stage.ordered()`; `WorkSet.items`.
- Produces: `_conferir_kinds(definicao: WorkflowDefinition, pool: WorkSet) -> None` — levanta `HTTPException(422)`.

- [ ] **Step 1: Os testes que falham**

Em `tests/api/test_execucao.py`, ao lado de `test_um_CSV_de_verdade_e_CONSUMIDO_e_produz_resolucao` (reuse `_csv_de_issues`, `_FONTE_ISSUES` e o padrão de `monkeypatch.setattr(api_app, "_RAIZ_ENTRADAS", ...)` que o arquivo já tem):

```python
def test_a_borda_recusa_bloco_que_a_fonte_NAO_alimenta(tmp_path, monkeypatch):
    """A frase do README que esta fatia apaga: "200 com lacuna de 100% sobre
    um pool que ninguém leu". Um CSV de issues na conciliação: L1 consome
    {banco, contabil}, a fonte entrega {issue}. Antes desta guarda o stage não
    enxergava nada, não rodava, e a resposta era 200 com tudo por resolver —
    um número com cara de medido sobre o que não foi medido."""
    import orchestrator.api.app as api_app

    _csv_de_issues(tmp_path, monkeypatch, linhas=2)

    r = cliente.post("/api/workflows/conciliacao/runs", json={"fonte": _FONTE_ISSUES})

    assert r.status_code == 422, r.text
    detalhe = r.json()["detail"]
    assert "'L1'" in detalhe and "banco" in detalhe and "issue" in detalhe


def test_a_borda_e_POR_RESOLVER_e_nao_pela_uniao_do_degrau(tmp_path, monkeypatch):
    """Pela união do degrau, um agente cego dentro de um degrau vivo passaria:
    L1 consome banco, a fonte traz banco, união satisfeita — e o agente que
    consome outra coisa roda sem ver item nenhum. Era o catálogo até a Task 3.
    Aqui uma receita `L1 + triador` sobre a fonte SINTÉTICA: L1 é alimentado,
    o triador (issue) não — e é o triador que a mensagem nomeia."""
    import orchestrator.api.app as api_app

    monkeypatch.setattr(api_app, "_RAIZ_RECEITAS", tmp_path / "receitas")
    criada = cliente.post("/api/receitas", json={
        "id": "mista", "nome": "m", "justificativa": "j",
        "resolvers": [{"nome": "L1"}, {"nome": "triador"}]})
    assert criada.status_code == 201, criada.text
    # `_executar` constrói o cliente ANTES da borda: sem este stub, a tranca de
    # rede do conftest levantaria `RedeProibida` no `AnthropicClient()` e o
    # teste morreria antes do 422. `_cliente_falso` também stuba `_tem_chave`.
    _cliente_falso(monkeypatch, [])

    r = cliente.post("/api/workflows/mista/runs", json={"teto_microcents": 1_000_000})

    assert r.status_code == 422, r.text
    detalhe = r.json()["detail"]
    assert "'triador'" in detalhe and "issue" in detalhe and "banco" in detalhe


def test_pool_VAZIO_e_recusado_e_nao_um_run_concluido_com_zero(tmp_path, monkeypatch):
    """Um CSV só com cabeçalho não é uma execução: é ausência de trabalho.
    Devolver 200 com zero itens seria outro número com cara de medido."""
    import orchestrator.api.app as api_app

    raiz = tmp_path / "entradas"
    raiz.mkdir()
    (raiz / "vazio.csv").write_text("id,titulo\n", encoding="utf-8")
    monkeypatch.setattr(api_app, "_RAIZ_ENTRADAS", raiz)

    r = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"fonte": {"tipo": "arquivo", "caminho": "vazio.csv",
                        "kind": "banco", "campo_id": "id"}},
    )

    assert r.status_code == 422, r.text
    assert "item nenhum" in r.json()["detail"]
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/api/test_execucao.py -q -k "borda or VAZIO"
```

Esperado: os três recebem 200 em vez de 422.

- [ ] **Step 3: A guarda**

Em `src/orchestrator/api/app.py`, logo depois de `_conferir_payload`:

```python
def _conferir_kinds(definicao: WorkflowDefinition, pool: WorkSet) -> None:
    """Cada resolver que declara o que consome é alimentado por esta fonte?

    A irmã de `_conferir_payload`, para a outra pergunta: aquela confere o
    TIPO do payload de um kind que o resolver exige; esta confere se o KIND
    que o resolver pega do pool existe na fonte. Sem ela, um CSV de issues na
    conciliação devolvia 200 com lacuna de 100% — o stage não enxergava nada,
    não rodava, e a resposta parecia medida. É a frase do README que esta
    guarda apaga: "não achei nada" indistinguível de "não procurei".

    **Por RESOLVER, não pela união do degrau.** A união deixaria passar um
    agente cego dentro de um degrau vivo: `L1` alimentado por `banco`
    satisfaz a união, e o agente que consome outro kind roda sem ver item
    nenhum. Foi o caso do `investigador` do catálogo até o conserto.

    **Aqui, e não no motor.** `runtime/engine.py` reserva os kinds que um
    degrau não consome e pula o degrau sem trabalho — semântica certa para um
    grafo de vários degraus. Recusar o RUN inteiro por kind errado é decisão
    de borda: só aqui existem, juntos, a fonte e o workflow.

    Pool vazio é recusa própria, não passe: sem item não há execução, e um
    run "concluído" com zero itens seria mais um número com cara de medido.
    """
    if not pool.items:
        raise HTTPException(status_code=422, detail="a fonte não entregou item nenhum")
    entregues = frozenset(item.kind for item in pool.items)
    for stage in definicao.stages:
        for resolver in stage.ordered():
            consome = resolver.describe().consome
            if consome and not (consome & entregues):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"o bloco {resolver.name!r} consome {sorted(consome)}, "
                        f"e a fonte entrega {sorted(entregues)}"
                    ),
                )
```

Em `_executar`, **logo depois** da chamada existente `_conferir_payload(definicao, pool)`:

```python
    _conferir_payload(definicao, pool)
    _conferir_kinds(definicao, pool)
```

(A ordem é deliberada: tipo errado de um kind que existe é o erro mais específico; kind ausente vem depois.)

- [ ] **Step 4: Rodar os novos; ver os dois que viram**

```bash
./.venv/Scripts/python.exe -m pytest tests/api/test_execucao.py -q
```

Os três novos passam. **Dois testes existentes passam a falhar, e é esperado** — os que esperavam `200` da conciliação sobre um arquivo de kind que nenhum resolver consome:

- `test_a_fonte_de_ARQUIVO_nao_inventa_taxa_de_acerto` (kind `lancamento`)
- `test_a_fila_de_uma_fonte_de_arquivo_e_ESCOPADA_por_conteudo` (kind `k`)

Os outros usos de `kind: "k"` no arquivo (raiz violada, arquivo inexistente, malformado, campo desconhecido) já eram `422` **antes** da borda — a recusa nasce em `_fonte_de`/`_ler`/schema, que rodam primeiro — e não mudam. Confirme rodando; se um terceiro teste virar, ele entra na mesma regra.

- [ ] **Step 5: Reescrever os dois — não apagar, e não perder o que provavam**

Cada um dos dois provava uma PROPRIEDADE num caminho `200` que agora não existe para kinds não consumidos. A propriedade não pode morrer com o 200:

- `..._nao_inventa_taxa_de_acerto` provava **`contra_gabarito: null`** numa execução real de arquivo — a evidência central de "AUSENTE, não zero". Ela passa a ser afirmada sobre a cascata CONSUMIDORA que o arquivo já tem (a `fabrica` local usada por `test_um_CSV_de_verdade_e_CONSUMIDO_e_produz_resolucao`): se aquele teste ainda não afirma `corpo["contra_gabarito"] is None`, acrescente a asserção lá. Só então o teste antigo vira `422`.
- `..._ESCOPADA_por_conteudo` provava que **a chave da fila sai do conteúdo do arquivo** (dois conteúdos → duas filas). Mova a observação da chave para uma execução sobre a mesma cascata consumidora — a propriedade é da fila, não do kind — e mantenha as duas asserções (uma fila por conteúdo, prefixo `file-`).

Depois, para cada um dos dois testes antigos: mantenha a fixture do arquivo, troque a asserção de `200` por `422`, afirme que o detalhe nomeia o bloco (`'L1'`) e o kind, e reescreva o docstring:

```
    Este teste provava que o arquivo é lido, hasheado e vira pool — usando um
    kind que NENHUM resolver consome, e recebendo 200 com lacuna de 100%. Era
    o "200 sobre um pool que ninguém leu" do README. Com a borda por resolver
    isso é 422, e a prova de que o arquivo É lido mora em
    `test_um_CSV_de_verdade_e_CONSUMIDO_e_produz_resolucao`, que consome o kind
    do arquivo e lê um campo dele.
```

- [ ] **Step 6: Suíte, lint, commit**

```bash
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m ruff check .
git add src/orchestrator/api/app.py tests/api/test_execucao.py
git commit -m "feat(api): a borda recusa, por resolver, o que a fonte nao alimenta — e pool vazio nao e run"
```

---

### Task 5: A composição entra no `registry()` — e o fim-a-fim

**Files:**
- Modify: `src/orchestrator/workflows.py` (`_de_composicao`; `registry`; `descrever`)
- Modify: `src/orchestrator/api/app.py` (todo `registry(_RAIZ_RECEITAS)` e o `descrever(_RAIZ_RECEITAS)`; 409 em `criar_composicao`; `gerado_em` em `listar_workflows`)
- Test: `tests/test_workflows.py`, `tests/api/test_execucao.py`

**Interfaces:**
- Consumes: `construir_composicao(c, fila=, cliente=)`, `authoring.composicao.listar(raiz)`, `WorkflowContext`.
- Produces: `registry(raiz: Path | None = None, raiz_composicoes: Path | None = None)`; `descrever(raiz=None, raiz_composicoes=None)`.

- [ ] **Step 1: Os testes de registry que falham**

Em `tests/test_workflows.py` (mesmo estilo dos testes existentes de `registry(tmp_path)`):

```python
def _composicao_em(raiz, cid="comp-1"):
    from datetime import UTC, datetime

    from orchestrator.authoring.composicao import BlocoRegra, Composicao, gravar

    raiz.mkdir(parents=True, exist_ok=True)
    c = Composicao(
        id=cid, nome="composta", gerado_em=datetime.now(UTC),
        blocos=(BlocoRegra(nome="L1", parametros={}),),
    )
    gravar(c, raiz)
    return c


def test_uma_COMPOSICAO_salva_entra_no_registry(tmp_path):
    _composicao_em(tmp_path / "composicoes")
    fabricas = registry(tmp_path / "receitas", tmp_path / "composicoes")
    definicao = construir_definicao(fabricas["comp-1"], WorkflowContext.vazio())
    assert definicao.id == "comp-1"
    assert [r.name for r in definicao.stages[0].cascade] == ["L1"]


def test_sem_raiz_de_composicoes_o_registry_e_o_de_ANTES(tmp_path):
    """Todo chamador existente passa só a raiz de receitas — e continua igual."""
    assert set(registry(tmp_path / "receitas")) == {ID_EMBUTIDO}


def test_a_ordem_e_a_tranca_receita_VENCE_composicao_com_o_mesmo_id(tmp_path, capsys):
    """Dois arquivos com o mesmo id em disco — criados antes desta fatia, ou à
    mão. A receita vence, a composição é PULADA com aviso: a configuração
    inválida não some em silêncio nem derruba a listagem inteira por causa de
    um id. Mesmo padrão com que `descrever()` isola uma receita que não
    constrói."""
    gravar_receita(_receita("mesmo-id"), raiz=tmp_path / "receitas")
    _composicao_em(tmp_path / "composicoes", cid="mesmo-id")

    fabricas = registry(tmp_path / "receitas", tmp_path / "composicoes")
    definicao = construir_definicao(fabricas["mesmo-id"], WorkflowContext.vazio())

    assert definicao.name != "composta"  # é a receita, não a composição
    assert "mesmo-id" in capsys.readouterr().err


def test_uma_composicao_que_NAO_constroi_some_da_listagem_com_aviso_e_nao_derruba_as_outras(
    tmp_path, capsys
):
    """O mesmo isolamento que `descrever()` já dá a uma receita ruim, agora
    para composições: um bloco que saiu do catálogo não pode matar o seletor
    da tela para TODOS os workflows."""
    from datetime import UTC, datetime

    from orchestrator.authoring.composicao import BlocoRegra, Composicao, gravar

    raiz = tmp_path / "composicoes"
    raiz.mkdir()
    gravar(
        Composicao(
            id="quebrada", nome="q", gerado_em=datetime.now(UTC),
            blocos=(BlocoRegra(nome="bloco-que-nao-existe", parametros={}),),
        ),
        raiz,
    )

    ids = [wid for wid, _ in descrever(tmp_path / "receitas", raiz)]

    assert ID_EMBUTIDO in ids
    assert "quebrada" not in ids
    assert "quebrada" in capsys.readouterr().err
```

`gravar_receita` e `_receita(rid)` já existem em `tests/test_workflows.py` (linhas ~23 e ~35) — é o mesmo caminho que alimenta `registry(tmp_path)["acme"]`. `descrever` e `ID_EMBUTIDO` vêm de `orchestrator.workflows`, como os demais imports do arquivo. Se `Composicao.__post_init__` recusar um bloco desconhecido já na construção do objeto, grave o JSON à mão com `json.dump` no formato de `para_json` — o que o teste precisa é um ARQUIVO que parseia e não constrói.

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_workflows.py -q
```

Esperado: `TypeError: registry() takes from 0 to 1 positional arguments but 2 were given`.

- [ ] **Step 3: A fábrica e o registry**

Em `src/orchestrator/workflows.py`, logo depois de `_de_receita`:

```python
def _de_composicao(composicao: Composicao) -> WorkflowFactory:
    """Fábrica para uma cascata composta no canvas. O espelho de `_de_receita`.

    `ctx.cliente` repassado VERBATIM, inclusive `None`: quem decide o que
    `None` significa é `construir_composicao`, que cai em `ClienteDeValidacao`
    — a tranca. O docstring de `construir_composicao` previu esta linha: "para
    que o dia em que uma composição ganhar caminho de execução seja um
    `fila=ctx.fila` a mais, e não uma segunda via de configuração".
    """

    def fabrica(ctx: WorkflowContext) -> WorkflowDefinition:
        return construir_composicao(composicao, fila=ctx.fila, cliente=ctx.cliente)

    return fabrica


def registry(
    raiz: Path | None = None, raiz_composicoes: Path | None = None
) -> dict[str, WorkflowFactory]:
    """Os workflows disponíveis: o embutido, os gerados em disco, os compostos.

    Saiu de `api/app.py`: quais workflows existem não é assunto da camada HTTP.
    A CLI e o benchmark precisam da mesma resposta, e duas listas paralelas
    seriam o join frágil que P3.2 já custou uma correção.

    A ORDEM é a tranca: embutida → receitas → composições. `conciliacao` é id
    reservado; disco nunca sobrescreve a embutida; uma composição nunca
    sobrescreve uma receita. Composições ficam em raiz própria porque são
    outro formato com outra serialização — um diretório só obrigaria o leitor
    a farejar o formato pelo conteúdo.
    """
    fabricas: dict[str, WorkflowFactory] = {
        ID_EMBUTIDO: lambda ctx: default_definition(ctx.fila)
    }
    for receita in listar_receitas(raiz):
        if receita.id in fabricas:
            continue
        fabricas[receita.id] = _de_receita(receita)
    for composicao in listar_composicoes(raiz_composicoes):
        if composicao.id in fabricas:
            # Não some em silêncio, não derruba a listagem: o mesmo isolamento
            # que `descrever()` dá a uma receita que não constrói.
            print(
                f"aviso: composição {composicao.id!r} ignorada — já existe um "
                f"workflow com esse id (embutido ou receita)",
                file=sys.stderr,
            )
            continue
        fabricas[composicao.id] = _de_composicao(composicao)
    return fabricas
```

Imports: `from orchestrator.authoring.composicao import Composicao, construir_composicao` e `from orchestrator.authoring.composicao import listar as listar_composicoes`. `sys` já é importado. Se o Python levantar `ImportError` circular ao importar `orchestrator.workflows`, mova esses dois imports para **dentro** de `registry()` e `_de_composicao()`, com um comentário de uma linha dizendo por quê — como `default_definition` faz com `review`.

`descrever` ganha o mesmo parâmetro e o repassa:

```python
def descrever(
    raiz: Path | None = None, raiz_composicoes: Path | None = None
) -> list[tuple[str, WorkflowDefinition]]:
    ...
    for workflow_id, fabrica in registry(raiz, raiz_composicoes).items():
```

- [ ] **Step 4: A API passa as duas raízes, recusa colisão, lista `gerado_em`**

Em `src/orchestrator/api/app.py`, **todas** as chamadas `registry(_RAIZ_RECEITAS)` (linhas ~350, 455, 469, 655, 1018, 1053) viram `registry(_RAIZ_RECEITAS, _RAIZ_COMPOSICOES)`, e `descrever(_RAIZ_RECEITAS)` em `listar_workflows` vira `descrever(_RAIZ_RECEITAS, _RAIZ_COMPOSICOES)`. Confira com `grep -n "registry(\|descrever(" src/orchestrator/api/app.py` que não sobrou nenhuma.

Em `criar_composicao`, entre `definicao = construir_composicao(composicao)` (dentro do `try`) e o `try: gravar(...)`:

```python
    if pedido.id in registry(_RAIZ_RECEITAS, _RAIZ_COMPOSICOES):
        # Simétrico a `/api/receitas`: o id é um só espaço para embutido,
        # receitas e composições. Recusar aqui é o que faz o pulo-com-aviso
        # de `registry()` ser um caso de disco editado à mão, não de tela.
        raise HTTPException(
            status_code=409,
            detail=f"já existe um workflow com id {pedido.id!r}; escolha outro",
        )
```

Em `listar_workflows`, o `gerado_em`:

```python
    por_id = {r.id: r for r in listar_receitas(_RAIZ_RECEITAS)}
    por_id.update({c.id: c for c in listar_composicoes(_RAIZ_COMPOSICOES)})
    ...
        origem = por_id.get(workflow_id)
        ...
                gerado_em=origem.gerado_em.isoformat() if origem else None,
```

com `from orchestrator.authoring.composicao import listar as listar_composicoes` nos imports de `app.py` (se `listar` já é importado com outro alias, use o existente).

- [ ] **Step 5: O fim-a-fim que é o objetivo da fatia**

Em `tests/api/test_execucao.py`, ao lado de `test_um_CSV_de_issues_roda_no_TRIADOR_composto_pela_WEB` — o mesmo teste, pela **composição**:

```python
def test_um_CSV_de_issues_roda_numa_COMPOSICAO_do_CANVAS(tmp_path, monkeypatch):
    """A frase do dono, de ponta a ponta: compor um agente na tela e rodar de
    verdade. A fatia anterior provou isto sobre uma RECEITA; uma composição
    vivia em data/composicoes/ e o registry não a conhecia — o botão do canvas
    recebia 404. Agora ela entra no registry e este é o mesmo teste, pela
    porta que a tela usa."""
    import orchestrator.api.app as api_app

    monkeypatch.setattr(api_app, "_RAIZ_RECEITAS", tmp_path / "receitas")
    monkeypatch.setattr(api_app, "_RAIZ_COMPOSICOES", tmp_path / "composicoes")
    _csv_de_issues(tmp_path, monkeypatch, linhas=3)
    fake = _cliente_falso(monkeypatch, [_resposta()] * 3)

    criada = cliente.post("/api/composicoes", json={
        "id": "triagem-canvas", "nome": "Triagem", "justificativa": "",
        "blocos": [{"tipo": "agente", "declaracao": {
            "name": "meu-triador", "system": "classifique a issue",
            "kind": "issue", "prompt": "{titulo}\n\n{corpo}",
            "tipos": ["BUG", "FEATURE"], "abstem_com": "NAO_SEI",
            "ferramentas": [], "max_turns": 3, "budget_microcents": 4_000_000}}]})
    assert criada.status_code == 201, criada.text

    listados = {w["id"]: w for w in cliente.get("/api/workflows").json()}
    assert "triagem-canvas" in listados
    assert listados["triagem-canvas"]["gerado_em"] is not None

    r = cliente.post(
        "/api/workflows/triagem-canvas/runs",
        json={"fonte": _FONTE_ISSUES, "teto_microcents": 10_000_000},
    )

    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["itens"] == 3
    assert len(fake.chamadas) == 3
    assert corpo["propostas_por_tipo"] == {"BUG": 3}
    assert corpo["falhas"] == 0
    assert corpo["teto_atingido"] is False
    assert corpo["contra_gabarito"] is None


def test_compor_com_id_de_workflow_EXISTENTE_e_409(tmp_path, monkeypatch):
    import orchestrator.api.app as api_app

    monkeypatch.setattr(api_app, "_RAIZ_COMPOSICOES", tmp_path / "composicoes")
    r = cliente.post("/api/composicoes", json={
        "id": "conciliacao", "nome": "x", "justificativa": "",
        "blocos": [{"tipo": "regra", "nome": "L1", "parametros": {}}]})
    assert r.status_code == 409, r.text
    assert "conciliacao" in r.json()["detail"]
```

Confira contra `_resposta()`/`_cliente_falso` que a resposta falsa classifica como `BUG` (é o que o teste da receita usa); se o `_agente()` de `tests/api/test_composicoes.py` tiver campos obrigatórios a mais, copie-os.

- [ ] **Step 6: Suíte, lint, commit**

```bash
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m ruff check .
git add src/orchestrator/workflows.py src/orchestrator/api/app.py tests/test_workflows.py tests/api/test_execucao.py
git commit -m "feat(workflows,api): a composicao do canvas entra no registry — lista, roda por /runs, e colisao de id e 409"
```

---

### Task 6: O canvas entrega para a execução

**Files:**
- Modify: `web-app/src/App.tsx` (estado `run`/`rodando`, `executar`, props do `Painel`)
- Modify: `web-app/src/Painel.tsx` (props; a cópia da linha ~185; o botão "▶ Run" e seu `title`/comentário ~273–283; o painel `{p.run && ...}` ~324)
- Modify: `web/assets/*`, `web/index.html` (bundle rebuildado)
- Test: `tests/api/test_compor.py`

**Interfaces:**
- Consumes: `/api/composicoes` (201 já grava); a vista de execução em `/?workflow=<id>` (sem `vista`, é a default).
- Produces: nenhuma API nova.

- [ ] **Step 1: As asserções de bundle que falham**

Em `tests/api/test_compor.py`, ao lado de `test_a_tela_de_execucao_pede_o_teto_ANTES_do_botao_de_rodar` (usa o `_bundle()` do arquivo):

```python
def test_o_canvas_ENTREGA_para_a_execucao_em_vez_de_fingir_que_roda():
    """O botão do canvas chamava /runs com o id da composição e recebia 404.
    Agora, depois de salvar, ele leva à tela de execução — onde fonte, teto e
    resultado moram. Um caminho só para o que gasta dinheiro."""
    js = _bundle()
    assert "abrir na execução" in js
    assert "?workflow=" in js


def test_a_copia_do_canvas_nao_diz_mais_que_a_API_nao_executa():
    """Virou mentira na Task 4 da fatia anterior: a API executa, com teto e
    chave. Uma tela que diz o contrário ensina a pessoa a rodar pela CLI o
    que ela podia rodar ali."""
    js = _bundle()
    assert "a API não a executa" not in js
    assert "pede teto e chave" in js
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/api/test_compor.py -q -k "ENTREGA or copia_do_canvas"
```

Esperado: os dois falham contra o bundle atual.

- [ ] **Step 3: `App.tsx` — o estado de execução sai**

Remova `run`, `setRun`, `rodando`, `setRodando` (linhas ~55–56), as chamadas `setRun(null)` (~130, ~232), a função `executar` inteira (~255–275), e no `<Painel ...>` as props `run={run}`, `rodando={rodando}` e `onExecutar={executar}`. Remova `type Run` do import de `./api` se ficou sem uso (`tsc` avisa). **Mantenha** `api.rodar` em `api.ts` — a vista de execução o usa.

- [ ] **Step 4: `Painel.tsx` — o hand-off, a cópia, e o painel que sai**

Na `interface Props`, remova `run`, `rodando` e `onExecutar`.

A cópia (~185):

```tsx
          {temAgente
            ? "Tem classe AGENTE: gasta dinheiro ao rodar — a execução pede teto e chave no servidor."
            : "Nenhum bloco paga por token. Roda de graça."}
```

O botão "▶ Run" (~268–283) e o comentário acima dele viram:

```tsx
          {p.construido && (
            // Hand-off, não execução: fonte, teto e resultado moram na vista
            // de execução, e é lá que o servidor exige o teto ANTES de gastar.
            // O mesmo idioma do link "fila de revisão →" e a mesma URL que o
            // grill imprime na CLI. Só existe DEPOIS de salvo: uma composição
            // validada e não gravada não está no registry.
            <a
              href={`/?workflow=${encodeURIComponent(p.construido.id)}`}
              className="rounded border border-regra bg-regra px-3 py-1.5 text-[12.5px] text-white transition hover:opacity-90"
            >
              abrir na execução →
            </a>
          )}
```

O bloco `{p.run && ( <Secao titulo="Execução" ...> ... )}` (~324 até o fechamento) sai inteiro. Se `Secao`, `CORES` ou algum import ficar sem uso, o `tsc` diz — remova.

Confira que não sobrou nenhuma cor literal nova: só tokens (`bg-regra`, `border-regra`, `dark:*`).

- [ ] **Step 5: Typecheck, build, bundle, testes**

```bash
cd web-app && npx tsc --noEmit && npm run build && cd ..
git status --porcelain web/
./.venv/Scripts/python.exe -m pytest tests/api/test_compor.py -q
```

Esperado: `tsc` limpo; `web/assets/index-*.js` novo e `web/index.html` com o hash novo aparecem no status; os dois testes passam.

- [ ] **Step 6: O gate do navegador — SEM chave**

Antes de qualquer coisa: garanta que `ANTHROPIC_API_KEY` **não** está no ambiente em que o servidor sobe; confirme com `GET /api/ambiente` → `tem_chave: false`. Com chave, um clique num workflow pago gasta dinheiro do dono da máquina.

Suba o servidor (`.claude/launch.json` tem `canvas` na porta 8111; se a porta já estiver ocupada por um uvicorn deste app, reutilize-o). Na vista `?vista=compor`: monte um `triador` (bloco de agente com `kind=issue`), dê um id, "Compor e validar" → aparece **"abrir na execução →"**; clique → a vista de execução abre com a composição selecionada no seletor de workflow; escolha fonte `arquivo`, `caminho=gate.csv` (crie `data/entradas/gate.csv` com `id,titulo,corpo` e 3 linhas — é gitignored), `kind=issue`, `campo id=id`; sem chave, o botão não roda e a tela diz o motivo. Light e dark. Registre no relatório o que viu em cada passo — `read_page` da árvore inteira vale como prova quando o screenshot não desenha.

- [ ] **Step 7: Suíte, lint, commit (com o bundle)**

```bash
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m ruff check .
git add web-app/src web/ tests/api/test_compor.py
git commit -m "feat(web): o canvas entrega para a execucao — abrir na execucao, e a copia que dizia que a API nao executa"
```

---

### Task 7: Os textos que diziam "aberta" deixam de dizer

**Files:**
- Modify: `README.md` (os dois blocos: "Não garante mais que o `kind`…" ~129–145 e "Não sabe EXECUTAR um workflow que não seja de conciliação…" ~146–160)
- Modify: `src/orchestrator/authoring/composicao.py` (o cabeçalho do módulo, do parágrafo "**A terceira garantia era…**" até "…é quem garante o `kind`."; e o comentário `# Sem checagem de \`kind\`…` em `construir_composicao`)
- Modify: `docs/superpowers/DECISOES.md` (nova entrada)

**Interfaces:** nenhuma. Documentação que virou mentira com as Tasks 2–5.

- [ ] **Step 1: README — o bloco do `kind`**

Substitua o item inteiro "**Não garante mais que o `kind` de um agente bate…**" por:

```markdown
- **Garante que cada bloco de uma cascata é alimentado pela fonte — na BORDA,
  por resolver.** Todo resolver declara o que consome
  (`ResolverDescription.consome`, `AgentSpec.consome`); os três construtores
  derivam `Stage.consome` disso (`consome_de`); e `POST /runs` recusa com 422,
  nomeando o bloco, qualquer resolver cujo `consome` não cruza os kinds do pool
  carregado. Por resolver, e não pela união do degrau: a união deixaria passar
  um agente cego dentro de um degrau vivo — que era o `investigador` do
  catálogo, declarado sobre `lancamento`, kind que nenhuma fonte produz, até o
  conserto. O que ainda NÃO existe: `produz` derivado (X8) — desnecessário
  enquanto agentes declarados só emitem propostas — e composição com vários
  stages. Uma composição continua sendo aceita ao salvar com qualquer `kind`:
  ela não conhece a fonte; a recusa vem na execução, antes de gastar.
```

- [ ] **Step 2: README — o bloco do `/runs`**

Substitua o item inteiro "**Não sabe EXECUTAR um workflow que não seja de conciliação — e ainda assim devolve 200.**" por:

```markdown
- **Executa qualquer workflow do `registry()` — embutido, receita ou composição
  do canvas — sobre a fonte que o pedido nomeia.** `POST /api/workflows/{id}/runs`
  recebe `fonte` (`sintetica` ou `arquivo` CSV/JSON sob `data/entradas/`) e um
  `teto_microcents`, obrigatório quando a cascata tem agente. Uma fonte sem
  gabarito devolve `contra_gabarito: null`, nunca uma taxa inventada; uma fonte
  cujos kinds nenhum bloco consome é recusada com 422 antes de rodar; um pool
  vazio também. O que ainda NÃO existe: fonte HTTP (§8 do spec da plataforma),
  upload de arquivo, e teto agregado/auth/rate limit em `/runs` — o teto é por
  requisição, por decisão do dono.
```

- [ ] **Step 3: O cabeçalho de `authoring/composicao.py`**

Substitua do parágrafo "**A terceira garantia era "um domínio só", e hoje ela NÃO TEM DONO aqui.**" até "…quem escreve um agente na tela é quem garante o `kind`." por:

```
**A terceira garantia — cada bloco é alimentado pela fonte — mora na BORDA,
não aqui.** Ela dizia: blocos cujos `WorkItem.kind` não conversam produzem
uma cascata vazia de sentido. A guarda antiga comparava o `kind` do agente
com os `kinds` de um domínio declarado, e saiu porque recusava cascata válida
depois que a tela perdeu o seletor.

O lugar certo é o grafo que VAI RODAR contra a fonte que VAI RODAR — e isso
só existe junto na borda do `/runs`. Esta função faz a metade dela: deriva
`Stage.consome` dos blocos (`consome_de`), então o degrau reserva o que não
consome e a borda tem o que ler. A outra metade, `api/app.py::_conferir_kinds`,
recusa com 422 — por resolver, nomeando o bloco — qualquer `consome` que não
cruze os kinds do pool carregado.

Uma composição continua sendo ACEITA aqui com qualquer `kind`: ela não conhece
a fonte, e "valida construindo" é a garantia desta função. Um `kind` digitado
errado é pego na execução, antes de gastar — não mais "aceito, e em execução
nunca pega item nenhum".

O que ainda não existe: `produz` derivado (X8), desnecessário enquanto um
`AgenteDeclarado` só emite propostas; e mais de um stage por composição.
```

E o comentário em `construir_composicao` que começa com `# Sem checagem de \`kind\`:` vira:

```python
            # Sem checagem de `kind` AQUI, de propósito: a composição não
            # conhece a fonte. `Stage.consome` sai de `consome_de` no `return`
            # abaixo, e é a borda do `/runs` (`_conferir_kinds`) que recusa um
            # kind que a fonte não entrega — por resolver, antes de gastar.
```

- [ ] **Step 4: `DECISOES.md`**

Acrescente ao fim, seguindo a numeração (a última entrada hoje é `### P8.5`; a próxima série livre é `P9`):

```markdown
### P9.1. A guarda de `kind` mora na BORDA, por resolver — não no kernel, não por degrau

**Decisão.** Todo resolver DECLARA o que consome (`ResolverDescription.consome`,
`AgentSpec.consome`); cada construtor deriva `Stage.consome` com `consome_de`;
e `POST /runs` recusa com 422 qualquer resolver cujo `consome` não cruze os
kinds do pool carregado — nomeando o bloco. Pool vazio também é 422.

**Por que declarado e não derivado de `payloads`.** `payloads` responde "que
TIPO exijo deste kind"; `consome` responde "que KINDS pego do pool". O
`investigador` em Python lê objetos tipados; o `triador` lê dicionário e não
exige tipo — ambos consomem um kind só. Amarrar as duas obrigaria um agente a
declarar tipo para dizer o que consome, e a borda de `payloads` recusaria
fonte válida.

**Por que na borda e não no motor.** `runtime/engine.py` reserva os kinds que
um degrau não consome e pula o degrau sem trabalho — semântica certa para um
grafo de vários degraus, e que devolveria `concluido` com lacuna de 100% para
um run inteiro sobre kind errado: "não achei nada" indistinguível de "não
procurei". Só a borda tem, juntos, a fonte e o workflow.

**Por que por resolver e não pela união do degrau.** A união deixaria passar
um agente cego dentro de um degrau vivo: `L1` alimentado por `banco`
satisfaz a união, e o agente que consome outro kind roda sem ver item. Era o
`investigador` do catálogo — `kind="lancamento"`, que nenhuma fonte produz, e
um prompt sobre `{descricao}`, campo que `BankEntry` não tem — cego desde o
rename do domínio, dentro de `pago.json`. A guarda o teria pego; ele foi
consertado antes de a guarda existir, para que ela nascesse sem quebrar nada
por acidente.

**Por que `consome_de` está no kernel e não em `workflows.py`.** `workflows.py`
importa `authoring/composicao.py` (a fábrica `_de_composicao`), e
`construir_composicao` chama `consome_de` — em `workflows.py` seria um ciclo.
E é uma função chamada por cada construtor, não `Stage.__post_init__`: derivar
no kernel trocaria em silêncio o significado do default vazio para toda
definição escrita em Python.

**O que fica fora.** `produz` derivado (X8) — desnecessário enquanto agentes
declarados só emitem propostas; vários stages por composição; a lacuna do
produtor, contida pelo `xfail(strict)` e pelo estopim da fatia anterior.
```

- [ ] **Step 4b: Três textos a mais que a exploração achou — X7 fechou, X8 não**

Os três dizem "X7/X8" como se fosse um item só. Depois desta fatia, X7 (a metade de `consome`) está fechado e X8 (a metade de `produz`) continua aberto; cada texto passa a dizer as duas coisas.

`README.md`, o parágrafo da `Tarefa` (por volta da linha 97) que termina em *"é o mesmo X7/X8 da lacuna de `kind`, no…"*: troque a menção por *"é a metade X8 da lacuna de `kind` — a metade X7, `consome` derivado e conferido na borda, fechou; `produz` declarado por agente ainda não existe"*, mantendo o resto do parágrafo.

`src/orchestrator/domains/registro.py:204-210`, o comentário que diz *"Ensinar `AgenteDeclarado` a declarar `produz` é o X7/X8 que o plano de execução-como-grafo reserva para depois"*: vira

```python
# Catalogá-lo hoje exigiria mentir sobre o que ele faz. Ensinar
# `AgenteDeclarado` a declarar `produz` é a metade X8 da lacuna de `kind` —
# ainda reservada. A metade X7 (`consome` declarado, derivado por
# `consome_de` e conferido na borda do `/runs`) fechou; ver P9.1 em
# `docs/superpowers/DECISOES.md`.
```

`src/orchestrator/authoring/composicao.py`, o parágrafo **"Estado desta fatia, dito em voz alta."** (por volta da linha 54): foi um interino, escrito quando `consome` já era populado e a borda ainda não existia, e diz de si mesmo *"este cabeçalho é reescrito por inteiro quando ela existir"*. Ela existe. **Remova o parágrafo** — o texto do Step 3 é a reescrita que ele prometia.

- [ ] **Step 5: Confira que nada mais chama a lacuna de aberta**

```bash
grep -rn "X7\|X8\|está INERTE\|esta INERTE\|não pega item nenhum\|nao pega item nenhum" README.md src/orchestrator docs/superpowers/DECISOES.md
```

Toda ocorrência restante tem que ser uma referência HISTÓRICA (P9.1, o cabeçalho reescrito, a spec desta fatia) — não uma afirmação de que a lacuna existe. Ajuste o que sobrar.

- [ ] **Step 6: Suíte, lint, commit**

```bash
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m ruff check .
git add README.md src/orchestrator/authoring/composicao.py docs/superpowers/DECISOES.md
git commit -m "docs: a lacuna de kind fechada deixa de ser escrita como aberta — README, composicao.py, P9.1"
```

---

## Fora deste plano

- **X8 — `AgenteDeclarado` declarar o que `produz`.** Desnecessário enquanto agentes declarados só emitem propostas.
- **Vários stages numa composição.**
- **A lacuna do produtor** (`_conferir_payload` só inspeciona o pool inicial) — contida pelo `xfail(strict)` + estopim.
- **Teto agregado, auth, rate limit em `/runs`.** Decisão de produto adiada pelo dono.
- **Vista da fila para fonte de arquivo** (`file-<sha16>` sem rota).
- **`BuscadorDeFornecedor` de `procurement/workflow.py`** não ligado ao `CATALOGO` — código morto que sombreia um nome; limpeza futura.
