# Fila de Revisão Humana — Documento de Design

**Data:** 2026-09-15
**Status:** ✅ **APROVADO — construção autorizada**
**Escopo:** a terceira classe de custo da cascata, e a primeira superfície que muta estado
**Spec pai:** [`2026-09-14-agent-orchestrator-design.md`](2026-09-14-agent-orchestrator-design.md)
**Spec irmão:** [`2026-09-14-composicao-de-workflows-design.md`](2026-09-14-composicao-de-workflows-design.md)
**Fatia anterior:** [`2026-09-15-cascata-e-canvas-design.md`](2026-09-15-cascata-e-canvas-design.md)

---

## 0. O que este documento decide

Propostas do agente viram uma fila. Um humano aceita, rejeita ou corrige. A
decisão vira um `MatchResult` — e é ela, não a proposta, que resolve.

Isto fecha a terceira classe de custo da cascata. `CostClass.HUMANO` existe
desde a fatia anterior e nunca teve ninguém dentro; o canvas desenha duas
classes e declara uma terceira que o motor não tem.

O §4.7 do spec pai define o produto desta fatia em três frases:

> Fila simples. Para cada divergência: a proposta, a evidência citada de forma
> navegável, e três ações — aceitar, rejeitar, corrigir.
>
> A **corrigir** é a mais importante das três: é ela que gera sinal de treino.

E o §4.4 do spec de composição define a forma:

> Aprovação humana não é feature especial. É o último resolver de uma cascata.
> Nenhum mecanismo novo, nenhum modo de execução separado.

Este documento leva os dois ao pé da letra.

---

## 1. O estado que motivou, e um defeito que a conferência achou

### 1.1 A terceira classe está vazia

`CostClass` tem `REGRA = 0`, `AGENTE = 1`, `HUMANO = 2`. As duas primeiras têm
implementação; a terceira nunca teve. O canvas mostra `REGRA` três vezes e uma
lacuna de 13,2% — parte da qual um humano resolveria em segundos, se houvesse
por onde.

### 1.2 As métricas de hoje puniriam uma aprovação correta

**Achado desta conferência, não do spec.** A regra de falso positivo
(`metrics.py:119`) é:

```python
if not gt.deterministic_expected and ids(gt) & casados_todos
```

Um caso reservado ao agente, tocado por **qualquer** match, é erro. A regra foi
escrita quando todo match era determinístico, e ali ela está certa: uma camada
barata casando o que devia sobrar para o agente é exatamente o defeito que ela
caça.

Com um resolver humano emitindo matches, ela se volta contra o produto. Um
controller aprovando `conciliar_com(l00003)` numa `DEFASAGEM_TEMPORAL`
produziria um match, o caso seria "tocado", e a métrica registraria **falso
positivo por um acerto**. A `deterministic_rate` também passaria a somar
matches humanos e deixaria de ser determinística.

Consequência para esta fatia: as métricas precisam distinguir match por classe
de custo, e isso é parte do escopo, não polimento posterior.

### 1.3 A fonte da verdade não pode ser `MatchResult.layer`

A tentação é filtrar por `layer == "revisor"`. Seria o mesmo join de identidade
com proveniência que a revisão final da fatia anterior mandou remover do
canvas, com as mesmas consequências: um resolver que carimbe uma proveniência
que não é o próprio nome sai da conta em silêncio.

O motor sabe, no laço, qual resolver produziu quais matches. A informação existe
e é descartada. Esta fatia para de descartá-la.

---

## 2. Escopo desta fatia

**Dentro:** `Decision`, `Fila`, `RevisorHumano`, a guarda de idempotência no
`Investigator`, as métricas por classe, duas rotas HTTP, a tela da fila, e o
campo `divergiu` que expõe o sinal de treino.

**Fora, com gatilho nomeado:**

| Não construir agora | Desbloqueia quando |
|---|---|
| Máquina de estado da aprovação (Tier 2 do spec pai) | houver efeito colateral — escrita em ERP |
| `ajustar(<valor>)` como decisão aplicável | houver onde lançar um ajuste |
| Decidir sem proposta do agente | um revisor pedir |
| Evidência navegável (clicar id → destacar lançamento) | primeiro usuário real |
| Lock, múltiplos revisores, escrita concorrente | multi-tenant, Tier 4 |
| Exportar correções como `EvalCase` | ≥10 correções acumuladas, ou dado real |
| Parear órfãos no domínio | corte próprio, já decidido nesta conversa |
| SQLite no lugar do JSONL | a leitura ficar mensuravelmente lenta, ou houver escrita de mais de um processo |
| Framework de front | arrastar-e-soltar de resolver (gatilho herdado) |

---

## 3. O domínio: decisão, fila, e o resolver humano

### 3.1 Os tipos

```python
class Veredito(StrEnum):
    ACEITAR = "aceitar"
    REJEITAR = "rejeitar"
    CORRIGIR = "corrigir"


@dataclass(frozen=True)
class Decision:
    divergence_id: str
    veredito: Veredito
    tipo: DivergenceType | None        # o que o humano afirma; None ao rejeitar
    conciliar_com: frozenset[str]      # ids da outra ponta; vazio se não concilia
    autor: str
    quando: datetime                   # UTC, sempre
    motivo: str = ""
```

- **`ACEITAR`** copia `tipo` e `conciliar_com` da proposta.
- **`CORRIGIR`** é aceitar com edições: o humano fornece os dois.
- **`REJEITAR`** não concilia nada. `tipo` é `None`.

### 3.2 O parser de `acao_sugerida`

Hoje `acao_sugerida` é uma string validada só por `startswith(ACOES_VALIDAS)`.
Aceitar uma proposta exige extrair os ids de `"conciliar_com(l00003)"`, e esse
parser não existe. Ele entra nesta fatia: `conciliar_com(a, b)` → `{"a", "b"}`;
qualquer outra forma → conjunto vazio, e aceitar uma proposta assim é concordar
que ela não concilia nada.

### 3.3 `Fila`

Guarda propostas e decisões, as duas chaveadas por `divergence_id`. Os ids já
são estáveis entre passagens — `d-b-<id do lançamento>` e `d-l-<id>`, derivados
do lançamento órfão em `WorkSet.as_divergences()` — e é isso que torna a fila
chaveável sem inventar identidade nova.

```python
class Fila:
    def proposta(self, divergence_id: str) -> Proposal | None: ...
    def decisao(self, divergence_id: str) -> Decision | None: ...
    def pendentes(self) -> list[Proposal]: ...
    def decididas(self) -> list[tuple[Proposal, Decision]]: ...
```

### 3.4 `RevisorHumano`

Um `Resolver` de classe `HUMANO`, construído com a fila. Para cada divergência
do pool que tem decisão `ACEITAR` ou `CORRIGIR` com `conciliar_com` não vazio,
emite:

```python
MatchResult(
    bank_ids=..., ledger_ids=...,
    layer="revisor", rule="decisão humana",
    evidence={"autor": ..., "quando": ..., "motivo": ..., "veredito": ...},
)
```

**De que lado vai cada id.** A divergência contribui os próprios ids no lado
que já ocupa; os ids de `conciliar_com` são classificados **pelo pool**: id
presente em `work.bank` vai para `bank_ids`, id presente em `work.ledger` vai
para `ledger_ids`. Não se infere lado pelo prefixo do id nem pelo tipo da
divergência — o pool é a única fonte que não mente.

`MatchResult` exige pelo menos um id de cada lado. Uma decisão que deixasse um
dos lados vazio não é um match: cai na mesma regra do `conciliar_com` vazio e
não emite nada.

**Se algum id da decisão não estiver mais no pool, a decisão não se aplica** e é
pulada. É a guarda contra decisão obsoleta, e é o que mantém o motor coerente
quando uma regra passa a resolver o que antes sobrava.

### 3.5 O fantasma se resolve por consequência

A execução ao vivo mostrou que uma divergência real chega ao agente partida em
duas: `d-b-b00003` (órfão bancário) e `d-l-l00003` (órfão contábil do mesmo
caso). Aceitar em `d-b-b00003` casa `{b00003}×{l00003}` — e **os dois saem do
pool**. `d-l-l00003` deixa de existir na passagem seguinte.

**Entre passagens** isso é automático: `WorkSet.without()` roda depois que
`resolve()` retorna, e a passagem seguinte já recebe um `work` sem `b00003`
nem `l00003`. Uma decisão tardia sobre o meio-item encontra `l00003` fora do
pool e é ignorada pela guarda do §3.4.

**Dentro da mesma passagem** isso NÃO é automático — e a primeira versão deste
resolver errou exatamente aqui. `work` não encolhe durante o laço de
`resolve()`: `no_banco`/`no_contabil` são calculados uma vez, no início, a
partir do pool que a passagem recebeu. Se o operador aceita `d-b-b00003` e
`d-l-l00003` na mesma leva — o fluxo natural de quem vê as duas metades do
mesmo caso na fila e resolve as duas — as duas decisões ainda encontram
`l00003` (e `b00003`) no pool, porque nenhuma delas removeu nada de lá.
Sem guarda própria isso produzia dois matches para um único par, inflando
`bank_matched_total`/`ledger_matched_total` e quebrando o invariante
`sum(rate) + gap == 1.0`.

A guarda é o mesmo padrão que `ExactMatcher._casar` já usa entre lançamentos
bancários (`usados: set[str]`), aplicado agora entre decisões: o resolver
mantém um `consumidos: set[str]` que cresce a cada match emitido nesta
passagem, e trata qualquer id — o da própria divergência ou um citado em
`conciliar_com` — que já esteja em `consumidos` como decisão obsoleta, pulando
o caso inteiro. Consistente com a guarda do §3.4, mas não decorre dela: é
código à parte, porque o pool por si só não basta dentro de uma passagem.

Isto não substitui o pareamento no domínio, que continua sendo corte próprio.
Mas significa que a fila não precisa esperar por ele.

### 3.6 A guarda de idempotência no `Investigator`

O agente é classe `AGENTE` e o revisor é `HUMANO`, então o agente roda
**antes** em toda passagem. Sem guarda, a passagem 2 reinvestigaria tudo e
pagaria de novo.

`Investigator` ganha `fila: Fila | None = None`. Quando a divergência já tem
proposta, devolve a proposta guardada em vez de chamar o modelo.

É a capacidade "idempotência de ingestão" do Tier 1 aplicada à chamada mais
cara do sistema: reprocessar o mesmo extrato não pode duplicar nada — nem
chamada de modelo.

### 3.7 Quem escreve

**Ninguém dentro de `reconcile`.** Resolvers apenas leem a fila. O CLI grava
propostas depois da passagem; a API grava decisões. `reconcile` continua puro e
sem efeito colateral — é disso que o golden e o teste do dinheiro dependem.

A invariante do projeto segue de pé, agora com o terceiro ator: **proposta não
remove nada do pool; `Decision` é o único caminho humano até um match.**

---

## 4. Persistência e idempotência

### 4.1 Um JSONL append-only, escopado a workflow E dataset

```
data/fila/<workflow_id>/<dataset_id>.jsonl
```

**O escopo por dataset foi achado ao desenhar a API, e é obrigatório.** O id
`d-b-b00003` existe em toda semente. Uma decisão tomada olhando a semente 1 se
aplicaria ao `b00003` da semente 7, que é outro lançamento. `dataset_id` é
`s{seed}-n{n}-t{taxa}` no sintético e, quando houver dado real, o id do
extrato/período.

`data/` já é gitignorado. Cada linha é um objeto com `kind: "proposta" |
"decisao"`. O idioma é o do `RecordingClient` (`replay.py`): `mkdir` dos pais,
`open("a", encoding="utf-8")`, um objeto JSON por linha. `Fila` lê o arquivo
inteiro ao construir e indexa em memória.

### 4.2 Duas regras de leitura, diferentes de propósito

| Registro | Regra | Por quê |
|---|---|---|
| proposta | **primeira** vence; o escritor pula ids já presentes | o agente não se repete — §3.6 garante na origem, o escritor garante na chegada |
| decisão | **última** vence; toda submissão fica no log | um humano muda de ideia, e a auditoria precisa mostrar *que* mudou, *quando* e *por quê* |

O efeito é idempotente — enviar a mesma decisão duas vezes produz o mesmo
estado — sem apagar histórico.

**Append-only É a trilha de auditoria do Tier 1.** Não é funcionalidade
construída depois; é subproduto do formato, exatamente como o spec pai (§3.2)
prevê.

### 4.3 Serialização

`Proposal` carrega dois enums, um `Cost` e um `trace` de `TraceEvent` com
`detail: dict`. Enum vira `.value`; `datetime` vira ISO-8601 em UTC; `frozenset`
vira lista ordenada, para o arquivo ser diffável. A volta reconstrói pelos
tipos. `replay.py` já faz isto para `LLMResponse` — o padrão existe e é seguido.

### 4.4 O que fica de fora, dito

Escrita concorrente de dois processos no mesmo arquivo não tem lock. Numa
máquina, um usuário, `open("a")` por linha é seguro o bastante. Multiusuário é
multi-tenant, Tier 4 do spec pai, com gatilho lá.

---

## 5. As métricas aprendem classe de custo

### 5.1 O motor para de descartar a classe

```python
matches_by_class: dict[CostClass, list[MatchResult]]
```

Preenchido no laço de `reconcile`, ao lado de `cost_by_resolver` e
`matches_by_resolver`. **Sem join** — a classe vem do resolver que produziu o
match, no momento em que produziu. `ReconcileResult.matches` continua sendo a
lista achatada, e nada que hoje a lê muda.

### 5.2 Cada número declara sua classe

| Campo | Passa a considerar | Golden |
|---|---|---|
| `deterministic_rate`, `bank_matched` | só `REGRA` | intacto |
| `false_positives` | caso reservado ao agente tocado por match **de regra** | intacto |
| `false_negatives` | caso que a regra devia pegar e **a regra** não cobriu | intacto |
| `matched_amount`, `divergent_amount` | **todas as classes** | intacto |
| `bank_matched_total`, `resolution_rate` (novos) | todas as classes | não existem no golden |

**Por que os dois valores em dinheiro não seguem a taxa determinística.** Isto
saiu da auto-revisão, contra o que uma leitura apressada sugere. `bank_matched`
e `deterministic_rate` são medidas do *catálogo de regras* — o nome de uma delas
diz isso — e restringi-las a `REGRA` é o que as mantém honestas. Já
`divergent_amount` responde a pergunta de um controller: **quanto ainda está em
aberto**. Dinheiro que um humano conciliou não está em aberto, e mantê-lo ali
reportaria como problema um trabalho que já foi feito.

Os quatro continuam idênticos no golden porque a definição padrão não tem
resolver fora da classe `REGRA` — e o agente, mesmo quando entra, produz
proposta, nunca match.

**O golden fica intacto porque a definição padrão só tem regras** — com a fila
vazia, `RevisorHumano` não emite nada e todos os matches são `REGRA`. Os quatro
primeiros campos calculam exatamente o mesmo valor que hoje.

Um falso negativo continua sendo da regra mesmo quando um humano fecha o caso
depois: se o L2 devia ter pego e não pegou, isso é lacuna da regra, e escondê-la
atrás do trabalho humano seria mentir sobre o catálogo.

### 5.3 A lacuna do canvas

A lacuna da API passa a usar `bank_matched_total`. O canvas deixa de contar como
aberto o que já foi decidido, e ganha a linha `④ revisor · HUMANO` com taxa
real — a terceira classe desenhada pela primeira vez.

---

## 6. A API e a tela

### 6.1 Uma definição só, com a terceira classe sempre presente

`default_definition(fila: Fila | None = None)` passa a incluir `RevisorHumano`.
Sem fila, ele usa uma vazia em memória e não emite nada: golden idêntico, CLI
idêntica. A API injeta a fila em disco, escopada por workflow e dataset.

**Não há "definição servida" separada da "definição executada".** É o mesmo
objeto — a propriedade anti-drift da fatia anterior, preservada.

**Um teste existente muda de propósito, e isso é correto.**
`test_definicao_padrao_nao_tem_agente` hoje afirma
`classes == {CostClass.REGRA}`. Com o revisor na definição padrão, a asserção
passa a ser `CostClass.AGENTE not in classes`. A propriedade que importa nunca
foi "só existem regras" — foi **"nada aqui gasta dinheiro"**, e é ela que o
teste deve dizer. Trocar a asserção sem trocar o nome nem a docstring
transformaria um guarda de dinheiro num guarda de forma; o nome vai junto.

### 6.2 Rotas

```
GET  /api/fila/{workflow}?seed&n&taxa[&estado=pendente|decidida]
POST /api/fila/{workflow}/{divergence_id}/decisao
```

### 6.2.1 A memoização da execução deixa de ser correta sozinha

`_executar_memoizado` é `lru_cache` sobre `(workflow, seed, n, taxa)`. Com a
fila no meio, a execução **deixa de ser função só desses quatro valores**: ela
passa a depender do conteúdo do arquivo de decisões. Sem cuidado, aprovar uma
proposta e recarregar o canvas mostraria o estado anterior, e o revisor
concluiria que a aprovação não funcionou.

O POST de decisão chama `_executar_memoizado.cache_clear()`. Recomputar custa
milissegundos e a correção é óbvia de ler. A alternativa — incluir uma revisão
da fila na chave — preserva as entradas de outros datasets, e é o gatilho para
quando houver datasets suficientes para isso importar.

### 6.2.2 O corpo das rotas

O GET reconstrói o benchmark (determinístico, cacheado como a execução já é) e
junta cada proposta aos **lançamentos que ela julga** — o controller precisa ver
extrato e contábil lado a lado, não só o veredito do agente. Devolve tipo,
confiança, explicação, evidência (lista de strings) e a ação parseada. Com
`estado=decidida`, devolve também a decisão e o campo `divergiu` do §7.

O POST recebe `{veredito, tipo?, conciliar_com?, autor, motivo?}` e valida por
veredito:

| Veredito | Corpo | Efeito |
|---|---|---|
| `aceitar` | ignora `tipo`/`conciliar_com` | copia da proposta |
| `corrigir` | `tipo` obrigatório | usa o que o humano mandou |
| `rejeitar` | ignora ambos | nenhum match |

Aceitar uma proposta cuja ação é `investigar_manual` é concordar que o caso é
manual: decisão válida, registrada, sem match.

Divergência sem proposta → **404** nesta fatia.

### 6.3 Dinheiro, ainda

Propostas entram na fila **só pela CLI**. Nenhuma rota HTTP chama `reconcile`
com um resolver de classe `AGENTE`. A regra do §5 da fatia anterior — o caminho
caro não é guardado, é inexistente — continua valendo com a fila no meio.

O teste do espião ganha um caso: **decidir e depois executar** continua sem
chamada a `complete()` e sem `cost_class == "AGENTE"` na resposta.

### 6.4 A tela

`web/fila.html`, sem framework, servida pelo mesmo mount estático. Lista de
itens; cada um mostra os lançamentos, a proposta do agente e três botões.
*Corrigir* abre inline: um `<select>` da taxonomia e um campo de ids. O autor
fica em `localStorage` — é conveniência por revisor, exatamente o que
armazenamento local serve.

O gatilho de framework continua sendo arrastar-e-soltar de resolver, que não é
isto.

---

## 7. O sinal de treino

O §4.7 diz que toda `Decision` que diverge da `Proposal` é candidata a
`EvalCase`. A candidatura é barata aqui porque a fila já tem os dois lados
chaveados pelo mesmo id: o GET com `estado=decidida` devolve `divergiu: bool`,
verdadeiro quando o tipo **ou** os ids decididos diferem do que o agente propôs.

O sinal fica exposto, sem máquina nova. **A exportação para a suíte de avaliação
fica fora**, com gatilho no §2: dez correções, ou dado real. Antes disso é
pipeline para dois exemplos.

---

## 8. Verificação

### 8.1 Testes que ganham o próprio custo

| Teste | O que quebra se sumir |
|---|---|
| golden byte-idêntico | revisor com fila vazia emitiu algo, ou a taxa deixou de ser só-REGRA |
| match `HUMANO` em caso reservado ao agente | conta como falso positivo, ou move `deterministic_rate` |
| mesma decisão enviada duas vezes | matches duplicam, ou o log perde a segunda submissão |
| decisão com id fora do pool | estoura, ou fabrica match com id fantasma |
| guarda do `Investigator` | `complete()` é chamado para divergência já proposta |
| aceitar em `d-b-X` | `d-l-Y` sobrevive à passagem seguinte |
| decidir e depois executar | `complete()` chamado, ou classe `AGENTE` na resposta |
| ida e volta JSON de `Proposal` e `Decision` | um campo some — enum, `datetime`, `frozenset` ou `trace` |
| parser de `conciliar_com` | `"conciliar_com(l1, l2)"` deixa de render dois ids |

O teste do espião continua sendo assertado sobre o **estado do espião**, nunca
sobre exceção propagada — a técnica baseada em levantar erro foi provada vazia
contra o `Investigator` real, e está registrada em `DECISOES.md` P3.8.

### 8.2 A prova de ponta a ponta

1. `orchestrator-eval --via assinatura --seed 1 --n 30` → duas propostas na fila.
2. Abrir `fila.html`, aceitar a `DEFASAGEM_TEMPORAL` de `d-b-b00003`.
3. Executar de novo → o canvas mostra `revisor` com 1 item, a lacuna encolhe, e
   **`d-l-l00003` desapareceu**.

O fantasma resolvido por consequência, não por código especial. É o demo que
torna a fatia demonstrável para um controller.

---

## 9. Alternativas rejeitadas, com razão registrada

**A fila vive na API; o domínio não sabe dela.** POST grava decisões, um
endpoint "aplicar" fabrica matches por fora da cascata. Domínio intocado.
Rejeitada: aprovação vira caminho especial fora da cascata — exatamente o que o
§4.4 do spec de composição rejeita — e o canvas desenharia um resolver `HUMANO`
que o motor não tem. É o drift que a fatia anterior existiu para tornar
impossível.

**Resolver `HUMANO` bloqueante, com callback `decidir()`.** Na CLI pergunta no
terminal; na API, espera. Rejeitada: não cabe em HTTP e obriga a execução
inteira a esperar por uma pessoa. Fila é assíncrona por natureza; um resolver
que bloqueia é a forma errada do problema.

**Filtrar matches humanos por `layer == "revisor"`.** Uma linha, nenhum campo
novo. Rejeitada: é o join de identidade com proveniência que a revisão final da
fatia anterior mandou remover do canvas, com a mesma consequência — um resolver
que carimbe outra proveniência sai da conta em silêncio.

**Parear órfãos no domínio junto com esta fatia.** Deixaria a fila limpa desde o
primeiro demo e cortaria o custo do agente pela metade. Rejeitada para esta
fatia: muda a contagem que o golden congela, o que exige regenerá-lo de
propósito, e acoplaria duas mudanças de raio diferente num corte só.

**SQLite desde já.** Rejeitada: um JSONL append-only já é a trilha de auditoria
pedida, é diffável, e não tem dependência. Gatilho de troca nomeado no §2.

---

## 10. Riscos

| Risco | Severidade | Mitigação |
|---|---|---|
| A mudança nas métricas move um número do golden | Alta | O golden roda em toda tarefa; a definição padrão só tem regras, então os quatro campos são calculados sobre o mesmo conjunto |
| Decisão aplicada ao dataset errado | Alta | Escopo por `dataset_id` no caminho do arquivo; toda rota da fila exige os parâmetros do benchmark |
| A guarda de idempotência mascara uma regressão do agente | Média | A guarda é por `divergence_id` presente na fila; apagar o arquivo força reinvestigação, e o teste do espião pina que a guarda funciona |
| Um endpoint passa a gastar dinheiro | Média | Nenhuma rota monta cascata com classe `AGENTE`; pinado por teste, com espião assertado sobre estado |
| JSONL cresce sem limite | Baixa | Uma linha por proposta e por submissão de decisão; na escala de um dataset sintético é irrelevante. Gatilho de troca no §2 |

---

## 11. Glossário

- **`Decision`** — o que um humano afirma sobre uma divergência: veredito, tipo, ids a conciliar, autor, quando e por quê.
- **Veredito** — `ACEITAR`, `REJEITAR` ou `CORRIGIR`.
- **Fila** — as propostas e decisões de um workflow sobre um dataset, chaveadas por `divergence_id`.
- **`RevisorHumano`** — o resolver de classe `HUMANO` que transforma decisão em `MatchResult`.
- **`dataset_id`** — a identidade do conjunto sobre o qual uma decisão foi tomada. `s{seed}-n{n}-t{taxa}` no sintético.
- **`divergiu`** — verdadeiro quando a decisão difere da proposta. É o sinal de treino do §4.7 do spec pai.
