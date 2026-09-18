# A composição do canvas roda por `/runs` — design

**Fatia:** canvas → registry → execução, e a fiação por `kind` (X7) fechada.
**Antecede:** `2026-09-18-agentes-rodando-design.md` (a fonte no pedido, o motor genérico, o teto).
**Decisões do dono, tomadas em brainstorming:** o canvas **entrega** para a tela de execução (não roda inline); a guarda de `kind` vale para **todos** os workflows (composições, receitas e a `conciliacao` embutida); abordagem **A** — declarar no resolver, derivar no construtor.

---

## 1. O problema, com a frase do dono

> compor um agente na tela e conseguir rodar de verdade

A fatia anterior provou o caminho inteiro — CSV de issues → `triador` → propostas, com teto e sem inventar taxa — **sobre um workflow do `registry()`**. Uma composição feita no canvas vive em `data/composicoes/` e o `registry()` não a conhece. O botão "▶ Run" do canvas chama `POST /api/workflows/{id}/runs` com o id da composição e recebe **404** (`app.py:469` só consulta `registry(_RAIZ_RECEITAS)`). O botão existe e está quebrado por desenho, não por acidente.

Atrás disso há uma segunda lacuna, escrita no README e no cabeçalho de `authoring/composicao.py`: **X7/X8**. `construir_composicao` devolve um stage com `consome`/`produz` no default; o kernel desliga a checagem de beco sem saída assim que um stage usa o default; e um `AgenteDeclarado` com `kind` digitado errado é aceito e, em execução, "simplesmente nunca pega item nenhum". A resposta é `200` com lacuna de `100%` — um número com cara de medido sobre um pool que ninguém leu (README, linhas 152–157).

**E o defeito que a exploração achou, anterior a esta fatia:** o `investigador` do catálogo declara `kind="lancamento"` (`domains/registro.py:284`). A fonte sintética emite só `banco` e `contabil` (`models.py:113–114`), e o literal `"lancamento"` como kind não existe em nenhum outro lugar de `src/`. É o nome legado do domínio, renomeado sem o catálogo acompanhar — e a defasagem é **dupla**: o `prompt` desse agente é `"Divergência {id}: {descricao}"`, escrito contra a forma `Divergence` do domínio antigo, enquanto `_units` monta uma tarefa por item de `decl.kind` e interpola o prompt com os **campos do payload desse item**. Trocar só o `kind` moveria a falha de "cego" para um `KeyError` alto ("o prompt cita 'descricao'"), porque `BankEntry` não tem esse campo. E como `grill.receita.construir` constrói agentes a partir desta mesma declaração, **`pago.json` (`L1 + investigador`) está cego desde o rename** — o exato modo de falha que o docstring de `composicao.py` descreve, dentro do próprio catálogo.

## 2. O que esta fatia entrega

1. Uma composição salva aparece em `/api/workflows`, abre em `/api/workflows/{id}`, tem fila em `/api/fila/{id}` e **roda em `/runs`** — sem mudar nenhuma dessas rotas.
2. Todo resolver declara **o que consome**; todo construtor deriva `Stage.consome` disso; a borda do `/runs` recusa, **por resolver**, uma fonte que não entrega o que ele consome.
3. O canvas entrega para a tela de execução em vez de fingir que executa.
4. O `investigador` do catálogo passa a consumir o que existe.
5. **Os textos que hoje dizem que a lacuna está aberta deixam de dizer.** O bloco do README ("Não garante mais que o `kind` de um agente bate…", linhas 129–145, e o de `/runs` sobre kind errado, 152–157), o cabeçalho de `authoring/composicao.py` (que descreve a guarda inerte e nomeia X7/X8 como o conserto) e o comentário em `construir_composicao` ("Sem checagem de `kind`…") são **reescritos** para dizer onde a guarda mora agora e o que ainda fica fora (§9). Entrada em `DECISOES.md` com o porquê de "por resolver, na borda" e não "no kernel". Uma lacuna fechada que continua escrita como aberta é a meia-verdade que este repositório se recusa a manter.

O que **não** entra está na §9.

## 3. O contrato `consome` (X7)

### 3.1 No resolver — declarado, nunca inferido

`ResolverDescription` ganha:

```python
# Quais `WorkItem.kind` este resolver PEGA do pool. Vazio — o default — é
# "vejo o pool inteiro", o MESMO significado do default de `Stage.consome`.
consome: frozenset[str] = frozenset()
```

Irmã de `payloads` (Task 3 da fatia anterior), e com a mesma disciplina: **declarada**, porque quem compõe precisa da recusa antes de executar, e uma propriedade que só existe depois de rodar não previne nada.

**Por que não derivar de `payloads`.** `payloads` responde "que *tipo* exijo do payload deste kind"; `consome` responde "que *kinds* pego do pool". São perguntas diferentes: o `investigador` em Python lê objetos tipados por ferramentas; o `triador` lê dicionário por `_campos`. Amarrar as duas obrigaria um agente a declarar um tipo para dizer que consome um kind — e a borda de `payloads` passaria a recusar fonte válida.

**Quem declara o quê:**

| Resolver | `consome` | De onde |
|---|---|---|
| `L1`, `L2`, `L3`, `revisor` | `frozenset(PAYLOADS)` = `{banco, contabil}` | as chaves de `models.PAYLOADS` já são os kinds |
| regras de `procurement` | `frozenset(PAYLOADS)` do domínio | idem |
| agente construído por `construir_agente` — inclui o `investigador` **declarado** do catálogo, o `triador` e o `buscador` | `{decl.kind}` | o `kind` do `AgenteDeclarado`; um kind só, porque `kind: str` |
| `investigador` **em Python** (`agent/investigator.py`, `AgentSpec` próprio, monta tarefas de `divergencias(work)`) | `{banco, contabil}` | ele lê os dois lados de uma vez; é outro objeto, não o do catálogo |
| os outros três `AgentSpec(` (`cli/scaffold.py`, `domains/swe`, `__init__.py`) | default vazio | specs escritas à mão não mudam de comportamento |

**`AgentSpec` ganha `consome: frozenset[str] = frozenset()`.** Necessário, não opcional: hoje o `kind` do `AgenteDeclarado` é **apagado** na construção — vira a closure de `units` — e `Agent.describe()` não tem de onde lê-lo. A spec é a declaração; `Agent.describe()` a repassa.

**Pinado pela tabela.** `tests/domains/test_registro.py` já compara `payloads` de cada bloco do `CATALOGO` contra uma tabela e falha alto para bloco sem entrada. `consome` entra na mesma tabela, com a mesma regra: um bloco novo sem declaração obriga o próximo a decidir, nunca a herdar.

### 3.2 No construtor — uma função, três chamadas

```python
def consome_de(cascade: Iterable[Resolver]) -> frozenset[str]:
    """A união do que cada resolver declara consumir."""
```

Em `workflows.py`. Chamada por **`construir_composicao`**, **`grill.receita.construir`** e **`default_definition`** para popular `Stage.consome`. Três chamadas explícitas, e não uma derivação no kernel: `Stage.__post_init__` popular `consome` sozinho trocaria em silêncio o significado do default vazio para toda definição escrita em Python (`domains/redacao` declara; as outras confiam no "vê tudo"). O kernel não muda de semântica nesta fatia.

**Efeito no motor, e é o desejado.** `runtime/engine.py:108–112`: um degrau com `consome` populado vê só os itens desses kinds e **reserva** os outros, recompondo o pool no fim do stage. Um degrau que não enxerga item nenhum não roda (`engine.py:115`). Isso é a semântica certa para grafos de vários degraus — e é por isso que a recusa de um run inteiro sobre kind errado **não** mora no motor (que devolveria `concluido` com lacuna de 100%), e sim na borda.

`produz` continua vazio para tudo que se compõe: um `AgenteDeclarado` emite propostas, nunca itens. Só uma `Tarefa` produz, e não há bloco de `Tarefa` no catálogo. **X8 não é necessário** para esta fatia — ver §9.

### 3.3 Na borda — por resolver, sobre o pool carregado

O `/runs` já carrega o pool antes de executar (`pool = fonte.load()`). Os kinds da fonte são `{i.kind for i in pool.items}` — **sem mudar o protocolo `Source`**, e vale para qualquer fonte futura (HTTP inclusa).

A guarda, antes do `execute()` e depois de `_conferir_payload`:

- para **cada** resolver da definição com `consome` declarado, se `consome ∩ kinds_da_fonte = ∅` → **422**: *"o bloco 'investigador' consome {'lancamento'}, e a fonte entrega {'banco', 'contabil'}"*;
- pool vazio → **422**: *"a fonte não entregou item nenhum"*. Nunca um passe.

**Por resolver, não pela união do degrau.** A união deixaria passar um agente cego dentro de um degrau vivo — `L1 + investigador` com `investigador` sobre `lancamento` passaria porque `L1` consome `banco`. É o caso do catálogo hoje.

**A composição continua sendo aceita ao salvar.** `POST /api/composicoes` com `kind="lancamento"` devolve 201 como antes: a composição não conhece a fonte, e "valida construindo" continua sendo a garantia. O que muda é que `Stage.consome` agora carrega o kind, e o `/runs` recusa quando a fonte não o entrega. A guarda migrou de "partição de catálogo" (a antiga, removida por recusar cascata válida) para "o grafo que vai rodar contra a fonte que vai rodar".

### 3.4 O `investigador` do catálogo

Vira um agente declarado **correto sobre `banco`** — um kind só, como todo `AgenteDeclarado`:

- `kind="banco"`; `consome` derivado = `{banco}`.
- `prompt` reescrito sobre os campos que `_campos` (`asdict`) expõe de um `BankEntry`: `id`, `date`, `amount`, `description`, `counterparty`, `document`. Nada de `{descricao}`.
- `ferramentas` inalteradas: são elas que buscam o lado contábil — o investigador continua investigando divergências, mas parte de **um** lançamento bancário por tarefa e usa as ferramentas para ver o outro lado, em vez de supor um payload `Divergence` que a fonte não entrega.
- `tipos` e `abstem_com` inalterados.

Teste que prova, com cliente falso: sobre a fonte sintética ele **vê** itens, o prompt **renderiza** sem `KeyError`, e sai proposta. Sem esse conserto a guarda nova recusaria `pago.json` com 422 — corretamente — e a fatia terminaria com o workflow de demonstração inexecutável. O conserto entra **nesta** fatia por isso, e é o primeiro defeito real que a guarda pega.

**Consequência dita em voz alta:** `pago.json` no `data/` real do dono deixa de estar cego. Com `ANTHROPIC_API_KEY` no servidor e teto no pedido, ele passa a **gastar de verdade** — que é o que sempre deveria ter feito.

## 4. Registry, colisão e listagens

### 4.1 A fábrica

```python
def _de_composicao(c: Composicao) -> WorkflowFactory:
    def fabrica(ctx: WorkflowContext) -> WorkflowDefinition:
        return construir_composicao(c, fila=ctx.fila, cliente=ctx.cliente)
    return fabrica
```

O espelho exato de `_de_receita` (`workflows.py:91`). `ctx.cliente` repassado verbatim, inclusive `None` — quem decide o que `None` significa é `construir_composicao`, que cai em `ClienteDeValidacao`, a tranca. O próprio docstring de `construir_composicao` previu esta linha: *"para que o dia em que uma composição ganhar caminho de execução seja um `fila=ctx.fila` a mais"*.

### 4.2 O registry

`registry(raiz=None, raiz_composicoes=None)`: **embutida → receitas → composições**, e a ordem é a tranca (`conciliacao` é id reservado; disco nunca sobrescreve a embutida; receita nunca é sobrescrita por composição). Parâmetro novo por palavra-chave com default: os 11 chamadores em 4 arquivos (`api/app.py`, `cli/comandos.py`, `workflows.py`, mais docstrings em `authoring/composicao.py`) continuam iguais; a API passa `_RAIZ_COMPOSICOES`, que já existe e já é monkeypatchado nos testes.

Composições ficam em raiz própria (`data/composicoes/`), não em `data/workflows/`: formato diferente, serialização diferente, e um diretório só obrigaria o leitor a farejar o formato pelo conteúdo.

**Sem ciclo de importação:** `workflows.py` passa a importar `authoring.composicao` (`listar`, `construir_composicao`); `composicao.py` importa `domains.registro`, `agent.declarado`, `review.*` — nenhum deles importa `workflows`, `authoring` ou `api`. Verificado na exploração; se a implementação encontrar um, o import vai para dentro de `registry()`, como `default_definition` já faz com `review`.

### 4.3 Colisão de id — dois momentos

- **Na escrita:** `POST /api/composicoes` recusa com **409** um id já presente no `registry()` — embutido, receita ou outra composição. Simétrico ao precedente de `/api/receitas` (`app.py:350`), mesmo texto.
- **Na leitura:** se os dois arquivos existirem em disco (criados antes desta fatia, ou à mão), a receita vence e a composição é **pulada com aviso impresso**, no mesmo padrão com que `descrever()` isola uma receita que não constrói. A configuração inválida não some em silêncio nem derruba a listagem de todos os workflows por causa de um.

### 4.4 Listagens — de graça

`/api/workflows` itera `descrever()`, que itera o `registry()`: composições aparecem no seletor da tela de execução, com `classes` e `executavel` derivados da definição, como hoje. Único ajuste: `gerado_em`, que vem de um `dict` de receitas, passa a olhar também as composições (`Composicao.gerado_em` existe, com fuso obrigatório). `/api/workflows/{id}`, `/api/fila/{id}` e `/runs` não mudam. `/api/composicoes` continua como listagem de **autoria** — é o que o canvas lê.

Uma composição que parseia e não constrói (regra que saiu do catálogo, parâmetro renomeado) cai no isolamento de `descrever()`: some da listagem com aviso, e as outras continuam respondendo 200.

## 5. O canvas entrega para a execução

**O botão muda de verbo.** Hoje `App.tsx:255` chama `api.rodar(id, {sintética}, null)`. Passa a ser um hand-off: depois de "Compor e validar" devolver 201 — que já **grava** (`app.py:421–426`), então o id já está no registry — aparece **"abrir na execução →"**, levando a `/?workflow=<id>`. Mesmo idioma do link "fila de revisão →" do banner (`href="/?vista=fila&…"`) e mesma URL que o grill imprime no hand-off da CLI (`grill/cli.py:122`); sem `vista`, a vista default é a execução. O botão só existe **depois** de salvo: composição validada mas não gravada não está no registry.

**O que sai do canvas.** O estado `run`/`rodando` (`App.tsx:55`), o painel de resultado (`Painel.tsx:324–329`) e o `api.rodar` do canvas. Fonte, teto e resultado moram na tela de execução, por decisão do dono. O que o canvas precisa para *compor* — classes, custa-por-token sim/não — fica.

**A cópia que ficou falsa.** `Painel.tsx:185` — *"Tem classe AGENTE: gasta dinheiro ao rodar, e a API não a executa."* — virou mentira na Task 4 da fatia anterior. Passa a: *"Tem classe AGENTE: gasta dinheiro ao rodar — a execução pede teto e chave no servidor."* O comentário em `Painel.tsx:273` que afirma que "executar pela web nunca gasta" morre junto. Ambos pinados por asserção de bundle, verificados por mutação.

**Do outro lado, nada novo.** A tela de execução já mostra `executavel: false` com o motivo sem chave, já exige teto com agente, já oferece fonte de arquivo.

## 6. Erros

| Onde | Código | Diz |
|---|---|---|
| `/runs`, resolver sem interseção com os kinds da fonte | 422 | bloco, o que ele consome, o que a fonte entregou |
| `/runs`, pool vazio | 422 | "a fonte não entregou item nenhum" |
| `POST /api/composicoes`, id já no registry | 409 | igual ao de `/api/receitas` |
| leitura, receita e composição com o mesmo id | aviso impresso | composição pulada; receita vence |
| leitura, composição que não constrói | aviso impresso | some da listagem; as outras seguem |

Nenhum caminho devolve 200 sobre um pool que ninguém leu.

## 7. Testes

**Que nascem.**
- `consome` na tabela de `test_registro.py`; bloco sem declaração falha alto.
- `consome_de` unitário; cada um dos três construtores populando `Stage.consome` — a `conciliacao` embutida com exatamente `{banco, contabil}`.
- Borda: o `investigador` sobre issues (422 nomeando bloco/consome/fonte), pool vazio (422), e um que passa.
- `investigador` corrigido: com cliente falso, vê itens da fonte sintética e propõe.
- Registry: ordem embutida→receita→composição; 409 na escrita; pulo-com-aviso na leitura; `gerado_em` da composição na listagem.
- **Fim-a-fim, o objetivo da fatia:** `POST /api/composicoes` com `triador` → `/runs` com CSV de issues, teto e cliente falso → `propostas_por_tipo` não vazio e `falhas == 0`.
- Bundle: a cópia nova e o `href` do hand-off, verificados por mutação como na Task 5 anterior.

**Que viram — reescritos, não apagados.**
- `tests/api/test_composicoes.py:159` pina hoje que `construir_composicao` "não popula `consome`" e diz "religar precisa do X7/X8 e da fiação". Mantém a asserção (201) e o docstring passa a dizer onde a guarda mora agora.
- `tests/api/test_execucao.py:527/532` provam que o arquivo é lido usando kinds que ninguém consome; com a guarda passam a afirmar o 422. A prova de "o arquivo é lido" já mora no teste com cascata consumidora que a Task 3 anterior criou.
- O estopim `test_a_lacuna_do_produtor_nao_e_alcancavel_pelo_CATALOGO` **continua verde**: populamos `consome`, não `produz`.
- **Os que dependiam do investigador cego sem saber.** Receitas com `investigador` aparecem em `test_execucao.py`, `test_workflows_gerados.py`, `test_dinheiro_workflow_gerado.py` e `test_compor.py`. Hoje esse agente nunca vê item, então qualquer asserção de "zero propostas", "custo zero" ou "o cliente não foi chamado" pode estar verde **por acidente**. Com o conserto ele propõe: cada um desses testes é relido, e o que afirmava um acidente passa a afirmar o comportamento real, com o motivo no docstring. Nenhum é apagado.

**Gate do navegador, sem `ANTHROPIC_API_KEY`.** Compor o `triador` no canvas → "Compor e validar" → "abrir na execução →" → a composição no seletor → fonte `arquivo` com o CSV de issues → sem chave, `executavel: false` com o motivo. A execução em si é provada pelo fim-a-fim com cliente falso: o navegador não pode gastar.

## 8. Restrições globais (herdadas, verbatim)

- Nenhum teste chama API paga. A tranca de rede de `tests/conftest.py` continua e não é tocada.
- `ClienteAusente` continua o default de `construir`; `ClienteDeValidacao`, o de `construir_composicao`.
- Configuração inválida falha alto; nunca fallback silencioso.
- AUSENTE, não zero — nunca um número com cara de medido sobre o que não foi medido.
- Dinheiro em inteiro de micro-centavos.
- Código, comentários e docstrings em português; docstring explica POR QUE.
- Rodar: `./.venv/Scripts/python.exe -m pytest -q`; lint: `ruff check .`; front: `cd web-app && npx tsc --noEmit && npm run build` (o `--prefix` do npx não typechecka) e commitar o bundle.

## 9. Fora desta fatia — dito em voz alta

- **X8 — `AgenteDeclarado` declarar o que `produz`.** Desnecessário enquanto agentes declarados só emitem propostas. Entra no dia em que houver bloco de `Tarefa` no catálogo.
- **Vários stages numa composição.** `construir_composicao` continua devolvendo um stage; `consome` derivado é a fiação *desse* stage. Pipeline composto no canvas é outra fatia.
- **A lacuna do produtor** (`_conferir_payload` só inspeciona o pool inicial) continua contida pelo `xfail(strict)` + estopim da fatia anterior.
- **Teto agregado, auth, rate limit em `/runs`.** Decisão de produto adiada pelo dono.
- **Vista da fila para fonte de arquivo** (`file-<sha16>` sem rota para abrir). Registrada na revisão final anterior.

## 10. Critério de aceite

Uma pessoa, na tela, sem tocar em código: compõe um agente `triador` no canvas, clica "Compor e validar", clica "abrir na execução →", escolhe um CSV de issues, diz o teto, roda — e vê propostas por tipo, o custo, e o estado do run. E se digitar um `kind` que a fonte não entrega, vê **antes de gastar** qual bloco não consome o quê.
