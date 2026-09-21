# Bloco Tarefa: o agente que transforma, montável na tela

> Tese: **a saída de um agente precisa ser trabalho para o próximo.** Hoje ela
> é uma proposta e nada mais — e por isso a cadeia escritor→revisor, que o
> runtime executa desde 2026-09-17, não é montável por quem usa o produto.

---

## 0. O pedido, e a medição que o originou

Pedido: "consegue validar se a partir do workflow que a gente monta ele
consegue de fato rodar os agentes com os blocos que temos?"

A validação rodou pela borda HTTP real — `POST /api/composicoes` seguido de
`POST /api/workflows/{id}/runs`, com `FakeLLMClient` e sem rede. Três lacunas
apareceram. Duas foram fechadas no mesmo dia (`ad54ce0`, `eb90444`). Esta spec
é a terceira, e é a única que exige desenho.

**A medição.** Uma composição de duas etapas — agente `triador` na primeira,
tripulação de dois agentes na segunda — sobre um CSV de 3 issues:

```
chamadas ao modelo: 6   custo: 700.000µ¢   estado: concluido
por_resolver: filtro REGRA matches=1 0µ¢ | triador AGENTE 350.000µ¢ | dupla CREW 350.000µ¢
```

A etapa 2 recebeu **as mesmas issues originais**, não a saída do triador: 4
chamadas sobre os mesmos itens. Os agentes compõem em ordem de CUSTO (a regra
abateu um item antes de qualquer token — a tese funciona), mas não compõem em
ordem de DADO. O segundo eixo do §2 do README não existe entre dois blocos de
modelo.

---

## 1. A auditoria

### 1.1 `Tarefa` existe, roda, e não é componível

`agent/tarefa.py` é o resolver que transforma: devolve `Resolution` +
`produced`, nunca `proposals`. `domains/redacao/workflow.py` o usa em três
degraus ligados por kind (`topico → achados → rascunho → texto_final`), e o
pipeline roda.

Só que ele é **cabeado à mão**: `TarefaSpec` exige duas funções Python.

```python
prompt_de: Callable[[WorkItem], str]
transformar: Callable[[str, str, Cost, list[TraceEvent]], SaidaDaTarefa | None]
```

Um bloco não pode carregar função. `data/composicoes/*.json` é dado, e o canvas
edita dado. Por isso `BlocoAgente` existe e `BlocoTarefa` não: `AgenteDeclarado`
já resolveu esse problema para o `Agent` — `units`, `parse` e `abstain`
**deixaram de ser funções** e viraram `kind`, `prompt`, `tipos` e `abstem_com`.
Falta fazer o mesmo para a `Tarefa`, e o que muda é só quais dados bastam.

### 1.2 A lacuna que a leitura desenterrou

`Tarefa.describe()` devolve `ResolverDescription(name, cost_class, summary)` —
**sem `consome` e sem `produz`**. Em `domains/redacao` isso não aparece porque
o `Stage` declara os dois à mão.

Na via composta, quem deriva o grafo é `construir_composicao`, por
`consome_de(resolvers)` e `produz_de(resolvers)` — as duas leem
`describe()`. Uma `Tarefa` composta entraria com conjuntos VAZIOS, e um
`consome` vazio significa "vejo o pool inteiro". O item produzido cairia na
recusa do kernel ("produziu kind não declarado"), ou pior: passaria e o degrau
seguinte leria o pool errado.

**O sintoma seria o pior conhecido nesta base:** a composição PASSA na tela, e
a execução recusa — sobre uma escolha que a tela tinha acabado de aceitar. É
textualmente o defeito que `produz_de` foi escrita para matar, e ele volta pela
porta de um resolver que não declara nada.

---

## 2. Abordagens consideradas

### A. `BlocoTarefa` como quarto tipo da união discriminada (ESCOLHIDA)

`TarefaDeclarada` nasce ao lado de `AgenteDeclarado`; o JSON ganha
`{"tipo": "tarefa"}`. O discriminador passa a dizer qual **contrato** o bloco
honra: propor ou transformar.

Preço: duas declarações com campos parecidos (`name`, `system`, `kind`,
`prompt`, `ferramentas`, orçamentos), que podem divergir com o tempo.

### B. `AgenteDeclarado` ganha `produz` — vazio propõe, preenchido transforma

**É o que o spec de 2026-09-17 propôs**, na §6.2: *"`AgenteDeclarado` ganha
`produz: str | Mapping[str, str]`"*. Esta spec o contradiz de propósito, e o
motivo é que o formato mudou desde então: a união discriminada de blocos
(`schemas.py`) foi escrita DEPOIS, e o comentário dela diz por que:

> Por isso o bloco é uma UNIÃO DISCRIMINADA e não um dicionário com campos
> opcionais. Um `parametros: dict[str, int] | None` ao lado de um `prompt: str
> | None` aceitaria os quatro cruzamentos, dois dos quais não significam nada
> — e a recusa deles viraria código de validação escrito à mão.

Com `produz` dentro de `AgenteDeclarado`, `tipos` e `abstem_com` deixam de
significar qualquer coisa quando ele está preenchido (uma transformação não tem
vocabulário de julgamento a rotular), e um agente com `tipos` E `produz` é
exatamente um dos cruzamentos sem sentido. **Custo de estar errado:** um bloco
onde metade dos campos é ignorada em silêncio conforme outro campo — e o
sintoma é um agente que parece configurado e responde fora do vocabulário que o
autor declarou.

O `Mapping[str, str]` daquela §6.2 — tipo→kind, "ramificação sem código" — não
entra aqui por outro motivo: `condicao` já é o bloco que roteia, com teste e
com recusa de `produz == kind`. Duas maneiras de ramificar é uma a mais.

### C. Unificar `Agent` e `Tarefa` num resolver que às vezes produz

Rejeitada. A assimetria é garantia de TIPO hoje — *"`Agent` devolve `proposals`
e nunca `resolutions`"* —, e ela é a única coisa que impede o julgamento não
conferido de um modelo encerrar a vida de um item por acidente. Custo de estar
errado: a invariante mais cara do projeto sai sem ninguém ver, que é
literalmente o risco que a §6 do spec anterior nomeia.

---

## 3. `TarefaDeclarada`

Em `agent/declarado.py`, ao lado de `AgenteDeclarado`:

| campo | por quê |
|---|---|
| `name` | identidade do resolver; as contas do run são indexadas por ele |
| `system` | o papel |
| `kind` | o que consome |
| `produz` | o kind que sai — é o que liga este bloco ao próximo |
| `prompt` | template sobre os campos do payload |
| `ferramentas` | recortadas do registro, como em `construir_agente` |
| `model`, `max_turns`, `max_format_retries` | o laço |
| `budget_microcents`, `budget_total_microcents` | os dois tetos |

**Sem `tipos` e sem `abstem_com`**, e não é economia: `tarefa.py::_abster` já
diz por quê — *"não há tipo a escolher: não transformar é a ausência de
resolução, e ausência é a mesma em todo domínio"*.

Guardas na construção, espelhando `AgenteDeclarado.__post_init__`:

1. **prompt que não interpola nada** → recusa. Todo item receberia o mesmo
   texto; é caro e silencioso (a conta vem, a medida não).
2. **`produz` vazio** → recusa. Consumir sem produzir é o `filtro`, e ali é o
   pedido; aqui o item sumiria do run.
3. **`produz == kind`** → recusa, com a mesma frase de `condicao.py`: o ramo
   alimentaria a si mesmo.

---

## 4. `construir_tarefa(decl, client, ferramentas) -> Tarefa`

Deriva as duas funções que hoje cada domínio escreve à mão.

**`prompt_de`** é o `_campos(payload)` + `format_map` que `_units` já faz para o
agente. EXTRAÍDO, não copiado: duas cópias divergem, e a que divergir é a que
ninguém testa. A mensagem de campo ausente continua sendo a de lá, que nomeia o
campo que falta.

**`transformar`** é a forma genérica, e ela é a mesma que `_degrau` de
`domains/redacao` escreve três vezes:

```python
texto vazio        -> None            # dispara o retry de formato que já existe
texto utilizável   -> SaidaDaTarefa(
    resolution=Resolution(item_ids={item_id}, produced_by=name, rule=name,
                          evidence={"trace": rastro}),
    produced=(WorkItem(id=f"{item_id}+{produz}", kind=produz,
                       payload={produz: texto}, origem=name),),
)
```

O rastro vai em `evidence` porque `Tarefa` não o anexa por conta própria — quem
decide se ele sobrevive é o `transformar`, e *"uma proposta sem rastro é uma
afirmação sem fonte"* vale igual para uma resolução.

### 4.1 O payload é `{<produz>: texto}`, e isso não é detalhe

`domains/redacao` põe `payload=texto` — string crua. Isso **quebra o bloco
seguinte**: `_campos` levanta `TypeError` para payload que não seja dict ou
dataclass, e montar o prompt do próximo degrau é exatamente o que um pipeline
declarado faz. A string crua funciona lá porque lá o `prompt_de` seguinte também
é escrito à mão (`f"Revise este rascunho:\n{item.payload}"`).

Chaveado pelo **nome do kind** e não por um `"texto"` fixo: dois ramos de um
`Parallel` que se reúnem num `Merge` trariam `texto` os dois, e quem lê não
distinguiria de qual ramo veio. O nome sai do que já está declarado — nenhum
campo novo — e o próximo bloco escreve `{rascunho}`, que é como o canvas o
mostra.

---

## 5. `Tarefa` declara o grafo

`TarefaSpec` ganha `kind` e `produz`, **com default vazio**; `Tarefa.describe()`
passa a publicá-los em `consome`/`produz`. É o que fecha a §1.2, e o default
vazio é o que mantém a mudança retrocompatível: uma `TarefaSpec` que não os
declara descreve exatamente o que descreve hoje.

`domains/redacao` passa a declará-los na `TarefaSpec` e **apaga**
`consome=`/`produz=` dos três `Stage` — não porque escrever à mão seja
proibido, mas porque a mesma afirmação em dois lugares é o join frágil de
sempre, e aqui um dos dois passou a ser derivável. **Critério:** os TESTES de
`redacao` passam sem serem tocados; se algum precisar de edição, a derivação
não reproduz o que estava escrito.

---

## 6. Formato e borda

- `authoring/composicao.py`: `BlocoTarefa(declaracao: TarefaDeclarada)`,
  `nome_do_bloco` o reconhece, `_blocos_para_json`/`_blocos_de_json` ganham
  `"tarefa"`, e o `else` que recusa tipo desconhecido passa a listar quatro.
- `api/schemas.py`: `TarefaDeclaradaJSON` + `BlocoTarefaJSON` na união
  discriminada. Nenhum campo opcional novo em bloco existente.
- `api/app.py`: `_blocos_de` traduz o tipo novo; o catálogo publica que ele
  existe.
- **`digest`**: `Composicao.version` já entra pelo conteúdo dos blocos, então um
  bloco novo muda a versão sem nada a fazer — é o que mantém dois resultados de
  benchmark comparáveis só quando mediram a mesma cascata.

---

## 7. O que este plano NÃO faz

- **Canvas.** A paleta, o editor do bloco em `web-app/src`, `npx tsc --noEmit` e
  o bundle de `web/` são a fatia seguinte, com commit próprio. Até lá o bloco é
  montável por HTTP e por arquivo, com teste.
- **Ramificação por tipo** (`Mapping[str, str]` da §6.2 do spec anterior):
  `condicao` já roteia.
- **A lacuna do teto silencioso.** `Tarefa.resolve` descarta o `trace` de quem
  desistiu por orçamento — está documentada em `tarefa.py` como lacuna
  conhecida, e vale igual para uma tarefa declarada. Consertar exige canal novo
  em `ResolverOutput`, que é desenho, não correção.
- **Decisão humana genérica.** Continua sendo o "degrau HUMANO genérico", e
  `RevisorHumano` continua consumindo payloads de conciliação.

---

## 8. Riscos

| risco | mitigação |
|---|---|
| Duas declarações parecidas divergem (`AgenteDeclarado` × `TarefaDeclarada`) | O que é COMUM — `_campos`, recorte de ferramentas, guarda de prompt — é extraído e compartilhado; o que difere é o que justifica os dois tipos |
| Um pipeline declarado gasta N × turnos sem ninguém olhar | Os dois tetos já existem em `TarefaSpec`, e o teto por REQUISIÇÃO da borda continua valendo — `tem_agente` cobre `CostClass.AGENTE`, que é a classe da `Tarefa` |
| `produz` digitado errado vira kind órfão | A recusa de beco sem saída do kernel já pega: ou alguém consome, ou o autor declara em `entrega` |

---

## 9. Critério de aceite

1. Uma composição de duas etapas — `BlocoTarefa` escritor produzindo
   `rascunho`, `BlocoTarefa` revisor consumindo `rascunho` — montada por
   `POST /api/composicoes` e executada por `POST /runs` faz o revisor receber
   **o texto do escritor**, não o item original. É a medição do §0, invertida.
2. `pytest` verde nas duas instalações (`[dev]` e `[dev,api]`).
3. `orchestrator --seed 1 --n 500` diz `85.3%`, zero falso positivo, zero falso
   negativo.
4. Os testes de `domains/redacao` passam sem serem tocados.
