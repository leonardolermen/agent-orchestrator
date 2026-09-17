# Execução como grafo: o pool que transforma

**Data:** 2026-09-17
**Estado:** proposta
**Antecessor:** `2026-09-16-plataforma-geral-design.md`

---

## 0. O pedido, e por que ele não é o spec anterior

O spec anterior abriu o escopo para "qualquer trabalho repetitivo" e recusou
deliberadamente, na §0.1, o trabalho **sem itens**: tarefa única, trabalho
criativo aberto, qualquer coisa sem noção de "resolvido". A recusa tinha uma
razão boa — *um orquestrador que aceita tudo não mede nada.*

O dono do projeto pediu o que aquela recusa excluía: uma plataforma em que
caibam **os três** — pipeline (a saída de uma tarefa é a entrada da próxima),
grafo (ramifica e volta) e tarefa única com ferramentas. Um CrewAI de verdade,
não uma cascata de conciliação generalizada.

Este spec responde a esse pedido **sem** revogar a tese de custo, e a §9 é
honesta sobre onde a tese deixa de gerar economia.

### 0.1 A tese, na forma que o pedido exige

> Trabalho é um **pool de itens tipados**. Um resolver consome itens e pode
> produzir outros. A execução termina quando ninguém consegue mais consumir
> nem produzir.
>
> Dentro de um degrau, a ordem é **custo**. Entre degraus, a ordem é **dado**.

A primeira metade é a mudança deste spec. A segunda metade já está construída e
medida, e é o que separa isto de um framework de agentes comum.

---

## 1. A auditoria que motivou o desenho

Levantado no código, não no README.

### 1.1 O kernel já é livre de domínio — isso é verificável

- `kernel/` não importa nenhum módulo de domínio. As menções a "conciliação"
  nos arquivos do kernel são docstrings *explicando como o acoplamento foi
  removido* (`kernel/work.py`, `kernel/resolution.py`).
- `tests/arquitetura/camadas.py` impõe a tabela de camadas no CI, com
  `"kernel": frozenset()` — não pode importar nada.
- `domains/procurement` e `domains/swe` rodam a cascata inteira ponta a ponta
  (`tests/domains/test_generalidade.py`), e escrevê-los achou dois defeitos de
  generalidade na primeira linha de código.
- ~6.100 linhas de núcleo genérico contra ~2.400 presas a conciliação.

**Conclusão:** o desconforto com o repositório é de BORDA (catálogo do grill,
API, raiz), não de fundação. Reescrever do zero jogaria fora o núcleo provado
por três domínios, a catraca que impede a regressão e 844 testes.

### 1.2 O eixo que existe no tipo e não tem usuário

`WorkflowDefinition.stages` é uma tupla. **As 9 definições do repositório têm
exatamente um stage.** O eixo de sequência existe e está vazio.

Esse é o achado central: o kernel já reservou os dois eixos e só um está em uso.

| Eixo | Significado | Uso hoje |
|---|---|---|
| `stages` (sequência) | dependência de dado | vazio |
| `cascade` dentro do stage (`Stage.ordered()`) | competição por custo | tudo |

### 1.3 O que falta, e é UMA coisa

`runtime/engine.py` encadeia stages com uma única expressão:

```python
work = work.without(saida.resolutions)
```

O stage seguinte recebe **o que sobrou**, nunca **o que o anterior produziu**.
Não existe fluxo de dado para frente. Um CrewAI é feito disso
(`Task(context=[task1])`).

Três consequências, e são exatamente as três queixas:

| Falta | Onde está preso |
|---|---|
| Saída de tarefa alimenta a próxima | `ResolverOutput` só tem `resolutions` e `proposals` |
| Tarefa única sem pool | `RunState` termina por pool vazio |
| Saída livre | `Resolution` exige `item_ids`; `Proposal` exige `tipo` |

### 1.4 A pista de que isto já foi entrevisto

`kernel/definition.py` já tem `Task()`, com o comentário: *"existe para que quem
chega do CrewAI encontre a palavra que espera, sem que o kernel ganhe um segundo
conceito"*. A palavra está lá; a semântica de encadeamento, não.

---

## 2. Abordagens consideradas

### A. Quadro-negro: o pool transforma (ESCOLHIDA)

`ResolverOutput` ganha `produced`. O motor passa a fazer
`work.without(consumidos).com(produzidos)`. O encadeamento é derivado do `kind`
dos itens, não de fiação declarada.

**A favor:** pipeline, ramificação, laço e tarefa única viram o MESMO mecanismo.
Preserva classe de custo, política, orçamento, trace, human-in-the-loop e
benchmark. É a extensão natural do eixo que a §1.2 mostrou vazio.

### B. DAG explícito

`Stage` ganha `depende_de`, o motor ordena topologicamente, saídas vão num
contexto compartilhado.

**Contra:** duas ordens competindo (topológica entre stages × custo dentro).
Condicional exige um tipo novo, porque o grafo é estático. O contexto vira um
saco de `Any` que o kernel inspeciona — exatamente o que `WorkItem.payload`
existe para evitar.

### C. Dois motores lado a lado

Cascata fica como está; `graph/` novo compartilha `Agent`, `ToolRegistry`,
`Cost`, `Trace`, `Run`.

**Contra:** duas semânticas de execução, dois canvas, dois formatos de `Run`, e
a tese de custo não vale na metade nova. É o caminho que mais parece começar do
zero, sem os ganhos de começar do zero.

**Decisão: A.** É a única em que os quatro casos são um mecanismo só, e a única
que mantém a ordenação por custo significando alguma coisa.

---

## 3. Kernel: o pool ganha a operação inversa

**POR QUE.** Sem produzir, não há fluxo para frente, e sem fluxo para frente não
há pipeline nem grafo.

**ONDE.** `kernel/resolver.py`, `kernel/work.py`.

**COMO.**

```python
@dataclass(frozen=True)
class ResolverOutput:
    resolutions: list[Resolution] = field(default_factory=list)
    proposals:   list[Proposal]   = field(default_factory=list)
    produced:    tuple[WorkItem, ...] = ()      # NOVO
    cost:        Cost = field(default_factory=Cost.zero)
```

`produced` é campo SEPARADO pela mesma razão que `resolutions` e `proposals` são
separados: resolução consome, produção cria, e nenhum tipo único expressa as
duas sem virar um campo de status. `proposals` não aparece em nenhuma das duas
expressões do motor — a invariante continua estrutural, não lembrada.

`WorkSet` ganha o espelho de `without()`:

```python
def com(self, novos: Iterable[WorkItem]) -> "WorkSet": ...
```

Recebe `WorkItem`, nunca `ResolverOutput`, pelo mesmo motivo que `without()`
recebe `Resolution`: não existe assinatura pela qual uma proposta chegue lá.

`WorkItem` ganha um campo:

```python
origem: str = ""     # qual resolver produziu este item
```

Sem proveniência a cadeia de auditoria quebra no primeiro salto e o replay não
reconstrói de onde o item veio.

### 3.1 A invariante nova

> **Transformar é resolver.**
> Uma tarefa que lê o item A e escreve o item B emite **uma `Resolution`
> consumindo A** e **um `produced` com B**.

O pool continua encolhendo por uma porta só. Não há segunda maneira.

---

## 4. `Stage` declara o que consome

**ONDE.** `kernel/definition.py`.

```python
@dataclass(frozen=True)
class Stage:
    name: str
    cascade: tuple[Resolver, ...]
    consome: frozenset[str] = frozenset()   # NOVO. vazio = o pool inteiro
    produz:  frozenset[str] = frozenset()   # NOVO. vazio = não produz nada
    policy: ExecutionPolicy = ...
```

`consome=frozenset()` e `produz=frozenset()` são EXATAMENTE o comportamento de
hoje. As 9 definições existentes não mudam.

**Por que `produz` é DECLARADO e não observado.** Produção emergente em runtime
não serve para nada que precise saber o grafo ANTES de rodar: a recusa de beco
sem saída (§6.1), as arestas do canvas (§7) e a `version` (§5.2) são todas
estáticas. Um grafo que só existe depois da execução não previne nada e não
desenha nada.

**A guarda que isso habilita, e ela é do kernel.** O motor recusa — `ValueError`,
não abstenção — um item produzido cujo `kind` não está no `produz` do stage que
o produziu. Sem essa checagem, `produz` seria documentação, e documentação que
o runtime não impõe desatualiza em silêncio.

**Ramificação sai daqui, sem `if` no kernel.** O triador produz `kind="urgente"`
ou `kind="normal"`; dois stages, cada um consumindo um. **O stage cujo `consome`
não casa com nada não roda.** A condicional é a ausência de item, não um
predicado — e é por isso que o kernel não ganha linguagem de expressão.

---

## 5. Motor: de passada única a ponto fixo

**ONDE.** `runtime/engine.py`, `kernel/definition.py`, `kernel/run.py`.

```python
@dataclass(frozen=True)
class WorkflowDefinition:
    id: str
    name: str
    stages: tuple[Stage, ...]
    max_rondas: int = 1                     # NOVO. 1 = semântica de hoje
    entrega: frozenset[str] = frozenset()   # NOVO. ver §6.1
```

O laço externo roda até uma ronda **não resolver nada e não produzir nada**, ou
bater o teto.

**Por que `max_rondas=1` já entrega pipeline.** Os stages rodam em ordem dentro
da mesma ronda, então `pesquisar -> escrever -> revisar` fecha numa passada.
Ronda extra só é necessária para ARESTA DE VOLTA (o revisor reprova e o rascunho
volta ao escritor). A complexidade do laço se paga só quando há laço.

**Bater o teto não termina em silêncio.** `RunState` ganha `LIMITE_DE_RONDAS` e
`Run` ganha `rondas: int`. Um run que parou por teto NÃO terminou, e este
repositório declara a lacuna em vez de escondê-la — mesmo espírito de
`AGUARDANDO_HUMANO`.

### 5.1 Os dois eixos, e a frase que precisa continuar verdadeira

> Dentro de um stage, a ordem é **custo** — quem tenta primeiro no mesmo
> trabalho.
> Entre stages, a ordem é **dado** — quem precisa da saída de quem.
> Ordenar por custo ENTRE stages seria escrever antes de pesquisar.

Vira docstring e vira teste.

### 5.2 Versão

`WorkflowDefinition.version` passa a incluir `consome`, `produz`, `max_rondas`
e `entrega`. Sem isso dois grafos diferentes hasheiam igual, e o
benchmark compararia coisas distintas achando que compara a mesma.

A política continua FORA da versão, pela razão já registrada: ela é variável de
experimento.

---

## 6. Como um agente PRODUZ em vez de propor

**POR QUE.** É o que faz tarefa única e pipeline existirem. É também a porta
pela qual a invariante mais cara do projeto poderia sair sem ninguém ver.

`Agent.resolve` tem hoje uma garantia no tipo: *"NUNCA devolve resolutions"*.
**Isso não muda.** Em vez disso, duas classes sobre o mesmo laço:

| | `Agent` (existe) | `Tarefa` (novo) |
|---|---|---|
| O que faz | julga SOBRE o item | transforma o item em outro |
| Devolve | `proposals` | `Resolution` + `produced` |
| Nunca devolve | `resolutions` | `proposals` |
| Exemplo | "esta divergência é tipo X" | "aqui está o rascunho" |

O laço de turnos, orçamento, retry de formato e abstenção é EXTRAÍDO e
compartilhado pelas duas. A diferença é o CONTRATO, imposto pelo tipo — como
`resolutions` e `proposals` já são separados.

### 6.1 Por que é legítimo uma `Tarefa` resolver, se um `Agent` não pode

> **Revisada em 2026-09-17**, depois de a revisão do branch CONSTRUIR e RODAR
> três workflows que passam por `WorkflowDefinition.__post_init__` e ainda
> assim deixam o julgamento não conferido de um modelo encerrar a vida de um
> item. O argumento original, preservado abaixo, **afirmava mais do que a
> guarda prova**. O que mudou: o parágrafo *"O que a guarda prova, e o que
> não"* passa a vir antes dele e a governar a leitura; o argumento original
> fica como o raciocínio de desenho que foi, não como garantia.

**O que a guarda de beco sem saída PROVA.** Uma coisa, e ela é real:
**reachability estática no grafo de kinds.** Nenhum kind produzido sai do grafo
sem nome — ou algum stage o consome, ou o autor o escreveu em `entrega`. Isso
pega o kind digitado errado e o kind esquecido, que de outro modo acumulariam
no pool para sempre, e obriga o autor a DECLARAR que um kind é terminal em vez
de descobri-lo por acidente.

**O que ela NÃO prova.** Não exige humano em lugar nenhum. Não exige que o
consumidor de um kind seja outra coisa além de mais um modelo. Não exige que
uma transformação produza coisa alguma — `SaidaDaTarefa(resolution=<x>,
produced=())` era aceito, e com `produz=frozenset()` a guarda não tinha o que
checar. E não limitava quais itens uma `Resolution` podia consumir: `Tarefa`
passava `item.id` ao `transformar` e não conferia o que voltava, enquanto
`WorkSet.without()` descarta em silêncio ids que ninguém perguntou.

As duas últimas são erro de CONFIGURAÇÃO e passaram a falhar alto em
`Tarefa.resolve`, por item, em runtime. As duas primeiras **permanecem**: um
run pode terminar na saída de um modelo, com `RunState.CONCLUIDO`, sem que
ninguém confira nada. **`domains/redacao`, como entregue, é exatamente essa
forma** — três `Tarefa` em fila, `entrega={"texto_final"}`, zero resolver de
classe `HUMANO`. Não é defeito do domínio; é o que a guarda permite, e agora
está escrito.

**A invariante que sobrevive é a literal, e só ela:** uma `Proposal` continua
sem conseguir chegar a `WorkSet.without()` ou a `WorkSet.com()` — não existe
assinatura por onde ela passe, e é isso que a §10 quer dizer com "proposta
continua sem resolver e sem produzir". A propriedade mais larga — *"o
julgamento de um modelo nunca remove um item sem um humano confirmar"* — **não
é preservada pela forma do grafo**. Quem a quiser tem de pôr um resolver de
classe `HUMANO` consumindo o kind terminal; nem o kernel nem `Tarefa` fazem
isso por ele. `tests/runtime/test_producao.py::test_a_guarda_nao_exige_humano`
fixa a limitação como fato da suíte.

*(A partir daqui, o argumento original de 2026-09-17, mantido porque este
repositório guarda o porquê de uma mudança — e porque ele continua sendo a
razão de `Tarefa` existir, só não é a garantia que dizia ser.)*

Não é "porque não decide". Um triador que produz `kind="urgente"` decide, e é
assim que a ramificação da §4 funciona. A distinção honesta é outra:

> Uma `Tarefa` **empurra o trabalho para frente dentro do run; nunca o
> encerra.** O item que ela produz continua no pool e ainda passa por quem vier
> depois — inclusive um `HUMANO`, se a cascata tiver um.
> Uma `Proposal` que resolvesse faria o item SAIR com um julgamento que ninguém
> conferiu.

**E isso é verificado na CONSTRUÇÃO, não em runtime.** A checagem mora em
`WorkflowDefinition.__post_init__` — **no kernel, não em `construir()`**, e a
diferença importa: `construir()` é a via de AUTORIA, e os domínios em Python
montam `WorkflowDefinition` direto, sem passar por ela. Uma guarda que só
protege o canvas não protege o código, e é o código que roda em produção.

A regra: todo `kind` em `Stage.produz` tem de estar no `consome` de algum stage,
ou em `entrega`. Beco sem saída é erro de construção, e falha alto — como toda
configuração inválida neste repositório.

> **Corrigida em 2026-09-17.** A regra acima lia `consome=frozenset()` como "não
> consome nada", quando a §4 o define como **"vê o pool inteiro"**. O efeito era
> recusar um pipeline CORRETO cujo degrau de baixo usa o default, e empurrar o
> autor a listar kinds INTERMEDIÁRIOS em `entrega` só para conseguir construir —
> o que faz a declaração mentir e desliga a guarda justo para esses kinds.
> Vários testes do branch carregavam essa fiação e foram desfeitos.
> **Um stage com `consome` vazio é consumidor curinga: nenhum kind fica órfão.**
> O custo, dito aqui e no comentário do kernel: a guarda fica **inerte** para o
> grafo inteiro assim que um stage usa o default. Declarar `consome` em todos os
> stages é o que a compra de volta. Uma guarda honesta e inerte é melhor que uma
> que recusa grafo válido e ensina o autor a mentir em `entrega`.

A única exceção é declarada: `WorkflowDefinition.entrega` lista os kinds que SÃO
a saída do run. Assim "ninguém consome isto" é afirmação do autor, nunca
acidente. O post do blog é `entrega={"texto_final"}`; um rascunho esquecido no
pool é erro de build.

### 6.2 Saída estruturada

`Tarefa` precisa de um `Transformador`, análogo ao `Parser` de `AgentSpec`:

```python
Transformador = Callable[
    [str, WorkItem, Cost, list[TraceEvent]],
    tuple[Resolution, tuple[WorkItem, ...]] | None,
]
```

Devolve `None` quando o texto não é utilizável — e é esse `None` que dispara o
retry de formato que já existe. Falha após o retry vira abstenção registrada: a
`Tarefa` NÃO resolve o item, que fica no pool para o próximo degrau. Um agente
que estoura não derruba o run.

Na via declarativa, `AgenteDeclarado` ganha `produz: str | Mapping[str, str]` —
um kind fixo, ou um mapa de `tipo` para kind, que é a ramificação sem código.

---

## 7. Autoria e canvas: arestas derivadas, nunca desenhadas

`Composicao.blocos` é hoje uma tupla plana — um stage. Vira
`etapas: tuple[Etapa, ...]`, cada uma com `consome`, `produz` e seus blocos.

O canvas desenha aresta de X para Y **sse** `X.produz ∩ Y.consome != {}`, lida do
objeto que o motor executa. Não é conveniência: `kernel/definition.py` já nomeia
o modo de falha — *"uma definição declarativa paralela permitiria drift entre o
desenho e a execução"*. Arrastar uma aresta no canvas EDITA `consome`/`produz`;
não existe grafo paralelo.

O `Entrevistador` ganha `declarar_etapa(nome, consome, produz)` — a ferramenta
que faltava na §9 do spec anterior, agora com onde encaixar.

---

## 8. Migração dos três domínios: nenhuma

`consome=frozenset()` + `max_rondas=1` + `entrega=frozenset()` reproduz a
semântica atual exatamente.

**Critério de aceite da mudança de kernel: os 844 testes passam sem serem
tocados.** Se algum teste precisar de edição, o default está errado.

O quarto domínio é o teste de verdade: um pipeline (`pesquisar -> escrever ->
revisar`) entra em `domains/` como esqueleto executável, do mesmo jeito que
procurement e swe entraram. `tests/domains/test_generalidade.py` registra que
essa prática achou dois defeitos de kernel na primeira linha de código de
domínio. Vai achar mais — e é para isso que ela existe.

---

## 9. O que acontece com a tese de custo

Honestidade obrigatória, e ela é o motivo de esta seção não estar escondida no
fim de outra.

**Num pipeline linear a tese de custo não gera economia.** Um stage com um
resolver só não tem competição: não há barato tentando antes do caro. A cascata
ordenada por classe continua rodando, mas ordena um elemento.

A tese volta a valer no momento em que um stage tem **regra + agente** — e volta
inteira, porque o laço de promoção (G7 do spec anterior) opera dentro de um
stage, não entre stages.

> A plataforma geral **não substitui** a tese de custo.
> Ela amplia o mercado onde a tese pode ser aplicada depois.

Dizer isso em voz alta é o que impede o produto de virar "mais um CrewAI" sem
ninguém perceber — que é exatamente o modo de falha que o spec anterior
registrou ter acontecido por oito PRs.

---

## 10. O que este plano deliberadamente NÃO faz

- **Não vira n8n.** Nenhum `if`, predicado ou expressão no kernel. Ramificação é
  ausência de item do `kind` certo.
- **Não existe contexto global `dict[str, Any]`.** Tudo que trafega é `WorkItem`
  com `kind` e `payload` opaco. O kernel continua sem conseguir perguntar o que
  um item é.
- **Proposta continua sem resolver e sem produzir.** Não entra em `without()`
  nem em `com()`.
- **`Crew` continua `Resolver` dentro de `Stage`.** A contenção é o que dá
  custo, política, trace e human-in-the-loop de graça.
- **Não geramos código.** §6.4 do spec anterior vale igual aqui.
- **Não reescrevemos o repositório.** §1.1.

---

## 11. Riscos

| Risco | Sintoma | Mitigação |
|---|---|---|
| Laço infinito | run roda para sempre trocando kind | `max_rondas` obrigatório; `RunState.LIMITE_DE_RONDAS` explícito |
| `Tarefa` vira porta dos fundos | alguém transforma quando devia propor; o humano some da cascata | **PARCIAL** — beco sem saída recusado no build e `entrega` declarada cobrem kind órfão; resolver sem produzir e resolver id alheio falham alto em `Tarefa.resolve`. O humano sumir da cascata NÃO é coberto: ver §6.1 revisada |
| Explosão de kinds | vinte kinds e ninguém sabe quem alimenta quem | `WorkflowDefinition` recusa beco sem saída; canvas desenha o grafo derivado |
| Confundir os dois eixos | alguém ordena stages por custo e escreve antes de pesquisar | §5.1 vira docstring e teste |
| Tese de custo perde sentido | pipeline linear sem competição, e o pitch some | §9, dita em voz alta e no README |
| Regressão nos 3 domínios | um default errado quebra conciliação | §8: os 844 testes não podem ser tocados |

---

## 12. Milestones

| M | O quê | Depende | Por quê nesta ordem |
|---|---|---|---|
| **X1** | `ResolverOutput.produced`, `WorkSet.com()`, `WorkItem.origem` | — | o campo sem o qual nada mais existe |
| **X2** | `Stage.consome`; motor filtra por kind | X1 | ramificação, sem tocar no laço externo |
| **X3** | Laço até ponto fixo; `max_rondas`; `LIMITE_DE_RONDAS`; `Run.rondas` | X2 | aresta de volta |
| **X4** | `Stage.produz`; `entrega`; recusa de beco sem saída em `WorkflowDefinition` | X2 | a guarda da §6.1 antes da peça que ela guarda |
| **X5** | `Tarefa` + `Transformador`; laço extraído e compartilhado com `Agent` | X4 | agora produzir é seguro |
| **X6** | Domínio `redacao`: `pesquisar -> escrever -> revisar` como esqueleto | X5 | o teste de generalidade de verdade |
| **X7** | `AgenteDeclarado.produz`; `Composicao.etapas`; `declarar_etapa` | X6 | a via sem código |
| **X8** | Canvas com arestas derivadas; edição de `consome`/`produz` | X7 | o desenho que não pode driftar |

**X4 antes de X5 é deliberado:** a guarda entra antes da peça que ela guarda. A
ordem inversa deixaria uma janela em que `Tarefa` resolve sem nada verificar
beco sem saída — e é nessa janela que a invariante mais cara do projeto sairia.

---

## 13. A frase que resume

> Um framework de agentes encadeia tarefas.
> Este encadeia tarefas **e** sabe qual delas podia ter custado menos.
