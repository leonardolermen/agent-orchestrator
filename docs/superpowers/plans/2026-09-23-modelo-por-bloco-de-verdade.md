# O Modelo por Bloco, de Verdade — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Fazer o `model` declarado num bloco decidir de verdade qual modelo é chamado, e fazer a tabela de custo do run precificar cada linha com o modelo daquela linha.

**Architecture:** A borda passa a entregar uma FÁBRICA de clientes (`cliente_para(model)`) em vez de um cliente, e todos os clientes que ela cria dividem um `Orcamento` — o acumulador de gasto em µ¢ e o contador de recusas. O resolver declara seu modelo em `ResolverDescription.model`, o mesmo canal que `consome`/`produz`/`payloads` já usam, e a borda converte cada linha do custo com ele.

**Tech Stack:** Python 3.11+, dataclasses, pytest. Nada de rede: modelo só via `FakeLLMClient`.

**Spec:** `docs/superpowers/specs/2026-09-22-modelo-por-bloco-de-verdade-design.md`

## Global Constraints

- **Português** no código e na prosa. Commits: `tipo(escopo): frase em minúscula`, assunto sem acento, corpo com o porquê e a evidência.
- **Comentário registra POR QUÊ, com evidência** — alternativa rejeitada, defeito evitado ou número medido.
- **TDD**: nenhum código de produção sem um teste que falhou antes.
- Suíte: `.venv/Scripts/python.exe -m pytest -q`. Lint: `.venv/Scripts/python.exe -m ruff check src tests`. **`ruff format` não roda.**
- Teste que importa `fastapi` precisa de `pytest.importorskip("fastapi")` no topo.
- Nenhum teste fala com a rede (`tests/conftest.py::_rede_proibida` é autouse).
- **`complete` NÃO muda de assinatura.** São 18 implementações no repositório, 12 em testes; a spec rejeita A2 por isso.
- **O teto continua por REQUISIÇÃO**, conferido ANTES de cada chamada, e a última pode ultrapassá-lo por um turno — o docstring de `teto.py` continua valendo palavra por palavra.
- Ao final de cada tarefa: suíte verde + `ruff check` limpo.
- Critério do produto: `.venv/Scripts/orchestrator.exe --seed 1 --n 500` diz `85.3%`, zero falso positivo, zero falso negativo.

---

### Task 1: `Orcamento` — o teto que vários clientes dividem

**Files:**
- Modify: `src/orchestrator/agent/teto.py`
- Test: `tests/agent/test_teto.py`

**Interfaces:**
- Consumes: `kernel/cost.py::Cost`.
- Produces: `Orcamento(teto_microcents: int | None = None)` com `gasto_microcents() -> int`, `registrar(cost: Cost, model: str) -> None`, `barrar() -> None`, `pode_gastar() -> bool`, `recusas: int`. `ClienteComTeto(interno, *, teto_microcents=None, orcamento: Orcamento | None = None)`.

- [x] **Step 1: Write the failing tests**

Acrescentar a `tests/agent/test_teto.py`:

```python
def test_dois_clientes_de_MODELOS_diferentes_dividem_um_teto():
    """O teto é da REQUISIÇÃO, não do modelo. Com um acumulador por cliente,
    uma cascata com dois modelos teria dois tetos que não somam — e o pedido
    que autorizou gastar X gastaria 2X sem ninguém pedir."""
    from orchestrator.agent.teto import ClienteComTeto, Orcamento

    orcamento = Orcamento(teto_microcents=1_000_000)
    caro = ClienteComTeto(
        FakeLLMClient([_resposta()], model="claude-opus-5"), orcamento=orcamento
    )
    barato = ClienteComTeto(
        FakeLLMClient([_resposta()], model="claude-haiku-4-5"), orcamento=orcamento
    )

    caro.complete(system="s", messages=[], tools=[])
    barato.complete(system="s", messages=[], tools=[])

    # Um acumulador só, e cada chamada entrou no PREÇO do seu modelo.
    assert orcamento.gasto_microcents() == caro.gasto_microcents()
    assert orcamento.gasto_microcents() == barato.gasto_microcents()


def test_o_gasto_de_cada_chamada_entra_no_PRECO_DO_SEU_MODELO():
    """100 tokens de entrada em opus custam 5x o que custam em haiku
    (500 vs 100 µ¢ por token, pela tabela). Somar tokens e converter uma vez no
    fim daria o mesmo número para consumos que custam diferente."""
    from orchestrator.agent.teto import ClienteComTeto, Orcamento
    from orchestrator.kernel.cost import Cost

    orcamento = Orcamento()
    ClienteComTeto(
        FakeLLMClient([_resposta(Cost(input_tokens=100))], model="claude-opus-5"),
        orcamento=orcamento,
    ).complete(system="s", messages=[], tools=[])
    so_opus = orcamento.gasto_microcents()

    outro = Orcamento()
    ClienteComTeto(
        FakeLLMClient([_resposta(Cost(input_tokens=100))], model="claude-haiku-4-5"),
        orcamento=outro,
    ).complete(system="s", messages=[], tools=[])

    assert so_opus == 100 * 500
    assert outro.gasto_microcents() == 100 * 100


def test_a_RECUSA_e_contada_no_orcamento_compartilhado():
    """`api/app.py` lê `cliente.recusas` para dizer `teto_atingido`. Com dois
    clientes, a recusa pode acontecer em qualquer um deles, e a resposta é
    sobre a REQUISIÇÃO."""
    from orchestrator.agent.teto import ClienteComTeto, Orcamento, TetoDaExecucaoEstourado

    orcamento = Orcamento(teto_microcents=1)
    a = ClienteComTeto(FakeLLMClient([_resposta()], model="claude-opus-5"), orcamento=orcamento)
    b = ClienteComTeto(FakeLLMClient([_resposta()], model="claude-haiku-4-5"), orcamento=orcamento)

    a.complete(system="s", messages=[], tools=[])
    with pytest.raises(TetoDaExecucaoEstourado):
        b.complete(system="s", messages=[], tools=[])

    assert orcamento.recusas == 1
    assert a.recusas == 1 and b.recusas == 1


def test_sem_orcamento_o_cliente_cria_o_seu_e_nada_muda():
    """Todo chamador de hoje escreve `ClienteComTeto(fake, teto_microcents=X)`.
    Essa forma continua valendo, e continua significando um teto só para aquele
    cliente."""
    from orchestrator.agent.teto import ClienteComTeto

    c = ClienteComTeto(FakeLLMClient([_resposta()], model="claude-opus-5"), teto_microcents=50)

    assert c.gasto_microcents() == 0
    assert c.recusas == 0
```

Se `FakeLLMClient` do arquivo não aceitar `model=`, ele já aceita: a assinatura é `FakeLLMClient(respostas, model="claude-opus-5")`. `_resposta()` é o helper do arquivo; se ele não receber `Cost`, acrescente o parâmetro opcional `custo` nele em vez de criar um segundo helper.

- [x] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/agent/test_teto.py -q`
Expected: FAIL com `ImportError: cannot import name 'Orcamento'`.

- [x] **Step 3: Write `Orcamento`**

Em `src/orchestrator/agent/teto.py`, antes de `ClienteComTeto`:

```python
class Orcamento:
    """O teto de UMA requisição, e o gasto acumulado dela.

    **Por que o acumulador saiu do cliente.** `ClienteComTeto` guardava `gasto`
    como `Cost` e convertia com `self.model` — um modelo só, porque um cliente
    só. Com `model` por bloco, uma cascata tem vários clientes, e um acumulador
    por cliente daria vários tetos: o pedido que autorizou gastar X gastaria X
    por modelo, sem ninguém pedir.

    **O acumulado é em MICRO-CENTAVOS, não em tokens.** Com dois modelos,
    tokens não somam: mil de haiku e mil de opus não são dois mil de coisa
    nenhuma. O teto é sobre dinheiro, então a moeda é µ¢ — e é a mesma razão
    pela qual `Cost` continua sem preço: cada lado guarda a unidade em que ele
    é verdade.
    """

    def __init__(self, teto_microcents: int | None = None) -> None:
        if teto_microcents is not None and teto_microcents < 0:
            # Teto negativo nasceria estourado e faria TODO item abster sem
            # nunca chamar o modelo — pareceria um agente funcionando com
            # orçamento zerado, em vez de configuração inválida.
            raise ValueError(f"teto_microcents não pode ser negativo: {teto_microcents}")
        self.teto_microcents = teto_microcents
        self._gasto = 0
        # Quantas chamadas o teto RECUSOU. Contado aqui e em lugar nenhum mais,
        # porque aqui é onde a recusa acontece — e porque "paramos no teto" e "a
        # API falhou" viram o mesmo desfecho depois da captura de `conversa.py`.
        self.recusas = 0

    def gasto_microcents(self) -> int:
        return self._gasto

    def pode_gastar(self) -> bool:
        """O teto é conferido ANTES de cada chamada, nunca depois — não há como
        saber o custo de uma chamada sem fazê-la, então a última pode
        ultrapassá-lo por um turno."""
        return self.teto_microcents is None or self._gasto < self.teto_microcents

    def registrar(self, cost: Cost, model: str) -> None:
        """Soma no PREÇO do modelo que gastou.

        `Cost.zero()` não consulta a tabela: uma execução que não gastou nada
        não deve exigir preço para ler zero — a mesma guarda de
        `metrics.evaluate` e de `Run.custo_total_microcents`.
        """
        if cost != Cost.zero():
            self._gasto += cost.microcents(model)

    def barrar(self) -> None:
        self.recusas += 1
```

- [x] **Step 4: `ClienteComTeto` passa a usar o `Orcamento`**

Trocar o corpo de `__init__`, `gasto_microcents` e `complete`:

```python
    def __init__(
        self,
        interno: LLMClient,
        *,
        teto_microcents: int | None = None,
        orcamento: "Orcamento | None" = None,
    ) -> None:
        # Sem `orcamento`, ele cria o seu: é a forma que todo chamador de hoje
        # escreve, e ela continua significando "um teto para este cliente".
        # Com `orcamento`, vários clientes de modelos diferentes dividem o
        # mesmo teto — que é o que a requisição autorizou.
        if orcamento is not None and teto_microcents is not None:
            raise ValueError(
                "passe `orcamento` OU `teto_microcents`, não os dois: o teto "
                "mora no orçamento, e dois valores seriam duas respostas para "
                "a mesma pergunta"
            )
        self.interno = interno
        self.orcamento = orcamento if orcamento is not None else Orcamento(teto_microcents)
        # O MODELO é o do cliente de dentro, e é com ele que ESTE embrulho
        # precifica o que ELE gastou.
        self.model = interno.model

    @property
    def teto_microcents(self) -> int | None:
        return self.orcamento.teto_microcents

    @property
    def recusas(self) -> int:
        return self.orcamento.recusas

    def gasto_microcents(self) -> int:
        return self.orcamento.gasto_microcents()

    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        if not self.orcamento.pode_gastar():
            self.orcamento.barrar()
            raise TetoDaExecucaoEstourado(
                f"teto desta execução esgotado: {self.orcamento.gasto_microcents()} µ¢ "
                f"gastos de um teto de {self.orcamento.teto_microcents} µ¢"
            )
        resposta = self.interno.complete(system=system, messages=messages, tools=tools)
        self.orcamento.registrar(resposta.cost, self.model)
        return resposta
```

- [x] **Step 5: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/agent/test_teto.py -q`
Expected: PASS, incluindo os testes que já existiam no arquivo.

- [x] **Step 6: Suíte, lint e commit**

```bash
.venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m ruff check src tests
git add src/orchestrator/agent/teto.py tests/agent/test_teto.py
git commit -m "feat(teto): Orcamento — o teto que varios clientes dividem"
```

---

### Task 2: O resolver declara seu modelo

**Files:**
- Modify: `src/orchestrator/kernel/resolver.py` (`ResolverDescription`)
- Modify: `src/orchestrator/agent/agent.py:170-176` e `src/orchestrator/agent/tarefa.py` (`describe`)
- Test: `tests/kernel/test_resolution.py` ou `tests/agent/test_declarado.py` — usar `tests/agent/test_declarado.py`, que já constrói agentes declarados

**Interfaces:**
- Consumes: nada da Task 1.
- Produces: `ResolverDescription(..., model: str = "")`; `Agent.describe().model == spec.model`; `Tarefa.describe().model == spec.model`.

- [x] **Step 1: Write the failing test**

Em `tests/agent/test_declarado.py`:

```python
def test_o_resolver_DECLARA_com_que_modelo_roda():
    """A borda precisa precificar CADA linha da tabela de custo com o modelo
    daquela linha. Sem isto ela converte tudo com um modelo só — medido: um run
    com um bloco declarado em haiku reportou 4.494.000 µ¢ de preço de opus.

    Declarado no RESOLVER e não numa tabela na borda, pela mesma razão que
    `consome`, `produz` e `payloads`: uma lista paralela apodrece no dia em que
    alguém escreve o próximo resolver.
    """
    from orchestrator.agent.declarado import AgenteDeclarado, construir_agente
    from orchestrator.agent.llm import FakeLLMClient

    declarado = AgenteDeclarado(
        name="triador",
        system="classifique",
        kind="issue",
        prompt="{titulo}",
        tipos=("BUG",),
        abstem_com="NAO_SEI",
        model="claude-haiku-4-5",
    )

    agente = construir_agente(declarado, FakeLLMClient([], model="claude-opus-5"))

    assert agente.describe().model == "claude-haiku-4-5"


def test_um_resolver_que_NAO_fala_com_modelo_declara_vazio():
    """Regra não tem modelo, e vazio é a resposta certa — não o modelo padrão
    do servidor, que faria uma linha de 0 µ¢ parecer precificada."""
    from orchestrator.kernel.resolver import ResolverDescription
    from orchestrator.kernel.cost import CostClass

    d = ResolverDescription(name="L1", cost_class=CostClass.REGRA, summary="x")

    assert d.model == ""
```

- [x] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/agent/test_declarado.py -q -k modelo`
Expected: FAIL com `AttributeError: 'ResolverDescription' object has no attribute 'model'`.

- [x] **Step 3: Implementar**

Em `kernel/resolver.py`, no fim dos campos de `ResolverDescription`:

```python
    # COM QUE MODELO este resolver fala, quando fala. Vazio — o default — é
    # "não falo com modelo nenhum", que é o caso de toda regra.
    #
    # Existe porque a tabela de custo do run precisa converter CADA linha com o
    # preço certo. Antes dela, a borda convertia tudo com um modelo só: medido,
    # um bloco declarado em `claude-haiku-4-5` apareceu com 4.494.000 µ¢, que é
    # preço de opus — o número que o produto vende, errado por 5x.
    #
    # Declarado no RESOLVER, e não numa tabela de nomes na borda, pela mesma
    # razão que `consome`, `produz` e `payloads`: a lista paralela apodrece no
    # dia em que alguém escreve o próximo resolver.
    model: str = ""
```

Em `agent/agent.py::Agent.describe` e `agent/tarefa.py::Tarefa.describe`, acrescentar `model=self.spec.model,`.

- [x] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/agent tests/kernel -q`
Expected: PASS.

- [x] **Step 5: Suíte, lint e commit**

```bash
.venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m ruff check src tests
git add src/orchestrator/kernel/resolver.py src/orchestrator/agent tests/agent
git commit -m "feat(kernel): o resolver declara com que modelo ele fala"
```

---

### Task 3: De um cliente para uma fábrica

**Files:**
- Modify: `src/orchestrator/workflows.py` (`WorkflowContext`, `_de_receita`, `_de_composicao`)
- Modify: `src/orchestrator/authoring/composicao.py` (`construir_composicao`, `_degrau`, `_tripulacao`)
- Modify: `src/orchestrator/grill/receita.py` (`construir`)
- Modify: `src/orchestrator/agent/declarado.py` (`construir_agente`, `construir_tarefa` — só o tipo do parâmetro muda de nome, ver abaixo)
- Test: `tests/authoring/test_composicao.py`

**Interfaces:**
- Consumes: `ResolverDescription.model` (Task 2) não é usado aqui; a Task 3 é sobre construção.
- Produces: `WorkflowContext(fila, cliente_para: Callable[[str], LLMClient] | None = None, contexto=None)`; `construir_composicao(c, *, fila=None, cliente_para=None, contexto=None)`; `construir(receita, *, fila=None, cliente_para=None, context=None)`.

**Decisão que o implementador não deve reabrir:** `construir_agente(decl, client, ferramentas)` **continua recebendo um CLIENTE**, não a fábrica. Quem chama a fábrica é o construtor da cascata, que sabe o `decl.model`. Isso mantém `construir_agente` testável com um fake direto — como 20 testes já fazem.

- [x] **Step 1: Write the failing test**

Em `tests/authoring/test_composicao.py`:

```python
def test_cada_bloco_recebe_o_CLIENTE_DO_SEU_MODELO():
    """A fábrica é chamada com o modelo que o bloco declarou.

    Sem isto, `model` era decorativo: medido contra uma API real, um bloco
    declarado em `claude-haiku-4-5` fez a chamada em opus, porque quem decide é
    `AnthropicClient.complete`, que usa o modelo do CLIENTE.
    """
    from orchestrator.agent.declarado import AgenteDeclarado
    from orchestrator.agent.llm import FakeLLMClient
    from orchestrator.authoring.composicao import (
        BlocoAgente,
        Composicao,
        agora,
        construir_composicao,
    )

    pedidos: list[str] = []

    def fabrica(model: str):
        pedidos.append(model)
        return FakeLLMClient([], model=model or "claude-opus-5")

    def _ag(nome, model):
        return BlocoAgente(
            declaracao=AgenteDeclarado(
                name=nome,
                system="s",
                kind="issue",
                prompt="{titulo}",
                tipos=("BUG",),
                abstem_com="NAO_SEI",
                model=model,
            )
        )

    construir_composicao(
        Composicao(
            id="c1",
            nome="dois modelos",
            gerado_em=agora(),
            blocos=(_ag("barato", "claude-haiku-4-5"), _ag("caro", "claude-opus-5")),
            entrega=("issue",),
        ),
        cliente_para=fabrica,
    )

    assert pedidos == ["claude-haiku-4-5", "claude-opus-5"]


def test_sem_fabrica_a_TRANCA_continua_sendo_o_default():
    """Compor não gasta. O default vira uma fábrica que devolve a tranca, e
    `ClienteDeValidacao.complete` continua levantando se alguém chegar ao
    modelo por um caminho que não deveria existir."""
    from orchestrator.agent.declarado import AgenteDeclarado, ClienteDeValidacao
    from orchestrator.authoring.composicao import (
        BlocoAgente,
        Composicao,
        agora,
        construir_composicao,
    )

    definicao = construir_composicao(
        Composicao(
            id="c2",
            nome="sem fabrica",
            gerado_em=agora(),
            blocos=(
                BlocoAgente(
                    declaracao=AgenteDeclarado(
                        name="a",
                        system="s",
                        kind="issue",
                        prompt="{titulo}",
                        tipos=("BUG",),
                        abstem_com="NAO_SEI",
                    )
                ),
            ),
            entrega=("issue",),
        )
    )

    (stage,) = definicao.stages
    assert isinstance(stage.cascade[0].client, ClienteDeValidacao)
```

- [x] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/authoring/test_composicao.py -q -k "MODELO or TRANCA"`
Expected: FAIL com `TypeError: construir_composicao() got an unexpected keyword argument 'cliente_para'`.

- [x] **Step 3: `construir_composicao` recebe a fábrica**

Trocar o parâmetro `cliente: LLMClient | None = None` por:

```python
    # QUEM dá o cliente de cada bloco, a partir do modelo que ele declarou.
    #
    # Era um cliente só, e por isso `AgenteDeclarado.model` não decidia nada: o
    # modelo da chamada é o do CLIENTE (`AnthropicClient.complete` usa
    # `self.model`), então todo bloco falava com o mesmo. Medido contra uma API
    # real: um bloco declarado em `claude-haiku-4-5` gastou preço de opus.
    #
    # `None` continua sendo a TRANCA, e agora ela também vem por fábrica:
    # `ClienteDeValidacao` constrói o agente e recusa falar com modelo.
    cliente_para: Callable[[str], LLMClient] | None = None,
```

e o default:

```python
    if cliente_para is None:
        cliente_para = lambda _model: ClienteDeValidacao()  # noqa: E731
```

`_degrau` e `_tripulacao` passam a receber `cliente_para` e chamam:

```python
            resolvers.append(
                construir_agente(bloco.declaracao, cliente_para(bloco.declaracao.model), ferramentas)
            )
```

```python
        elif isinstance(bloco, BlocoTarefa):
            resolvers.append(
                construir_tarefa(bloco.declaracao, cliente_para(bloco.declaracao.model), ferramentas)
            )
```

e em `_tripulacao`, cada agente da tripulação pede o SEU:

```python
    agentes = tuple(
        construir_agente(a, cliente_para(a.model), ferramentas) for a in bloco.agentes
    )
```

- [x] **Step 4: `grill/receita.py::construir` e `workflows.py`**

Em `grill/receita.py`, a assinatura e o default:

```python
def construir(
    receita: Receita,
    *,
    fila: Fila | None = None,
    cliente_para: Callable[[str], LLMClient] | None = None,
    context: ToolContext | None = None,
) -> WorkflowDefinition:
```

```python
    if cliente_para is None:
        # A TRANCA, agora entregue por fábrica: `ClienteAusente` levanta se
        # algum caminho chegar ao modelo por onde não deveria existir caminho.
        # `is None` e não `or`, como as três linhas vizinhas já fazem.
        cliente_para = lambda _model: ClienteAusente()  # noqa: E731
```

E a única linha que constrói agente (hoje `receita.py:190`):

```python
            # O cliente do MODELO que este agente declarou. Um cliente só fazia
            # todo bloco falar com o mesmo modelo, e era por isso que
            # `AgenteDeclarado.model` não decidia nada.
            resolvers.append(
                construir_agente(entrada, cliente_para(entrada.model), ferramentas)
            )
```

Não há outro ponto: o ramo de `RegraDisponivel` chama `entrada.construir(...)`, que tem assinatura uniforme `(parametros) -> Resolver` e não recebe cliente nenhum — uma regra não fala com modelo.

`WorkflowContext.cliente` vira:

```python
    # QUEM dá o cliente de cada bloco, pelo modelo que ele declarou. Era um
    # cliente só — e é por isso que `model` por bloco não decidia nada.
    cliente_para: "Callable[[str], LLMClient] | None" = None
```

e as duas fábricas repassam `cliente_para=ctx.cliente_para`.

- [x] **Step 5: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/authoring tests/grill tests/api -q`
Expected: PASS. Os testes que hoje passam `cliente=fake` para `construir_composicao`/`construir` viram `cliente_para=lambda _: fake` — é a tradução mecânica, e ela preserva exatamente o comportamento antigo.

- [x] **Step 6: Suíte, lint e commit**

```bash
.venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m ruff check src tests
git add src/orchestrator tests
git commit -m "feat(authoring): cada bloco recebe o cliente do SEU modelo"
```

---

### Task 4: A borda — a chamada certa e o preço certo

**Files:**
- Modify: `src/orchestrator/api/app.py` (`_cliente_de_execucao`, `_executar`, a tabela `por_resolver`)
- Test: `tests/api/test_execucao.py`

**Interfaces:**
- Consumes: `Orcamento` (Task 1), `ResolverDescription.model` (Task 2), `cliente_para` (Task 3).
- Produces: `RunJSON.por_resolver[].microcents` no preço do modelo daquela linha; `RunJSON.custo_microcents` = soma das linhas.

- [x] **Step 1: Write the failing test**

Em `tests/api/test_execucao.py`:

```python
def test_dois_agentes_em_MODELOS_diferentes_dao_duas_linhas_com_precos_diferentes(
    tmp_path, monkeypatch
):
    """O critério que fecha a fatia: a mesma quantidade de tokens custa 5x mais
    em opus que em haiku, e a tabela precisa dizer isso.

    Antes: a borda convertia tudo com `MODELO_INERTE`. Medido contra a API do
    Barrier, um bloco declarado em haiku apareceu com 4.494.000 µ¢ — preço de
    opus para uma chamada que deveria custar um quinto.
    """
    import orchestrator.api.app as api_app
    from orchestrator.agent.llm import FakeLLMClient, LLMResponse
    from orchestrator.kernel.cost import Cost

    _csv_de_issues(tmp_path, monkeypatch, linhas=1)
    vistos: list[str] = []

    def _de_execucao(teto):
        from orchestrator.agent.teto import ClienteComTeto, Orcamento

        orcamento = Orcamento(teto)

        def fabrica(model: str):
            model = model or "claude-opus-5"
            vistos.append(model)
            return ClienteComTeto(
                FakeLLMClient([_resposta()] * 4, model=model), orcamento=orcamento
            )

        return fabrica, orcamento

    monkeypatch.setattr(api_app, "_tem_chave", lambda: True)
    monkeypatch.setattr(api_app, "_cliente_de_execucao", _de_execucao)
    _registrar(
        monkeypatch,
        "dois-modelos",
        _fabrica_com_agentes(
            _declarado(name="barato", model="claude-haiku-4-5"),
            _declarado(name="caro", model="claude-opus-5"),
        ),
    )

    r = cliente.post(
        "/api/workflows/dois-modelos/runs",
        json={"fonte": _FONTE_ISSUES, "teto_microcents": 100_000_000},
    )

    assert r.status_code == 200, r.text
    linhas = {p["name"]: p["microcents"] for p in r.json()["por_resolver"]}
    # Mesmos tokens, preços diferentes: opus é 5x haiku na tabela.
    assert linhas["caro"] == 5 * linhas["barato"]
    # E o total é a SOMA das linhas, não uma conversão única.
    assert r.json()["custo_microcents"] == linhas["caro"] + linhas["barato"]
    assert vistos == ["claude-haiku-4-5", "claude-opus-5"]
```

`_fabrica_com_agentes` do arquivo monta a cascata com `construir_agente(d, cliente_do_ctx)`; ela passa a usar `ctx.cliente_para(d.model)`. `_declarado(**kw)` já aceita `name=` e passará a aceitar `model=` por já usar `base.update(kw)`.

- [x] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_execucao.py -q -k MODELOS_diferentes`
Expected: FAIL — hoje as duas linhas têm o mesmo preço, porque as duas são convertidas com `MODELO_INERTE`.

- [x] **Step 3: `_cliente_de_execucao` devolve a fábrica e o orçamento**

```python
def _cliente_de_execucao(
    teto_microcents: int | None,
) -> tuple[Callable[[str], ClienteComTeto], Orcamento]:
    """A fábrica de clientes desta requisição, e o orçamento que todos dividem.

    **Por que uma fábrica e não um cliente.** O modelo da chamada é o do
    CLIENTE (`AnthropicClient.complete` usa `self.model`), então um cliente só
    fazia todo bloco falar com o mesmo modelo — e `model` por bloco não decidia
    nada. Medido contra uma API real: um bloco declarado em `claude-haiku-4-5`
    gastou preço de opus.

    **Por que UM orçamento.** O teto é da REQUISIÇÃO. Um acumulador por cliente
    daria um teto por modelo, e o pedido que autorizou gastar X gastaria X por
    modelo sem ninguém pedir.

    Construir NÃO fala com a rede: `AnthropicClient` só instancia o SDK na
    primeira chamada, e a fábrica é memoizada por modelo para não criar um
    cliente por bloco.
    """
    from orchestrator.agent.anthropic_client import AnthropicClient

    orcamento = Orcamento(teto_microcents)
    cache: dict[str, ClienteComTeto] = {}

    def para(model: str) -> ClienteComTeto:
        nome = model or MODELO_INERTE
        if nome not in cache:
            cache[nome] = ClienteComTeto(AnthropicClient(nome), orcamento=orcamento)
        return cache[nome]

    return para, orcamento
```

Em `_executar`, o uso:

```python
        cliente_para, orcamento = _cliente_de_execucao(pedido.teto_microcents)
        definicao = construir_definicao(
            fabrica,
            WorkflowContext(fila=fila, cliente_para=cliente_para, contexto=_contexto_de(pool)),
        )
```

e as duas leituras que hoje usam `cliente`:

```python
        parou_no_teto = orcamento is not None and orcamento.recusas > 0
```

```python
                "custo_microcents": orcamento.gasto_microcents() if orcamento else 0,
```

- [x] **Step 4: A tabela precifica por linha**

```python
    # O modelo de CADA linha, declarado pelo resolver. Era `modelo` — um só
    # para a tabela inteira —, e com `model` por bloco isso passou a mentir: a
    # linha de um bloco em haiku vinha com preço de opus, 5x maior. O número
    # por resolver é o que este produto vende; ele não pode sair de um default.
    microcents=(
        c.microcents(d.model or modelo)
        if (c := run.cost_by_resolver.get(d.name, Cost.zero())) != Cost.zero()
        else 0
    ),
```

e o total:

```python
        # A SOMA das linhas, cada uma no seu preço — e não
        # `run.custo_total_microcents(modelo)`, que converte tudo com um modelo
        # só. `Run.custo_total_microcents` continua existindo para a CLI e o
        # `eval/`, que de fato rodam com um modelo só.
        custo_microcents=sum(p.microcents for p in por_resolver),
```

- [x] **Step 5: Atualizar os cinco arquivos que trocam `_cliente_de_execucao`**

`_cliente_de_execucao` passa a devolver `(fábrica, orçamento)` em vez de um cliente, então todo teste que o monkeypatcha muda. São **cinco**, e a tradução é mecânica:

```python
# antes
monkeypatch.setattr(
    api_app, "_cliente_de_execucao",
    lambda teto: ClienteComTeto(fake, teto_microcents=teto),
)

# depois
def _de_execucao(teto):
    orcamento = Orcamento(teto)
    return (lambda _model: ClienteComTeto(fake, orcamento=orcamento)), orcamento

monkeypatch.setattr(api_app, "_cliente_de_execucao", _de_execucao)
```

Os arquivos: `tests/api/test_execucao.py`, `tests/api/test_bloco_tarefa.py`, `tests/api/test_contexto_das_ferramentas.py`, `tests/api/test_dinheiro_workflow_gerado.py` e `tests/api/test_propostas_persistidas.py`.

**Um deles merece leitura, não substituição cega:** `test_execucao.py` tem os testes de teto (`test_o_teto_do_pedido_PARA_o_gasto`, `test_um_teto_GENEROSO_nao_desliga_o_teto_do_AGENTE`), e eles afirmam números de gasto. Os números não mudam — o fake continua sendo o mesmo e o modelo do embrulho continua sendo o do fake —, mas se algum mudar, é sinal de que o `Orcamento` está precificando diferente, e aí o teste está certo e o código errado.

- [x] **Step 6: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api -q`
Expected: PASS.

- [x] **Step 7: Suíte, lint, número do produto e commit**

```bash
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check src tests
.venv/Scripts/orchestrator.exe --seed 1 --n 500
git add src/orchestrator/api tests/api
git commit -m "feat(runs): a chamada vai para o modelo do bloco, e o preco e por linha"
```

---

### Task 5: Fechar a medição contra o Barrier

**GASTA DINHEIRO — não execute sem dizer o custo esperado e obter um sim.**

- [ ] **Step 1: Subir o servidor com chave e conferir a mesa**

`preview_start` com `canvas-com-chave` (porta 8112), e
`GET http://192.168.1.13:8080/v1/mesa/queues/ANALISE_PADRAO` com o bearer do
Barrier deve devolver os dois casos.

- [ ] **Step 2: Rodar `mesa-barrier-haiku`**

```bash
curl -X POST http://localhost:8112/api/workflows/mesa-barrier-haiku/runs \
  -H "Content-Type: application/json" -d '{"teto_microcents": 3000000}'
```

Expected: `estado: concluido`, a linha do `analista-de-mesa` custando ~1/5 do
que custou em opus (4.494.000 µ¢), e duas propostas na fila com o
encaminhamento de cada caso.

- [ ] **Step 3: Registrar os números na spec e commitar**

Acrescentar a seção "Executado" com o custo medido das duas execuções lado a
lado, e commitar com `docs(spec):`.

---

## Fora deste plano, de propósito

- **`complete` com parâmetro `model`** (A2 da spec): fica para o dia em que
  alguém precisar trocar de modelo no meio de uma conversa.
- **Modelo por ITEM** dentro do mesmo bloco: isso é cascata, e o produto já tem
  cascata — são dois blocos.
- **Preço de modelo local:** sem preço não há custo, e `0` faria a coluna mentir.
