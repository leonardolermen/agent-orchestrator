# Bloco `Enrich` + Caso Barrier — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Um bloco determinístico que, para cada item, busca o detalhe numa API e o funde no payload — e um caso real que o prova: a fila da mesa de análise do Barrier (KYC/PLD-FT) triada até virar proposta na fila de revisão humana.

**Architecture:** O bloco vive em `sources/` (não em `regras/`: a tabela de camadas dá a `regras` só o `kernel`, e o bloco precisa da guarda de host e do cliente HTTP que moram em `sources`). Ele CONSOME um kind e PRODUZ outro, como `condicao` e `Tarefa`, porque o kernel não tem alteração em lugar. Herda de `sources/http.py` a guarda de URL, o token por nome e o teto de bytes.

**Tech Stack:** Python 3.11+, httpx (extra `fontes`), pytest com `httpx.MockTransport`. Do lado do Barrier: Docker (a Risk Engine sobe por container; esta máquina tem JDK 17 e ele exige 25).

**Spec:** `docs/superpowers/specs/2026-09-22-bloco-enrich-e-o-caso-barrier-design.md`

## Global Constraints

- **Português** no código e na prosa. Commits: `tipo(escopo): frase em minúscula`, assunto sem acento, corpo com o porquê e a evidência.
- **Comentário registra POR QUÊ, com evidência** — alternativa rejeitada, defeito evitado ou número medido.
- **TDD**: nenhum código de produção sem um teste que falhou antes.
- Suíte: `.venv/Scripts/python.exe -m pytest -q`. Lint: `.venv/Scripts/python.exe -m ruff check src tests`. **`ruff format` não roda.**
- `httpx` é do extra `fontes`: todo teste que o importa precisa de `pytest.importorskip("httpx")` no topo, antes do import — sem ele o arquivo derruba a coleta na instalação `[dev]` do CI.
- Nenhum teste fala com a rede: `tests/conftest.py::_rede_proibida` é autouse. HTTP só via `httpx.MockTransport`.
- **Camadas:** `sources` importa só `kernel`. Módulo novo exige entrada em `tests/arquitetura/camadas.py::DESTINO` — `sources/enriquecimento.py` cai no diretório `sources`, que já é nome de camada, então **não** precisa de entrada nova.
- Ao final de cada tarefa: suíte verde + `ruff check` limpo.
- Critério do produto: `.venv/Scripts/orchestrator.exe --seed 1 --n 500` diz `85.3%`, zero falso positivo, zero falso negativo. **O bloco novo nunca entra nesse caminho** — o golden depende de regras puras.

---

### Task 1: O resolver `Enriquecimento`

**Files:**
- Create: `src/orchestrator/sources/enriquecimento.py`
- Modify: `docs/superpowers/specs/2026-09-22-bloco-enrich-e-o-caso-barrier-design.md` (duas correções, abaixo)
- Test: `tests/sources/test_enriquecimento.py` (criar)

**Interfaces:**
- Consumes: `sources/http.py::{_guarda_url, _url_publica, MAX_BYTES_PADRAO, _ler_com_teto, _seguir, _transporte_padrao}`, `sources/erros.py::{ErroDeFonte, ExtraAusente, FonteFalhou, VariavelAusente}`, `kernel/work.py::campos_de`.
- Produces: `Enriquecimento(kind, produz, url, token_env=None, caminho="", max_bytes=..., transporte=None)` — um `Resolver` com `name="enriquecer"` e `cost_class=CostClass.REGRA`.

- [ ] **Step 1: Corrigir as duas afirmações da spec que a leitura derrubou**

Em `docs/superpowers/specs/2026-09-22-bloco-enrich-e-o-caso-barrier-design.md`:

1. `regras/enriquecimento.py` → `sources/enriquecimento.py`, com o motivo: a tabela de camadas dá a `regras` só o `kernel`, e o bloco precisa da guarda de host e do cliente HTTP. Precedente: `sources/bloco.py`, o `Input`, é um resolver que mora lá pela mesma razão.
2. Onde a spec diz "o motivo entra no trace", trocar por: **o motivo vai para o log do servidor, e o sinal visível é o item aparecer na LACUNA**. `ResolverOutput` não tem canal por item para "pulei e eis por quê" — é a mesma lacuna que `agent/tarefa.py` já declara sobre o teto de orçamento, e prometer trace seria prometer o que o tipo não carrega.

- [ ] **Step 2: Write the failing tests**

Criar `tests/sources/test_enriquecimento.py`:

```python
"""O bloco que busca o detalhe de cada item.

Entre `Input` (traz a lista) e os blocos de decisão faltava a operação mais
comum de automação: para cada item, buscar o que a lista não trouxe. Sem ela, a
única saída era pagar um turno de modelo para executar um GET que não decide
nada.
"""

import json

import pytest

pytest.importorskip("httpx")

import httpx

from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.sources.enriquecimento import Enriquecimento
from orchestrator.sources.erros import VariavelAusente


def _transporte(handler):
    return httpx.MockTransport(handler)


def _bloco(handler, **kw) -> Enriquecimento:
    base = dict(
        kind="caso",
        produz="caso_completo",
        url="https://api.exemplo.test/v1/assessments/{assessmentId}",
        transporte=_transporte(handler),
    )
    base.update(kw)
    return Enriquecimento(**base)


def _pool(*payloads) -> WorkSet:
    return WorkSet(
        items=tuple(
            WorkItem(id=str(p["assessmentId"]), kind="caso", payload=p) for p in payloads
        )
    )


def test_os_campos_da_resposta_pousam_no_TOPO_do_payload():
    """No primeiro nível, e não aninhados sob um nome: `_prompt_do_item` usa
    `format_map`, que só alcança o primeiro nível — aninhar tornaria
    inalcançável pelo prompt justamente o dado que foi buscado para ele."""

    def handler(pedido):
        assert pedido.url.path == "/v1/assessments/a1"
        return httpx.Response(200, json={"risco": "ALTO", "motivo": "PEP"})

    saida = _bloco(handler).resolve(_pool({"assessmentId": "a1", "slaSeconds": 90}))

    (produzido,) = saida.produced
    assert produzido.kind == "caso_completo"
    assert produzido.payload == {
        "assessmentId": "a1",
        "slaSeconds": 90,
        "risco": "ALTO",
        "motivo": "PEP",
    }
    # Consome E produz: o item original sai do pool por uma resolução.
    (resolucao,) = saida.resolutions
    assert resolucao.item_ids == frozenset({"a1"})


def test_em_COLISAO_o_campo_original_do_item_vence():
    """Uma resposta de terceiro não pode reescrever o campo que IDENTIFICA o
    item: se pudesse, o id do run, a chave da fila e a decisão humana passariam
    a apontar para coisas diferentes.

    É a regra OPOSTA à do `BlocoTarefa`, onde o texto novo vence — e a
    assimetria é deliberada: lá o campo novo é a saída do trabalho, aqui é
    informação de fora chegando sobre um item que já tem identidade.
    """

    def handler(pedido):
        return httpx.Response(200, json={"assessmentId": "OUTRO", "risco": "BAIXO"})

    saida = _bloco(handler).resolve(_pool({"assessmentId": "a1"}))

    assert saida.produced[0].payload == {"assessmentId": "a1", "risco": "BAIXO"}


def test_um_item_que_FALHA_fica_no_pool_e_os_outros_seguem():
    """Falha de rede não derruba um fechamento por causa de um item — é a mesma
    forma da abstenção de um agente. O item não consumido aparece na LACUNA,
    que é a notícia certa; um payload pela metade seria lido como fato pelo
    degrau seguinte."""

    def handler(pedido):
        if pedido.url.path.endswith("a1"):
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"risco": "BAIXO"})

    saida = _bloco(handler).resolve(_pool({"assessmentId": "a1"}, {"assessmentId": "a2"}))

    assert [p.payload["assessmentId"] for p in saida.produced] == ["a2"]
    assert [r.item_ids for r in saida.resolutions] == [frozenset({"a2"})]


def test_template_citando_campo_que_o_item_NAO_TEM_abstem_nomeando_o_campo(caplog):
    """Mesma abstenção, e o log diz qual campo faltou — sem isso, quem monta o
    workflow só vê a lacuna e não tem como saber se errou o nome do campo ou se
    a API caiu."""

    def handler(pedido):  # pragma: no cover - não deve ser alcançado
        raise AssertionError("não devia chegar à rede com o template furado")

    bloco = _bloco(handler, url="https://api.exemplo.test/v1/x/{nao_existe}")

    saida = bloco.resolve(_pool({"assessmentId": "a1"}))

    assert saida.produced == ()
    assert "nao_existe" in caplog.text


def test_token_ausente_falha_ALTO_e_nao_toca_a_rede():
    """Erro de CONFIGURAÇÃO, não abstenção: abster item a item por falta de
    credencial gastaria a fila inteira para não fazer nada."""

    def handler(pedido):  # pragma: no cover
        raise AssertionError("não devia chegar à rede sem token")

    bloco = _bloco(handler, token_env="NAO_DEFINIDA_NO_AMBIENTE")

    with pytest.raises(VariavelAusente):
        bloco.resolve(_pool({"assessmentId": "a1"}))


def test_o_token_vai_no_cabecalho_e_vem_do_NOME_da_variavel(monkeypatch):
    monkeypatch.setenv("BARRIER_TOKEN", "segredo-123")
    vistos = {}

    def handler(pedido):
        vistos["auth"] = pedido.headers.get("authorization")
        return httpx.Response(200, json={"risco": "ALTO"})

    _bloco(handler, token_env="BARRIER_TOKEN").resolve(_pool({"assessmentId": "a1"}))

    assert vistos["auth"] == "Bearer segredo-123"


def test_host_LOOPBACK_e_recusado_pela_guarda_herdada():
    """A mesma guarda de `sources/http.py`, e pela mesma razão: o servidor passa
    a fazer requisições para URLs que vêm da tela. Afrouxá-la para alcançar um
    serviço local seria trocar a proteção por conveniência."""
    from orchestrator.sources.erros import ErroDeFonte

    def handler(pedido):  # pragma: no cover
        raise AssertionError("não devia chegar à rede com host de loopback")

    bloco = _bloco(handler, url="http://127.0.0.1:8080/v1/x/{assessmentId}")

    with pytest.raises(ErroDeFonte):
        bloco.resolve(_pool({"assessmentId": "a1"}))


def test_caminho_aponta_o_objeto_dentro_do_corpo():
    """`caminho` é a ferramenta de MINIMIZAÇÃO: apontá-lo para o subobjeto que
    importa é o que mantém o cadastro inteiro fora do pool, da fila e do
    trace."""

    def handler(pedido):
        return httpx.Response(
            200, json={"dados": {"screening": {"risco": "ALTO"}}, "cadastro": {"nome": "Fulano"}}
        )

    saida = _bloco(handler, caminho="dados.screening").resolve(_pool({"assessmentId": "a1"}))

    assert saida.produced[0].payload == {"assessmentId": "a1", "risco": "ALTO"}


def test_resposta_que_nao_e_OBJETO_abstem():
    """Uma lista ou um número não têm campos para fundir. Fundir "de algum
    jeito" inventaria uma chave que ninguém declarou."""

    def handler(pedido):
        return httpx.Response(200, json=[1, 2, 3])

    saida = _bloco(handler).resolve(_pool({"assessmentId": "a1"}))

    assert saida.produced == ()


def test_produz_igual_ao_kind_e_recusado_na_CONSTRUCAO():
    """O ramo alimentaria a si mesmo — a mesma recusa de `condicao.py` e de
    `TarefaDeclarada`."""
    with pytest.raises(ValueError, match="mesmo kind"):
        Enriquecimento(kind="caso", produz="caso", url="https://x.test/{id}")


def test_a_classe_de_custo_e_REGRA():
    """Ela mede DINHEIRO, e o bloco custa 0 µ¢ — isso é verdade. O que ele
    ganha é latência e um modo de falha, e é por isso que ele nunca entra no
    caminho do golden."""
    assert _bloco(lambda p: httpx.Response(200, json={})).cost_class is CostClass.REGRA
```

- [ ] **Step 3: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/sources/test_enriquecimento.py -q`
Expected: FAIL na coleta — `ImportError: cannot import name 'Enriquecimento'`.

- [ ] **Step 4: Write the implementation**

Criar `src/orchestrator/sources/enriquecimento.py`:

```python
"""O bloco que busca, para CADA item, o detalhe que a lista não trouxe.

**Por que ele existe.** `Input` traz uma lista de uma API; os blocos de decisão
julgam o que está no item. Entre os dois faltava a operação mais comum de
automação, e sem ela a única saída era pagar um turno de modelo para executar um
`GET` cujo resultado não depende de julgamento nenhum — exatamente o que o §2 do
README proíbe.

**Por que ele mora em `sources/` e não em `regras/`.** `regras` importa só
`kernel`, por decisão de arquitetura: uma regra determinística casa por nome de
campo e não conhece o mundo. Este bloco precisa da guarda de host, do cliente e
do teto de bytes que moram aqui. O precedente é `sources/bloco.py` — o `Input` é
um resolver que mora em `sources` pela mesma razão.

**Consome e produz**, como `condicao` e `Tarefa`: o kernel não tem alteração em
lugar — resolução consome, produção cria. É isso que põe o bloco no grafo, faz a
aresta aparecer no canvas e mantém a recusa de beco sem saída viva.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.resolution import Resolution
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkItem, WorkSet, campos_de
from orchestrator.sources.erros import ErroDeFonte, ExtraAusente, FonteFalhou, VariavelAusente
from orchestrator.sources.http import (
    MAX_BYTES_PADRAO,
    _guarda_url,
    _ler_com_teto,
    _seguir,
    _transporte_padrao,
    _url_publica,
)

_log = logging.getLogger("orchestrator.sources")


@dataclass(frozen=True)
class Enriquecimento:
    """Consome `kind`, busca `url` por item, funde a resposta, produz `produz`."""

    kind: str
    produz: str
    url: str
    token_env: str | None = None
    caminho: str = ""
    max_bytes: int = MAX_BYTES_PADRAO
    transporte: Any = field(default=None, compare=False)

    name: str = field(default="enriquecer", init=False)
    cost_class: CostClass = field(default=CostClass.REGRA, init=False)

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ValueError("enriquecer: diga sobre qual kind ele roda")
        if not self.produz.strip():
            raise ValueError(
                "enriquecer: `produz` vazio. o item seria consumido sem ser "
                "entregue a ninguém — para descartar de propósito existe o `filtro`"
            )
        if self.produz == self.kind:
            raise ValueError(
                f"enriquecer: produz o mesmo kind que consome ({self.kind!r}). "
                f"o ramo alimentaria a si mesmo"
            )
        if "{" not in self.url:
            raise ValueError(
                f"enriquecer: a url não interpola campo nenhum do item "
                f"({_url_publica(self.url)}). todo item buscaria o MESMO recurso, "
                f"e uma chamada por item que devolve sempre a mesma coisa é uma "
                f"fonte, não um enriquecimento"
            )

    def describe(self) -> ResolverDescription:
        return ResolverDescription(
            name=self.name,
            cost_class=self.cost_class,
            summary=f"busca {_url_publica(self.url)} para cada item",
            consome=frozenset({self.kind}),
            produz=frozenset({self.produz}),
        )

    def resolve(self, work: WorkSet) -> ResolverOutput:
        resolucoes: list[Resolution] = []
        produzidos: list[WorkItem] = []
        for item in work.of_kind(self.kind):
            try:
                campos = campos_de(item.payload)
            except TypeError:
                _log.warning(
                    "enriquecer: item %s tem payload sem campos; pulado", item.id
                )
                continue
            try:
                url = self.url.format_map(campos)
            except KeyError as erro:
                # NOMEIA o campo, como `_prompt_do_item` faz: sem isto quem
                # monta o workflow vê só a lacuna e não sabe se errou o nome do
                # campo ou se a API caiu.
                _log.warning(
                    "enriquecer: a url cita %s e o item %s não tem esse campo; "
                    "disponíveis: %s",
                    erro,
                    item.id,
                    sorted(campos),
                )
                continue
            try:
                dados = self._buscar(url)
            except VariavelAusente:
                # Credencial é CONFIGURAÇÃO: falha alto, uma vez. Abster item a
                # item por falta de token gastaria a fila para não fazer nada.
                raise
            except ErroDeFonte as erro:
                _log.warning("enriquecer: item %s não enriquecido — %s", item.id, erro)
                continue
            if not isinstance(dados, dict):
                _log.warning(
                    "enriquecer: item %s — a resposta em %r não é objeto (%s); "
                    "não há campos para fundir",
                    item.id,
                    self.caminho or "(corpo)",
                    type(dados).__name__,
                )
                continue
            # O ORIGINAL vence: uma resposta de fora não reescreve o campo que
            # identifica o item. Regra oposta à do `BlocoTarefa`, e a assimetria
            # é deliberada — ver o docstring do módulo e a spec.
            descartados = sorted(set(dados) & set(campos))
            if descartados:
                _log.info(
                    "enriquecer: item %s — campos da resposta descartados por "
                    "colisão com o item: %s",
                    item.id,
                    descartados,
                )
            produzidos.append(
                WorkItem(
                    id=f"{item.id}+{self.produz}",
                    kind=self.produz,
                    payload={**dados, **campos},
                    origem=self.name,
                )
            )
            resolucoes.append(
                Resolution(
                    item_ids=frozenset({item.id}),
                    produced_by=self.name,
                    rule=self.name,
                    evidence={"url": _url_publica(url)},
                )
            )
        return ResolverOutput(resolutions=resolucoes, produced=tuple(produzidos))

    def _buscar(self, url: str) -> Any:
        """Uma requisição, com as MESMAS guardas da fonte HTTP."""
        import json

        _guarda_url(url)
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
                with cliente.stream("GET", url, headers=cabecalhos) as resposta:
                    if not 200 <= resposta.status_code < 300:
                        # Só status e a url PÚBLICA: o corpo pode ecoar o token.
                        raise FonteFalhou(
                            f"GET {_url_publica(url)} devolveu {resposta.status_code}"
                        )
                    corpo = _ler_com_teto(resposta, self.max_bytes)
        except ErroDeFonte:
            raise
        except Exception as erro:
            _log.error("enriquecer:%s — requisição falhou: %s", _url_publica(url), erro)
            raise FonteFalhou(f"requisição falhou: {type(erro).__name__}") from erro
        try:
            dados = json.loads(corpo)
        except ValueError as erro:
            raise FonteFalhou("a resposta não é JSON") from erro
        return _seguir(dados, self.caminho)
```

Acrescentar `import os` no topo junto dos demais.

- [ ] **Step 5: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/sources/test_enriquecimento.py -q`
Expected: 11 passed.

- [ ] **Step 6: Suíte, lint e commit**

```bash
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check src tests
git add src/orchestrator/sources/enriquecimento.py tests/sources/test_enriquecimento.py docs/superpowers/specs/2026-09-22-bloco-enrich-e-o-caso-barrier-design.md
git commit -m "feat(sources): Enrich — a regra que busca o detalhe de cada item"
```

Corpo: por que mora em `sources` e não em `regras` (a catraca), por que consome e produz, e a regra de colisão com o motivo.

---

### Task 2: O bloco no catálogo

**Files:**
- Modify: `src/orchestrator/domains/registro.py` (uma `RegraDisponivel` nova)
- Test: `tests/domains/test_registro.py` (ou o arquivo que já cobre o catálogo — conferir o nome antes)

**Interfaces:**
- Consumes: `Enriquecimento` (Task 1).
- Produces: a entrada `enriquecer` no `CATALOGO`, categoria `DATA`, rótulo `Enrich`.

- [ ] **Step 1: Write the failing test**

```python
def test_o_bloco_ENRIQUECER_esta_no_catalogo_e_compoe():
    """Ele precisa estar no catálogo para existir na paleta e no `enum` da
    ferramenta do chat — é por ali que um bloco novo chega a quem monta."""
    from orchestrator.domains.registro import CATALOGO

    regra = next(r for r in CATALOGO.regras if r.nome == "enriquecer")

    assert regra.categoria == "DATA"
    assert {p.nome for p in regra.parametros} >= {"kind", "produz", "url", "token_env", "caminho"}
    resolver = regra.construir(
        {
            "kind": "caso",
            "produz": "caso_completo",
            "url": "https://api.exemplo.test/v1/assessments/{assessmentId}",
        }
    )
    assert resolver.describe().consome == frozenset({"caso"})
    assert resolver.describe().produz == frozenset({"caso_completo"})
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/domains -q -k enriquecer`
Expected: FAIL com `StopIteration` — não há `enriquecer` no catálogo.

- [ ] **Step 3: Registrar no catálogo**

Em `src/orchestrator/domains/registro.py`, ao lado das outras regras genéricas:

```python
        RegraDisponivel(
            nome="enriquecer",
            rotulo="Enrich",
            categoria="DATA",
            cost_class=CostClass.REGRA,
            resumo="busca numa API o detalhe de cada item e funde no payload",
            parametros=(
                ParametroDeRegra("kind", "", "o kind que entra neste bloco", obrigatorio=True),
                ParametroDeRegra(
                    "produz", "", "o kind que sai, já enriquecido", obrigatorio=True
                ),
                ParametroDeRegra(
                    "url",
                    "",
                    "a url, com {campo} do item — ex.: https://api/v1/casos/{id}",
                    obrigatorio=True,
                ),
                ParametroDeRegra(
                    "token_env", "", "o NOME da variável de ambiente com o bearer"
                ),
                ParametroDeRegra(
                    "caminho", "", "onde o objeto está no corpo (vazio = o corpo inteiro)"
                ),
            ),
            construir=lambda p: _enriquecimento(p),
        ),
```

e a fábrica, junto das outras `_`:

```python
def _enriquecimento(p: dict[str, Any]):
    """`token_env` vazio vira `None`: a tela manda string vazia quando o campo
    não foi preenchido, e `""` como NOME de variável pediria uma variável
    chamada vazio — `VariavelAusente("")`, que não diz nada a ninguém."""
    from orchestrator.sources.enriquecimento import Enriquecimento

    token = str(p.get("token_env", "")).strip()
    return Enriquecimento(
        kind=str(p["kind"]),
        produz=str(p["produz"]),
        url=str(p["url"]),
        token_env=token or None,
        caminho=str(p.get("caminho", "")),
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/domains -q`
Expected: PASS.

- [ ] **Step 5: Conferir que a tela e o chat o enxergam sem mudança**

Run: `.venv/Scripts/python.exe -c "from orchestrator.grill.ferramentas import _nomes_de_regra; print('enriquecer' in _nomes_de_regra())"`
Expected: `True` — o `enum` da ferramenta do chat é derivado do catálogo, e a paleta lê `/api/catalogo`. Nenhum código de front muda.

- [ ] **Step 6: Suíte, lint e commit**

```bash
.venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m ruff check src tests
git add src/orchestrator/domains/registro.py tests/domains
git commit -m "feat(catalogo): o bloco Enrich entra na paleta e no chat"
```

---

### Task 3: O caso Barrier, ponta a ponta

**Files:**
- Create: `data/composicoes/mesa-barrier.json` (via a API, não à mão)
- Nenhum arquivo de `src/` muda nesta tarefa.

**Interfaces:**
- Consumes: tudo das Tasks 1 e 2.

- [ ] **Step 1: Subir o Barrier por container**

```bash
cd /c/Dev/barrier
docker compose up -d                                   # Postgres, Kafka, Kafka UI
docker build --build-arg SERVICE=risk-engine -t barrier/risk-engine .
```

A Risk Engine sobe como container na MESMA rede do compose (o `docker-compose.yml` de lá não a inclui), publicando a 8080 e apontando `SPRING_DATASOURCE_URL` e o bootstrap do Kafka para os serviços da rede. O primeiro build baixa o mundo — conte minutos.

Expected: `GET http://<ip-da-lan>:8080/actuator/health` responde `UP`, e o log da subida imprime a chave de desenvolvimento (`API key de DESENVOLVIMENTO emitida...`).

**O endereço NÃO pode ser `localhost`.** A guarda de host recusa loopback, de propósito — use o IP da máquina na LAN (`192.168.x.x`), que a guarda declara não cobrir.

- [ ] **Step 2: Semear a mesa com casos determinísticos**

O corpo sai da collection Postman do Barrier (`docs/api/barrier-risk-engine.postman_collection.json`), não de invenção — são três campos:

```bash
# Caso 1: PEP. Cai em revisao humana (EDD) pelo screening, nao pelo bureau.
curl -X POST http://<ip>:8080/v1/assessments \
  -H "Authorization: Bearer <api-key-de-dev>" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: seed-pep" \
  -d '{"documentType": "CPF", "document": "529.982.247-25", "name": "Fulano Pep Exemplo"}'

# Caso 2: divergencia de bureau. O quarto digito do CPF 999... escolhe o desfecho:
# 999.300.000-03 = SUSPENSA -> MISMATCH -> EM_REVISAO.
curl -X POST http://<ip>:8080/v1/assessments \
  -H "Authorization: Bearer <api-key-de-dev>" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: seed-mismatch" \
  -d '{"documentType": "CPF", "document": "999.300.000-03", "name": "Fulano Divergente"}'
```

**Dois motivos DIFERENTES de propósito.** Um caso de PEP e um de divergência de
identidade dão ao agente dois resíduos distintos para classificar — se os dois
fossem iguais, a demonstração provaria que o modelo repete, não que ele lê.

Expected: `GET /v1/mesa/queues/ANALISE_PADRAO` devolve dois `CaseSummary`.

- [ ] **Step 3: Guardar o token como variável do cliente**

```bash
curl -X PUT http://localhost:8111/api/ambiente/variaveis/BARRIER_TOKEN \
  -H "Content-Type: application/json" -d '{"valor": "<api-key-de-dev>"}'
```

É a indireção de segredo que o orquestrador já tem: o valor entra no ambiente do processo e **o workflow guarda só o NOME**.

- [ ] **Step 4: Compor o workflow pela API**

`POST /api/composicoes` com três etapas — `entrada` (a fila), `enriquecer` (o detalhe), `agente` (a classificação). O `caminho` do `enriquecer` aponta o subobjeto do screening, **não** o cadastro inteiro: é a minimização de dado pessoal que a §4.2 da spec pede.

Expected: 201, e o workflow aparece em `GET /api/workflows`.

- [ ] **Step 5: Rodar**

```bash
curl -X POST http://localhost:8111/api/workflows/mesa-barrier/runs \
  -H "Content-Type: application/json" -d '{"teto_microcents": 5000000}'
```

Expected: 200, com `enriquecer` resolvendo 2 itens a 0 µ¢ e o agente propondo sobre `caso_completo`. As propostas aparecem em `GET /api/fila/mesa-barrier/propostas?ref=<input_ref>`, com o risco do Barrier citado na evidência.

**O modelo aqui é Haiku ou gravado, não Opus** — é uma verificação, não produção.

- [ ] **Step 6: Derrubar um caso de propósito**

Parar a Risk Engine (`docker stop`) e rodar de novo.

Expected: o run CONCLUI, os itens ficam na lacuna, e o log do servidor diz `enriquecer: item <id> não enriquecido — requisição falhou`. É o critério de aceite nº 2 da spec.

- [ ] **Step 7: Registrar o que foi medido**

Acrescentar ao final da spec uma seção "Executado em 2026-09-22" com os números reais: quantos casos, custo do run, e o que a fila recebeu. Commit:

```bash
git add docs/superpowers/specs/2026-09-22-bloco-enrich-e-o-caso-barrier-design.md
git commit -m "docs(spec): o caso Barrier rodou — os numeros"
```

---

## Fora deste plano, de propósito

- **Escrever a decisão no Barrier.** Exige a primeira ferramenta WRITE, com compensadora.
- **Paginação e cache.** A fonte HTTP já os deixou de fora com o motivo escrito.
- **Paralelismo.** 200 casos são 200 chamadas em série; o motor é sequencial e isso está declarado como risco na spec.
