# Grill de Conciliação — Documento de Design

**Data:** 2026-09-15
**Status:** 🟡 aguardando revisão do dono
**Escopo:** de uma descrição em prosa a uma `WorkflowDefinition` executável, via entrevista
**Spec pai:** [`2026-09-14-agent-orchestrator-design.md`](2026-09-14-agent-orchestrator-design.md)
**Spec irmão:** [`2026-09-14-composicao-de-workflows-design.md`](2026-09-14-composicao-de-workflows-design.md)
**Fatia anterior:** [`2026-09-15-fila-de-revisao-humana-design.md`](2026-09-15-fila-de-revisao-humana-design.md)

---

## 0. O que este documento decide

O parceiro descreve o problema dele em prosa. O maestro entrevista — pergunta
o que a descrição não respondeu — e ao final propõe uma cascata: quais
resolvers, com quais parâmetros. A proposta vira receita em disco, roda no
benchmark, e aparece desenhada no canvas.

Ou o maestro diz que não dá, e explica o que faltaria.

Esta é a primeira fatia em que o sistema **produz** um workflow em vez de
executar o único que existe.

### 0.1 A restrição que torna a fatia viável agora

O espaço de saída é pequeno e finito. Hoje o catálogo inteiro cabe numa
tabela:

| Resolver | Classe | Parâmetros |
|---|---|---|
| `L1` `ExactMatcher` | REGRA | nenhum |
| `L2` `ToleranceMatcher` | REGRA | `max_cents`, `max_business_days` |
| `L3` `GroupingMatcher` | REGRA | `max_group_size`, `max_business_days`, `max_candidates` |
| `agente` `Investigator` | AGENTE | `max_turns`, teto de gasto |
| `revisor` `RevisorHumano` | HUMANO | nenhum |

São cinco entradas e oito valores. Um grill sobre um catálogo deste tamanho
não pode inventar um resolver que não existe — e é por isso que toda receita
gerada roda. Sobre um catálogo grande e aberto, essa garantia teria que ser
verificada; aqui ela é estrutural.

Isso também é o **limite honesto** desta fatia: a entrevista só descobre
coisas que o motor sabe fazer. O §2.2 registra o que isso exclui.

---

## 1. O estado que motivou

### 1.1 O produto é a entrevista, não o conciliador

A visão declarada pelo dono do projeto, verbatim:

> quero que a partir de uma descrição, o maestro / agent orchestrator faça o
> grill para entender o problema nos detalhes que lhe faltar e consiga sugerir
> um workflow com agentes ou code para automatizar/resolver esse case do
> parceiro

Nada no repositório consome uma descrição. `_WORKFLOWS` é um dict com uma
entrada apontando para uma função Python; criar workflow hoje é escrever
código e fazer deploy.

### 1.2 O que já existe e esta fatia reaproveita

- O protocolo `LLMClient` ([`agent/llm.py`](../../../src/orchestrator/agent/llm.py)),
  que permite testar laço, orçamento e formato sem gastar um centavo.
- A disciplina de saída tipada por schema de ferramenta, provada em
  `conciliar_com` no investigador.
- O teto de turnos e o retry de formato, com a derivação de orçamento feita em
  código e pinada por teste.
- A cascata, as métricas por classe de custo, e o canvas que desenha.

### 1.3 Três defeitos latentes que esta fatia obriga a corrigir

**O `.gitignore` não cobre receitas.** Ele ignora `data/real/`,
`data/scratch/` e `*.jsonl`. Uma receita em `data/workflows/<id>.json` seria
commitada, e a `justificativa` dela carrega a descrição do problema do
parceiro — dado de terceiro, que o spec pai proíbe versionar. A fila escapou
por acidente do formato (`.jsonl`), não por decisão.

**`eval/assinatura.py` não serve para a entrevista.** Ele usa `query()`, que é
one-shot: um prompt, uma resposta. A entrevista é multi-turno com humano no
meio. Não há reaproveitamento; é adaptador novo.

**O nome `fila` é um contrato não verificado.** `_construir_definicao`
introspecciona o nome literal do parâmetro para decidir se repassa a fila.
Existe teste travando isso para `default_definition`; fábricas construídas de
receita caem na mesma armadilha e precisam do teste análogo.

---

## 2. Escopo desta fatia

### 2.1 Dentro

1. Catálogo de resolvers como tabela única, fonte do schema **e** do construtor.
2. Entrevista aberta com saída tipada em três caminhos.
3. `Receita` serializável e `construir(receita) → WorkflowDefinition`.
4. Registro em disco: gravar, ler, listar, recusar sobrescrita.
5. `orchestrator-grill`: entrada de CLI própria.
6. Execução no benchmark ao final, com a ressalva do §8.2 impressa.
7. `GET /api/workflows` e o canvas desenhando workflow gerado.
8. `ClienteAusente` e o 409, que preservam o invariante de dinheiro da API.
9. `.gitignore` como allowlist sob `data/`.

### 2.2 Fora, com gatilho

| Adiado | Gatilho para voltar |
|---|---|
| Grill olhar dados para **medir** a tolerância em vez de perguntar | Existirem dados de parceiro no sistema |
| Otimização iterativa: propõe → mede → ajusta → repropõe | Propostas boas mas mal calibradas |
| Entrevista na web | Qualidade da entrevista validada na CLI |
| Editar receita existente conversando | Alguém pedir duas vezes |
| Cascatas multi-stage | Um caso precisar de ordem que a classe de custo não expressa |
| Resolvers fora de conciliação | Generalização do `WorkSet` (fatia 3 do roadmap) |
| Avaliar a *qualidade* da entrevista com gabarito | Existirem casos reais suficientes para formar gabarito |

### 2.3 A ressalva registrada

A entrevista aberta foi escolhida pelo dono **sobre** a recomendação de ficha
fixa. A objeção levantada, para constar: entrevista aberta não é avaliável do
jeito que o investigador é — não existe gabarito de "boa pergunta", e nenhum
teste desta fatia prova que o grill pergunta bem. O que este design salva é a
**saída**: as perguntas ficam livres, a saída é tipada, e nenhuma
configuração inválida ou valor inventado consegue atravessar.

O que resta sem rede: o modelo pode fazer perguntas ruins, redundantes, ou em
ordem confusa, e nada aqui detecta isso. Só uso com parceiro real detecta. O
gatilho do §2.2 para gabarito é a saída dessa dívida.

---

## 3. O catálogo: a tabela única

`grill/catalogo.py`.

```python
@dataclass(frozen=True)
class ParametroSpec:
    nome: str
    tipo: type          # int hoje; o schema JSON deriva daqui
    default: int
    descricao: str      # uma linha, em português, para o modelo ler

@dataclass(frozen=True)
class EntradaCatalogo:
    nome: str                       # "L2"
    cost_class: CostClass
    resumo: str                     # reaproveita o de `describe()`
    parametros: tuple[ParametroSpec, ...]
    construir: Callable[..., Resolver]
```

`CATALOGO: dict[str, EntradaCatalogo]` com as cinco entradas do §0.1.

### 3.1 A propriedade que a tabela carrega

O `enum` de nomes no schema da ferramenta e o construtor usado pela validação
saem **da mesma estrutura**. Um resolver que o grill consegue propor é, por
construção, um resolver que o motor consegue rodar. Não existe receita gerada
inexecutável — não porque alguém valida, mas porque não há de onde vir.

Duas listas paralelas (uma no schema, outra no construtor) seriam exatamente o
join frágil que P3.2 já custou uma correção.

### 3.2 `ParametroSpec` descreve, não valida

`ParametroSpec` **não** carrega faixa (mínimo, máximo). As restrições já vivem
nos resolvers: `ToleranceMatcher.__post_init__` rejeita `max_cents` negativo;
`GroupingMatcher.__post_init__` rejeita grupo menor que 2 e teto de candidatos
menor que o tamanho do grupo. Duplicar as faixas aqui criaria duas fontes de
verdade que divergiriam na primeira mudança.

Ver §5.

### 3.3 A entrada `agente` e o cliente

`construir` da entrada `agente` recebe o `LLMClient` como argumento. Mesma
tabela, um único parâmetro, e — **como implementado** — nenhum chamador que
passe um cliente de verdade: tanto a API quanto a CLI constroem com o
`ClienteAusente` default (§7.3). Para conferir: `grep -rn "cliente=" src/` dá
dois hits, e **nenhum dos dois é um chamador passando cliente** — um é o
repasse interno de `receita.py` para `entrada.construir(...)`, o outro é um
comentário em `grill/cli.py`. O default em si é `if cliente is None:` em
`receita.py`, que não casa com esse grep.

**Correção de uma afirmação anterior deste spec.** Este parágrafo dizia "a CLI
passa um cliente real". É falso. A CLI gasta dinheiro na *entrevista* — ali o
`Entrevistador` fala com `ClienteAssinatura` —, mas o benchmark que ela roda no
fim não executa o resolver pago: `_medir` remove os resolvers de classe
`AGENTE` da cascata medida e imprime uma linha dizendo que eles não foram
consultados. A versão anterior de `_medir` deixava o agente na cascata com o
default inerte, e o resultado era uma linha `agente 0,0%` — que se lê como "o
agente tentou e não achou nada" quando a verdade era "o agente nunca foi
chamado". Número sem dizer sobre o que foi medido é precisamente o que o §8.2
proíbe.

**O que precisaria mudar para um dia passar um cliente de verdade.** Três
coisas, nenhuma delas de uma linha: (a) a CLI teria que construir o
`ToolContext(bank, ledger)` do dataset medido e passar `cliente=` e `context=`
a `construir` — o contexto vazio default não acha nada, então o cliente
sozinho não bastaria; (b) precisaria de uma flag explícita de consentimento
(algo como `--rodar-agente`), porque o custo é POR DIVERGÊNCIA e não é decisão
de quem imprime um percentual; e (c) o teto de gasto da execução inteira
(`budget_total_microcents`) teria que ser mostrado ao parceiro ANTES de rodar,
junto do número de divergências que sobraram para o agente. Enquanto nada
disso existir, o honesto é não medir e dizer que não mediu.

O cliente **não** é um `ParametroSpec`: `parametros` é o que o modelo pode
propor e o que a receita grava; o cliente é injetado por quem constrói e nunca
atravessa o disco. Confundir os dois poria um objeto não serializável na
receita.

### 3.4 O agente é ligado aos dados na construção

`Investigator` exige `context: ToolContext(bank, ledger)` — as ferramentas
dele buscam no razão inteiro, não só na divergência. E `__post_init__` chama
`Cost.zero().microcents(self.client.model)`, logo exige um modelo
**precificado** já ao construir. É por isso que `default_definition()` nunca
teve agente.

Portanto a assinatura é:

```python
construir(
    receita: Receita,
    *,
    fila: Fila | None = None,        # default: Fila.vazia()
    cliente: LLMClient | None = None, # default: ClienteAusente()
    context: ToolContext | None = None, # default: ToolContext([], [])
) -> WorkflowDefinition
```

Os três defaults são **inertes**: fila vazia não resolve nada, `ClienteAusente`
levanta ao ser chamado, contexto vazio não acha nada.

### 3.5 Ninguém passa cliente nem contexto reais — nem a API, nem a CLI

Consequência que fortalece o §7: como `POST /runs` responde 409 antes de
`reconcile` para qualquer cascata com classe `AGENTE`, **nenhum workflow com
agente chega a executar por um endpoint** — então a API pode sempre construir
com os defaults inertes. Não há caminho em que um endpoint precise de um
agente funcional, e portanto não existe código que o construa.

E a CLI **também não passa**, embora pudesse. A frase original aqui era "só a
CLI passa cliente e contexto de verdade"; ela descrevia uma intenção que
nenhuma linha deste repositório exerce. `_medir` constrói com os defaults
inertes e, desde a rodada de correção, **exclui** da medição os resolvers de
classe `AGENTE` em vez de deixá-los rodar contra `ClienteAusente` e reportar
0%. Ver o §3.3 para o que precisaria mudar para isso deixar de ser verdade.

Consequência: os defaults inertes não são só a rede de segurança da API — são
o caminho único de `construir` em todo o código de produção. Um cliente de
verdade só entra por `Entrevistador.client`, na conversa, nunca na cascata.

---

## 4. As três ferramentas

`grill/ferramentas.py`. Todo turno do modelo termina em **exatamente uma**.

```
perguntar(texto: str)
propor_workflow(nome, justificativa, resolvers[])
fora_do_catalogo(motivo, o_que_faltaria)
```

### 4.1 Por que `perguntar` é ferramenta, e não texto livre

Se a pergunta fosse texto solto, "isto é uma pergunta ou o modelo pensando
alto?" viraria heurística, e um turno em que ele apenas comenta travaria o
laço esperando resposta a nada. Como ferramenta, **o fim da entrevista é
evento tipado**, não inferência sobre prosa.

### 4.2 `propor_workflow`

```json
{
  "nome":          "string",
  "justificativa": "string",
  "resolvers": [
    {"nome": "<enum do catálogo>", "parametros": {"<chave>": <int>}}
  ]
}
```

**O modelo não propõe o `id`.** O id do workflow vem do `--id` da CLI, que é
validado contra colisão **antes** do primeiro turno (§9.3) e nomeia também o
arquivo de recusa (§4.3). Deixar o modelo propor um id criaria duas fontes de
verdade para a mesma chave, e a do modelo só seria conhecida no fim — tarde
demais para recusar sem desperdiçar a conversa do parceiro. `nome` é rótulo
legível ("Conciliação Acme"), não chave.

`resolvers` tem `minItems: 1`. O `enum` é gerado de `CATALOGO.keys()`.
`parametros` é objeto livre no schema e validado depois (§5) — schema JSON não
expressa "as chaves permitidas dependem do valor de `nome`" sem `oneOf`
combinatório, e a validação por construção cobre isso melhor.

### 4.3 `fora_do_catalogo`

`motivo` explica ao parceiro por que o caso não cabe. `o_que_faltaria` é a
semente de backlog: qual resolver precisaria existir.

Gravado em `data/grill/recusas/<id>.json`, usando o `--id` da CLI. É desfecho
**legítimo** — sai com código 0, não é erro. Toda recusa é uma linha de
roadmap escrita pela demanda, não por nós.

---

## 5. A validação é a construção

Validar uma proposta é **tentar construí-la**.

```python
definicao = construir(receita, cliente=...)   # ou levanta ValueError
```

Se retorna, a receita roda. Se levanta, a mensagem do `ValueError` volta ao
modelo verbatim como `tool_result` e ele corrige. As restrições ficam num
lugar só — o resolver — e o catálogo fica com o papel de apenas descrever.

### 5.1 O que `construir` rejeita além do que os resolvers já rejeitam

**Nome fora do catálogo.** O `enum` do schema já restringe, mas modelos violam
`enum`. Cinto e suspensório.

**Chave de parâmetro desconhecida.** `{"tolerancia": 10}` em vez de
`{"max_cents": 10}` seria ignorado silenciosamente por um construtor
permissivo, e o parceiro receberia a tolerância default achando que pediu 10.

**Resolver repetido na cascata.** Dois `L2` no mesmo stage: o segundo roda
sobre o pool que o primeiro esvaziou e casa zero. Não é erro para o Python —
é um no-op silencioso que aparece na tela como uma camada de 0%.

O `id` **não** entra aqui: ele não vem do modelo. A colisão é checada pela CLI
antes do primeiro turno (§9.3) e pelo registro na gravação (§6.2).

### 5.2 Retry com teto

Mesma disciplina do `max_tentativas_formato` do investigador: default 2.
Esgotou, a entrevista **falha alto** e nada é gravado. Receita meia-boca em
disco é pior que entrevista perdida.

---

## 6. A receita em disco

### 6.1 Forma

```python
@dataclass(frozen=True)
class ResolverReceita:
    nome: str
    parametros: dict[str, int]

@dataclass(frozen=True)
class Receita:
    id: str
    nome: str
    justificativa: str
    gerado_em: datetime
    resolvers: tuple[ResolverReceita, ...]
```

Serializa para `data/workflows/<id>.json`. Round-trip obrigatório por teste.

**A ordem é gravada verbatim** — o que o modelo propôs. `Stage.ordered()`
impõe a ordem entre classes de custo em tempo de execução, exatamente como já
faz com a definição embutida: o modelo pode propor `[agente, L1]` e o motor
roda `[L1, agente]`. Nenhuma regra nova. O canvas desenha `ordered()`, então o
que se vê é o que roda.

### 6.2 Sobrescrita é recusada

A fila de revisão é chaveada por `(workflow, dataset)`. Sobrescrever a receita
`acme` mudaria, por baixo, o significado das decisões humanas já gravadas
sob esse workflow — o mesmo defeito de escopo que a fatia anterior corrigiu ao
introduzir `dataset_id`.

O registro recusa e diz qual id já existe. `conciliacao` é reservado.

### 6.3 O `.gitignore` vira allowlist

Nada está versionado sob `data/` hoje (`git ls-files data/` é vazio). Então:

```gitignore
# Dados: nada sob data/ é versionado por padrão.
# Para versionar algo novo, adicione uma exceção explícita AQUI e diga por quê.
data/*
```

Remendo por diretório (`data/workflows/`, `data/grill/`) resolveria hoje e
falharia na próxima fatia que escrevesse um tipo de arquivo novo. Foi
exatamente assim que chegamos aqui: `*.jsonl` cobria a fila por acidente do
formato.

O comentário existente sobre dado sintético versionado descreve uma intenção
que o repositório nunca exerceu; ele é substituído, não mantido junto.

Consequência operacional: `data/` não existe num clone novo. Todo código que
escreve ali cria os diretórios pais — o registro de receitas e o de recusas,
com `mkdir(parents=True, exist_ok=True)` no momento da gravação, como
`Fila._append` já faz. (`caminho_da_fila` apenas monta o caminho; quem cria o
diretório é quem escreve.)

---

## 7. Registro, API e o invariante de dinheiro

### 7.1 `_WORKFLOWS` vira função

Hoje é dict literal com uma entrada. Passa a ser uma função que devolve a
embutida mais uma fábrica por receita em disco.

### 7.2 A armadilha do nome `fila`

`_construir_definicao` decide repassar a fila **olhando o nome literal do
parâmetro**. Uma closure que declare `q` em vez de `fila` deixa tudo verde e
faz o workflow gerado servir fila vazia em silêncio.

A fábrica de receita declara `fila` explicitamente, e um teste trava o nome —
espelhando `test_a_fabrica_padrao_declara_o_parametro_fila`.

### 7.3 `ClienteAusente`: o objeto existe, a chamada explode

O parceiro pode legitimamente precisar do agente, e o canvas precisa
desenhá-lo. Mas nenhum endpoint pode gastar.

A API constrói a entrada `agente` com um `LLMClient` sentinela cujo
`complete()` levanta. Consequências:

- O objeto **existe** — logo é desenhável e serializável, e a rota continua
  servindo *o mesmo objeto que o motor executa*. O invariante do
  [`definition.py`](../../../src/orchestrator/workflow/definition.py) — nunca
  uma descrição paralela ao motor — fica intacto.
- Nenhuma chamada chega ao modelo: `complete()` levanta antes de qualquer rede.
  A garantia de dinheiro é essa, e ela se sustenta.

**Correção de uma afirmação anterior deste spec.** Este parágrafo dizia que a
tentativa "explode alto, não silenciosamente". É **falso**, e foi medido na
Task 8: com a guarda do 409 removida, `POST /runs` responde **200 com 14
chamadas** a `ClienteAusente.complete` — todas engolidas pelo `except Exception`
de `Investigator._uma`, que as converte em abstenções. Nenhum centavo é gasto,
mas nada aparece.

Uma ressalva à ressalva: o erro engolido **não some**. A mensagem do
`RuntimeError` entra no `TraceEvent` e na explicação de cada proposta abstida,
então quem abre o detalhe de uma execução consegue ver que a tranca disparou.
O que falta é sinal no nível de cima — o status da resposta continua 200.

Consequência para o desenho: a tranca garante **não gastar**, e avisa apenas
quem for olhar o detalhe. Quem torna o caso visível é o 409, e é por isso que as duas metades
existem — não como redundância, mas porque cada uma cobre o que a outra não
cobre. É o mesmo `except Exception` amplo que, na fatia 2, tornou vazio um teste
de dinheiro inteiro.

`ClienteAusente.model` precisa ser um modelo **da tabela de preços**:
`Investigator.__post_init__` chama `Cost.zero().microcents(self.client.model)`
e um nome inventado faria a construção levantar — o que impediria até de
desenhar. O sentinela levanta em `complete()`, nunca em `model`.

### 7.4 O 409

`POST /runs` num workflow cuja cascata contém classe `AGENTE` responde **409**
antes de `reconcile`, com mensagem dizendo para rodar pela CLI.

O 409 é a porta educada; `ClienteAusente` é a tranca. As duas, porque uma
mensagem clara não é garantia e uma garantia não é mensagem clara.

### 7.5 Rota nova

`GET /api/workflows` → lista de `{id, nome, classes, gerado_em, executavel}`.
`executavel` é falso quando a cascata tem classe `AGENTE`. O canvas usa isso
para desabilitar o botão em vez de deixar o usuário colher um 409.

---

## 8. O fluxo ponta a ponta

### 8.1 A CLI

```
$ orchestrator-grill --id acme --descricao-arquivo caso-acme.md

  modelo → perguntar("Vocês lançam o pagamento na data do caixa ou na competência?")
  você   → caixa, mas o banco às vezes atrasa 2-3 dias
  modelo → perguntar("Um pagamento seu pode cobrir várias notas do mesmo fornecedor?")
  você   → sim, consolidamos por fornecedor no fim do mês
  modelo → propor_workflow(id="acme", resolvers=[L1, L2(10,5), L3(4,5), revisor])

  ✓ construída e validada
  ✓ data/workflows/acme.json
  ✓ benchmark (semente 1, n=500): 87,1% — L1 62% · L2 21% · L3 4% · lacuna 12,9%
    Este número é do NOSSO benchmark sintético, não dos seus dados.
  → http://localhost:8000/?workflow=acme
```

Flags: `--id` (obrigatório), `--descricao` ou `--descricao-arquivo` (um dos
dois obrigatório), `--seed 1`, `--n 500`, `--taxa-divergencia 0.15` — mesmos
defaults de `orchestrator`.

### 8.2 A ressalva impressa é requisito, não rodapé

Mostrar "87,1%" a um parceiro sem dizer sobre o que foi medido é vender número
que não é dele. O grill não vê dado nenhum: a configuração sai inteira da
conversa, e o percentual é do benchmark sintético.

A linha é testada. Um teste assere que a saída da CLI contém a ressalva sempre
que contém um percentual.

### 8.3 Injeção da resposta humana

`Entrevistador.entrevistar(descricao, responder: Callable[[str], str])`. A CLI
passa `input`; os testes passam uma lista de respostas prontas. Nenhum teste
toca stdin.

### 8.4 Um stage só

O grill propõe um stage. Ordenação que a classe de custo não expressa exigiria
múltiplos stages — §2.2.

---

## 9. Limites, erros e custo

| Situação | Comportamento |
|---|---|
| Teto de turnos estourado sem saída | Falha alto. Nada gravado. Imprime a transcrição — a conversa do parceiro não se perde por erro nosso |
| Proposta inválida | Erro volta como `tool_result`; teto de tentativas; esgotou, falha alto |
| `fora_do_catalogo` | Grava a recusa, sai com 0 |
| `id` colidindo ou reservado | Recusa antes da entrevista começar, não depois |
| Ctrl+C no meio | Nada gravado |
| Teto de gasto em µ¢ | Mesma disciplina do investigador: acumula por turno, para ao estourar |

### 9.1 O teto de turnos

Default 12 — cabe cerca de onze perguntas mais a proposta. É **teto, não
meta**: uma entrevista que resolve em três turnos é melhor que uma que usa os
doze.

### 9.2 O orçamento default é derivado, não chutado

O investigador não escolheu `4_000_000 µ¢`; derivou de `len(SYSTEM)`,
`len(json.dumps(TOOL_SCHEMAS))`, uma saída realista por turno e a tabela de
preços, e pinou a conta com um teste.

Este spec **não fixa um número**. Ele exige o mesmo método: a implementação
calcula o default a partir do system prompt e dos schemas reais desta fatia, e
um teste reproduz a conta. Um número escrito aqui seria chute com aparência de
medida — e o histórico deste projeto tem um defeito crítico causado
exatamente por custo entrando onde não foi medido.

### 9.3 `--id` é validado antes da entrevista

Colisão descoberta depois de doze turnos desperdiça a conversa do parceiro.

---

## 10. Verificação

O laço inteiro roda com `FakeLLMClient`: sem rede, sem centavo.

### 10.1 O que precisa ser provado

1. **Entrevista feliz**: pergunta, pergunta, propõe → receita correta em disco,
   e a definição construída tem os resolvers e parâmetros propostos.
2. **Proposta inválida volta ao modelo com a mensagem do `__post_init__`**, e
   ele corrige. A asserção é sobre `client.chamadas` — o que o modelo
   **recebeu** — não sobre o resultado final. Asserção só no resultado passaria
   com um laço que ignorou o erro e deu sorte no turno seguinte.
3. **Retry esgotado → levanta, nada em disco.**
4. **Turnos estourados → levanta, nada em disco, transcrição impressa.**
5. **`fora_do_catalogo` → arquivo de recusa, nenhuma receita, código 0.**
6. **Propriedade sobre o catálogo inteiro**: todo nome no `enum` constrói com
   os defaults. Não é exemplo, é `for` sobre `CATALOGO` — é isto que garante
   "receita gerada sempre executa".
7. **Resolver repetido rejeitado.**
8. **Chave de parâmetro desconhecida rejeitada** (não ignorada em silêncio).
9. **`id` colidindo recusado**, e recusado **antes** do primeiro turno.
10. **Receita com `agente`: `POST /runs` responde 409 E `ClienteAusente.complete`
    nunca foi chamado.** As duas metades — a porta e a tranca. Só o 409
    passaria com a tranca quebrada.
11. **Fábrica de receita declara `fila` pelo nome.**
12. **Round-trip** `Receita → json → Receita`.
13. **A ressalva do §8.2 aparece sempre que a saída tem percentual.**
14. **Golden byte-idêntico e `conciliacao` intocada.**

### 10.2 Disciplina de mutação

Vale como nas fatias anteriores: cada teste acima tem que ser mostrado
**falhando** com o código quebrado de propósito. Um teste que passa com a
implementação errada não é teste, e esta é a terceira fatia seguida em que
essa exigência encontrou defeito real.

### 10.3 O que esta fatia não prova

Que o grill pergunta bem. Ver §2.3.

---

## 11. Alternativas rejeitadas

**Ficha fixa de campos, modelo só conduzindo.** Recomendada e recusada pelo
dono; ver §2.3. Teria dado testabilidade da entrevista em troca de rigidez.

**Entrevistador como `Resolver`.** A estética do repositório puxa para isso —
tudo é resolver — mas seria abuso: um resolver consome pool e produz vínculos;
o grill não toca em pool e produz uma **definição**. `resolve(work)` receberia
um `WorkSet` que ignora. É subsistema irmão da cascata, não degrau dela.

**Texto livre como pergunta.** Ver §4.1.

**Faixas de parâmetro no catálogo.** Ver §3.2.

**Grill na web nesta fatia.** Quebraria o invariante "nenhum endpoint gasta
dinheiro", que hoje é estrutural e testado, ou exigiria um segundo app antes
de sabermos se a entrevista presta. CLI primeiro; a web tem gatilho no §2.2.

**Receita citando resolver a construir (`a_construir`).** Transformaria o
grill em máquina de descoberta de produto, mas a receita deixaria de ser
sempre executável e o canvas teria que desenhar caixa fantasma. O caminho
`fora_do_catalogo` captura a mesma informação sem custar a garantia.

**Sobrescrever receita existente.** Ver §6.2.

---

## 12. Riscos

**O adaptador de assinatura pode não existir.** `ClaudeSDKClient` precisa
aceitar uma conversa multi-turno com histórico. Se não aceitar, o adaptador
cai para chave de API. Mitigação: o entrevistador fala com `LLMClient` e nada
mais, então a troca é de **uma** classe e nenhum outro arquivo muda. O
adaptador é a última tarefa do plano, de propósito: tudo o mais fica provado
antes de tocar em SDK.

**A entrevista pode ser ruim e nada avisa.** §2.3. Risco aceito com registro.

**O modelo pode propor uma cascata pior que a default.** Nada nesta fatia
compara a proposta com a linha de base. O número do benchmark aparece, mas
quem julga é a pessoa. Gatilho de otimização iterativa no §2.2.

**`data/*` no `.gitignore` pode esconder algo que se queira versionar depois.**
Aceito: a exceção explícita é uma linha, e o comentário obriga a justificar.

---

## 13. Glossário

**Grill** — a entrevista. O nome vem do uso do dono do projeto.

**Catálogo** — a tabela de resolvers proponíveis. Fonte única do schema da
ferramenta e do construtor.

**Receita** — a forma serializável de um workflow: quais resolvers, quais
parâmetros. É **entrada**, não descrição servida: o loader constrói o objeto
de verdade e é esse objeto que a API serializa.

**`ClienteAusente`** — `LLMClient` sentinela que levanta ao ser chamado.
Permite construir e desenhar um resolver pago sem que exista caminho de
execução paga atrás de um endpoint.

**Recusa** — desfecho legítimo da entrevista em que o caso não cabe no
catálogo. Vira backlog de resolver.
