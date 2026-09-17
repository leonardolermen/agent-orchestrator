# Agentes rodando — Plano 1 (R1–R6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer um agente composto na tela rodar de verdade — sobre um arquivo do usuário, pelo motor genérico, com teto de gasto e sem inventar taxa de acerto onde não há gabarito.

**Architecture:** O `/runs` deixa de chamar `reconcile(bank, ledger)` e passa a chamar `execute(definicao, fonte.load())`. A fonte vem no PEDIDO, como união discriminada — a sintética vira uma fonte entre outras, e `FonteArquivo` lê CSV/JSON sob uma raiz configurada, com `ref` por sha256 do conteúdo. A resposta ganha duas formas: `contra_gabarito` só existe quando a fonte tem gabarito, e é AUSENTE — nunca zero — quando não tem.

**Tech Stack:** Python 3.13, FastAPI (extra `[api]`), pydantic, dataclasses congelados, pytest, ruff. React 18 + Vite + Tailwind no front. Zero dependências novas — `csv` e `json` são da stdlib.

**Spec:** `docs/superpowers/specs/2026-09-18-agentes-rodando-design.md`

## Global Constraints

- **Ordem: R2 antes de R4 e R5.** Enquanto o `/runs` chamar `reconcile`, a fonte não tem quem a receba e o agente não tem quem o execute. Esta é a Task 3 e ela é o gargalo.
- **Nenhum teste chama API paga.** `FakeLLMClient`, `ClienteAusente` e `ClienteDeValidacao` são as costuras. Um teste que gaste é defeito, não cobertura.
- **`ClienteAusente` continua sendo o default de `construir`.** Desarmar a tranca continua sendo ato explícito de quem executa.
- **Sem gabarito, `contra_gabarito` é `None`** — nunca `0.0`. Este projeto já revogou duas conclusões por ler número pequeno como resultado (P6.81, P6.84).
- **`ref` estável ou não há replay:** hash do CONTEÚDO, nunca `mtime`, nunca `datetime.now()`.
- **Dinheiro e custo em inteiro de micro-centavos.** Ponto flutuante proibido.
- Código, comentários e docstrings em **português**. Docstring explica POR QUE, não O QUE.
- Configuração inválida falha alto; nunca fallback silencioso.
- Rodar: `./.venv/Scripts/python.exe -m pytest -q`. Lint: `./.venv/Scripts/python.exe -m ruff check src tests`. Front: `cd web-app && npx tsc --noEmit && npm run build` (o `--prefix` do npx NÃO typechecka), e commitar o bundle.

## Estrutura de arquivos

| Arquivo | Responsabilidade | Task |
|---|---|---|
| `src/orchestrator/api/schemas.py` | `FonteSintetica`/`FonteArquivo`, `RunRequest.fonte`, `RunJSON` em duas formas | 1, 3 |
| `src/orchestrator/sources/arquivo.py` **(novo)** | ler CSV/JSON → `WorkSet`, `ref` por sha256, raiz | 2 |
| `src/orchestrator/api/app.py` | `_executar` pelo motor genérico; teto; recusa sem chave | 3, 4 |
| `src/orchestrator/workflows.py` | `WorkflowContext.cliente` | 4 |
| `web-app/src/api.ts`, `Execucao.tsx` | escolher a fonte, ver custo, ver "sem gabarito" | 5 |

**Por que `sources/` e não `synth/`.** `synth/benchmark.py` é o gerador sintético; uma fonte de arquivo não tem nada a ver com geração. A camada nova importa só `kernel` (`WorkSet`, `WorkItem`), o que a mantém abaixo de `api` e fora do caminho de qualquer domínio — acrescente `"sources": frozenset({"kernel"})` à tabela de `tests/arquitetura/camadas.py` na Task 2.

---

### Task 1: A fonte vem no pedido

**Files:**
- Modify: `src/orchestrator/api/schemas.py`
- Test: `tests/api/test_execucao.py`

**Interfaces:**
- Consumes: nada
- Produces:
  - `FonteSintetica(tipo: Literal["sintetica"], seed, n, taxa_divergencia)`
  - `FonteArquivo(tipo: Literal["arquivo"], caminho: str, kind: str, campo_id: str)`
  - `RunRequest(fonte: FonteSintetica | FonteArquivo = FonteSintetica(), teto_microcents: int | None = None)`

**Nota de escopo.** Esta task só declara a forma do pedido. Quem a usa é a Task 3; até lá `_executar` continua lendo `seed`/`n`/`taxa` como hoje, através da fonte sintética.

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar a `tests/api/test_execucao.py`:

```python
def test_pedido_SEM_fonte_continua_valendo():
    """A compatibilidade que mantém o canvas, a CLI do grill e os testes de
    hoje sem edição. O default é a sintética com os mesmos números."""
    from orchestrator.api.schemas import RunRequest

    r = RunRequest()

    assert r.fonte.tipo == "sintetica"
    assert (r.fonte.seed, r.fonte.n, r.fonte.taxa_divergencia) == (1, 300, 0.15)
    assert r.teto_microcents is None


def test_a_fonte_e_uma_UNIAO_DISCRIMINADA_por_tipo():
    """Um objeto com `seed?` ao lado de `caminho?` aceitaria os cruzamentos que
    não significam nada — uma fonte sintética com caminho, um arquivo com
    semente. `tipo` é o que torna os quatro cruzamentos dois."""
    from orchestrator.api.schemas import RunRequest

    r = RunRequest.model_validate(
        {"fonte": {"tipo": "arquivo", "caminho": "issues.csv",
                   "kind": "issue", "campo_id": "numero"}}
    )

    assert r.fonte.tipo == "arquivo"
    assert r.fonte.caminho == "issues.csv"
    assert not hasattr(r.fonte, "seed")


def test_fonte_de_arquivo_EXIGE_kind_e_campo_id():
    """Nenhum dos dois é inferível. `kind` é o que liga um degrau ao outro no
    grafo, e `campo_id` é o que dá identidade ao item — adivinhar qualquer um
    seria conveniência com cara de defeito."""
    import pydantic

    from orchestrator.api.schemas import RunRequest

    with pytest.raises(pydantic.ValidationError):
        RunRequest.model_validate({"fonte": {"tipo": "arquivo", "caminho": "x.csv"}})


def test_teto_negativo_e_recusado_pelo_SCHEMA():
    """Fora do handler, como `taxa_divergencia` já é: o FastAPI devolve 422
    sozinho em vez de deixar a aritmética de orçamento levantar mais fundo."""
    import pydantic

    from orchestrator.api.schemas import RunRequest

    with pytest.raises(pydantic.ValidationError):
        RunRequest(teto_microcents=-1)
```

Acrescentar `import pytest` ao topo do arquivo se ainda não estiver lá.

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/api/test_execucao.py -q
```

Esperado: `AttributeError: 'RunRequest' object has no attribute 'fonte'`.

- [ ] **Step 3: Implementar**

Em `src/orchestrator/api/schemas.py`, substituir `RunRequest` por:

```python
class FonteSintetica(BaseModel):
    """O benchmark sintético, agora como UMA fonte entre outras.

    Os três campos eram o corpo inteiro de `RunRequest` — e era essa a forma
    de dizer "toda execução é um benchmark". Deixaram de ser o pedido e
    viraram os parâmetros de uma origem específica.
    """

    tipo: Literal["sintetica"] = "sintetica"
    seed: int = Field(default=1, ge=0)
    n: int = Field(default=300, ge=1, le=5000)
    taxa_divergencia: float = Field(default=0.15, ge=0.0, le=1.0)


class FonteArquivo(BaseModel):
    """Um arquivo do usuário — CSV ou JSON — como pool de trabalho.

    `kind` e `campo_id` são OBRIGATÓRIOS e não têm default, porque não existe
    coluna que diga o que um item é nem qual campo o identifica. Inferir do
    nome do arquivo ou da primeira coluna seria adivinhação, e o `kind` é o que
    liga um degrau ao outro no grafo.
    """

    tipo: Literal["arquivo"]
    caminho: str
    kind: str
    campo_id: str


class RunRequest(BaseModel):
    """O pedido de execução.

    `fonte` com default mantém todo chamador de hoje funcionando sem edição: um
    corpo vazio continua sendo o benchmark sintético com os mesmos números.
    """

    fonte: FonteSintetica | FonteArquivo = Field(
        default_factory=FonteSintetica, discriminator="tipo"
    )
    # Teto da EXECUÇÃO inteira, em micro-centavos. `None` = o teto do próprio
    # agente (`AgentSpec.budget_total_microcents`). NÃO existe valor que
    # signifique "sem teto", e a ausência dele é deliberada: um agente sem teto
    # é um agente que gasta até o fim da fila.
    teto_microcents: int | None = Field(default=None, ge=0)
```

Acrescentar `Literal` ao import de `typing` no topo do arquivo.

**Deixe `RunRequest.seed`/`n`/`taxa_divergencia` MORREREM aqui.** Os chamadores que os passavam soltos são atualizados na Task 3; até lá eles usam o default e continuam verdes porque os números são os mesmos.

- [ ] **Step 4: Rodar os testes**

```bash
./.venv/Scripts/python.exe -m pytest tests/api -q
```

Esperado: os quatro novos passam. Se algum teste antigo montar `RunRequest(seed=2)` diretamente, ele quebra — esse é escopo da Task 3; anote quais e siga.

- [ ] **Step 5: Suíte e lint**

```bash
./.venv/Scripts/python.exe -m pytest -q && ./.venv/Scripts/python.exe -m ruff check src tests
```

- [ ] **Step 6: Commit**

```bash
git add src/orchestrator/api/schemas.py tests/api/test_execucao.py
git commit -m "feat(api): a fonte vem no pedido — a sintetica vira uma entre outras"
```

---

### Task 2: `FonteArquivo` — ler CSV e JSON, com raiz e `ref` estável

**Files:**
- Create: `src/orchestrator/sources/__init__.py`, `src/orchestrator/sources/arquivo.py`
- Modify: `tests/arquitetura/camadas.py`
- Test: `tests/sources/test_arquivo.py` (criar, com `__init__.py`)

**Interfaces:**
- Consumes: nada das tasks anteriores
- Produces:
  - `ArquivoSource(caminho: Path, kind: str, campo_id: str, raiz: Path)` com `.ref: str` e `.load() -> WorkSet`
  - `RaizViolada(ValueError)` — o caminho saiu da raiz

**A segurança desta task é o ponto dela.** `caminho` é uma string que chega pela rede e vira leitura de disco. Sem cerca, o endpoint é um leitor de arquivos arbitrários — e o alvo que importa não é `/etc/passwd`, é `data/fila/**`, que devolveria a trilha de decisões humanas de outro workflow.

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/sources/__init__.py` vazio e `tests/sources/test_arquivo.py`:

```python
"""A fonte de arquivo: ler é fácil, a cerca é o trabalho."""

import json

import pytest

from orchestrator.sources.arquivo import ArquivoSource, RaizViolada


def _raiz(tmp_path):
    (tmp_path / "entradas").mkdir()
    return tmp_path / "entradas"


def test_csv_vira_pool_com_o_kind_declarado(tmp_path):
    raiz = _raiz(tmp_path)
    (raiz / "issues.csv").write_text(
        "numero,titulo\n7,trava ao salvar\n8,lento\n", encoding="utf-8"
    )

    fonte = ArquivoSource(
        caminho=raiz / "issues.csv", kind="issue", campo_id="numero", raiz=raiz
    )
    pool = fonte.load()

    assert [i.id for i in pool.items] == ["7", "8"]
    assert {i.kind for i in pool.items} == {"issue"}
    # O payload é a linha CRUA. O kernel nunca o inspeciona, e o `prompt` do
    # agente formata a partir dele.
    assert pool.items[0].payload == {"numero": "7", "titulo": "trava ao salvar"}


def test_json_com_lista_de_objetos_vira_o_mesmo_pool(tmp_path):
    raiz = _raiz(tmp_path)
    (raiz / "issues.json").write_text(
        json.dumps([{"numero": 7, "titulo": "trava"}]), encoding="utf-8"
    )

    pool = ArquivoSource(
        caminho=raiz / "issues.json", kind="issue", campo_id="numero", raiz=raiz
    ).load()

    # O id vira STRING mesmo quando o JSON traz número: `WorkItem.id` é `str`,
    # e deixar `7` e `"7"` coexistirem faria dois itens distintos para o mesmo
    # trabalho conforme o formato do arquivo.
    assert [i.id for i in pool.items] == ["7"]


def test_o_ref_e_o_SHA256_DO_CONTEUDO(tmp_path):
    """`ref` estável ou não há replay. Copiar o arquivo muda `mtime` e não muda
    o trabalho — por isso o hash é do conteúdo, nunca da data."""
    raiz = _raiz(tmp_path)
    (raiz / "a.csv").write_text("id,x\n1,um\n", encoding="utf-8")
    (raiz / "b.csv").write_text("id,x\n1,um\n", encoding="utf-8")

    a = ArquivoSource(caminho=raiz / "a.csv", kind="k", campo_id="id", raiz=raiz)
    b = ArquivoSource(caminho=raiz / "b.csv", kind="k", campo_id="id", raiz=raiz)

    assert a.ref.startswith("file:")
    # Mesmo conteúdo, arquivos diferentes: o hash bate, o caminho não.
    assert a.ref.split("@")[1] == b.ref.split("@")[1]
    assert a.ref != b.ref


def test_o_ref_MUDA_quando_o_conteudo_muda(tmp_path):
    raiz = _raiz(tmp_path)
    alvo = raiz / "a.csv"
    alvo.write_text("id,x\n1,um\n", encoding="utf-8")
    antes = ArquivoSource(caminho=alvo, kind="k", campo_id="id", raiz=raiz).ref

    alvo.write_text("id,x\n1,dois\n", encoding="utf-8")
    depois = ArquivoSource(caminho=alvo, kind="k", campo_id="id", raiz=raiz).ref

    assert antes != depois


def test_caminho_FORA_da_raiz_e_recusado(tmp_path):
    """O alvo que importa não é `/etc/passwd` — é `data/fila/**`, a trilha de
    decisões humanas de outro workflow."""
    raiz = _raiz(tmp_path)
    (tmp_path / "segredo.csv").write_text("id,x\n1,um\n", encoding="utf-8")

    with pytest.raises(RaizViolada):
        ArquivoSource(
            caminho=raiz / ".." / "segredo.csv", kind="k", campo_id="id", raiz=raiz
        )


def test_symlink_apontando_para_fora_e_recusado(tmp_path):
    """`resolve()` ANTES de comparar. Uma checagem feita sobre o caminho não
    resolvido é furada por um symlink que mora dentro da raiz."""
    raiz = _raiz(tmp_path)
    fora = tmp_path / "segredo.csv"
    fora.write_text("id,x\n1,um\n", encoding="utf-8")
    link = raiz / "atalho.csv"
    try:
        link.symlink_to(fora)
    except (OSError, NotImplementedError):
        pytest.skip("symlink exige privilégio neste sistema")

    with pytest.raises(RaizViolada):
        ArquivoSource(caminho=link, kind="k", campo_id="id", raiz=raiz)


def test_prefixo_de_string_NAO_conta_como_dentro(tmp_path):
    """`/dados-secretos` não está dentro de `/dados`, mas `startswith` diz que
    sim. É por isso que a comparação é `is_relative_to`."""
    raiz = _raiz(tmp_path)
    vizinho = tmp_path / "entradas-secretas"
    vizinho.mkdir()
    (vizinho / "x.csv").write_text("id,x\n1,um\n", encoding="utf-8")

    with pytest.raises(RaizViolada):
        ArquivoSource(
            caminho=vizinho / "x.csv", kind="k", campo_id="id", raiz=raiz
        )


def test_campo_id_ausente_e_erro_ALTO_nao_linha_pulada(tmp_path):
    """Pular em silêncio produziria um pool menor que o arquivo, e ninguém
    saberia. `WorkItem` já recusa id vazio; aqui a mensagem diz qual linha."""
    raiz = _raiz(tmp_path)
    (raiz / "x.csv").write_text("outro,x\n1,um\n", encoding="utf-8")

    fonte = ArquivoSource(caminho=raiz / "x.csv", kind="k", campo_id="id", raiz=raiz)

    with pytest.raises(ValueError, match="campo_id"):
        fonte.load()


def test_id_repetido_e_recusado_pelo_WorkSet(tmp_path):
    raiz = _raiz(tmp_path)
    (raiz / "x.csv").write_text("id,x\n1,um\n1,dois\n", encoding="utf-8")

    fonte = ArquivoSource(caminho=raiz / "x.csv", kind="k", campo_id="id", raiz=raiz)

    with pytest.raises(ValueError, match="id repetido"):
        fonte.load()


def test_teto_de_linhas_recusa_com_motivo(tmp_path):
    """Uma planilha de 200k linhas não pode derrubar o processo. Mesmo espírito
    do `n_max` que o pedido sintético já tem."""
    raiz = _raiz(tmp_path)
    linhas = "id,x\n" + "".join(f"{i},v\n" for i in range(12))
    (raiz / "grande.csv").write_text(linhas, encoding="utf-8")

    fonte = ArquivoSource(
        caminho=raiz / "grande.csv", kind="k", campo_id="id", raiz=raiz, max_linhas=10
    )

    with pytest.raises(ValueError, match="linhas"):
        fonte.load()
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/sources -q
```

Esperado: `ModuleNotFoundError: No module named 'orchestrator.sources'`.

- [ ] **Step 3: Implementar**

Criar `src/orchestrator/sources/__init__.py` vazio e `src/orchestrator/sources/arquivo.py`:

```python
"""Um arquivo do usuário como pool de trabalho.

`kernel/source.py` prometeu isto no docstring: *"quem tiver o dado escreve um
`Source` de 40 linhas, e é essa a promessa do framework"*. Este é o segundo
`Source` do projeto — o primeiro foi o sintético, e enquanto ele era o único a
promessa não tinha sido cobrada.

**A leitura é a parte fácil. A CERCA é o trabalho.** `caminho` chega pela rede
e vira uma leitura de disco no servidor: sem raiz, este módulo é um leitor de
arquivos arbitrários. O alvo que importa não é `/etc/passwd` — é `data/fila/**`,
que devolveria a trilha de decisões humanas de OUTRO workflow.
"""

import csv
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from orchestrator.kernel.work import WorkItem, WorkSet

MAX_LINHAS_PADRAO = 5000


class RaizViolada(ValueError):
    """O caminho pedido não está sob a raiz de entradas."""


@dataclass(frozen=True)
class ArquivoSource:
    """CSV ou JSON, sob uma raiz, com `ref` por conteúdo.

    O formato sai da extensão e não de um campo declarado: quem escolhe `.csv`
    já disse o que é, e um campo `formato` que pudesse contradizer a extensão
    seria uma segunda fonte de verdade sobre a mesma coisa.
    """

    caminho: Path
    kind: str
    campo_id: str
    raiz: Path
    max_linhas: int = MAX_LINHAS_PADRAO
    _resolvido: Path = field(init=False, repr=False)

    def __post_init__(self) -> None:
        raiz = self.raiz.resolve()
        alvo = self.caminho.resolve()
        # `resolve()` ANTES de comparar, e `is_relative_to` em vez de
        # `startswith`: um prefixo de string diz que `/dados-secretos` está
        # dentro de `/dados`, e um symlink que mora dentro da raiz fura
        # qualquer checagem feita antes de resolver.
        if not alvo.is_relative_to(raiz):
            raise RaizViolada(
                f"caminho fora da raiz de entradas: {self.caminho} não está sob {self.raiz}"
            )
        object.__setattr__(self, "_resolvido", alvo)

    @property
    def ref(self) -> str:
        """`file:<caminho relativo>@<sha256 do conteúdo>`.

        Do CONTEÚDO, nunca do `mtime`: copiar ou tocar um arquivo muda a data e
        não muda o trabalho, e o replay quebraria por nada. Relativo à raiz
        porque o caminho absoluto da máquina não é parte da identidade do
        trabalho — mover a raiz não deveria invalidar decisões já tomadas.
        """
        digest = hashlib.sha256(self._resolvido.read_bytes()).hexdigest()
        return f"file:{self._resolvido.relative_to(self.raiz.resolve())}@{digest}"

    def load(self) -> WorkSet:
        linhas = self._linhas()
        if len(linhas) > self.max_linhas:
            raise ValueError(
                f"{self.caminho.name} tem {len(linhas)} linhas, acima do teto de "
                f"{self.max_linhas}. Reduza o arquivo ou suba o teto."
            )
        itens = []
        for i, linha in enumerate(linhas, start=1):
            if self.campo_id not in linha:
                # Alto, com o número da linha. Pular em silêncio produziria um
                # pool menor que o arquivo, e ninguém saberia.
                raise ValueError(
                    f"linha {i} de {self.caminho.name} não tem o campo_id "
                    f"{self.campo_id!r}. campos: {sorted(linha)}"
                )
            itens.append(
                WorkItem(id=str(linha[self.campo_id]), kind=self.kind, payload=linha)
            )
        # `WorkSet.__post_init__` recusa id repetido — deixar a guarda dele
        # falar evita uma segunda mensagem para a mesma falha.
        return WorkSet(items=tuple(itens))

    def _linhas(self) -> list[dict]:
        texto = self._resolvido.read_text(encoding="utf-8")
        if self._resolvido.suffix.lower() == ".json":
            dados = json.loads(texto)
            if not isinstance(dados, list):
                raise ValueError(
                    f"{self.caminho.name}: o JSON precisa ser uma LISTA de objetos, "
                    f"e veio {type(dados).__name__}"
                )
            return dados
        return list(csv.DictReader(texto.splitlines()))
```

- [ ] **Step 4: Acrescentar a camada**

Em `tests/arquitetura/camadas.py`, na tabela `PERMITIDO`, acrescentar:

```python
    "sources": frozenset({"kernel"}),
```

e `"sources"` ao `_BORDA` (as bordas — `api` e `cli` — podem importar tudo, e `sources` precisa estar no conjunto que elas alcançam).

- [ ] **Step 5: Rodar os testes**

```bash
./.venv/Scripts/python.exe -m pytest tests/sources tests/arquitetura -q
```

Esperado: PASS. O teste de symlink pode pular no Windows sem privilégio — `pytest.skip` é o comportamento certo, não uma falha.

- [ ] **Step 6: Suíte e lint**

```bash
./.venv/Scripts/python.exe -m pytest -q && ./.venv/Scripts/python.exe -m ruff check src tests
```

- [ ] **Step 7: Commit**

```bash
git add src/orchestrator/sources tests/sources tests/arquitetura/camadas.py
git commit -m "feat(sources): arquivo como fonte — CSV, JSON, ref por conteudo e a cerca da raiz"
```

---

### Task 3: O `/runs` pelo motor genérico, e a resposta em duas formas

**Esta é a task-gargalo.** Enquanto ela não landar, a fonte da Task 2 não tem quem a receba e o agente da Task 4 não tem quem o execute.

**Files:**
- Modify: `src/orchestrator/api/app.py` (`_executar`)
- Modify: `src/orchestrator/api/schemas.py` (`RunJSON`, `MedidoJSON`)
- Test: `tests/api/test_execucao.py`

**Interfaces:**
- Consumes: `RunRequest.fonte` (Task 1), `ArquivoSource` (Task 2)
- Produces:
  - `MedidoJSON(seed, n, bank_total, deterministic_rate)`
  - `RunJSON(input_ref, itens, resolvidos, por_resolver, gap, custo_microcents, contra_gabarito: MedidoJSON | None)`

**O desenho que faz as duas formas serem honestas.** Quem sabe se há gabarito é a FONTE, não um `if` sobre o id do workflow. `SyntheticSource` tem `dataset()`; `ArquivoSource` não. O adaptador na borda devolve os dois:

```python
def _fonte_de(pedido: RunRequest) -> tuple[Source, Dataset | None]:
    """A fonte e o gabarito, quando existe.

    `Dataset | None` em vez de um método no protocolo: `kernel/source.py` diz
    que gabarito é insumo de AVALIAÇÃO e o motor não deve recebê-lo. Pôr
    `gabarito()` no `Source` obrigaria toda fonte de dado real a implementar um
    método que devolve `None` — e convidaria alguém a chamá-lo no motor.
    """
```

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar a `tests/api/test_execucao.py`:

```python
def test_a_fonte_SINTETICA_continua_medindo_contra_gabarito():
    """O caminho de hoje, com a forma nova. A conciliação não perde nada."""
    r = cliente.post("/api/workflows/conciliacao/runs", json={})

    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["contra_gabarito"] is not None
    assert corpo["contra_gabarito"]["bank_total"] > 0
    assert 0.0 <= corpo["contra_gabarito"]["deterministic_rate"] <= 1.0
    assert corpo["input_ref"].startswith("synth:")


def test_a_fonte_de_ARQUIVO_nao_inventa_taxa_de_acerto(tmp_path, monkeypatch):
    """O teste que existe por causa de um bug real.

    Antes desta fatia, compor uma cascata de compras e rodar devolvia `200` com
    `deterministic_rate: 0.0` e lacuna de 100% — um número que parece medido e
    não é. AUSENTE é a forma de dizer "não medido contra verdade"; `0.0` seria
    a mesma mentira com outra roupa.
    """
    import orchestrator.api.app as api_app

    raiz = tmp_path / "entradas"
    raiz.mkdir()
    (raiz / "itens.csv").write_text("id,texto\na,um\nb,dois\n", encoding="utf-8")
    monkeypatch.setattr(api_app, "_RAIZ_ENTRADAS", raiz)

    r = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"fonte": {"tipo": "arquivo", "caminho": "itens.csv",
                        "kind": "lancamento", "campo_id": "id"}},
    )

    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["contra_gabarito"] is None
    assert corpo["itens"] == 2
    assert corpo["input_ref"].startswith("file:")


def test_caminho_fora_da_raiz_vira_422_e_nao_500(tmp_path, monkeypatch):
    import orchestrator.api.app as api_app

    raiz = tmp_path / "entradas"
    raiz.mkdir()
    monkeypatch.setattr(api_app, "_RAIZ_ENTRADAS", raiz)

    r = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"fonte": {"tipo": "arquivo", "caminho": "../segredo.csv",
                        "kind": "k", "campo_id": "id"}},
    )

    assert r.status_code == 422
    assert "raiz" in r.json()["detail"]


def test_o_custo_da_execucao_volta_na_resposta():
    """`Run.cost_by_resolver` já acumula entre rondas. Gasto que não aparece na
    tela é gasto que ninguém revisa."""
    corpo = cliente.post("/api/workflows/conciliacao/runs", json={}).json()

    assert "custo_microcents" in corpo
    assert corpo["custo_microcents"] >= 0
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/api/test_execucao.py -q
```

Esperado: `KeyError: 'contra_gabarito'`.

- [ ] **Step 3: Implementar os schemas**

Em `src/orchestrator/api/schemas.py`, substituir `RunJSON`:

```python
class MedidoJSON(BaseModel):
    """O que só existe quando a fonte carrega gabarito.

    `seed`, `n` e `bank_total` moravam no topo de `RunJSON` porque só existia
    uma fonte. Num CSV de issues eles não têm valor certo nem valor neutro —
    têm ausência, e é isso que esta separação passa a expressar.
    """

    seed: int
    n: int
    bank_total: int
    deterministic_rate: float


class RunJSON(BaseModel):
    input_ref: str
    itens: int
    resolvidos: int
    por_resolver: list[ResolverRunJSON]
    gap: GapJSON
    custo_microcents: int
    # AUSENTE, não zero. Publicar `0.0` sobre uma fonte sem verdade seria dizer
    # "errou tudo" quando o certo é "não há com o que comparar".
    contra_gabarito: MedidoJSON | None = None
```

- [ ] **Step 4: Implementar a raiz e o adaptador de fonte**

Em `src/orchestrator/api/app.py`, junto das outras raízes:

```python
_RAIZ_ENTRADAS = Path(__file__).resolve().parents[3] / "data" / "entradas"
```

E o adaptador:

```python
def _fonte_de(pedido: RunRequest):
    """A fonte e o gabarito, quando existe.

    Quem sabe se há gabarito é a FONTE — não um `if` sobre o id do workflow.
    `SyntheticSource` tem `dataset()`; uma fonte de dado real não tem, e é
    exatamente por isso que `metrics.evaluate` continua exigindo um `Dataset`.
    """
    f = pedido.fonte
    if f.tipo == "sintetica":
        fonte = SyntheticSource(seed=f.seed, n=f.n, taxa_divergencia=f.taxa_divergencia)
        return fonte, fonte.dataset()
    try:
        return (
            ArquivoSource(
                caminho=_RAIZ_ENTRADAS / f.caminho,
                kind=f.kind,
                campo_id=f.campo_id,
                raiz=_RAIZ_ENTRADAS,
            ),
            None,
        )
    except RaizViolada as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
```

- [ ] **Step 5: Implementar `_executar`**

O corpo passa a ser UM caminho, com um ramo só no fim:

```python
    fonte, gabarito = _fonte_de(pedido)
    pool = fonte.load()
    run = execute(definicao, pool, input_ref=fonte.ref, bus=bus)
    _run_store().save(run)
    _trace_store().save(coletor.trace(run))

    total = len(pool.items)
    resolvidos = total - len(run.unresolved.items)
    modelo = pedido.fonte.tipo and MODELO_INERTE  # o modelo da tabela de preços
    por_resolver = [
        ResolverRunJSON(
            name=d.name,
            cost_class=d.cost_class.name,
            matches=run.resolved_by_resolver.get(d.name, 0),
            rate=run.resolved_by_resolver.get(d.name, 0) / total if total else 0.0,
            microcents=run.cost_by_resolver.get(d.name, Cost.zero()).microcents(modelo),
        )
        for stage in definicao.stages
        for d in (r.describe() for r in stage.ordered())
    ]
```

E o gabarito, quando existe:

```python
    medido = None
    if gabarito is not None:
        # `evaluate` exige um `ReconcileResult`, e ele é um invólucro FINO do
        # `Run`: das seis coisas que carrega, `evaluate` lê exatamente duas —
        # `matches` e `matches_by_class`. `divergences` fica vazio de propósito
        # e isso NÃO é uma meia-verdade escondida: traduzir o resto do pool em
        # `Divergence` é trabalho do domínio, para a CLI, e `evaluate` não o
        # consulta. Adaptar `metrics.evaluate` para receber um `Run` seria mais
        # limpo e arrastaria os outros dois chamadores (CLI e grill) para dentro
        # desta fatia — troca que não vale aqui.
        m = evaluate(
            gabarito,
            ReconcileResult(
                matches=list(run.resolutions),
                divergences=[],
                proposals=list(run.proposals),
                cost_by_resolver=run.cost_by_resolver,
                matches_by_resolver=run.resolved_by_resolver,
                matches_by_class=run.resolutions_by_class,
            ),
        )
        medido = MedidoJSON(
            seed=pedido.fonte.seed,
            n=pedido.fonte.n,
            bank_total=m.bank_total,
            deterministic_rate=m.deterministic_rate,
        )
```

**A lacuna passa a sair do `Run`**: `len(run.unresolved.items)` sobre o total do pool. O comentário longo sobre `bank_matched_total` explicava por que a lacuna NÃO era a soma das contagens por resolver — com `run.unresolved` a suposição que ele temia ("um id bancário por match") deixa de existir, porque o pool restante é contado e não inferido. **Mova o comentário para o ramo do gabarito, adaptado**, em vez de apagá-lo: ele registra um defeito que já custou uma correção.

- [ ] **Step 6: Rodar os testes**

```bash
./.venv/Scripts/python.exe -m pytest tests/api -q
```

Esperado: PASS. Testes que liam `corpo["bank_total"]` ou `corpo["deterministic_rate"]` no topo mudam de alvo para `corpo["contra_gabarito"][...]` — a quebra é deliberada (§7 do spec) e esses testes são desta fatia.

- [ ] **Step 7: Suíte, lint e commit**

```bash
./.venv/Scripts/python.exe -m pytest -q && ./.venv/Scripts/python.exe -m ruff check src tests
git add src/orchestrator/api tests/api
git commit -m "feat(api): /runs pelo motor generico, e a resposta que nao inventa taxa"
```

---

### Task 4: Executar com agente, com teto

**Files:**
- Modify: `src/orchestrator/workflows.py` (`WorkflowContext`)
- Modify: `src/orchestrator/api/app.py`
- Test: `tests/api/test_execucao.py`

**Interfaces:**
- Consumes: tudo das tasks 1–3
- Produces: `WorkflowContext(fila: Fila, cliente: LLMClient | None = None)`

**O achado que o spec não nomeou, e que esta task precisa resolver.** `WorkflowContext` carrega só `fila`. Uma cascata com agente precisa de um `LLMClient` de verdade para ser construída, e `construir_definicao(fabrica, ctx)` não tem por onde passá-lo. Sem isso, a definição é montada com `ClienteAusente` — a tranca — e o agente levanta ao primeiro turno. **`cliente` entra em `WorkflowContext` com default `None`**, e `None` continua significando "use a tranca", que é o comportamento de hoje para todos os chamadores existentes.

- [ ] **Step 1: Escrever os testes que falham**

```python
def test_sem_chave_a_execucao_com_agente_e_recusada_com_MOTIVO(monkeypatch):
    """Guarda 3, a mesma do chat. Sem chave, recusa legível — em vez de o SDK
    levantar no meio do laço com o trabalho já pela metade."""
    import orchestrator.api.app as api_app

    monkeypatch.setattr(api_app, "_tem_chave", lambda: False)
    cliente.post("/api/receitas", json={
        "id": "com-agente", "nome": "x", "justificativa": "",
        "resolvers": [{"nome": "investigador"}]})

    r = cliente.post("/api/workflows/com-agente/runs", json={})

    assert r.status_code == 409
    assert "chave" in r.json()["detail"].lower()


def test_cascata_SEM_agente_nao_exige_chave(monkeypatch):
    """A regra ficou mais precisa, não mais frouxa: só gasta quem tem agente."""
    import orchestrator.api.app as api_app

    monkeypatch.setattr(api_app, "_tem_chave", lambda: False)

    r = cliente.post("/api/workflows/conciliacao/runs", json={})

    assert r.status_code == 200


def test_o_teto_do_pedido_chega_ao_agente(monkeypatch):
    """Guarda 1. O teto é dito ANTES, e é o do pedido que vale — não o default
    do agente, que é generoso por ser um default."""
    import orchestrator.api.app as api_app

    vistos = {}
    monkeypatch.setattr(api_app, "_tem_chave", lambda: True)
    monkeypatch.setattr(
        api_app, "_cliente_de_execucao",
        lambda teto: vistos.setdefault("teto", teto) or FakeLLMClient([]),
    )
    cliente.post("/api/receitas", json={
        "id": "com-teto", "nome": "x", "justificativa": "",
        "resolvers": [{"nome": "investigador"}]})

    cliente.post("/api/workflows/com-teto/runs", json={"teto_microcents": 12345})

    assert vistos["teto"] == 12345
```

Importar `FakeLLMClient` de `orchestrator.agent.llm` no topo.

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/api/test_execucao.py -q
```

Esperado: `AttributeError: module 'orchestrator.api.app' has no attribute '_tem_chave'`.

- [ ] **Step 3: `WorkflowContext` ganha o cliente**

```python
@dataclass(frozen=True)
class WorkflowContext:
    fila: Fila
    # O cliente que a EXECUÇÃO usa. `None` mantém o comportamento de todos os
    # chamadores de hoje: a fábrica cai no `ClienteAusente`, que é a tranca.
    # Desarmá-la continua sendo ato explícito de quem executa — o que muda é
    # que agora existe por onde fazê-lo sem inventar um segundo caminho.
    cliente: "LLMClient | None" = None
```

- [ ] **Step 4: As três guardas na rota**

Substituir o `409` de "etapa paga" por:

```python
    tem_agente = CostClass.AGENTE in classes
    if tem_agente:
        # A regra deste módulo ficou MAIS precisa, não mais frouxa:
        #   EXECUTAR pela web gasta QUANDO a cascata tem agente, com teto, e o
        #   teto é dito antes.
        # As três guardas são as do chat (`api/entrevista.py`), e nenhuma é
        # opcional.
        if not _tem_chave():
            raise HTTPException(
                status_code=409,
                detail=(
                    "esta cascata tem etapa paga e não há ANTHROPIC_API_KEY no "
                    "ambiente. configure a chave ou rode pela CLI."
                ),
            )
```

e passar o cliente adiante:

```python
    ctx = WorkflowContext(
        fila=fila,
        cliente=_cliente_de_execucao(pedido.teto_microcents) if tem_agente else None,
    )
```

`_tem_chave()` e `_cliente_de_execucao(teto)` ficam como funções de módulo — é o que torna os dois substituíveis por `monkeypatch` no teste sem tocar em ambiente de verdade.

- [ ] **Step 5: Rodar os testes**

```bash
./.venv/Scripts/python.exe -m pytest tests/api tests/test_workflows.py -q
```

Esperado: PASS. **Confirme que nenhum teste passou a chamar API paga**: `FakeLLMClient` no teste, e `_cliente_de_execucao` só é chamado quando `tem_agente`.

- [ ] **Step 6: Suíte, lint e commit**

```bash
./.venv/Scripts/python.exe -m pytest -q && ./.venv/Scripts/python.exe -m ruff check src tests
git add src/orchestrator tests
git commit -m "feat(api): executar com agente — teto no pedido, recusa sem chave"
```

---

### Task 5: A tela — escolher a fonte, ver o custo, ver "sem gabarito"

**Files:**
- Modify: `web-app/src/api.ts`, `web-app/src/Execucao.tsx`
- Test: `tests/api/test_compor.py` (asserções sobre o bundle)

**Interfaces:**
- Consumes: `RunJSON` com `contra_gabarito` (Task 3), `teto_microcents` (Task 4)
- Produces: nenhuma API nova

- [ ] **Step 1: Os tipos**

Em `api.ts`, substituir `Run`:

```ts
export interface Medido {
  seed: number;
  n: number;
  bank_total: number;
  deterministic_rate: number;
}

export interface Run {
  input_ref: string;
  itens: number;
  resolvidos: number;
  por_resolver: LinhaDeRun[];
  gap: { items: number; rate: number };
  custo_microcents: number;
  // `null` quando a fonte não tem gabarito. A tela DIZ isso — não desenha
  // uma barra vazia nem um zero.
  contra_gabarito: Medido | null;
}
```

e `rodar` passa a mandar a fonte e o teto.

- [ ] **Step 2: A vista**

Em `Execucao.tsx`: um seletor de fonte (sintética ou arquivo), os campos de arquivo quando "arquivo" estiver escolhido, o custo da execução no cabeçalho, e — onde hoje mora a taxa determinística — **o texto "sem gabarito: não há com o que comparar" quando `contra_gabarito` é `null`**, no lugar de um número.

A cor da lacuna e das classes de custo já existem em `COR_DA_CLASSE`; reuse.

- [ ] **Step 3: Typecheck e build**

```bash
cd web-app && npx tsc --noEmit && npm run build
```

- [ ] **Step 4: Verificar no NAVEGADOR — é o gate desta task**

```bash
./.venv/Scripts/python.exe -m uvicorn orchestrator.api.app:app --port 8111
```

Com um CSV em `data/entradas/`, confirme com os próprios olhos:
- fonte sintética: a taxa contra gabarito aparece, como hoje;
- fonte arquivo: a taxa **não** aparece, e no lugar há o texto dizendo por quê;
- o custo da execução aparece no cabeçalho;
- caminho fora da raiz devolve mensagem legível, não uma tela quebrada.

Nem o `tsc` nem o pytest pegam uma barra desenhada sobre `null`. O navegador pega.

- [ ] **Step 5: Suíte, lint e commit**

```bash
./.venv/Scripts/python.exe -m pytest -q && ./.venv/Scripts/python.exe -m ruff check src tests
git add web-app web tests/api/test_compor.py
git commit -m "feat(web): escolher a fonte, ver o custo, e dizer quando nao ha gabarito"
```

---

## Fora deste plano

- **R7 — `FonteHttp`** (auth, paginação, cursor, `ref` por etag). Plano 2, pelas razões da §4 do spec.
- **Upload de arquivo.** O caminho é lido do disco do servidor. Upload com id próprio, limite e expiração é outra fatia.
- **A lacuna de custo (G3).** Decisão explícita do dono: fica por último.
- **A lacuna de `kind` na composição** (X7/X8). Continua aberta e continua escrita no README.
