# Runtime de Orquestração — do conciliador ao motor genérico

**Data:** 2026-09-16
**Estado:** ENTREGUE (M0–M8).
**Estado do repo auditado (instantâneo de 2026-09-16, não atualizado):** branch `ci/github-actions`, 107 arquivos Python,
~12.2k LOC (≈5.5k em `src/`, ≈6.7k em `tests/`), **449 testes passando**,
CI verde em 3.11/3.13 × `[dev]`/`[dev,api]`.
**Specs antecessores:** [design do produto](2026-09-14-agent-orchestrator-design.md),
[composição de workflows](2026-09-14-composicao-de-workflows-design.md).

> Tese: **CrewAI orquestra agentes. Agent Orchestrator deve orquestrar trabalho.**

---

## 1. Executive Summary

### 1.1 O achado principal

**A tese já está implementada.** Não como slide, como código executável e
testado. O que existe hoje em `src/orchestrator/workflow/` é, literalmente, a
arquitetura alvo em miniatura:

| Conceito do desenho alvo | Já existe em | Forma atual |
|---|---|---|
| Workflow | `workflow/definition.py` | `WorkflowDefinition(id, name, stages)` |
| Task/Step | `workflow/definition.py` | `Stage(name, cascade)` |
| Deterministic step | `matching/exact.py`, `tolerance.py`, `grouping.py` | 3 `Resolver` de classe `REGRA` |
| Resolver | `workflow/resolver.py` | `Resolver` Protocol |
| Agent | `agent/investigator.py` | `Investigator`, um `Resolver` de classe `AGENTE` |
| Human | `review/revisor.py` | `RevisorHumano`, um `Resolver` de classe `HUMANO` |
| Policy (custo) | `workflow/cost_class.py` | `CostClass(IntEnum)` = ordem de execução |
| Execution | `matching/engine.py` | `reconcile()` |
| State | `workflow/workset.py` | `WorkSet.without(matches)` |
| Cost | `agent/proposal.py` | `Cost` em micro-centavos, 5 componentes |
| Trace | `agent/proposal.py` | `TraceEvent` / `TraceKind` |
| Human-in-the-loop | `review/` | `Proposal` → `Decision` → `MatchResult` |
| Workflow authoring | `grill/` | entrevista → `Receita` → `construir()` |

A cadeia `Resolver → Agent → Human` **roda hoje**, num único motor, com custo
medido por resolver e trilha de auditoria append-only. O `Resolver → Agent →
Crew → Human` do desenho alvo é uma extensão de um item numa enum, não uma
reescrita.

### 1.2 O que de fato falta

Cinco lacunas, em ordem de consequência arquitetural:

1. **O kernel é soldado ao domínio de conciliação.** `WorkSet` tem
   `bank: list[BankEntry]` e `ledger: list[LedgerEntry]` literalmente nos
   campos. `ResolverOutput.matches` é `list[MatchResult]`, e `MatchResult` tem
   `bank_ids`/`ledger_ids`. `Proposal.tipo` é `DivergenceType`. **Não existe um
   segundo domínio expressável** sem tocar em `workflow/`. Este é o bloqueador
   de tudo o mais.

2. **`Run` não existe como entidade.** A execução é
   `_executar_memoizado(workflow_id, seed, n, taxa)` com `@lru_cache(maxsize=64)`
   em `api/app.py`. Não há id de execução, timestamp, status, duração nem
   persistência. Sem `Run`, não há o que observar, pausar, retomar, comparar ou
   avaliar — observabilidade, HITL formal e evaluation todos param aqui.

3. **Não existe abstração de fonte de entrada.** O único produtor de `Dataset` é
   `build_benchmark(seed, n, taxa_divergencia)` em `cli.py`, e a API **importa
   dele**: o corpo de `POST /runs` é literalmente `RunRequest(seed, n,
   taxa_divergencia)`. Isso é acoplamento mesmo que o sintético continue sendo a
   única fonte — porque a **identidade** de uma execução (e, por tabela, o
   escopo da fila de decisões humanas) passa a ser uma tupla de parâmetros de
   benchmark. O que falta não é um parser de OFX; é um `Source` e um
   `input_ref`. (Ver §1.3: parser de formato bancário real saiu do escopo.)

4. **A avaliação só sabe comparar modelos.** `agent_eval.py` compara `opus` ×
   `sonnet` × `haiku` contra o mesmo gabarito, e faz isso bem. Não há como
   comparar **prompt A × prompt B**, **política A × B**, **cascata A × B** ou
   **agente × crew** — que são as comparações que um framework precisa oferecer.
   Falta `EvaluationCase`, `EvalDataset` versionado, `Evaluator` plugável e
   detecção de regressão. O sinal de correção humana existe e é descartado
   (`ItemFilaJSON.divergiu` é calculado, exibido na tela e jogado fora).

5. **A política é uma ordenação estática, não uma decisão.**
   `Stage.ordered()` faz `sorted(cascade, key=lambda r: r.cost_class)` e o motor
   roda **todos** os resolvers, sempre. Não há avaliação de política por item:
   nenhum ponto no código decide *se* vale a pena chamar o agente para *este*
   item. Os ingredientes existem (classe de custo, orçamento em dois níveis,
   `Confidence`); o ponto de decisão, não.

Multi-agente (`Crew`), memória, knowledge/RAG, MCP e A2A: **zero linhas**. São
os itens de menor risco e menor prioridade, precisamente porque nada depende
deles.

### 1.3 A regra dos três usos, suspensa por decisão do dono

Este plano contraria uma decisão arquitetural registrada e datada no próprio
repositório:

> `spec §2.1`: "nenhuma abstração de plataforma é criada antes de existirem
> **três usos concretos** que a justifiquem."
> `spec §9`, tabela de anti-escopo: "DSL de workflow — desbloqueia quando
> houver 3 workflows reais e distintos **em produção**."
> `spec §10`, riscos: "Deriva para plataforma cedo demais — severidade **Alta**."
> `README`: "A plataforma é o produto do ano 2, **extraída** de três casos
> reais — não projetada a partir de zero instâncias."

**Decisão (2026-09-16, dono do projeto): a regra fica suspensa. A plataforma é
construída agora, a partir de uma instância.** Registrada aqui porque uma
decisão que contraria um spec precisa aparecer no lugar onde o spec é lido, e
não numa conversa.

O que isso muda no plano: a ordem das fases (§23) passa a otimizar para
**framework utilizável por terceiro**, não para **produto entregue antes da
plataforma**. Consequências concretas — API pública (`Agent`/`Task`/`Tool`) sobe
de M5 para M2; CLI e scaffold sobem de M9 para M5; `Crew`, MCP e memória deixam
de estar atrás de gatilho comercial e passam a estar atrás apenas de dependência
técnica.

**O que NÃO muda, porque não era produto de cautela e sim de engenharia:**

1. **A ordem M0 → M1 continua.** De-domainizar o kernel e criar `Run` não são
   "abstrair cedo" — são pré-requisitos técnicos de tudo o mais. Policy precisa
   de `Run`; observabilidade precisa de `Event`; avaliação precisa dos dois.
2. **Generalizar continua sendo remover domínio, não adicionar conceito.** As
   Fases 0–1 seguem sem criar um único conceito novo além de `Run`/`Event`: elas
   tiram `BankEntry`/`LedgerEntry`/`DivergenceType` de `workflow/`, `Cost` de
   `agent/` e `Run` de dentro de um `lru_cache`.
3. **Os números do conciliador continuam sendo o critério de aceitação.** `85.3%`,
   FP=0, FN=0 e o golden de 12 sementes valem para todo PR. Suspender a regra dos
   três usos não suspende a suíte.

**O substituto de engenharia para a regra suspensa.** A regra existia porque
abstração desenhada a partir de zero instâncias costuma estar errada, e isso
continua verdade independentemente de quem decide. O substituto barato não é
esperar três clientes — é **escrever as outras duas instâncias como esqueletos
executáveis junto com a abstração, não depois dela**. O spec de composição §1.3
já nomeia as três verticais:

| Vertical | Stage | Cascata |
|---|---|---|
| Finance Ops | "conciliar lançamentos" | exato → tolerância → agrupamento → agente → humano |
| Procurement | "quem fornece isto?" | preferidos → compras anteriores → agente → humano |
| Software Eng | "que mudança esta issue pede?" | *(sem regra barata)* → agente → humano |

A terceira é o caso degenerado — cascata sem nenhum resolver de classe `REGRA`.
Se ela couber sem forçar, a abstração é genérica; se não couber, é a conciliação
com nomes trocados. **Por isso os dois domínios extras entram em M0, e não em
M5** (ver §23, Fase 0): são ~80 linhas cada, não precisam ser úteis, e precisam
apenas rodar. É a diferença entre validar a abstração em duas semanas e
descobrir em seis meses que ela não serve.

**O anti-escopo (§21) foi revisado à luz desta decisão:** os itens que estavam
lá por serem *cedo demais* saíram; os que estavam por serem *caros e sem
demanda* (multi-tenancy, RBAC, marketplace, durable execution própria, vector DB
no core) ficam, porque a razão deles nunca foi a regra dos três usos.

### 1.4 A ordem, derivada das dependências

O roadmap sugerido no pedido começa por "Phase 1 — Agent Runtime". A análise de
dependências diz que **nada** pode começar por ali: o `Investigator` importa
`WorkSet`, que importa `BankEntry`. Generalizar o agente antes de
de-domainizar o kernel é generalizar sobre um alicerce que ainda vai se mover.

A ordem que as dependências impõem, já com a regra dos três usos suspensa
(§1.3) e a conciliação rebaixada a implementação de referência:

```
M0  kernel sem domínio + 3 domínios   ← bloqueia TUDO; valida a abstração na hora
M1  Run + Event + Store + Context     ← bloqueia observabilidade, HITL, eval
M2  Agent / Task / Tool / Registry    ← a API pública do framework
M3  Policy engine                     ← a tese; precisa de M0+M1
M4  Observability                     ← lê o stream de M1
M5  CLI / SDK / scaffold              ← framework que ninguém consegue usar não é framework
M6  Evaluation                        ← precisa de M1+M4; gate para M8
M7  HITL formal                       ← precisa de M1 (estados de Run)
M8  Crew                              ← precisa de M2; medido contra M6
M9  Memory / Knowledge                ← adapters
M10 Dashboard
M11 Ecossistema (MCP / A2A / Temporal)
```

**Três inversões em relação ao pedido, com a razão de cada uma:**

1. **`Agent`/`Task`/`Tool` sobe de "Phase 2" para M2** — mas depois de M0/M1, não
   antes. É a superfície que um terceiro importa, e com a plataforma como alvo
   ela deixa de ser refatoração e vira entregável.
2. **CLI/DX sobe de "Phase 10" para M5.** Um framework que exige ler o código
   para ser usado não tem usuários. `orchestrator init` + um exemplo que roda é
   pré-requisito de qualquer feedback externo, e feedback externo é o único
   substituto real para a regra dos três usos que foi suspensa.
3. **Evaluation fica em M6, não em M4.** No plano original ela subia porque o
   README a chama de "ativo de longo prazo" que acumula correção humana de
   produção ao longo de meses. **Com a conciliação descartável, não há produção
   de onde colher** — o argumento do fosso evapora junto com o produto.
   Avaliação continua necessária (comparar prompt, política, cascata, agente ×
   crew é feature de framework, e é o gate do M8), mas como capacidade, não como
   ativo que precisa começar a render cedo. Esta é a consequência mais direta da
   decisão de §1.3, e vale registrá-la: **suspender o produto também suspende a
   razão pela qual a avaliação era urgente.**

### 1.5 O que este plano preserva sem negociação

Sete invariantes que a auditoria encontrou codificados como garantias
estruturais — não convenções — e que **nenhuma fase pode quebrar**:

1. **Proposta não resolve.** `WorkSet.without()` recebe `list[MatchResult]`, não
   `ResolverOutput`, deliberadamente: não existe assinatura pela qual uma
   proposta chegue ao pool.
2. **A ordem de custo não é invertível.** `Stage.ordered()` ordena pelo valor da
   enum; não há entrada que a inverta.
3. **Nenhum endpoint gasta dinheiro.** Não é flag: não existe caminho de código
   de `api/app.py` até o modelo. Provado por `tests/api/test_execucao.py`, com
   `ClienteAusente` como tranca e 409 como porta.
4. **Uma definição só.** O objeto que o motor executa é o mesmo que a API
   serializa. Nunca uma descrição paralela.
5. **`reconcile()` é puro.** Só o CLI grava proposta, só a API grava decisão. É
   disso que o golden de 12 sementes depende.
6. **Dinheiro é `int` em centavos; custo é `int` em micro-centavos.** Ponto
   flutuante é proibido.
7. **Validar é construir.** `grill/receita.py::construir()` — se retorna, roda.

---

## 2. Current Repository Architecture

### 2.1 Mapa de módulos e camadas reais

O grafo de imports (extraído do código, não do README) revela **cinco camadas
de fato**, com três inversões:

```
NÍVEL 0 — folhas puras, zero dependências internas
  models.py        BankEntry, LedgerEntry, MatchResult, Divergence
  money.py         parse_brl / format_brl, int centavos
  dates.py         dias úteis
  tax.py           retenção na fonte
  taxonomy.py      DivergenceType (14 tipos)
  workflow/cost_class.py   CostClass(IntEnum) REGRA=0 AGENTE=1 HUMANO=2

NÍVEL 1 — contratos
  agent/proposal.py     Cost, Proposal, Confidence, TraceEvent, _PRECOS
  workflow/workset.py   WorkSet
  workflow/resolver.py  Resolver, ResolverOutput, ResolverDescription
  agent/llm.py          LLMClient, LLMResponse, ToolCall, FakeLLMClient

NÍVEL 2 — implementações de resolver
  matching/{exact,tolerance,grouping}.py   REGRA
  agent/investigator.py                    AGENTE
  review/revisor.py                        HUMANO

NÍVEL 3 — composição e motor
  workflow/definition.py   WorkflowDefinition, Stage, default_definition
  matching/engine.py       reconcile(), default_resolvers(), ReconcileResult
  metrics.py               evaluate() -> Metrics

NÍVEL 4 — bordas
  cli.py                orchestrator
  api/{app,schemas}.py  FastAPI + canvas
  eval/                 agent_eval, replay, assinatura
  grill/                entrevista → receita → workflow
  synth/                gerador de benchmark com gabarito
  web/                  canvas.js, fila.js (vanilla, 624 linhas)
```

**Inversão 1 — o núcleo depende do agente.** `workflow/resolver.py` importa
`Cost` e `Proposal` de `orchestrator.agent.proposal`. O contrato genérico de
resolução importa o pacote do agente. Consequência: não é possível usar o
kernel sem arrastar a tabela de preços de LLM e a taxonomia de conciliação.

**Inversão 2 — o motor depende da composição e vice-versa.**
`matching/engine.py` importa `default_definition` **dentro da função**
`reconcile` e `workflow/definition.py` importa `default_resolvers` **do
motor**. Circular, resolvido por import local. Ambos os arquivos documentam a
gambiarra honestamente. É o sintoma de que `default_definition()` está na camada
errada: é configuração de produto, não parte do motor.

**Inversão 3 — a plataforma depende do gerador de benchmark.**
`api/app.py` faz `from orchestrator.cli import build_benchmark`. A camada HTTP
importa o gerador sintético. Consequência direta: a API não sabe executar sobre
nada que não seja um benchmark fabricado por semente.

**O que o teste de camadas encontrou quando foi escrito (PR #1).** As três
inversões acima são as visíveis lendo o código. Medido, o total é **23 arestas
ilegais**, e elas colapsam em cinco causas:

| Causa | Arestas | Fecha em |
|---|---|---|
| Tipos de domínio dentro do núcleo (`models`, `taxonomy`, `money`, `synth`, `agent.tools`) | **14** | PR #3, #4 |
| Motor conhece resolvers do domínio; definição conhece o motor | 6 | PR #5 |
| `api.app -> cli` (inversão 3) | 1 | PR #9 |
| Avaliação lê `ReconcileResult` do motor em vez de `Run` do store | 1 | PR #7 |
| Agente usa a fila humana como cache de idempotência | 1 | PR #11 |

Duas correções ao que esta seção afirmava antes de o teste existir:

1. **A inversão 1 não é problema de dependência — é de localização.**
   `workflow/resolver.py` importar `Cost` de `agent/proposal.py` só é ilegal
   porque `Cost` está no diretório errado. Não há acoplamento a desfazer: PR #2
   é literalmente mover o arquivo. O teste separa as duas coisas
   (`violacoes()` × `deslocados()`) justamente para que um PR que só move
   arquivo não pareça ter consertado acoplamento.
2. **A causa dominante é uma só, e é a lacuna nº 1.** 14 das 23 arestas são
   domínio vazando para dentro de kernel, runtime, agent, human e evaluation.
   Isso confirma a ordem do roadmap: de-domainizar o kernel (M0) não é a
   primeira fase por cautela, é por aritmética.

### 2.2 Componente a componente

#### `workflow/` — o kernel

**O que existe.** `Resolver` Protocol com `name`, `cost_class`, `resolve(work)`,
`describe()`. `ResolverOutput` com `matches`/`proposals`/`cost` separados.
`CostClass(IntEnum)` de três níveis. `WorkSet` com `without()` e
`as_divergences()`. `WorkflowDefinition(id, name, stages)` com
`Stage.ordered()` usando `sorted` estável.

**O que funciona.** Tudo. Esta é a melhor parte do repositório. A separação
`matches` vs `proposals` é uma garantia de tipo, não uma convenção — comentada
no próprio `resolver.py` com a justificativa correta. `sorted` estável preserva
a ordem autoral dentro de uma classe de custo e impõe a ordem entre classes.

**O que está incompleto.** Um `Stage` não tem política, condição de entrada,
timeout, retry nem critério de parada. `WorkflowDefinition` não tem versão — o
spec de composição §4.2 exige "versão imutável, execução fixa a versão", e não
existe campo. Não há `Run`, `Event`, `Checkpoint`.

**O que permanece.** `Resolver`, `ResolverOutput`, `ResolverDescription`,
`CostClass`, `Stage`, `WorkflowDefinition`, `Stage.ordered()`. Os nomes e as
formas estão certos.

**O que deve ser refatorado.** `WorkSet(bank, ledger)` → `WorkSet(items)` com
`WorkItem(id, kind, payload)`. `ResolverOutput.matches: list[MatchResult]` →
`list[Resolution]`. `Cost` sai de `agent/proposal.py` para `kernel/cost.py`.

**O que deve ser removido.** Nada.

**O que deve ser generalizado.** `CostClass` ganha `CREW`; `Stage` ganha
`policy` e `version`; `WorkflowDefinition` ganha `version`.

#### `matching/` — motor + três regras

**O que existe.** `reconcile(bank, ledger, definition=None)` itera stages e
resolvers, encolhe o `WorkSet`, acumula `cost_by_resolver`,
`matches_by_resolver` e `matches_by_class`. Três matchers: L1 exato (índice por
`(documento, valor, data)`), L2 tolerância (5 centavos / 3 dias úteis), L3
agrupamento (busca de subconjuntos com teto de 24 candidatos e grupo máximo 4).

**O que funciona.** A cascata. As três camadas. As guardas de configuração
inválida em `__post_init__` (tolerância negativa, grupo < 2, teto < grupo) — a
disciplina "falha alto em config inválida" é consistente em todo o repositório.
O comentário em `engine.py` explicando que `saida.proposals` não aparece na
expressão que encolhe o pool, e que essa **ausência** é o que torna a invariante
estrutural, é engenharia de primeira linha.

**O que está incompleto.** Sem timeout por resolver. Sem retry por resolver
(só o agente tem, e por dentro). Sem cancelamento. Sem paralelismo. Sem
emissão de evento. Sem medição de latência — `Cost` mede tokens, nunca tempo.

**O que deve ser refatorado.** O nome e o lugar: `reconcile()` é o motor
genérico com nome de domínio, dentro de `matching/`, que é o pacote de um dos
três tipos de resolver. Vira `runtime/engine.py::execute(definition, work,
policy)`. Os três matchers vão para `domains/reconciliation/resolvers/`.

**O que deve ser removido.** `default_resolvers()` sai de `engine.py` (é
configuração do domínio) — o que quebra a circularidade com `definition.py` sem
truque de import.

#### `agent/` — o runtime do agente

**O que existe.** `LLMClient` Protocol (`complete(system, messages, tools)`),
`AnthropicClient` (o único arquivo que conhece o SDK), `FakeLLMClient`,
`Investigator` (laço de 6 turnos, orçamento por divergência e por execução,
retry de formato, abstenção como resposta válida), `ToolContext` com 5
ferramentas somente-leitura + `TOOL_SCHEMAS`, `Proposal` com coerção de enum no
`__post_init__`, `Cost` com 5 componentes e tabela de preços em micro-centavos.

**O que funciona.** O laço inteiro, provado sem rede por `FakeLLMClient`. A
contabilidade de custo — incluindo `cache_creation_tokens`, que a maioria das
implementações ignora e que subcontaria toda primeira chamada de janela de
cache. As guardas: modelo sem preço falha na construção; `max_turns < 1` falha;
orçamento negativo falha. A captura **estreita** em volta de `client.complete()`
(alargá-la transformaria bug do investigador em abstenção plausível) contra a
captura **larga** em `_executar` (erro de ferramenta tem que voltar ao modelo) —
a inversão deliberada está documentada nos dois lugares.

**O que está incompleto.** Não há `Agent` como abstração configurável: existe
**um** agente, `Investigator`, com `SYSTEM` como constante de módulo e as
ferramentas fixas em `ToolContext`. Sem delegação, sem planejamento, sem
memória, sem structured output genérico (o parsing de JSON é manual em
`interpretar_proposta`), sem guardrails além da coerção de enum. `ToolContext`
não é registry: é um objeto com métodos, e `_executar` faz
`getattr(self.context, c.name)` cruzado com os nomes de `TOOL_SCHEMAS`.

**O que deve permanecer.** `LLMClient`, `FakeLLMClient`, `blocos_assistente`,
`AnthropicClient`, a política de erro, os dois níveis de orçamento, `Cost`,
`Confidence`, a abstenção barata.

**O que deve ser refatorado.** `Cost`/`TraceEvent` → kernel. `Proposal` genérica
(hoje `tipo: DivergenceType`, `divergence_id`, `acao_sugerida` com
`conciliar_com(...)`). `ToolContext` → `ToolRegistry` com schema, permissão,
timeout e custo por ferramenta. `Investigator` → `Agent(role, system, tools,
output_schema, budget)` + uma instância de conciliação.

**Armadilha conhecida a corrigir.** `Investigator.investigate()` usa a fila como
**cache permanente sem invalidação** (documentado no próprio comentário): uma vez
na fila, a divergência nunca é reinvestigada, nem se o prompt mudar, o modelo
trocar ou um bug for corrigido. Reprocessar exige apagar a entrada. Isso é
idempotência correta para uma execução e **errado como chave de cache** — a
chave deveria incluir a versão do agente/prompt/modelo.

#### `review/` — human-in-the-loop

**O que existe.** `Decision(divergence_id, veredito, tipo, conciliar_com, autor,
quando, motivo)` com `quando` exigindo timezone. `Fila`: JSONL append-only por
`(workflow, dataset)`, primeira proposta vence, última decisão vence.
`RevisorHumano`: `Resolver` de classe `HUMANO` que lê a fila e emite
`MatchResult`. `serial.py`: ida e volta JSON campo a campo.

**O que funciona.** **Este é o segundo melhor ativo do repositório e é
genuinamente superior ao estado da arte dos frameworks de agente.** O tratamento
de decisão obsoleta em `revisor.py` — id já consumido nesta passagem, id fora do
pool, tudo-ou-nada, silêncio em vez de erro — é o tipo de detalhe que só aparece
depois de um bug em produção. O append-only entrega trilha de auditoria como
subproduto do formato, não como feature.

**O que está incompleto.** Não há pausa nem retomada de verdade: o "pause" é o
item simplesmente não sair do pool, e o "resume" é reexecutar tudo. (Ver §2.3 —
isso é mais elegante do que parece e deve ser **preservado e nomeado**, não
substituído.) Não há SLA, atribuição, fila por usuário, notificação. `Fila`
acumula quatro papéis: fila de trabalho, store de propostas, log de auditoria e
cache de idempotência.

**O acoplamento mais caro do repositório.** A identidade da fila é
`dataset_id(seed, n, taxa) = f"s{seed}-n{n}-t{taxa}"`. **A chave de persistência
de decisões humanas é uma tupla de parâmetros de benchmark sintético.** Quando
entrar dado real, esse identificador não significa nada. Ele tem que virar
identidade de `Run`/`WorkItem`.

#### `api/` + `web/` — plataforma e canvas

**O que existe.** 6 rotas: lista/detalhe de workflow, `POST /runs`, `GET /fila`,
`POST /decisao`, e `mount("/")` estático. Schemas pydantic construídos **a
partir** do domínio (`workflow_json(definicao)`), com teste anti-drift. Canvas
vanilla de 624 linhas que desenha a cascata com números medidos e declara a
lacuna que nenhum resolver cobre.

**O que funciona.** A regra "nenhum endpoint gasta dinheiro", com porta (409) e
tranca (`ClienteAusente`). Os defaults compartilhados por URL entre `canvas.js`
e `fila.js` (uma constante duplicada já quebrou uma vez — P4.14). A checagem de
`ok` em todo `fetch`. O `mount("/")` obrigatoriamente na última linha, comentado.

**O que está incompleto.** Sem autenticação, sem persistência de run, sem
histórico, sem paginação, sem streaming, sem versionamento de API.

**O que deve ser refatorado, com urgência moderada.**
`_construir_definicao(fabrica, fila)` decide passar a fila inspecionando
`inspect.signature(fabrica).parameters` e procurando o **nome** `"fila"`. O
próprio docstring admite: *"O nome `fila` é o único contrato entre este módulo e
`default_definition` — não há import de tipo nem checagem estrutural que os
amarre. Renomear isto para `q` deixaria a suíte inteira verde e faria todo
workflow gerado servir fila vazia em silêncio."* Isso é injeção de dependência
por reflexão sobre nome de parâmetro. Precisa virar um `RuntimeContext` tipado
passado a um `WorkflowFactory` Protocol.

`_executar_memoizado` com `@lru_cache(maxsize=64)` + `cache_clear()` depois de
cada decisão é um **run store disfarçado de memoização**. O próprio docstring
reconhece que a função deixou de ser pura. Vira `RunStore`.

**O que deve ser generalizado, não reescrito.** O canvas. Ele é pequeno,
correto, sem build step e já desenha o conceito certo (cascata com custo e
lacuna). Reescrevê-lo em React seria trocar 624 linhas que funcionam por um
pipeline de build. Ver §17.

#### `grill/` — geração de workflow por entrevista

**O que existe.** `CATALOGO: dict[str, EntradaCatalogo]` — nome, classe de
custo, resumo, specs de parâmetro (com default lido por `dataclasses.fields` do
próprio resolver) e um construtor de **assinatura uniforme**
`construir(parametros, *, fila, cliente, context)`. Três ferramentas tipadas
(`perguntar`, `propor_workflow`, `fora_do_catalogo`) cujo `enum` sai do próprio
catálogo. `Entrevistador`: laço de 12 turnos com orçamento derivado por medição.
`Receita` serializável; `construir()` valida construindo. `registro.py` grava em
`data/workflows/*.json`, não versionado.

**O que funciona.** É um **resolver registry funcionando**, e o mecanismo
`_param()` que lê o default do próprio dataclass (renomear o campo explode no
import, alto, não em silêncio) é exatamente a disciplina certa para um registry
extensível. `fora_do_catalogo` como desfecho **tipado e legítimo** — "não dá" é
resposta correta — é um padrão que a maioria dos geradores de workflow não tem.

**O que está incompleto.** Um estágio só, hard-coded em `receita.py`. Sem grafo,
sem branching, sem paralelismo. Sem versão de receita. O catálogo é um dict
literal de módulo — não há registro por entry point.

**O que deve ser generalizado.** `CATALOGO` → `ResolverRegistry` alimentado por
entry points. `Receita` → `WorkflowSpec` com `stages` plural e `version`.

#### `eval/` + `metrics.py` + `synth/` — avaliação

**O que existe.** `synth/`: gerador de pares limpos + 4 injetores
(`DefasagemTemporal`, `RetencaoImposto`, `DevolucaoFundos`, `PagamentoAgregado`)
com `GroundTruth` e o campo `deterministic_expected` separando "a regra deve
resolver" de "reservado ao agente". `metrics.evaluate()`: taxa determinística,
falso positivo (por **sobreposição**) e falso negativo (por **contenção
total**) — assimetria deliberada e correta, registrada na decisão 24.
`eval/agent_eval.py`: compara N modelos contra o mesmo gabarito, com tabela lado
a lado e o contador `proposals_api_failed` que impede reportar "0% de precisão
por falha de rede" como se fosse desempenho. `eval/replay.py`:
`RecordingClient` / `ReplayClient`. `tests/golden/cascata_12_sementes.json`.

**O que funciona.** A camada de três níveis (unitário com `FakeLLMClient` →
replay gravado → avaliação ao vivo paga) é a arquitetura de teste certa para
sistema com LLM. O `custo_medido: bool` distinguindo "grátis" de "não medido" é
o tipo de honestidade de instrumento que quase ninguém implementa.

**O que está incompleto — e é a lacuna nº 4 do sumário.** Não existe
`EvaluationCase`, `Dataset` de avaliação persistido, `Evaluator` plugável,
`Benchmark` versionado nem detecção de regressão. `metrics.py` importa
`synth.dataset`: **a avaliação só sabe medir contra gabarito sintético**.
Correção humana (`Veredito.CORRIGIR` + `divergiu=True`) morre no JSONL da fila.
O loop do README está aberto.

**O que deve ser refatorado.** `evaluate(dataset, result)` → `Evaluator`
Protocol sobre `Run` + `ExpectedOutcome`, com o gabarito sintético como **uma**
fonte de expectativa entre duas (a outra: correção humana).

### 2.3 Um padrão que a auditoria encontrou e que precisa de nome

O repositório implementou, sem nomear, uma estratégia de durabilidade legítima:

```
execução pura + log append-only de decisões + reexecução idempotente
```

`reconcile()` é puro. As decisões humanas vivem num JSONL append-only. Retomar
uma execução parada por intervenção humana é **reexecutá-la inteira**: as regras
rodam de novo (grátis, determinísticas), o agente pula o que já tem proposta
(cache na fila), e o revisor aplica as decisões novas. O resultado converge.

Isso é *event sourcing com o estado derivado por replay total*. Para trabalho de
escala de minutos — que é o que o spec §3.2 Tier 3 diz ser o caso hoje — é
**estritamente melhor** que checkpointing: não há estado serializado para
corromper, não há versão de snapshot para migrar, e a auditoria sai de graça.

**Decisão deste plano: preservar e nomear esse padrão como `ReplayResume`,
torná-lo explícito no runtime, e adotar durable execution externa (Temporal /
Restate) somente quando o gatilho do spec §3.2 Tier 3 disparar — trabalho que
atravessa dias.** Ver ADR-09.

### 2.4 Dependências externas

`anthropic>=1.0` é a **única** dependência de runtime. `fastapi`/`uvicorn` são
extra `[api]`; `pytest`/`ruff`/`httpx` são `[dev]`; `claude-agent-sdk` é
`[assinatura]`, só para avaliação. Zero LangChain, zero pydantic no núcleo
(só nos schemas de API), zero ORM, zero banco, zero fila.

**Isto é um ativo, não uma lacuna.** A superfície de dependência mínima é o que
torna a extração barata. Nenhuma fase deste plano adiciona dependência de
runtime obrigatória.

---

## 3. Gap Analysis

Prioridade: **P0** = bloqueia outras coisas; **P1** = entrega a tese;
**P2** = entrega valor isolado; **P3** = atrás de gatilho, não fazer cedo.

### 3.1 Core

| Área | Estado atual | Target | Gap | Prio | Dependências |
|---|---|---|---|---|---|
| Agent | `Investigator`, classe única, `SYSTEM` constante de módulo | `Agent(role, system, tools, output_schema, budget, policy)` configurável | Extrair config do código | P2 | M0 (Cost fora de `agent/`) |
| Task | **não existe**; unidade é `Divergence`/`WorkItem` | `Task(id, input_schema, output_schema, resolver, retries, timeout, guardrails)` | Conceito inteiro | P2 | M0, M1 |
| Tool | `ToolContext` (5 métodos) + `TOOL_SCHEMAS` (lista paralela), despacho por `getattr` | `ToolRegistry` com schema, permissão, timeout, custo, audit | Registry real | P2 | M0 |
| Workflow | `WorkflowDefinition(id, name, stages)` — bom, sem versão | + `version`, + `policy`, + `metadata` | Campos | P1 | M0 |
| Flow | **não existe**; um `Stage`, cascata linear | Branching, roteamento, paralelismo, listeners | Grafo | P3 | M1, M3 |
| Resolver | `Resolver` Protocol — **correto**, preservar | Idem, sobre tipos genéricos | Só de-domainizar | **P0** | — |
| Execution | `reconcile()` puro, retorna `ReconcileResult` | `execute()` que emite eventos e produz `Run` | Emissão + identidade | **P0** | M0 |
| State | `WorkSet.without()` — imutável, correto | Idem, genérico, + snapshot por passo | De-domainizar | **P0** | — |
| Events | **não existe** | `Event` tipado, `EventBus`, `EventStore` append-only | Conceito inteiro | **P0** | M0 |

### 3.2 Agent capabilities

| Área | Estado atual | Target | Gap | Prio | Dependências |
|---|---|---|---|---|---|
| LLM abstraction | `LLMClient` Protocol + `AnthropicClient` + `FakeLLMClient` — **maduro** | + `ModelRouter` (fallback, roteamento por política) | Router | P2 | M3 (policy) |
| Structured output | JSON manual em `interpretar_proposta`, coerção de enum em `__post_init__` | `OutputSchema` declarativo + validação + retry | Generalizar o que já existe | P2 | M2 |
| Guardrails | Só rebaixamento de confiança sem evidência e vocabulário fechado de ação | `Guardrail` Protocol pré/pós execução | Conceito | P2 | M2 |
| Tool calling | Funciona: paralelo, `tool_result` por `tool_use_id`, erro volta ao modelo | Idem sobre registry | Nenhum funcional | P2 | M2 |
| Agent delegation | **não existe** | Agente chama agente como ferramenta | Conceito | P3 | M8 |
| Planning | **não existe** (o laço de 6 turnos é reativo) | `Planner` opcional | Conceito | P3 | M2 |
| Memory | **não existe** | Short/long/episodic/semantic via adapter | Conceito | P3 | M1 |
| Knowledge/RAG | **não existe** | `KnowledgeSource` Protocol, sem vector DB no core | Conceito | P3 | M9 |

### 3.3 Multi-agent

| Área | Estado atual | Target | Gap | Prio | Dependências |
|---|---|---|---|---|---|
| Crew | **zero** | `Crew` como `Resolver` de classe `CREW` | Conceito | P3 | M2 |
| Sequential | **existe**, via cascata de resolvers | Idem dentro de Crew | Reuso | P3 | M8 |
| Hierarchical | **zero** | Manager agent delega a workers | Conceito | P3 | M8 |
| Delegation | **zero** | Ferramenta `delegar_para(agent, task)` | Conceito | P3 | M8 |
| Agent communication | **zero** | Via `SharedContext`, nunca mensagem livre | Conceito | P3 | M8 |
| Shared context | `ToolContext` é compartilhado, mas read-only e sem escrita entre agentes | `SharedContext` versionado, escrita auditada | Conceito | P3 | M8 |

### 3.4 Reliability

| Área | Estado atual | Target | Gap | Prio | Dependências |
|---|---|---|---|---|---|
| Retries | Só no SDK (`max_retries=2`) e retry de formato no laço | `RetryPolicy` por resolver/task, com backoff e jitter | Subir para o runtime | P2 | M1 |
| Timeout | Só no SDK (`120s`) | Timeout por task, por resolver e por run | Subir para o runtime | P2 | M1 |
| Idempotency | Cache permanente na fila, **sem invalidação** (bug latente) | Chave = `(work_item, resolver_version, model, prompt_hash)` | Corrigir chave | P1 | M1 |
| Checkpointing | **não existe** | `ReplayResume` explícito + checkpoint opcional | Nomear o padrão | P2 | M1 |
| Resume | Reexecução total (funciona, não nomeada) | Idem, com `Run.resume(run_id)` | API | P2 | M1, M7 |
| Failure handling | Abstenção registrada; erro de ferramenta volta ao modelo — **maduro** | + `FailurePolicy` por task (abster / falhar / escalar) | Política | P2 | M3 |
| Human-in-the-loop | **maduro**, ver §15 | + estados de Run, SLA, atribuição | Formalizar | P1 | M1 |

### 3.5 Intelligence

| Área | Estado atual | Target | Gap | Prio | Dependências |
|---|---|---|---|---|---|
| Routing | `sorted(cascade, key=cost_class)` — estático, roda tudo | `PolicyEngine.decide(item, ctx) -> Route` | **A tese** | **P1** | M0, M1 |
| Policy engine | Ingredientes existem, ponto de decisão não | `ExecutionPolicy` declarativa, avaliada por item | **A tese** | **P1** | M0, M1 |
| Cost optimization | Cascata barata→cara + 2 orçamentos. **Já é o melhor da categoria** | + decisão por item, não só ordem | Refinar | P1 | M3 |
| Confidence | `Confidence` na `Proposal`, usada só para rebaixar | Insumo de política e de roteamento para humano | Ligar ao motor | P1 | M3 |
| Evaluation | `metrics.evaluate()` só contra gabarito sintético | `Evaluator` sobre `Run`, 2 fontes de verdade | Comparabilidade | P2 | M1, M4 |
| Benchmark | Golden de 12 sementes + `agent_eval` multi-modelo | `Benchmark` versionado, regressão, arms A/B | Gate do M8 | P2 | M6 |
| Model selection | `--model` repetível na CLI de eval | Escolha por política, alimentada por benchmark | Ligar | P2 | M3, M6 |

### 3.6 Observability

| Área | Estado atual | Target | Gap | Prio | Dependências |
|---|---|---|---|---|---|
| Traces | `TraceEvent` só dentro de `Proposal` (só o agente) | `Trace` por `Run`, cobrindo todo resolver | Unificar | P1 | M1 |
| Spans | **não existe** (lista plana de eventos) | `Span` com pai, início/fim, atributos | Conceito | P1 | M1 |
| Token usage | **maduro**: 5 componentes, incl. cache creation | Idem no kernel | Mover | **P0** | — |
| Latency | **zero** — nada mede tempo | `duration_ms` em todo span | Conceito | P1 | M4 |
| Cost | **maduro**: micro-centavos int, por resolver | Idem + por span, por run, por item | Estender | P1 | M4 |
| Tool calls | No trace do agente (arg + retorno) | Span por chamada, com custo e latência | Unificar | P1 | M4 |
| Errors | `TraceKind.ERRO` + `proposals_api_failed` | Span de erro tipado, por categoria | Estender | P1 | M4 |
| Workflow history | **não existe** (`lru_cache` de 64) | `RunStore` consultável | Conceito | **P0** | M1 |

### 3.7 Platform

| Área | Estado atual | Target | Gap | Prio | Dependências |
|---|---|---|---|---|---|
| API | 6 rotas, sem auth, sem histórico, acoplada ao benchmark | Runs, traces, eval, ingestão | Reescrever rotas de run | P1 | M1 |
| CLI | 3 entry points (`orchestrator`, `-eval`, `-grill`), argparse plano | `orchestrator {init,run,test,benchmark,trace}` | Subcomandos | P2 | M5 |
| Dashboard | Canvas de cascata + fila de revisão, vanilla, correto | + runs, traces, custo, eval | Estender, **não reescrever** | P2 | M1, M4, M6 |
| Run history | **não existe** | `RunStore` + `GET /api/runs` | Conceito | **P0** | M1 |
| Agent registry | **não existe** | Registry por entry point | Conceito | P2 | M2 |
| Tool registry | `TOOL_SCHEMAS` lista de módulo | `ToolRegistry` | Conceito | P2 | M2 |
| Secrets | `ANTHROPIC_API_KEY` no ambiente + `.env` | `SecretProvider` Protocol, env como default | Interface fina | P3 | — |
| Configuration | Kwargs de dataclass + defaults no código | `orchestrator.yaml` + overrides | Conceito | P2 | M5 |
| Multi-tenancy | **zero** (explicitamente anti-escopo) | — | **Não fazer** | P3 | 2º cliente |
| RBAC | **zero** (explicitamente anti-escopo) | — | **Não fazer** | P3 | cliente pedir |

### 3.8 Ecosystem

| Área | Estado atual | Target | Gap | Prio | Dependências |
|---|---|---|---|---|---|
| MCP | Existe **só** em `eval/assinatura.py` (`create_sdk_mcp_server` in-process, para avaliação) | `MCPToolAdapter` → `ToolRegistry` | Adapter | P3 | M2 |
| A2A | **zero** | `RemoteAgentAdapter` → `Resolver` | Adapter | P3 | M8 |
| Plugins | `CATALOGO` dict literal | Entry points `orchestrator.resolvers` / `.tools` | Registry | P2 | M2 |

### 3.9 O gap que não está em nenhuma tabela

**`Source` — a abstração de entrada.** Não há nenhuma: `build_benchmark(seed, n,
taxa)` é chamado direto por `cli.py`, por `api/app.py` e por `eval/agent_eval.py`.

Com a conciliação rebaixada a implementação de referência (§1.3), **ler OFX/CNAB
saiu do escopo** — mas o gap continua, e por um motivo que não é o produto:

1. A **identidade** de uma execução hoje é `(seed, n, taxa)`, e é ela que escopa
   a fila de decisões humanas (`dataset_id`). Um framework cujo id de execução é
   uma tupla de parâmetros de benchmark não consegue representar execução
   nenhuma que não seja um benchmark.
2. Um domínio novo (procurement, SWE) **não tem de onde receber trabalho**. Sem
   `Source`, escrever o segundo domínio exige inventar um segundo
   `build_benchmark` — que é exatamente o acoplamento se repetindo.

Portanto: **`Source` + `input_ref` são P0 (M1); parser de formato bancário real
não está no roadmap.** O gerador sintético vira a primeira implementação de
`Source` (`synth:s1-n300-t0.15`), e um `ListSource` trivial atende os domínios
esqueleto. Quem precisar de OFX escreve um `Source` de 40 linhas — que é a
promessa do framework, não uma tarefa dele.

---

## 4. Target Architecture

### 4.1 Uma distribuição, camadas impostas por teste

**Decisão contrária ao formato sugerido no pedido (`packages/`).** Para uma
pessoa ou equipe pequena, dividir em N pacotes instaláveis compra isolamento que
um teste de import já garante, e paga com N versionamentos, N changelogs, N
matrizes de CI e resolução de versão cruzada. O repositório tem hoje **uma**
dependência de runtime; multiplicar o overhead de release por oito para proteger
5.5k linhas é over-engineering do tipo que a §21 proíbe.

**A camada é o diretório. A fronteira é um teste.**

```text
src/orchestrator/
│
├── kernel/                    # NÍVEL 0 — zero imports de outros níveis
│   ├── work.py                #   WorkItem, WorkSet
│   ├── resolution.py          #   Resolution, Proposal, Evidence, Confidence
│   ├── resolver.py            #   Resolver, ResolverOutput, ResolverDescription
│   ├── cost.py                #   Cost, Budget, CostClass, price table
│   ├── policy.py              #   ExecutionPolicy, Route, PolicyDecision
│   ├── run.py                 #   Run, RunId, RunState, WorkItemState
│   ├── event.py               #   Event, EventKind, EventBus
│   ├── trace.py               #   Span, SpanKind, Trace
│   └── definition.py          #   WorkflowDefinition, Stage, StagePolicy
│
├── runtime/                   # NÍVEL 1 — importa kernel
│   ├── engine.py              #   execute(definition, work, ctx) -> Run
│   ├── context.py             #   RuntimeContext (DI tipada)
│   ├── policy_engine.py       #   avalia ExecutionPolicy por item
│   ├── reliability.py         #   retry, timeout, idempotência
│   ├── resume.py              #   ReplayResume
│   └── registry.py            #   ResolverRegistry (entry points)
│
├── storage/                   # NÍVEL 1 — importa kernel
│   ├── protocols.py           #   RunStore, EventStore, DecisionLog, CaseStore
│   ├── jsonl/                 #   implementação append-only (a de hoje)
│   └── sqlite/                #   implementação consultável (M10)
│
├── observability/             # NÍVEL 2 — importa kernel + storage
│   ├── collector.py           #   Event -> Span
│   ├── metrics.py             #   agregações (custo, latência, tokens)
│   └── otel.py                #   exportador opcional (extra [otel])
│
├── agent/                     # NÍVEL 2 — importa kernel
│   ├── agent.py               #   Agent (Resolver de classe AGENTE)
│   ├── loop.py                #   o laço de turnos (hoje Investigator._uma)
│   ├── llm.py                 #   LLMClient, LLMResponse, FakeLLMClient
│   ├── router.py              #   ModelRouter
│   ├── providers/anthropic.py #   AnthropicClient
│   ├── tools/registry.py      #   ToolRegistry, ToolSpec, ToolPermission
│   ├── output.py              #   OutputSchema, parsing, guardrails
│   └── memory/                #   protocolos + adapters (M9)
│
├── crew/                      # NÍVEL 3 — importa kernel + agent (M8)
│   ├── crew.py                #   Crew (Resolver de classe CREW)
│   ├── process.py             #   Sequential, Hierarchical
│   └── shared.py              #   SharedContext
│
├── human/                     # NÍVEL 2 — importa kernel + storage
│   ├── decision.py            #   Decision, Veredito
│   ├── reviewer.py            #   HumanReviewer (Resolver de classe HUMANO)
│   └── queue.py               #   ReviewQueue (hoje Fila, com 4 papéis separados)
│
├── evaluation/                # NÍVEL 3 — importa kernel + storage + observability
│   ├── case.py                #   EvaluationCase, ExpectedOutcome
│   ├── dataset.py             #   EvalDataset (versionado)
│   ├── evaluator.py           #   Evaluator Protocol, métricas
│   ├── benchmark.py           #   Benchmark, comparação A/B
│   ├── regression.py          #   detecção de regressão
│   └── harvest.py             #   correção humana -> EvaluationCase
│
├── domains/                   # NÍVEL 4 — importa tudo; nada importa dele
│   └── reconciliation/
│       ├── models.py          #   BankEntry, LedgerEntry (hoje models.py)
│       ├── taxonomy.py        #   DivergenceType
│       ├── money.py, dates.py, tax.py
│       ├── resolvers/         #   L1, L2, L3 (hoje matching/)
│       ├── agent/             #   prompt, ToolContext, output schema
│       ├── ingest/            #   OFX/CNAB/CSV -> WorkItem   [NOVO, P0]
│       ├── synth/             #   gerador com gabarito
│       └── workflow.py        #   default_definition
│
├── authoring/                 # NÍVEL 4 — hoje grill/
│   ├── interview.py, prompt.py, tools.py
│   ├── spec.py                #   WorkflowSpec (hoje Receita)
│   └── registry.py            #   receitas em disco
│
├── api/                       # NÍVEL 5
└── cli/                       # NÍVEL 5
```

### 4.2 Dependências permitidas — a regra, e como é imposta

```text
kernel          →  (nada)
runtime         →  kernel
storage         →  kernel
observability   →  kernel, storage
agent           →  kernel                       [+ runtime só p/ reliability]
human           →  kernel, storage
crew            →  kernel, agent
evaluation      →  kernel, storage, observability
domains/*       →  kernel, runtime, agent, human, crew, evaluation
authoring       →  kernel, runtime, domains
api, cli        →  tudo
```

**Regras absolutas:**

1. `kernel/` **nunca** importa nada fora de `kernel/`. Nem pydantic, nem
   anthropic, nem fastapi.
2. **Nenhuma camada importa `domains/`.** Se precisar, o conceito está na camada
   errada — é exatamente o defeito de hoje (`workflow/workset.py` importando
   `BankEntry`).
3. `agent/` não importa `crew/`. `crew/` importa `agent/`. Nunca o contrário.
4. `evaluation/` não importa `runtime/`: ela lê `Run` do store, não executa.

**Como é imposta.** Um teste, não um documento:

```python
# tests/arquitetura/camadas.py — a tabela é DADO, lida por vários testes
PERMITIDO: dict[str, frozenset[str]] = {
    "kernel": frozenset(),                       # não importa NADA
    "runtime": frozenset({"kernel"}),
    "storage": frozenset({"kernel"}),
    "observability": frozenset({"kernel", "storage"}),
    "agent": frozenset({"kernel", "runtime"}),
    "human": frozenset({"kernel", "storage"}),
    "crew": frozenset({"kernel", "agent"}),
    "evaluation": frozenset({"kernel", "storage", "observability"}),
    "domains": frozenset({...}),                 # ninguém importa domains
    ...
}

# tests/arquitetura/test_camadas.py — a catraca
VIOLACOES_CONHECIDAS = frozenset({("workflow.workset", "models"), ...})

def test_sem_violacao_nova():
    """Impede a arquitetura de piorar enquanto é reescrita."""
    assert {(d.de, d.para) for d in violacoes()} <= VIOLACOES_CONHECIDAS

def test_baseline_honesta():
    """Obriga o ganho a aparecer no diff, em vez de a lista só crescer."""
    assert VIOLACOES_CONHECIDAS <= {(d.de, d.para) for d in violacoes()}
```

**O extrator usa `ast.walk` sobre a árvore inteira, não só o topo do arquivo** —
obrigatório, porque a circularidade `engine ↔ definition` vive em imports
*dentro de função*, colocados lá justamente para escondê-la do interpretador, e
`agent.investigator → review.fila` só existe sob `TYPE_CHECKING`. Um extrator
que lesse só o cabeçalho não veria os dois acoplamentos mais antigos do
repositório. Há um teste que pina essa capacidade usando os dois como fixture.

Este teste é o **PR #1** do roadmap. Ele entra **verde**, com a baseline das 23
arestas de hoje — e cada PR seguinte o deixa vermelho de propósito até a
baseline encolher no mesmo commit que encolheu o acoplamento.

### 4.3 Onde cada conceito mora

| Conceito | Camada | Arquivo | Vem de hoje |
|---|---|---|---|
| `WorkItem`, `WorkSet` | kernel | `work.py` | `workflow/workset.py` (de-domainizado) |
| `Resolution` | kernel | `resolution.py` | `models.MatchResult` (generalizado) |
| `Proposal`, `Confidence`, `Evidence` | kernel | `resolution.py` | `agent/proposal.py` |
| `Resolver`, `ResolverOutput` | kernel | `resolver.py` | `workflow/resolver.py` (igual) |
| `Cost`, `Budget`, `CostClass` | kernel | `cost.py` | `agent/proposal.py` + `workflow/cost_class.py` |
| `ExecutionPolicy`, `Route` | kernel | `policy.py` | **novo** |
| `Run`, `RunState` | kernel | `run.py` | **novo** (hoje `lru_cache`) |
| `Event`, `EventBus` | kernel | `event.py` | **novo** |
| `Span`, `Trace` | kernel | `trace.py` | `agent/proposal.TraceEvent` (elevado) |
| `Checkpoint` | kernel | `run.py` | **novo**, opcional |
| `WorkflowDefinition`, `Stage` | kernel | `definition.py` | `workflow/definition.py` |
| Execução | runtime | `engine.py` | `matching/engine.reconcile` |
| `Agent` | agent | `agent.py` | `agent/investigator.py` |
| `Task` | kernel | `definition.py` | **novo** (`Stage` com 1 resolver é o caso degenerado) |
| `Tool` | agent | `tools/registry.py` | `agent/tools.py` |
| `Crew` | crew | `crew.py` | **novo** |
| `Memory` | agent | `memory/` | **novo**, adapter |
| `Knowledge` | agent | `memory/knowledge.py` | **novo**, adapter |
| `EvaluationCase` | evaluation | `case.py` | **novo** |
| Decisão humana | human | `decision.py` | `review/decision.py` (igual) |

**Nota sobre `Task`.** O pedido lista `Task` como abstração separada de `Stage`.
A auditoria diz que criar as duas seria duplicação: um `Stage` com um resolver
só **já é** uma task — o spec de composição §1.2 diz isso textualmente ("o caso
degenerado é um passo simples... não são dois conceitos; é um"). Este plano
mantém **um** conceito e dá a ele o vocabulário de `Task` onde o usuário espera
(`Task(...)` é um construtor de conveniência que devolve um `Stage`). Ver §8.2.

---

## 5. Core Domain Model

Todas as assinaturas abaixo são concretas o bastante para começar a
implementação. Onde algo já existe no repo, está marcado — e o que já existe
muda o mínimo possível.

### 5.1 `WorkItem` e `WorkSet` — a mudança que destrava tudo

**POR QUÊ.** `WorkSet(bank: list[BankEntry], ledger: list[LedgerEntry])` é a
razão pela qual nenhum segundo domínio cabe. Enquanto o kernel souber o que é um
lançamento bancário, o produto e a plataforma são a mesma coisa.

**ONDE.** `kernel/work.py`, vindo de `workflow/workset.py`.

**COMO.** Um item opaco para o kernel, tipado para o domínio:

```python
@dataclass(frozen=True)
class WorkItem:
    """Uma unidade de trabalho ainda não resolvida.

    `payload` é um dataclass congelado do domínio — BankEntry hoje, um item de
    compra ou uma issue amanhã. O kernel nunca o inspeciona: ele só move ids.
    É isso que mantém as garantias do domínio (dinheiro em int, campos
    congelados) sem que o kernel precise conhecê-las.
    """
    id: str
    kind: str          # "bank" | "ledger" para conciliação; "issue" etc.
    payload: Any       # frozen dataclass do domínio

@dataclass(frozen=True)
class WorkSet:
    items: tuple[WorkItem, ...]

    def of_kind(self, kind: str) -> tuple[WorkItem, ...]: ...
    def payloads(self, kind: str) -> tuple[Any, ...]: ...

    def without(self, resolutions: list[Resolution]) -> "WorkSet":
        """O pool sem o que estas resoluções consumiram.

        Recebe `list[Resolution]`, NUNCA `ResolverOutput` — a invariante
        "proposta não resolve" continua sendo coisa que o tipo não sabe
        expressar, exatamente como em `workset.py` hoje.
        """
```

**Por que `kind: str` e não generics (`WorkSet[T]`).** A conciliação tem **dois**
tipos de item no mesmo pool (bancário e contábil), assimétricos. `WorkSet[T]`
forçaria `T = BankEntry | LedgerEntry` e devolveria uniões que todo resolver
teria de estreitar. `kind` modela a assimetria diretamente e o domínio fornece
acessores tipados (`bank(work)`, `ledger(work)`) que fazem o estreitamento uma
vez, em um lugar. Teste de generalidade (spec de composição §1.3): Procurement e
Software Eng são de um `kind` só — o caso degenerado cabe sem forçar.

**DEPENDÊNCIAS.** Nenhuma. É a primeira mudança possível.

**IMPACTO.** Alto e contido. Toca `workset.py`, os 3 matchers, `investigator.py`,
`revisor.py`, `engine.py` e `metrics.py`. **Risco concreto:** `metrics.evaluate`
calcula falso positivo/negativo a partir de `m.bank_ids | m.ledger_ids`
(`metrics.py`); com `Resolution.item_ids` unificado, a distinção de lado passa a
vir do `WorkSet`, não do `MatchResult`. O golden de 12 sementes
(`tests/golden/cascata_12_sementes.json`) e o `85.3%` do CI são a rede: se o
número não mudar, a migração foi correta. **Se mudar, a migração está errada** —
esse é o critério de aceitação, não uma revisão de código.

### 5.2 `Resolution` e `Proposal`

```python
@dataclass(frozen=True)
class Resolution:
    """Um vínculo que RESOLVE: os itens saem do pool.

    Substitui MatchResult. `item_ids` unifica bank_ids/ledger_ids — o lado de
    cada id é recuperável do WorkSet, e manter dois campos no kernel seria
    manter conciliação no kernel.
    """
    item_ids: frozenset[str]
    produced_by: str                      # Resolver.name (identidade)
    rule: str                             # a justificativa legível
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.item_ids:
            raise ValueError("Resolution exige pelo menos um id")


@dataclass(frozen=True)
class Proposal:
    """O que um resolver PROPÕE. Nunca resolve.

    Genérica: `kind` era `tipo: DivergenceType`. O vocabulário fechado continua
    existindo, mas mora no domínio, validado pelo OutputSchema do agente.
    """
    item_id: str
    kind: str
    explanation: str
    evidence: tuple[str, ...]
    confidence: Confidence
    suggested_action: str
    cost: Cost = field(default_factory=Cost.zero)
    span_id: str | None = None            # liga a proposta ao trace

    def __post_init__(self) -> None:
        # Preservado verbatim de agent/proposal.py: confiança alta sem
        # evidência é a combinação que destrói a credibilidade mais rápido
        # que qualquer erro.
        if self.confidence is Confidence.ALTA and not self.evidence:
            raise ValueError(f"{self.item_id} declara confiança alta sem evidência")

    @staticmethod
    def abstention(item_id: str, reason: str, cost: Cost | None = None) -> "Proposal":
        """Não saber é resposta válida, e precisa ser barata de produzir."""
```

### 5.3 `Resolver` — preservado, só de-domainizado

```python
@dataclass(frozen=True)
class ResolverOutput:
    """`resolutions` e `proposals` SEPARADOS. Deliberado, preservado do repo.

    Unificar os dois num tipo com campo de status transformaria uma garantia
    de tipo numa convenção verificada, e um filtro esquecido viraria
    conciliação fantasma.
    """
    resolutions: list[Resolution] = field(default_factory=list)
    proposals: list[Proposal] = field(default_factory=list)
    cost: Cost = field(default_factory=Cost.zero)
    spans: list[Span] = field(default_factory=list)   # NOVO

class Resolver(Protocol):
    name: str
    version: str                 # NOVO: entra na chave de idempotência
    cost_class: CostClass

    def resolve(self, work: WorkSet, ctx: ResolverContext) -> ResolverOutput: ...
    def describe(self) -> ResolverDescription: ...
```

**`ctx: ResolverContext` é a única mudança de assinatura**, e substitui o
`inspect.signature` de `api/app.py`: em vez de adivinhar por nome de parâmetro
se a fábrica quer a fila, o runtime **passa** um contexto tipado que carrega
tudo (decision log, event bus, budget restante, deadline, cancel token).

### 5.4 `Cost`, `Budget`, `CostClass`

**POR QUÊ mover.** `Cost` está em `agent/proposal.py` e é importado por
`workflow/resolver.py` — o kernel dependendo do agente. `Cost` não é um conceito
de agente: `RevisorHumano` devolve `Cost.zero()` e o comentário lá diz "trabalho
humano custa, mas não em tokens — e `Cost` só mede tokens". Isso é uma lacuna
do tipo, não do revisor.

```python
class CostClass(IntEnum):
    """A ordem que impede a armadilha mais cara do produto.

    CREW entra entre AGENTE e HUMANO: uma tripulação é mais cara que um agente
    (N laços em vez de um) e mais barata que interromper uma pessoa. O valor
    numérico é o que ordena a cascata — não uma convenção que alguém segue.
    """
    REGRA = 0
    AGENTE = 1
    CREW = 2        # NOVO (M8)
    HUMANO = 3      # era 2

@dataclass(frozen=True)
class Cost:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cache_creation_tokens: int = 0
    calls: int = 0
    wall_ms: int = 0              # NOVO — latência é custo
    human_seconds: int = 0        # NOVO — trabalho humano é custo

    def microcents(self, model: str) -> int: ...
    def __add__(self, other: "Cost") -> "Cost": ...

@dataclass(frozen=True)
class Budget:
    """Tetos. `None` = sem teto, explicitamente."""
    per_item_microcents: int | None = None
    per_run_microcents: int | None = None
    per_item_ms: int | None = None
    per_run_ms: int | None = None

    def exceeded_by(self, spent: Cost, model: str) -> str | None:
        """Devolve o nome do teto estourado, ou None. Nunca levanta.

        Estourar orçamento é evento observável, não exceção — é a política
        que `Investigator.investigate` já aplica hoje, elevada ao kernel.
        """
```

**Mudança de `CostClass.HUMANO` de 2 para 3: impacto real.** `metrics.py` e
`api/app.py` usam `CostClass.AGENTE`/`REGRA` por nome, nunca por valor
numérico, e `matches_by_class` é chaveado pelo membro da enum. A varredura do
repo não encontrou nenhum literal `2` comparado a `CostClass`. A migração é
segura, mas o PR deve incluir um teste que trave a **ordem relativa**
(`REGRA < AGENTE < CREW < HUMANO`), não os valores.

### 5.5 `Run` — a entidade que falta

```python
class RunState(StrEnum):
    PENDENTE = "pendente"
    EXECUTANDO = "executando"
    AGUARDANDO_HUMANO = "aguardando_humano"   # o estado que hoje é implícito
    CONCLUIDO = "concluido"
    FALHOU = "falhou"
    CANCELADO = "cancelado"

@dataclass(frozen=True)
class Run:
    id: str                              # ULID: ordenável por tempo
    workflow_id: str
    workflow_version: str                # spec composição §4.2: execução fixa a versão
    state: RunState
    started_at: datetime                 # sempre tz-aware (Decision já exige)
    finished_at: datetime | None
    input_ref: str                       # de ONDE veio o trabalho
    resolutions: tuple[Resolution, ...]
    proposals: tuple[Proposal, ...]
    unresolved: tuple[str, ...]          # a LACUNA, declarada
    cost_by_resolver: Mapping[str, Cost]
    resolved_by_resolver: Mapping[str, int]
    policy_decisions: tuple[PolicyDecision, ...]   # POR QUE cada rota foi tomada
    trace_id: str
```

**`input_ref` é o campo que mata o acoplamento ao benchmark.** Hoje a identidade
de um "run" é `(seed, n, taxa)` (`fila.dataset_id`). Com `input_ref`, um run
sobre benchmark tem `"synth:s1-n300-t0.15"` e um run sobre dado real tem
`"file:extrato-2026-09.ofx#sha256:abc..."`. A fila de revisão passa a ser
escopada por `run.input_ref`, e a mesma decisão humana vale entre execuções
sobre a mesma entrada — que é o comportamento correto e o que o `ReplayResume`
exige.

### 5.6 `Event` — o stream

```python
class EventKind(StrEnum):
    RUN_INICIADO = "run.iniciado"
    RUN_CONCLUIDO = "run.concluido"
    RUN_FALHOU = "run.falhou"
    STAGE_INICIADO = "stage.iniciado"
    POLITICA_DECIDIU = "politica.decidiu"
    RESOLVER_INICIADO = "resolver.iniciado"
    RESOLVER_CONCLUIDO = "resolver.concluido"
    ITEM_RESOLVIDO = "item.resolvido"
    ITEM_PROPOSTO = "item.proposto"
    ITEM_ESCALADO = "item.escalado"
    LLM_CHAMADO = "llm.chamado"
    TOOL_CHAMADA = "tool.chamada"
    ORCAMENTO_ESTOURADO = "orcamento.estourado"
    HUMANO_DECIDIU = "humano.decidiu"
    ERRO = "erro"

@dataclass(frozen=True)
class Event:
    kind: EventKind
    run_id: str
    span_id: str
    parent_span_id: str | None
    at: datetime
    payload: Mapping[str, Any]
```

**Eventos são observação, não controle.** O motor não reage a eventos para
decidir o que fazer em seguida — ver ADR-02. Isso preserva a determinismo que o
golden depende.

### 5.7 Exemplo de API Python — o alvo

```python
from orchestrator import Agent, Task, Workflow, ExecutionPolicy, Budget, Tool

# --- domínio, não kernel ---
buscar = Tool.from_function(
    buscar_lancamentos,
    permission=Tool.READ_ONLY,
    timeout_s=5,
)

investigador = Agent(
    name="investigador",
    system=PROMPT_INVESTIGACAO,
    tools=[buscar, calcular_retencao, calendario_bancario],
    output_schema=PropostaDeConciliacao,      # valida e rebaixa, não confia
    budget=Budget(per_item_microcents=4_000_000),
)

conciliar = Task(
    name="conciliar lançamentos",
    cascade=[
        regra_exata(),                        # CostClass.REGRA
        regra_tolerancia(max_cents=5),        # CostClass.REGRA
        regra_agrupamento(max_group_size=4),  # CostClass.REGRA
        investigador,                         # CostClass.AGENTE
        revisor_humano(),                     # CostClass.HUMANO
    ],
    policy=ExecutionPolicy(
        budget=Budget(per_run_microcents=400_000_000),
        min_confidence_to_auto_resolve=Confidence.ALTA,
        autonomy=Autonomy.PROPOR,             # nunca aplica sozinho
        escalate_when=lambda item, ctx: ctx.value_at_risk(item) > 50_00,
    ),
)

workflow = Workflow(id="conciliacao", version="3", tasks=[conciliar])

run = workflow.run(
    work=ingest_ofx("extrato-2026-09.ofx") + ingest_csv("razao-2026-09.csv"),
)

print(run.state)                  # RunState.AGUARDANDO_HUMANO
print(run.cost_total_microcents)  # 12_400_000
print(len(run.unresolved))        # 41 itens esperando decisão

# retomar depois que um humano decidiu, sem reprocessar o que já foi resolvido
run2 = workflow.resume(run.id)
```

O `Workflow.run()` é açúcar sobre `runtime.engine.execute(definition, work,
ctx)`; `Task(...)` devolve um `Stage`. Nenhuma das duas introduz conceito novo
no kernel — elas dão à superfície pública o vocabulário que um usuário vindo de
CrewAI espera encontrar.

---

## 6. Execution Model

### 6.1 O lifecycle, mapeado ao que já existe

```text
Input (WorkItem[])                     ← NOVO: ingestão (hoje só build_benchmark)
   ↓
Run criado (id, workflow_version)      ← NOVO (hoje lru_cache)
   ↓  emite RUN_INICIADO
para cada Stage (em ordem de definição):
   ↓  emite STAGE_INICIADO
   resolvers = stage.ordered()         ← EXISTE (sorted estável por cost_class)
   para cada resolver:
      ↓
      PolicyEngine.decide(resolver, work, ctx)   ← NOVO: a tese
      ├── EXECUTAR  → segue
      ├── PULAR     → emite POLITICA_DECIDIU(motivo), próximo resolver
      └── PARAR     → sai do stage (orçamento, deadline, cancelamento)
      ↓
      reliability.run(resolver, work, ctx)       ← NOVO: timeout + retry + idem.
      ↓
      output = resolver.resolve(work, ctx)       ← EXISTE
      ↓
      validação de saída                          ← PARCIAL (só no agente hoje)
      │  - ids existem no WorkSet? (metrics.py já intersecta; sobe p/ o motor)
      │  - proposta com confiança ALTA tem evidência? (existe)
      │  - Resolution não cita id já consumido? (revisor.py já faz; sobe)
      ↓
      work = work.without(output.resolutions)     ← EXISTE (só resolutions)
      ↓  emite ITEM_RESOLVIDO / ITEM_PROPOSTO / RESOLVER_CONCLUIDO
   ↓
Run finalizado: CONCLUIDO | AGUARDANDO_HUMANO | FALHOU
   ↓  emite RUN_CONCLUIDO; RunStore.save(run)
Resultado + lacuna declarada
```

**O que muda de verdade em `reconcile()`:** três inserções (política,
confiabilidade, emissão de evento) e a validação de saída que hoje mora espalhada
em `metrics.py` e `revisor.py`. O laço em si — encolher o pool com
`without(matches)` — **não muda**.

### 6.2 Sync vs async

**Decisão: o motor permanece síncrono.** Ver ADR-01.

O código hoje é inteiramente síncrono; o único `asyncio.run` está em
`eval/assinatura.py`, isolado. Tornar o motor `async` custaria colorir toda a
cadeia (`Resolver.resolve`, os 3 matchers, o revisor, o CLI, os 449 testes) para
comprar concorrência que **nenhum caso atual precisa**: L1/L2/L3 são CPU-bound e
determinísticas; a única espera de I/O real é a chamada ao modelo, e ela já é
serial por item **de propósito**, porque o orçamento é verificado entre itens
(`investigator.investigate` checa `budget_total` antes de cada `_uma`).

Onde o paralelismo vale, ele entra **local e explícito**, sem colorir o motor:

```python
@dataclass
class ParallelResolver:
    """Adapter que roda um resolver sobre N itens em paralelo.

    Thread pool, não asyncio: o trabalho é uma chamada HTTP bloqueante por
    item, e um pool de threads dá a mesma concorrência sem async/await
    contaminar `Resolver.resolve`. O orçamento passa a ser verificado por
    lote, não por item — e essa perda de granularidade é o trade-off que
    esta classe cobra, declarado aqui em vez de descoberto na fatura.
    """
    inner: Resolver
    max_workers: int = 4
```

Gatilho para reavaliar: um workflow com dois stages independentes, ou um lote
com mais de ~500 itens indo ao agente.

### 6.3 Retries, timeout, cancelamento

| Mecanismo | Hoje | Alvo | Onde |
|---|---|---|---|
| Retry de rede | SDK, `max_retries=2` | Mantém no SDK | `providers/anthropic.py` |
| Retry de formato | `max_tentativas_formato=2` no laço | Mantém no laço do agente | `agent/loop.py` |
| Retry de resolver | **não existe** | `RetryPolicy(attempts, backoff, jitter, retry_on)` | `runtime/reliability.py` |
| Timeout de chamada | SDK, 120s | Mantém | `providers/anthropic.py` |
| Timeout de resolver | **não existe** | Deadline no `ResolverContext` | `runtime/reliability.py` |
| Timeout de run | **não existe** | `Budget.per_run_ms` | `runtime/engine.py` |
| Cancelamento | **não existe** | `ctx.cancelled` cooperativo, checado entre itens | `runtime/context.py` |

**Cancelamento cooperativo, não preemptivo.** O motor checa `ctx.cancelled`
entre itens e entre resolvers. Matar uma thread no meio de uma chamada HTTP
deixaria custo gasto e não contabilizado — e custo não contabilizado é
exatamente o que este projeto não pode ter.

### 6.4 Idempotência — corrigir o bug latente

**O defeito.** `Investigator.investigate` pula qualquer divergência que já tenha
proposta na fila. O comentário é honesto: *"É um cache permanente, sem
invalidação: uma vez na fila, a divergência nunca mais é reinvestigada, mesmo
que o prompt mude, o modelo troque ou um bug do agente seja corrigido."*

**Por que importa mais depois de M6.** Assim que a avaliação comparar modelo A
contra modelo B sobre a mesma entrada, esse cache faz a segunda medição ler as
propostas da primeira. **A avaliação mediria o cache, não o modelo.** Isso hoje
não morde porque `agent_eval` constrói um `Investigator` sem fila; morde no dia
em que o benchmark rodar sobre a fila de produção.

**A correção.**

```python
@dataclass(frozen=True)
class IdempotencyKey:
    """A identidade de um trabalho já feito.

    Inclui a VERSÃO do resolver e o hash do prompt: trocar de modelo ou
    corrigir o prompt invalida o cache automaticamente, em vez de exigir que
    alguém lembre de apagar o arquivo.
    """
    item_id: str
    resolver_name: str
    resolver_version: str
    fingerprint: str      # sha256(model + system_prompt + tool_schemas)
```

**IMPACTO.** Baixo em código, alto em confiança. Toca `investigator.py`,
`fila.py` e o formato do JSONL (campo novo, retrocompatível: registro sem
`fingerprint` é tratado como fingerprint desconhecido = cache miss, o que é o
padrão seguro).

### 6.5 Falha e compensação

**Compensação não entra.** O spec §3.2 Tier 2 já decidiu: *"Compensação /
rollback — quando uma ação for irreversível. No v1 não existe: ferramentas são
somente-leitura."* `agent/tools.py` diz o mesmo: *"TODAS são somente-leitura...
Isso elimina deste plano compensação, idempotência e rollback."*

Enquanto toda ferramenta for read-only e o único efeito colateral for gravar num
JSONL append-only, **não há o que compensar**. O gatilho está definido (escrita
em sistema de terceiro) e a costura que a acomoda é o `ToolPermission` do M2:
uma ferramenta `WRITE` exigirá declarar sua compensadora, e o `ToolRegistry`
recusará registrar uma que não declare.

### 6.6 Transições de estado

```text
                  ┌──────────┐
                  │ PENDENTE │
                  └────┬─────┘
                       ▼
                ┌─────────────┐   orçamento/deadline/erro fatal   ┌────────┐
                │ EXECUTANDO  │ ─────────────────────────────────►│ FALHOU │
                └──┬───────┬──┘                                   └────────┘
       tudo        │       │  sobrou item + há resolver HUMANO
       resolvido   │       ▼
                   │  ┌──────────────────────┐
                   │  │ AGUARDANDO_HUMANO    │◄──┐
                   │  └──────────┬───────────┘   │ decisão nova
                   ▼             │ resume()      │
            ┌────────────┐       └───────────────┘
            │ CONCLUIDO  │
            └────────────┘
```

`AGUARDANDO_HUMANO` é o estado que hoje existe **de fato mas não de nome**: é
"sobraram divergências e a cascata tem um `RevisorHumano`". Nomeá-lo é o que
permite à API responder "este run está esperando você" em vez de devolver uma
lacuna sem explicação.

---

## 7. Policy Engine

### 7.1 Por que esta é a peça central

A tese do projeto é que o sistema decide **como** o trabalho deve ser executado.
Hoje ele não decide: `Stage.ordered()` ordena e o motor roda tudo. A ordenação
por custo é uma **heurística global excelente** — é o que já entrega os 85,3% por
centavos — mas é cega ao item: uma divergência de R$ 3,00 e uma de R$ 300.000,00
recebem exatamente o mesmo tratamento e o mesmo orçamento.

O Policy Engine é a diferença entre "cascata barata→cara" e "runtime que decide".
É também o item da tabela §21 da comparação com CrewAI onde não há equivalente
do outro lado.

### 7.2 A abstração

```python
class Autonomy(IntEnum):
    """Quanto o sistema pode fazer sozinho. Ordem é significado."""
    OBSERVAR = 0    # só registra o que faria
    PROPOR = 1      # propõe; humano decide sempre        ← o modo de hoje
    AGIR_SE_SEGURO = 2  # aplica quando a política permite
    AGIR = 3        # aplica sempre

class Route(StrEnum):
    PULAR = "pular"
    EXECUTAR = "executar"
    ESCALAR = "escalar"       # manda direto para a próxima classe
    PARAR = "parar"           # encerra o stage

@dataclass(frozen=True)
class ExecutionPolicy:
    budget: Budget = Budget()
    autonomy: Autonomy = Autonomy.PROPOR
    min_confidence_to_auto_resolve: Confidence = Confidence.ALTA
    max_cost_class: CostClass = CostClass.HUMANO
    # Predicados do DOMÍNIO, injetados. O kernel não sabe o que é "valor em
    # risco" — ele só sabe chamar um Callable e registrar o resultado.
    skip_when: Callable[[WorkItem, PolicyContext], bool] | None = None
    escalate_when: Callable[[WorkItem, PolicyContext], bool] | None = None

@dataclass(frozen=True)
class PolicyDecision:
    """POR QUE o runtime fez o que fez. Vai no Run e no trace.

    Sem este registro, uma execução em que a política pulou o agente é
    indistinguível de uma em que o agente não achou nada — que é a mesma
    classe de ambiguidade que `proposals_api_failed` existe para eliminar
    em `agent_eval.py`.
    """
    item_id: str | None
    resolver_name: str
    route: Route
    reason: str
    evidence: Mapping[str, Any]
```

### 7.3 Como a decisão é tomada

Regras avaliadas **em ordem**, primeira que casa vence. A ordem é fixa e
testável — não há prioridade configurável, porque prioridade configurável é
como uma política vira inauditável:

```python
def decide(resolver, item, policy, ctx) -> PolicyDecision:
    # 1. TETO DE CLASSE — nunca suba acima do autorizado
    if resolver.cost_class > policy.max_cost_class:
        return PULAR("classe acima do teto da política")

    # 2. ORÇAMENTO — o teto é duro, e estourar é evento, não exceção
    if estourado := policy.budget.exceeded_by(ctx.spent, ctx.model):
        return PARAR(f"orçamento esgotado: {estourado}")

    # 3. DEADLINE / CANCELAMENTO
    if ctx.cancelled or ctx.past_deadline():
        return PARAR("cancelado" if ctx.cancelled else "deadline")

    # 4. AUTONOMIA — OBSERVAR nunca executa classe paga
    if policy.autonomy is Autonomy.OBSERVAR and resolver.cost_class > CostClass.REGRA:
        return PULAR("autonomia OBSERVAR")

    # 5. DISPONIBILIDADE — sem credencial, sem provider, sem revisor de plantão
    if not ctx.available(resolver):
        return PULAR(f"indisponível: {ctx.unavailable_reason(resolver)}")

    # 6. PREDICADO DE DOMÍNIO — escalar antes de gastar
    if policy.escalate_when and policy.escalate_when(item, ctx):
        return ESCALAR("predicado de escalonamento do domínio")
    if policy.skip_when and policy.skip_when(item, ctx):
        return PULAR("predicado de pulo do domínio")

    # 7. VIABILIDADE ECONÔMICA — a regra que a tese pede
    #    Não gaste US$ 0,04 para investigar uma divergência de R$ 0,30.
    if (valor := ctx.value_at_risk(item)) is not None:
        if ctx.estimated_cost(resolver) > valor * policy.max_cost_ratio:
            return PULAR(f"custo estimado excede {policy.max_cost_ratio:.0%} do valor em risco")

    return EXECUTAR("nenhuma regra impediu")
```

**Nota de desenho sobre a regra 7.** `value_at_risk` é do **domínio**
(`abs(bank_entry.amount)` na conciliação; talvez `None` em Software Eng, onde
não há valor monetário). O kernel só chama e registra. Quando devolve `None`, a
regra não se aplica — e não se aplicar é diferente de aplicar e passar, o que o
`PolicyDecision.reason` registra.

### 7.4 Exemplo de uso

```python
# Modo conservador: hoje. Nada muda no comportamento — é a política que
# descreve o que o repo já faz, e é assim que M3 entra sem quebrar o golden.
POLITICA_ATUAL = ExecutionPolicy(
    budget=Budget(per_item_microcents=4_000_000,
                  per_run_microcents=400_000_000),
    autonomy=Autonomy.PROPOR,
    max_cost_class=CostClass.HUMANO,
)

# Modo econômico: o agente só acorda quando vale a pena.
POLITICA_ECONOMICA = replace(
    POLITICA_ATUAL,
    max_cost_ratio=0.02,     # no máximo 2% do valor em risco
    skip_when=lambda item, ctx: ctx.value_at_risk(item) < 10_00,   # R$ 10,00
)

# Modo fechamento: tudo que sobrar vai para humano, sem gastar com agente.
POLITICA_FECHAMENTO = replace(POLITICA_ATUAL, max_cost_class=CostClass.REGRA)
```

### 7.5 Por que a política é comparável, não só configurável

`ExecutionPolicy` é um dataclass congelado e serializável. Isso é o que permite
o M6 tratá-la como **variável de experimento**: rodar o mesmo `EvalDataset` com
`POLITICA_ATUAL` e `POLITICA_ECONOMICA` e comparar precisão contra custo, do
mesmo jeito que `agent_eval._tabela` já compara modelos hoje. Uma política que
não é dado não é comparável — e política incomparável é opinião.

**IMPACTO no que existe.** `Stage.ordered()` **não muda**: ela continua sendo a
ordem. A política decide se cada resolver da ordem roda. As duas coisas são
ortogonais, e mantê-las ortogonais é o que impede a política de poder inverter a
ordem de custo — a invariante nº 2 da §1.5.

---

## 8. Agent / Task / Tool

### 8.1 Agent

**Estado.** Existe **um** agente: `Investigator`. Ele é bom — 423 linhas, 714 de
teste — mas é uma classe com o prompt numa constante de módulo e as ferramentas
soldadas em `ToolContext`. Não há como declarar um segundo agente sem copiar o
laço.

**A separação a fazer:** o **laço** é genérico, a **configuração** é do domínio.

```python
@dataclass(frozen=True)
class AgentSpec:
    """A configuração de um agente. Dado, não comportamento — serializável,
    versionável, e portanto comparável numa avaliação."""
    name: str
    system: str
    tools: tuple[str, ...]              # nomes no ToolRegistry
    output_schema: type[OutputSchema]
    model: str
    max_turns: int = 6
    max_format_retries: int = 2
    budget: Budget = field(default_factory=Budget)

    @property
    def version(self) -> str:
        """sha256 curto de (system, tools, output_schema, model).

        É a chave de idempotência de M7.4: mudar o prompt muda a versão, e
        mudar a versão invalida o cache — em vez de exigir que alguém lembre
        de apagar o JSONL.
        """

@dataclass
class Agent:
    """Um `Resolver` de classe AGENTE. O laço genérico + uma AgentSpec.

    O laço é EXATAMENTE o de `Investigator._uma` hoje, extraído:
    turnos, orçamento, retry de formato, execução de ferramenta com erro
    voltando ao modelo, abstenção como saída. Nenhuma linha de lógica nova
    — só a config saindo de dentro do código.
    """
    spec: AgentSpec
    client: LLMClient
    tools: ToolRegistry

    name: str = field(init=False)
    cost_class: CostClass = field(default=CostClass.AGENTE, init=False)

    def resolve(self, work: WorkSet, ctx: ResolverContext) -> ResolverOutput:
        """Nunca devolve `resolutions`: proposta não resolve.

        Preservado literalmente de `Investigator.resolve`. Um agente que
        pudesse emitir Resolution quebraria a invariante nº 1 da §1.5, e o
        tipo é o que impede.
        """
```

**Lifecycle de um agente, por item:**

```text
construção    valida modelo contra a tabela de preços e falha ALTO se ausente
              (preservado de Investigator.__post_init__ — modelo sem preço
               não é abstenção, é erro de configuração)
   ↓
por item:     monta a entrada a partir do WorkItem
   ↓
laço (n ≤ max_turns):
   ├─ complete()        captura ESTREITA só aqui → falha vira abstenção
   ├─ contabiliza custo, checa orçamento → estourou: abstenção registrada
   ├─ tem tool_call?  → executa TODAS, captura LARGA (erro volta ao modelo),
   │                     um tool_result por tool_use_id, continua
   └─ senão           → valida contra output_schema
                        ├─ válido   → Proposal
                        └─ inválido → retry de formato (máx. 2), depois abstenção
   ↓
saída:        Proposal ou abstenção. NUNCA exceção. NUNCA Resolution.
```

As duas capturas de exceção **invertidas** (estreita na chamada ao modelo, larga
na execução de ferramenta) são a decisão P2.11/P2.14 do repo e precisam
sobreviver à extração com os comentários que as explicam. Um PR que as unifique
é um PR que precisa ser recusado.

### 8.2 Task

**Decisão: `Task` é vocabulário, não conceito novo.** `Stage` já é a unidade, e
o spec de composição §1.2 diz explicitamente que passo simples e cascata "não são
dois conceitos; é um". Criar `Task` como entidade separada duplicaria estado,
duplicaria serialização e criaria a pergunta "uma task tem stages ou um stage tem
tasks?", que não tem resposta boa.

```python
@dataclass(frozen=True)
class Stage:
    name: str
    cascade: tuple[Resolver, ...]
    policy: ExecutionPolicy = field(default_factory=ExecutionPolicy)   # NOVO
    retry: RetryPolicy = field(default_factory=RetryPolicy)            # NOVO
    timeout_ms: int | None = None                                      # NOVO
    guardrails: tuple[Guardrail, ...] = ()                             # NOVO

    def ordered(self) -> list[Resolver]:
        """INALTERADO. `sorted` estável: ordem entre classes é derivada,
        ordem dentro de uma classe é a que o autor escreveu."""
        return sorted(self.cascade, key=lambda r: r.cost_class)

def Task(name, *, resolver=None, cascade=None, **kw) -> Stage:
    """Açúcar: `Task(resolver=x)` é `Stage(cascade=(x,))`.

    Existe para que quem chega do CrewAI encontre a palavra que espera, sem
    que o kernel ganhe um segundo conceito para manter em sincronia.
    """
```

| O pedido lista | Onde mora |
|---|---|
| inputs | `WorkSet` filtrado por `kind` na entrada do stage |
| outputs | `ResolverOutput` (resolutions + proposals) |
| agent | um item da `cascade` |
| dependencies | ordem dos stages em `WorkflowDefinition.stages` |
| retries | `Stage.retry` |
| timeout | `Stage.timeout_ms` |
| schema | `AgentSpec.output_schema` (agente) / tipo do payload (regra) |
| guardrails | `Stage.guardrails` |

### 8.3 Tool

**Estado.** `ToolContext` é um objeto com 5 métodos; `TOOL_SCHEMAS` é uma lista
literal ao lado; o despacho é `getattr(self.context, c.name)` cruzado com
`{s["name"] for s in TOOL_SCHEMAS}`. **São duas listas paralelas** — exatamente o
join frágil que o `CATALOGO` do grill já resolveu para resolvers (`_param()` lê o
default do próprio dataclass) e que ainda não foi aplicado a ferramentas.

```python
class ToolPermission(StrEnum):
    READ_ONLY = "read_only"
    WRITE = "write"              # exige compensadora declarada
    EXTERNAL = "external"        # sai da máquina

@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Mapping[str, Any]
    fn: Callable[..., Any]
    permission: ToolPermission = ToolPermission.READ_ONLY
    timeout_s: float = 10.0
    cost_microcents: int = 0             # ferramenta que chama API paga
    compensates: str | None = None       # obrigatório se permission is WRITE

class ToolRegistry:
    def register(self, spec: ToolSpec) -> None:
        """Recusa WRITE sem compensadora, e nome duplicado.

        A mesma disciplina de `Receita.construir`: validar é construir. Se
        registrou, dá para chamar; e se dá para chamar, o schema que o modelo
        vê veio DAQUI, não de uma lista paralela.
        """
    def schemas(self, names: tuple[str, ...]) -> list[dict]: ...
    def call(self, name, args, ctx) -> ToolResult:
        """Executa com timeout, mede latência, emite TOOL_CHAMADA.

        Erro NUNCA sobe como exceção: volta como ToolResult(error=...) para o
        modelo se corrigir. Preservado de `Investigator._executar`, que
        documenta a razão: o modelo se corrige, o processo não.
        """
```

**IMPACTO.** `TOOL_SCHEMAS` deixa de existir como lista literal: os schemas saem
do registry. `eval/assinatura.py::_montar_servidor` já reusa `TOOL_SCHEMAS`
verbatim para montar o servidor MCP — e continua funcionando, agora lendo do
registry, o que é exatamente o encaixe para o `MCPToolAdapter` do M11.

**Audit metadata.** Toda chamada emite `TOOL_CHAMADA` com nome, argumentos,
retorno, latência, custo e permissão. Hoje isso existe pela metade
(`TraceKind.TOOL` já carrega argumento **e** retorno, decisão I2), falta latência
e custo.

---

## 9. Workflow / Flow

### 9.1 Workflow: o que existe, o que falta

```python
@dataclass(frozen=True)
class WorkflowDefinition:
    id: str
    name: str
    version: str                                      # NOVO
    stages: tuple[Stage, ...]
    policy: ExecutionPolicy = ...                     # NOVO: default dos stages
    metadata: Mapping[str, str] = ...                 # NOVO
```

**`version` não é campo cosmético.** O spec de composição §4.2 exige "versão
imutável, execução fixa a versão" e §4.3 diz que "o diff é a peça que vende para
auditoria". Sem versão: (a) `Run` não consegue registrar o que executou, (b) a
avaliação não consegue comparar workflow A com B, (c) uma execução em voo durante
um deploy vira comportamento indefinido.

**Regra de versionamento:** `version` é o sha256 curto da definição serializada.
Derivado, não escrito à mão — pela mesma razão que `_param()` lê o default do
dataclass: número escrito à mão é número que desatualiza em silêncio.

### 9.2 Flow: branching, roteamento, paralelismo — **P3, com gatilho**

**Estado: zero.** Um stage, cascata linear.

**Recomendação: não construir agora, e o motivo é forte.** Um grafo com
branching resolve "o passo B roda só se A der X". A auditoria não encontrou
**nenhum** caso no repositório que precise disso: a cascata resolve "tente o
barato, depois o caro", que é uma estrutura diferente e que já cobre o domínio.
O spec §9 lista "DSL de workflow" como anti-escopo com gatilho explícito.

**Quando construir, construir assim** — sem eventos como controle:

```python
@dataclass(frozen=True)
class Stage:
    ...
    depends_on: tuple[str, ...] = ()          # nomes de stages anteriores
    when: Callable[[RunContext], bool] | None = None
```

Um DAG com `depends_on` + predicado de entrada dá branching e paralelismo entre
stages independentes, mantendo a **ordem determinística** (topological sort
estável). É estritamente menos poderoso que os `@listen`/`@router` do CrewAI
Flow, e essa é a intenção: com decorators reativos, a ordem de execução é
emergente, e o golden de 12 sementes deixa de ser possível. Determinismo é um
requisito deste produto, não um detalhe.

**Gatilho:** dois stages que precisam rodar em ordem parcial num workflow real.

### 9.3 Listeners

Existem desde M1, e são a forma **correta** de "listener": assinantes do
`EventBus`. Um listener observa; ele não decide o que roda em seguida. Ver
ADR-02.

```python
bus.subscribe(EventKind.ORCAMENTO_ESTOURADO, alertar_operador)
bus.subscribe(EventKind.ITEM_PROPOSTO, enfileirar_para_revisao)
bus.subscribe(EventKind.HUMANO_DECIDIU, colher_caso_de_avaliacao)   # M6
```

A terceira linha é a seta que falta no README, e ela custa uma assinatura.

---

## 10. Multi-Agent / Crew

### 10.1 A regra de contenção

```text
CERTO                          ERRADO
Workflow                       Crew
   └── Stage                      └── tudo
        └── Crew (um Resolver)
             └── Agents
```

`Crew` é **um `Resolver` de classe `CREW`**, e nada mais. Isso não é preferência
estética: é o que mantém as invariantes. Um Crew que fosse o topo precisaria da
sua própria noção de custo, de política, de trace e de human-in-the-loop — quatro
duplicações do que o runtime já faz. Como resolver, ele herda tudo: aparece na
cascata, é ordenado por classe de custo, tem orçamento, emite spans, e o revisor
humano continua depois dele.

### 10.2 A abstração

```python
class Process(StrEnum):
    SEQUENTIAL = "sequential"
    HIERARCHICAL = "hierarchical"

@dataclass
class Crew:
    """Vários agentes num item de trabalho. Um Resolver como qualquer outro."""
    name: str
    agents: tuple[Agent, ...]
    process: Process = Process.SEQUENTIAL
    manager: Agent | None = None            # obrigatório se HIERARCHICAL
    max_rounds: int = 3
    budget: Budget = ...                    # teto do Crew INTEIRO
    synthesizer: Agent | None = None        # quem escreve a proposta final

    cost_class: CostClass = field(default=CostClass.CREW, init=False)

    def resolve(self, work, ctx) -> ResolverOutput:
        """Devolve `proposals`, NUNCA `resolutions`.

        Um Crew é mais opinião, não mais autoridade. Se um agente sozinho não
        pode resolver (invariante nº 1), três também não podem — e deixar um
        Crew resolver seria a porta pela qual a invariante mais cara do
        projeto sairia sem ninguém notar.
        """
```

### 10.3 Os modos

**Sequential.** Agente 1 produz, agente 2 recebe o `SharedContext` com o que o 1
produziu, e assim por diante. É a cascata de novo, um nível abaixo — e por isso
reusa o mesmo laço, não um novo.

**Hierarchical.** O `manager` recebe o item, decide qual worker chamar (via
ferramenta `delegar_para`), agrega. O manager **não** executa trabalho: ele
roteia. Sem essa restrição, "hierárquico" vira "um agente grande com ferramentas
caras", que é o modo de falha mais comum desse padrão.

### 10.4 Comunicação, contexto e conflito

**Comunicação é via `SharedContext`, nunca mensagem livre.**

```python
@dataclass
class SharedContext:
    """Quadro branco versionado. Toda escrita é atribuída e auditada.

    Chat livre entre agentes é o modo mais rápido conhecido de queimar
    orçamento sem produzir nada: N agentes concordando educadamente por seis
    turnos. Com um quadro branco, uma contribuição que não muda o estado não
    custa um turno de ninguém.
    """
    entries: tuple[ContextEntry, ...]   # (author, at, key, value, span_id)

    def write(self, author: str, key: str, value: Any) -> "SharedContext": ...
    def read(self, key: str) -> tuple[ContextEntry, ...]: ...
```

**Conflito.** Dois agentes propõem tipos diferentes para o mesmo item. Três
políticas, em ordem de preferência:

1. **Abstenção por desacordo (default).** Desacordo é informação: vira uma
   proposta de baixa confiança com as duas hipóteses na evidência, e o humano
   decide. Barato, honesto, e alimenta o dataset de avaliação com um caso
   genuinamente difícil.
2. **Síntese.** Um `synthesizer` lê o `SharedContext` e escreve a proposta final.
   Custa um turno a mais.
3. **Maioria.** Só faz sentido com 3+ agentes e o mesmo esquema de saída. Barato,
   mas apaga a informação do desacordo — por isso não é o default.

**Voto ponderado por confiança declarada está explicitamente fora.** Confiança de
LLM não é calibrada; ponderar por ela dá autoridade a um número que o M6 ainda
vai medir se significa alguma coisa.

### 10.5 Por que isto é P3 e vem em M8

Nada no repositório depende de Crew. Nenhum caso de conciliação melhora com três
agentes — o gargalo medido não é raciocínio, é contexto (o agente vê uma
divergência e busca o resto por ferramenta). Construir Crew antes de M6 seria
construir uma capacidade cara **sem instrumento para saber se ela melhora
alguma coisa**. Depois de M6, a pergunta "Crew vale o custo?" vira uma linha na
tabela de benchmark em vez de uma opinião.

**Gatilho:** um caso onde um agente sozinho, com o melhor prompt e o melhor
modelo medidos, fica abaixo do alvo de precisão — e a hipótese de que múltiplas
perspectivas ajudam é testável contra o benchmark.

---

## 11. Memory / Knowledge

### 11.1 A separação, que é onde quase todo framework erra

| Camada | O que é | Escopo | Onde mora | Existe hoje? |
|---|---|---|---|---|
| **Workflow state** | `WorkSet` — o que ainda não foi resolvido | um run | `kernel/work.py` | **Sim**, maduro |
| **Short-term memory** | histórico de turnos de um item | um item | `agent/loop.py` (`mensagens`) | **Sim** |
| **Episodic memory** | o que aconteceu em runs passados | workflow | `storage/` (`RunStore`) | Parcial (a fila) |
| **Semantic memory** | fatos aprendidos, destilados | workflow | adapter | Não |
| **Structured memory** | tabelas do domínio consultáveis | domínio | `domains/*/ingest` | **Sim** (`ToolContext`) |
| **Knowledge / RAG** | documentos externos recuperáveis | global | adapter | Não |

**A confusão que esta tabela previne.** Frameworks de agente costumam vender
"memória" como uma coisa só, com um vector DB embutido. Aí o estado do workflow
(que precisa ser exato, versionado e auditável) passa a viver no mesmo lugar que
notas semânticas aproximadas, e uma busca por similaridade decide o que entra no
contexto de uma conciliação. Num produto que um contador audita linha a linha,
isso é inaceitável.

**Regra deste projeto: nada que o produto precise reproduzir exatamente pode
viver em memória aproximada.** `WorkSet`, `Decision` e `Run` são exatos,
versionados e no kernel. Memória semântica e RAG são adapters, opcionais, e o que
vem deles entra no prompt **rotulado como recuperado**, nunca como fato.

### 11.2 O que é core e o que é adapter

**No core (kernel), porque o motor não funciona sem):**
`WorkSet` · `Run` · `Decision` · `SharedContext` · `Span`

**Protocolo no core, implementação fora:**

```python
class MemoryStore(Protocol):
    """Sem menção a embedding, vetor, índice ou coleção — de propósito.

    Amarrar o core a um vector DB é a armadilha que a §21 nomeia. Este
    protocolo é satisfeito por um dict em memória, um SQLite com FTS5 e um
    Qdrant, e o kernel não sabe a diferença.
    """
    def remember(self, scope: str, key: str, value: Any, tags: Mapping[str, str]) -> None: ...
    def recall(self, scope: str, query: str, limit: int) -> list[MemoryHit]: ...
    def forget(self, scope: str, key: str) -> None: ...

class KnowledgeSource(Protocol):
    def search(self, query: str, limit: int) -> list[Passage]: ...

@dataclass(frozen=True)
class Passage:
    """Todo trecho recuperado carrega a FONTE.

    Sem `source`, uma proposta cita uma passagem que ninguém consegue
    verificar — que é o oposto do produto. `evidencia` já tem essa disciplina
    na Proposal de hoje: ids e valores que o agente de fato consultou.
    """
    text: str
    source: str
    score: float
```

**Implementações, em ordem de adoção:**
1. `InMemoryStore` — para teste. Primeira e obrigatória.
2. `SQLiteStore` com FTS5 — zero dependência nova, resolve a maioria dos casos.
3. `VectorStore` adapter — só atrás do extra `[memory-vector]`, quando houver um
   caso medido em que FTS5 perde.

**Ninguém adota (3) antes de medir (2) contra o benchmark.** É a mesma disciplina
de escolher modelo por medição em `agent_eval.py`.

### 11.3 A memória que este projeto já tem e não chama assim

A `Fila` é **memória episódica com gabarito humano**: um log append-only de
`(proposta do agente, decisão do humano, se divergiram)`. É o insumo mais valioso
que o sistema produz, e hoje ele só serve para aplicar decisões.

Em M6 ela ganha o segundo consumidor (`harvest` → `EvaluationCase`). Em M9, um
terceiro: memória semântica destilada — *"para este fornecedor, diferença de
4,65% é sempre CSLL/PIS/COFINS, confirmado por humano 23 vezes"*. Isso é
recuperado como contexto e **rotulado como histórico**, nunca como regra; se
virar regra, vira um `Resolver` de classe `REGRA`, que é grátis e auditável.

**Esse é o caminho de graduação que a arquitetura deve tornar natural:**

```text
agente propõe  →  humano confirma N vezes  →  memória semântica
                                           →  regra determinística (grátis)
```

Cada passo desce uma classe de custo. Um runtime que orquestra trabalho deveria
ficar mais barato com o tempo, e este é o mecanismo concreto pelo qual isso
acontece.

---

## 12. Reliability

### 12.1 O que já é confiável, e por quê

Vale registrar antes de listar lacunas, porque a tentação de "adicionar
confiabilidade" costuma destruir o que já existe:

- **O agente nunca derruba o lote.** JSON quebrado, tipo inventado, ferramenta
  inexistente, orçamento estourado, turnos esgotados, API caída — tudo vira
  abstenção **registrada**, com o motivo no trace. Um investigador que estoura no
  meio de um fechamento derruba o processo inteiro por causa de um item.
- **Erro de ferramenta volta ao modelo como texto**, nunca como exceção. O modelo
  se corrige; o processo não se recupera de um estouro.
- **Config inválida falha alto, na construção.** Tolerância negativa, grupo < 2,
  teto < grupo, `max_turns < 1`, orçamento negativo, modelo sem preço: todos
  levantam em `__post_init__`. Nenhum degrada em silêncio.
- **Decisão obsoleta vira silêncio, não erro.** `RevisorHumano` descarta decisão
  cujos ids saíram do pool, com tudo-ou-nada para não fabricar vínculo parcial.
- **Um arquivo corrompido não derruba a listagem inteira**, mas também não some
  em silêncio: `listar_receitas` e `listar_workflows` isolam e escrevem em stderr.

Esses cinco padrões são a definição operacional de confiabilidade neste projeto e
devem ser **replicados** nas camadas novas, não substituídos por um framework de
retry genérico.

### 12.2 O que falta

| Lacuna | Risco hoje | Onde entra |
|---|---|---|
| Timeout por resolver | Um matcher patológico (L3 com pool grande) trava o run | `runtime/reliability.py`, M1 |
| Retry por resolver | Falha transitória de I/O em regra = item vira divergência sem motivo registrado | idem |
| Cancelamento | Impossível abortar um lote caro em andamento | `ResolverContext.cancelled`, M1 |
| Chave de idempotência | Cache permanente sem invalidação (§6.4) | `human/queue.py`, M1 |
| Validação de saída no motor | `metrics.py` intersecta ids fantasma; o **motor** não | `runtime/engine.py`, M1 |
| Estado de run | Falha no meio deixa nada persistido | `RunStore`, M1 |

**A mais importante é a validação de saída no motor.** Hoje `metrics.evaluate`
comenta: *"um resolver com bug — ou hostil — pode devolver ids que não existem no
dataset; sem intersectar, esses ids fantasma inflam o numerador sem limite e a
taxa passa de 1.0."* A guarda existe **na métrica**, não no motor. Um resolver de
terceiro (que é o objetivo declarado: catálogo extensível, plugins) pode hoje
corromper o `WorkSet` e só a métrica percebe. Isso sobe para
`runtime/engine.py`, imediatamente depois de `resolver.resolve()`:

```python
def _validar(saida: ResolverOutput, work: WorkSet, resolver: Resolver) -> None:
    """Falha ALTO. Um resolver que devolve id fantasma tem bug, e continuar
    com o resultado é propagar o bug para dentro do estado do run."""
    conhecidos = {i.id for i in work.items}
    for r in saida.resolutions:
        if fantasma := (r.item_ids - conhecidos):
            raise ResolverContractError(
                f"{resolver.name} devolveu ids fora do WorkSet: {sorted(fantasma)}"
            )
```

### 12.3 `RetryPolicy`

```python
@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 1                       # 1 = sem retry. Default conservador.
    backoff_ms: int = 250
    multiplier: float = 2.0
    jitter: bool = True
    retry_on: tuple[type[Exception], ...] = (TimeoutError, ConnectionError)

    def __post_init__(self) -> None:
        # Mesma disciplina do resto do repo: config que não faz nada e não
        # avisa é armadilha. attempts=0 nunca executaria o resolver.
        if self.attempts < 1:
            raise ValueError(f"attempts precisa ser pelo menos 1: {self.attempts}")
```

**`retry_on` é explícito e estreito de propósito.** Retry cego sobre `Exception`
transformaria um bug do resolver em três bugs do resolver, e a suíte continuaria
verde — a mesma classe de falha que a captura estreita em volta de
`client.complete()` já previne no agente.

**Retry de resolver caro é retry de dinheiro.** Um `Agent` com `attempts=3`
pode triplicar a conta. Por isso: `RetryPolicy` para resolver de classe `AGENTE`
ou acima **verifica o orçamento antes de cada tentativa**, e o custo da tentativa
falha é contabilizado (ele foi gasto). O teste que trava isso é obrigatório no PR.

### 12.4 Idempotência de ingestão

O spec §3.2 lista "Idempotência de ingestão — reprocessar o mesmo extrato não
pode duplicar nada" como Tier 1, e ela **não existe**, porque a ingestão não
existe. Quando entrar (M1), a regra é simples e não precisa de máquina nova:

```python
def item_id(source_ref: str, natural_key: str) -> str:
    """Id determinístico a partir da fonte e da chave natural do registro.

    Reprocessar o mesmo arquivo produz os MESMOS ids, então as decisões
    humanas já tomadas continuam casando. É o que faz `ReplayResume`
    funcionar sobre dado real, e não só sobre benchmark de semente fixa.
    """
    return f"{source_ref}:{natural_key}"
```

### 12.5 `ReplayResume` — o padrão, formalizado

```python
def resume(run_id: str, ctx: RuntimeContext) -> Run:
    """Retoma reexecutando, não restaurando snapshot.

    Pré-condições que tornam isso correto, e que são propriedades do
    sistema, não boas intenções:
      1. Resolvers de classe REGRA são puros e determinísticos.
      2. Resolvers de classe AGENTE são idempotentes por IdempotencyKey.
      3. Decisões humanas vivem num log append-only.
      4. A entrada é reproduzível por `input_ref` (id determinístico).

    Consequência: o custo de retomar é o custo dos resolvers de classe REGRA
    (zero) mais o dos itens que AINDA não têm proposta. Não há estado
    serializado para corromper nem versão de snapshot para migrar.

    Quando (1) ou (2) deixar de valer — trabalho com efeito colateral, ou
    itens demais para reexecutar em tempo aceitável — o gatilho de durable
    execution externa disparou. Ver ADR-09.
    """
```

**O teste que prova o padrão** (e que é o critério de aceitação de M7):
executar → decidir três itens → `resume()` → o resultado é idêntico a executar do
zero com as três decisões já no log. Se divergir, alguma das quatro
pré-condições quebrou, e o teste diz qual.

---

## 13. Observability

### 13.1 O modelo

```python
class SpanKind(StrEnum):
    RUN = "run"
    STAGE = "stage"
    POLICY = "policy"
    RESOLVER = "resolver"
    LLM = "llm"
    TOOL = "tool"
    HUMAN = "human"
    ITEM = "item"

@dataclass(frozen=True)
class Span:
    id: str
    parent_id: str | None
    trace_id: str
    kind: SpanKind
    name: str
    started_at: datetime
    duration_ms: int
    status: Literal["ok", "erro", "abstencao", "pulado"]
    cost: Cost
    attributes: Mapping[str, Any]
    error: str | None = None
```

Hierarquia de uma execução real:

```text
run  conciliacao@v3                     12.4s   US$ 0,1240
├── stage  conciliar lançamentos        12.4s
│   ├── policy  L1                        0ms   EXECUTAR
│   ├── resolver  L1        REGRA        84ms   US$ 0      resolveu 247
│   ├── policy  L2                        0ms   EXECUTAR
│   ├── resolver  L2        REGRA        31ms   US$ 0      resolveu 18
│   ├── policy  L3                        0ms   EXECUTAR
│   ├── resolver  L3        REGRA       902ms   US$ 0      resolveu 11
│   ├── policy  investigador              1ms   EXECUTAR
│   ├── resolver  investigador AGENTE   11.2s   US$ 0,1240
│   │   ├── item  d-b-b00042           1.4s    US$ 0,0180
│   │   │   ├── llm    turno 1          0.8s    US$ 0,0090  in 1203 out 88
│   │   │   ├── tool   buscar_lancamentos 3ms   US$ 0
│   │   │   ├── llm    turno 2          0.6s    US$ 0,0090  in 1502 out 140
│   │   │   └── outcome RETENCAO_IMPOSTO  confiança=ALTA  evidências=3
│   │   └── item  d-l-l00311           1.1s    US$ 0,0140  → abstenção
│   ├── policy  revisor                   0ms   EXECUTAR
│   └── resolver  revisor    HUMANO       2ms   US$ 0      resolveu 4
└── gap  41 itens  R$ 18.402,55  AGUARDANDO_HUMANO
```

Isso é a tela do dashboard (§17) e também o `orchestrator trace <run-id>` (§16).

### 13.2 O que cada execução passa a expor

| Métrica | Hoje | Depois |
|---|---|---|
| latência | **nada** | `duration_ms` em todo span |
| tokens in/out | por resolver | por span |
| cached / cache creation | por resolver | por span |
| custo (µ¢) | por resolver | por span, item, resolver, stage, run |
| modelo | no `EvalResult` | atributo de todo span LLM |
| tool calls | no trace da proposta | span próprio, com latência e erro |
| retries | **nada** | contador no span do resolver |
| erros | `TraceKind.ERRO` | `Span.status` + `Span.error`, por categoria |
| confiança | na proposta | atributo do span de outcome |
| decisão de política | **nada** | span `POLICY` com `route` e `reason` |
| avaliação | separada | atributo pós-fato no span de outcome (M6) |

**O span `POLICY` com custo zero e duração ~0 parece desperdício e não é.** Ele
é o registro de *por que o runtime não gastou dinheiro* — a informação que
diferencia "o agente não achou nada" de "a política não deixou o agente rodar".
Sem ele, a decisão mais valiosa do sistema é a única que não deixa rastro.

### 13.3 Como os spans são produzidos

**Pelo motor, a partir do `EventBus`. Não por decorator, não por monkey-patching,
não por context manager espalhado pelo código de domínio.**

```python
# observability/collector.py
class SpanCollector:
    """Assina o EventBus e monta a árvore de spans.

    O domínio NUNCA importa daqui. Um resolver não sabe que está sendo
    observado — ele emite eventos pelo ctx, e a observabilidade é um
    assinante. É o que permite testar todo resolver sem instrumentação e
    desligar a observabilidade inteira sem tocar em lógica.
    """
```

**Migração do `TraceEvent` que já existe.** `Proposal.trace: list[TraceEvent]`
continua existindo por compatibilidade, mas passa a ser **derivado** dos spans do
item, não uma segunda fonte. Duas fontes de verdade sobre o que aconteceu numa
investigação é exatamente o drift que `definition.py` já recusa para a definição
de workflow ("nunca uma descrição paralela ao motor").

### 13.4 OpenTelemetry

**Adapter opcional, nunca modelo interno.** Ver ADR-08.

```python
# observability/otel.py — extra [otel]
def export(span: Span, tracer) -> None:
    """Mapeia Span -> OTel. Mão única.

    O modelo interno NÃO é OTel porque:
      - Custo em micro-centavos int não tem lugar canônico em OTel; viraria
        atributo float, e ponto flutuante em dinheiro é proibido aqui.
      - `status="abstencao"` e `status="pulado"` não são OK nem ERROR: são
        desfechos legítimos que o produto precisa contar separadamente.
      - Depender de OTel no kernel adicionaria dependência de runtime a um
        pacote que hoje tem uma.
    """
```

Quem quiser Langfuse, Phoenix ou Braintrust escreve um exportador de 40 linhas
sobre `Span`. Quem não quiser não instala nada.

---

## 14. Evaluation e Benchmarking

> **Revisada em 2026-09-16 pela decisão de §1.3.** Na primeira versão esta era
> "a seção mais importante do plano", porque o README chama o conjunto de
> avaliação de ativo de longo prazo que acumula correção humana de produção ao
> longo de meses. **Com a conciliação rebaixada a fixture, não há produção de
> onde colher** — o argumento do fosso caiu junto com o produto, e a fase desceu
> de M4 para M6 (§1.4).
>
> O que sobra continua valendo, e é substancial: um framework precisa poder
> responder "o prompt B é melhor que o A?", "a política econômica perde
> precisão?", "o crew vale o custo?". Sem isso, M8 (Crew) vira opinião. A
> mecânica de colheita de correção humana fica desenhada e implementada — ela
> passa a servir a quem usar o framework com um produto de verdade, que é o
> propósito de um framework.

### 14.1 O loop, e onde ele está cortado

```text
Production execution          ✅ existe (reconcile + Proposal)
        ↓
Human correction              ✅ existe (Decision, e `divergiu` já é calculado)
        ↓
Evaluation case               ❌ NÃO EXISTE  ← o corte
        ↓
Benchmark dataset             🟡 existe só sintético (synth/ + golden)
        ↓
Model / prompt / policy eval  🟡 existe só para modelo (agent_eval)
        ↓
Regression detection          🟡 existe só binário (golden + piso de 78%)
```

**O corte é de uma seta.** `api/app.py::_item` já calcula
`divergiu = decisao.tipo is not proposta.tipo or decisao.conciliar_com != ids` e
o schema já documenta: *"é o sinal de treino do §4.7 do spec pai, exposto sem
máquina nova."* O sinal é computado, exibido na tela, e **descartado**.

### 14.2 As abstrações

```python
@dataclass(frozen=True)
class ExpectedOutcome:
    """O que deveria ter acontecido com um item. Vale para as DUAS fontes."""
    kind: str | None                      # tipo esperado (None = "não sei")
    should_resolve_deterministically: bool
    resolves_with: frozenset[str] = frozenset()
    note: str = ""

class Provenance(StrEnum):
    SINTETICO = "sintetico"     # gabarito do gerador — existe desde o plano 1
    HUMANO = "humano"           # correção de revisor — a fonte nova
    ESPECIALISTA = "especialista"  # curado à mão

@dataclass(frozen=True)
class EvaluationCase:
    """Um caso: a entrada, o esperado, e de onde a verdade veio.

    `input_snapshot` carrega os payloads dos itens, não uma referência ao
    dataset. Deliberado: um caso colhido da produção precisa sobreviver ao
    arquivo que o originou e à semente que o gerou. É a correção direta do
    acoplamento `dataset_id(seed, n, taxa)` — um caso que só existe enquanto
    a semente existir não é um ativo.
    """
    id: str
    input_snapshot: tuple[WorkItem, ...]
    expected: ExpectedOutcome
    provenance: Provenance
    created_at: datetime
    source_run_id: str | None = None
    tags: frozenset[str] = frozenset()

@dataclass(frozen=True)
class EvalDataset:
    id: str
    version: str                          # sha256 dos ids dos casos
    cases: tuple[EvaluationCase, ...]

class Evaluator(Protocol):
    """Compara um Run contra os casos. Plugável por dimensão."""
    name: str
    def evaluate(self, run: Run, dataset: EvalDataset) -> EvalMetrics: ...

@dataclass(frozen=True)
class BenchmarkArm:
    """Uma variante a comparar. É aqui que 'sem contaminar o runtime' mora."""
    label: str
    workflow: WorkflowDefinition          # prompt/agente/resolver variam AQUI
    policy: ExecutionPolicy
    model: str | None = None

@dataclass(frozen=True)
class BenchmarkResult:
    dataset_version: str
    arms: tuple[tuple[BenchmarkArm, EvalMetrics], ...]
    at: datetime
```

### 14.3 A colheita — a seta que faltava

```python
# evaluation/harvest.py
def harvest(proposal: Proposal, decision: Decision, run: Run) -> EvaluationCase | None:
    """Transforma uma decisão humana em caso de avaliação.

    Vale para os três vereditos, e cada um vale por um motivo diferente:
      - CORRIGIR : o humano afirmou um tipo diferente. É o sinal mais forte,
                   e é negativo — o caso que o agente errou.
      - REJEITAR : a hipótese estava errada. Ensina a abster.
      - ACEITAR  : confirmação. Vira caso de REGRESSÃO — o que hoje acerta e
                   não pode parar de acertar.

    Colher só CORRIGIR daria um dataset só de fracassos, e um benchmark que
    só tem casos difíceis não detecta regressão no caso fácil.
    """
```

**Assinatura de evento, uma linha:**

```python
bus.subscribe(EventKind.HUMANO_DECIDIU,
              lambda e: case_store.add(harvest(...)))
```

**Contaminação, e como é evitada.** Um caso colhido de um run é usado para avaliar
runs **futuros**, nunca o run que o originou — isso é garantido por
`EvaluationCase.created_at > run.started_at` ser condição de exclusão no
`Benchmark`. Sem essa guarda, o benchmark mediria memorização.

### 14.4 O que se compara, e como

Toda comparação é: **fixar o dataset, variar um `BenchmarkArm`, medir.** O
runtime não sabe que está sendo avaliado.

| Comparação | O que varia no arm | Já é possível hoje? |
|---|---|---|
| modelo A × B | `arm.model` | **Sim** (`agent_eval --model`) |
| prompt A × B | `AgentSpec.system` (muda a `version`) | Não |
| política A × B | `arm.policy` | Não |
| estratégia de resolver | `L2(max_cents=5)` × `L2(max_cents=20)` | Não (mas `Receita` já parametriza) |
| agente × crew | resolver diferente na cascata | Não |
| cascata A × B | `arm.workflow` inteiro | Não |

**A propriedade que torna isso barato:** `BenchmarkArm` contém uma
`WorkflowDefinition` e uma `ExecutionPolicy`, ambas dataclasses congelados e
serializáveis. Comparar duas cascatas é construir duas definições e rodar o mesmo
dataset — o que o `grill` **já faz** para produzir uma (`construir(receita)`) e o
que `agent_eval.avaliar` **já faz** para rodar uma. M6 é, em grande medida,
costurar duas peças existentes.

### 14.5 Métricas e detecção de regressão

```python
@dataclass(frozen=True)
class EvalMetrics:
    # Qualidade — as definições de metrics.py preservadas
    deterministic_rate: float
    resolution_rate: float
    false_positives: int         # SOBREPOSIÇÃO (decisão 24, preservada)
    false_negatives: int         # CONTENÇÃO TOTAL (decisão 24, preservada)
    proposal_precision: float
    abstention_rate: float
    # Custo — a dimensão que quase nenhum framework mede
    microcents_total: int
    microcents_per_item: int
    microcents_per_correct_proposal: int   # NOVO: a métrica que decide modelo
    # Operação
    p50_latency_ms: int
    p95_latency_ms: int
    escalation_rate: float                 # % que foi para humano
    api_failures: int                      # preservado de EvalResult
```

`microcents_per_correct_proposal` é a métrica que o produto precisa e que hoje
não existe: um modelo mais barato com metade da precisão **não** é mais barato.

```python
@dataclass(frozen=True)
class RegressionCheck:
    """Compara contra a linha de base e falha o CI.

    Por MÍNIMO entre sementes, não por média — preservado da decisão 26:
    'um teste de regressão precisa pegar ALGUMA semente colapsar, não a
    média deslizar; a média esconde exatamente o caso que interessa.'
    """
    baseline: BenchmarkResult
    max_precision_drop: float = 0.05
    max_cost_increase: float = 0.20
    zero_tolerance: tuple[str, ...] = ("false_positives",)
```

### 14.6 Como isso encaixa no CI que já existe

O job `conciliador` do CI já trava `85.3%`, `Falsos positivos: 0` e
`Falsos negativos: 0` com `grep` na saída da CLI. **Essa é a forma primitiva do
`RegressionCheck`** e ela funciona. M6 não a substitui: adiciona um segundo job
que roda o `EvalDataset` acumulado (as partes que não gastam dinheiro — regras e
replay) e falha nos mesmos critérios. O job pago (`agent_eval` ao vivo) roda sob
demanda, nunca em cada push, pela mesma razão que a API não gasta dinheiro.

---

## 15. Human-in-the-Loop

### 15.1 O que já existe é melhor do que o pedido

O desenho pedido é:

```text
Agent → Proposal → Evidence → Confidence → Human {approve, reject, correct}
```

O repositório implementa **exatamente isso**, com nomes diferentes e com detalhes
que o desenho não menciona e que são onde o valor está:

| Desenho | No repo | Além do pedido |
|---|---|---|
| Proposal | `Proposal` | não resolve — garantido pelo tipo |
| Evidence | `Proposal.evidencia` | confiança ALTA sem evidência levanta |
| Confidence | `Confidence` | rebaixa automático quando falta evidência |
| approve | `Veredito.ACEITAR` | recusa 422 se a ação do agente é malformada |
| reject | `Veredito.REJEITAR` | |
| correct | `Veredito.CORRIGIR` | exige `tipo`; valida ids contra o dataset |
| — | `divergiu` | sinal de treino calculado |
| — | append-only JSONL | trilha de auditoria de graça |
| — | decisão obsoleta | tudo-ou-nada, silêncio em vez de vínculo fantasma |

**O que M7 faz não é construir HITL. É dar nome a estados e tirar quatro papéis
de uma classe.**

### 15.2 Pausar e retomar

**Como funciona hoje (e funciona):** não há "pausa". Um item sem decisão
simplesmente não sai do pool e reaparece como lacuna. A "retomada" é reexecutar,
e converge porque regras são puras e o agente é idempotente.

**O que falta é vocabulário, não mecanismo:**

```python
run = workflow.run(work=itens)
assert run.state is RunState.AGUARDANDO_HUMANO      # NOVO: hoje é implícito
assert len(run.pending_review) == 41                 # NOVO: hoje é a "lacuna"

# ... humano decide na UI; cada decisão emite HUMANO_DECIDIU e é gravada ...

run2 = workflow.resume(run.id)                       # NOVO: hoje é rodar de novo
assert run2.state is RunState.CONCLUIDO
assert run2.cost_delta_microcents == 0               # regras são grátis
```

`resume()` é literalmente reexecução com o mesmo `input_ref` e o log de decisões
acumulado. A linha `cost_delta == 0` é a propriedade que torna isso barato e é o
teste que a fixa.

### 15.3 A refatoração da `Fila`

`Fila` acumula quatro papéis. Separá-los é o que permite cada um evoluir:

```python
class ProposalStore(Protocol):     # idempotência do agente
    def get(self, key: IdempotencyKey) -> Proposal | None: ...
    def put(self, key: IdempotencyKey, p: Proposal) -> None: ...

class DecisionLog(Protocol):       # trilha de auditoria append-only
    def append(self, d: Decision) -> None: ...
    def latest(self, item_id: str) -> Decision | None: ...
    def all(self) -> Iterator[Decision]: ...

class ReviewQueue(Protocol):       # o que espera humano
    def pending(self, run_id: str) -> list[ReviewItem]: ...
    def assign(self, item_id: str, to: str) -> None: ...   # M7
```

**A implementação continua sendo o mesmo JSONL append-only.** Os três protocolos
são satisfeitos por uma classe `JsonlQueue` com a mesma semântica de hoje
(primeira proposta vence, última decisão vence). A separação é de **interface**,
para que o dia de trocar por SQLite não seja o dia de reescrever o revisor.

**A mudança que de fato quebra compatibilidade:** o escopo passa de
`(workflow_id, dataset_id(seed,n,taxa))` para `(workflow_id, input_ref)`. Para
runs sintéticos, `input_ref == "synth:s1-n300-t0.15"` — que é a string de hoje
com prefixo. Um script de migração de 15 linhas reescreve os JSONL existentes;
como `data/` não é versionado, o alcance é a máquina do desenvolvedor.

### 15.4 Autonomia — o eixo que o Policy Engine controla

```text
OBSERVAR         registra o que faria; nunca chama modelo pago
PROPOR           propõe; humano decide sempre            ← o modo de hoje
AGIR_SE_SEGURO   aplica quando confiança ≥ limiar E valor < teto E ferramenta é read-only
AGIR             aplica sempre
```

**`AGIR_SE_SEGURO` é o único degrau que muda o produto,** e ele tem uma
pré-condição não negociável: só pode existir depois que o benchmark de M6
mostrar, com casos colhidos de produção, qual é a precisão real por faixa de
confiança. Ligar auto-resolução com base numa confiança **autodeclarada por um
LLM e nunca medida** é o jeito mais rápido de destruir a credibilidade do
produto — que é o mesmo risco que `Proposal.__post_init__` já protege no
pequeno.

**Portanto: `AGIR_SE_SEGURO` é bloqueado por gatilho em M6, não agendado.** O
default do produto continua `PROPOR`, que é o que o README chama de "a frase que
resume a fatia inteira: decisão é o que resolve; proposta nunca resolve".

### 15.5 Durable execution — a fronteira

O spec §3.2 Tier 3 já decidiu: *"ao atingir o Tier 3, adotar Temporal, Restate
ou DBOS. Não construir."* Este plano concorda e acrescenta **onde** a costura
fica:

```python
class Executor(Protocol):
    """A fronteira de durabilidade. Hoje in-process; amanhã, talvez, não.

    O motor chama `submit`; ele não sabe se a execução acontece nesta thread
    ou num worker Temporal. É a interface `Executor` que o spec §3.3 já
    declarou e que ainda não tem implementação porque só há uma.
    """
    def submit(self, definition, work, ctx) -> Run: ...

class InProcessExecutor:   # M1 — o de hoje, nomeado
class TemporalExecutor:    # só quando o gatilho disparar
```

**Gatilho explícito:** trabalho que atravessa dias, ou lote grande o bastante
para que reexecutar custe mais do que persistir estado. Enquanto conciliação levar
minutos, `ReplayResume` é estritamente melhor: sem estado serializado, sem
migração de snapshot, auditoria de graça.

---

## 16. CLI / SDK / DX

### 16.1 Estado

Três entry points independentes, cada um com `argparse` plano:
`orchestrator` (benchmark + reconcile + métricas), `orchestrator-eval`
(avaliação paga multi-modelo), `orchestrator-grill` (entrevista → receita).

`grill/cli.py` documenta por que são separados: *"Entrada separada, não
subcomando de `orchestrator`: o `main()` de lá é argparse plano e introduzir
subcomandos quebraria a invocação de hoje sem ganho."* Isso estava certo com
três comandos. Com dez, deixa de estar.

### 16.2 O alvo

```bash
orchestrator init my-project          # scaffold
orchestrator run <workflow> [--input ...] [--policy ...] [--dry-run]
orchestrator resume <run-id>
orchestrator runs [--workflow ...] [--state ...] [--since ...]
orchestrator trace <run-id> [--item ...] [--format tree|json|otel]
orchestrator cost <run-id> [--by resolver|item|model]
orchestrator review [<run-id>]        # fila no terminal
orchestrator test                     # suíte local, sem gastar
orchestrator benchmark [--arms a,b] [--dataset ...]   # GASTA DINHEIRO
orchestrator eval harvest             # colhe decisões humanas em casos
orchestrator workflow list|show|new   # `new` é a entrevista de hoje
```

**Compatibilidade.** `orchestrator --seed 1 --n 500` está travado no CI
(job `conciliador`, com `grep` na saída). O despachante mantém a forma antiga
como alias explícito enquanto o CI a exigir:

```python
def main(argv=None) -> int:
    """Se o primeiro argumento começa com `-`, é a invocação legada
    (`orchestrator --seed 1 --n 500`) e vai para o comando `run` do
    conciliador. É o que mantém o job `conciliador` do CI verde durante toda
    a migração, em vez de exigir que ele mude no mesmo PR que o CLI."""
```

`orchestrator-eval` e `orchestrator-grill` viram aliases finos de
`orchestrator benchmark` e `orchestrator workflow new`, e continuam no
`[project.scripts]` até o M5 fechar.

**Disciplina de gasto no CLI, preservada.** `orchestrator-eval` hoje imprime
"GASTA DINHEIRO" no cabeçalho. Todo comando que pode chamar modelo pago mantém
isso, e `--dry-run` fica disponível em todos eles: um `run` com `--dry-run` usa
`Autonomy.OBSERVAR`, que a política garante nunca chamar classe acima de `REGRA`.

### 16.3 Estrutura de projeto

```text
my-project/
├── orchestrator.yaml          # config: providers, storage, defaults
├── agents/
│   └── investigador.py        # AgentSpec
├── tools/
│   └── financeiro.py          # @tool
├── workflows/
│   └── conciliacao.py         # Workflow(...)
├── domain/
│   ├── models.py              # os dataclasses congelados do payload
│   └── ingest.py              # arquivo -> WorkItem
├── evaluations/
│   ├── cases/                 # EvaluationCase colhidos (versionados!)
│   └── datasets/
├── tests/
└── data/                      # runs, filas, traces (NÃO versionado)
```

**Diferença deliberada do scaffold do CrewAI:** existe uma pasta `domain/`. O
scaffold do CrewAI é `agents.yaml` + `tasks.yaml`, porque lá o domínio é o texto
do prompt. Aqui o domínio é código tipado, e a pasta existe para dizer, na
estrutura, que **o que é determinístico não mora num YAML de prompt**.

**`evaluations/cases/` é versionado; `data/` não.** É a decisão de ativo do
projeto tornada explícita no scaffold: o dataset de avaliação é o que não se
copia, e por isso vive no git. (Com a ressalva do spec §8: caso colhido de
cliente carrega dado de terceiro e precisa de anonimização antes de versionar —
o `harvest` deve produzir `input_snapshot` já sanitizado.)

### 16.4 O `orchestrator.yaml`

```yaml
version: 1
providers:
  anthropic:
    api_key_env: ANTHROPIC_API_KEY
    default_model: claude-sonnet-5
storage:
  runs:      { driver: jsonl, path: data/runs }
  decisions: { driver: jsonl, path: data/decisions }
  cases:     { driver: jsonl, path: evaluations/cases }
policy:
  default:
    autonomy: PROPOR
    budget:
      per_item_microcents:  4000000
      per_run_microcents:  400000000
observability:
  spans: true
  otel:  { enabled: false }
```

**Precedência, do mais forte ao mais fraco:** argumento de CLI → variável de
ambiente → `orchestrator.yaml` → default do dataclass. A última linha é
importante: o default continua morando **no código**, junto da guarda que o
valida — `budget_microcents` tem 40 linhas de derivação comentada ao lado dele, e
mover o valor para um YAML separaria o número da prova de onde ele veio.

### 16.5 Exemplo mínimo de uso (SDK)

```python
from orchestrator import Agent, Workflow, Task, tool
from orchestrator.providers.anthropic import AnthropicClient

@tool(permission="read_only", timeout_s=5)
def buscar_pedido(numero: str) -> dict:
    """Busca um pedido de compra pelo número."""
    return db.pedidos.get(numero)

triagem = Agent(
    name="triador",
    system="Classifique a solicitação de compra...",
    tools=[buscar_pedido],
    output_schema=Triagem,
    model="claude-sonnet-5",
)

wf = Workflow(id="compras", version="1", tasks=[
    Task("classificar", cascade=[regra_catalogo(), triagem, revisor_humano()]),
])

run = wf.run(work=[WorkItem(id=p.id, kind="pedido", payload=p) for p in pedidos])
print(run.cost_total_microcents, run.state)
```

Quinze linhas, um domínio novo, **zero mudança no kernel**. Se essa propriedade
não valer ao final de M2, a generalização falhou — e é assim que se testa.

---

## 17. Dashboard

### 17.1 Não reescrever, e a justificativa

O canvas atual são 624 linhas de JS/CSS/HTML vanilla, sem build step, servidas
por `StaticFiles` do próprio app. Ele já:

- desenha a cascata com classe de custo por resolver;
- mostra taxa de resolução e custo **medidos**, com "não medido" quando não há
  medição (em vez de zero, que mentiria);
- declara a lacuna que nenhum resolver cobre, em vez de escondê-la;
- desabilita o botão de workflow com etapa paga em vez de deixar colher um 409;
- tem uma fila de revisão funcional com três ações e validação;
- compartilha os defaults com a API pela URL, porque duplicar constante já
  quebrou uma vez (P4.14).

**Trocar isso por React compraria:** componentização e ecossistema de gráficos.
**E pagaria:** `package.json`, bundler, pipeline de build no CI, e a reimplementação
de cinco comportamentos corretos que hoje são invisíveis porque funcionam. Numa
equipe pequena, é um mau negócio.

**Decisão: estender o canvas existente. Reavaliar só se (a) surgir necessidade de
gráfico de série temporal com interação, ou (b) o JS passar de ~2.000 linhas.**
Nesse ponto, a migração é para Preact ou Lit via CDN — mantendo "sem build step",
que é o que torna `uvicorn orchestrator.api.app:app` suficiente para rodar tudo.

### 17.2 As telas

| Tela | Estado | O que mostra | Depende de |
|---|---|---|---|
| **Cascata** | **existe** | resolvers, classe, taxa, custo, lacuna | — |
| **Fila** | **existe** | pendentes, lado a lado, 3 ações, `divergiu` | — |
| **Runs** | novo | lista: id, workflow@versão, estado, itens, custo, duração | M1 |
| **Run** | novo | árvore de spans (§13.1), custo por nível, lacuna | M1, M4 |
| **Item** | novo | a investigação de um item: turnos, ferramentas, evidência, proposta, decisão | M4 |
| **Custo** | novo | custo por resolver/modelo/dia; µ¢ por proposta correta | M4, M6 |
| **Avaliação** | novo | benchmark por arm, regressão vs. linha de base | M6 |
| **Workflow graph** | estender | a cascata já é o grafo; ganha stages quando existirem | M1 |

### 17.3 A tela que diferencia

A tela **Custo** não tem equivalente em nenhum framework de agente da categoria.
Ela responde:

```text
Este fechamento custou US$ 0,1240 em 317 itens  (US$ 0,00039 / item)

  L1            247 itens   US$ 0         0,3s   ← 78% resolvido de graça
  L2             18 itens   US$ 0         0,0s
  L3             11 itens   US$ 0         0,9s
  investigador   31 itens   US$ 0,1240   11,2s   ← 79% do tempo, 100% do custo
  revisor         4 itens   US$ 0         0,0s
  lacuna         41 itens   R$ 18.402,55  aguardando humano

  política pulou o investigador em 12 itens
    → economia estimada US$ 0,0480 (custo > 2% do valor em risco)

  custo por proposta CORRETA: US$ 0,0055  (22 de 31 corretas)
```

As duas últimas seções são as que só existem porque o `PolicyDecision` e o
`EvaluationCase` são de primeira classe. É a tese do projeto numa tela.

### 17.4 Como a API alimenta isso

```text
GET  /api/runs?workflow&state&since&limit
GET  /api/runs/{run_id}
GET  /api/runs/{run_id}/trace
GET  /api/runs/{run_id}/items/{item_id}
GET  /api/runs/{run_id}/cost?by=resolver|model|item
POST /api/runs                        # ingestão real, não só benchmark
GET  /api/queue/{run_id}
POST /api/queue/{run_id}/{item_id}/decision
GET  /api/benchmarks?dataset
```

**A regra "nenhum endpoint gasta dinheiro" vale para todas elas.** `POST /api/runs`
sobre uma cascata com classe `AGENTE` continua devolvendo 409, e o
`ClienteAusente` continua sendo a tranca. Se algum dia a API precisar disparar
execução paga, ela o faz **enfileirando** — e o worker que consome a fila é outro
processo, com sua própria autorização explícita. O teste
`tests/api/test_execucao.py` é o guardião e não deve ser afrouxado.

---

## 18. MCP / A2A / Plugins

### 18.1 A regra: adapter, nunca core

```text
kernel        conhece  Resolver, Tool, Cost
agent         conhece  ToolRegistry, LLMClient
adapters/     conhecem MCP, A2A, HTTP, SDKs de terceiros
```

Se o kernel souber o que é MCP, ele fica preso à versão do protocolo. A postura
correta é a que `agent/anthropic_client.py` já adota: *"Este é o único arquivo do
projeto que conhece o SDK. Todo o resto fala com `LLMClient`."* Um arquivo por
protocolo externo.

### 18.2 MCP

**Já existe, parcialmente, e num lugar inesperado.** `eval/assinatura.py` monta um
servidor MCP in-process com `create_sdk_mcp_server`, reusando `TOOL_SCHEMAS`
verbatim, e o docstring explica por quê: *"Se os dois caminhos declarassem
contratos diferentes, comparar o agente pago com o agente por assinatura não
mediria o agente, mediria a diferença entre as duas declarações."* Isso é MCP
como **servidor** (expondo as nossas ferramentas).

Falta o outro sentido — MCP como **cliente** (consumindo ferramentas de fora):

```python
# adapters/mcp/client.py — extra [mcp]
class MCPToolAdapter:
    """Ferramentas de um servidor MCP, registradas como ToolSpec.

    Toda ferramenta importada entra com permission=EXTERNAL e timeout
    obrigatório. Ferramenta de terceiro é código que não escrevemos, e o
    spec §3.2 Tier 4 já reservou 'sandbox de execução' para esse gatilho —
    até lá, EXTERNAL significa que a política pode recusá-la por default.
    """
    def discover(self, server: MCPServerConfig) -> list[ToolSpec]: ...
```

**Não entra no MVP.** Gatilho: um caso real precisando de uma ferramenta que já
existe como servidor MCP e que seria cara de reescrever. Antes de M2 (registry
com permissão), importar ferramenta externa é importar risco sem o mecanismo que
o contém.

### 18.3 A2A

```python
# adapters/a2a/remote.py
class RemoteAgentResolver:
    """Um agente remoto como Resolver. Nada mais.

    Consequências que precisam estar resolvidas ANTES de isso existir:
      - custo: o agente remoto reporta tokens? Se não, `custo_medido=False`,
        como `InvestigadorAssinatura` já faz — jamais US$ 0,00 passando por
        medição.
      - trace: os spans dele entram na nossa árvore, ou vira caixa-preta?
      - falha: timeout de rede vira abstenção, como toda falha de agente.
      - confiança: a confiança dele é comparável à nossa? Só depois de M6.
    """
```

**Bloqueado até M8.** Não porque seja difícil, mas porque "agente remoto"
pressupõe que a semântica de multi-agente esteja estável localmente. Adotar A2A
com um único agente local é adotar um protocolo de integração para integrar
consigo mesmo.

### 18.4 Plugins

**O mecanismo já está desenhado no `CATALOGO`; falta só a porta de entrada.**

```python
# runtime/registry.py
class ResolverRegistry:
    """Resolvers de entry points + os embutidos.

    `CATALOGO` de hoje vira o registro embutido, com a mesma estrutura
    (nome, classe de custo, resumo, ParametroSpec lidos do dataclass). O que
    muda é que `load_plugins()` acrescenta entradas de terceiros.

    A disciplina do `_param()` — ler o default do PRÓPRIO dataclass, de modo
    que renomear o campo exploda no import — vale igualmente para plugin, e
    é o que faz um plugin quebrado falhar alto no carregamento em vez de em
    silêncio na tela.
    """
    def load_plugins(self) -> None:
        for ep in entry_points(group="orchestrator.resolvers"):
            self.register(ep.load())
```

```toml
# no pyproject de um plugin
[project.entry-points."orchestrator.resolvers"]
fuzzy_matcher = "meupacote.resolvers:FuzzyMatcher"
```

**Regras que o registry impõe no carregamento:** id reservado não é sobrescrito
(`ID_RESERVADOS` já existe em `receita.py`); classe de custo é obrigatória; um
plugin que não constrói é ignorado com aviso em stderr, nunca derruba a listagem
(a metade que `listar_workflows` já implementa). Os três são código que já existe
e só precisa ser reapontado.

---

## 19. Migration Strategy

### 19.1 A garantia — e por que ela sobrevive à conciliação ser descartável

A conciliação deixou de ser o produto (§1.3). **A suíte dela não deixou de ser a
prova.** A distinção importa e vale ser explícita, porque a conclusão intuitiva
é a oposta:

- "Descartável" significa: **não investir nela** — sem parser de OFX, sem novas
  camadas de matching, sem features de produto, sem cliente.
- "Descartável" **não** significa: abrir mão de 449 testes, de um golden de 12
  sementes e de três números travados no CI, no exato momento em que o kernel vai
  ser reescrito por baixo.

Num refactor desta magnitude — `WorkSet`, `Resolution`, o motor, o store, a
política — a única coisa que separa "generalizei corretamente" de "quebrei em
silêncio" é um domínio complexo o bastante para exercitar tudo, com saída
travada. A conciliação é exatamente isso: cardinalidade N:M, dinheiro em
inteiros, três classes de custo, decisão humana, falso positivo e falso negativo
com definições assimétricas. **Ela vale mais como fixture agora do que valia como
produto antes**, porque agora é a única coisa que pode falhar alto.

Portanto a garantia continua idêntica, só muda a razão. A medida não é opinião:

```bash
orchestrator --seed 1 --n 500
# Taxa determinística (lado bancário): 85.3%
# Falsos positivos:  0
# Falsos negativos:  0
```

Esses três valores estão travados no job `conciliador` do CI por `grep` de linha
inteira, e o golden de 12 sementes
(`tests/golden/cascata_12_sementes.json`) trava a saída do motor. **Todo PR deste
roadmap roda o CI inteiro; nenhum altera esses números.** Se um PR precisar
alterá-los, ele não é migração — é mudança de comportamento, e precisa de
justificativa própria.

### 19.2 De `Resolver → Resolver → Resolver → Agente` para workflow genérico

```text
HOJE
reconcile(bank, ledger, definition)
  └── Stage "conciliar lançamentos"
       ├── L1            REGRA
       ├── L2            REGRA
       ├── L3            REGRA
       ├── investigador  AGENTE    (opcional, não na definição servida)
       └── revisor       HUMANO

ALVO
Workflow(id="conciliacao", version="4")
  └── Task "conciliar lançamentos"  policy=ExecutionPolicy(...)
       ├── deterministic  L1, L2, L3       REGRA
       ├── agent          investigador     AGENTE
       ├── crew           (opcional)       CREW
       └── human          revisor          HUMANO
```

**A distância entre os dois é menor do que o desenho sugere.** O que muda:
`bank, ledger` → `WorkSet(items)`; a política passa a ser avaliada antes de cada
resolver; o resultado vira `Run` em vez de `ReconcileResult`. **O que não muda:**
os três matchers, o investigador, o revisor, a ordem, a cascata, os números.

### 19.3 Sequência de introdução, e por que nesta ordem

**A regra que governa a sequência: nenhum passo pode exigir que dois conceitos
mudem ao mesmo tempo.** Cada linha abaixo é um PR que entra verde.

| # | Introduzir | Por quê agora | Quebra o quê |
|---|---|---|---|
| 1 | teste de camadas (vermelho) | documenta as 3 inversões como falha, não prosa | nada (marcado `xfail`) |
| 2 | `kernel/cost.py` | `Cost` fora de `agent/` mata a inversão 1; nenhum outro conceito muda | nada — re-export em `agent/proposal.py` |
| 3 | `WorkItem` / `WorkSet(items)` | destrava tudo; é a mudança mais arriscada, e por isso vem cedo, com o golden inteiro como rede | `WorkSet`, 3 matchers, agente, revisor, métricas |
| 4 | `Resolution` | idem, mesmo PR ou o seguinte | `MatchResult` → alias temporário |
| 5 | `runtime/engine.execute` | `reconcile` vira casca fina sobre ele; a circularidade some quando `default_resolvers` sai do motor | imports de `matching/engine` |
| 6 | `Run` + `EventBus` + `RunStore` | substitui o `lru_cache`; destrava observabilidade e HITL | `api/app.py` |
| 7 | `Source` + `input_ref` | id de execução deixa de ser uma tupla de benchmark; domínio novo passa a ter de onde receber trabalho | escopo da `Fila` (script de migração) |
| 8 | `ExecutionPolicy` (modo "igual a hoje") | entra sem mudar comportamento — a política que descreve o status quo | nada |
| 9 | `Span` + collector | trace do agente passa a ser derivado, não paralelo | `Proposal.trace` vira derivado |
| 10 | `EvaluationCase` + harvest | fecha o loop | nada (só acrescenta) |

**O passo 3 é o de maior risco do roadmap inteiro** e merece tratamento especial:

- Vem cedo, quando a superfície é a menor que vai ser.
- Roda com `matches_by_layer`, `matches_by_resolver` e `matches_by_class`
  preservados campo a campo, porque `metrics.py` e `api/app.py` dependem dos três
  com semânticas diferentes (decisão P3.2) — confundi-los é o defeito que o repo
  já pagou uma vez para corrigir.
- Critério de aceitação: golden idêntico, `85.3%` idêntico, FP=0, FN=0, 449
  testes verdes. **Nada disso é "revisar com cuidado". São comandos que rodam.**

### 19.4 Compatibilidade durante a transição

```python
# orchestrator/models.py — durante a migração
MatchResult = Resolution           # alias, com DeprecationWarning no import

# orchestrator/matching/engine.py — durante a migração
def reconcile(bank, ledger, definition=None) -> ReconcileResult:
    """Casca fina sobre runtime.execute. Preserva a assinatura que o CLI, o
    eval, o grill e 449 testes usam.

    Some quando o último chamador migrar — e não antes, porque manter dois
    caminhos de execução vivos é o drift que `definition.py` recusa.
    """
    run = execute(definition or default_definition(), to_workset(bank, ledger), ctx)
    return ReconcileResult.from_run(run)
```

**Regra de remoção:** um alias vive até o último chamador migrar, e some no PR
que migra o último. Aliases permanentes viram API pública por acidente.

### 19.5 O que acontece com o domínio de conciliação

Ele **para de crescer e vira fixture**. Concretamente, a partir do PR #1:

| | |
|---|---|
| **Congelado** | nenhuma camada de matching nova, nenhum injetor novo, nenhum tipo novo na taxonomia, nenhum parser de formato real |
| **Mantido e testado** | os 3 matchers, o investigador, o revisor, a fila, o gerador sintético, os 449 testes, o golden, os 3 números do CI |
| **Migrado como qualquer outro domínio** | vira `domains/reconciliation/`, importa do kernel, não é importado por ninguém |
| **Ganha de graça** | `Run`, trace, política, avaliação — porque são do runtime, não dele |

**A regra operacional:** um PR pode tocar `domains/reconciliation/` para
**migrar** (mudar import, adaptar à assinatura nova). Um PR que toque ali para
**adicionar capacidade de conciliação** está fora do roadmap e precisa de
justificativa própria.

### 19.6 O teste de generalidade, antecipado para M0

No plano original, o segundo domínio vinha em M5 como critério de saída. Com a
regra dos três usos suspensa (§1.3), ele **sobe para M0** e deixa de ser
critério de saída para virar **ferramenta de projeto**: os dois esqueletos são
escritos enquanto o kernel ainda está mole, e cada atrito que eles encontram é
uma correção barata em vez de uma descoberta cara.

```python
# domains/procurement/workflow.py   (~80 linhas)
Task("quem fornece isto?", cascade=[
    FornecedorPreferido(),      # REGRA
    ComprasAnteriores(),        # REGRA
    BuscadorDeFornecedor(),     # AGENTE
    RevisorHumano(),            # HUMANO
])

# domains/swe/workflow.py           (~80 linhas) — o caso DEGENERADO
Task("que mudança esta issue pede?", cascade=[
    TriadorDeIssue(),           # AGENTE  ← sem nenhum resolver de classe REGRA
    RevisorHumano(),            # HUMANO
])
```

**O segundo é o que importa.** Uma cascata sem nenhum resolver barato testa o
limite mais duro da abstração: `deterministic_rate` sobre zero regras,
`matches_by_class` sem a chave `REGRA`, `Stage.ordered()` com uma classe só. O
repositório **já antecipou esse caso** — o comentário em `metrics.py` diz que o
default é `[]` e não `result.matches` justamente porque *"uma cascata sem
resolver REGRA nenhum — um stage só de revisão humana, por exemplo —
legitimamente não tem match determinístico algum"*. A guarda existe e nunca foi
exercida por um domínio real. Em M0, passa a ser.

**Critério, em comandos:** ao final de M0, `git diff --stat src/orchestrator/kernel/`
no PR que adiciona os dois domínios precisa vir **vazio**. Se não vier, a
abstração não é genérica — e descobrir isso no PR #6 custa um dia, enquanto
descobrir no M5 custaria um mês.

---

## 20. ADRs recomendados

Formato do repositório: contexto, decisão, alternativas, por quê, trade-offs.
Cada um vira um arquivo em `docs/adr/` no PR que o implementa.

### ADR-01 — Motor síncrono; paralelismo local e explícito

**Contexto.** Todo o código é síncrono. O único `asyncio.run` está em
`eval/assinatura.py`. Frameworks concorrentes são async por padrão.

**Decisão.** `Resolver.resolve()` e `engine.execute()` permanecem síncronos.
Concorrência entra por `ParallelResolver` (thread pool) onde medida como
necessária.

**Alternativas.** (a) Async no motor. (b) API dupla sync/async. (c) Async só no
agente.

**Por quê.** Async coloriria `Resolver.resolve`, os 3 matchers, o revisor, o
CLI e 449 testes para comprar concorrência que nenhum caso atual precisa:
L1–L3 são CPU-bound; a chamada ao modelo é serial **de propósito**, porque o
orçamento é verificado entre itens. API dupla dobra a superfície de teste do
laço, que é a parte mais delicada do sistema.

**Trade-offs.** Um lote grande com o agente demora mais. Mitigação:
`ParallelResolver`, que degrada a granularidade do orçamento para por-lote — e
essa perda é declarada no docstring, não descoberta na fatura. Reavaliar com
lote > 500 itens indo ao agente.

### ADR-02 — Eventos observam; não controlam

**Contexto.** CrewAI Flow usa `@start`/`@listen`/`@router`: a ordem de execução é
emergente da reação a eventos.

**Decisão.** O motor é imperativo e determinístico. Ele **emite** eventos; nada
no fluxo de controle reage a eles.

**Alternativas.** (a) Event-driven de verdade. (b) Híbrido.

**Por quê.** Com controle event-driven, a ordem de execução deixa de ser uma
propriedade da definição e passa a ser emergente. O golden de 12 sementes, o
`85.3%` travado no CI e o `ReplayResume` **todos** dependem de determinismo. É
um requisito do produto, não uma preferência.

**Trade-offs.** Fluxos genuinamente reativos (webhook no meio do processo) ficam
desconfortáveis. Mitigação: um webhook cria um `Run` novo, não retoma o meio de
um existente.

### ADR-03 — `WorkItem` com `kind` + payload opaco, não generics

**Contexto.** `WorkSet(bank, ledger)` solda o kernel à conciliação.

**Decisão.** `WorkItem(id, kind: str, payload: Any)` onde `payload` é um
dataclass congelado do domínio; acessores tipados ficam no domínio.

**Alternativas.** (a) `WorkSet[T]` genérico. (b) payload como `dict`. (c) manter
dois campos com nomes neutros (`left`/`right`).

**Por quê.** (a) forçaria `T = BankEntry | LedgerEntry` e uniões estreitadas em
todo resolver, porque a conciliação é assimétrica. (b) perderia as garantias do
domínio (int em centavos, campos congelados), que são o núcleo da disciplina do
repositório. (c) só renomeia o problema e não cabe em domínios de um lado só.

**Trade-offs.** `payload: Any` é um buraco de tipagem no kernel. Contido por:
o kernel **nunca** inspeciona payload (garantido pelo teste de camadas), e o
domínio expõe acessores tipados usados por todos os seus resolvers.

### ADR-04 — Uma distribuição; camadas impostas por teste

**Contexto.** O pedido sugere `packages/`. O repo tem 5.5k linhas de `src` e uma
dependência de runtime.

**Decisão.** Um pacote instalável, camadas como diretórios,
`tests/arquitetura/test_camadas.py` como fronteira.

**Alternativas.** (a) Monorepo com N pacotes. (b) Nada além de convenção.

**Por quê.** (a) paga N versionamentos, N changelogs e resolução de versão
cruzada para comprar o que um teste garante de graça. (b) é o estado de hoje, e é
o que produziu as três inversões documentadas na §2.1.

**Trade-offs.** Quem quiser só o kernel instala tudo. Aceitável: a dependência de
runtime é uma. Reavaliar se um terceiro publicar um plugin sério.

### ADR-05 — Store append-only JSONL; SQLite por gatilho

**Contexto.** `Fila` já usa JSONL append-only e o docstring explica que isso não
é economia de esforço — é a trilha de auditoria saindo como subproduto do
formato.

**Decisão.** `RunStore`/`EventStore`/`DecisionLog` como protocolos; JSONL como
primeira implementação; SQLite quando o dashboard precisar de consulta.

**Alternativas.** (a) SQLite já. (b) Postgres. (c) memória.

**Por quê.** JSONL é diffável, auditável, sem dependência, e já provado neste
repo. Postgres exige operação que um projeto pessoal não tem. SQLite entra quando
"listar os 50 últimos runs com custo acima de X" ficar lento — e não antes.

**Trade-offs.** Consulta ruim, arquivo cresce. Gatilho: > 10k runs, ou latência
de listagem > 500ms.

### ADR-06 — DI por contexto tipado; morte do `inspect.signature`

**Contexto.** `api/app.py::_construir_definicao` inspeciona o **nome** do
parâmetro para decidir passar a fila. O próprio docstring avisa que renomear
`fila` para `q` deixaria a suíte verde e serviria fila vazia em silêncio.

**Decisão.** `RuntimeContext` congelado, passado explicitamente a um
`WorkflowFactory` Protocol e a `Resolver.resolve()`.

**Alternativas.** (a) Container de DI. (b) Variáveis globais/`contextvars`.
(c) Manter.

**Por quê.** (a) é maquinário para um problema de cinco dependências. (b) torna
o teste dependente de ordem e esconde o acoplamento. (c) é um defeito silencioso
esperando um rename — a classe de falha que este repositório já corrigiu seis
vezes.

**Trade-offs.** Assinaturas mais longas. É o preço certo: acoplamento visível.

### ADR-07 — `LLMClient` preservado; `ModelRouter` o implementa

**Contexto.** `LLMClient` é um Protocol de 3 argumentos, e `AnthropicClient` é o
único arquivo que conhece o SDK. Funciona.

**Decisão.** Manter o Protocol. Roteamento, fallback e cache entram como uma
**implementação** dele (`ModelRouter`), não como mudança do contrato.

**Alternativas.** (a) LiteLLM no core. (b) Cliente por provider exposto ao
domínio.

**Por quê.** Se o router é um `LLMClient`, o agente não muda, os testes com
`FakeLLMClient` não mudam, e `ReplayClient` continua valendo. LiteLLM adicionaria
uma dependência de runtime pesada para resolver um problema que este projeto
ainda não tem (um provider).

**Trade-offs.** Cada provider novo é um arquivo nosso. Com 1–3 providers, é menos
trabalho que gerenciar a abstração de terceiro.

### ADR-08 — OTel é exportador, não modelo interno

**Contexto.** OTel é o padrão, e há pressão para adotá-lo como modelo.

**Decisão.** `Span` interno próprio; `observability/otel.py` exporta, sob extra
`[otel]`.

**Alternativas.** (a) OTel como modelo interno. (b) Nenhum OTel.

**Por quê.** Custo em micro-centavos `int` não tem lugar canônico em OTel e
viraria atributo float — ponto flutuante em dinheiro é proibido aqui.
`status="abstencao"` e `status="pulado"` não são OK nem ERROR, e a diferença é
comercialmente relevante. E OTel no kernel é dependência de runtime num pacote
que hoje tem uma.

**Trade-offs.** Um mapeamento a manter. ~40 linhas.

### ADR-09 — Durable execution: adotar, nunca construir

**Contexto.** O spec §3.2 já decidiu isso. Este ADR formaliza **onde** a costura
fica e qual é o padrão até lá.

**Decisão.** `Executor` Protocol com `InProcessExecutor` hoje. Durabilidade por
`ReplayResume` (§12.5). Temporal/Restate/DBOS só no gatilho Tier 3.

**Alternativas.** (a) Construir event sourcing. (b) Temporal agora.

**Por quê.** (a) são meses e não é o diferencial. (b) adiciona um cluster e um
modelo de programação para trabalho que leva minutos e já retoma corretamente.

**Trade-offs.** `ReplayResume` reexecuta as regras (grátis) e exige que a entrada
seja reproduzível. As duas condições valem hoje. Gatilho: trabalho de dias, ou
resolver com efeito colateral não idempotente.

### ADR-10 — Idioma: superfície pública em inglês, domínio em português

**Contexto.** O código mistura os dois: `resolve`/`Resolver`/`WorkSet` em inglês;
`entrevistador`/`fila`/`receita`/`construir` em português. Funciona internamente;
não funciona como API pública de framework.

**Decisão.** `kernel/`, `runtime/`, `agent/`, `crew/`, `evaluation/` em inglês.
`domains/reconciliation/` e `authoring/` mantêm português onde o termo é do
domínio brasileiro (`retencao`, `competencia`, `CNAB`). Comentários e docs em
português.

**Alternativas.** (a) Tudo em inglês. (b) Tudo em português. (c) Manter a mistura
atual.

**Por quê.** A camada genérica é a que um terceiro importa; ela precisa ser
legível por quem vem de CrewAI/LangGraph. O domínio é fiscal brasileiro:
traduzir "retenção de ISS" para inglês perde precisão e não ganha ninguém.

**Trade-offs.** A fronteira precisa ser clara, e isso é exatamente o que o teste
de camadas já impõe. Renomeações são mecânicas e entram nos PRs de migração que
já tocam os arquivos — nunca num PR de rename isolado, que seria puro risco sem
ganho.

### ADR-11 — Config: default no código, YAML só para override

**Contexto.** Os defaults hoje são kwargs de dataclass, e alguns carregam 40
linhas de derivação comentada (`budget_microcents`, `ORCAMENTO_PADRAO`).

**Decisão.** Default mora no dataclass, junto da guarda e da derivação.
`orchestrator.yaml` só sobrescreve. Precedência: CLI → env → YAML → código.

**Alternativas.** (a) Tudo no YAML. (b) Sem YAML.

**Por quê.** Mover `budget_microcents = 4_000_000` para um YAML separaria o
número da prova de onde ele veio e do teste que o pina em todo modelo
precificado. (b) impede operar sem editar código.

**Trade-offs.** Duas fontes. Contido pela precedência única e testada.

### ADR-12 — Segredos: só provider de ambiente no core

**Contexto.** Hoje: `ANTHROPIC_API_KEY` no ambiente e um `.env`.

**Decisão.** `SecretProvider` Protocol com `EnvSecretProvider` como única
implementação no core. Vault/AWS/GCP como adapters de terceiros.

**Por quê.** Gestão de segredo é Tier 2 no spec, com gatilho "quando houver
credencial de cliente, não só nossa". Antes disso, um Protocol de três métodos
já preserva o caminho.

**Trade-offs.** Nenhum relevante hoje.

### ADR-13 — Plugins por entry point; catálogo embutido preservado

**Contexto.** `CATALOGO` é um dict literal, e o mecanismo de `ParametroSpec` que
lê o default do dataclass é bom demais para ser jogado fora.

**Decisão.** `ResolverRegistry` com os embutidos + `entry_points(group=
"orchestrator.resolvers")`. Plugin que não constrói é ignorado com aviso em
stderr.

**Alternativas.** (a) Importar por string de config. (b) Sem plugin.

**Por quê.** Entry points são o mecanismo padrão do Python, funcionam com
`pip install`, e a validação por construção já existe.

**Trade-offs.** Código de terceiro no processo. O spec §3.2 Tier 4 já reservou
sandbox para isso; até lá, plugin instalado é código confiado, como qualquer
dependência.

### ADR-14 — Sem fila e sem cache no core

**Contexto.** `lru_cache` em `_executar_memoizado` já é um cache que virou store
por acidente.

**Decisão.** Nenhuma fila (Celery/RQ/Redis) e nenhum cache no core. Idempotência
por `IdempotencyKey` no store; memoização de execução **removida**.

**Por quê.** O `lru_cache` de hoje já causou uma correção (`cache_clear()` depois
de decisão) e o próprio docstring admite que a função deixou de ser pura. Um
`RunStore` consultável resolve o problema real (histórico) sem fingir ser cache.

**Trade-offs.** Cada `POST /runs` reexecuta. Para uma cascata só de regras sobre
n=300, isso é dezenas de milissegundos. Se deixar de ser, é `RunStore` com
lookup por `(workflow, version, input_ref)` — que é um store, não um cache, e
não invalida errado.

---

## 21. Non-Goals — o que NÃO implementar

> Esta seção tem a mesma autoridade que o roadmap. Um item aqui só sai com
> gatilho registrado e datado.

> **Revisado em 2026-09-16.** A decisão de §1.3 suspendeu a regra dos três usos.
> Os itens que estavam aqui por serem *cedo demais para o produto* **saíram**.
> Os que estavam por serem *caros, sem demanda, ou erro de categoria* **ficam** —
> a razão deles nunca foi a regra suspensa.

### 21.1 Herdados do spec, e reafirmados

| Não construir | Desbloqueia quando |
|---|---|
| Durable execution própria | **Nunca.** Adotar Temporal/Restate no Tier 3 |
| Marketplace de agentes | 10+ usuários pedirem |
| Multi-tenancy | Alguém hospedar isso para terceiros |
| RBAC | Idem |
| Sandbox de execução | Executarmos plugin de terceiro não confiado |
| DSL de workflow em YAML como **superfície de autoria** | Nunca. A receita é **gerada**; YAML escrito à mão é a superfície que o spec de composição §4.1 já rejeitou |

### 21.2 Saíram do anti-escopo por causa da decisão de §1.3

| Item | Estava barrado por | Agora |
|---|---|---|
| `Crew` | "antes de haver produto e benchmark" | **M8**, atrás de dependência técnica (M2) e do gate de medição (M6) |
| MCP como cliente | "antes de core estável" | **M11**, atrás de `ToolPermission` (M2) — a contenção continua sendo requisito |
| A2A | "antes de multi-agente" | **M11**, depois de M8 |
| Memória / knowledge | "antes de caso medido" | **M9**, como adapter, com o benchmark de M6 decidindo se ajuda |
| Publicar no PyPI | "antes de 3 usos" | Depois de **M5** (CLI/SDK) — `0.x`, quebra permitida |

### 21.3 Ficam, e por razões que a decisão não toca

| Não construir | Por quê | Desbloqueia quando |
|---|---|---|
| **Parser de OFX/CNAB/ERP** | A conciliação é fixture, não produto (§1.3). `Source` é a abstração; formato real é trabalho de quem tiver o caso | Alguém com o dado quiser — e aí é um `Source` de 40 linhas, não uma fase |
| **Abstração de vector DB no core** | Amarra o core a um ecossistema volátil. Erro de categoria, não de timing | SQLite FTS5 perder contra baseline **medido** |
| **`Task` como entidade separada de `Stage`** | Duplicaria estado e serialização; o spec já diz que "é um" | Nunca |
| **Async no motor** | Colore 449 testes por concorrência que ninguém precisa | Lote > 500 itens ao agente, medido |
| **Reescrita do canvas em React** | Troca 624 linhas corretas por um pipeline de build | JS > 2.000 linhas ou série temporal interativa |
| **Streaming de resposta** | Complica o laço e a contabilidade de custo sem consumidor | Uma UI com humano esperando token a token |
| **Memória ligada por default** | Memória aproximada perto de estado auditável é o erro de categoria da §11.1 | Nunca por default; sempre opt-in |
| **Planejamento (ReAct / plan-and-execute)** | O laço de 6 turnos basta; planejamento triplica turnos e custo | Caso onde o agente falha por falta de plano, não de contexto |
| **`AGIR_SE_SEGURO` (auto-resolução)** | Confiança de LLM não é calibrada; ligar sem medir destrói credibilidade | M6 medir precisão por faixa de confiança |
| **Voto ponderado por confiança em Crew** | Dá autoridade a um número não calibrado | Idem |
| **Otimização automática de prompt** | Sem benchmark, otimiza para ruído | M6 + dataset com 100+ casos |
| **Múltiplos providers de LLM** | Um provider, zero demanda; a costura (`LLMClient`) já preserva o caminho | Um caso exigir modelo que a Anthropic não tem |
| **Grafo de workflow com branching** | Nenhum dos três domínios precisa; a cascata cobre os três | Dois stages com ordem parcial num workflow real |
| **Migração para Postgres** | Operação que um projeto pessoal não tem | >10k runs ou acesso concorrente real |
| **Autenticação/autorização na API** | A API roda em localhost | Primeiro deploy fora da máquina do dev |

### 21.4 As quatro armadilhas mais prováveis, nomeadas

1. **Construir `Crew` porque o desenho tem uma caixa chamada Crew.** É a caixa
   mais cara e a única da qual nada depende. Ordem correta: medir primeiro (M6
   antes de M8).
2. **Trocar `Fila`/JSONL por um banco "de verdade" cedo.** O append-only **é** a
   trilha de auditoria. Um ORM compraria consulta e venderia auditabilidade.
3. **Generalizar `Stage` em grafo antes de existir um segundo stage.** A cascata
   é o primitivo (spec de composição §1.2). Grafo sem caso é abstração
   prematura, e nenhum dos três domínios pede grafo.
4. **Tratar "a conciliação é descartável" como licença para afrouxar a suíte
   dela.** É a armadilha nova, criada pela decisão de §1.3, e a mais perigosa
   das quatro: ela remove a única rede que existe no exato PR em que o kernel é
   reescrito. Ver §19.1.

---

## 22. Technical Risks

Probabilidade e impacto em baixo/médio/alto. Sem notas numéricas.

| # | Risco | Prob. | Impacto | Mitigação |
|---|---|---|---|---|
| R1 | **Migração do `WorkSet` muda os números do conciliador** | Média | **Alto** | Golden de 12 sementes + `85.3%`/FP=0/FN=0 no CI como critério de aceitação binário, não como revisão. PR 3 não entra se qualquer um mudar |
| R2 | **Generalização prematura: kernel genérico, um domínio só** | **Alta** | Médio | Teste de generalidade em M5 (segundo domínio sem tocar em `kernel/`). Falha barata e cedo |
| R3 | **Abstração desenhada a partir de uma instância só estar errada** — o risco que a regra dos três usos existia para conter, e que a decisão de §1.3 **aceita** | **Alta** | **Alto** | Substituto de engenharia: os dois domínios esqueleto entram em **M0**, não em M5, e o critério é `git diff --stat kernel/` vazio. Errar fica barato porque fica cedo |
| R4 | **Custo de LLM explodir em benchmark** | Média | Médio | Orçamento em dois níveis já existe; política acrescenta decisão por item; CI nunca roda caminho pago; `--dry-run` = `Autonomy.OBSERVAR` |
| R5 | **Não-determinismo do LLM quebrar o benchmark** | **Alta** | Médio | Três camadas já existem (fake → replay → ao vivo). Regressão por **mínimo** entre sementes, não média (decisão 26) |
| R6 | **Cache de proposta contaminar a avaliação** | Média | **Alto** | `IdempotencyKey` com versão de agente e fingerprint de prompt (§6.4). É o único bug latente que a auditoria encontrou com consequência sobre a métrica |
| R7 | **Falha de ferramenta virar abstenção plausível e esconder bug** | Média | Médio | A inversão das duas capturas (estreita no modelo, larga na ferramenta) é preservada e testada. PR que as unifique é recusado |
| R8 | **Concorrência ao gravar o JSONL** | Baixa | Médio | Hoje: uma máquina, um usuário, `open("a")` por linha (documentado). Gatilho para lock ou SQLite: segundo escritor |
| R9 | **Execução distribuída antes da hora** | Baixa | **Alto** | ADR-09: `Executor` Protocol é a costura; nada mais |
| R10 | **Observabilidade custar mais que o observado** | Média | Baixo | Spans em memória, escrita em lote no fim do run; `observability.spans: false` desliga tudo; domínio nunca importa de `observability/` |
| R11 | **Quebrar compatibilidade da API/CLI** | Média | Médio | Aliases com `DeprecationWarning`; despachante de CLI aceita a forma legada; job `conciliador` do CI é o guardião |
| R12 | **Complexidade de plugin (resolver de terceiro corromper estado)** | Baixa | **Alto** | `_validar()` no motor levanta em id fantasma (§12.2). Hoje essa guarda só existe na métrica |
| R13 | **Instabilidade da API: interfaces mudarem depois de publicadas** | Média | Médio | Não publicar no PyPI antes de M5 (§21.2). `0.x` com quebra permitida |
| R14 | **`payload: Any` erodir a tipagem do domínio** | Média | Médio | Teste de camadas proíbe kernel importar domínio; acessores tipados por domínio, em um lugar |
| R15 | **Roadmap longo demais para uma pessoa; parar no meio** | **Alta** | Médio | Cada milestone é demonstrável sozinho e o produto fica melhor mesmo se o próximo nunca vier. M0–M2 já entregam o argumento comercial |
| R16 | **Perder o que torna este repo bom** (as sete invariantes) | Média | **Alto** | §1.5 lista as sete. Cada uma tem teste. Todo PR do roadmap roda a suíte inteira |

**Os dois riscos que merecem atenção desproporcional são R2/R3 e R16, e a
decisão de §1.3 mexeu nos dois em direções opostas.**

**R2/R3 subiu.** A regra dos três usos era a mitigação embutida no spec, e ela foi
suspensa por decisão do dono. O substituto é mais barato e mais rápido, mas é
mais fraco: dois domínios esqueleto escritos por quem escreve o kernel não
descobrem tudo o que dois usuários reais descobririam. O plano compensa pela
**velocidade de falha** (M0, não M5) e pelo **critério binário** (`diff` do
kernel vazio), não fingindo que o risco sumiu. Aceito, conscientemente, e
registrado.

**R16 subiu junto, e por um motivo menos óbvio.** Com a conciliação rebaixada a
fixture, a tentação de tratá-la como descartável **inclusive nos testes** é real
— e é exatamente quando ela é mais necessária (§19.1, §21.4 item 4). A
mitigação não é disciplina: é o job `conciliador` do CI e o golden continuarem
obrigatórios em todo PR, sem exceção prevista no roadmap.

**O que a decisão de §1.3 tirou do plano:** a propriedade "parar em qualquer
milestone e ter deixado o produto melhor" não vale mais, porque não há produto.
A propriedade que a substitui é mais fraca e vale nomear: **parar em qualquer
milestone e ter um framework que funciona até ali, com três domínios provando
que funciona.** M0–M2 já entregam isso; antes de M0, não há nada de pé.

---

## 23. Phased Roadmap

> **Sequência revisada em 2026-09-16** pela decisão de §1.3 (regra dos três usos
> suspensa) e pelo rebaixamento da conciliação a implementação de referência.
> As mudanças em relação à primeira versão: os dois domínios esqueleto sobem
> para a Fase 0; `Agent`/`Task`/`Tool` sobe de M5 para M2; CLI/DX sobe de M9 para
> M5; Evaluation desce de M4 para M6; ingestão de formato bancário real sai do
> roadmap e vira `Source` (§3.9).

**Regra que governa todas as fases:** cada fase entra com os 449 testes verdes,
o golden idêntico e `85.3% / FP=0 / FN=0` no job `conciliador`. Conciliação ser
descartável **não** afrouxa isso — ver §19.1.

---

### FASE 0 — Kernel sem domínio, provado por três domínios (→ M0)

**Goal.** Um kernel que não sabe o que é conciliação, com **três** domínios
rodando em cima dele — e a prova de que o segundo e o terceiro não exigiram
tocar no kernel.

**Features.**
- `tests/arquitetura/test_camadas.py` (nasce vermelho, `xfail`)
- `kernel/cost.py`: `Cost`, `Budget`, `CostClass` (+ `CREW`)
- `kernel/work.py`: `WorkItem`, `WorkSet(items)`
- `kernel/resolution.py`: `Resolution`, `Proposal` genérica, `Confidence`
- `kernel/resolver.py`, `kernel/definition.py` (+ `version`)
- `runtime/engine.py::execute()`; `reconcile()` vira casca fina
- `domains/reconciliation/` recebe o que é de domínio
- **`domains/procurement/` e `domains/swe/` — os esqueletos (§19.6)**

**Files/modules affected.** `workflow/*` → `kernel/*`; `agent/proposal.py`
(divide em `kernel/cost.py` + `kernel/resolution.py`); `models.py` → `domains/`;
`matching/*` → `domains/reconciliation/resolvers/` e `runtime/engine.py`;
`metrics.py`, `review/revisor.py`, `agent/investigator.py`, `grill/catalogo.py`.

**Dependencies.** Nenhuma. É o primeiro passo possível.

**Migration work.** Aliases com `DeprecationWarning`: `MatchResult = Resolution`,
re-export de `Cost` em `agent/proposal.py`. `WorkSet.bank`/`.ledger` viram
`@property` sobre `of_kind()` durante a transição. `default_resolvers()` sai do
motor para o domínio — é o que desfaz a circularidade `engine ↔ definition`.

**Tests.** Os 449 existentes, sem mudança de asserção (só de import). Novos:
camadas; `WorkItem` preserva identidade; `Resolution` rejeita conjunto vazio;
ordem relativa `REGRA < AGENTE < CREW < HUMANO`; `WorkSet.without()` não aceita
`ResolverOutput`; **cascata sem nenhum resolver `REGRA` (o caso degenerado do
`domains/swe/`) produz `deterministic_rate` bem definida** — a guarda que
`metrics.py` já documenta e que nunca foi exercida por um domínio real.

**Acceptance criteria.**
1. `pytest` → 449+ passando.
2. `orchestrator --seed 1 --n 500` → `85.3%`, FP=0, FN=0.
3. `tests/golden/cascata_12_sementes.json` idêntico, **sem regenerar**.
4. `grep -rE "BankEntry|LedgerEntry|DivergenceType" src/orchestrator/kernel/` → vazio.
5. Teste de camadas verde, com a baseline em **zero** violações de dependência.
6. **`git diff --stat src/orchestrator/kernel/` no PR dos dois domínios → vazio.**

**Risks.** R1 (alto) — mitigado por 1–3 serem comandos, não julgamento.
R2/R3 (alto) — **o critério 6 é o teste desse risco**, e é a razão de os
esqueletos estarem aqui e não em M5.

**DoD.** Kernel sem domínio; três domínios rodando; camadas impostas por teste.

---

### FASE 1 — Run, Event, Store, Context e `Source` (→ M1)

**Goal.** Toda execução tem identidade, histórico e uma fonte de entrada
nomeada — e as dependências chegam aos resolvers por contexto tipado.

**Features.**
- `kernel/run.py`, `kernel/event.py`
- `storage/protocols.py` + `storage/jsonl/`
- `runtime/context.py::RuntimeContext` — **mata o `inspect.signature`**
- `runtime/reliability.py`: timeout, `RetryPolicy`, `IdempotencyKey`
- `_validar()` de saída de resolver **no motor** (id fantasma)
- `Source` + `input_ref`: sintético vira **uma** implementação (`synth:...`);
  `ListSource` trivial para os domínios esqueleto
- API: `GET /api/runs`, `GET /api/runs/{id}`; **remove o `lru_cache`**

**Dependencies.** Fase 0.

**Migration work.** Script de ~15 linhas reescrevendo o escopo dos JSONL de
`s1-n300-t0.15` para `synth:s1-n300-t0.15`. `data/` não é versionado: o alcance é
a máquina do dev. `reconcile()` mantém assinatura.

**Tests.** `Run` persiste e relê byte a byte; eventos emitidos em ordem
determinística; `_validar` levanta em id fantasma; timeout interrompe; retry de
resolver pago verifica orçamento antes de cada tentativa; **um teste que renomeia
o parâmetro `fila` e prova que agora quebra alto** — o defeito que
`test_fabrica.py` hoje só documenta.

**Acceptance criteria.**
1. `GET /api/runs` lista execuções com custo, estado e duração.
2. Reexecutar a mesma `Source` produz os mesmos ids (idempotência de entrada).
3. Nenhum `lru_cache` em `api/`; nenhum `inspect.signature` em `src/`.
4. Os três domínios produzem `Run` válido.

**Risks.** R8 (baixo), R11 (médio).

**DoD.** Uma execução é uma entidade consultável, com fonte nomeada.

---

### FASE 2 — Agent, Task, Tool e Registry (→ M2) ★

**Goal.** A API pública do framework: declarar agente, ferramenta e task sem
tocar no kernel.

**Features.** `AgentSpec` + `Agent` (o laço extraído de `Investigator`, sem uma
linha de lógica nova); `ToolRegistry` + `ToolSpec` + `ToolPermission`;
`OutputSchema` + `Guardrail`; `Stage.retry`/`timeout_ms`/`guardrails`; `Task()`
como açúcar sobre `Stage`; `ResolverRegistry` com entry points.

**Dependencies.** Fases 0 e 1.

**Migration work.** `Investigator` vira `Agent(spec=SPEC_INVESTIGADOR)`.
`TOOL_SCHEMAS` deixa de ser lista literal e sai do registry.
`eval/assinatura.py` continua reusando os mesmos schemas — agora do registry, o
que já é o encaixe do `MCPToolAdapter` da Fase 11.

**Tests.** **Os 714 testes de `test_investigator.py` passam contra o `Agent`
genérico, sem mudança de asserção** — é o critério de que a extração não perdeu
nada. Registry recusa `WRITE` sem compensadora e nome duplicado. As duas capturas
invertidas (estreita no modelo, larga na ferramenta) preservadas com teste
próprio e comentário.

**Acceptance criteria.**
1. `domains/swe/` ganha um agente de verdade declarado em ~20 linhas.
2. Nenhuma regressão de precisão/custo na avaliação existente (`agent_eval`).
3. Registry é a única fonte de schema de ferramenta.

**Risks.** R2 (alto) — esta fase é onde a abstração encontra o segundo usuário
real. R7 (médio): um PR que unifique as duas capturas deve ser recusado.

**DoD.** `from orchestrator import Agent, Task, Tool` é suficiente para declarar
um agente novo.

---

### FASE 3 — Policy Engine (→ M3)

**Goal.** O runtime decide, por item, como o trabalho é executado.

**Features.** `kernel/policy.py`; `runtime/policy_engine.py` com as 7 regras
ordenadas; `PolicyDecision` no `Run` e no trace; `Stage.policy`;
`ctx.value_at_risk` fornecido pelo domínio; `Autonomy` (sem `AGIR_SE_SEGURO`).

**Dependencies.** Fases 0 e 1.

**Migration work.** `POLITICA_ATUAL` descreve exatamente o comportamento de hoje.
A fase entra **sem mudar nenhum número**; política econômica é opt-in.

**Tests.** Cada uma das 7 regras isolada; ordem de avaliação travada; **nenhuma
política consegue inverter a ordem de custo** (invariante nº 2);
`PolicyDecision` registra motivo em todo pulo; `Autonomy.OBSERVAR` nunca chama
classe > `REGRA`, com `ClienteAusente` como tranca.

**Acceptance criteria.**
1. `POLITICA_ATUAL` → resultado byte a byte igual ao da Fase 2.
2. `POLITICA_ECONOMICA` reduz custo medido e registra o motivo de cada pulo.
3. `domains/swe/` (cascata sem `REGRA`) e `domains/reconciliation/` usam a mesma
   política sem código condicional por domínio.

**Risks.** Política virar inauditável — mitigado pela ordem fixa e `reason`
obrigatório.

**DoD.** A tese é executável: duas políticas, mesmo dataset, custos diferentes,
ambos explicados.

---

### FASE 4 — Observabilidade (→ M4)

**Goal.** Toda execução é inspecionável do run até a chamada de ferramenta.

**Features.** `kernel/trace.py`; `observability/collector.py` assinando o
`EventBus`; latência em todo span; custo por span; `Proposal.trace` vira
**derivado** dos spans (uma fonte, não duas); `observability/otel.py` (extra).

**Dependencies.** Fase 1 (eventos).

**Tests.** Árvore bem formada (todo pai existe, sem ciclo); soma dos custos dos
filhos = custo do pai; span `POLICY` existe mesmo quando pula; desligar
observabilidade não muda resultado.

**Acceptance criteria.**
1. Árvore de spans da §13.1 é produzida para os três domínios.
2. Custo por resolver/item/modelo bate com o total do `Run`.
3. `observability.spans: false` → resultado idêntico.

**Risks.** R10 (baixo).

**DoD.** Um item é auditável do input ao desfecho, com custo e latência.

---

### FASE 5 — CLI, SDK e DX (→ M5) ★

**Goal.** Um terceiro consegue instalar, criar um projeto e rodar um workflow.

**Por que aqui e não em M9.** Com a regra dos três usos suspensa, feedback
externo é o único substituto real que sobrou para validar a abstração. Feedback
externo exige que alguém consiga usar o framework sem ler o código-fonte.

**Features.** Despachante de subcomandos com alias legado; `orchestrator init`
com o scaffold da §16.3; `orchestrator.yaml` com precedência testada;
`orchestrator run/runs/trace/cost`; `__init__.py` público curado; três exemplos
(um por domínio); README de quickstart.

**Dependencies.** Fases 1–4.

**Acceptance criteria.**
1. Numa máquina limpa: `pip install -e .` → `orchestrator init x` → editar um
   arquivo → workflow roda.
2. `orchestrator --seed 1 --n 500` continua funcionando (job do CI verde).
3. `from orchestrator import Agent, Task, Workflow, Tool` é suficiente.

**Risks.** R13 (médio) — congelar contrato cedo demais. Mitigação: `0.x`, quebra
permitida e anunciada; publicar no PyPI só ao fim desta fase.

**DoD.** O quickstart funciona numa máquina limpa, para os três domínios.

---

### FASE 6 — Evaluation (→ M6)

**Goal.** Comparar prompt, política, cascata e modelo sobre o mesmo dataset, e
detectar regressão.

**Por que desceu de M4 para M6.** O argumento original era que o dataset de
avaliação é um ativo que acumula correção humana de produção ao longo de meses.
**Com a conciliação descartável, não há produção de onde colher.** A avaliação
continua necessária — é feature de framework e é o gate da Fase 8 — mas deixou
de ser urgente. Registrado em §1.4.

**Features.** `evaluation/case.py`, `dataset.py`, `evaluator.py`,
`benchmark.py`, `regression.py`, `harvest.py`; assinatura de `HUMANO_DECIDIU`;
`microcents_per_correct_proposal`; `orchestrator benchmark --arms a,b`; job de CI
de regressão **não-pago**.

**Dependencies.** Fases 1 e 4.

**Migration work.** `metrics.evaluate` vira um `Evaluator`; o gabarito sintético
vira uma `Provenance` entre duas. Definições de FP (sobreposição) e FN
(contenção total) preservadas — decisão 24.

**Tests.** `harvest` produz caso para os 3 vereditos; caso não avalia o run que o
originou; `RegressionCheck` falha em queda de precisão **e** em aumento de custo;
regressão por **mínimo** entre sementes (decisão 26); benchmark A/B com
`FakeLLMClient` produz tabela comparável a custo zero.

**Acceptance criteria.**
1. `orchestrator benchmark --arms opus,sonnet` compara precisão **e** custo por
   proposta correta.
2. Comparar **prompt A × B** e **política A × B** funciona pelo mesmo mecanismo.
3. Um prompt deliberadamente pior é detectado como regressão pelo CI.
4. Nenhum caminho pago no CI.

**Risks.** R5 (alto), R6 — mitigado pela `IdempotencyKey` da Fase 1.

**DoD.** Qualquer variável do runtime é comparável sem contaminar o runtime.

---

### FASE 7 — Human-in-the-loop formalizado (→ M7)

**Goal.** Pausa e retomada com nome, estado e API.

**Features.** `RunState.AGUARDANDO_HUMANO`; `workflow.resume(run_id)`;
`ReplayResume` explícito e testado; `Fila` dividida em `ProposalStore` /
`DecisionLog` / `ReviewQueue`; `orchestrator review` no terminal.

**Dependencies.** Fase 1.

**Tests.** `resume` converge ao mesmo resultado de executar do zero com as
decisões no log; `cost_delta == 0` quando só regras rodam; decisão obsoleta
continua virando silêncio (`test_revisor.py` preservado inteiro).

**Acceptance criteria.**
1. Run para em `AGUARDANDO_HUMANO` com lista de pendentes.
2. `resume` fecha o run sem reinvestigar o já investigado.
3. Funciona nos três domínios.

**DoD.** Pausar e retomar é operação nomeada, testada e observável.

---

### FASE 8 — Crew (→ M8)

**Goal.** Múltiplos agentes num item, contidos por um `Resolver`.

**Features.** `crew/crew.py` (`CostClass.CREW`), `Process.SEQUENTIAL` e
`HIERARCHICAL`, `SharedContext`, ferramenta `delegar_para`, conflito por
abstenção (default) ou síntese.

**Dependencies.** Fase 2 (técnica) + **Fase 6 (gate de medição)**.

**Tests.** Crew nunca devolve `Resolution`; orçamento do crew é teto do conjunto;
desacordo vira proposta de baixa confiança com as duas hipóteses;
`SharedContext` atribui toda escrita; manager hierárquico não executa trabalho.

**Acceptance criteria.**
1. Crew aparece na cascata ordenado entre `AGENTE` e `HUMANO`.
2. Benchmark compara `agente` × `crew` no mesmo dataset: precisão **e** custo.
3. **Se o crew não ganhar na medição, ele não entra em nenhum default** — e o
   resultado negativo é registrado em `DECISOES.md`.

**Risks.** R4 (custo). Complexidade sem ganho — mitigado pelo critério 3.

**DoD.** Multi-agente existe, é medido, e usá-lo é uma decisão com número.

---

### FASE 9 — Memory e Knowledge (→ M9)

**Goal.** Contexto histórico sem acoplar o core a vector DB.

**Features.** `MemoryStore` e `KnowledgeSource` Protocols; `InMemoryStore`;
`SQLiteStore` (FTS5); destilação `decisões confirmadas → memória semântica`;
`Passage` sempre com fonte.

**Dependencies.** Fases 1 e 6.

**Acceptance criteria.**
1. Kernel sem menção a embedding/vetor/índice (grep).
2. Benchmark com e sem memória, medido.
3. Passagem recuperada entra no prompt **rotulada como recuperada**.

**DoD.** Memória é adapter opcional, medido, com o caminho de graduação para
regra aberto (§11.3).

---

### FASE 10 — Dashboard (→ M10)

**Goal.** Ver runs, traces, custo e avaliação, **estendendo** o canvas.

**Features.** Telas Runs / Run / Item / Custo / Avaliação; rotas de leitura;
`storage/sqlite/` se a listagem ficar lenta; seletor de domínio.

**Acceptance criteria.**
1. Da lista de runs até a chamada de ferramenta de um item, em cliques.
2. Sem build step.
3. Nenhum endpoint gasta dinheiro (`tests/api/test_execucao.py` preservado).

**DoD.** A tese cabe numa tela, para qualquer um dos três domínios.

---

### FASE 11 — Ecossistema (→ M11)

**Goal.** Preservar os caminhos; construir só o que tiver caso.

**Features (cada uma atrás de gatilho, §21).** `MCPToolAdapter` (precisa de
`ToolPermission`, que existe desde a Fase 2); `RemoteAgentResolver` (A2A, depois
da Fase 8); `TemporalExecutor` (só no Tier 3); plugins de terceiro publicados.

**DoD.** Cada item tem gatilho registrado e **nenhum foi construído sem ele**.

---

## 24. Milestones

| # | Milestone | Demonstração | Fase |
|---|---|---|---|
| **M0** | **Kernel sem domínio, provado por três** ★ | `diff` do kernel vazio no PR dos dois domínios novos; 449 testes verdes; `85.3%` intacto | 0 |
| **M1** | **Execução é uma entidade** | `GET /api/runs` lista runs dos três domínios, com custo, estado e duração | 1 |
| **M2** | **API pública** ★ | `from orchestrator import Agent, Task, Tool` declara um agente novo em ~20 linhas; os 714 testes do investigador passam contra o `Agent` genérico | 2 |
| **M3** | **O runtime decide** | Mesmo dataset, duas políticas, custos diferentes, cada pulo explicado | 3 |
| **M4** | **Execução inspecionável** | `orchestrator trace <run-id>`: árvore com custo e latência até a ferramenta | 4 |
| **M5** | **Usável por terceiro** ★ | Máquina limpa: `pip install` → `init` → workflow rodando | 5 |
| **M6** | **Tudo é comparável** | `benchmark --arms` compara modelo, prompt e política; CI pega regressão | 6 |
| **M7** | **Pausa e retomada** | Run em `AGUARDANDO_HUMANO`; `resume` fecha com custo delta zero | 7 |
| **M8** | **Multi-agente medido** | `agente` × `crew` no mesmo dataset; decisão por número, inclusive negativa | 8 |
| **M9** | **Memória como adapter** | Benchmark com/sem memória; kernel sem vector DB | 9 |
| **M10** | **Dashboard** | Da lista de runs à chamada de ferramenta, em cliques | 10 |
| **M11** | **Fronteira de ecossistema** | Cada gatilho registrado como disparado ou não | 11 |

**Os três milestones marcados com ★ são os que mudaram de posição** pela decisão
de §1.3, e são os que carregam o risco aceito:

- **M0** agora carrega a validação inteira da abstração. É o milestone mais
  importante do roadmap e o único cujo critério de aceitação (`diff` do kernel
  vazio) pode reprovar o desenho deste documento.
- **M2** subiu de M5 porque virou entregável, não refatoração.
- **M5** subiu de M9 porque feedback externo é o substituto que sobrou para a
  regra dos três usos.

**Se houver orçamento de tempo para só três milestones, são M0, M1 e M2** — é o
mínimo que constitui um framework: kernel genérico validado, execução com
identidade, e uma API pública para declarar trabalho.

## 25. Definition of Done

### 25.1 Por PR

- [ ] `pytest` verde (449 + novos)
- [ ] `ruff check src tests` limpo
- [ ] `orchestrator --seed 1 --n 500` → `85.3%`, FP=0, FN=0
- [ ] Golden de 12 sementes idêntico **ou** regeneração justificada no corpo do PR
- [ ] `tests/arquitetura/test_camadas.py` verde
- [ ] Nenhum caminho novo de API até o modelo (`tests/api/test_execucao.py` verde)
- [ ] Toda config nova tem guarda em `__post_init__` que falha alto
- [ ] Todo `try/except` largo tem comentário dizendo por que é largo
- [ ] Toda decisão não óbvia comentada com a alternativa rejeitada
- [ ] Nenhuma dependência de runtime nova sem ADR

### 25.2 Por milestone

- [ ] A demonstração da tabela §24 roda numa máquina limpa
- [ ] As sete invariantes da §1.5 continuam com teste
- [ ] Decisões tomadas sem consulta registradas em `DECISOES.md` com alternativa
      e custo de estar errado
- [ ] README atualizado com o que o milestone entrega — **medido**, não prometido
- [ ] ADRs do milestone escritos e commitados

### 25.3 Do projeto (o que "pronto" significa)

O runtime está pronto quando:

1. Um domínio novo cabe em `domains/` sem tocar em `kernel/` — **provado** por
   `git diff --stat` vazio.
2. Uma execução pode ser pausada, retomada e auditada do input ao desfecho.
3. O sistema decide, por item, entre resolver/agente/crew/humano, e **registra
   por quê**.
4. Toda execução reporta custo, latência e tokens por span.
5. Uma correção humana vira caso de avaliação automaticamente.
6. Uma regressão de precisão ou de custo falha o CI.
7. O conciliador continua entregando `85.3%`, FP=0, FN=0.
8. Nada do anti-escopo §21 foi construído sem gatilho registrado.

**Os itens 1 e 7 são os que carregam a decisão de §1.3.**

O item 1 é a prova de que a abstração é genérica — o substituto que sobrou
quando a regra dos três usos foi suspensa, e a razão de os dois domínios
esqueleto entrarem em M0.

O item 7 é a prova de que ela foi construída **sem quebrar o que já funcionava**.
A conciliação deixou de ser o produto, mas continua sendo o único corpo de código
complexo o bastante para que "os testes passam" signifique alguma coisa. No dia
em que alguém propuser relaxar o `85.3%` porque "a conciliação é descartável
mesmo", a resposta está em §19.1 e em §21.4 item 4: descartável é não investir
nela, não é abrir mão da única rede que existe.

---

## 26. Suggested Repository Structure

Ver §4.1 para a árvore completa. Resumo do estado final:

```text
agent-orchestrator/
├── src/orchestrator/
│   ├── kernel/          # camada 0 — zero deps. Work, Resolution, Resolver,
│   │                    #   Cost, Policy, Run, Event, Trace, Definition
│   ├── runtime/         # camada 1 — engine, context, policy_engine,
│   │                    #   reliability, resume, registry
│   ├── storage/         # camada 1 — protocols + jsonl/ + sqlite/
│   ├── observability/   # camada 2 — collector, metrics, otel (extra)
│   ├── agent/           # camada 2 — agent, loop, llm, router, providers/,
│   │                    #   tools/, output, memory/
│   ├── human/           # camada 2 — decision, reviewer, queue
│   ├── crew/            # camada 3 — crew, process, shared
│   ├── evaluation/      # camada 3 — case, dataset, evaluator, benchmark,
│   │                    #   regression, harvest
│   ├── domains/         # camada 4 — reconciliation/ (+ procurement/ em M5)
│   ├── authoring/       # camada 4 — a entrevista (hoje grill/)
│   ├── api/             # camada 5
│   └── cli/             # camada 5
├── adapters/            # opcionais: mcp/, a2a/, temporal/, vector/
├── web/                 # canvas vanilla, estendido
├── docs/
│   ├── adr/             # ADR-01..14
│   └── superpowers/     # specs e planos (convenção existente)
├── evaluations/         # cases/ e datasets/ — VERSIONADOS (o ativo)
├── data/                # runs, filas, traces — NÃO versionado
└── tests/
    ├── arquitetura/     # test_camadas.py — a fronteira
    ├── kernel/ runtime/ storage/ observability/ agent/ human/
    ├── crew/ evaluation/ domains/ api/ cli/
    └── golden/          # cascata_12_sementes.json
```

**Três propriedades desta estrutura, explicitadas:**

1. **`evaluations/` é versionado e `data/` não.** É a decisão de ativo do projeto
   visível na árvore. (Com a ressalva do spec §8: caso colhido de cliente precisa
   ser anonimizado pelo `harvest` antes de entrar no git.)
2. **`adapters/` fica fora de `src/orchestrator/`.** São instaláveis separados,
   opcionais, e nenhum é importado pelo core — o que o teste de camadas garante.
3. **`domains/` é folha.** Nada importa dela. Se algo precisar, o conceito está na
   camada errada.

---

## 27. First 10 PRs

> **Revisada em 2026-09-16.** A ingestão de formato bancário (antigo PR #8) saiu
> da lista e foi substituída pelos **dois domínios esqueleto (#6)** — a troca
> que a decisão de §1.3 exige, porque o que estava barrando a plataforma era o
> produto, e o que passa a barrar é a validação da abstração.

### Status em 2026-09-16

| PR | Estado | Onde |
|---|---|---|
| #1 catraca de camadas | ✅ | PR #6 (M0) |
| #2 `kernel/cost.py` | ✅ | PR #6 (M0) |
| #3 `WorkItem` / `WorkSet` | ✅ | PR #6 (M0) — junto com #4 |
| #4 `Resolution` | ✅ | PR #6 (M0) |
| #5 `runtime/engine.execute()` | ✅ | PR #6 (M0) |
| #6 dois domínios esqueleto | ✅ | PR #6 (M0) — em 3 commits, ver P6.24 |
| #7 `Run` + `EventBus` + `RunStore` | ✅ | PR #7 (M1) |
| #8 `WorkflowContext` | ✅ | PR #7 (M1) |
| #9 `Source` + `input_ref` | ✅ | PR #7 (M1) |
| #10 `ExecutionPolicy` | ✅ | PR #9 (M3) |

**Além dos dez:** M2 inteiro (`Agent`, `AgentSpec`, `ToolRegistry`, `Task`) no
PR #8, e M3 (`ExecutionPolicy` + as 7 regras) no PR #9.

**Medido ao fim do M3:** 566 testes (eram 449), **13 arestas ilegais** (eram
23), `85.3% / FP=0 / FN=0` intactos, golden idêntico, CI verde nas 6 checagens
dos quatro PRs.

Três das cinco causas de acoplamento estão fechadas:

| Causa | Arestas | Estado |
|---|---|---|
| 1 — tipos de domínio fora do domínio | 10 | kernel saiu; resta `agent` e `human` → PR #12 |
| 2 — circularidade `engine ↔ definition` | 0 | ✅ PR #5 |
| 3 — `api.app → cli` | 0 | ✅ PR #9 |
| 4 — avaliação lê saída da execução | 1 | M6 |
| 5 — agente usa a fila como cache | 1 | PR #11 |

**Duas descobertas que mudaram o plano** (as duas em §27 PR #6): `Proposal` não
era genérica (`tipo: DivergenceType`) e `Proposal.divergence_id` era vocabulário
de conciliação. Nenhuma das duas aparece numa leitura do código — foi preciso
escrever o segundo domínio. É o argumento inteiro de por que os esqueletos
entram em M0.

---

Cada um é pequeno, entra verde, e não exige que dois conceitos mudem juntos.

---

**PR #1 — `test_camadas`: a fronteira, imposta por catraca** ✅ *entregue*
`tests/arquitetura/{camadas,test_camadas}.py`. Varre `src/orchestrator` com
`ast`, mapeia módulo → camada alvo, valida imports contra a tabela da §4.2.
**Por quê primeiro:** transforma a §2.1 em falha executável, com arquivo e
linha. Sem ele, "não quebre as camadas" é um pedido.

**Desvio do plano, e a razão.** O plano pedia `xfail`. Entregue como **baseline
com catraca**, verde desde o primeiro dia:

- violação **nova** → `test_sem_violacao_nova` falha (regressão barrada);
- violação **corrigida** sem apagar a linha → `test_baseline_honesta` falha
  (o ganho tem que aparecer no diff).

`xfail` é um check vermelho permanente, e este repositório já recusou isso uma
vez pelo motivo certo — ver o comentário sobre `ruff format` em
`.github/workflows/ci.yml`: *"um check de formato vermelho desde o primeiro dia
é um check que as pessoas aprendem a ignorar."* Além disso, `xfail` não detecta
violação nova; a catraca detecta nos dois sentidos.

**Aceitação (verificada):** 19 testes novos, 468 na suíte, ruff limpo, `85.3%`
intacto. Catraca provada nos dois sentidos por experimento — violação
introduzida no `cost_class.py` fez 2 testes falharem; entrada obsoleta na
baseline fez `test_baseline_honesta` falhar.
*~420 linhas (mapa + testes). Risco: nenhum no produto.*

---

**PR #2 — `kernel/cost.py`: `Cost` sai de `agent/`**
Move `Cost`, `_PRECOS`, `modelo_precificado` e `CostClass` para `kernel/cost.py`.
Acrescenta `Budget` e `CostClass.CREW`. `agent/proposal.py` re-exporta com
`DeprecationWarning`.
**Por quê agora:** mata a inversão 1 sem que nenhum outro conceito mude. Menor
mudança com maior efeito estrutural.
**Dependências:** #1. **Impacto:** imports em 9 arquivos.
**Aceitação:** 449 verdes; camadas cai para 2 violações; teste novo travando
`REGRA < AGENTE < CREW < HUMANO` (ordem relativa, nunca os valores).
*~200 linhas movidas. Risco: baixo.*

---

**PR #3 — `WorkItem` e `WorkSet(items)`**
`kernel/work.py`. `WorkSet.bank`/`.ledger` viram `@property` sobre `of_kind()`.
Os 3 matchers, o investigador e o revisor passam a usar acessores tipados do
domínio.
**Por quê agora:** destrava tudo, e é a mudança de maior risco — vem enquanto a
superfície é a menor que vai ser.
**Dependências:** #2.
**Aceitação (binária, não editorial):** golden idêntico sem regenerar; `85.3%`;
FP=0; FN=0; 449 verdes; `grep -r "BankEntry" src/orchestrator/kernel/` vazio.
*~400 linhas tocadas. Risco: **ALTO** (R1). Revisar sozinho, sem batch.*

---

**PR #4 — `Resolution` substitui `MatchResult`**
`kernel/resolution.py` com `Resolution(item_ids, produced_by, rule, evidence)` e
`Proposal` genérica. `MatchResult` vira alias. `metrics.py` deriva o lado a
partir do `WorkSet`, preservando FP por **sobreposição** e FN por **contenção
total** (decisão 24).
**Por quê agora:** completa o par com #3. Adiar deixaria o kernel meio
de-domainizado, que é pior que qualquer um dos dois estados.
**Dependências:** #3. **Aceitação:** igual a #3, mais teste explícito de que a
assimetria FP/FN não mudou.
*~300 linhas. Risco: alto.*

---

**PR #5 — `runtime/engine.execute()` e o fim da circularidade**
Move `reconcile` → `runtime/engine.py::execute()`. `default_resolvers()` sai do
motor para `domains/reconciliation/workflow.py`. Os dois imports locais
circulares somem. `reconcile()` vira casca fina.
**Por quê agora:** com #3 e #4, o motor já é genérico; falta o endereço.
**Dependências:** #4. **Aceitação:** zero import local justificado por
circularidade em `src/`; as 6 arestas da CAUSA 2 saem de `VIOLACOES_CONHECIDAS`
no mesmo commit.
*~250 linhas. Risco: médio.*

---

**PR #6 — `domains/procurement/` e `domains/swe/`: o teste da abstração** ★
Dois domínios esqueleto, ~80 linhas cada, chamando `execute()` com um `WorkSet`
construído à mão. Procurement: cascata `REGRA → REGRA → AGENTE → HUMANO`. SWE: o
**caso degenerado**, `AGENTE → HUMANO`, sem nenhum resolver de classe `REGRA`.
Nenhum dos dois precisa ser útil; os dois precisam rodar.
**Por quê agora e não em M5:** é o substituto de engenharia para a regra dos três
usos, que §1.3 suspendeu. Escrito enquanto o kernel ainda está mole, cada atrito
é uma correção de um dia; escrito em M5, é uma descoberta de um mês.
**Dependências:** #5.
**Aceitação:**
1. **`git diff --stat src/orchestrator/kernel/` neste PR → vazio.** Se não vier
   vazio, o desenho deste documento está errado e o PR é a prova — informação,
   não fracasso.
2. `domains/swe/` exercita a guarda que `metrics.py` já documenta e que nunca foi
   exercida: cascata sem `REGRA` não tem a chave em `matches_by_class`, e
   `deterministic_rate` precisa sair `0.0` em vez de estourar `KeyError`.
3. Um teste por domínio, rodando ponta a ponta.
*~200 linhas. Risco: baixo em código, **o mais alto do roadmap em informação**.*

---

**PR #7 — `Run`, `EventBus` e `RunStore` (JSONL)**
`kernel/run.py`, `kernel/event.py`, `storage/protocols.py`,
`storage/jsonl/run_store.py`. `execute()` cria `Run`, emite eventos, persiste.
`ReconcileResult.from_run()` para compatibilidade.
**Por quê agora:** destrava observabilidade, HITL e avaliação de uma vez.
**Dependências:** #6 (os três domínios validam o `Run` de saída).
**Aceitação:** `Run` persiste e relê byte a byte; eventos em ordem
determinística; os três domínios produzem `Run` válido; CLI inalterada.
*~450 linhas. Risco: médio.*

---

**PR #8 — `RuntimeContext`: morte do `inspect.signature`**
`runtime/context.py`. `WorkflowFactory` Protocol.
`api/app.py::_construir_definicao` some. `Resolver.resolve(work, ctx)`.
**Por quê agora:** `Run` e `EventBus` precisam chegar aos resolvers, e inspeção
por nome de parâmetro não escala para cinco dependências.
**Dependências:** #7. **Aceitação:** zero `inspect.signature` em `src/`; **um
teste que renomeia o parâmetro e prova que agora quebra alto** — o defeito que
`test_fabrica.py` hoje só documenta.
*~200 linhas. Risco: baixo.*

---

**PR #9 — `Source` e `input_ref`**
`Source` Protocol. `build_benchmark` vira **uma** implementação (`synth:...`);
`ListSource` trivial para procurement e SWE. `Fila` reescopada por `input_ref` +
script de migração. `api/app.py` deixa de importar de `cli.py`.
**Por quê agora:** mata a inversão 3 e tira a identidade de execução de cima de
uma tupla de parâmetros de benchmark. **Não inclui parser de OFX/CNAB** — saiu do
escopo em §1.3.
**Dependências:** #7. **Aceitação:** `85.3%` intacto via
`--input synth:s1-n500-t0.15`; os três domínios têm `Source`; reexecutar a mesma
`Source` produz os mesmos ids.
*~250 linhas. Risco: médio.*

---

**PR #10 — `ExecutionPolicy` no modo "igual a hoje"**
`kernel/policy.py`, `runtime/policy_engine.py` com as 7 regras ordenadas,
`PolicyDecision` no `Run`. `POLITICA_ATUAL` reproduz o comportamento atual
exatamente.
**Por quê agora:** entra sem mudar nada, o que torna o PR seguro; e a partir dele
qualquer política nova é um dataclass, não uma mudança no motor.
**Dependências:** #8. **Aceitação:** resultado byte a byte igual ao de #9;
`POLITICA_ECONOMICA` em teste reduz custo e registra motivo; teste provando que
**nenhuma política consegue inverter a ordem de custo**.
*~300 linhas. Risco: baixo — o comportamento default não muda.*

---

**Depois dos 10:** #11 `IdempotencyKey` (o bug latente da §6.4 — desceu de
posição porque só vira crítico quando a avaliação rodar sobre fila de produção,
agora em M6); #12 `AgentSpec` + `Agent` genérico; #13 `ToolRegistry`;
#14 spans + collector; #15 `orchestrator trace`.

**Ordem de revisão sugerida.** #3 e #4 são os únicos que merecem revisão dedicada
e sem batch: são os que podem mover os números. #6 merece atenção de outro tipo —
não porque possa quebrar algo, mas porque é o único PR cujo resultado pode
invalidar o desenho.

## Apêndice A — Comparação com CrewAI

Descritiva. Não há avaliação de qual é melhor: os dois resolvem problemas
diferentes, e a maior parte da diferença vem disso.

| Agent Orchestrator | CrewAI | Como se comparam |
|---|---|---|
| `Agent` (hoje `Investigator`) | `Agent(role, goal, backstory)` | CrewAI tem uma abstração madura e configurável; AO tem **um** agente, com laço mais rígido (turnos, orçamento, abstenção). AO precisa **extrair a config**; CrewAI já tem. |
| `Stage` / `Task` | `Task(description, expected_output, agent)` | CrewAI descreve a task em **linguagem natural**; AO a descreve como **cascata tipada**. A de AO é serializável e comparável; a do CrewAI é mais rápida de escrever. |
| `WorkflowDefinition` | `Flow` (`@start`/`@listen`/`@router`) | CrewAI é reativo e code-first (decorators); AO é declarativo e data-first (dataclass serializável). AO ganha determinismo e diff auditável; CrewAI ganha expressividade de branching. |
| `Crew` (M7) | `Crew(agents, tasks, process)` | CrewAI tem; AO não. Em CrewAI, `Crew` é o topo; em AO será **um resolver contido num workflow** — a diferença de contenção da §10.1. |
| `Tool` (`ToolContext`) | `BaseTool` + `args_schema` | CrewAI tem registry e ecossistema (CrewAI Tools). AO tem 5 ferramentas com schema estrito, todas read-only, sem registry. **Inspirar-se**: registry e schema declarativo. **Manter diferente**: permissão e custo por ferramenta, que CrewAI não modela. |
| `Fila` (episódica) | `Memory` (short/long/entity, ChromaDB) | CrewAI tem memória embutida com vector DB por padrão. AO não tem memória e **não quer** vector DB no core (§11.1). AO tem algo que CrewAI não tem: memória episódica **com gabarito humano**. |
| **`ExecutionPolicy`** | *(sem equivalente)* | CrewAI tem `max_rpm` e limites de iteração; não há decisão por item entre determinístico/agente/humano baseada em custo, confiança, risco e autonomia. |
| **`Resolver` + `CostClass`** | *(sem equivalente)* | Em CrewAI todo passo é um agente. A ideia de "tente a regra grátis antes de gastar com inteligência" **não tem lugar no modelo**. É a diferença central. |
| **`Evaluation` / `Benchmark`** | `crew.test()` | CrewAI tem avaliação por LLM-as-judge sobre execuções. AO tem gabarito, FP/FN, custo por proposta correta, e (em M6) colheita de correção humana. Profundidade diferente. |
| **Runtime de execução** | `crew.kickoff()` | CrewAI acopla definição e execução no `Crew`. AO separa `WorkflowDefinition` (dado) de `execute()` (motor) — o que permite serializar, versionar, comparar e retomar. |
| **Human-in-the-loop** | `human_input=True` na task | CrewAI pausa e pede input no terminal. AO tem proposta/decisão tipadas, log append-only, tratamento de decisão obsoleta e sinal de divergência. AO está bem à frente aqui. |
| **Custo** | `usage_metrics` (tokens) | CrewAI reporta tokens. AO reporta micro-centavos por resolver, incluindo escrita de cache, com orçamento em dois níveis e falha alta em modelo sem preço. AO está à frente. |

**O que já existe e é bom:** `Resolver`/`CostClass`, contabilidade de custo,
HITL, avaliação com gabarito, separação definição/execução.

**O que falta:** `Agent` configurável, `ToolRegistry`, memória, `Crew`, DX de
scaffold, ecossistema.

**O que vale inspirar:** registry de ferramentas com schema declarativo;
vocabulário público (`Agent`, `Task`, `Crew`, `Workflow`) para reduzir a curva de
quem chega; scaffold de projeto.

**O que deve permanecer diferente:**
1. **A cascata com classe de custo.** É a tese. Em CrewAI, todo passo é agente.
2. **Determinismo.** Controle imperativo, não reativo — o golden depende disso.
3. **Definição como dado**, não como decorators.
4. **Custo como cidadão de primeira classe**, em inteiro, auditado.
5. **HITL como resolver**, não como flag numa task.
6. **Sem vector DB no core.**
7. **`Crew` contido por `Workflow`**, nunca o contrário.

**Não é um clone, e a razão é estrutural:** CrewAI otimiza para *"faça N agentes
colaborarem"*. Este projeto otimiza para *"não gaste com agente o que uma regra
resolve, e prove quanto custou"*. As duas otimizações produzem modelos de dados
diferentes, e a semelhança de vocabulário na superfície não muda isso.

---

## Apêndice B — Arquitetura alvo final

Adaptada ao que a auditoria encontrou: o canvas existe, o `grill` existe, a
cascata é o primitivo, e `Resolver` é o contrato único.

```text
                    ┌────────────────────────────────────┐
                    │              PLATFORM              │
                    │   API  ·  CLI  ·  Canvas/Dashboard │
                    │   authoring (entrevista → spec)    │
                    └──────────────────┬─────────────────┘
                                       │
                    ┌──────────────────▼─────────────────┐
                    │              RUNTIME               │
                    │  Executor → engine.execute()       │
                    │  Run · WorkSet · Event · Context   │
                    │  Policy Engine · Reliability       │
                    │  ReplayResume                      │
                    └──────────────────┬─────────────────┘
                                       │
                         Stage.ordered() — ordem por custo
                                       │
      ┌──────────────┬─────────────────┼─────────────────┬──────────────┐
      ▼              ▼                 ▼                 ▼              ▼
  REGRA          AGENTE             CREW             HUMANO         (lacuna)
      │              │                 │                 │              │
  Resolver        Agent             Crew            Reviewer      declarada,
  determinís-     ├ LLMClient       ├ Agents        ├ Proposal     nunca
  tico            ├ ToolRegistry    ├ SharedCtx     ├ Decision     escondida
  (L1 L2 L3)      ├ OutputSchema    └ Process       └ DecisionLog
                  ├ Guardrails                         (append-only)
                  └ Memory/Knowledge (adapter)
      │              │                 │                 │              │
      └──────────────┴─────────────────┼─────────────────┴──────────────┘
                                       │
                          ┌────────────▼────────────┐
                          │       KERNEL            │
                          │  WorkItem · Resolution  │
                          │  Proposal · Resolver    │
                          │  Cost · Budget · Policy │
                          │  Run · Event · Span     │
                          │      (zero deps)        │
                          └────────────┬────────────┘
                                       │
                          ┌────────────▼────────────┐
                          │     OBSERVABILITY       │
                          │  Trace · Span · Cost    │
                          │  Latency · Tokens       │
                          │  PolicyDecision         │
                          └────────────┬────────────┘
                                       │
                          ┌────────────▼────────────┐
                          │       EVALUATION        │
                          │  EvaluationCase         │
                          │  Dataset · Evaluator    │
                          │  Benchmark · Regression │
                          └────────────┬────────────┘
                                       │
                          ┌────────────▼────────────┐
                          │   correção humana vira  │
                          │   caso  →  benchmark    │
                          │   →  regressão  →  CI   │
                          └─────────────────────────┘
                              o ativo que se acumula
```

**Três diferenças em relação ao desenho do pedido, e a razão de cada uma:**

1. **A lacuna é uma saída de primeira classe**, ao lado das quatro classes de
   custo. O canvas já a desenha, e o spec de composição §3.4 chama isso de "o
   ponto mais valioso da tela". Um runtime que só mostra o que resolveu esconde
   o que importa.
2. **`Observability` e `Evaluation` estão em série, não em paralelo.** A
   avaliação **consome** o trace: sem span, não há o que avaliar por item. Pôr as
   duas lado a lado sugere independência que não existe.
3. **A seta final volta ao CI.** É o que fecha o loop do README e o que torna o
   conjunto de avaliação um ativo em vez de um relatório.
