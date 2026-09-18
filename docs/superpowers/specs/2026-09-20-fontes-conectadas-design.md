# Fontes conectadas — banco por DSN e API com token — design

**Fatia:** duas `Source`s novas, `PostgresSource` e `HttpSource`, escolhíveis na tela de execução, com segredo por nome de variável de ambiente.
**Antecede:** `2026-09-18-agentes-rodando-design.md` (§4 adiou o HTTP como "plano 2"; esta fatia o fecha) e `2026-09-19-canvas-para-runs-design.md` (a fonte vem no pedido; o canvas entrega para a execução).
**Decisões do dono, tomadas em brainstorming:** um bloco de entrada é uma **fonte** (alimenta o pool no início do run), não uma ferramenta de agente; o segredo é uma **referência a variável de ambiente**, nunca digitado nem gravado; primeira fatia com **Postgres + HTTP com token**, `psycopg` e `httpx` como dependências de runtime num extra; abordagem **A** — fontes escolhidas na execução, canvas inalterado.

---

## 1. O problema

Hoje uma execução só sabe vir de dois lugares: o benchmark sintético e um arquivo CSV/JSON que alguém copiou para `data/entradas/`. O trabalho de verdade mora num banco e atrás de uma API. A frase do dono:

> seria bom por uns blocos/tools de entrada de dados como poder conectar com uma string de banco, uma api com token, e etc

`kernel/source.py` prometeu isto desde o PR #9 — *"quem tiver o dado escreve um `Source` de 40 linhas, e é essa a promessa do framework"* — e já reserva o prefixo `erp:` ao lado de `synth:` e `file:`. O spec anterior deixou o HTTP escrito como plano 2 pelas razões certas: `ref` estável exige etag ou hash do corpo, e junto vêm auth, paginação e cursor. Esta fatia entrega a parte que tem `ref` estável hoje e diz em voz alta o que fica.

**O que não muda, e é o ponto.** A borda do `/runs` — `_fonte_de`, `_ler`, `_conferir_payload`, `_conferir_kinds`, pool vazio, `contra_gabarito: null`, chave da fila por `dataset_de_ref` — é a mesma para as fontes novas. Uma fonte é um `ref` e um `load()`; tudo que a plataforma aprendeu a fazer com um arquivo ela faz com uma query ou um endpoint sem tocar numa linha da borda.

## 2. O que esta fatia entrega

1. `PostgresSource(dsn_env, query, kind, campo_id, max_linhas=5000)` em `src/orchestrator/sources/postgres.py`.
2. `HttpSource(url, token_env, kind, campo_id, caminho="", max_linhas=5000)` em `src/orchestrator/sources/http.py`.
3. `RunRequest.fonte` ganha `FontePostgres` e `FonteHttp` (discriminadas por `tipo`, `extra="forbid"`); `_fonte_de` as constrói; nada mais muda na borda.
4. Um extra `[fontes]` em `pyproject.toml` com `psycopg[binary]` e `httpx`, importados **dentro** do `load()`: sem o extra a API sobe e a fonte devolve 422, não 500.
5. A tela de execução com os dois tipos no seletor e os campos por tipo; os campos de segredo são **nomes**.
6. Testes sem infraestrutura, e os testes de higiene de segredo.
7. README e `DECISOES.md` dizendo o que entrou e o que ficou (§9).

## 3. As duas fontes

### 3.1 `PostgresSource`

```python
@dataclass(frozen=True)
class PostgresSource:
    dsn_env: str          # NOME da variável de ambiente que guarda o DSN
    query: str            # um SELECT (ou WITH … SELECT), uma instrução só
    kind: str
    campo_id: str
    max_linhas: int = MAX_LINHAS_PADRAO
    # Injetável para os testes. `None` significa "o de verdade": `psycopg.connect`,
    # importado dentro do `load()` para que o extra [fontes] seja opcional.
    conectar: Callable[[str], Any] | None = None
```

`load()` lê `os.environ[dsn_env]` **na hora de rodar** — nunca na construção, para que construir (validar, descrever) não exija segredo —, conecta com `psycopg` em `dict_row`, executa a query e transforma cada linha em `WorkItem(id=str(linha[campo_id]), kind=kind, payload=dict(linha))`. As guardas são as do `ArquivoSource`, pela mesma razão: `campo_id` ausente ou vazio numa linha falha alto nomeando a linha; acima de `max_linhas` falha alto; nada é pulado em silêncio. Zero linhas não é tratado aqui: é a guarda de pool vazio da borda, que já existe.

**A query tem que ser leitura.** Antes de conectar: sem comentários e espaço à frente, a primeira palavra é `SELECT` ou `WITH` (CTE é leitura), e não há `;` no meio (uma instrução só). Qualquer outra coisa é 422. A guarda é **conservadora de propósito**: a plataforma lê e nunca escreve no banco do parceiro. Um `SELECT` legítimo que ela recuse é um bug a corrigir; um `DELETE` que ela deixasse passar seria um desastre. Sem parâmetros nesta fatia — a query é texto; parâmetros entram quando houver caso (§9).

**`ref`:** `pg:<dsn_env>/<sha256(query)[:12]>@<sha256(linhas canônicas)>`. O *nome* da variável identifica a conexão sem revelar nada; o hash da query diz qual pergunta; o hash das linhas (JSON canônico, chaves ordenadas, `default=str`) diz qual resposta — é o que faz duas execuções sobre os mesmos dados casarem as decisões humanas, e uma linha mudada mudar o `ref`. O DSN nunca entra.

### 3.2 `HttpSource`

```python
@dataclass(frozen=True)
class HttpSource:
    url: str
    token_env: str | None  # NOME da variável com o token; None = sem autenticação
    kind: str
    campo_id: str
    caminho: str = ""      # ponteiro simples até a lista: "dados.itens"; vazio = o corpo é a lista
    max_linhas: int = MAX_LINHAS_PADRAO
    transporte: Any = None # injetável; default o do httpx
```

`load()` faz **um** `GET` com `Authorization: Bearer <os.environ[token_env]>` quando `token_env` está dado. O corpo tem que ser JSON; a lista é o corpo inteiro ou o que `caminho` aponta (`a.b.c`, só chaves de objeto, sem índices); cada objeto vira um item como acima. **Uma página só nesta fatia** — paginação e cursor ficam em §9, com o porquê.

**`ref`:** ~~`http:<url>@<etag>` quando o servidor manda `ETag`; senão `http:<url>@<sha256(corpo)>`. É o que o spec anterior desenhou.~~ A URL entra inteira (é identidade), o cabeçalho de autorização nunca.

> **SUPERADO na revisão final (achado 4), depois de a fatia estar escrita.** O que está riscado acima é o que este spec pediu e o que a implementação original fez. A regra que vale é: **`ref` é `http:<url>@<sha256(corpo)>`, SEMPRE — o ETag não entra.**
>
> O motivo: o ETag é escolhido pelo servidor do parceiro e não tem relação garantida com os bytes. Um ETag fraco (`W/"v1"`) significa, por definição da própria especificação de HTTP, "equivalente, não idêntico" — então dois pools DIFERENTES podiam compartilhar um `ref`, e uma decisão humana tomada sobre o pool A seria casada com os itens do pool B. O inverso também: ETag derivado de inode ou variado por nó de CDN muda para bytes idênticos, e cada `ref` novo órfã a fila de revisão daquele conjunto. A garantia de content-addressing do protocolo `Source` é mais funda do que esta linha do spec, e o dono decidiu que é ela que vence. O ETag volta a ter uso no dia em que houver cache, como `If-None-Match`, que é para o que ele serve.
>
> A mesma correção vale para a linha de §7 sobre testes: onde se lê "etag → `ref` usa o etag", leia-se "mesmo corpo → mesmo `ref`, corpos diferentes → `ref` diferentes, com ou sem ETag". O registro completo está em `.superpowers/sdd/2026-09-20-fontes-conectadas/final-review.md` e no relatório da onda de correção ao lado dele.

**Segurança dita em voz alta.** Com esta fonte o servidor passa a fazer requisições para URLs que vêm da tela. `localhost`, `127.0.0.0/8`, `::1`, `169.254.0.0/16` e esquemas que não sejam `http`/`https` são recusados com 422 **antes de qualquer requisição** — a proteção mínima contra usar a plataforma para alcançar o que só o servidor alcança. Um erro HTTP cita status e URL; o cabeçalho de autorização não aparece em resposta, log, `ref` nem run.

### 3.3 O segredo é um nome

`dsn_env` e `token_env` são nomes de variáveis do **ambiente do servidor**, o mesmo padrão da `ANTHROPIC_API_KEY`. O valor é lido no `load()`, usado, e descartado. Se a variável não existe: 422 nomeando-a — o nome, só o nome. Nenhum segredo em composição, pedido persistido, `ref`, resposta, log ou tela.

**Os erros do driver são reduzidos.** `psycopg.OperationalError` pode ecoar host e usuário na mensagem. A resposta ao cliente é *"conexão falhou: <classe do erro>"* (ou *"consulta falhou: <classe>"*); a mensagem inteira vai para o log do servidor, onde quem opera o servidor a lê. Esta redução tem teste próprio (§7).

### 3.4 O extra `[fontes]`

`pyproject.toml`: `fontes = ["psycopg[binary]>=3.1", "httpx>=0.27"]`. Os imports ficam **dentro** de `load()` (e de `_guarda_select`, que não precisa de driver). Sem o extra, a API sobe normalmente, o seletor mostra os tipos, e a execução devolve 422 *"instale o extra [fontes]"* — falha alta, não 500. `sources/` continua importando só `kernel` de dentro do pacote: `tests/arquitetura/camadas.py` não muda.

## 4. A borda

`api/schemas.py`:

```python
class FontePostgres(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tipo: Literal["postgres"]
    dsn_env: str
    query: str
    kind: str
    campo_id: str

class FonteHttp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tipo: Literal["http"]
    url: str
    token_env: str | None = None
    kind: str
    campo_id: str
    caminho: str = ""
```

`RunRequest.fonte: FonteSintetica | FonteArquivo | FontePostgres | FonteHttp`, discriminador `tipo`. `_fonte_de` constrói a fonte e devolve `(fonte, None)` — sem gabarito, como o arquivo. `_ler` já é o lugar onde a leitura preguiçosa falha em 422; ganha os erros novos (§6) na mesma cláusula, com a mesma disciplina de nunca devolver o que o servidor sabe e o cliente não pediu.

**Nada mais muda.** `_conferir_payload` e `_conferir_kinds` rodam sobre o pool que veio; `contra_gabarito` é `None`; a chave da fila é `dataset_de_ref(fonte.ref)` — `pg-<sha16>`, `http-<sha16>` — e a fila fica escopada por conteúdo, como o arquivo.

## 5. A tela de execução

Só `web-app/src/Execucao.tsx` e `api.ts`. O canvas não muda: ele entrega para a execução, e é lá que a fonte é escolhida.

**O seletor ganha dois tipos:** `postgres (sem gabarito)` e `api http (sem gabarito)`. Cada tipo mostra os seus campos; `kind` e `campo id` são comuns aos tipos sem gabarito.

- *postgres:* `variável do DSN` — texto, dica *"nome da variável de ambiente no servidor — ex.: ERP_DSN"*; `query` — área de texto, dica *"só SELECT"*.
- *api http:* `url`; `variável do token` — mesma dica, opcional; `caminho na resposta` — opcional, dica *"deixe vazio se o corpo já é a lista"*.

**O que a tela não faz.** Os campos de segredo são `<input type="text">` — **nunca** `type="password"`: não há segredo ali para esconder, e um campo de senha ensinaria a pessoa a colar o valor. A tela nunca pede, guarda ou mostra um DSN ou token. Os 422 do servidor aparecem onde hoje aparecem "fora da raiz" e "arquivo não encontrado". Teto antes do botão, `contra_gabarito` ausente como texto, `estado`/`teto_atingido`/`falhas`: como está.

`api.ts`: `FontePedido` vira a união dos quatro tipos, espelhando `RunRequest.fonte`; `rodar()` não muda de assinatura.

## 6. Erros

| Onde | Código | Diz |
|---|---|---|
| variável de ambiente ausente | 422 | o nome, só o nome |
| query que não começa com `SELECT`/`WITH`, ou com `;` no meio | 422 | "a query precisa ser um SELECT só" — antes de conectar |
| erro do driver (conexão, SQL) | 422 | "conexão/consulta falhou: <classe>"; a mensagem inteira no log |
| HTTP não-2xx | 422 | status e URL; nunca o cabeçalho de autorização |
| corpo que não é JSON, não é lista, ou `caminho` não leva a uma lista | 422 | o que veio no lugar |
| URL loopback / link-local / esquema não-http | 422 | antes de qualquer requisição |
| extra `[fontes]` não instalado | 422 | "instale o extra [fontes]" |
| `campo_id` ausente/vazio numa linha; acima de `max_linhas` | 422 | a linha, o campo, o teto — como `ArquivoSource` |
| zero linhas | 422 | a guarda de pool vazio da borda |

Nenhum caminho devolve 500 sobre uma escolha do cliente, e nenhum devolve um segredo.

## 7. Testes

**Sem infraestrutura.** `PostgresSource.conectar` injetável: os testes passam uma conexão falsa cujo cursor devolve linhas-dict; `HttpSource.transporte` injetável: `httpx.MockTransport` (já dep de dev). Nenhum teste abre socket; nenhum precisa de Postgres. Um teste de integração **opcional**, `skipif` sem `TESTE_PG_DSN`, para quem tiver banco — nunca exigido pelo CI.

**Higiene de segredo — os que importam.** Com `ERP_DSN` e `CRM_TOKEN` apontando para um sentinela (`SEGREDO-4F2A`), cada caminho de falha roda — conexão recusada, query inválida, 401, corpo que não é lista, teto de linhas — e o sentinela **não aparece** em corpo da resposta, `ref`, run persistido, nem `stderr`. Variável ausente → 422 com o nome, e só o nome. A redução do erro do psycopg (§3.3) tem teste: uma `OperationalError` cuja mensagem contém o sentinela vira *"conexão falhou: OperationalError"*.

**`ref` estável ou não há replay.** Mesmas linhas → mesmo `ref`; uma linha mudada → outro; query mudada → outro. HTTP: ~~etag → `ref` usa o etag; sem etag → hash do corpo;~~ (superado — ver §3.2) hash do corpo sempre; mesmo corpo → mesmo `ref`. `dataset_de_ref` das duas fontes é nome de arquivo válido e distinto por conteúdo — por construção, como na fatia anterior.

**A guarda de `SELECT`.** `SELECT …`, `select …`, `  -- comentário\nSELECT …`, `WITH x AS (…) SELECT …` passam; `INSERT`, `UPDATE`, `DELETE`, `DROP`, `CALL`, `SELECT 1; DELETE …` são 422 — e o teste afirma que **`conectar` não foi chamado**.

**Loopback.** `http://127.0.0.1/…`, `http://localhost/…`, `http://169.254.1.1/…`, `ftp://…` → 422 e o transporte falso registra **zero** requisições.

**Fim-a-fim pela borda**, com transporte/conexão falsos injetados por `monkeypatch` no módulo: `/runs` com fonte `http` de issues → `triador` com cliente falso → `propostas_por_tipo` não vazio, `contra_gabarito: null`, custo, teto — o mesmo teste que a fatia anterior fez para arquivo; e o mesmo para `postgres`. Sem o extra: `ImportError` simulado → 422 "instale o extra [fontes]".

**Bundle** (`tests/api/test_compor.py`): as duas opções novas existem; **nenhum** `type="password"` na vista de execução.

**Gate do navegador, sem chave e sem banco:** os dois tipos no seletor, os campos por tipo, e o 422 de variável ausente renderizado — basta não definir a variável. Light e dark com os tokens existentes.

## 8. Restrições globais (herdadas, verbatim)

- Nenhum teste chama API paga; `tests/conftest.py` intacto; mesmo resultado com `ANTHROPIC_API_KEY=lixo`. **Nenhum teste abre socket para banco ou HTTP.**
- Configuração inválida falha alto; nunca fallback silencioso.
- AUSENTE, não zero.
- `ref` estável ou não há replay: hash do CONTEÚDO.
- Dinheiro em inteiro de micro-centavos.
- Português; docstring explica POR QUE.
- `sources/` importa só `kernel` de dentro do pacote (ratchet).
- Rodar: `./.venv/Scripts/python.exe -m pytest -q`; `ruff check .`; front: `cd web-app && npx tsc --noEmit && npm run build` e commitar o bundle.

## 9. Fora desta fatia — dito em voz alta

- **Paginação e cursor no HTTP.** Uma página só. O `ref` de várias páginas depende de várias respostas, e o etag de uma não cobre as outras — é desenho próprio.
- **Query com parâmetros.** Entra quando houver caso; hoje a query é texto e a guarda é de leitura.
- **Outros bancos** (MySQL, SQL Server). A costura — `conectar` injetável, `ref` por hash — nasce pronta; o driver é outro extra.
- **"Testar conexão" antes de rodar.** Seria uma segunda rota até o segredo; fica para quando a tela pedir.
- **A CLI** (`orch run`) não ganha os tipos novos nesta fatia.
- **Allowlist de hosts** para a fonte HTTP. Loopback recusado é o mínimo; uma lista do operador é decisão de produto.
- **Teto agregado, auth, rate limit em `/runs`.** Continua adiado pelo dono.

## 10. Critério de aceite

Uma pessoa, na tela, sem tocar em código: escolhe `postgres`, digita o nome da variável do DSN e um `SELECT`, `kind` e `campo id`, diz o teto, roda — e vê propostas por tipo, custo e estado, com *"sem gabarito"* no lugar da taxa. Troca para `api http`, digita a URL e o nome da variável do token, roda — o mesmo. Erra o nome da variável e vê o nome na mensagem, nunca um valor. E em nenhum lugar — resposta, run, log, tela — o DSN ou o token aparecem.
