# O chat compõe a automação inteira

> Tese: **o chat fala o formato antigo.** O canvas e a API compõem `Composicao`
> — etapas, agente declarado na hora, tripulação, tarefa, entrega, rondas. O
> entrevistador ainda propõe `Receita`: uma fileira de nomes prontos, num
> degrau só. Quem chega pelo chat não alcança o produto que existe.

---

## 0. O pedido, e onde o chat parou

Pedido: "vamos fazer o chat funcionar para ele sugerir as automações com os
blocos disponíveis".

O chat funciona — ele conversa, propõe, grava e pousa no canvas. O que ele não
faz é **usar os blocos disponíveis**. O system prompt diz, textualmente:

> A cascata tem um estágio.

E a ferramenta que encerra a entrevista aceita `resolvers: [{nome, parametros}]`,
onde `nome` é um `enum` dos nomes do catálogo. Disso saem três limites duros:

1. **Agente só pronto.** Os três do catálogo (`investigador`, `triador`,
   `buscador`). Declarar um agente novo — prompt, vocabulário, ferramentas — é
   o que `AgenteDeclarado` destravou e o chat não alcança.
2. **Um degrau.** Nada de "o escritor produz, o revisor consome".
3. **Sem tripulação, sem tarefa, sem `entrega`, sem `Loop`.**

Medido lendo: `grill/ferramentas.py::esquemas`, `grill/prompt.py`,
`App.tsx::aceitarProposta` (que pousa tudo em `etapa: 0`).

---

## 1. O que NÃO precisa ser reinventado

Três peças do caminho de hoje sobrevivem inteiras, e é por isso que esta fatia
é menor do que parece.

**O laço que valida construindo.** `entrevistador.py:214` chama
`construir(receita)` e, se levantar, devolve o erro ao modelo como
`tool_result` com `is_error: True`, para ele se corrigir no turno seguinte.
Trocar por `construir_composicao` herda esse mecanismo — e herda com ele todas
as recusas que já têm texto escrito para ser lido: prompt que não interpola,
`abstem_com` colidindo com tipo, `produz == kind`, bloco repetido, parâmetro
desconhecido.

**As três guardas de custo.** Teto por entrevista, custo em cada desfecho,
recusa legível sem chave. Estão em `api/entrevista.py` e não mudam.

**A gravação com tranca.** `_gravar_receita_do_chat` recusa id que já exista em
`registry()` — a terceira porta de escrita, com a mesma leitura das outras
duas. Vira `_gravar_composicao_do_chat`, mesma frase, mesma recusa.

---

## 2. Abordagens consideradas

### A. O entrevistador passa a produzir `Composicao` (ESCOLHIDA)

Um formato só. O chat fala o que o produto fala.

### B. Segunda ferramenta ao lado da atual

`propor_workflow` (Receita, um degrau) e `propor_automacao` (Composicao),
convivendo. Rejeitada: são duas portas para a mesma decisão, e o modelo escolhe
a mais fácil. **Custo de estar errado:** o recurso novo fica sem uso e ninguém
descobre, porque as duas portas devolvem 200.

### C. Um entrevistador novo, só para composição

Rejeitada pelo motivo que `api/entrevista.py` já escreve sobre si mesmo: *"Duas
cópias de um laço que gasta dinheiro divergiriam, e a que diverge é sempre a
que ninguém testa."*

---

## 3. A ferramenta: de `resolvers` para `etapas`

```
propor_workflow(nome, justificativa, etapas[], entrega[], max_rondas)
  etapas[]  = {nome, blocos[]}
  blocos[]  = {tipo, regra?, agente?, tarefa?, crew?}
```

### 3.1 Por que o bloco NÃO é uma união discriminada aqui

`api/schemas.py` usa `Field(discriminator="tipo")` e o comentário de lá explica
por quê: campos opcionais aceitariam cruzamentos que não significam nada.
**Aqui isso não é expressável**, e o motivo é medido: `_PALAVRAS_DE_SCHEMA` —
a lista branca conferida contra a Messages API — é

```
{type, description, properties, required, additionalProperties, items, enum}
```

Sem `oneOf`, sem `anyOf`. Usá-los seria apostar a requisição inteira: a API
recusa a chamada por uma ferramenta malformada, e *"o erro só aparece gastando
dinheiro"* (o `"minimum": 1` de 2026-09-16 é o precedente, e nenhum dos 620
testes de então viu).

**A forma que cabe:** `tipo` é o `enum` que manda, e cada tipo tem seu próprio
OBJETO — `regra`, `agente`, `tarefa`, `crew` —, todos opcionais. Isso é melhor
que campos soltos: um objeto `agente` tem `tipos`/`abstem_com`, um objeto
`tarefa` tem `produz`, e nenhum dos dois oferece o campo do outro. O que sobra
para a borda conferir é UMA coisa, não a matriz de cruzamentos: *"`tipo` diz
`tarefa` e o objeto `tarefa` não veio"*.

Essa recusa volta ao modelo como `is_error`, pelo caminho que já existe.

### 3.2 O catálogo no texto da ferramenta

`_catalogo_em_texto` continua listando as regras com seus parâmetros, e ganha
duas frases: como declarar um agente e como declarar uma tarefa.

Também perde uma mentira que está em DOIS lugares: `_catalogo_em_texto` imprime
`{p.nome} (int, default ...)` para todo parâmetro, e a descrição de
`propor_workflow` fecha com *"Todo parâmetro é inteiro"*. `ValorDeParametro` é
`int | str | tuple[str, ...]` desde que as regras genéricas passaram a receber
NOME DE CAMPO — então o modelo está sendo informado de que não pode dizer
`campo: "documento"` num bloco que exige exatamente isso.

---

## 4. Os campos do item: a pergunta que não pode faltar

Um agente ou tarefa declarado tem prompt que interpola campos do payload
(`"{titulo}"`). `AgenteDeclarado` recusa prompt que não interpola nada — mas
nada, em composição, sabe se `titulo` existe: `_campos` só encontra o payload
na EXECUÇÃO.

**A regra entra no system prompt:** antes de declarar agente ou tarefa,
perguntar quais campos cada item tem, e interpolar só esses. É a disciplina que
o prompt já impõe para parâmetro — *"NUNCA invente um valor que não ouviu"* —
estendida a campo, que é onde ela passou a custar caro: parâmetro inventado dá
um número errado; campo inventado dá uma execução paga que morre no primeiro
item.

**Alternativa rejeitada: um campo `campos_do_item` na declaração, conferido
pela borda.** Pareceria garantia e seria teatro — o modelo que inventa o prompt
inventa a lista junto, e a conferência passaria vacuamente. O que de fato pega
invenção é `_prompt_do_item`, na execução, e ele já falha ALTO nomeando o campo
que falta e listando os disponíveis. A segunda linha de defesa real é humana: a
declaração inteira, prompt incluído, aparece no nó do canvas antes de qualquer
run.

---

## 5. A borda: WS, gravação e canvas

- `Proposta.receita` vira `Proposta.composicao`; a mensagem `{"tipo":
  "proposta"}` do WebSocket passa a carregar `composicao` (o `para_json` de
  `authoring`).
- `_gravar_receita_do_chat` → `_gravar_composicao_do_chat`, com `gravar` de
  `authoring/composicao.py` e a MESMA recusa por id já existente.
- `App.tsx::aceitarProposta` pousa **por etapa** (hoje força `etapa: 0`) e
  passa a entender os tipos `tarefa` e `crew`. `Chat.tsx` mostra o resumo pelas
  etapas em vez de `receita.resolvers`.

---

## 6. O `grill` CLI: uma saída só

`grill/cli.py` grava `Receita` (`gravar_receita`) e mede a proposta com
`construir`. Com o entrevistador produzindo composição, ele passa a gravar
composição e a medir com `construir_composicao`.

**`Receita` NÃO é depreciada**, e isso é decisão registrada: os arquivos em
`data/receitas/` continuam carregando por `_de_receita`, e os testes dela
continuam valendo. O que deixa de existir é a segunda SAÍDA do entrevistador —
um produtor com dois formatos é o join frágil de sempre.

---

## 7. O que este plano NÃO faz

- **O nó de `tarefa` no canvas.** Fatia curta ANTES desta (paleta, editor,
  `tsc`, bundle commitado). Sem ela, o chat proporia um bloco que a tela não
  desenha.
- **Ler os campos de uma fonte conectada.** Decidido: o chat pergunta. A fonte
  é escolhida na hora de EXECUTAR, depois da conversa — ligar as duas é outra
  fatia, com outra pergunta.
- **Sugerir várias automações para comparar.** A entrevista propõe UMA. Duas ou
  três alternativas com custo lado a lado é um produto diferente, e cabe
  discutir depois de esta existir.
- **Decisão humana genérica.** Continua sendo o degrau HUMANO genérico, que não
  existe.

---

## 8. Riscos

| risco | mitigação |
|---|---|
| O modelo declara agente com prompt citando campo que não existe | Regra no system prompt; o nó do canvas mostra o prompt antes do run; `_prompt_do_item` falha nomeando o campo |
| A ferramenta fica grande demais e o modelo erra a forma | `is_error` devolve a recusa e ele corrige — é o laço de hoje, com `max_tentativas_formato` já existente |
| Uma palavra de JSON Schema nova derruba a requisição inteira | O schema fica nas sete palavras da lista branca; qualquer acréscimo exige medir contra a API e registrar a evidência |
| A entrevista fica mais cara (mais turnos, schema maior) | O teto por entrevista já existe e é por conexão; o custo volta em cada desfecho |

---

## 9. Critério de aceite

1. Uma entrevista com `FakeLLMClient` que pede duas etapas — um agente
   declarado na primeira, uma tarefa na segunda — produz uma `Composicao` que
   `construir_composicao` aceita, e o WS a entrega no `{"tipo": "proposta"}`.
2. Uma proposta inválida (prompt que não interpola) volta ao modelo como
   `is_error` com o texto do domínio, e a entrevista continua.
3. `pytest` verde nas duas instalações; `npx tsc --noEmit` limpo; bundle de
   `web/` commitado batendo com a fonte.
4. `orchestrator --seed 1 --n 500` continua em `85.3%`, zero falso positivo,
   zero falso negativo.
