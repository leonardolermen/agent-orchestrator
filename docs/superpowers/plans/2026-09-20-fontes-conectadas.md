# Fontes conectadas — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Uma execução pode vir de uma query Postgres ou de uma API HTTP com token, escolhidas na tela, com o segredo referenciado por nome de variável de ambiente — e nenhum segredo aparece em resposta, `ref`, run, log de resposta ou tela.

**Architecture:** Duas `Source`s novas com a costura do `ArquivoSource` (leitura preguiçosa memoizada, `ref` por hash do conteúdo, guardas altas por linha), conexão e transporte injetáveis para testar sem infraestrutura, erros normalizados numa hierarquia própria (`sources/erros.py`) que a borda mapeia para 422, e a tela de execução com os dois tipos e campos de nome.

**Tech Stack:** Python 3.13, pydantic, FastAPI, `psycopg[binary]` e `httpx` num extra `[fontes]` importados dentro do `load()`; React/Vite/Tailwind em `web-app/`, bundle commitado em `web/`.

**Spec:** `docs/superpowers/specs/2026-09-20-fontes-conectadas-design.md`

**Uma clarificação da spec (§7), decidida aqui:** "o sentinela não aparece em `stderr`" vale para o que a FONTE emite (ela não imprime nada); a mensagem inteira do driver vai para **um registro de `logging`**, o lugar designado, e o teste a afirma lá com `caplog`. `logging` escreve em stderr por padrão — isso é o log do servidor, não uma fuga.

## Global Constraints

- Nenhum teste chama API paga; `tests/conftest.py` intacto; mesmo resultado com `ANTHROPIC_API_KEY=lixo`. **Nenhum teste abre socket para banco ou HTTP** — conexão e transporte são injetados.
- Configuração inválida falha alto; nunca fallback silencioso.
- AUSENTE, não zero: fonte sem gabarito → `contra_gabarito: null`.
- `ref` estável ou não há replay: hash do CONTEÚDO (linhas canônicas; etag ou corpo).
- **O segredo é um NOME.** `dsn_env`/`token_env` são nomes de variáveis do ambiente do servidor, lidos no `load()`. Nenhum valor em composição, pedido persistido, `ref`, resposta, tela, nem no que a fonte imprime.
- **A query é leitura:** primeira palavra `SELECT` ou `WITH`, uma instrução só — antes de conectar.
- **Loopback recusado antes de qualquer requisição:** `localhost`, `127.0.0.0/8`, `::1`, `169.254.0.0/16`, esquema que não seja `http`/`https`.
- Extra `[fontes]` importado DENTRO do `load()`; sem ele, 422 "instale o extra [fontes]", nunca 500.
- `sources/` importa só `kernel` de dentro do pacote (ratchet em `tests/arquitetura/camadas.py` não muda).
- Português; docstring explica POR QUE.
- Rodar: `./.venv/Scripts/python.exe -m pytest -q`; lint: `./.venv/Scripts/python.exe -m ruff check .`; front: `cd web-app && npx tsc --noEmit && npm run build` (o `--prefix` do npx NÃO typechecka) e **commitar o bundle**.
- Baseline ao começar: **1006 passed, 1 skipped, 1 xfailed** (skip: symlink; xfail: `strict`, deliberado). Nenhum dos dois muda.

## Estrutura de arquivos

| Arquivo | Responsabilidade | Task |
|---|---|---|
| `src/orchestrator/sources/erros.py` **(novo)** | `ErroDeFonte`, `VariavelAusente`, `ExtraAusente`, `FonteFalhou` — a hierarquia que a borda mapeia para 422 | 1 |
| `src/orchestrator/sources/postgres.py` **(novo)** | `PostgresSource`: guarda de SELECT, conexão injetável, `ref`, redução de erro | 1 |
| `pyproject.toml` | extra `fontes = ["psycopg[binary]>=3.1", "httpx>=0.27"]` | 1 |
| `tests/sources/test_postgres.py` **(novo)** | conexão falsa; guarda; segredo; `ref` | 1 |
| `src/orchestrator/sources/http.py` **(novo)** | `HttpSource`: guarda de URL, transporte injetável, `caminho`, `ref` por etag/corpo | 2 |
| `tests/sources/test_http.py` **(novo)** | `MockTransport`; loopback; 401 sem token na mensagem; `ref` | 2 |
| `src/orchestrator/api/schemas.py` | `FontePostgres`, `FonteHttp`, união em `RunRequest.fonte` | 3 |
| `src/orchestrator/api/app.py` | `_fonte_de` constrói; `_ler` mapeia `ErroDeFonte` → 422 | 3 |
| `tests/api/test_execucao.py` | fim-a-fim das duas fontes pela borda; extra ausente → 422 | 3 |
| `tests/review/test_fila.py` | `dataset_de_ref` de `pg:`/`http:` | 3 |
| `web-app/src/api.ts`, `Execucao.tsx`, `web/` | seletor, campos por tipo, bundle | 4 |
| `tests/api/test_compor.py` | bundle: opções presentes; nenhum `password` | 4 |
| `README.md`, `docs/superpowers/DECISOES.md` | o bloco do `/runs`; P9.2 | 5 |

---

### Task 1: `PostgresSource` — e a hierarquia de erros das fontes

**Files:**
- Create: `src/orchestrator/sources/erros.py`
- Create: `src/orchestrator/sources/postgres.py`
- Modify: `pyproject.toml` (extra `fontes`, ao lado de `api`)
- Test: `tests/sources/test_postgres.py`

**Interfaces:**
- Produces: `ErroDeFonte(ValueError)`, `VariavelAusente(ErroDeFonte)`, `ExtraAusente(ErroDeFonte)`, `FonteFalhou(ErroDeFonte)`; `PostgresSource(dsn_env, query, kind, campo_id, max_linhas=5000, conectar=None)` com `.ref` e `.load()`; `MAX_LINHAS_PADRAO = 5000`.
- A conexão injetada é qualquer objeto com `cursor()` → objeto com `execute(query)` e `fetchall()` → `list[dict]`, e `close()`.

- [ ] **Step 1: Os testes que falham**

`tests/sources/test_postgres.py`:

```python
"""A fonte Postgres: ler é fácil; não escrever, não vazar, e ter `ref` é o trabalho."""

import logging

import pytest

from orchestrator.sources.erros import ExtraAusente, FonteFalhou, VariavelAusente
from orchestrator.sources.postgres import PostgresSource

SENTINELA = "postgresql://usuario:SEGREDO-4F2A@db.interna:5432/erp"


class _Cursor:
    def __init__(self, linhas, erro=None):
        self.linhas, self.erro, self.executadas = linhas, erro, []

    def execute(self, query):
        self.executadas.append(query)
        if self.erro:
            raise self.erro

    def fetchall(self):
        return list(self.linhas)


class _Conexao:
    def __init__(self, linhas, erro=None):
        self.cursor_ = _Cursor(linhas, erro)
        self.fechada = False

    def cursor(self):
        return self.cursor_

    def close(self):
        self.fechada = True


def _fonte(monkeypatch, linhas, *, query="SELECT id, titulo FROM issues", erro=None, env=SENTINELA):
    """Conexão FALSA injetada; nenhum socket. A variável de ambiente recebe o
    sentinela para que qualquer vazamento apareça como texto reconhecível."""
    if env is not None:
        monkeypatch.setenv("ERP_DSN", env)
    else:
        monkeypatch.delenv("ERP_DSN", raising=False)
    conexoes = []

    def conectar(dsn):
        conexoes.append(dsn)
        return _Conexao(linhas, erro)

    fonte = PostgresSource(dsn_env="ERP_DSN", query=query, kind="issue", campo_id="id", conectar=conectar)
    return fonte, conexoes


def test_linhas_viram_pool_com_o_kind_e_o_payload_cru(monkeypatch):
    fonte, _ = _fonte(monkeypatch, [{"id": 7, "titulo": "trava"}, {"id": 8, "titulo": "lento"}])
    pool = fonte.load()
    assert [i.id for i in pool.items] == ["7", "8"]
    assert {i.kind for i in pool.items} == {"issue"}
    assert pool.items[0].payload == {"id": 7, "titulo": "trava"}


def test_o_DSN_e_lido_do_ambiente_NA_HORA_e_passado_ao_conectar(monkeypatch):
    fonte, conexoes = _fonte(monkeypatch, [{"id": 1}])
    fonte.load()
    assert conexoes == [SENTINELA]


def test_variavel_ausente_e_422_que_cita_o_NOME_e_nao_conecta(monkeypatch):
    fonte, conexoes = _fonte(monkeypatch, [{"id": 1}], env=None)
    with pytest.raises(VariavelAusente) as erro:
        fonte.load()
    assert "ERP_DSN" in str(erro.value)
    assert conexoes == []


@pytest.mark.parametrize(
    "query",
    [
        "SELECT id FROM issues",
        "select id from issues",
        "  -- comentário\nSELECT id FROM issues",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "SELECT id FROM issues;",
    ],
)
def test_leitura_PASSA_na_guarda(monkeypatch, query):
    fonte, conexoes = _fonte(monkeypatch, [{"id": 1}], query=query)
    fonte.load()
    assert len(conexoes) == 1


@pytest.mark.parametrize(
    "query",
    [
        "INSERT INTO issues VALUES (1)",
        "UPDATE issues SET x = 1",
        "DELETE FROM issues",
        "DROP TABLE issues",
        "CALL limpar()",
        "SELECT 1; DELETE FROM issues",
    ],
)
def test_escrita_e_recusada_ANTES_de_conectar(monkeypatch, query):
    """A plataforma lê e nunca escreve. A guarda é conservadora de propósito, e
    o que ela prova é que `conectar` NÃO foi chamado."""
    fonte, conexoes = _fonte(monkeypatch, [{"id": 1}], query=query)
    with pytest.raises(FonteFalhou, match="SELECT"):
        fonte.load()
    assert conexoes == []


def test_o_ref_leva_o_NOME_da_variavel_o_hash_da_query_e_o_hash_das_linhas(monkeypatch):
    fonte, _ = _fonte(monkeypatch, [{"id": 1, "t": "a"}])
    ref = fonte.ref
    assert ref.startswith("pg:ERP_DSN/")
    assert "@" in ref
    assert "SEGREDO" not in ref and "db.interna" not in ref


def test_o_ref_e_ESTAVEL_para_as_mesmas_linhas_e_muda_quando_uma_muda(monkeypatch):
    a, _ = _fonte(monkeypatch, [{"id": 1, "t": "a"}, {"id": 2, "t": "b"}])
    b, _ = _fonte(monkeypatch, [{"id": 1, "t": "a"}, {"id": 2, "t": "b"}])
    c, _ = _fonte(monkeypatch, [{"id": 1, "t": "a"}, {"id": 2, "t": "MUDOU"}])
    assert a.ref == b.ref
    assert a.ref != c.ref


def test_o_ref_muda_quando_a_QUERY_muda(monkeypatch):
    a, _ = _fonte(monkeypatch, [{"id": 1}], query="SELECT id FROM a")
    b, _ = _fonte(monkeypatch, [{"id": 1}], query="SELECT id FROM b")
    assert a.ref != b.ref


def test_ref_e_load_sao_UMA_consulta(monkeypatch):
    """Como o `ArquivoSource` memoiza os bytes: o `ref` nomeia exatamente as
    linhas que viraram trabalho, e o banco não é consultado duas vezes."""
    fonte, conexoes = _fonte(monkeypatch, [{"id": 1}])
    fonte.ref
    fonte.load()
    assert len(conexoes) == 1


def test_erro_do_driver_e_REDUZIDO_a_classe_e_a_mensagem_inteira_vai_ao_log(monkeypatch, caplog):
    """`OperationalError` ecoa host e usuário. A resposta ao cliente leva só a
    classe; o log do servidor leva tudo — é o lugar designado."""

    class OperationalError(Exception):
        pass

    fonte, _ = _fonte(monkeypatch, [], erro=OperationalError(f"could not connect to {SENTINELA}"))
    with caplog.at_level(logging.ERROR, logger="orchestrator.sources"):
        with pytest.raises(FonteFalhou) as erro:
            fonte.load()
    assert str(erro.value) == "consulta falhou: OperationalError"
    assert "SEGREDO-4F2A" not in str(erro.value)
    assert any("SEGREDO-4F2A" in r.getMessage() for r in caplog.records)


def test_a_fonte_nao_IMPRIME_nada(monkeypatch, capsys):
    fonte, _ = _fonte(monkeypatch, [{"id": 1}])
    fonte.load()
    saida = capsys.readouterr()
    assert saida.out == "" and saida.err == ""


def test_campo_id_ausente_numa_linha_e_erro_ALTO_com_a_linha(monkeypatch):
    fonte, _ = _fonte(monkeypatch, [{"id": 1}, {"titulo": "sem id"}])
    with pytest.raises(FonteFalhou, match="linha 2"):
        fonte.load()


def test_teto_de_linhas_recusa_com_motivo(monkeypatch):
    linhas = [{"id": i} for i in range(6)]
    monkeypatch.setenv("ERP_DSN", SENTINELA)
    fonte = PostgresSource(
        dsn_env="ERP_DSN", query="SELECT id FROM t", kind="k", campo_id="id",
        max_linhas=5, conectar=lambda dsn: _Conexao(linhas),
    )
    with pytest.raises(FonteFalhou, match="teto"):
        fonte.load()


def test_sem_o_extra_a_falha_e_ALTA_e_nomeia_o_extra(monkeypatch):
    """Sem `conectar` injetado, o default importa `psycopg` dentro do `load()`.
    Fingir que o módulo não existe é `sys.modules[nome] = None`: o import
    levanta ImportError, e a fonte tem que virar isso em algo legível."""
    monkeypatch.setenv("ERP_DSN", SENTINELA)
    monkeypatch.setitem(__import__("sys").modules, "psycopg", None)
    fonte = PostgresSource(dsn_env="ERP_DSN", query="SELECT 1", kind="k", campo_id="id")
    with pytest.raises(ExtraAusente, match=r"\[fontes\]"):
        fonte.load()


@pytest.mark.skipif(
    not __import__("os").environ.get("TESTE_PG_DSN"),
    reason="integração opcional: defina TESTE_PG_DSN com um Postgres de teste",
)
def test_integracao_OPCIONAL_com_um_postgres_de_verdade(monkeypatch):
    """Nunca exigido pelo CI. Para quem tiver um banco: prova que o default
    `_conectar_padrao` (psycopg em `dict_row`) devolve linhas-dict e que o
    `ref` sai. Um `SELECT` constante não precisa de tabela nenhuma."""
    monkeypatch.setenv("ERP_DSN", __import__("os").environ["TESTE_PG_DSN"])
    fonte = PostgresSource(
        dsn_env="ERP_DSN", query="SELECT 1 AS id, 'a' AS t", kind="k", campo_id="id"
    )
    pool = fonte.load()
    assert [i.id for i in pool.items] == ["1"]
    assert fonte.ref.startswith("pg:ERP_DSN/")
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/sources/test_postgres.py -q
```

Esperado: `ModuleNotFoundError: No module named 'orchestrator.sources.erros'`.

- [ ] **Step 3: A hierarquia de erros**

`src/orchestrator/sources/erros.py`:

```python
"""Os erros que uma fonte conectada levanta — e que a borda vira em 422.

Uma hierarquia própria, e não `ValueError` solto, por dois motivos. O primeiro
é a borda: `api/app.py::_ler` precisa distinguir "a fonte recusou, e a mensagem
é para o cliente" de "o servidor quebrou" — a primeira é 422 com o texto
inteiro, a segunda é 500. O segundo é o segredo: toda mensagem destas classes é
escrita para ser DEVOLVIDA ao cliente, então nenhuma delas pode carregar DSN,
token ou o que o driver ecoou. Quem constrói uma, reduz antes.
"""


class ErroDeFonte(ValueError):
    """Base. A mensagem é segura para devolver ao cliente."""


class VariavelAusente(ErroDeFonte):
    """A variável de ambiente que guardaria o segredo não existe no servidor.

    A mensagem cita o NOME — é a única coisa que o cliente pediu e a única que
    ele precisa para consertar.
    """

    def __init__(self, nome: str) -> None:
        self.nome = nome
        super().__init__(f"a variável de ambiente {nome!r} não existe no servidor")


class ExtraAusente(ErroDeFonte):
    """O driver do extra `[fontes]` não está instalado. Alto, não 500."""

    def __init__(self, pacote: str) -> None:
        super().__init__(
            f"a fonte precisa de {pacote!r}, que não está instalado: "
            f"instale o extra [fontes] (pip install '.[fontes]')"
        )


class FonteFalhou(ErroDeFonte):
    """A fonte recusou ou falhou, com mensagem já reduzida para o cliente."""
```

- [ ] **Step 4: A fonte**

`src/orchestrator/sources/postgres.py`:

```python
"""Uma query Postgres como pool de trabalho.

**Ler é fácil. Não escrever, não vazar e ter `ref` é o trabalho.** Três
compromissos, e cada um tem um teste que o prova:

1. A query é LEITURA: `SELECT` ou `WITH`, uma instrução só — conferido antes
   de conectar. A plataforma lê o banco do parceiro; escrever nele a partir
   de um campo de texto na tela não é uma feature, é um incidente.
2. O DSN é um NOME de variável de ambiente, lido no `load()`. Ele não entra no
   `ref`, na mensagem de erro, nem em nada que a fonte emita. O erro do driver
   — que ecoa host e usuário — é reduzido à classe; a mensagem inteira vai
   para o log do servidor, o lugar designado.
3. `ref` = `pg:<dsn_env>/<sha(query)>@<sha(linhas)>`. O hash das linhas é o
   que faz duas execuções sobre os mesmos dados casarem as decisões humanas
   já tomadas — e uma linha mudada mudar o `ref`.

A conexão é INJETÁVEL (`conectar`) para que os testes não abram socket: o
default importa `psycopg` dentro do `load()`, e é isso que torna o extra
`[fontes]` opcional para quem só usa arquivo.
"""

import hashlib
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.sources.erros import ExtraAusente, FonteFalhou, VariavelAusente

MAX_LINHAS_PADRAO = 5000
_LEITURA = ("SELECT", "WITH")
_log = logging.getLogger("orchestrator.sources")


def _guarda_select(query: str) -> str:
    """A primeira palavra é SELECT/WITH e há UMA instrução. Conservadora de
    propósito: um SELECT legítimo recusado é bug a corrigir; um DELETE que
    passasse seria um desastre. Um `;` final é tolerado; um no meio, não."""
    corpo = "\n".join(
        linha for linha in query.strip().splitlines() if not linha.lstrip().startswith("--")
    ).strip()
    sem_final = corpo.rstrip().rstrip(";").rstrip()
    if ";" in sem_final:
        raise FonteFalhou("a query precisa ser um SELECT só — há mais de uma instrução")
    primeira = sem_final.split(None, 1)[0].upper() if sem_final else ""
    if primeira not in _LEITURA:
        raise FonteFalhou(
            f"a query precisa ser um SELECT só (ou WITH … SELECT); começa com {primeira or 'nada'!r}"
        )
    return sem_final


def _conectar_padrao(dsn: str) -> Any:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as erro:
        raise ExtraAusente("psycopg") from erro
    return psycopg.connect(dsn, row_factory=dict_row)


@dataclass(frozen=True)
class PostgresSource:
    dsn_env: str
    query: str
    kind: str
    campo_id: str
    max_linhas: int = MAX_LINHAS_PADRAO
    # Injetável para os testes. `None` = o de verdade, importado no `load()`.
    conectar: Callable[[str], Any] | None = field(default=None, compare=False)
    # Memo das linhas: `ref` e `load()` são UMA consulta, como os bytes do
    # `ArquivoSource`. `compare=False` pelo mesmo motivo de lá — um frozen
    # dataclass não pode mudar de hash depois de ler.
    _linhas: tuple[dict, ...] | None = field(default=None, init=False, repr=False, compare=False)

    def _consultar(self) -> tuple[dict, ...]:
        if self._linhas is not None:
            return self._linhas
        query = _guarda_select(self.query)
        dsn = os.environ.get(self.dsn_env)
        if dsn is None:
            raise VariavelAusente(self.dsn_env)
        conectar = self.conectar or _conectar_padrao
        try:
            conexao = conectar(dsn)
        except ExtraAusente:
            raise
        except Exception as erro:
            # NUNCA `str(erro)`: o driver ecoa host e usuário. A classe vai ao
            # cliente; o texto inteiro, ao log do servidor.
            _log.error("fonte pg:%s — conexão falhou: %s", self.dsn_env, erro)
            raise FonteFalhou(f"conexão falhou: {type(erro).__name__}") from erro
        try:
            cursor = conexao.cursor()
            cursor.execute(query)
            linhas = tuple(dict(linha) for linha in cursor.fetchall())
        except Exception as erro:
            _log.error("fonte pg:%s — consulta falhou: %s", self.dsn_env, erro)
            raise FonteFalhou(f"consulta falhou: {type(erro).__name__}") from erro
        finally:
            conexao.close()
        object.__setattr__(self, "_linhas", linhas)
        return linhas

    @property
    def ref(self) -> str:
        linhas = self._consultar()
        q = hashlib.sha256(self.query.encode("utf-8")).hexdigest()[:12]
        canonico = json.dumps(linhas, sort_keys=True, default=str, ensure_ascii=False)
        d = hashlib.sha256(canonico.encode("utf-8")).hexdigest()
        return f"pg:{self.dsn_env}/{q}@{d}"

    def load(self) -> WorkSet:
        linhas = self._consultar()
        if len(linhas) > self.max_linhas:
            raise FonteFalhou(
                f"a query devolveu {len(linhas)} linhas, acima do teto de {self.max_linhas}"
            )
        itens = []
        for i, linha in enumerate(linhas, start=1):
            valor = linha.get(self.campo_id)
            if valor is None or (isinstance(valor, str) and valor.strip() == ""):
                raise FonteFalhou(
                    f"linha {i} não tem o campo_id {self.campo_id!r} (ou ele está vazio). "
                    f"colunas: {sorted(linha)}"
                )
            itens.append(WorkItem(id=str(valor), kind=self.kind, payload=linha))
        return WorkSet(items=tuple(itens))
```

- [ ] **Step 5: O extra**

Em `pyproject.toml`, logo abaixo da linha `api = [...]`:

```toml
# Fontes CONECTADAS: banco por DSN e API com token. Importados DENTRO do
# `load()` — sem o extra a API sobe e a fonte devolve 422 nomeando-o.
fontes = ["psycopg[binary]>=3.1", "httpx>=0.27"]
```

Não instale o extra na venv para rodar os testes — eles injetam a conexão. (Instalar é o que o dono faz quando tiver um banco.)

- [ ] **Step 6: Rodar, suíte, lint, commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/sources/test_postgres.py -q
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m ruff check .
git add src/orchestrator/sources/erros.py src/orchestrator/sources/postgres.py pyproject.toml tests/sources/test_postgres.py
git commit -m "feat(sources): PostgresSource — so leitura, segredo por nome, ref por hash de query e linhas"
```

Esperado: os novos passam; `tests/arquitetura` continua verde (`sources` importa só `kernel`).

---

### Task 2: `HttpSource`

**Files:**
- Create: `src/orchestrator/sources/http.py`
- Test: `tests/sources/test_http.py`

**Interfaces:**
- Consumes: `ErroDeFonte`, `VariavelAusente`, `ExtraAusente`, `FonteFalhou` (Task 1).
- Produces: `HttpSource(url, token_env, kind, campo_id, caminho="", max_linhas=5000, transporte=None)` com `.ref` e `.load()`. `transporte` é um `httpx.BaseTransport` (nos testes, `httpx.MockTransport`).

- [ ] **Step 1: Os testes que falham**

`tests/sources/test_http.py`:

```python
"""A fonte HTTP: uma página, com token por nome, e o servidor não vira proxy."""

import json

import httpx
import pytest

from orchestrator.sources.erros import ExtraAusente, FonteFalhou, VariavelAusente
from orchestrator.sources.http import HttpSource

TOKEN = "SEGREDO-4F2A"


def _fonte(monkeypatch, responder, *, url="https://api.exemplo/issues", token="CRM_TOKEN", caminho="", env=TOKEN):
    """`MockTransport` responde sem rede; `pedidos` guarda o que saiu para que
    o teste veja o cabeçalho de autorização e conte as requisições."""
    if env is not None:
        monkeypatch.setenv("CRM_TOKEN", env)
    else:
        monkeypatch.delenv("CRM_TOKEN", raising=False)
    pedidos = []

    def handler(pedido):
        pedidos.append(pedido)
        return responder(pedido)

    fonte = HttpSource(
        url=url, token_env=token, kind="issue", campo_id="id", caminho=caminho,
        transporte=httpx.MockTransport(handler),
    )
    return fonte, pedidos


def _lista(itens, **cabecalhos):
    return lambda pedido: httpx.Response(200, json=itens, headers=cabecalhos)


def test_a_lista_do_corpo_vira_pool(monkeypatch):
    fonte, pedidos = _fonte(monkeypatch, _lista([{"id": 7, "titulo": "trava"}]))
    pool = fonte.load()
    assert [i.id for i in pool.items] == ["7"]
    assert pool.items[0].payload == {"id": 7, "titulo": "trava"}
    assert pedidos[0].headers["Authorization"] == f"Bearer {TOKEN}"


def test_caminho_aponta_a_lista_dentro_do_corpo(monkeypatch):
    fonte, _ = _fonte(
        monkeypatch, lambda p: httpx.Response(200, json={"dados": {"itens": [{"id": 1}]}}),
        caminho="dados.itens",
    )
    assert [i.id for i in fonte.load().items] == ["1"]


def test_sem_token_env_nao_manda_Authorization(monkeypatch):
    fonte, pedidos = _fonte(monkeypatch, _lista([{"id": 1}]), token=None)
    fonte.load()
    assert "Authorization" not in pedidos[0].headers


def test_variavel_ausente_e_erro_que_cita_o_NOME_e_nao_faz_requisicao(monkeypatch):
    fonte, pedidos = _fonte(monkeypatch, _lista([{"id": 1}]), env=None)
    with pytest.raises(VariavelAusente, match="CRM_TOKEN"):
        fonte.load()
    assert pedidos == []


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/x", "http://127.0.0.1/x", "http://127.9.9.9/x",
        "http://[::1]/x", "http://169.254.1.1/x", "ftp://api.exemplo/x", "api.exemplo/x",
    ],
)
def test_loopback_link_local_e_esquema_estranho_sao_recusados_SEM_requisicao(monkeypatch, url):
    """O servidor passa a fazer requisições para URLs que vêm da tela. Recusar
    o que só o servidor alcança é o mínimo — e é recusado ANTES de sair."""
    fonte, pedidos = _fonte(monkeypatch, _lista([{"id": 1}]), url=url)
    with pytest.raises(FonteFalhou):
        fonte.load()
    assert pedidos == []


def test_status_nao_2xx_e_erro_com_status_e_url_e_NUNCA_o_token(monkeypatch):
    fonte, _ = _fonte(monkeypatch, lambda p: httpx.Response(401, text=f"bad token {TOKEN}"))
    with pytest.raises(FonteFalhou) as erro:
        fonte.load()
    assert "401" in str(erro.value) and "https://api.exemplo/issues" in str(erro.value)
    assert TOKEN not in str(erro.value)


def test_corpo_que_nao_e_lista_e_recusado_dizendo_o_que_veio(monkeypatch):
    fonte, _ = _fonte(monkeypatch, lambda p: httpx.Response(200, json={"ok": True}))
    with pytest.raises(FonteFalhou, match="lista"):
        fonte.load()


def test_o_ref_usa_o_ETAG_quando_ha(monkeypatch):
    fonte, _ = _fonte(monkeypatch, _lista([{"id": 1}], ETag='"v7"'))
    assert fonte.ref == 'http:https://api.exemplo/issues@"v7"'


def test_sem_etag_o_ref_e_o_hash_do_corpo_e_e_ESTAVEL(monkeypatch):
    a, _ = _fonte(monkeypatch, _lista([{"id": 1}]))
    b, _ = _fonte(monkeypatch, _lista([{"id": 1}]))
    c, _ = _fonte(monkeypatch, _lista([{"id": 2}]))
    assert a.ref == b.ref and a.ref != c.ref
    assert a.ref.startswith("http:https://api.exemplo/issues@")
    assert TOKEN not in a.ref


def test_ref_e_load_sao_UMA_requisicao(monkeypatch):
    fonte, pedidos = _fonte(monkeypatch, _lista([{"id": 1}]))
    fonte.ref
    fonte.load()
    assert len(pedidos) == 1


def test_erro_de_transporte_e_reduzido_a_classe(monkeypatch):
    def handler(p):
        raise httpx.ConnectError("boom to https://x with " + TOKEN)

    fonte, _ = _fonte(monkeypatch, handler)
    with pytest.raises(FonteFalhou) as erro:
        fonte.load()
    assert str(erro.value) == "requisição falhou: ConnectError"


def test_sem_o_extra_a_falha_e_ALTA(monkeypatch):
    monkeypatch.setenv("CRM_TOKEN", TOKEN)
    monkeypatch.setitem(__import__("sys").modules, "httpx", None)
    fonte = HttpSource(url="https://api.exemplo/x", token_env="CRM_TOKEN", kind="k", campo_id="id")
    with pytest.raises(ExtraAusente, match=r"\[fontes\]"):
        fonte.load()
```

O último teste zera `httpx` em `sys.modules` — o próprio arquivo o importou no topo, e isso é esperado: o que se testa é o import DENTRO de `_transporte_padrao`, que lê `sys.modules` de novo. Se pytest reclamar do estado do módulo, faça o teste importar `httpx` só dentro de `_fonte` — não relaxe a asserção.

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/sources/test_http.py -q
```

Esperado: `ModuleNotFoundError: No module named 'orchestrator.sources.http'`.

- [ ] **Step 3: A fonte**

`src/orchestrator/sources/http.py`:

```python
"""Uma API HTTP como pool de trabalho — uma página, com token por nome.

Fecha o R7 que o spec de agentes-rodando adiou: `ref` = `http:<url>@<etag>`
quando o servidor manda ETag, senão `@<sha256 do corpo>`. Paginação e cursor
ficam FORA (o `ref` de várias páginas é desenho próprio) e estão escritos
como fora no spec.

**O servidor passa a fazer requisições para URLs que vêm da tela.** Recusar
loopback e link-local antes de qualquer requisição é o mínimo contra usar a
plataforma para alcançar o que só o servidor alcança. A guarda olha o HOST
literal: um nome DNS que resolva para loopback não é pego — isso exige
resolver o nome, e está dito em voz alta em vez de fingido.

O token é um NOME de variável; o cabeçalho de autorização não entra em `ref`,
mensagem de erro nem log. O transporte é INJETÁVEL (`httpx.MockTransport`
nos testes); o default importa `httpx` dentro do `load()`.
"""

import hashlib
import ipaddress
import logging
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.sources.erros import ExtraAusente, FonteFalhou, VariavelAusente

MAX_LINHAS_PADRAO = 5000
_log = logging.getLogger("orchestrator.sources")


def _guarda_url(url: str) -> None:
    partes = urlsplit(url)
    if partes.scheme not in ("http", "https") or not partes.hostname:
        raise FonteFalhou(f"a url precisa ser http(s) com host: {url!r}")
    host = partes.hostname
    if host == "localhost":
        raise FonteFalhou("url de loopback recusada: o servidor não faz requisição a si mesmo")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return  # nome DNS: aceito (ver o cabeçalho sobre o limite)
    if ip.is_loopback or ip.is_link_local:
        raise FonteFalhou(f"url de loopback/link-local recusada: {host}")


def _transporte_padrao() -> Any:
    try:
        import httpx
    except ImportError as erro:
        raise ExtraAusente("httpx") from erro
    return httpx.HTTPTransport()


def _seguir(corpo: Any, caminho: str) -> Any:
    for chave in (c for c in caminho.split(".") if c):
        if not isinstance(corpo, dict) or chave not in corpo:
            raise FonteFalhou(f"o caminho {caminho!r} não leva a uma lista: parou em {chave!r}")
        corpo = corpo[chave]
    return corpo


@dataclass(frozen=True)
class HttpSource:
    url: str
    token_env: str | None
    kind: str
    campo_id: str
    caminho: str = ""
    max_linhas: int = MAX_LINHAS_PADRAO
    transporte: Any = field(default=None, compare=False)
    _resposta: tuple[str | None, bytes] | None = field(
        default=None, init=False, repr=False, compare=False
    )  # (etag, corpo) — memo: ref e load são UMA requisição

    def _buscar(self) -> tuple[str | None, bytes]:
        if self._resposta is not None:
            return self._resposta
        _guarda_url(self.url)
        cabecalhos = {}
        if self.token_env is not None:
            token = os.environ.get(self.token_env)
            if token is None:
                raise VariavelAusente(self.token_env)
            cabecalhos["Authorization"] = f"Bearer {token}"
        try:
            import httpx
        except ImportError as erro:
            raise ExtraAusente("httpx") from erro
        transporte = self.transporte or _transporte_padrao()
        try:
            with httpx.Client(transport=transporte, timeout=30.0) as cliente:
                resposta = cliente.get(self.url, headers=cabecalhos)
        except Exception as erro:
            _log.error("fonte http:%s — requisição falhou: %s", self.url, erro)
            raise FonteFalhou(f"requisição falhou: {type(erro).__name__}") from erro
        if not 200 <= resposta.status_code < 300:
            # Só status e URL. O corpo pode ecoar o token; a mensagem, nunca.
            raise FonteFalhou(f"GET {self.url} devolveu {resposta.status_code}")
        memo = (resposta.headers.get("ETag"), resposta.content)
        object.__setattr__(self, "_resposta", memo)
        return memo

    @property
    def ref(self) -> str:
        etag, corpo = self._buscar()
        marca = etag if etag else hashlib.sha256(corpo).hexdigest()
        return f"http:{self.url}@{marca}"

    def load(self) -> WorkSet:
        import json

        _, corpo = self._buscar()
        try:
            dados = json.loads(corpo)
        except ValueError as erro:
            raise FonteFalhou("a resposta não é JSON") from erro
        lista = _seguir(dados, self.caminho)
        if not isinstance(lista, list):
            raise FonteFalhou(
                f"a resposta precisa ser uma LISTA de objetos, e veio {type(lista).__name__}"
            )
        if len(lista) > self.max_linhas:
            raise FonteFalhou(f"a resposta tem {len(lista)} itens, acima do teto de {self.max_linhas}")
        itens = []
        for i, obj in enumerate(lista, start=1):
            if not isinstance(obj, dict):
                raise FonteFalhou(f"item {i} não é um objeto: {type(obj).__name__}")
            valor = obj.get(self.campo_id)
            if valor is None or (isinstance(valor, str) and valor.strip() == ""):
                raise FonteFalhou(
                    f"item {i} não tem o campo_id {self.campo_id!r} (ou ele está vazio). "
                    f"campos: {sorted(obj)}"
                )
            itens.append(WorkItem(id=str(valor), kind=self.kind, payload=obj))
        return WorkSet(items=tuple(itens))
```

- [ ] **Step 4: Rodar, suíte, lint, commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/sources/test_http.py -q
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m ruff check .
git add src/orchestrator/sources/http.py tests/sources/test_http.py
git commit -m "feat(sources): HttpSource — uma pagina com token por nome, ref por etag ou corpo, loopback recusado"
```

---

### Task 3: A borda — `FontePostgres`, `FonteHttp`, e os erros viram 422

**Files:**
- Modify: `src/orchestrator/api/schemas.py` (ao lado de `FonteArquivo`; a união em `RunRequest.fonte`)
- Modify: `src/orchestrator/api/app.py` (`_fonte_de`, `_ler`, imports)
- Test: `tests/api/test_execucao.py`, `tests/review/test_fila.py`

**Interfaces:**
- Consumes: `PostgresSource`, `HttpSource`, `ErroDeFonte` (Tasks 1–2); `_csv_de_issues`, `_cliente_falso`, `_resposta` de `tests/api/test_execucao.py`.
- Produces: `FontePostgres(tipo="postgres", dsn_env, query, kind, campo_id)`, `FonteHttp(tipo="http", url, token_env=None, kind, campo_id, caminho="")`.

- [ ] **Step 1: Os testes que falham**

Em `tests/api/test_execucao.py`, ao lado de `test_um_CSV_de_issues_roda_no_TRIADOR_composto_pela_WEB`:

```python
def _issues_http(monkeypatch, itens):
    """Transporte falso injetado no MÓDULO: a fonte que `_fonte_de` constrói
    não recebe `transporte`, então o default `_transporte_padrao` é o que se
    troca. Nenhum socket."""
    import httpx

    import orchestrator.sources.http as mod

    def handler(pedido):
        return httpx.Response(200, json=itens, headers={"ETag": '"v1"'})

    monkeypatch.setattr(mod, "_transporte_padrao", lambda: httpx.MockTransport(handler))
    monkeypatch.setenv("CRM_TOKEN", "SEGREDO-4F2A")


def _issues_pg(monkeypatch, linhas):
    import orchestrator.sources.postgres as mod

    class _Cursor:
        def execute(self, q): ...
        def fetchall(self): return list(linhas)

    class _Conexao:
        def cursor(self): return _Cursor()
        def close(self): ...

    monkeypatch.setattr(mod, "_conectar_padrao", lambda dsn: _Conexao())
    monkeypatch.setenv("ERP_DSN", "postgresql://u:SEGREDO-4F2A@h/db")


_ISSUES = [{"id": i, "titulo": f"titulo {i}", "corpo": f"corpo {i}"} for i in (1, 2, 3)]


@pytest.mark.parametrize(
    "fonte, preparar",
    [
        ({"tipo": "http", "url": "https://api.exemplo/issues", "token_env": "CRM_TOKEN",
          "kind": "issue", "campo_id": "id"}, _issues_http),
        ({"tipo": "postgres", "dsn_env": "ERP_DSN", "query": "SELECT id, titulo, corpo FROM issues",
          "kind": "issue", "campo_id": "id"}, _issues_pg),
    ],
    ids=["http", "postgres"],
)
def test_uma_fonte_CONECTADA_roda_no_triador_pela_borda(tmp_path, monkeypatch, fonte, preparar):
    """O mesmo fim-a-fim do arquivo, pelas duas fontes novas: nada na borda
    muda, e é isso que o teste prova."""
    import orchestrator.api.app as api_app

    monkeypatch.setattr(api_app, "_RAIZ_RECEITAS", tmp_path / "receitas")
    preparar(monkeypatch, _ISSUES)
    fake = _cliente_falso(monkeypatch, [_resposta()] * 3)
    criada = cliente.post("/api/receitas", json={
        "id": "triagem-conectada", "nome": "T", "justificativa": "j",
        "resolvers": [{"nome": "triador"}]})
    assert criada.status_code == 201, criada.text

    r = cliente.post("/api/workflows/triagem-conectada/runs",
                     json={"fonte": fonte, "teto_microcents": 10_000_000})

    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["itens"] == 3 and len(fake.chamadas) == 3
    assert corpo["propostas_por_tipo"] == {"BUG": 3} and corpo["falhas"] == 0
    assert corpo["contra_gabarito"] is None
    assert corpo["input_ref"].startswith(("http:", "pg:"))
    assert "SEGREDO-4F2A" not in r.text


def test_variavel_de_ambiente_ausente_e_422_com_o_NOME(monkeypatch):
    monkeypatch.delenv("ERP_DSN", raising=False)
    r = cliente.post("/api/workflows/conciliacao/runs", json={"fonte": {
        "tipo": "postgres", "dsn_env": "ERP_DSN", "query": "SELECT 1", "kind": "banco", "campo_id": "id"}})
    assert r.status_code == 422, r.text
    assert "ERP_DSN" in r.json()["detail"]


def test_query_de_escrita_e_422_antes_de_conectar(monkeypatch):
    monkeypatch.setenv("ERP_DSN", "postgresql://u:SEGREDO-4F2A@h/db")
    import orchestrator.sources.postgres as mod

    def _nao_deveria_conectar(dsn):
        raise AssertionError("a guarda de SELECT deixou conectar")

    monkeypatch.setattr(mod, "_conectar_padrao", _nao_deveria_conectar)
    r = cliente.post("/api/workflows/conciliacao/runs", json={"fonte": {
        "tipo": "postgres", "dsn_env": "ERP_DSN", "query": "DELETE FROM x", "kind": "banco", "campo_id": "id"}})
    assert r.status_code == 422 and "SELECT" in r.json()["detail"]
    assert "SEGREDO" not in r.text


def test_sem_o_extra_fontes_e_422_e_nao_500(monkeypatch):
    monkeypatch.setenv("CRM_TOKEN", "x")
    monkeypatch.setitem(__import__("sys").modules, "httpx", None)
    r = cliente.post("/api/workflows/conciliacao/runs", json={"fonte": {
        "tipo": "http", "url": "https://api.exemplo/x", "token_env": "CRM_TOKEN", "kind": "banco", "campo_id": "id"}})
    assert r.status_code == 422 and "[fontes]" in r.json()["detail"]


def test_a_forma_antiga_sem_tipo_conhecido_continua_422(monkeypatch):
    r = cliente.post("/api/workflows/conciliacao/runs", json={"fonte": {"tipo": "mysql", "x": 1}})
    assert r.status_code == 422
```

`_issues_http` e `_issues_pg` usam `kind="issue"` para a receita do `triador`; os testes de erro usam a `conciliacao` embutida porque a falha acontece em `_ler`, antes de qualquer guarda de kind.

Em `tests/review/test_fila.py`, ao lado de `test_a_chave_da_fila_sintetica_nao_mudou`:

```python
@pytest.mark.parametrize(
    "ref", ["pg:ERP_DSN/abc123def456@" + "f" * 64, 'http:https://api.exemplo/issues?x=1@"v7"']
)
def test_a_chave_de_uma_fonte_conectada_e_nome_de_arquivo_e_leva_o_esquema(ref):
    chave = dataset_de_ref(ref)
    assert chave.startswith(("pg-", "http-"))
    assert not any(c in chave for c in "/\\:@?\"")
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/api/test_execucao.py -q -k "CONECTADA or NOME or escrita or extra_fontes or forma_antiga"
./.venv/Scripts/python.exe -m pytest tests/review/test_fila.py -q -k conectada
```

Esperado: 422 de validação do pydantic (`tipo` desconhecido) nos primeiros; o de `test_fila` pode já passar — `dataset_de_ref` é genérico — e nesse caso fica como guarda.

- [ ] **Step 3: Os schemas**

Em `src/orchestrator/api/schemas.py`, logo depois de `FonteArquivo`:

```python
class FontePostgres(BaseModel):
    """Uma query num Postgres do parceiro. `dsn_env` é o NOME da variável de
    ambiente do servidor que guarda o DSN — o valor nunca passa por aqui."""

    model_config = ConfigDict(extra="forbid")

    tipo: Literal["postgres"]
    dsn_env: str = Field(min_length=1)
    query: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    campo_id: str = Field(min_length=1)


class FonteHttp(BaseModel):
    """Uma página de uma API JSON. `token_env` é o NOME da variável com o
    token; `None` é uma API sem autenticação. `caminho` aponta a lista dentro
    do corpo (`dados.itens`); vazio = o corpo é a lista."""

    model_config = ConfigDict(extra="forbid")

    tipo: Literal["http"]
    url: str = Field(min_length=1)
    token_env: str | None = None
    kind: str = Field(min_length=1)
    campo_id: str = Field(min_length=1)
    caminho: str = ""
```

E em `RunRequest`:

```python
    fonte: FonteSintetica | FonteArquivo | FontePostgres | FonteHttp = Field(
        default_factory=FonteSintetica, discriminator="tipo"
    )
```

- [ ] **Step 4: A borda**

Em `src/orchestrator/api/app.py`, imports:

```python
from orchestrator.sources.arquivo import ArquivoSource, RaizViolada
from orchestrator.sources.erros import ErroDeFonte
from orchestrator.sources.http import HttpSource
from orchestrator.sources.postgres import PostgresSource
```

`_fonte_de` ganha os dois ramos antes do `try` do arquivo (a anotação de retorno vira `tuple[SyntheticSource | ArquivoSource | PostgresSource | HttpSource, Dataset | None]`):

```python
    if f.tipo == "postgres":
        return PostgresSource(dsn_env=f.dsn_env, query=f.query, kind=f.kind, campo_id=f.campo_id), None
    if f.tipo == "http":
        return (
            HttpSource(url=f.url, token_env=f.token_env, kind=f.kind, campo_id=f.campo_id, caminho=f.caminho),
            None,
        )
```

`_ler` (mesma anotação ampliada): a cláusula `except` passa a tratar `ErroDeFonte` **primeiro** — a mensagem já é segura —, e o `raise` para "não é arquivo" vale só para o que sobrar:

```python
    try:
        return fonte.ref, fonte.load()
    except ErroDeFonte as erro:
        # Toda mensagem desta hierarquia foi escrita para o cliente: sem DSN,
        # sem token, sem o que o driver ecoou. Ver `sources/erros.py`.
        raise HTTPException(status_code=422, detail=str(erro)) from erro
    except (OSError, ValueError) as erro:
        if pedido.fonte.tipo != "arquivo":
            raise
        ...  # o corpo existente do arquivo, sem mudança
```

- [ ] **Step 5: Rodar, suíte (com e sem chave de lixo), lint, commit**

```bash
./.venv/Scripts/python.exe -m pytest -q
ANTHROPIC_API_KEY=lixo ./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m ruff check .
git add src/orchestrator/api/schemas.py src/orchestrator/api/app.py tests/api/test_execucao.py tests/review/test_fila.py
git commit -m "feat(api): fonte postgres e http no pedido — a borda nao muda, e os erros das fontes viram 422"
```

---

### Task 4: A tela de execução

**Files:**
- Modify: `web-app/src/api.ts` (`FontePedido`)
- Modify: `web-app/src/Execucao.tsx` (estado, seletor, campos, construção da `fonte`)
- Modify: `web/assets/*`, `web/index.html` (bundle rebuildado)
- Test: `tests/api/test_compor.py`

**Interfaces:**
- Consumes: `FontePostgres`/`FonteHttp` (Task 3) — a união de `FontePedido` os espelha.

- [ ] **Step 1: As asserções de bundle que falham**

Em `tests/api/test_compor.py`, ao lado das outras de `_bundle()`:

```python
def test_a_tela_de_execucao_oferece_postgres_e_api_http():
    js = _bundle()
    assert "postgres (sem gabarito)" in js
    assert "api http (sem gabarito)" in js
    assert "nome da variável de ambiente no servidor" in js


def test_a_tela_de_execucao_NAO_tem_campo_de_senha():
    """O segredo é um NOME. Um `type=\"password\"` ensinaria a pessoa a colar o
    valor — e é a única forma de um segredo entrar pela tela."""
    js = _bundle()
    assert 'type:"password"' not in js and 'type="password"' not in js
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/api/test_compor.py -q -k "postgres_e_api or campo_de_senha"
```

Esperado: o primeiro falha contra o bundle atual; o segundo pode já passar (fica como guarda).

- [ ] **Step 3: `api.ts`**

```ts
export type FontePedido =
  | { tipo: "sintetica"; seed: number; n: number; taxa_divergencia: number }
  | { tipo: "arquivo"; caminho: string; kind: string; campo_id: string }
  | { tipo: "postgres"; dsn_env: string; query: string; kind: string; campo_id: string }
  | { tipo: "http"; url: string; token_env: string | null; kind: string; campo_id: string; caminho: string };
```

- [ ] **Step 4: `Execucao.tsx`**

O estado (`~:89–95`):

```tsx
type FonteTipo = "sintetica" | "arquivo" | "postgres" | "http";
const [fonteTipo, setFonteTipo] = useState<FonteTipo>("sintetica");
// postgres
const [dsnEnv, setDsnEnv] = useState("");
const [query, setQuery] = useState("");
// http
const [url, setUrl] = useState("");
const [tokenEnv, setTokenEnv] = useState("");
const [caminhoJson, setCaminhoJson] = useState("");
```

A construção da `fonte` (`~:164`):

```tsx
const fonte: FontePedido =
  fonteTipo === "sintetica"
    ? { tipo: "sintetica", seed, n, taxa_divergencia: taxaDivergencia }
    : fonteTipo === "arquivo"
      ? { tipo: "arquivo", caminho, kind, campo_id: campoId }
      : fonteTipo === "postgres"
        ? { tipo: "postgres", dsn_env: dsnEnv, query, kind, campo_id: campoId }
        // `token_env` vazio vira null: API sem autenticação. Não é fallback —
        // é o que o campo opcional significa, e o servidor não inventa nada.
        : { tipo: "http", url, token_env: tokenEnv.trim() === "" ? null : tokenEnv, kind, campo_id: campoId, caminho: caminhoJson };
```

O seletor (`~:273`) ganha as duas opções e o `onChange` usa `FonteTipo`:

```tsx
<option value="sintetica">sintética (com gabarito)</option>
<option value="arquivo">arquivo (sem gabarito)</option>
<option value="postgres">postgres (sem gabarito)</option>
<option value="http">api http (sem gabarito)</option>
```

Os campos por tipo, no lugar do ternário `fonteTipo === "sintetica" ? … : …` (`~:283`) — mantendo `kind` e `campo id` para todo tipo sem gabarito:

```tsx
{fonteTipo === "sintetica" ? (
  /* os três campos de hoje, sem mudança */
) : (
  <>
    {fonteTipo === "arquivo" && (
      <CampoTexto rotulo="caminho" valor={caminho} definir={setCaminho} />
    )}
    {fonteTipo === "postgres" && (
      <>
        <CampoTexto rotulo="variável do DSN" valor={dsnEnv} definir={setDsnEnv}
          dica="nome da variável de ambiente no servidor — ex.: ERP_DSN" />
        <label className="grid gap-1 text-[11.5px]">
          <span>query <span className="text-neutral-500 dark:text-noite-fraca">(só SELECT)</span></span>
          <textarea value={query} onChange={(e) => setQuery(e.target.value)} rows={3}
            className="rounded border border-borda bg-white px-2 py-1 font-mono text-[12px] dark:border-noite-borda dark:bg-noite-fundo" />
        </label>
      </>
    )}
    {fonteTipo === "http" && (
      <>
        <CampoTexto rotulo="url" valor={url} definir={setUrl} />
        <CampoTexto rotulo="variável do token" valor={tokenEnv} definir={setTokenEnv}
          dica="nome da variável de ambiente no servidor — vazio para API sem autenticação" />
        <CampoTexto rotulo="caminho na resposta" valor={caminhoJson} definir={setCaminhoJson}
          dica="deixe vazio se o corpo já é a lista" />
      </>
    )}
    <CampoTexto rotulo="kind" valor={kind} definir={setKind} />
    <CampoTexto rotulo="campo id" valor={campoId} definir={setCampoId} />
  </>
)}
```

Se `CampoTexto` não aceitar `dica`, acrescente a prop (um `<span>` abaixo do input, com as classes de texto fraco que o arquivo já usa) — **nunca** `type="password"`. Use só tokens de tema existentes no arquivo (`border-borda`, `dark:border-noite-borda`, `dark:bg-noite-fundo`, `dark:text-noite-fraca`); confira os nomes contra os que já aparecem em `Execucao.tsx`.

- [ ] **Step 5: Typecheck, build, bundle, testes**

```bash
cd web-app && npx tsc --noEmit && npm run build && cd ..
git status --porcelain web/
./.venv/Scripts/python.exe -m pytest tests/api/test_compor.py -q
```

- [ ] **Step 6: O gate do navegador — SEM chave, SEM banco**

Servidor via `.claude/launch.json` (`canvas`, 8111), com `ANTHROPIC_API_KEY` ausente (`/api/ambiente` → `tem_chave: false`) e **sem** definir `ERP_DSN`/`CRM_TOKEN`. Na tela de execução: os quatro tipos no seletor; escolha `postgres`, preencha `variável do DSN = ERP_DSN`, uma query `SELECT 1`, `kind`, `campo id`, rode → **422 citando `ERP_DSN`** renderizado onde os outros erros aparecem. Idem `api http` com `CRM_TOKEN`. Nenhum campo de senha. Light e dark. `read_page` da árvore inteira vale como prova quando o screenshot não desenha; anote no relatório o que viu por pixel e o que viu por árvore.

- [ ] **Step 7: Suíte, lint, commit (com o bundle)**

```bash
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m ruff check .
git add web-app/src web/ tests/api/test_compor.py
git commit -m "feat(web): postgres e api http na tela de execucao — o segredo e um NOME, nunca um campo de senha"
```

---

### Task 5: Os textos

**Files:**
- Modify: `README.md` (o item "**Executa qualquer workflow do `registry()`…**", ~linha 146)
- Modify: `docs/superpowers/DECISOES.md` (nova entrada, depois de `### P9.1`)

- [ ] **Step 1: README**

No item que hoje diz *"`fonte` (`sintetica` ou `arquivo` CSV/JSON sob `data/entradas/`)"* e *"O que ainda NÃO existe: fonte HTTP (§8 do spec da plataforma), upload de arquivo…"*, substitua por:

```markdown
- **Executa qualquer workflow do `registry()` — embutido, receita ou composição
  do canvas — sobre a fonte que o pedido nomeia.** `POST /api/workflows/{id}/runs`
  recebe `fonte` — `sintetica`, `arquivo` (CSV/JSON sob `data/entradas/`),
  `postgres` (query de LEITURA num DSN referenciado por nome de variável de
  ambiente) ou `http` (uma página JSON com token referenciado por nome) — e um
  `teto_microcents`, obrigatório quando a cascata tem agente. Nenhum segredo
  passa pela tela, pelo pedido persistido, pelo `ref` ou pela resposta: o
  servidor lê o valor do ambiente na hora e o erro do driver volta reduzido à
  classe. Uma fonte sem gabarito devolve `contra_gabarito: null`; uma cujos
  kinds nenhum bloco consome é recusada antes de rodar; pool vazio também. O
  que ainda NÃO existe: paginação/cursor no HTTP, query com parâmetros,
  outros bancos, "testar conexão", allowlist de hosts, upload de arquivo, e
  teto agregado/auth/rate limit em `/runs` — o teto é por requisição, por
  decisão do dono.
```

- [ ] **Step 2: `DECISOES.md`**

```markdown
### P9.2. Uma fonte conectada guarda o NOME do segredo, lê o valor na hora, e nunca o devolve

**Decisão.** `PostgresSource(dsn_env, …)` e `HttpSource(url, token_env, …)`
guardam o nome de uma variável de ambiente do servidor; o valor é lido no
`load()`, usado e descartado. Variável ausente é 422 com o nome. Erros do
driver voltam como `<classe>` (a mensagem inteira vai ao log do servidor).
A query é leitura (`SELECT`/`WITH`, uma instrução), conferida antes de
conectar; loopback e link-local são recusados antes de qualquer requisição.

**Por que nome e não valor.** A tela é o único lugar por onde um segredo
entraria — e entraria em composição, pedido persistido e `ref`, que são
gravados. O nome não é segredo; o ambiente do servidor já é onde a
`ANTHROPIC_API_KEY` mora. Um campo de senha na tela ensinaria a colar o
valor; por isso nenhum existe (pinado no bundle).

**Por que reduzir o erro do driver.** `OperationalError` do psycopg ecoa host
e usuário. A classe diz ao cliente o que aconteceu; o texto inteiro diz ao
operador — no log, que é dele.

**Por que a guarda de SELECT é conservadora.** A plataforma lê. Um SELECT
legítimo recusado é bug a corrigir; um DELETE que passasse seria um
incidente no banco do parceiro. Parâmetros entram quando houver caso.

**Por que loopback é recusado, e o que não é.** O servidor passa a fazer
requisições para URLs da tela. Recusar o que só o servidor alcança é o
mínimo; a guarda olha o host literal, e um nome DNS que resolva para
loopback não é pego — dito em voz alta, allowlist é decisão do operador.

**O que fica fora.** Paginação e cursor; outros bancos (a costura —
`conectar` injetável, `ref` por hash — está pronta); "testar conexão"; CLI.
```

- [ ] **Step 3: Suíte, lint, commit**

```bash
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m ruff check .
git add README.md docs/superpowers/DECISOES.md
git commit -m "docs: fontes conectadas no README e P9.2 — o segredo e um nome"
```

---

## Fora deste plano

- Paginação e cursor no HTTP; query com parâmetros; MySQL/SQL Server; "testar conexão"; allowlist de hosts; a CLI (`orch run`) com os tipos novos; upload de arquivo; teto agregado/auth/rate limit em `/runs`.
