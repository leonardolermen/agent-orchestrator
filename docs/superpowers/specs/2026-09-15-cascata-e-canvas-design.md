# Cascata de Resolução e Canvas Read-Only — Documento de Design

**Data:** 2026-09-15
**Status:** ✅ **APROVADO — construção autorizada**
**Escopo:** primeira fatia da plataforma de composição (V3)
**Spec pai:** [`2026-09-14-agent-orchestrator-design.md`](2026-09-14-agent-orchestrator-design.md)
**Spec irmão:** [`2026-09-14-composicao-de-workflows-design.md`](2026-09-14-composicao-de-workflows-design.md)

---

## 0. O que este documento decide, e a ressalva que fica registrada

Este documento autoriza a construção da **primeira fatia** da plataforma de
composição: tornar a cascata de resolução um objeto de primeira classe do
domínio e desenhá-la numa tela, sem edição.

**A ressalva, registrada e não repetida.** O §7.1 do spec de composição
condiciona toda construção de plataforma a "três workflows reais e distintos em
produção, com V1 e V2 pagos". Hoje são zero workflows, zero clientes, e o F2 do
spec pai — qualidade medida — não foi atingido porque o agente nunca fez uma
chamada real. O dono do projeto foi informado disso e decidiu construir mesmo
assim. A decisão é dele; o registro é para que, se a deriva para plataforma
cobrar o preço que o spec pai prevê, a causa esteja escrita e datada.

**O que reduz o risco dessa decisão:** desta fatia, a maior parte é **dívida do
V1**, não escopo novo. Duas das três costuras do §3.3 do spec pai nunca foram
implementadas, e o §6 do spec de composição nomeia a uniformidade de resolvers
como lacuna que *deveria ter caído no plano 2* e não caiu.

---

## 1. O estado que motivou

O canvas é a peça 7 de 8 numa cadeia de dependência. Em 2026-09-15:

| # | Peça | Estado |
|---|---|---|
| 1 | Resolver uniforme — regra, agente e humano com a mesma forma | ❌ |
| 2 | Cascata como dado | ❌ |
| 3 | Métricas por resolver | ◐ contagem sim, custo não |
| 4 | Executor | ❌ |
| 5 | Catálogo consultável | ❌ |
| 6 | Gerador prosa → rascunho | ❌ |
| 7 | Canvas | ❌ |
| 8 | Diff com consequência | ❌ |

A peça 1 é a lacuna que o §6 do spec de composição registrou:

> ❌ **Resolvers uniformes: regra e agente com a mesma forma** — lacuna — cai no plano 2

**O plano 2 não a fechou.** A prova está na assinatura que ele produziu:

```python
def reconcile(bank, ledger,
              matchers: list[Matcher] | None = None,
              investigator: Investigator | None = None)
```

Dois parâmetros porque são dois conceitos. `Matcher` tem `layer` e `match()`;
`Investigator` tem `name` e `investigate()`. Não existe cascata no código — há
três regras numa lista e um agente pregado ao lado. **Não se desenha na tela
uma cascata que o domínio não tem**, e desenhar assim mesmo é o modo de falha
que o §3.5 do spec de composição nomeia: selo sem medição é decoração.

---

## 2. Escopo desta fatia

**Dentro:** peças 1, 2, 3 e a metade read-only da 7.

**Fora, com gatilho nomeado:**

| Não construir agora | Desbloqueia quando |
|---|---|
| Edição no canvas | Esta fatia estiver rodando e a definição for estável |
| Versão imutável + histórico (§4.2) | Houver edição — sem editar, toda execução usa a mesma versão |
| Diff com consequência (§4.3) | Houver duas versões para diferir |
| Serialização para DSL/YAML (§4.1) | Anti-escopo do spec pai: 3 workflows em produção |
| Catálogo consultável | Houver gerador de prosa, ou edição |
| Gerador prosa → rascunho | Houver catálogo |
| `Executor` como costura separada | Houver execução que não seja in-process |
| Framework de front | Começar arrastar-e-soltar de resolver |
| Selo do agente por replay de gravação (§5.3) | Houver crédito de API, uma gravação do benchmark, e uma definição `conciliacao-com-agente` para servir |

---

## 3. O domínio: a cascata

### 3.1 O contrato

```python
class CostClass(IntEnum):
    REGRA = 0
    AGENTE = 1
    HUMANO = 2

@dataclass(frozen=True)
class WorkSet:
    """O que ainda não foi resolvido quando este resolver é chamado."""
    bank: list[BankEntry]
    ledger: list[LedgerEntry]

    def as_divergences(self) -> list[Divergence]: ...
    def without(self, matches: list[MatchResult]) -> "WorkSet": ...

@dataclass(frozen=True)
class ResolverOutput:
    matches: list[MatchResult] = field(default_factory=list)   # resolve: sai do pool
    proposals: list[Proposal] = field(default_factory=list)    # propõe: NÃO sai do pool
    cost: Cost = field(default_factory=Cost.zero)

class Resolver(Protocol):
    name: str
    cost_class: CostClass
    def resolve(self, work: WorkSet) -> ResolverOutput: ...
    def describe(self) -> ResolverDescription: ...
```

### 3.2 O motor

```python
def reconcile(bank, ledger, definition=None) -> ReconcileResult:
    definicao = default_definition() if definition is None else definition
    work = WorkSet(list(bank), list(ledger))
    for stage in definicao.stages:
        for r in sorted(stage.cascade, key=lambda r: r.cost_class):
            out = r.resolve(work)
            work = work.without(out.matches)    # proposals sequer aparece
```

É `is None`, não `or`: uma `WorkflowDefinition` explicitamente vazia (`stages=()`)
é *falsy* como qualquer coleção vazia, e `definition or default_definition()`
a substituiria pelos resolvers padrão em silêncio — a mesma classe de defeito
que as decisões #7, #9 e #10 do plano 1 já registraram noutros pontos do
projeto: entrada malformada, ou aqui explicitamente vazia, tratada em silêncio
em vez de honrada ou rejeitada. `is None` distingue "não foi passado" de "foi
passado vazio".

O `sorted` é por stage, não global: a cascata é a unidade de ordenação, e um
stage posterior não pode ter seus resolvers embaralhados com os de um anterior.
Com um stage só — o caso de hoje — os dois dariam no mesmo; com dois, só este
está certo.

### 3.3 Três propriedades que não são acidente

**A ordenação entre classes é derivada; dentro da classe, preservada.**
`sorted` em Python é estável. Numa linha isso entrega o §3.1 e o §3.2 do spec
de composição: a ordem que o especialista deu entre duas regras sobrevive; a
ordem entre uma regra e um agente não é escolhível. Não existe lista de entrada
que ponha agente antes de regra.

**A invariante da proposta vira estrutural.** `work.without(out.matches)` — o
campo `proposals` não aparece na expressão. Não é regra que alguém lembra; é
coisa que o motor não sabe fazer. Isso substitui, por construção, a garantia
que o plano 2 obteve por verificação empírica.

**O agente não muda.** Rodando por último (classe AGENTE), ele chama
`work.as_divergences()` e recebe exatamente a lista que recebe hoje — a mesma
derivação que hoje mora dentro do `reconcile`, uma divergência por lançamento
órfão de cada lado.

### 3.4 As três camadas implementam `Resolver` diretamente

Sem adaptador. O corpo de cada matcher não muda: muda `layer` → `name`, entra
`cost_class = REGRA`, e `match(bank, ledger)` vira `resolve(work)`. Um
adaptador manteria `Matcher` vivo como segundo conceito, que é metade da lacuna
do §6 sobrevivendo com outro nome.

`MatchResult.layer` permanece — é campo de proveniência (quem produziu o
vínculo), não o mesmo conceito que `Resolver.name`, e `metrics.matches_by_layer`
já o consome como taxa por resolver.

### 3.5 Custo por resolver

`ReconcileResult.agent_cost: Cost` vira `cost_by_resolver: dict[str, Cost]`. A
peça 3 exige e a tela exige: um selo por resolver precisa do custo daquele
resolver, não do total do sistema. `metrics.py` passa a somar em vez de ler um
campo único.

---

## 4. A cascata como dado

### 4.1 A definição não descreve a cascata — ela É a cascata

```python
@dataclass(frozen=True)
class Stage:
    name: str
    cascade: tuple[Resolver, ...]

@dataclass(frozen=True)
class WorkflowDefinition:
    id: str
    name: str
    stages: tuple[Stage, ...]
```

`reconcile` recebe uma `WorkflowDefinition`. A alternativa — uma definição
declarativa ao lado, que *descreve* o que o motor faz — permite drift, e drift
entre desenho e motor é a decoração do §3.5 com mais passos. Se a API serializa
o mesmo objeto que o motor executou, a tela não tem como mentir.

### 4.2 Como um resolver vira JSON

Cada resolver responde `describe() -> ResolverDescription`: nome, classe de
custo, o que resolve, uma linha de texto. A definição guarda os objetos vivos,
não ids com um registro que os instancia — isso é o catálogo, e nada nesta
fatia precisa dele. **Gatilho para trocar:** edição ou persistência, porque aí
a definição precisa sobreviver ao processo.

### 4.3 Ressalva sobre `Stage`

O conciliador tem **um** stage, e o §4.4 do spec de composição diz que
aprovação humana é o último resolver de uma cascata, não um stage separado —
então nem a fila de revisão cria um segundo. `Stage` entra mesmo assim por um
motivo só: o JSON é contrato com o front, e `{"stages": [...]}` agora custa
dez linhas enquanto remodelar o front depois custa mais. É estrutura
antecipada, assumida como tal.

---

## 5. A API e o dinheiro

### 5.1 O problema que a API cria

Hoje gastar dinheiro exige digitar `orchestrator-eval` e ver um banner escrito
GASTA DINHEIRO. Um endpoint HTTP apaga todas as barreiras: um F5, um duplo
clique, um prefetch do navegador, uma aba esquecida aberta. Os tetos existentes
são **por divergência** (4.000.000 µ¢) e **por execução** (400.000.000 µ¢);
não há teto *entre* execuções. Cem refreshes são cem execuções, cada uma dentro
do orçamento.

### 5.2 A resposta: o caminho caro não é guardado, é inexistente

```
GET  /api/workflows/conciliacao          → a definição
POST /api/workflows/conciliacao/runs     → executa; NUNCA toca no agente
```

Não é uma flag `incluir_agente`. O endpoint **não tem** como chamar o agente —
não existe corpo de request que o faça gastar. É a mesma filosofia da cascata:
a armadilha cara deixa de ser erro possível e passa a ser coisa que a interface
não sabe expressar.

Consequência: determinístico, e portanto cacheável por `(seed, n, taxa)`.
Refresh não recomputa.

**Nenhum endpoint desta fatia gasta dinheiro. Nenhum.** Isso é pinado por
teste, não prometido — ver §7.

### 5.3 O selo do agente vem de gravação, não de chamada

`RecordingClient` e `ReplayClient` já existem e a gravação guarda o custo real
de cada chamada. Então:

1. Quando houver crédito, rodar `orchestrator-eval` **uma vez** com
   `RecordingClient` contra o benchmark.
2. O canvas mede o selo do agente com `ReplayClient` sobre aquela gravação.
3. Custo por divergência real, taxa real, zero centavo por request, para sempre.

O selo declara a procedência — *"medido em AAAA-MM-DD, gravação X"* — e não
finge ser ao vivo. Enquanto não houver gravação, diz **"não medido"**, que é a
verdade em 2026-09-15 e é pressão útil.

**Anti-escopo desta fatia, não construído.** `default_definition()` — a única
definição que a API serve hoje — não tem agente, então não há selo nenhum para
gravar ou repetir: o que sobra das regras aparece como LACUNA (§6), não como
uma linha AGENTE "não medido". O desenho acima continua correto — não gastar
por request e declarar procedência —, mas só passa a ter o que medir quando
existir uma segunda definição com agente. Ver a tabela do §2: desbloqueia com
crédito de API, uma gravação do benchmark, e uma definição
`conciliacao-com-agente` para servir.

---

## 6. O front

Sem build step: FastAPI serve estáticos, a página busca o JSON e desenha. HTML,
CSS e JS puro.

Isto é o que a tela **de fato** desenha para `default_definition()` — medido,
não um mock imaginado antes de existir front:

```
┌─ conciliar lançamentos ─────────────────────────────┐
│  ① L1   REGRA    US$ 0     84,1% ●                  │
│  ② L2   REGRA    US$ 0      0,0% ●                  │
│  ③ L3   REGRA    US$ 0      2,6% ●                  │
│  —  sem resolver configurado  LACUNA   13,2% ◌      │
└─────────────────────────────────────────────────────┘
```

Duas coisas nessa medição merecem prosa, não só o desenho.

**L2 mede zero, e isso é o design funcionando, não um bug.** A camada de
tolerância roda — ela está na cascata, custa manutenção, tem os próprios
testes — e não resolve nada neste benchmark. A causa está documentada em
`tests/golden/gerar.py`: dos quatro tipos de divergência que o gerador injeta,
nenhum cai dentro da janela de tolerância do L2 (defasagem de prazo,
retenção de imposto e devolução de fundos são construídos deliberadamente fora
dela; pares limpos já são tomados pelo L1 antes de chegar ao L2). Um selo por
resolver existe exatamente para tornar visível esse tipo de fato: uma camada
que existe e não ganha nada com o dataset atual é informação que o especialista
precisa ver, não algo para esconder atrás de uma média.

**A lacuna substitui a linha do agente**, e é mais honesta que um selo escrito
"não medido": `default_definition()` genuinely não tem agente configurado, então
o que as regras não resolvem é **não resolvido**, não "não medido". Não medido
sugere que existe um resolver ali e falta instrumentá-lo; a lacuna diz que não
há resolver nenhum configurado para aquele resto — é o §3.4 do spec de
composição, o ponto na tela onde um especialista do domínio olha e diz "existe
regra pra isso" (ou, aqui, ainda não existe).

Renderizar isso é DOM e CSS; framework não compra nada. Cada hora em bundler é
hora fora da unificação do domínio, que é a parte com valor. O contrato que
sobrevive é o JSON, não o front. **Gatilho para framework:** arrastar-e-soltar
de resolver.

Estrutura e dependência:

```
src/orchestrator/workflow/   definition.py, resolver.py, workset.py
src/orchestrator/api/        app.py, schemas.py
web/                         index.html, style.css, canvas.js
```

`fastapi` e `uvicorn` entram como extra `[api]`, não como dependência dura: o
núcleo continua importável e o CI continua leve sem stack web.

---

## 7. Verificação

### 7.1 O refactor não pode mudar um dígito

Os testes de hoje afirmam **pisos** (mínimo 0,78 entre sementes), e piso não
pega refactor que mexe nos números para cima.

Antes de tocar em qualquer coisa: capturar um **golden file** com a medição de
12 sementes — taxa por semente, contagem por camada, falsos positivos e
negativos. Depois do refactor, reproduzir exatamente.

O golden vira guarda permanente: qualquer mudança futura na lógica de matching
precisa regenerá-lo conscientemente, com explicação no commit. **A mensagem de
falha do teste diz isso**, para ninguém regenerar no automático.

### 7.2 Testes novos que ganham o próprio custo

| Teste | O que quebra se sumir |
|---|---|
| Ordenação derivada | cascata com agente em primeiro roda o agente por último |
| Estabilidade dentro da classe | `[Tolerância, Exato]` preserva essa ordem — é o §3.1 |
| Proposta não remove | `work.without()` ignora `proposals` |
| Anti-drift da API | JSON da definição bate com `default_definition()` real |
| **O endpoint não gasta dinheiro** | espião que grava chamadas a `complete()` + toda `cost_class` da resposta é REGRA |

O último transforma a promessa do §5.2 em teste. **A técnica mudou em
execução e vale registrar por quê.** A ideia original era injetar um
`LLMClient` que levanta em `complete()` e exigir 200 — mas isso não prova
nada: `Investigator._uma()` envolve `complete()` num `except Exception` amplo
por desenho, então o erro injetado vira abstenção silenciosa e o endpoint
responde 200 com ou sem agente de fato ligado. Isso foi demonstrado, não
teorizado — um `Investigator` real foi ligado à definição servida e o teste
antigo continuou passando. A técnica que ficou é duas asserções
independentes: um espião que nunca levanta, só grava cada chamada a
`complete()` numa lista, com a asserção sobre essa lista estar vazia; e uma
verificação estrutural de que todo resolver na resposta de execução é da
classe REGRA. Com um agente ligado, as duas falham, cada uma por um motivo
diferente. Ver `docs/superpowers/DECISOES.md`, Plano 3, para o relato
completo.

Front sem teste automatizado nesta fatia — o contrato é o JSON e ele é testado
do lado do servidor. Gatilho: edição.

---

## 8. Alternativas rejeitadas, com razão registrada

**Dois protocolos, metadado comum só para a tela.** Mudança mínima, risco zero
ao que está medido. Rejeitada: não fecha a lacuna do §6 — o motor continua com
dois parâmetros e o canvas desenharia uma cascata que o domínio não tem.

**Tudo devolve `MatchResult`, com `status: CONFIRMADO | PROPOSTO`.** Um tipo
só, ótimo para a tela. Rejeitada, e é a mais tentadora: hoje é *impossível* uma
proposta sair do pool porque são tipos diferentes. Com `status` vira
possível-mas-verificado — um filtro esquecido e há conciliação fantasma. O
plano 1 já produziu dinheiro fantasma por inferência silenciosa; não se troca
garantia de tipo por convenção.

**Canvas com dados de mentira, ligar no motor depois.** Vira plataforma aos
olhos mais rápido. Rejeitada: é literalmente o modo de falha do §3.5 e do §7.2
do spec de composição.

**App web com framework desde já.** Fundação real para a edição futura.
Rejeitada para esta fatia: gasta a maioria das horas em andaime em vez da
unificação do domínio, e edição não está no escopo.

**Adaptador `RuleResolver` embrulhando os matchers atuais.** Risco zero ao
código medido. Rejeitada: mantém `Matcher` vivo como segundo conceito.

---

## 9. Riscos

| Risco | Severidade | Mitigação |
|---|---|---|
| O refactor muda números em silêncio | Alta | Golden file de 12 sementes, exato, antes de tocar em qualquer coisa |
| Deriva para plataforma antes de valor | Alta | Escopo travado no §2 com gatilho por item; nada de edição, catálogo ou DSL |
| Selo do agente nunca sai de "não medido" | Média | Depende de crédito de API; a tela declara a ausência em vez de inventar número |
| `Stage` sem segundo stage vira peso morto | Baixa | Assumido no §4.3; dez linhas, reversível |
| Endpoint passa a gastar dinheiro numa mudança futura | Média | Espião que grava chamadas a `complete()` (assinatura sobre estado, não exceção) + assinatura estrutural: toda `cost_class` da resposta é REGRA. Ver §7.2 e `DECISOES.md`, Plano 3, para a técnica anterior por exceção, provada vazia contra o `Investigator` real |

---

## 10. Glossário

- **Resolver** — uma tentativa de resolução: regra, agente ou humano. Tem nome e classe de custo.
- **Cascata** — lista ordenada de resolvers, ordenada por classe de custo de forma derivada.
- **WorkSet** — o que ainda não foi resolvido no momento em que um resolver é chamado.
- **Classe de custo** — REGRA, AGENTE ou HUMANO. Define a ordem entre resolvers; a ordem dentro da classe é do especialista.
- **Golden file** — medição exata de 12 sementes, capturada antes do refactor, que ele precisa reproduzir dígito a dígito.
