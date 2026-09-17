# Plataforma geral: qualquer trabalho, orquestrado com custo

**Data:** 2026-09-16
**Estado:** proposta
**Antecessor:** `2026-09-16-runtime-de-orquestracao-design.md` (M0–M8 entregues)

---

## 0. A tese, dita para escopo amplo

O spec anterior abriu com: *"CrewAI orquestra agentes. Agent Orchestrator deve
orquestrar trabalho."* Isso continua valendo e ficou pequeno na execução: o
catálogo virou um cardápio de conciliação e ninguém notou por oito PRs.

A tese, na forma que o escopo amplo exige:

> **Qualquer trabalho repetitivo pode ser descrito como um pool de itens e uma
> cascata de resolvers ordenada por custo. A plataforma existe para que o
> trabalho desça essa cascata o mais cedo possível — e para que ela fique mais
> barata à medida que é usada.**

Duas metades, e a segunda é a que ninguém mais tem. A primeira é arquitetura: já
está construída e medida (85,3% do volume morre na classe `REGRA`). A segunda é
o produto: **o caminho caro ensina o caminho barato.**

### 0.1 O que "geral" significa aqui, e o que não significa

**Significa:** conciliação bancária, triagem de issues, aprovação de compras,
classificação de chamados, revisão de contratos, roteamento de e-mail, controle
de qualidade de cadastro — qualquer coisa em que chegam N itens parecidos por
período e alguém decide o que fazer com cada um.

**Não significa:** tarefa única e irrepetível, trabalho criativo aberto, ou
qualquer coisa em que não exista noção de "item" e "resolvido". Um orquestrador
de trabalho que aceita tudo não mede nada — e medir é a única vantagem que este
projeto tem.

Esta fronteira é explícita porque ela é vendável: *"se o seu trabalho tem itens
e uma decisão por item, a gente mede quanto dele pode deixar de custar."*

---

## 1. Auditoria: o que já é geral e o que está preso

Levantado no código, não no README.

### 1.1 Já é geral, e foi provado por mais de um domínio

| Peça | Onde | Prova de generalidade |
|---|---|---|
| `WorkItem` / `WorkSet` | `kernel/work.py` | três `kind` diferentes em uso |
| `Resolution` / `Proposal` | `kernel/resolution.py` | `tipo: str`, genérico desde o PR #6 |
| `CostClass` + `Stage.ordered()` | `kernel/cost.py`, `definition.py` | ordem por custo vale em `procurement` |
| `Resolver` (protocolo) | `kernel/resolver.py` | um contrato para regra, agente e humano |
| `Agent` + `AgentSpec` | `agent/agent.py` | extraído no M2, usado por dois domínios |
| `AgenteDeclarado` | `agent/declarado.py` | um domínio novo sem uma linha de Python |
| `Crew` | `crew/crew.py` | resolver de classe `CREW`, sem domínio |
| `ToolRegistry` (catálogo × executável) | `agent/tools/registry.py` | contexto injetado na execução |
| Camada de avaliação | `evaluation/` | pontua qualquer `Run` contra qualquer conjunto |
| `Source` | `kernel/source.py` | `ref` estável, prefixo por origem |

### 1.2 Ainda preso, e por quê

| Peça | Prisão | Custo de destravar |
|---|---|---|
| `CATALOGO` do grill | cinco resolvers de conciliação, construtor tipado em `ToolContext` | §3, §6 |
| `workflows.registry()` | `ID_EMBUTIDO = "conciliacao"` mais receitas de disco | §9 |
| `orchestrator/metrics.py` | `bank_total`, `ledger_total`; violação `metrics → taxonomy` na catraca | substituído por `evaluation/metrics.py` |
| CLI `bench` | benchmark sintético de conciliação | §8 |
| Canvas | consome `/api/catalogo` | §9 |

### 1.3 Construído e DESLIGADO — o achado mais importante da auditoria

**`ToolPermission.WRITE` e `ToolSpec.compensates` existem, são validados no
registro, e não têm um único usuário.** Toda ferramenta do projeto é
`READ_ONLY`.

Isso significa que hoje a plataforma **observa e propõe; ela não age.** Para
"automatizar qualquer tarefa", agir é obrigatório — e a boa notícia é que a
guarda já está escrita: o registro RECUSA registrar uma ferramenta `WRITE` que
não declare compensadora. O que falta é §7, não é fundação.

**E já publicamos MCP sem nunca consumir.** `eval/assinatura.py` monta um
servidor MCP com `create_sdk_mcp_server` para expor as ferramentas de
conciliação ao Claude Code. O caminho inverso — consumir servidores MCP de
terceiros — é o que transforma "escreva uma ferramenta em Python" em "conecte o
que você já tem" (§3.3).

---

## 2. Os cinco eixos da generalidade

Um trabalho qualquer precisa de cinco coisas. Hoje temos duas e meia.

| Eixo | Pergunta | Hoje | Alvo |
|---|---|---|---|
| **Entrada** | de onde vêm os itens? | `Source`, uma implementação sintética | §8 |
| **Ferramentas** | o que o sistema consegue tocar? | código Python por domínio | §3 |
| **Decisão** | quem resolve, e em que ordem de custo? | completo | mantém |
| **Ação** | o que ele FAZ com a decisão? | nada — só propõe | §7 |
| **Aprendizado** | ele fica mais barato com o uso? | não | §6 |

Os dois vazios — ação e aprendizado — são o produto. Os outros três são
infraestrutura e estão quase prontos.

---

## 3. Ferramentas: quatro origens, uma interface

**POR QUE.** "Qualquer tarefa" quebra na primeira pergunta prática: o agente
precisa tocar alguma coisa. Hoje a única resposta é *"escreva uma função Python
e registre"*, o que restringe a plataforma a quem a desenvolve.

**ONDE.** `agent/tools/`, mais um pacote `tools/fontes/`.

**COMO.** Quatro origens, todas produzindo `ToolSpec` — nenhuma introduz um
segundo tipo de ferramenta:

### 3.1 Código de domínio (existe)

O que temos. Continua sendo a via para lógica que precisa de Python de verdade.

### 3.2 Ferramentas genéricas declarativas (novo)

Tipos parametrizáveis, sem código:

| Tipo | Parâmetros | Permissão |
|---|---|---|
| `http` | método, url template, headers, schema de saída | READ_ONLY ou WRITE |
| `sql` | conexão, query com parâmetros nomeados | READ_ONLY |
| `arquivo` | caminho base, glob, formato | READ_ONLY |
| `busca_tabela` | tabela em memória, chave | READ_ONLY |
| `calculo` | expressão sobre campos do item | READ_ONLY |

A `url template` e a `query` são interpoladas sobre os **argumentos declarados**,
nunca sobre o payload cru — interpolar payload direto numa query é injeção com
outro nome.

**Cada uma declara custo.** `ToolSpec.cost_microcents` existe e é zero em todas
as locais de hoje. Uma chamada HTTP a uma API paga não é zero, e o orçamento do
agente já sabe somar isso.

### 3.3 MCP consumido (novo, e é o que destrava "qualquer")

Um servidor MCP É um catálogo de ferramentas com schema. Conectar um dá ao
agente as capacidades que a empresa já tem — Slack, GitHub, Jira, Drive, o ERP
interno com um wrapper — sem que a gente escreva um adaptador por integração.

**POR QUE isto e não uma biblioteca de integrações nossa.** Porque a biblioteca
nossa nunca alcança o ERP do cliente, e o MCP dele já existe ou custa um dia
para existir. Escolher o padrão da indústria aqui é a diferença entre um
catálogo que a gente mantém e um que o ecossistema mantém.

**DEPENDÊNCIAS.** Um cliente MCP. Isso quebra a propriedade de "uma dependência
de runtime" — e por isso entra como **extra opcional** `[mcp]`, igual a `[api]`
e `[otel]`. Quem não conecta MCP não instala.

**IMPACTO no que já existe:** `ToolRegistry` não muda. Um servidor MCP vira N
`ToolSpec` com `permission` derivada do anúncio do servidor, e `fn` que faz a
chamada. O agente não sabe a diferença, o orçamento conta igual, o trace
registra igual.

**A guarda que não é opcional.** Ferramenta de servidor externo entra como
`EXTERNAL`, nunca `READ_ONLY`, mesmo quando o servidor jura que só lê. A
diferença entre as duas é quem responde pelo que acontece — e não somos nós.

### 3.4 Agente como ferramenta (novo, barato)

Um `AgenteDeclarado` exposto como `ToolSpec`. É o que permite composição
hierárquica sem o `Crew` hierárquico: um agente de triagem chama um agente
especialista como se fosse uma função.

**Custo:** o do agente interno, somado ao de quem chamou. Sem isso, o orçamento
de dois níveis vira um só, e o teto de execução para de significar alguma coisa.

---

## 4. Agentes: o que já é declarativo e o que falta

`AgenteDeclarado` (entregue) cobre `kind`, prompt, vocabulário, rótulo de
abstenção, ferramentas, turnos e orçamento. Falta:

**4.1 Saída estruturada além de `tipo/explicacao/evidencia`.** Hoje o formato da
proposta é fixo. Um domínio que precise extrair campos (valor, data, CNPJ)
precisa de um schema de saída próprio. **COMO:** `AgenteDeclarado.schema_saida`
opcional, e `Proposal.dados: Mapping[str, Any]` para carregá-lo. O `tipo`
continua obrigatório porque a cascata e a avaliação dependem dele.

**4.2 Exemplos no prompt.** Poucos casos rotulados melhoram classificação mais
que qualquer instrução. **COMO:** `AgenteDeclarado.exemplos: tuple[Exemplo, ...]`,
renderizados no system. **E é aqui que o M6 fecha um laço:** os exemplos saem do
`EvalDataset`, e a guarda de contaminação impede usar como exemplo um caso que
está no conjunto de teste.

**4.3 Política de escolha de modelo.** Hoje o modelo é um campo. Com o M6,
"qual modelo para este agente" é uma linha de benchmark — `microcents_per_correct_proposal`
por braço. **COMO:** `AgenteDeclarado.modelo` aceita `"auto"`, e a escolha vem
do último `BenchmarkResult` daquele agente. Sem benchmark, `auto` recusa em vez
de chutar.

---

## 5. Crews: o que muda com escopo amplo

O `Crew` do M8 é genérico e não precisa de mudança estrutural. Duas adições:

**5.1 Tripulação heterogênea medida.** Hoje o experimento usa dois agentes
IDÊNTICOS de propósito, para perguntar uma coisa só. Com escopo amplo, a
pergunta interessante é outra: **especialistas diferentes no mesmo item**. Isso
é um `BenchmarkArm`, não uma feature.

**5.2 `Process.HIERARCHICAL` com delegação por ferramenta.** Hoje o gerente
roteia citando o nome na explicação, e a queda é explícita. Com §3.4 (agente
como ferramenta), a delegação vira chamada de ferramenta de verdade — o gerente
tem uma ferramenta por especialista.

**O que NÃO muda:** voto ponderado por confiança continua fora, e concordância
continua sem elevar confiança. As duas decisões valem mais em escopo amplo, não
menos: quanto mais domínios, mais tentador seria confiar num número que o M6
ainda não validou.

---

## 6. Regras genéricas e o LAÇO DE PROMOÇÃO

Esta seção é o produto. As outras são infraestrutura.

### 6.1 O problema

A tese é "o barato antes do caro". Num domínio novo, **não existe nada barato no
dia 1**: ninguém escreveu as regras. O sistema começa 100% na classe `AGENTE`,
que é o pior custo possível, e é exatamente onde um framework de agentes comum
também começa — e permanece.

### 6.2 Regras genéricas (o piso)

Tipos declarativos que cobrem a maior parte do que uma regra de triagem faz:

| Tipo | O que decide | Exemplo |
|---|---|---|
| `igualdade` | campos idênticos entre itens | documento + valor + data |
| `tolerancia` | campos dentro de uma folga | valor ±5 centavos, data ±3 dias úteis |
| `agrupamento` | um item de um lado contra N do outro | um pagamento cobrindo N notas |
| `tabela` | consulta a uma tabela de decisão | fornecedor → centro de custo |
| `padrao` | regex ou lista de termos sobre um campo | assunto contém "cancelar" |
| `limiar` | comparação numérica | valor > R$ 10.000 → humano |

Os três primeiros são exatamente L1, L2 e L3 generalizados — o que prova que a
lista não é inventada: ela é a conciliação com os nomes dos campos abertos.

### 6.3 O laço de promoção — a parte que ninguém mais tem

**POR QUE.** Um agente que resolve o mesmo caso mil vezes gastou mil vezes.
Quase sempre há um padrão determinístico ali, e hoje ele é jogado fora a cada
execução.

**COMO, em cinco passos, e cada um usa peça que já existe:**

1. **Observar.** O `Run` já registra, por item, o que o agente propôs e com que
   evidência. O `harvest` (M6) já transforma decisão humana em caso.
2. **Hipotetizar.** Um agente de classe `AGENTE` — o *promotor* — lê N casos
   confirmados e propõe uma **regra genérica** (§6.2) que os explicaria.
3. **Testar sem custo.** A regra proposta roda sobre o `EvalDataset` acumulado.
   Isso é gratuito: regra não chama modelo.
4. **Medir com o instrumento que já existe.** Dois `BenchmarkArm` sobre o mesmo
   conjunto — cascata atual × cascata com a regra nova. O critério de promoção
   é `RegressionCheck`: **zero falso positivo novo**, precisão não cai além do
   limiar, e custo por acerto desce.
5. **Promover.** A regra entra na cascata **antes** do agente, porque
   `Stage.ordered()` ordena por `CostClass` e uma regra é `REGRA`. O trabalho
   que ela captura para de custar.

**A propriedade que isso dá ao produto, e que é o pitch inteiro:**

> No dia 1, 100% do trabalho passa pelo modelo.
> No dia 90, a parte repetitiva não passa mais — e existe um número dizendo
> quanto deixou de custar.

**O que impede isso de virar promessa vazia.** Três guardas, e nenhuma é nova:

- **Promoção exige medição, não plausibilidade.** Passo 4 é `RegressionCheck`
  com `zero_tolerance=("false_positives",)`. Uma regra que fecha errado é pior
  que um agente caro — decisão 24, e ela não muda de opinião aqui.
- **A guarda de contaminação vale.** A regra é testada contra casos ANTERIORES
  aos runs que a originaram (`elegiveis_para`). Sem isso mediríamos memorização.
- **Promoção é reversível e registrada.** Uma regra promovida é uma entrada na
  `Receita`, com a data e o `BenchmarkResult` que a justificou. Despromover é
  remover a entrada.

**RISCO honesto:** o laço precisa de volume. Com dez itens por mês não há
padrão a achar, e o promotor vai propor regras que passam no conjunto pequeno e
falham na produção. **Mitigação:** mínimo de casos configurável, e a recusa de
promover é a resposta default — igual ao veredito escalado do P6.92.

### 6.4 Por que a regra promovida NÃO é código gerado

Tentação óbvia: o agente escreve Python. Recusado.

Código gerado precisa ser revisado, versionado, testado e tem superfície de
execução arbitrária. Uma **regra genérica declarada** tem os parâmetros
limitados aos tipos de §6.2, roda num interpretador que a gente escreveu, e é
diffável por quem não programa.

O preço: regras que não cabem nos seis tipos precisam de código humano. É o
preço certo — e é o mesmo trade do `AgenteDeclarado` (§0 do `declarado.py`).

---

## 7. Ação: ligar o que está construído e desligado

**POR QUE.** "Automatizar qualquer tarefa" sem agir é um classificador caro.
Hoje toda ferramenta é `READ_ONLY` e nenhuma resolução vira efeito no mundo.

**O QUE JÁ EXISTE:** `ToolPermission.WRITE`, `ToolSpec.compensates`, e a recusa
de registro sem compensadora. A fundação está escrita e sem usuário.

**O QUE FALTA, e cada item tem um motivo que já foi pago noutro lugar:**

**7.1 Efeito é resolução, não proposta.** Uma ação só roda a partir de uma
`Resolution` — nunca de uma `Proposal`. É a invariante nº 1 aplicada onde ela
mais custa: proposta não resolve, e portanto proposta não age.

**7.2 Ensaio antes de agir (`dry_run`).** Toda ferramenta `WRITE` executa
primeiro em modo ensaio, que devolve o que FARIA. O ensaio é o que o revisor
humano aprova. Sem isso, a aprovação humana é sobre uma descrição em prosa, e
prosa não é o que vai rodar.

**7.3 Idempotência por chave.** Toda ação carrega uma chave derivada do
`(run_id, item_id, ferramenta)`. Reexecutar um run — que é o mecanismo de
durabilidade do `ReplayResume` — não pode duplicar um pagamento.

**7.4 Compensação registrada.** A compensadora declarada é chamada quando uma
resolução é revertida. O log de compensação é append-only, como a fila e o
armazém de casos, e pelo mesmo motivo.

**7.5 Autonomia por classe de ação.** `ExecutionPolicy` já tem `Autonomy`.
Ação externa irreversível (pagamento, e-mail para cliente, publicação) exige
`HUMANO` na cascata antes dela, e isso é verificado na construção da
`WorkflowDefinition` — não em tempo de execução, quando já é tarde.

**IMPACTO:** é a mudança de maior risco do plano inteiro. Um defeito aqui não é
um número errado num relatório; é dinheiro transferido ou e-mail enviado. Por
isso ela vem DEPOIS da avaliação estar madura, e não antes.

---

## 8. Entrada: de onde o trabalho vem

`Source` existe, com `ref` estável. Falta implementação além da sintética.

| Fonte | `ref` | Nota |
|---|---|---|
| `arquivo` | `file:<caminho>@<sha256>` | o hash é o que torna o replay possível |
| `http` | `http:<url>@<etag ou hash>` | polling com cursor |
| `webhook` | `hook:<id do evento>` | o evento é o item |
| `fila` | `queue:<tópico>@<offset>` | offset é o cursor |
| `agenda` | `cron:<expr>@<instante>` | dispara uma execução |

**A regra que vale para todas:** `ref` estável ou não há replay. É o que o
docstring de `Source` já diz, e é o que uma implementação apressada quebra
primeiro (um `ref` com `datetime.now()` dentro).

---

## 9. O agente arquiteto: quem desenha a cascata

**POR QUE.** O pedido é *"qualquer tarefa automatizada com a crew/workflow que o
agente pensar"*. Hoje o `Entrevistador` existe e escolhe entre CINCO resolvers
de conciliação. Generalizá-lo é o que fecha o pedido.

**COMO.** O entrevistador ganha ferramentas novas, e cada uma corresponde a uma
peça deste spec:

| Ferramenta | O que ela cria | Seção |
|---|---|---|
| `perguntar` | (existe) | — |
| `declarar_agente` | um `AgenteDeclarado` | §4 |
| `declarar_regra` | uma regra genérica | §6.2 |
| `escolher_ferramentas` | recorte do catálogo do domínio | §3 |
| `declarar_tripulacao` | um `Crew` | §5 |
| `propor_workflow` | (existe, generalizado) | — |
| `fora_do_catalogo` | (existe) | — |

**A restrição que mantém isso honesto:** o arquiteto compõe a partir do que
EXISTE — ferramentas conectadas, tipos de regra, o laço de agente. Ele não
escreve código, não inventa ferramenta e não pode propor uma cascata que
`construir()` recuse. É a mesma disciplina de hoje, com um catálogo maior.

**E o desfecho `fora_do_catalogo` fica mais importante, não menos.** Num escopo
amplo, a tentação de forçar qualquer pedido num workflow é maior. Dizer *"isto
não cabe, e o que faltaria é X"* é a resposta que constrói confiança — e X vira
o roadmap.

---

## 10. Custo: o que muda quando o escopo abre

`Cost` mede token. Com §3 e §7, uma execução também gasta em:

- **chamada de ferramenta paga** — `ToolSpec.cost_microcents`, que já existe e é
  sempre zero hoje;
- **ação externa** — uma transferência tem tarifa;
- **tempo humano** — a classe `HUMANO` é a mais cara da enum e a única sem
  preço.

**COMO:** `Cost` ganha `external_microcents`, somado pelo `ToolRegistry` a
partir do `cost_microcents` da spec. **`HUMANO` ganha preço configurável por
workflow** — não porque a gente saiba quanto vale a hora de um revisor, mas
porque sem um número a cascata não consegue comparar "escalar" com "gastar mais
token", e essa é a comparação central do produto.

**A constraint não muda:** inteiro em micro-centavos, ponto flutuante proibido.
Já custou uma correção (unidade BRL contra µ¢ USD, P6.x) e vai custar de novo se
alguém relaxar.

---

## 11. Avaliação num domínio novo

O M6 mede qualquer `Run` contra qualquer `EvalDataset` — isso já é geral. O que
falta é o **começo**: um domínio novo não tem conjunto de avaliação.

**A sequência, e ela é barata:**

1. **Dia 1:** sem conjunto. O sistema roda 100% agente e não sabe se acerta.
2. **Primeiras revisões:** `harvest` colhe cada decisão humana. Trinta revisões
   dão um conjunto que já distingue braços.
3. **Quando o conjunto passa do mínimo:** o benchmark começa a responder
   perguntas — qual modelo, com ou sem ferramenta, agente ou tripulação.
4. **Quando há padrão:** o laço de promoção (§6.3) liga.

**A honestidade obrigatória:** entre 1 e 3 o produto não sabe se está acertando,
e tem de DIZER isso. `EvalResult.custo_medido` já faz o análogo para custo; o
equivalente para qualidade é uma taxa de precisão que se recusa a existir antes
de um mínimo de casos — em vez de imprimir 100% sobre dois itens.

Este projeto já publicou duas conclusões erradas por ler número pequeno como
resultado (P6.81 e P6.84, as duas revogadas). A regra do P6.92 — a ressalva
escala com a amostra — vale para domínio novo com força dobrada.

---

## 12. Milestones

Cada um é entregável e mede alguma coisa.

| M | O quê | Depende | Por que nesta ordem |
|---|---|---|---|
| **G1** | Catálogo por domínio no canvas; agente editável na tela | entregue: `AgenteDeclarado`, `/api/dominios` | fecha o buraco que o dono achou |
| **G2** | Ferramentas genéricas declarativas (§3.2) | G1 | primeira capacidade sem código |
| **G3** | Regras genéricas (§6.2) + interpretador | G1 | sem isso não há piso barato num domínio novo |
| **G4** | Fontes: arquivo e HTTP (§8) | G2 | o trabalho passa a entrar sozinho |
| **G5** | Arquiteto generalizado (§9) | G2, G3 | "o agente pensa o workflow" |
| **G6** | MCP consumido (§3.3) | G2 | o catálogo deixa de ser nosso |
| **G7** | **Laço de promoção (§6.3)** | G3, M6 | **o produto** |
| **G8** | Ação: WRITE, ensaio, idempotência, compensação (§7) | G4, M6 maduro | maior risco, por último |
| **G9** | Custo externo e preço do humano (§10) | G8 | a cascata passa a comparar tudo |

**G7 é o marco que importa.** G1–G6 constroem uma plataforma de agentes
competente e substituível. G7 é o que nenhum concorrente tem, porque ele exige
exatamente as três coisas que este projeto construiu antes de precisar delas:
classe de custo na execução, conjunto de avaliação com procedência, e benchmark
com contrafactual.

---

## 13. O que este plano deliberadamente NÃO faz

- **Não gera código.** Nem regra, nem ferramenta, nem agente. §6.4.
- **Não aceita trabalho sem itens.** §0.1. Um orquestrador que aceita tudo não
  mede nada.
- **Não pondera voto por confiança de LLM.** Continua fora até o M6 medir se
  essa confiança significa alguma coisa.
- **Não deixa proposta agir.** §7.1. É a invariante mais cara do projeto e o
  escopo amplo é justamente onde ela seria mais tentador furar.
- **Não promove regra por plausibilidade.** §6.3, passo 4.
- **Não publica taxa de precisão sobre amostra insuficiente.** §11.

---

## 14. Riscos, e o que cada um custaria

| Risco | Sintoma | Mitigação |
|---|---|---|
| Promoção de regra ruim | falso positivo em produção; fecha errado e ninguém olha | `zero_tolerance` no `RegressionCheck`; promoção reversível |
| Volume insuficiente | promotor propõe regra que passa em 20 casos e falha em 2000 | mínimo de casos; recusa é o default |
| Ferramenta MCP hostil | servidor de terceiro faz mais do que anuncia | `EXTERNAL` sempre; ação irreversível exige `HUMANO` antes |
| Ação sem idempotência | replay duplica pagamento | chave derivada de `(run, item, ferramenta)`; §7.3 |
| Escopo virar sopa | "orquestrador de qualquer coisa" que não mede nada | §0.1, e ela é vendável |
| Prompt do arquiteto virar produto | a qualidade do sistema passa a ser a qualidade de um prompt | o arquiteto compõe do catálogo, não inventa; `construir()` recusa o impossível |

---

## 15. A frase que resume, e que precisa continuar verdadeira

> Um framework de agentes te diz **quanto você gastou**.
> Este te diz **se valeu** — e depois **para de cobrar pela parte que já
> aprendeu**.

A primeira metade está construída e medida. A segunda é G7.
