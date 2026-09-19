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
declarar `produz` fecha essa lacuna — é a metade X8 da lacuna de `kind` — a
metade X7, `consome` derivado e conferido na borda, fechou; `produz`
declarado por agente ainda não existe — no anti-escopo abaixo.

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
  ela não conhece a fonte; a recusa vem na execução, antes de gastar. E a
  guarda confia no `produz` declarado: um resolver que declara
  `produz={"banco"}` e não emite nada passa pela borda sem erro — a lacuna do
  produtor, contida hoje só pelo `xfail(strict)`
  `test_a_lacuna_do_produtor_nao_e_alcancavel_pelo_CATALOGO`.
- **Executa qualquer workflow do `registry()` — embutido, receita ou composição
  do canvas — sobre a fonte que o pedido nomeia.** `POST /api/workflows/{id}/runs`
  recebe `fonte` — `sintetica`, `arquivo` (CSV/JSON sob `data/entradas/`),
  `postgres` (query de LEITURA num DSN referenciado por nome de variável de
  ambiente) ou `http` (uma página JSON com token referenciado por nome) — e um
  `teto_microcents`, obrigatório quando a cascata tem agente — e recusado
  ANTES de a fonte ser tocada, para que um campo ausente do pedido não custe
  uma conexão no banco do parceiro. Nenhum segredo passa pela tela, pelo pedido
  persistido, pelo `ref` ou pela resposta: o servidor lê o valor do ambiente na
  hora e o erro do driver volta reduzido à classe. **E um segredo escrito na url
  à mão também não viaja** — a afirmação é sobre o que a plataforma faz, não
  sobre o que dá para digitar: `usuario:senha@` é RECUSADO (não existe userinfo
  inocente, e recusar ensina que `token_env` existe), e a query é REDIGIDA a um
  digest no `ref`, no log e nas mensagens (`?since=…` é legítimo demais para ser
  recusado, e `?api_key=…` não pode sair do processo). O que fica de fora: um
  segredo em segmento de caminho, indistinguível de um id. O `ref` é o hash do CONTEÚDO nas
  duas fontes novas (linhas ordenadas no Postgres, corpo no HTTP — o ETag não
  entra), e os tetos valem para o `ref` também, não só para o `load()`: no
  máximo `max_linhas + 1` linhas saem do cursor, e o corpo HTTP para em 32 MiB.
  A conexão Postgres tem `connect_timeout` e `statement_timeout` fixos no
  módulo. Uma fonte sem gabarito devolve `contra_gabarito: null`; uma cujos
  kinds nenhum bloco consome é recusada antes de rodar; pool vazio também. O
  que ainda NÃO existe: paginação/cursor no HTTP, query com parâmetros,
  outros bancos, "testar conexão", allowlist de hosts, upload de arquivo, e
  teto agregado/auth/rate limit em `/runs` — o teto é por requisição, por
  decisão do dono.

- **Gatilho: uma URL que dispara execução, com segredo e teto próprios.**
  `POST /api/triggers` cria um disparador para um workflow e mostra o segredo
  UMA vez — o disco guarda só o sha256. `POST /api/triggers/{id}/disparar` com
  `Authorization: Bearer <segredo>` executa. Duas recusas acontecem na CRIAÇÃO,
  não no disparo: o teto é obrigatório (o disparo vem de fora e não é confiável,
  então um teto que viesse nele seria um teto que o atacante escolhe), e o
  workflow precisa carregar a própria entrada — um bloco `Input`, porque um
  disparo não tem ninguém para escolher a fonte. Gatilho inexistente e segredo
  errado respondem o MESMO 404, para a rota não virar um oráculo de ids
  válidos; revogar APAGA, porque a razão de revogar costuma ser que o segredo
  vazou.

  **O que ele NÃO resolve, e é o mesmo buraco de cima com mais peso:** quem tem
  o segredo pode disparar em laço. Cada disparo respeita o teto dele; nada
  limita quantos disparos acontecem por minuto, e dez mil chamadas são dez mil
  tetos. Limite de frequência exige estado compartilhado que este servidor não
  guarda. A diferença para o `/runs` é que ninguém descobre o `/runs` por
  acaso, e uma URL de webhook circula.

- **Variáveis do cliente: o outro lado da indireção.** Um bloco `Input` recebe
  `token_env`/`dsn_env` — o NOME de uma variável — e nunca o segredo, porque o
  workflow é gravado, versionado e mostrado na tela. Faltava quem DEFINE essas
  variáveis: `PUT /api/ambiente/variaveis/{nome}` grava no processo e em
  `data/ambiente/`, e `GET` lista só os nomes e se cada um tem valor. O valor
  não volta por rota nenhuma, **nem mascarado** — mascarado ainda vaza o
  comprimento, e o comprimento de um token identifica o provedor.

  Só nomes com prefixo `WF_`. Sem a cerca, a rota trocaria `ANTHROPIC_API_KEY`
  por outra chave, apontaria o `PATH` para outro binário, e a listagem
  revelaria que variáveis existem na máquina.

  **O que isso NÃO resolve.** O arquivo guarda segredo em claro; cifrar não
  ajuda sozinho, porque a chave para decifrar ficaria do lado. A permissão é
  pedida (`0600`) e **o Windows a ignora** — lá quem manda é a ACL do NTFS, e o
  arquivo sai `644`; quem hospeda em Windows precisa fechar `data/` por fora. E
  o buraco maior: **este servidor não tem autenticação**. Quem alcança a porta
  não LÊ segredo nenhum, mas ESCREVE — e escrever já basta para apontar o
  workflow de um cliente para o servidor de outra pessoa. Enquanto for assim,
  este servidor é de uso próprio ou de rede confiável.

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
