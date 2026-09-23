# O modelo por bloco, de verdade: a chamada certa e o preço certo

> Tese: **a classe de custo diz que um bloco é caro; o modelo diz quanto.** A
> cascata já escolhe regra antes de agente. Falta escolher *qual* agente — e,
> escolhido, cobrar o preço dele.

---

## 0. O defeito, medido

`a651b05` expôs `model` por bloco: no schema da API, no `enum` da ferramenta do
chat e num `<select>` no painel. **Ele não faz nada.**

`AgentSpec.model` aparece em UM lugar em todo o `src/`:

```python
summary=f"agente {self.spec.model}"     # agent.py:174 (e tarefa.py:184)
```

Quem decide o modelo da chamada é `AnthropicClient.complete`, que usa
`self.model` — o modelo do CLIENTE, que a borda constrói como
`AnthropicClient()`, ou seja `claude-opus-5`. E o custo do run é convertido com
`modelo = MODELO_INERTE`, também Opus, para todas as linhas.

**Medido contra o Barrier**, duas vezes, com a mesma composição:

| | modelo declarado | modelo chamado | custo reportado | real |
|---|---|---|---|---|
| run 1 | (nenhum) | opus | 3.863.500 µ¢ | US$ 0,039 |
| run 2 | `claude-haiku-4-5` | **opus** | 4.494.000 µ¢ | US$ 0,045 |

O segundo run existia para provar a economia de 5× e provou o contrário: o
campo é decorativo, e a tela, o chat e o prompt convencem quem monta de que a
escolha existe. **Um recurso que promete e não cumpre é pior que a ausência
dele** — a ausência ninguém configura.

---

## 1. Duas metades independentes

**A chamada.** `LLMClient` carrega o modelo como propriedade (`client.model`), e
`complete(system, messages, tools)` não o recebe. Existem **18 implementações**
de `complete` no repositório, 12 delas em testes.

**O preço.** `Run.cost_by_resolver` é `dict[str, Cost]` — tokens, sem preço, por
desenho (*"o preço depende do modelo, e o mesmo consumo custa diferente em cada
um"*). Quem converte é a borda, com UM modelo para a tabela inteira.

As duas metades se resolvem separadamente e nenhuma depende da outra: a
primeira faz a chamada certa acontecer; a segunda faz o número dizer a verdade.

---

## 2. Abordagens

### A. A chamada

**A1 — um cliente por modelo, com teto compartilhado (ESCOLHIDA).** A borda
constrói um `ClienteComTeto` por modelo distinto da cascata, e todos dividem um
`Orcamento`: o objeto que acumula o gasto em µ¢ e conta as recusas. Cada
embrulho precifica os próprios tokens com o próprio modelo — mais correto que
hoje, onde `ClienteComTeto.model` é copiado do cliente interno e vale para tudo.

`complete` não muda, e é isso que mantém as 18 implementações de pé. Onde havia
um cliente, passa a haver uma função `cliente_para(model) -> LLMClient`; um
`lambda _: fake` reproduz exatamente o comportamento de hoje em todo teste.

**A2 — `complete` ganha `model`.** É o desenho mais honesto: o modelo é
propriedade da CHAMADA, não do cliente, e `AgentSpec.model` passaria a
significar algo por si. Rejeitada nesta fatia pelo custo/benefício: 18
assinaturas mudam, e o livro-caixa por modelo continua sendo necessário do mesmo
jeito. Fica registrada como a evolução natural — no dia em que um provedor
exigir trocar de modelo no meio de uma conversa, ela deixa de ser opcional.

**A3 — o agente constrói o próprio cliente.** Rejeitada: mataria a tranca
(`ClienteAusente`, `ClienteDeValidacao`) e o teto por requisição, que só existem
porque o cliente vem de fora. **Custo de estar errado:** compor um workflow
passaria a poder gastar dinheiro, e é exatamente isso que `/api/composicoes`
promete que não acontece.

### B. O preço

**B1 — `ResolverDescription.model` (ESCOLHIDA).** O resolver declara com que
modelo roda: `Agent` e `Tarefa` devolvem `spec.model`, regra devolve vazio. A
borda converte o `Cost` de cada linha com o modelo daquela linha. É o canal que
`consome`, `produz` e `payloads` já usam, pela mesma razão declarada lá: quem
precisa da informação é a borda, e declarar no resolver evita a lista paralela
que apodrece.

**B2 — `Run.model_by_resolver`, preenchido pelo motor.** Rejeitada: o motor não
conhece modelo nenhum e teria de ler `describe()` para gravar — B1 com um estado
a mais para dessincronizar.

**B3 — `Cost` carregar o modelo.** Rejeitada pelo docstring do próprio tipo:
*"Tokens, não dinheiro"*. Um `Cost` com preço embutido não poderia ser somado
entre modelos, que é o que a linha do total faz.

---

## 3. `Orcamento`: o teto que vários clientes dividem

Novo em `agent/teto.py`, ao lado de `ClienteComTeto`:

- `registrar(cost: Cost, model: str)` — soma em µ¢, no preço daquele modelo.
- `gasto_microcents()` — o acumulado.
- `recusas` — quantas chamadas o teto barrou.
- `pode_gastar()` — a conferência que hoje mora dentro do `complete`.

`ClienteComTeto` passa a receber um `Orcamento` opcional; sem ele, cria o seu —
o que mantém `ClienteComTeto(fake, teto_microcents=…)` funcionando em todos os
testes de hoje, verbatim.

**Por que o gasto é somado em µ¢ e não em tokens:** com dois modelos, tokens não
somam — 1.000 tokens de Haiku e 1.000 de Opus não são 2.000 de coisa nenhuma. O
teto é sobre dinheiro, então a moeda é µ¢. É a mesma razão pela qual `Cost` não
carrega preço: cada lado guarda a unidade em que ele é verdade.

**O teto continua sendo por REQUISIÇÃO**, conferido ANTES de cada chamada, e a
última pode ultrapassá-lo por um turno — nada disso muda, e o docstring de
`teto.py` continua valendo palavra por palavra.

---

## 4. A borda: de um cliente para uma fábrica

`WorkflowContext.cliente: LLMClient | None` vira
`cliente_para: Callable[[str], LLMClient] | None`, onde o argumento é o modelo
declarado pelo bloco (vazio = "o padrão do servidor").

Os três construtores que hoje recebem `cliente` — `construir_composicao`,
`grill.receita.construir` e, por dentro, `construir_agente`/`construir_tarefa`/
`_tripulacao` — passam a receber a fábrica e a chamá-la com `decl.model`.

**O default continua sendo a TRANCA.** `None` cai em `ClienteDeValidacao` /
`ClienteAusente` exatamente como hoje: compor não gasta, e desarmar é ato
explícito de quem executa. O que muda é que agora a tranca também é entregue por
uma fábrica (`lambda _: ClienteAusente()`).

---

## 5. O que a tabela do run passa a dizer

`RunJSON.por_resolver[].microcents` usa o modelo daquela linha; `custo_microcents`
vira a SOMA das linhas. Hoje é `run.custo_total_microcents(MODELO_INERTE)`, um
modelo para tudo.

`Run.custo_total_microcents(model)` **fica**: a CLI e o `eval/` rodam com um
modelo só, e o método continua sendo a resposta certa para eles.

A garantia nova, e é ela que fecha a tese do produto: **um workflow com dois
agentes em modelos diferentes reporta duas linhas com preços diferentes.**

---

## 6. O que esta fatia NÃO faz

- **Trocar de modelo no meio de uma conversa.** É A2, e ninguém precisa hoje.
- **Escolher modelo por ITEM** (barato primeiro, caro no que sobrou dentro do
  mesmo bloco). É uma cascata dentro do bloco, e o produto já tem cascata: são
  dois blocos.
- **Preço de modelo local.** Continua valendo o que a conversa registrou: sem
  preço não há custo, e `0` faria a coluna mentir.

---

## 7. Riscos

| risco | mitigação |
|---|---|
| A fábrica vira um saco de clientes e alguém constrói um pago sem querer | Ela é `Callable[[str], LLMClient]`, não um registro; quem a escreve é a borda, num lugar só (`_cliente_de_execucao`) |
| Dois modelos, dois embrulhos, e o teto deixa de ser um | O `Orcamento` é o único acumulador; o teste que fixa isso roda dois modelos e confere um teto só |
| Cliente sem preço conhecido chega por um caminho novo | `AnthropicClient.__init__` já recusa, e `_modelo()` na borda recusa antes, na composição |

---

## 8. Critério de aceite

1. Um workflow com dois agentes — um `claude-haiku-4-5`, outro `claude-opus-5`
   — faz DUAS chamadas a modelos diferentes (provado por cliente falso que
   registra qual recebeu cada uma) e reporta **duas linhas com preços
   diferentes**.
2. O teto por requisição continua sendo UM: com dois modelos, a soma em µ¢
   respeita o mesmo teto, e `teto_atingido` continua saindo de uma variável só.
3. `pytest` verde nas duas instalações; `ruff` limpo; bundle de `web/` batendo.
4. `orchestrator --seed 1 --n 500` continua em `85.3%`, zero falso positivo,
   zero falso negativo.
5. O caso do Barrier roda em Haiku e a linha do agente custa ~1/5 do que custou
   em Opus — a medição que motivou esta spec, fechada.
