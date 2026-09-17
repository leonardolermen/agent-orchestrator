# Agent Orchestrator

> **Nome de trabalho.** Marca a definir quando houver cliente.

Runtime para transformar trabalho repetitivo em execução confiável e auditável:
**workflow determinístico, com agente apenas onde inteligência é necessária, e
um número dizendo quanto cada degrau custou.**

## A tese

A camada de orquestração de agentes virou commodity. A camada de execução
confiável, não. E o erro mais caro em produção não é o agente falhar — é gastar
US$ 15 num encadeamento de LLMs para resolver algo que uma query resolve por
centavos.

Então a fronteira entre código e agente **é** o produto:

```
entrada estruturada
      ↓
  [código]   normalização
      ↓
  [código]   regra determinística  ──→ resolvido (83-92%) ──→ fim, centavos
      ↓ não resolvido
  [AGENTE]   investigação com ferramentas
      ↓
  proposta + evidência + confiança
      ↓
  [humano]   aprova / rejeita / corrige
      ↓
  correção vira caso de teste no benchmark
```

A última seta é o ativo de longo prazo. Em seis meses, o conjunto de avaliação
é a coisa que um concorrente não copia.

**Onde a tese não gera economia, dito aqui e não só no spec.** Num pipeline
linear — um degrau, um resolver, a saída de um alimentando o próximo — não há
barato competindo com caro: a cascata ordenada por custo continua rodando, mas
ordena um elemento só. O encadeamento ganha pipeline e grafo; não ganha
centavo. A tese volta inteira no momento em que um degrau tem **regra + agente**
— é aí que existe alguém mais barato para tentar antes, e é aí que medir custo
por resolver passa a decidir alguma coisa. Ampliar o mercado onde a tese se
aplica não é o mesmo que aplicá-la, e confundir os dois é como um produto vira
"mais um framework de agentes" sem ninguém perceber.

## Os dois eixos

Trabalho é um **pool de itens tipados**. Um resolver consome itens e pode
produzir outros. A execução termina quando ninguém consegue mais consumir nem
produzir.

|  | Dentro de um degrau | Entre degraus |
|---|---|---|
| A ordem é | **custo** | **dado** |
| Quer dizer | quem tenta primeiro no mesmo trabalho | quem precisa da saída de quem |

> Ordenar por custo entre degraus seria escrever antes de pesquisar.

Os dois eixos juntos dão pipeline, ramificação, laço e tarefa única pelo **mesmo
mecanismo**, sem o kernel ganhar `if`, predicado ou linguagem de expressão:

- **pipeline** — o degrau declara `produz={"achados"}`, o seguinte declara
  `consome={"achados"}`. O encadeamento é dado, não fiação.
- **ramificação** — um triador produz `"urgente"` ou `"normal"`; o degrau cujo
  `consome` não casa com nada **não roda**. A condicional é a ausência de item.
- **laço** — um degrau produz um kind que um anterior consome. Exige
  `max_rondas > 1`, e bater o teto é `RunState.LIMITE_DE_RONDAS`, nunca um
  `CONCLUIDO` silencioso.
- **tarefa única** — pool de um item, um degrau. Caso degenerado, sem código
  especial.

Um kind produzido que ninguém consome é **recusado na construção**, a menos que
esteja declarado em `entrega` — assim "ninguém consome isto" é afirmação do
autor, nunca acidente.

## Domínios

| Domínio | Forma | Estado |
|---|---|---|
| `conciliacao` | pool que encolhe; três regras, agente, revisor humano | domínio de referência, o mais completo |
| `procurement` | pool que encolhe; regras + agente + comprador humano | esqueleto executável |
| `swe` | pool que encolhe; triagem de issue | esqueleto executável |
| `redacao` | **pool que transforma**: pesquisar → escrever → revisar | esqueleto executável, fora do catálogo (ver abaixo) |

Os esqueletos existem para achar defeito no kernel enquanto ele ainda está mole.
Já funcionou três vezes: `procurement` e `swe` acharam dois defeitos de
generalidade na primeira linha de código de domínio, e `redacao` achou o
terceiro — **que não está no kernel, está no catálogo**: `CATALOGO.agentes`
descreve estruturalmente um resolver que *julga* um item e devolve
`Proposal`/`Resolution` a respeito DELE, sem campo para "que kind este degrau
produz". `redacao` não julga: cada um dos três degraus é uma `Tarefa` que
TRANSFORMA o item num item de outro kind para o próximo consumir. Catalogá-lo
hoje exigiria mentir sobre o que ele faz — por isso `redacao` roda
(`tests/domains/test_redacao.py`) mas fica fora de `CATALOGO`, de propósito
(a nota completa mora em `domains/registro.py`). Ensinar `AgenteDeclarado` a
declarar `produz` fecha essa lacuna — é o mesmo X7/X8 da lacuna de `kind`, no
anti-escopo abaixo.

## Por que Brasil

Não é geografia — é que a stack documental e regulatória brasileira é
idiossincrática: NF-e, SPED, CNAB, retenção de ISS/IRRF, Pix, ERPs nacionais,
LGPD. Trabalho chato, local, que fornecedor de fora não faz direito. Em
"agentes genéricos" não haveria fosso nenhum; aqui há.

## O que este projeto NÃO é

Anti-escopo vale tanto quanto escopo:

- **Não** tem DSL. O motor é genérico, mas a composição é por `kind` declarado —
  nada de `if`, predicado ou expressão no kernel. Regra que não cabe nos tipos
  declarativos é código Python, e isso é o preço certo.
- **Não** gera código. Nem regra, nem ferramenta, nem agente.
- **Não** reimplementa durable execution — se virar necessário, entra
  Temporal/Restate por baixo, e a fronteira de execução fica isolada pra isso.
- **Não** tem marketplace de agentes.
- **Não** é multi-tenant.
- **Não** deixa o agente fazer o matching.
- **Não** aceita trabalho sem itens. Um orquestrador que aceita tudo não mede
  nada — e medir é a única vantagem que este projeto tem.
- **Não tem piso barato para trabalho novo, ainda.** A paleta é um catálogo
  plano de tudo que existe, e o que existe hoje é regra de conciliação e de
  compras — código, com a forma do trabalho delas. Um workflow de um trabalho
  NOVO começa 100% na classe `AGENTE`, que é o pior custo possível. Enquanto
  isso for verdade, a tese de custo não se aplica a ele: o que fecha é a regra
  genérica declarativa (igualdade, tolerância, agrupamento, tabela, padrão,
  limiar), e ela ainda não existe.
- **Não garante mais que o `kind` de um agente bate com o que o degrau anterior
  produz, para composição feita pelo canvas.** O domínio fazia essa checagem, e
  ela saiu certo: com a tela sem seletor, toda composição chegava com o domínio
  default e a checagem passou a recusar qualquer `kind` que não fosse
  `lancamento` — guarda certa aplicada ao pedido errado, recusando cascata
  válida. O lugar certo é o grafo: `Stage.consome`/`Stage.produz` valida a
  fiação por degrau, e recusaria um `kind` que não conecta. Só que, para uma
  composição montada por `construir_composicao`, essa checagem está INERTE —
  a função devolve um único `Stage` com `consome`/`produz` nos defaults, o que
  desliga a checagem de beco sem saída do grafo inteiro, e ela nunca popula
  `consome`/`produz` a partir dos blocos, então não haveria o que comparar
  mesmo se rodasse. Um `kind` digitado errado é aceito na composição e, em
  execução, simplesmente não pega item nenhum — falha muda, sem erro. Fecha
  com as duas pontas do X7/X8: `AgenteDeclarado` declarar o que `produz`, e
  `construir_composicao` derivar `consome`/`produz` dos blocos a partir disso.
  Até as duas existirem, quem escreve um agente na tela é quem garante o
  `kind`.
- **Não sabe EXECUTAR um workflow que não seja de conciliação — e ainda assim
  devolve 200.** A paleta é o catálogo inteiro, então o chat e o canvas compõem
  cascatas de compras (`preferido`, `anteriores`) ou de qualquer bloco novo que
  entre. Mas o único caminho de execução que existe gera dados bancários:
  `POST /api/workflows/{id}/runs` monta um `SyntheticSource` e chama
  `reconcile(dataset.bank, dataset.ledger, ...)`, sempre. Uma cascata cujos
  blocos trabalham outro `kind` roda contra um pool que ela não enxerga, e a
  resposta é `200` com `deterministic_rate: 0.0` e lacuna de `100%` — medido,
  não suposto. É o pior formato possível para essa falha, porque é exatamente
  o que este projeto nomeia como o erro que ele existe para não cometer:
  **"não achei nada" indistinguível de "não procurei"**. Um número que parece
  medido e não é. O que fecha é uma fonte que produza os `kinds` que o workflow
  consome — a `Source` além da sintética, §8 do spec da plataforma geral
  (`arquivo`, `http`, `webhook`, `fila`, `agenda`). Até ela existir, o único
  resultado de `/runs` que quer dizer alguma coisa é o de um workflow de
  conciliação.

### A invariante mais cara, e o limite dela

**Uma proposta não resolve.** Um `Agent` devolve `proposals` e nunca
`resolutions`, e isso é garantido pelo TIPO: `WorkSet.without()` não aceita
proposta. Nenhum julgamento de modelo tira um item do pool por conta própria.

O limite, dito em voz alta porque uma revisão o encontrou construindo workflows
que o furavam: uma `Tarefa` — o resolver que transforma item em item —
**resolve**, e o que a legitima é empurrar o trabalho para frente sem encerrá-lo.
Mas a guarda de beco sem saída **não exige um humano em lugar nenhum**. Um run
pode terminar na saída de um modelo, com `CONCLUIDO`, sem ninguém conferir —
`domains/redacao` é exatamente essa forma. A invariante literal sobrevive; a
propriedade mais larga ("o julgamento de um modelo nunca remove um item sem um
humano confirmar") **não** é preservada pela forma do grafo. Quem monta a
cascata é que põe o humano nela.

## Decisões

O registro completo, com a alternativa rejeitada e o custo de estar errada, está
em [`docs/superpowers/DECISOES.md`](docs/superpowers/DECISOES.md). As
estruturantes:

| Data | Decisão | Razão |
|---|---|---|
| 2026-09-14 | Produto antes de plataforma | Abstração se extrai de instâncias, não se projeta |
| 2026-09-14 | Python | Ecossistema de avaliação; o benchmark é o ativo |
| 2026-09-14 | Sem engine durável no v1 | Conciliação leva minutos, não dias |
| 2026-09-14 | Zero dado de terceiros | Validação por dado sintético com gabarito |
| 2026-09-16 | Domínios esqueleto antes de clientes | Substituto barato da regra dos três usos |
| 2026-09-17 | Pool que transforma, não DAG declarado | Um mecanismo para os quatro casos; custo continua significando algo |

## Status

O núcleo está construído e medido. O que existe hoje:

- **Kernel livre de domínio**, com catraca no CI (`tests/arquitetura/`) que
  falha se alguém importar domínio de dentro dele
- **Motor** com cascata por custo, política, orçamento, trace, human-in-the-loop
  e laço até ponto fixo
- **Agente como dado** (`AgenteDeclarado`) — um domínio novo sem uma linha de
  Python — e `Tarefa`, o resolver que transforma
- **Avaliação**: benchmark, matriz de confusão, regressão, colheita de decisão
  humana viram casos de teste
- **Canvas** em React/React Flow que desenha a cascata com números medidos
- **883 testes**, e nenhum deles chama API paga

O agente **já rodou contra o modelo de verdade** — três execuções pagas, e foi
delas que saiu a limitação medida registrada no P6.86.

O que falta, em ordem: a autoria declarativa alcançar o grafo
(`AgenteDeclarado.produz`, `Composicao.etapas`, o canvas com arestas derivadas),
o laço de promoção — o agente caro ensinando a regra barata — e a limpeza do
vocabulário de conciliação que ainda mora na raiz do pacote.

## Rodar

```bash
pip install -e ".[dev]"
pytest
orchestrator --seed 1 --n 500
```

Flags: `--seed` (semente do gerador), `--n` (tamanho do dataset) e
`--taxa-divergencia` (fração de pares que recebe divergência injetada — é o flag
que move a taxa determinística reportada acima).

Quatro comandos: `orchestrator` (a cascata), `orchestrator-eval` (avaliação do
agente, **gasta dinheiro**), `orchestrator-grill` (compor um workflow por
entrevista) e `orchestrator-trace` (a árvore de spans de um run).

### O canvas

```bash
pip install -e ".[dev,api]"
uvicorn orchestrator.api.app:app --port 8000
```

Abra `http://localhost:8000`: cada resolver da cascata com classe de custo, taxa
de resolução e custo — medidos contra um benchmark sintético — e a lacuna que
nenhum resolver cobre, declarada em vez de escondida. Nenhum endpoint por trás
da página tem caminho de código até o modelo (ver `tests/api/test_execucao.py`),
então nenhum F5 gasta dinheiro.

**Uma aplicação, três vistas**, todas na mesma URL e todas escuras por default:

| Vista | URL | O que é |
|---|---|---|
| execução | `/` (ou `/?workflow=<id>`) | um workflow salvo, com os números medidos |
| fila | `/?vista=fila` | a revisão humana que fecha a cascata |
| compor | `/?vista=compor` | o canvas de autoria |

O front é um app React em `web-app/`, buildado para `web/` — que é servido como
estático. O bundle é commitado porque o pacote é Python e `pip install` não roda
npm; o CI rebuilda e exige `git diff` vazio, então fonte não buildada não passa.

```bash
npm --prefix web-app install
npm --prefix web-app run dev    # com proxy para o uvicorn em 8111
npm --prefix web-app run build  # antes de commitar mudança de front
```

### Avaliar o agente (gasta dinheiro)

Exige `ANTHROPIC_API_KEY` no ambiente ou `ant auth login`.

```bash
orchestrator-eval --n 100 --seed 1
```

Sem `--model`, compara `claude-opus-5`, `claude-sonnet-5` e `claude-haiku-4-5`
contra o mesmo gabarito.

### Fila de revisão humana

O agente propõe; ele nunca resolve. `--fila` grava as propostas na fila em vez
de só imprimir o relatório:

```bash
orchestrator-eval --via assinatura --seed 1 --n 30 --fila
uvicorn orchestrator.api.app:app --port 8000
# http://localhost:8000/?vista=fila&seed=1&n=30&taxa_divergencia=0.15
```

Cada proposta pendente aparece com o lançamento bancário e o contábil lado a
lado, e três botões: aceitar, rejeitar, ou corrigir o tipo e os ids. Decidir
grava uma `Decision` e o canvas passa a mostrar o `revisor` — o resolver de
classe `HUMANO` que fecha a cascata.

**A fila é escopada por dataset** (`seed`/`n`/`taxa_divergencia`), porque o mesmo
id de divergência aponta para lançamentos diferentes conforme o dataset muda.
Abra o canvas e a fila com a MESMA query string, ou as duas páginas olham para
datasets diferentes.

A frase que resume: **decisão é o que resolve; proposta nunca resolve.**
`reconcile()` continua puro — só lê a fila através do `revisor`, só o CLI grava
proposta e só a API grava decisão — e é disso que o golden e o teste de "nenhum
endpoint gasta dinheiro" dependem.
