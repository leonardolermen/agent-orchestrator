# Grill de Conciliação — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a partir de uma descrição em prosa, o maestro entrevista o parceiro e produz uma `WorkflowDefinition` executável — ou declara que o caso não cabe no catálogo.

**Architecture:** um catálogo de resolvers serve como fonte única do schema da ferramenta **e** do construtor, de modo que toda receita gerada roda por construção. A entrevista é aberta (o modelo escolhe as perguntas) mas a saída é tipada em três ferramentas, e validar uma proposta é tentar construí-la — as restrições ficam nos `__post_init__` dos resolvers, nunca duplicadas.

**Tech Stack:** Python 3.11+, dataclasses, argparse, FastAPI (já presente), `claude-agent-sdk` (opcional, última tarefa), pytest.

**Spec:** [`docs/superpowers/specs/2026-09-15-grill-de-conciliacao-design.md`](../specs/2026-09-15-grill-de-conciliacao-design.md)

## Global Constraints

- **Dinheiro é `int`.** Centavos para valores em BRL; micro-centavos de USD (`microcents`) para custo de API. Nunca `float`.
- **Nenhum endpoint da API pode gastar dinheiro.** A API sempre constrói com `cliente=ClienteAusente()` e `context=ToolContext([], [])`. Só a CLI passa cliente e contexto reais.
- **O golden de 12 sementes tem que reproduzir byte-idêntico.** Rodar `pytest tests/` inteiro antes de cada commit.
- **`default_definition()` e a cascata `["L1","L2","L3","revisor"]` não mudam.** Esta fatia acrescenta; não altera o conciliador embutido.
- **Nada sob `data/` é versionado.** A `justificativa` de uma receita carrega a descrição do problema do parceiro — dado de terceiro.
- **Toda restrição de parâmetro vive no `__post_init__` do resolver**, nunca duplicada no catálogo.
- **Um teste que passa com a implementação errada não é teste.** Para cada teste escrito, quebre a implementação de propósito e mostre o teste falhando antes de seguir.
- **Comentários e mensagens em português**, seguindo o estilo do repositório: explique *por quê*, não *o quê*.
- **Ferramentas vivem no venv, NÃO no PATH.** Todo comando do plano roda como
  `.venv/Scripts/python.exe -m pytest ...` e `.venv/Scripts/python.exe -m ruff ...`.
  Consoles scripts: `.venv/Scripts/orchestrator.exe`, `.venv/Scripts/orchestrator-grill.exe`.
  `pytest`/`ruff` pelados falham com "command not found".
- **Ruff limpo:** `ruff check src tests` antes de cada commit. `line-length = 100`.
  NÃO rode `ruff format`: 39 arquivos pré-existentes seriam reformatados e o diff
  real ficaria enterrado sob ruído alheio. Só o lint é o padrão exercido aqui.

---

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `src/orchestrator/grill/__init__.py` | vazio |
| `src/orchestrator/grill/catalogo.py` | `ParametroSpec`, `EntradaCatalogo`, `CATALOGO`, `ClienteAusente` |
| `src/orchestrator/grill/receita.py` | `ResolverReceita`, `Receita`, `para_json`/`de_json`, `construir` |
| `src/orchestrator/grill/prompt.py` | `SYSTEM` da entrevista |
| `src/orchestrator/grill/ferramentas.py` | `esquemas()`, `interpretar()`, tipos de saída |
| `src/orchestrator/grill/entrevistador.py` | `Entrevistador`, o laço, `EntrevistaFalhou` |
| `src/orchestrator/grill/registro.py` | receitas e recusas em disco |
| `src/orchestrator/grill/cli.py` | `orchestrator-grill` |
| `src/orchestrator/grill/assinatura.py` | `ClienteAssinatura` (LLMClient sobre o SDK) |

Modificados: `.gitignore`, `pyproject.toml`, `src/orchestrator/api/app.py`, `src/orchestrator/api/schemas.py`, `web/index.html`, `web/canvas.js`.

---

### Task 1: Catálogo e `ClienteAusente`

**Files:**
- Create: `src/orchestrator/grill/__init__.py` (vazio)
- Create: `src/orchestrator/grill/catalogo.py`
- Test: `tests/grill/test_catalogo.py`

**Interfaces:**
- Consumes: `ExactMatcher`, `ToleranceMatcher`, `GroupingMatcher` de `orchestrator.matching.*`; `Investigator` de `orchestrator.agent.investigator`; `ToolContext` de `orchestrator.agent.tools`; `RevisorHumano` de `orchestrator.review.revisor`; `Fila` de `orchestrator.review.fila`; `CostClass`; `Resolver`, `LLMResponse`.
- Produces: `ParametroSpec(nome: str, default: int, descricao: str)`; `EntradaCatalogo(nome, cost_class, resumo, parametros: tuple[ParametroSpec, ...], construir: Callable)`; `CATALOGO: dict[str, EntradaCatalogo]` com chaves `"L1"`, `"L2"`, `"L3"`, `"agente"`, `"revisor"`; `ClienteAusente` com `model: str` precificado e `complete()` que levanta `RuntimeError`.
- Contrato de `construir`: **toda** entrada tem a mesma assinatura `construir(parametros: dict[str, int], *, fila: Fila, cliente: LLMClient, context: ToolContext) -> Resolver`. Uniforme de propósito — sem introspecção de assinatura, que é exatamente a armadilha que a Task 7 precisa travar em outro lugar.

- [ ] **Step 1: Escreva os testes que falham**

Crie `tests/grill/__init__.py` vazio e `tests/grill/test_catalogo.py`:

```python
import dataclasses

import pytest

from orchestrator.agent.proposal import Cost
from orchestrator.agent.tools import ToolContext
from orchestrator.grill.catalogo import CATALOGO, ClienteAusente, ParametroSpec
from orchestrator.review.fila import Fila
from orchestrator.workflow.cost_class import CostClass


def _inerte():
    return {"fila": Fila.vazia(), "cliente": ClienteAusente(), "context": ToolContext([], [])}


def test_toda_entrada_do_catalogo_constroi_com_os_defaults():
    # A propriedade central da fatia: o `enum` da ferramenta sai de
    # CATALOGO.keys(), então tudo que o modelo pode propor precisa construir.
    # É `for` sobre o catálogo, não exemplo: uma entrada nova entra coberta.
    for chave, entrada in CATALOGO.items():
        resolver = entrada.construir({}, **_inerte())
        assert resolver.cost_class is entrada.cost_class, chave


def test_resumo_do_catalogo_bate_com_o_describe_do_resolver():
    # Duas fontes de verdade para a mesma frase divergiriam na primeira
    # mudança, e a tela mostraria uma coisa e o motor outra.
    for chave, entrada in CATALOGO.items():
        resolver = entrada.construir({}, **_inerte())
        assert resolver.describe().summary == entrada.resumo, chave


def test_default_de_parametro_vem_do_proprio_resolver():
    # `max_cents` default 5 mora em ToleranceMatcher. Se alguém mudar lá e o
    # catálogo continuar dizendo 5, o modelo recebe informação falsa.
    from orchestrator.matching.tolerance import ToleranceMatcher

    campos = {f.name: f.default for f in dataclasses.fields(ToleranceMatcher)}
    specs = {p.nome: p.default for p in CATALOGO["L2"].parametros}
    assert specs["max_cents"] == campos["max_cents"]
    assert specs["max_business_days"] == campos["max_business_days"]


def test_parametro_inexistente_no_resolver_explode_na_construcao_do_catalogo():
    from orchestrator.grill.catalogo import _param
    from orchestrator.matching.tolerance import ToleranceMatcher

    with pytest.raises(ValueError, match="não tem campo"):
        _param(ToleranceMatcher, "tolerancia", "campo que não existe")


def test_cliente_ausente_tem_modelo_precificado():
    # `Investigator.__post_init__` chama Cost.zero().microcents(client.model).
    # Um nome inventado faria a construção levantar — e a entrada `agente`
    # deixaria de ser sequer DESENHÁVEL.
    Cost.zero().microcents(ClienteAusente().model)


def test_cliente_ausente_levanta_ao_ser_chamado():
    with pytest.raises(RuntimeError, match="ClienteAusente"):
        ClienteAusente().complete(system="s", messages=[], tools=[])


def test_o_catalogo_cobre_as_tres_classes_de_custo():
    classes = {e.cost_class for e in CATALOGO.values()}
    assert classes == {CostClass.REGRA, CostClass.AGENTE, CostClass.HUMANO}


def test_parametro_spec_e_imutavel():
    p = ParametroSpec(nome="x", default=1, descricao="d")
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.default = 2
```

- [ ] **Step 2: Rode e confirme que falham**

```bash
pytest tests/grill/test_catalogo.py -v
```
Esperado: FAIL — `ModuleNotFoundError: No module named 'orchestrator.grill'`.

- [ ] **Step 3: Implemente `catalogo.py`**

```python
"""O catálogo: a tabela única de resolvers proponíveis.

O `enum` do schema da ferramenta e o construtor usado pela validação saem
DAQUI, da mesma estrutura. Um resolver que o grill consegue propor é, por
construção, um resolver que o motor consegue rodar — não porque alguém valida,
mas porque não há de onde vir. Duas listas paralelas (uma no schema, outra no
construtor) seriam o join frágil que P3.2 já custou uma correção.
"""

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from orchestrator.agent.investigator import Investigator
from orchestrator.agent.llm import LLMClient, LLMResponse
from orchestrator.agent.tools import ToolContext
from orchestrator.matching.exact import ExactMatcher
from orchestrator.matching.grouping import GroupingMatcher
from orchestrator.matching.tolerance import ToleranceMatcher
from orchestrator.review.fila import Fila
from orchestrator.review.revisor import RevisorHumano
from orchestrator.workflow.cost_class import CostClass
from orchestrator.workflow.resolver import Resolver

# Um modelo REAL da tabela de preços, de propósito: `Investigator.__post_init__`
# chama `Cost.zero().microcents(self.client.model)` e um nome inventado faria a
# construção levantar — o que impediria até de DESENHAR um workflow com agente.
MODELO_INERTE = "claude-opus-5"


class ClienteAusente:
    """`LLMClient` sentinela: existe para ser construído, nunca para ser chamado.

    É o que permite à API construir e desenhar um resolver pago sem que exista
    caminho de execução paga atrás de um endpoint. O 409 do `app.py` é a porta
    educada; isto aqui é a tranca.
    """

    model: str = MODELO_INERTE

    def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        raise RuntimeError(
            "ClienteAusente.complete() foi chamado: algum caminho de execução "
            "chegou ao modelo por onde não deveria existir caminho nenhum"
        )


@dataclass(frozen=True)
class ParametroSpec:
    """O que o modelo pode propor para um resolver. DESCREVE, não valida.

    Não carrega faixa (mínimo/máximo) de propósito: as restrições já vivem nos
    `__post_init__` dos resolvers, e duplicá-las aqui criaria duas fontes de
    verdade que divergiriam na primeira mudança. Ver §3.2 do spec.
    """

    nome: str
    default: int
    descricao: str


@dataclass(frozen=True)
class EntradaCatalogo:
    nome: str
    cost_class: CostClass
    resumo: str
    parametros: tuple[ParametroSpec, ...]
    # Assinatura UNIFORME em todas as entradas, mesmo nas que ignoram quase
    # tudo: `construir(parametros, *, fila, cliente, context)`. Assinaturas
    # variáveis exigiriam introspecção para saber o que passar — e é
    # exatamente esse padrão que já nos deu um defeito silencioso no
    # `_construir_definicao` da API.
    construir: Callable[..., Resolver]


def _param(cls: type, nome: str, descricao: str) -> ParametroSpec:
    """Lê o default do PRÓPRIO resolver. Renomear o campo lá explode aqui, no
    import — alto, e não em silêncio com um default falso na tela."""
    campos = {f.name: f for f in dataclasses.fields(cls)}
    if nome not in campos:
        raise ValueError(f"{cls.__name__} não tem campo {nome!r}")
    return ParametroSpec(nome=nome, default=campos[nome].default, descricao=descricao)


def _l1(p: dict[str, int], *, fila: Fila, cliente: LLMClient, context: ToolContext) -> Resolver:
    return ExactMatcher()


def _l2(p: dict[str, int], *, fila: Fila, cliente: LLMClient, context: ToolContext) -> Resolver:
    return ToleranceMatcher(**p)


def _l3(p: dict[str, int], *, fila: Fila, cliente: LLMClient, context: ToolContext) -> Resolver:
    return GroupingMatcher(**p)


def _agente(p: dict[str, int], *, fila: Fila, cliente: LLMClient, context: ToolContext) -> Resolver:
    return Investigator(client=cliente, context=context, fila=fila, **p)


def _revisor(p: dict[str, int], *, fila: Fila, cliente: LLMClient, context: ToolContext) -> Resolver:
    return RevisorHumano(fila=fila)


CATALOGO: dict[str, EntradaCatalogo] = {
    "L1": EntradaCatalogo(
        nome="L1",
        cost_class=CostClass.REGRA,
        resumo="documento, valor e data coincidem exatamente",
        parametros=(),
        construir=_l1,
    ),
    "L2": EntradaCatalogo(
        nome="L2",
        cost_class=CostClass.REGRA,
        resumo="mesmo documento, com folga de valor e dias úteis",
        parametros=(
            _param(ToleranceMatcher, "max_cents", "folga máxima de valor, em centavos"),
            _param(
                ToleranceMatcher,
                "max_business_days",
                "folga máxima entre as datas, em dias úteis",
            ),
        ),
        construir=_l2,
    ),
    "L3": EntradaCatalogo(
        nome="L3",
        cost_class=CostClass.REGRA,
        resumo="um lançamento bancário cobrindo N contábeis do mesmo fornecedor",
        parametros=(
            _param(
                GroupingMatcher,
                "max_group_size",
                "quantos lançamentos contábeis um pagamento pode cobrir",
            ),
            _param(
                GroupingMatcher,
                "max_business_days",
                "janela de data do grupo, em dias úteis",
            ),
            _param(
                GroupingMatcher,
                "max_candidates",
                "teto de candidatos considerados; protege contra busca exponencial",
            ),
        ),
        construir=_l3,
    ),
    "agente": EntradaCatalogo(
        nome="agente",
        cost_class=CostClass.AGENTE,
        resumo="investiga o que as regras não resolveram e propõe uma explicação",
        parametros=(
            _param(Investigator, "max_turns", "turnos por divergência investigada"),
            _param(
                Investigator,
                "budget_microcents",
                "teto de gasto POR divergência, em micro-centavos de dólar",
            ),
            _param(
                Investigator,
                "budget_total_microcents",
                "teto de gasto da execução inteira, em micro-centavos de dólar",
            ),
        ),
        construir=_agente,
    ),
    "revisor": EntradaCatalogo(
        nome="revisor",
        cost_class=CostClass.HUMANO,
        resumo="aplica as decisões aprovadas na fila de revisão",
        parametros=(),
        construir=_revisor,
    ),
}
```

Nota: todos os `resumo` são literais, e `test_resumo_do_catalogo_bate_com_o_describe_do_resolver` trava a igualdade com o `describe()` de cada resolver. Se algum literal acima não bater exatamente com o `summary` do resolver correspondente, **corrija o literal lendo o `describe()` do arquivo do resolver** — não relaxe o teste. Confira em `src/orchestrator/matching/grouping.py` o texto exato de `L3`.

- [ ] **Step 4: Rode e confirme que passam**

```bash
pytest tests/grill/test_catalogo.py -v
```
Esperado: 8 passed.

- [ ] **Step 5: Mutação — quebre e confirme que o teste pega**

Faça, uma de cada vez, e confirme o FAIL antes de desfazer:
1. Em `ParametroSpec` de `max_cents`, troque `_param(...)` por `ParametroSpec("max_cents", 99, "...")` → `test_default_de_parametro_vem_do_proprio_resolver` FALHA.
2. Faça `ClienteAusente.complete` devolver `None` em vez de levantar → `test_cliente_ausente_levanta_ao_ser_chamado` FALHA.
3. Troque `MODELO_INERTE` por `"modelo-inventado"` → `test_cliente_ausente_tem_modelo_precificado` FALHA.

- [ ] **Step 6: Commit**

```bash
ruff check src tests && pytest tests/ -q
git add src/orchestrator/grill tests/grill
git commit -m "feat(grill): catálogo como tabela única e ClienteAusente"
```

---

### Task 2: `Receita` e `construir`

**Files:**
- Create: `src/orchestrator/grill/receita.py`
- Test: `tests/grill/test_receita.py`

**Interfaces:**
- Consumes: `CATALOGO`, `ClienteAusente` da Task 1; `Stage`, `WorkflowDefinition` de `orchestrator.workflow.definition`; `Fila`; `ToolContext`.
- Produces:
  - `ResolverReceita(nome: str, parametros: dict[str, int])`
  - `Receita(id: str, nome: str, justificativa: str, gerado_em: datetime, resolvers: tuple[ResolverReceita, ...])`
  - `para_json(r: Receita) -> dict`, `de_json(d: dict) -> Receita`
  - `construir(receita, *, fila=None, cliente=None, context=None) -> WorkflowDefinition` — defaults inertes: `Fila.vazia()`, `ClienteAusente()`, `ToolContext([], [])`
  - `ID_RESERVADOS: frozenset[str]` = `{"conciliacao"}`
  - `PADRAO_ID: re.Pattern` = `^[a-z][a-z0-9-]{2,39}$`
  - `validar_id(workflow_id: str) -> None` — levanta `ValueError` para id fora do padrão ou reservado. **Mora aqui, e só aqui**: a Task 4 e a Task 5 chamam esta função; nenhuma das duas reescreve a checagem. Duplicar um bloco lógico verbatim é defeito pelo rubric de revisão.

- [ ] **Step 1: Escreva os testes que falham**

`tests/grill/test_receita.py`:

```python
from datetime import UTC, datetime

import pytest

from orchestrator.grill.receita import (
    Receita,
    ResolverReceita,
    construir,
    de_json,
    para_json,
)
from orchestrator.workflow.cost_class import CostClass


def _receita(*resolvers: ResolverReceita, id: str = "acme") -> Receita:
    return Receita(
        id=id,
        nome="Conciliação Acme",
        justificativa="o parceiro consolida por fornecedor",
        gerado_em=datetime(2026, 9, 15, 12, 0, tzinfo=UTC),
        resolvers=tuple(resolvers),
    )


def test_construir_produz_definicao_com_os_parametros_propostos():
    r = _receita(
        ResolverReceita("L1", {}),
        ResolverReceita("L2", {"max_cents": 10, "max_business_days": 5}),
    )
    d = construir(r)

    assert d.id == "acme"
    assert d.name == "Conciliação Acme"
    cascata = d.stages[0].ordered()
    assert [x.name for x in cascata] == ["L1", "L2"]
    assert cascata[1].max_cents == 10
    assert cascata[1].max_business_days == 5


def test_construir_ordena_por_classe_de_custo_ignorando_a_ordem_proposta():
    # O modelo pode propor [revisor, L1]; o motor roda [L1, revisor]. Regra
    # antiga, não nova — `Stage.ordered()` já fazia isso com a embutida.
    r = _receita(ResolverReceita("revisor", {}), ResolverReceita("L1", {}))
    cascata = construir(r).stages[0].ordered()

    assert [x.name for x in cascata] == ["L1", "revisor"]
    assert [x.cost_class for x in cascata] == [CostClass.REGRA, CostClass.HUMANO]


def test_construir_rejeita_resolver_fora_do_catalogo():
    r = _receita(ResolverReceita("L9", {}))
    with pytest.raises(ValueError, match="L9"):
        construir(r)


def test_construir_rejeita_chave_de_parametro_desconhecida():
    # Ignorar em silêncio entregaria a tolerância default ao parceiro que
    # pediu 10 — e ninguém descobriria olhando a tela.
    r = _receita(ResolverReceita("L2", {"tolerancia": 10}))
    with pytest.raises(ValueError, match="tolerancia"):
        construir(r)


def test_construir_rejeita_resolver_repetido():
    # O segundo L2 roda sobre o pool que o primeiro esvaziou e casa zero: não
    # é erro para o Python, é uma camada de 0% inexplicável na tela.
    r = _receita(ResolverReceita("L2", {}), ResolverReceita("L2", {"max_cents": 9}))
    with pytest.raises(ValueError, match="repetido"):
        construir(r)


def test_construir_rejeita_cascata_vazia():
    with pytest.raises(ValueError, match="pelo menos um"):
        construir(_receita())


def test_construir_propaga_a_mensagem_do_post_init_do_resolver():
    # A validação É a construção: a faixa mora no resolver, e a mensagem dele
    # é o que volta ao modelo para ele corrigir.
    r = _receita(ResolverReceita("L2", {"max_cents": -1}))
    with pytest.raises(ValueError, match="max_cents não pode ser negativo"):
        construir(r)


def test_construir_usa_defaults_inertes():
    # Sem cliente e sem contexto, um workflow com agente ainda CONSTRÓI (logo
    # é desenhável) — e só explode se alguém tentar chamar o modelo.
    r = _receita(ResolverReceita("agente", {}))
    d = construir(r)

    agente = d.stages[0].ordered()[0]
    assert agente.cost_class is CostClass.AGENTE
    with pytest.raises(RuntimeError, match="ClienteAusente"):
        agente.client.complete(system="s", messages=[], tools=[])


def test_round_trip_json():
    r = _receita(
        ResolverReceita("L1", {}),
        ResolverReceita("L3", {"max_group_size": 3}),
    )
    assert de_json(para_json(r)) == r


def test_para_json_preserva_a_ordem_proposta():
    # A receita grava o que o modelo propôs, verbatim; a ordenação por classe
    # acontece na execução. Reordenar na serialização apagaria a intenção.
    r = _receita(ResolverReceita("revisor", {}), ResolverReceita("L1", {}))
    assert [x["nome"] for x in para_json(r)["resolvers"]] == ["revisor", "L1"]
```

- [ ] **Step 2: Rode e confirme que falham**

```bash
pytest tests/grill/test_receita.py -v
```
Esperado: FAIL — `ModuleNotFoundError: orchestrator.grill.receita`.

- [ ] **Step 3: Implemente `receita.py`**

```python
"""A forma serializável de um workflow, e a construção que a valida.

A receita é ENTRADA, não descrição servida: o loader constrói o objeto de
verdade e é esse objeto que a API serializa. O invariante do `definition.py` —
nunca uma descrição paralela ao motor — fica intacto.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from orchestrator.agent.llm import LLMClient
from orchestrator.agent.tools import ToolContext
from orchestrator.grill.catalogo import CATALOGO, ClienteAusente
from orchestrator.review.fila import Fila
from orchestrator.workflow.definition import Stage, WorkflowDefinition

PADRAO_ID = re.compile(r"^[a-z][a-z0-9-]{2,39}$")
ID_RESERVADOS = frozenset({"conciliacao"})


def validar_id(workflow_id: str) -> None:
    """Único lugar onde a forma de um id é decidida.

    Chamado pelo entrevistador (antes do primeiro turno, para não desperdiçar
    a conversa do parceiro) e pelo registro (antes de montar caminho, porque um
    id com `../` escreveria fora de `data/`). Dois pontos de chamada, uma
    lógica.
    """
    if not PADRAO_ID.match(workflow_id):
        raise ValueError(
            f"id inválido: {workflow_id!r}. use minúsculas, dígitos e hífen, "
            f"começando por letra, de 3 a 40 caracteres"
        )
    if workflow_id in ID_RESERVADOS:
        raise ValueError(f"id reservado: {workflow_id!r}")


@dataclass(frozen=True)
class ResolverReceita:
    nome: str
    parametros: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Receita:
    id: str
    nome: str
    justificativa: str
    gerado_em: datetime
    resolvers: tuple[ResolverReceita, ...]


def para_json(r: Receita) -> dict[str, Any]:
    return {
        "id": r.id,
        "nome": r.nome,
        "justificativa": r.justificativa,
        "gerado_em": r.gerado_em.isoformat(),
        # Ordem verbatim: é o que o modelo propôs. `Stage.ordered()` impõe a
        # ordem entre classes na EXECUÇÃO; reordenar aqui apagaria a intenção.
        "resolvers": [{"nome": x.nome, "parametros": dict(x.parametros)} for x in r.resolvers],
    }


def de_json(d: dict[str, Any]) -> Receita:
    return Receita(
        id=d["id"],
        nome=d["nome"],
        justificativa=d["justificativa"],
        gerado_em=datetime.fromisoformat(d["gerado_em"]),
        resolvers=tuple(
            ResolverReceita(nome=x["nome"], parametros=dict(x.get("parametros", {})))
            for x in d["resolvers"]
        ),
    )


def construir(
    receita: Receita,
    *,
    fila: Fila | None = None,
    cliente: LLMClient | None = None,
    context: ToolContext | None = None,
) -> WorkflowDefinition:
    """Valida construindo. Se retorna, a receita roda.

    Levantar `ValueError` aqui é o canal pelo qual o entrevistador devolve o
    erro ao modelo para ele corrigir — por isso as mensagens são escritas para
    serem lidas por um modelo, não só por uma pessoa.

    `is None` e não `or`: `Fila.vazia()` e `ToolContext([], [])` são objetos
    legítimos e um `or` os trocaria pelos defaults, transformando "fila vazia
    explícita" em "fila default" sem aviso.
    """
    if fila is None:
        fila = Fila.vazia()
    if cliente is None:
        cliente = ClienteAusente()
    if context is None:
        context = ToolContext([], [])

    if not receita.resolvers:
        raise ValueError("a cascata precisa de pelo menos um resolver")

    vistos: set[str] = set()
    resolvers = []
    for item in receita.resolvers:
        entrada = CATALOGO.get(item.nome)
        if entrada is None:
            raise ValueError(
                f"resolver desconhecido: {item.nome!r}. "
                f"disponíveis: {sorted(CATALOGO)}"
            )
        if item.nome in vistos:
            raise ValueError(
                f"resolver repetido na cascata: {item.nome!r}. o segundo rodaria "
                f"sobre o pool que o primeiro já esvaziou e casaria zero"
            )
        vistos.add(item.nome)

        conhecidos = {p.nome for p in entrada.parametros}
        desconhecidos = sorted(set(item.parametros) - conhecidos)
        if desconhecidos:
            raise ValueError(
                f"parâmetro desconhecido para {item.nome!r}: {desconhecidos}. "
                f"aceitos: {sorted(conhecidos)}"
            )

        resolvers.append(
            entrada.construir(dict(item.parametros), fila=fila, cliente=cliente, context=context)
        )

    return WorkflowDefinition(
        id=receita.id,
        name=receita.nome,
        stages=(Stage(name="conciliar lançamentos", cascade=tuple(resolvers)),),
    )
```

- [ ] **Step 4: Rode e confirme que passam**

```bash
pytest tests/grill/test_receita.py -v
```
Esperado: 10 passed.

- [ ] **Step 5: Mutação**

1. Remova a checagem de `desconhecidos` → `test_construir_rejeita_chave_de_parametro_desconhecida` FALHA com `TypeError` em vez de `ValueError`; confirme que falha, depois restaure.
2. Remova `vistos` → `test_construir_rejeita_resolver_repetido` FALHA.
3. Troque `if fila is None` por `fila = fila or Fila.vazia()` e rode `pytest tests/` — anote se algum teste pega. Se **nenhum** pegar, isso confirma por que o `is None` é comentado: a armadilha é real e invisível. Restaure.

- [ ] **Step 6: Commit**

```bash
ruff check src tests && pytest tests/ -q
git add src/orchestrator/grill/receita.py tests/grill/test_receita.py
git commit -m "feat(grill): Receita serializável e construir() que valida construindo"
```

---

### Task 3: As três ferramentas

**Files:**
- Create: `src/orchestrator/grill/prompt.py`
- Create: `src/orchestrator/grill/ferramentas.py`
- Test: `tests/grill/test_ferramentas.py`

**Interfaces:**
- Consumes: `CATALOGO` (Task 1); `ResolverReceita` (Task 2); `ToolCall` de `orchestrator.agent.llm`.
- Produces:
  - `SYSTEM: str` em `prompt.py`
  - `esquemas() -> list[dict]` — três schemas; o `enum` de `resolvers[].nome` vem de `sorted(CATALOGO)`
  - `Pergunta(texto: str)`, `PropostaBruta(nome, justificativa, resolvers: tuple[ResolverReceita, ...])`, `Recusa(motivo, o_que_faltaria)`
  - `interpretar(chamada: ToolCall) -> Pergunta | PropostaBruta | Recusa` — levanta `ValueError` para ferramenta ou argumento fora do contrato
  - `NOMES: tuple[str, ...]` = `("perguntar", "propor_workflow", "fora_do_catalogo")`

- [ ] **Step 1: Escreva os testes que falham**

`tests/grill/test_ferramentas.py`:

```python
import json

import pytest

from orchestrator.agent.llm import ToolCall
from orchestrator.grill.catalogo import CATALOGO
from orchestrator.grill.ferramentas import (
    NOMES,
    Pergunta,
    PropostaBruta,
    Recusa,
    esquemas,
    interpretar,
)


def test_sao_exatamente_tres_ferramentas():
    assert tuple(e["name"] for e in esquemas()) == NOMES


def test_enum_de_resolver_vem_do_catalogo():
    # Uma lista literal aqui e outra no catálogo divergiriam, e o modelo
    # poderia propor algo que `construir` não conhece — ou nunca ficar
    # sabendo de um resolver novo.
    proposta = next(e for e in esquemas() if e["name"] == "propor_workflow")
    item = proposta["input_schema"]["properties"]["resolvers"]["items"]
    assert item["properties"]["nome"]["enum"] == sorted(CATALOGO)


def test_propor_workflow_nao_aceita_id():
    # O id vem do --id da CLI, validado ANTES do primeiro turno. Deixar o
    # modelo propor um criaria duas fontes de verdade para a mesma chave, e a
    # do modelo só seria conhecida no fim — tarde para recusar sem
    # desperdiçar a conversa do parceiro.
    proposta = next(e for e in esquemas() if e["name"] == "propor_workflow")
    assert "id" not in proposta["input_schema"]["properties"]


def test_descricao_da_proposta_lista_os_parametros_de_cada_resolver():
    # JSON Schema não expressa "as chaves permitidas dependem do valor de
    # `nome`" sem oneOf combinatório. O modelo aprende isso pela descrição.
    proposta = next(e for e in esquemas() if e["name"] == "propor_workflow")
    texto = proposta["description"]
    assert "max_cents" in texto
    assert "max_group_size" in texto
    assert "L1" in texto


def test_esquemas_sao_serializaveis():
    json.dumps(esquemas(), ensure_ascii=False)


def test_interpretar_pergunta():
    r = interpretar(ToolCall(id="1", name="perguntar", arguments={"texto": "qual a data?"}))
    assert r == Pergunta(texto="qual a data?")


def test_interpretar_proposta():
    r = interpretar(
        ToolCall(
            id="1",
            name="propor_workflow",
            arguments={
                "nome": "Conciliação Acme",
                "justificativa": "consolidam por fornecedor",
                "resolvers": [
                    {"nome": "L1"},
                    {"nome": "L2", "parametros": {"max_cents": 10}},
                ],
            },
        )
    )
    assert isinstance(r, PropostaBruta)
    assert r.nome == "Conciliação Acme"
    assert r.resolvers[0].nome == "L1"
    assert r.resolvers[0].parametros == {}
    assert r.resolvers[1].parametros == {"max_cents": 10}


def test_interpretar_recusa():
    r = interpretar(
        ToolCall(
            id="1",
            name="fora_do_catalogo",
            arguments={"motivo": "é cartão, não extrato", "o_que_faltaria": "resolver de adquirente"},
        )
    )
    assert r == Recusa(motivo="é cartão, não extrato", o_que_faltaria="resolver de adquirente")


def test_interpretar_rejeita_ferramenta_desconhecida():
    with pytest.raises(ValueError, match="pensar"):
        interpretar(ToolCall(id="1", name="pensar", arguments={}))


def test_interpretar_rejeita_argumento_faltando():
    with pytest.raises(ValueError, match="texto"):
        interpretar(ToolCall(id="1", name="perguntar", arguments={}))


def test_interpretar_rejeita_pergunta_vazia():
    # Pergunta em branco travaria o laço esperando resposta a nada.
    with pytest.raises(ValueError, match="vazi"):
        interpretar(ToolCall(id="1", name="perguntar", arguments={"texto": "   "}))


def test_interpretar_rejeita_parametro_nao_inteiro():
    # Dinheiro e janelas são int. Um 10.5 aqui viraria float silencioso no
    # centavo — a invariante que o projeto inteiro protege.
    with pytest.raises(ValueError, match="inteiro"):
        interpretar(
            ToolCall(
                id="1",
                name="propor_workflow",
                arguments={
                    "nome": "x",
                    "justificativa": "y",
                    "resolvers": [{"nome": "L2", "parametros": {"max_cents": 10.5}}],
                },
            )
        )
```

- [ ] **Step 2: Rode e confirme que falham**

```bash
pytest tests/grill/test_ferramentas.py -v
```
Esperado: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implemente `prompt.py`**

```python
"""O system prompt da entrevista.

A entrevista é ABERTA de propósito: o modelo escolhe o que perguntar. O que o
prompt fixa não é a lista de perguntas, é a DISCIPLINA — não inventar valor que
não ouviu, não perguntar o que a descrição já respondeu, e sair por uma das
duas portas tipadas.
"""

SYSTEM = """Você é o maestro do Agent Orchestrator, conversando com um parceiro
que descreveu um problema de conciliação bancária.

Seu trabalho: entender o caso dele em detalhe suficiente para propor uma
cascata de resolução — e então propô-la.

Como conduzir:
- Leia a descrição com atenção. NÃO pergunte o que ela já respondeu.
- Pergunte uma coisa por vez, em português claro, sem jargão nosso.
- Pergunte o que MUDA a configuração. Se a resposta não altera nenhum
  parâmetro nem inclui/exclui um resolver, não pergunte.
- Você não vê os dados do parceiro. Tudo que souber vem da conversa.

Regras que não se quebram:
- NUNCA invente um valor que não ouviu. Se o parceiro não disse a tolerância,
  pergunte, ou omita o parâmetro para usar o default do resolver.
- Termine SEMPRE por `propor_workflow` ou `fora_do_catalogo`. Não escreva
  conclusões em texto solto: use as ferramentas.
- Se o caso não for conciliação de extrato bancário contra razão contábil, use
  `fora_do_catalogo`. Dizer "não dá" é uma resposta correta e útil — melhor que
  entregar uma cascata que não resolve o problema dele.
- A cascata tem um estágio. A ordem entre classes de custo é imposta pelo
  motor: regra, depois agente, depois humano. Não tente contorná-la.

Sobre custo: o agente investigador chama um modelo e gasta dinheiro de verdade.
Só o inclua se o parceiro indicar que precisa de investigação caso a caso, e
diga isso na justificativa."""
```

- [ ] **Step 4: Implemente `ferramentas.py`**

```python
"""As três ferramentas. Todo turno do modelo termina em exatamente uma.

`perguntar` é FERRAMENTA, e não texto livre, de propósito: se a pergunta fosse
prosa solta, "isto é uma pergunta ou o modelo pensando alto?" viraria
heurística, e um turno em que ele apenas comenta travaria o laço esperando
resposta a nada. Como ferramenta, o fim da entrevista é evento tipado.
"""

from dataclasses import dataclass
from typing import Any

from orchestrator.agent.llm import ToolCall
from orchestrator.grill.catalogo import CATALOGO
from orchestrator.grill.receita import ResolverReceita

NOMES = ("perguntar", "propor_workflow", "fora_do_catalogo")


@dataclass(frozen=True)
class Pergunta:
    texto: str


@dataclass(frozen=True)
class PropostaBruta:
    """Ainda não é `Receita`: falta o id (que vem da CLI) e a validação por
    construção (que é da Task 2)."""

    nome: str
    justificativa: str
    resolvers: tuple[ResolverReceita, ...]


@dataclass(frozen=True)
class Recusa:
    motivo: str
    o_que_faltaria: str


def _catalogo_em_texto() -> str:
    linhas = []
    for chave in sorted(CATALOGO):
        e = CATALOGO[chave]
        if e.parametros:
            params = "; ".join(
                f"{p.nome} (int, default {p.default}) — {p.descricao}" for p in e.parametros
            )
        else:
            params = "sem parâmetros"
        linhas.append(f"- {e.nome} [{e.cost_class.name}]: {e.resumo}. Parâmetros: {params}")
    return "\n".join(linhas)


def esquemas() -> list[dict[str, Any]]:
    return [
        {
            "name": "perguntar",
            "description": "Faz UMA pergunta ao parceiro e espera a resposta.",
            "input_schema": {
                "type": "object",
                "properties": {"texto": {"type": "string"}},
                "required": ["texto"],
            },
        },
        {
            "name": "propor_workflow",
            "description": (
                "Encerra a entrevista propondo a cascata. Resolvers disponíveis:\n"
                + _catalogo_em_texto()
                + "\n\nOmita um parâmetro para usar o default. Todo parâmetro é "
                "inteiro. Não repita um resolver na mesma cascata."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "nome": {
                        "type": "string",
                        "description": "rótulo legível, ex.: 'Conciliação Acme'",
                    },
                    "justificativa": {
                        "type": "string",
                        "description": "por que esta cascata resolve o caso descrito",
                    },
                    "resolvers": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                # Do catálogo, nunca literal: ver o teste que trava isto.
                                "nome": {"type": "string", "enum": sorted(CATALOGO)},
                                "parametros": {"type": "object"},
                            },
                            "required": ["nome"],
                        },
                    },
                },
                "required": ["nome", "justificativa", "resolvers"],
            },
        },
        {
            "name": "fora_do_catalogo",
            "description": (
                "Encerra a entrevista declarando que o caso não cabe no catálogo. "
                "Desfecho legítimo, não erro."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "motivo": {"type": "string"},
                    "o_que_faltaria": {
                        "type": "string",
                        "description": "que resolver precisaria existir",
                    },
                },
                "required": ["motivo", "o_que_faltaria"],
            },
        },
    ]


def _texto(args: dict[str, Any], chave: str) -> str:
    valor = args.get(chave)
    if not isinstance(valor, str):
        raise ValueError(f"argumento {chave!r} ausente ou não é texto")
    if not valor.strip():
        raise ValueError(f"argumento {chave!r} veio vazio")
    return valor


def interpretar(chamada: ToolCall) -> Pergunta | PropostaBruta | Recusa:
    args = chamada.arguments
    if chamada.name == "perguntar":
        return Pergunta(texto=_texto(args, "texto"))
    if chamada.name == "fora_do_catalogo":
        return Recusa(
            motivo=_texto(args, "motivo"),
            o_que_faltaria=_texto(args, "o_que_faltaria"),
        )
    if chamada.name == "propor_workflow":
        brutos = args.get("resolvers")
        if not isinstance(brutos, list) or not brutos:
            raise ValueError("argumento 'resolvers' ausente ou vazio")
        resolvers = []
        for item in brutos:
            if not isinstance(item, dict) or not isinstance(item.get("nome"), str):
                raise ValueError(f"item de 'resolvers' malformado: {item!r}")
            params = item.get("parametros") or {}
            if not isinstance(params, dict):
                raise ValueError(f"'parametros' de {item['nome']!r} não é objeto")
            limpos: dict[str, int] = {}
            for k, v in params.items():
                # `isinstance(True, int)` é True em Python: bool precisa de
                # exclusão explícita, senão `max_cents=true` viraria 1.
                if isinstance(v, bool) or not isinstance(v, int):
                    raise ValueError(
                        f"parâmetro {k!r} de {item['nome']!r} precisa ser inteiro, veio {v!r}"
                    )
                limpos[k] = v
            resolvers.append(ResolverReceita(nome=item["nome"], parametros=limpos))
        return PropostaBruta(
            nome=_texto(args, "nome"),
            justificativa=_texto(args, "justificativa"),
            resolvers=tuple(resolvers),
        )
    raise ValueError(f"ferramenta desconhecida: {chamada.name!r}. use uma de {list(NOMES)}")
```

- [ ] **Step 5: Rode e confirme que passam**

```bash
pytest tests/grill/test_ferramentas.py -v
```
Esperado: 12 passed.

- [ ] **Step 6: Mutação**

1. Troque `"enum": sorted(CATALOGO)` por `"enum": ["L1", "L2", "L3"]` → `test_enum_de_resolver_vem_do_catalogo` FALHA.
2. Remova a exclusão de `bool` e teste com `{"max_cents": True}` num teste temporário → confirme que passaria como `1`; restaure.
3. Faça `_texto` aceitar string vazia → `test_interpretar_rejeita_pergunta_vazia` FALHA.

- [ ] **Step 7: Commit**

```bash
ruff check src tests && pytest tests/ -q
git add src/orchestrator/grill/prompt.py src/orchestrator/grill/ferramentas.py tests/grill/test_ferramentas.py
git commit -m "feat(grill): três ferramentas com enum derivado do catálogo"
```

---

### Task 4: O entrevistador

**Files:**
- Create: `src/orchestrator/grill/entrevistador.py`
- Test: `tests/grill/test_entrevistador.py`

**Interfaces:**
- Consumes: `SYSTEM`, `esquemas`, `interpretar`, `Pergunta`, `PropostaBruta`, `Recusa` (Task 3); `Receita`, `construir` (Task 2); `LLMClient`, `LLMResponse`, `ToolCall`, `FakeLLMClient` de `orchestrator.agent.llm`; `Cost` de `orchestrator.agent.proposal`.
- Produces:
  - `Entrevistador(client, max_turnos=12, max_tentativas_formato=2, budget_microcents=<derivado>)`
  - `entrevistar(workflow_id: str, descricao: str, responder: Callable[[str], str]) -> Proposta | RecusaFinal`
  - `Proposta(receita: Receita, cost: Cost, transcricao: tuple[str, ...])`
  - `RecusaFinal(motivo: str, o_que_faltaria: str, cost: Cost, transcricao: tuple[str, ...])`
  - `EntrevistaFalhou(Exception)` com atributo `transcricao: tuple[str, ...]`

- [ ] **Step 1: Derive o orçamento default**

Rode este cálculo e anote o resultado:

```bash
python -c "
import json, sys
sys.path.insert(0, 'src')
from orchestrator.grill.prompt import SYSTEM
from orchestrator.grill.ferramentas import esquemas
from orchestrator.agent.proposal import Cost
overhead = len(SYSTEM) + len(json.dumps(esquemas(), ensure_ascii=False))
entrada = overhead // 4
print('overhead chars:', overhead, '-> tokens entrada:', entrada)
c = Cost(input_tokens=entrada, output_tokens=200, calls=1)
print('1 turno em opus-5, sem cache:', c.microcents('claude-opus-5'))
"
```

Multiplique o custo de um turno por `max_turnos` (12), some 50% de folga para o histórico que cresce turno a turno (que esta conta não modela), e arredonde para cima até um número limpo. Esse é o `budget_microcents` default. Escreva o número com a conta inteira em comentário, no formato do comentário de `Investigator.budget_microcents`.

- [ ] **Step 2: Escreva os testes que falham**

`tests/grill/test_entrevistador.py`:

```python
import json

import pytest

from orchestrator.agent.llm import FakeLLMClient, LLMResponse, ToolCall
from orchestrator.agent.proposal import Cost
from orchestrator.grill.entrevistador import (
    Entrevistador,
    EntrevistaFalhou,
    Proposta,
    RecusaFinal,
)


def _chamada(nome: str, **args) -> LLMResponse:
    return LLMResponse(
        text="", tool_calls=[ToolCall(id="t", name=nome, arguments=args)], cost=Cost.zero()
    )


def _propor(**extra):
    base = {
        "nome": "Conciliação Acme",
        "justificativa": "consolidam por fornecedor",
        "resolvers": [{"nome": "L1"}, {"nome": "L2", "parametros": {"max_cents": 10}}],
    }
    base.update(extra)
    return _chamada("propor_workflow", **base)


class _Respostas:
    """Substitui stdin: devolve respostas na ordem e registra as perguntas."""

    def __init__(self, *respostas: str) -> None:
        self.perguntas: list[str] = []
        self._respostas = list(respostas)

    def __call__(self, pergunta: str) -> str:
        self.perguntas.append(pergunta)
        assert self._respostas, f"o modelo perguntou {len(self.perguntas)} vezes; o teste previu menos"
        return self._respostas.pop(0)


def test_entrevista_feliz_produz_receita():
    cliente = FakeLLMClient([
        _chamada("perguntar", texto="data de caixa ou competência?"),
        _propor(),
    ])
    responder = _Respostas("caixa")

    r = Entrevistador(client=cliente).entrevistar("acme", "conciliamos NF com extrato", responder)

    assert isinstance(r, Proposta)
    assert r.receita.id == "acme"
    assert r.receita.nome == "Conciliação Acme"
    assert [x.nome for x in r.receita.resolvers] == ["L1", "L2"]
    assert r.receita.resolvers[1].parametros == {"max_cents": 10}
    assert responder.perguntas == ["data de caixa ou competência?"]


def test_a_descricao_entra_como_primeiro_turno_do_usuario():
    cliente = FakeLLMClient([_propor()])
    Entrevistador(client=cliente).entrevistar("acme", "MINHA DESCRIÇÃO", _Respostas())

    primeira = cliente.chamadas[0]["messages"][0]
    assert primeira["role"] == "user"
    assert "MINHA DESCRIÇÃO" in json.dumps(primeira, ensure_ascii=False)


def test_proposta_invalida_volta_ao_modelo_com_a_mensagem_do_resolver():
    # A asserção é sobre o que o modelo RECEBEU, não sobre o resultado final.
    # Asserção só no resultado passaria com um laço que ignorou o erro e deu
    # sorte no turno seguinte.
    cliente = FakeLLMClient([
        _propor(resolvers=[{"nome": "L2", "parametros": {"max_cents": -1}}]),
        _propor(),
    ])

    r = Entrevistador(client=cliente).entrevistar("acme", "d", _Respostas())

    assert isinstance(r, Proposta)
    enviado = json.dumps(cliente.chamadas[1]["messages"], ensure_ascii=False)
    assert "max_cents não pode ser negativo" in enviado


def test_erro_de_ferramenta_desconhecida_tambem_volta_ao_modelo():
    cliente = FakeLLMClient([_chamada("pensar"), _propor()])

    r = Entrevistador(client=cliente).entrevistar("acme", "d", _Respostas())

    assert isinstance(r, Proposta)
    assert "ferramenta desconhecida" in json.dumps(cliente.chamadas[1]["messages"], ensure_ascii=False)


def test_tentativas_de_formato_esgotadas_falha_alto():
    ruim = _propor(resolvers=[{"nome": "L9"}])
    cliente = FakeLLMClient([ruim, ruim, ruim])

    with pytest.raises(EntrevistaFalhou, match="formato"):
        Entrevistador(client=cliente, max_tentativas_formato=2).entrevistar("acme", "d", _Respostas())


def test_turnos_esgotados_falha_alto_e_preserva_a_transcricao():
    # A conversa do parceiro não pode se perder por erro nosso.
    perguntas = [_chamada("perguntar", texto=f"p{i}") for i in range(3)]
    cliente = FakeLLMClient(perguntas)

    with pytest.raises(EntrevistaFalhou) as erro:
        Entrevistador(client=cliente, max_turnos=3).entrevistar(
            "acme", "d", _Respostas("a", "b", "c")
        )

    assert "turnos" in str(erro.value)
    assert any("p0" in linha for linha in erro.value.transcricao)


def test_recusa_e_desfecho_legitimo():
    cliente = FakeLLMClient([
        _chamada("fora_do_catalogo", motivo="é cartão", o_que_faltaria="resolver de adquirente")
    ])

    r = Entrevistador(client=cliente).entrevistar("acme", "concilio cartão", _Respostas())

    assert isinstance(r, RecusaFinal)
    assert r.motivo == "é cartão"
    assert r.o_que_faltaria == "resolver de adquirente"


def test_orcamento_estourado_falha_alto():
    caro = LLMResponse(
        text="",
        tool_calls=[ToolCall(id="t", name="perguntar", arguments={"texto": "p"})],
        cost=Cost(input_tokens=10_000_000, output_tokens=10_000_000, calls=1),
    )
    cliente = FakeLLMClient([caro, caro])

    with pytest.raises(EntrevistaFalhou, match="orçamento"):
        Entrevistador(client=cliente).entrevistar("acme", "d", _Respostas("a", "b"))


def test_orcamento_padrao_cobre_uma_entrevista_realista():
    # Trava a derivação do Step 1: se o prompt ou os schemas crescerem, o
    # default precisa crescer junto ou este teste quebra sozinho.
    from orchestrator.grill.entrevistador import ORCAMENTO_PADRAO
    from orchestrator.grill.ferramentas import esquemas
    from orchestrator.grill.prompt import SYSTEM

    overhead = len(SYSTEM) + len(json.dumps(esquemas(), ensure_ascii=False))
    um_turno = Cost(input_tokens=overhead // 4, output_tokens=200, calls=1)
    assert ORCAMENTO_PADRAO >= um_turno.microcents("claude-opus-5") * 12


def test_a_transcricao_registra_perguntas_e_respostas():
    cliente = FakeLLMClient([_chamada("perguntar", texto="qual a folga?"), _propor()])

    r = Entrevistador(client=cliente).entrevistar("acme", "d", _Respostas("uns 10 centavos"))

    juntas = "\n".join(r.transcricao)
    assert "qual a folga?" in juntas
    assert "uns 10 centavos" in juntas


def test_id_invalido_e_recusado_antes_do_primeiro_turno():
    # Descobrir isso no fim desperdiçaria a conversa inteira do parceiro.
    cliente = FakeLLMClient([])

    with pytest.raises(ValueError, match="id"):
        Entrevistador(client=cliente).entrevistar("Acme!", "d", _Respostas())

    assert cliente.chamadas == []
```

- [ ] **Step 3: Rode e confirme que falham**

```bash
pytest tests/grill/test_entrevistador.py -v
```
Esperado: FAIL — `ModuleNotFoundError`.

- [ ] **Step 4: Implemente `entrevistador.py`**

```python
"""O laço da entrevista.

Fala com `LLMClient` e nada mais — nunca com um SDK. É isso que permite provar
teto de turnos, retry de formato, orçamento e os três caminhos de saída com
`FakeLLMClient`: sem rede, sem um centavo. O adaptador de assinatura (a última
tarefa do plano) é uma classe substituível atrás deste protocolo.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from orchestrator.agent.llm import LLMClient
from orchestrator.agent.proposal import Cost
from orchestrator.grill.ferramentas import (
    Pergunta,
    PropostaBruta,
    Recusa,
    esquemas,
    interpretar,
)
from orchestrator.grill.prompt import SYSTEM
from orchestrator.grill.receita import Receita, construir, validar_id

# SUBSTITUA pelo número derivado no Step 1 desta tarefa, e cole a conta
# inteira neste comentário no formato do comentário de
# `Investigator.budget_microcents`. Não chute: o histórico deste projeto tem um
# defeito crítico causado exatamente por custo entrando onde não foi medido.
#
# `0` aqui é deliberado: faz `test_orcamento_padrao_cobre_uma_entrevista_realista`
# falhar na primeira execução, de modo que a tarefa não pode ser dada por
# pronta sem a derivação. (Os outros testes do laço passam com `0`, porque as
# respostas do `FakeLLMClient` custam `Cost.zero()` e `0 > 0` é falso — é o
# teste de orçamento, e só ele, que força a conta.) A ordem de grandeza
# esperada é dezenas de milhões de µ¢ (US$ 0,1–1,0 por entrevista de 12 turnos
# em opus-5); se o seu número sair fora disso, a conta está errada.
ORCAMENTO_PADRAO = 0  # SUBSTITUA — ver Step 1


class EntrevistaFalhou(Exception):
    """A entrevista não chegou a um desfecho. Nada é gravado.

    Carrega a transcrição: a conversa do parceiro não pode se perder por erro
    nosso.
    """

    def __init__(self, mensagem: str, transcricao: tuple[str, ...]) -> None:
        super().__init__(mensagem)
        self.transcricao = transcricao


@dataclass(frozen=True)
class Proposta:
    receita: Receita
    cost: Cost
    transcricao: tuple[str, ...]


@dataclass(frozen=True)
class RecusaFinal:
    motivo: str
    o_que_faltaria: str
    cost: Cost
    transcricao: tuple[str, ...]


@dataclass
class Entrevistador:
    client: LLMClient
    # Teto, não meta: uma entrevista que resolve em três turnos é melhor que
    # uma que usa os doze.
    max_turnos: int = 12
    max_tentativas_formato: int = 2
    budget_microcents: int = ORCAMENTO_PADRAO

    def entrevistar(
        self,
        workflow_id: str,
        descricao: str,
        responder: Callable[[str], str],
    ) -> Proposta | RecusaFinal:
        # ANTES do primeiro turno: descobrir um id inválido no fim
        # desperdiçaria a conversa inteira do parceiro. A checagem em si mora
        # em `receita.validar_id` — o registro chama a MESMA função.
        validar_id(workflow_id)

        ferramentas = esquemas()
        mensagens: list[dict[str, Any]] = [{"role": "user", "content": descricao}]
        transcricao: list[str] = [f"[parceiro] {descricao}"]
        total = Cost.zero()
        tentativas = 0

        for _ in range(self.max_turnos):
            resposta = self.client.complete(
                system=SYSTEM, messages=mensagens, tools=ferramentas
            )
            total = total + resposta.cost
            if total.microcents(self.client.model) > self.budget_microcents:
                raise EntrevistaFalhou(
                    "orçamento da entrevista esgotado", tuple(transcricao)
                )

            mensagens.append(self._turno_do_assistente(resposta))

            if not resposta.tool_calls:
                erro = "todo turno precisa terminar numa ferramenta; nenhuma foi chamada"
                mensagens.append(self._erro(None, erro))
                tentativas += 1
            else:
                chamada = resposta.tool_calls[0]
                try:
                    interpretada = interpretar(chamada)
                except ValueError as e:
                    mensagens.append(self._erro(chamada.id, str(e)))
                    tentativas += 1
                else:
                    if isinstance(interpretada, Pergunta):
                        transcricao.append(f"[maestro] {interpretada.texto}")
                        dita = responder(interpretada.texto)
                        transcricao.append(f"[parceiro] {dita}")
                        mensagens.append(self._resultado(chamada.id, dita))
                        continue
                    if isinstance(interpretada, Recusa):
                        return RecusaFinal(
                            motivo=interpretada.motivo,
                            o_que_faltaria=interpretada.o_que_faltaria,
                            cost=total,
                            transcricao=tuple(transcricao),
                        )
                    receita = self._receita(workflow_id, interpretada)
                    try:
                        # VALIDAR É CONSTRUIR. Se constrói, roda.
                        construir(receita)
                    except ValueError as e:
                        mensagens.append(self._erro(chamada.id, str(e)))
                        tentativas += 1
                    else:
                        return Proposta(
                            receita=receita, cost=total, transcricao=tuple(transcricao)
                        )

            if tentativas > self.max_tentativas_formato:
                raise EntrevistaFalhou(
                    f"formato inválido {tentativas} vezes seguidas", tuple(transcricao)
                )

        raise EntrevistaFalhou(
            f"a entrevista esgotou {self.max_turnos} turnos sem desfecho",
            tuple(transcricao),
        )

    @staticmethod
    def _receita(workflow_id: str, bruta: PropostaBruta) -> Receita:
        return Receita(
            id=workflow_id,
            nome=bruta.nome,
            justificativa=bruta.justificativa,
            gerado_em=datetime.now(UTC),
            resolvers=bruta.resolvers,
        )

    @staticmethod
    def _turno_do_assistente(resposta: Any) -> dict[str, Any]:
        """Devolve `raw_content` VERBATIM quando existe: é o único jeito de
        preservar blocos de raciocínio e de dar ao SDK real o mesmo objeto que
        ele emitiu. `FakeLLMClient` não preenche, e aí reconstruímos o mínimo.
        """
        if resposta.raw_content:
            return {"role": "assistant", "content": resposta.raw_content}
        blocos: list[dict[str, Any]] = []
        if resposta.text:
            blocos.append({"type": "text", "text": resposta.text})
        for c in resposta.tool_calls:
            blocos.append(
                {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
            )
        return {"role": "assistant", "content": blocos}

    @staticmethod
    def _resultado(tool_use_id: str, conteudo: str) -> dict[str, Any]:
        return {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tool_use_id, "content": conteudo}
            ],
        }

    @staticmethod
    def _erro(tool_use_id: str | None, mensagem: str) -> dict[str, Any]:
        if tool_use_id is None:
            return {"role": "user", "content": f"erro: {mensagem}"}
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "is_error": True,
                    "content": f"erro: {mensagem}",
                }
            ],
        }
```

- [ ] **Step 5: Rode e confirme que passam**

```bash
pytest tests/grill/test_entrevistador.py -v
```
Esperado: 11 passed. Se `test_orcamento_padrao_cobre_uma_entrevista_realista` falhar, o número do Step 1 está baixo — recalcule, não relaxe o teste.

- [ ] **Step 6: Mutação**

1. Troque `mensagens.append(self._erro(...))` (no ramo de `construir` falhando) por um `pass` → `test_proposta_invalida_volta_ao_modelo_com_a_mensagem_do_resolver` FALHA na asserção sobre `cliente.chamadas[1]`.
2. Remova a chamada a `validar_id` de `entrevistar` → `test_id_invalido_e_recusado_antes_do_primeiro_turno` FALHA.
3. Mova a checagem de orçamento para DEPOIS do `return` da proposta → `test_orcamento_estourado_falha_alto` FALHA.
4. Troque `for _ in range(self.max_turnos)` por `while True` → `test_turnos_esgotados_falha_alto_e_preserva_a_transcricao` trava; confirme com `pytest --timeout` ou Ctrl+C, depois restaure.

- [ ] **Step 7: Commit**

```bash
ruff check src tests && pytest tests/ -q
git add src/orchestrator/grill/entrevistador.py tests/grill/test_entrevistador.py
git commit -m "feat(grill): laço da entrevista com saída tipada e orçamento derivado"
```

---

### Task 5: Registro em disco e o `.gitignore`

**Files:**
- Create: `src/orchestrator/grill/registro.py`
- Modify: `.gitignore`
- Test: `tests/grill/test_registro.py`

**Interfaces:**
- Consumes: `Receita`, `para_json`, `de_json`, `validar_id` (Task 2); `RecusaFinal` (Task 4). **Não reescreva a validação de id** — importe `validar_id` de `receita.py`.
- Produces:
  - `_RAIZ_PADRAO: Path` = `Path("data")` — atributo de módulo, trocável por `tmp_path` no teste
  - `caminho_da_receita(id, raiz=None) -> Path` → `<raiz>/workflows/<id>.json`
  - `caminho_da_recusa(id, raiz=None) -> Path` → `<raiz>/grill/recusas/<id>.json`
  - `gravar_receita(r: Receita, raiz=None) -> Path` — levanta `ValueError` se o id já existe ou é reservado
  - `ler_receita(id, raiz=None) -> Receita`
  - `listar_receitas(raiz=None) -> list[Receita]` — ordenadas por id, arquivo ilegível é ignorado com aviso em `stderr`
  - `gravar_recusa(id, r: RecusaFinal, raiz=None) -> Path`

- [ ] **Step 1: Escreva os testes que falham**

`tests/grill/test_registro.py`:

```python
import json
from datetime import UTC, datetime

import pytest

from orchestrator.grill.receita import Receita, ResolverReceita
from orchestrator.grill.registro import (
    caminho_da_receita,
    gravar_receita,
    gravar_recusa,
    ler_receita,
    listar_receitas,
)


def _r(id: str = "acme") -> Receita:
    return Receita(
        id=id,
        nome="Acme",
        justificativa="j",
        gerado_em=datetime(2026, 9, 15, tzinfo=UTC),
        resolvers=(ResolverReceita("L1", {}),),
    )


def test_gravar_cria_o_diretorio_e_o_arquivo(tmp_path):
    # `data/` não existe num clone novo depois do .gitignore virar allowlist.
    caminho = gravar_receita(_r(), raiz=tmp_path)

    assert caminho == tmp_path / "workflows" / "acme.json"
    assert json.loads(caminho.read_text(encoding="utf-8"))["id"] == "acme"


def test_ler_devolve_a_mesma_receita(tmp_path):
    gravar_receita(_r(), raiz=tmp_path)
    assert ler_receita("acme", raiz=tmp_path) == _r()


def test_gravar_recusa_sobrescrever(tmp_path):
    # Sobrescrever mudaria, por baixo, o significado das decisões humanas já
    # gravadas sob esse workflow na fila.
    gravar_receita(_r(), raiz=tmp_path)
    with pytest.raises(ValueError, match="já existe"):
        gravar_receita(_r(), raiz=tmp_path)


def test_gravar_recusa_id_reservado(tmp_path):
    with pytest.raises(ValueError, match="reservado"):
        gravar_receita(_r("conciliacao"), raiz=tmp_path)


def test_gravar_recusa_id_fora_do_padrao(tmp_path):
    with pytest.raises(ValueError, match="id inválido"):
        gravar_receita(_r("Acme!"), raiz=tmp_path)


def test_id_com_travessia_de_caminho_e_recusado(tmp_path):
    # `PADRAO_ID` já barra, mas o teste existe porque a consequência de falhar
    # aqui é escrita fora de `data/`.
    with pytest.raises(ValueError, match="id inválido"):
        gravar_receita(_r("../fora"), raiz=tmp_path)
    assert not (tmp_path.parent / "fora.json").exists()


def test_listar_devolve_ordenado_por_id(tmp_path):
    gravar_receita(_r("zeta"), raiz=tmp_path)
    gravar_receita(_r("alfa"), raiz=tmp_path)

    assert [x.id for x in listar_receitas(raiz=tmp_path)] == ["alfa", "zeta"]


def test_listar_em_raiz_inexistente_devolve_vazio(tmp_path):
    assert listar_receitas(raiz=tmp_path / "nao-existe") == []


def test_listar_ignora_arquivo_corrompido(tmp_path, capsys):
    gravar_receita(_r("bom"), raiz=tmp_path)
    (tmp_path / "workflows" / "ruim.json").write_text("{isto não é json", encoding="utf-8")

    achadas = listar_receitas(raiz=tmp_path)

    assert [x.id for x in achadas] == ["bom"]
    assert "ruim" in capsys.readouterr().err


def test_gravar_recusa_escreve_motivo_e_lacuna(tmp_path):
    from orchestrator.agent.proposal import Cost
    from orchestrator.grill.entrevistador import RecusaFinal

    caminho = gravar_recusa(
        "acme",
        RecusaFinal(motivo="é cartão", o_que_faltaria="adquirente", cost=Cost.zero(), transcricao=()),
        raiz=tmp_path,
    )

    dados = json.loads(caminho.read_text(encoding="utf-8"))
    assert dados["motivo"] == "é cartão"
    assert dados["o_que_faltaria"] == "adquirente"


def test_caminho_da_receita_nao_cria_nada(tmp_path):
    # Montar caminho e criar diretório são responsabilidades diferentes: quem
    # cria é quem escreve. Mesma divisão de `caminho_da_fila` e `Fila._append`.
    caminho_da_receita("acme", raiz=tmp_path)
    assert not (tmp_path / "workflows").exists()
```

- [ ] **Step 2: Rode e confirme que falham**

```bash
pytest tests/grill/test_registro.py -v
```
Esperado: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implemente `registro.py`**

```python
"""Receitas e recusas em disco.

Nada aqui é versionado: a `justificativa` de uma receita carrega a descrição do
problema do parceiro — dado de terceiro, que o spec pai proíbe versionar. Ver o
`.gitignore`, que é allowlist sob `data/`.
"""

import json
import sys
from pathlib import Path

from orchestrator.grill.receita import Receita, de_json, para_json, validar_id

_RAIZ_PADRAO = Path("data")


def _raiz(raiz: Path | None) -> Path:
    # `is None`, não `or`: `Path("")` e `Path(".")` são objetos legítimos.
    return _RAIZ_PADRAO if raiz is None else raiz


def caminho_da_receita(workflow_id: str, raiz: Path | None = None) -> Path:
    return _raiz(raiz) / "workflows" / f"{workflow_id}.json"


def caminho_da_recusa(workflow_id: str, raiz: Path | None = None) -> Path:
    return _raiz(raiz) / "grill" / "recusas" / f"{workflow_id}.json"


def _escrever(caminho: Path, dados: dict) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    return caminho


def gravar_receita(receita: Receita, raiz: Path | None = None) -> Path:
    # ANTES de montar o caminho: um id com `../` escreveria fora de `data/`.
    validar_id(receita.id)
    caminho = caminho_da_receita(receita.id, raiz)
    if caminho.exists():
        raise ValueError(
            f"já existe uma receita com id {receita.id!r} em {caminho}. "
            f"sobrescrever mudaria o significado das decisões já gravadas na "
            f"fila desse workflow — escolha outro id"
        )
    return _escrever(caminho, para_json(receita))


def ler_receita(workflow_id: str, raiz: Path | None = None) -> Receita:
    caminho = caminho_da_receita(workflow_id, raiz)
    return de_json(json.loads(caminho.read_text(encoding="utf-8")))


def listar_receitas(raiz: Path | None = None) -> list[Receita]:
    pasta = _raiz(raiz) / "workflows"
    if not pasta.is_dir():
        return []
    achadas = []
    for caminho in sorted(pasta.glob("*.json")):
        try:
            achadas.append(de_json(json.loads(caminho.read_text(encoding="utf-8"))))
        except (json.JSONDecodeError, KeyError, ValueError) as erro:
            # Um arquivo corrompido não pode derrubar a listagem inteira — mas
            # também não pode sumir em silêncio.
            print(f"receita ignorada, ilegível: {caminho} ({erro})", file=sys.stderr)
    return achadas


def gravar_recusa(workflow_id: str, recusa, raiz: Path | None = None) -> Path:
    validar_id(workflow_id)
    return _escrever(
        caminho_da_recusa(workflow_id, raiz),
        {
            "id": workflow_id,
            "motivo": recusa.motivo,
            "o_que_faltaria": recusa.o_que_faltaria,
            "transcricao": list(recusa.transcricao),
        },
    )
```

- [ ] **Step 4: Corrija o `.gitignore`**

Substitua o bloco `# Dados` inteiro por:

```gitignore
# Dados
# Allowlist: NADA sob data/ é versionado por padrão. Receitas do grill
# carregam a descrição do problema do parceiro na `justificativa` — dado de
# terceiro, que o spec pai proíbe versionar. Remendo por diretório resolveria
# hoje e falharia na próxima fatia que escrevesse um formato novo, que foi
# exatamente como chegamos aqui (`*.jsonl` cobria a fila por acidente).
# Para versionar algo novo, adicione uma exceção explícita AQUI e diga por quê.
data/*
*.ofx
*.ret
```

Confirme que nada versionado foi perdido:

```bash
git ls-files data/
git status --porcelain
```
Esperado: a primeira vazia; a segunda mostra só `.gitignore` modificado.

- [ ] **Step 5: Rode e confirme que passam**

```bash
pytest tests/grill/test_registro.py -v
```
Esperado: 11 passed.

- [ ] **Step 6: Mutação**

1. Remova a chamada a `validar_id` de `gravar_receita` → `test_id_com_travessia_de_caminho_e_recusado` FALHA **e escreve fora de `tmp_path`**; confirme e restaure.
2. Remova o `if caminho.exists()` → `test_gravar_recusa_sobrescrever` FALHA.
3. Troque o `except` de `listar_receitas` por um `raise` → `test_listar_ignora_arquivo_corrompido` FALHA.

- [ ] **Step 7: Commit**

```bash
ruff check src tests && pytest tests/ -q
git add src/orchestrator/grill/registro.py tests/grill/test_registro.py .gitignore
git commit -m "feat(grill): registro em disco e .gitignore como allowlist sob data/"
```

---

### Task 6: A CLI `orchestrator-grill`

**Files:**
- Create: `src/orchestrator/grill/cli.py`
- Modify: `pyproject.toml` (seção `[project.scripts]`)
- Test: `tests/grill/test_cli.py`

**Interfaces:**
- Consumes: `Entrevistador`, `Proposta`, `RecusaFinal`, `EntrevistaFalhou` (Task 4); `gravar_receita`, `gravar_recusa` (Task 5); `construir` (Task 2); `build_benchmark` de `orchestrator.cli`; `reconcile` de `orchestrator.matching.engine`; `evaluate` de `orchestrator.metrics`.
- Produces: `main(argv: list[str] | None = None, *, entrevistador=None, responder=None) -> int` — os dois últimos são injeção para teste; em produção constrói o cliente de assinatura e usa `input`.
- Constante: `RESSALVA = "Este número é do NOSSO benchmark sintético, não dos seus dados."`

**Entrada de CLI separada, não subcomando:** `main()` de `orchestrator.cli` é argparse plano (`--seed/--n/--taxa-divergencia`); introduzir subcomandos quebraria a invocação de hoje sem ganho. Segue o padrão que `orchestrator-eval` já estabeleceu.

- [ ] **Step 1: Escreva os testes que falham**

`tests/grill/test_cli.py`:

```python
import pytest

from orchestrator.agent.llm import FakeLLMClient, LLMResponse, ToolCall
from orchestrator.agent.proposal import Cost
from orchestrator.grill import cli as grill_cli
from orchestrator.grill.entrevistador import Entrevistador


def _chamada(nome: str, **args) -> LLMResponse:
    return LLMResponse(
        text="", tool_calls=[ToolCall(id="t", name=nome, arguments=args)], cost=Cost.zero()
    )


def _propor() -> LLMResponse:
    return _chamada(
        "propor_workflow",
        nome="Acme",
        justificativa="j",
        resolvers=[{"nome": "L1"}, {"nome": "L2", "parametros": {"max_cents": 10}}],
    )


@pytest.fixture(autouse=True)
def _raiz_isolada(tmp_path, monkeypatch):
    # Sem isto os testes escreveriam no `data/` real do desenvolvedor — o
    # mesmo defeito que `tests/conftest.py` já corrige para a fila.
    monkeypatch.setattr(grill_cli, "_RAIZ", tmp_path)


def _rodar(argv, respostas, entrevistador):
    it = iter(respostas)
    return grill_cli.main(argv, entrevistador=entrevistador, responder=lambda _: next(it))


def test_entrevista_feliz_grava_e_imprime_o_numero(capsys, tmp_path):
    ent = Entrevistador(client=FakeLLMClient([_chamada("perguntar", texto="p?"), _propor()]))

    codigo = _rodar(["--id", "acme", "--descricao", "conciliamos NF"], ["r"], ent)

    assert codigo == 0
    assert (tmp_path / "workflows" / "acme.json").exists()
    saida = capsys.readouterr().out
    assert "acme" in saida
    assert "%" in saida


def test_a_ressalva_aparece_sempre_que_ha_percentual(capsys):
    # Mostrar "87,1%" a um parceiro sem dizer sobre o que foi medido é vender
    # número que não é dele. A linha é requisito, não rodapé.
    ent = Entrevistador(client=FakeLLMClient([_propor()]))

    _rodar(["--id", "acme", "--descricao", "d"], [], ent)

    saida = capsys.readouterr().out
    assert "%" in saida
    assert grill_cli.RESSALVA in saida


def test_recusa_grava_e_sai_com_zero(capsys, tmp_path):
    ent = Entrevistador(
        client=FakeLLMClient(
            [_chamada("fora_do_catalogo", motivo="é cartão", o_que_faltaria="adquirente")]
        )
    )

    codigo = _rodar(["--id", "acme", "--descricao", "d"], [], ent)

    assert codigo == 0
    assert (tmp_path / "grill" / "recusas" / "acme.json").exists()
    assert not (tmp_path / "workflows" / "acme.json").exists()
    assert "adquirente" in capsys.readouterr().out


def test_entrevista_falha_nao_grava_e_imprime_a_transcricao(capsys, tmp_path):
    perguntas = [_chamada("perguntar", texto=f"p{i}") for i in range(2)]
    ent = Entrevistador(client=FakeLLMClient(perguntas), max_turnos=2)

    codigo = _rodar(["--id", "acme", "--descricao", "d"], ["a", "b"], ent)

    assert codigo == 1
    assert not (tmp_path / "workflows" / "acme.json").exists()
    assert "p0" in capsys.readouterr().out


def test_id_colidindo_recusa_antes_de_entrevistar(capsys, tmp_path):
    # Descobrir a colisão no fim desperdiçaria a conversa do parceiro.
    (tmp_path / "workflows").mkdir(parents=True)
    (tmp_path / "workflows" / "acme.json").write_text("{}", encoding="utf-8")
    cliente = FakeLLMClient([])

    codigo = _rodar(["--id", "acme", "--descricao", "d"], [], Entrevistador(client=cliente))

    assert codigo == 2
    assert cliente.chamadas == []
    assert "já existe" in capsys.readouterr().err


def test_exige_descricao():
    with pytest.raises(SystemExit):
        grill_cli.main(["--id", "acme"])


def test_descricao_por_arquivo(tmp_path, capsys):
    arquivo = tmp_path / "caso.md"
    arquivo.write_text("DESCRIÇÃO DO ARQUIVO", encoding="utf-8")
    cliente = FakeLLMClient([_propor()])

    _rodar(
        ["--id", "acme", "--descricao-arquivo", str(arquivo)], [], Entrevistador(client=cliente)
    )

    import json as _json

    assert "DESCRIÇÃO DO ARQUIVO" in _json.dumps(cliente.chamadas[0]["messages"], ensure_ascii=False)
```

- [ ] **Step 2: Rode e confirme que falham**

```bash
pytest tests/grill/test_cli.py -v
```
Esperado: FAIL — `ModuleNotFoundError: orchestrator.grill.cli`.

- [ ] **Step 3: Implemente `cli.py`**

```python
"""`orchestrator-grill`: a entrevista no terminal.

Entrada separada, não subcomando de `orchestrator`: o `main()` de lá é argparse
plano e introduzir subcomandos quebraria a invocação de hoje sem ganho. Mesmo
padrão de `orchestrator-eval`.

A CLI PODE gastar dinheiro — é onde o investigador já roda. É a API que não
pode, e é por isso que o grill não ganhou rotas.
"""

import argparse
import sys
from pathlib import Path

from orchestrator.cli import build_benchmark
from orchestrator.grill.entrevistador import (
    Entrevistador,
    EntrevistaFalhou,
    Proposta,
    RecusaFinal,
)
from orchestrator.grill.receita import construir
from orchestrator.grill.registro import (
    caminho_da_receita,
    gravar_receita,
    gravar_recusa,
)
from orchestrator.matching.engine import reconcile
from orchestrator.metrics import evaluate

RESSALVA = "Este número é do NOSSO benchmark sintético, não dos seus dados."

# Atributo de módulo para o teste trocar por tmp_path sem escrever no
# repositório do desenvolvedor.
_RAIZ: Path | None = None


def _construir_entrevistador() -> Entrevistador:
    from orchestrator.grill.assinatura import ClienteAssinatura

    return Entrevistador(client=ClienteAssinatura())


def main(argv=None, *, entrevistador=None, responder=None) -> int:
    parser = argparse.ArgumentParser(
        description="Entrevista o parceiro e propõe uma cascata de conciliação"
    )
    parser.add_argument("--id", required=True, help="id do workflow, ex.: acme")
    fonte = parser.add_mutually_exclusive_group(required=True)
    fonte.add_argument("--descricao")
    fonte.add_argument("--descricao-arquivo")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--n", type=int, default=500)
    parser.add_argument("--taxa-divergencia", type=float, default=0.15)
    args = parser.parse_args(argv)

    # Colisão checada ANTES do primeiro turno: descobrir no fim desperdiçaria
    # a conversa inteira do parceiro.
    if caminho_da_receita(args.id, _RAIZ).exists():
        print(f"já existe uma receita com id {args.id!r}. escolha outro.", file=sys.stderr)
        return 2

    descricao = (
        args.descricao
        if args.descricao is not None
        else Path(args.descricao_arquivo).read_text(encoding="utf-8")
    )
    ent = entrevistador if entrevistador is not None else _construir_entrevistador()
    resp = responder if responder is not None else input

    try:
        resultado = ent.entrevistar(args.id, descricao, resp)
    except ValueError as erro:
        print(str(erro), file=sys.stderr)
        return 2
    except EntrevistaFalhou as erro:
        print(f"a entrevista não chegou a um desfecho: {erro}", file=sys.stderr)
        print("\n--- transcrição ---")
        for linha in erro.transcricao:
            print(linha)
        return 1

    if isinstance(resultado, RecusaFinal):
        caminho = gravar_recusa(args.id, resultado, _RAIZ)
        print(f"\nfora do catálogo: {resultado.motivo}")
        print(f"o que faltaria: {resultado.o_que_faltaria}")
        print(f"registrado em {caminho}")
        return 0

    assert isinstance(resultado, Proposta)
    caminho = gravar_receita(resultado.receita, _RAIZ)
    print(f"\n✓ {resultado.receita.nome} ({resultado.receita.id})")
    print(f"✓ {caminho}")
    _medir(resultado, args)
    print(f"→ http://localhost:8000/?workflow={args.id}")
    return 0


def _medir(proposta: Proposta, args) -> None:
    dataset = build_benchmark(args.seed, args.n, args.taxa_divergencia)
    definicao = construir(proposta.receita)
    resultado = reconcile(dataset.bank, dataset.ledger, definition=definicao)
    m = evaluate(dataset, resultado)

    total = m.bank_total
    partes = " · ".join(
        f"{nome} {(resultado.matches_by_resolver.get(nome, 0) / total if total else 0):.1%}"
        for nome in resultado.matches_by_resolver
    )
    lacuna = (total - m.bank_matched_total) / total if total else 0.0
    print(
        f"✓ benchmark (semente {args.seed}, n={args.n}): "
        f"{m.deterministic_rate:.1%} — {partes} · lacuna {lacuna:.1%}"
    )
    # Requisito, não rodapé: ver §8.2 do spec e o teste que o trava.
    print(f"  {RESSALVA}")


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Registre a entrada no `pyproject.toml`**

Na seção `[project.scripts]`, acrescente a terceira linha:

```toml
[project.scripts]
orchestrator = "orchestrator.cli:main"
orchestrator-eval = "orchestrator.eval.agent_eval:main"
orchestrator-grill = "orchestrator.grill.cli:main"
```

- [ ] **Step 5: Rode e confirme que passam**

```bash
pytest tests/grill/test_cli.py -v
```
Esperado: 7 passed.

- [ ] **Step 6: Mutação**

1. Remova a linha do `RESSALVA` de `_medir` → `test_a_ressalva_aparece_sempre_que_ha_percentual` FALHA.
2. Mova a checagem de colisão para DEPOIS de `ent.entrevistar(...)` → `test_id_colidindo_recusa_antes_de_entrevistar` FALHA na asserção `cliente.chamadas == []`.
3. No ramo de `EntrevistaFalhou`, troque `return 1` por `return 0` → `test_entrevista_falha_nao_grava_e_imprime_a_transcricao` FALHA.

- [ ] **Step 7: Commit**

```bash
ruff check src tests && pytest tests/ -q
git add src/orchestrator/grill/cli.py tests/grill/test_cli.py pyproject.toml
git commit -m "feat(grill): CLI orchestrator-grill com a ressalva do benchmark"
```

---

### Task 7: A API lê workflows gerados

**Files:**
- Modify: `src/orchestrator/api/app.py`
- Modify: `src/orchestrator/api/schemas.py`
- Test: `tests/api/test_workflows_gerados.py`
- Test: `tests/grill/test_fabrica.py`

**Interfaces:**
- Consumes: `listar_receitas`, `ler_receita` (Task 5); `construir` (Task 2).
- Produces (em `app.py`):
  - `fabrica_de(receita: Receita) -> Callable` — a função devolvida declara **o parâmetro `fila` pelo nome**
  - `_fabricas() -> dict[str, Callable]` — `{"conciliacao": default_definition}` mais uma entrada por receita em disco
  - rota `GET /api/workflows -> list[WorkflowResumoJSON]`
- Produces (em `schemas.py`): `WorkflowResumoJSON(id: str, nome: str, classes: list[str], gerado_em: str | None, executavel: bool)`

**Aviso ao implementador:** `_construir_definicao` decide repassar a fila **olhando o nome literal do parâmetro** (`inspect.signature`). Uma closure que declare `q` em vez de `fila` deixa a suíte inteira verde e faz o workflow gerado servir fila vazia em silêncio — o mesmo defeito que a Task 8 do plano anterior corrigiu. O teste em `tests/grill/test_fabrica.py` existe só para travar esse nome.

- [ ] **Step 1: Escreva os testes que falham**

`tests/grill/test_fabrica.py`:

```python
import inspect
from datetime import UTC, datetime

from orchestrator.api.app import fabrica_de
from orchestrator.grill.receita import Receita, ResolverReceita
from orchestrator.review.fila import Fila


def _r() -> Receita:
    return Receita(
        id="acme",
        nome="Acme",
        justificativa="j",
        gerado_em=datetime(2026, 9, 15, tzinfo=UTC),
        resolvers=(ResolverReceita("L1", {}), ResolverReceita("revisor", {})),
    )


def test_a_fabrica_de_receita_declara_o_parametro_fila():
    # `_construir_definicao` decide repassar a fila olhando o NOME literal
    # `fila` na assinatura. Renomear para `q` deixa tudo verde e faz o
    # workflow gerado servir fila vazia em silêncio.
    assert "fila" in inspect.signature(fabrica_de(_r())).parameters


def test_a_fabrica_repassa_a_fila_ao_revisor():
    fila = Fila.vazia()
    definicao = fabrica_de(_r())(fila)

    revisor = next(r for r in definicao.stages[0].ordered() if r.name == "revisor")
    assert revisor.fila is fila
```

`tests/api/test_workflows_gerados.py`:

```python
import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from orchestrator.api import app as app_mod
from orchestrator.grill.receita import Receita, ResolverReceita, para_json


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "_RAIZ_FILA", tmp_path)
    monkeypatch.setattr(app_mod, "_RAIZ_RECEITAS", tmp_path)
    app_mod._executar_memoizado.cache_clear()
    yield
    app_mod._executar_memoizado.cache_clear()


def _gravar(tmp_path, id: str, *resolvers: str) -> None:
    r = Receita(
        id=id,
        nome=f"W {id}",
        justificativa="j",
        gerado_em=datetime(2026, 9, 15, tzinfo=UTC),
        resolvers=tuple(ResolverReceita(n, {}) for n in resolvers),
    )
    destino = tmp_path / "workflows"
    destino.mkdir(parents=True, exist_ok=True)
    (destino / f"{id}.json").write_text(
        json.dumps(para_json(r), ensure_ascii=False), encoding="utf-8"
    )


def test_listar_inclui_a_embutida_e_as_geradas(tmp_path):
    _gravar(tmp_path, "acme", "L1", "revisor")
    cliente = TestClient(app_mod.app)

    dados = cliente.get("/api/workflows").json()

    ids = {x["id"] for x in dados}
    assert "conciliacao" in ids
    assert "acme" in ids


def test_workflow_gerado_tem_a_cascata_desenhavel(tmp_path):
    _gravar(tmp_path, "acme", "L1", "L2", "revisor")
    cliente = TestClient(app_mod.app)

    dados = cliente.get("/api/workflows/acme").json()

    assert [r["name"] for r in dados["resolvers"]] == ["L1", "L2", "revisor"]


def test_workflow_gerado_executa_e_fecha_a_lacuna(tmp_path):
    _gravar(tmp_path, "acme", "L1", "revisor")
    cliente = TestClient(app_mod.app)

    dados = cliente.post(
        "/api/workflows/acme/runs", json={"seed": 1, "n": 60, "taxa_divergencia": 0.15}
    ).json()

    soma = sum(r["rate"] for r in dados["by_resolver"]) + dados["gap"]["rate"]
    assert soma == pytest.approx(1.0)


def test_workflow_com_agente_e_listado_como_nao_executavel(tmp_path):
    _gravar(tmp_path, "pago", "L1", "agente")
    cliente = TestClient(app_mod.app)

    dados = cliente.get("/api/workflows").json()
    pago = next(x for x in dados if x["id"] == "pago")

    assert pago["executavel"] is False
    assert "AGENTE" in pago["classes"]


def test_id_desconhecido_continua_404(tmp_path):
    cliente = TestClient(app_mod.app)
    assert cliente.get("/api/workflows/nao-existe").status_code == 404
```

- [ ] **Step 2: Rode e confirme que falham**

```bash
pytest tests/grill/test_fabrica.py tests/api/test_workflows_gerados.py -v
```
Esperado: FAIL — `ImportError: cannot import name 'fabrica_de'`.

- [ ] **Step 3: Acrescente o schema em `schemas.py`**

```python
class WorkflowResumoJSON(BaseModel):
    id: str
    nome: str
    classes: list[str]
    gerado_em: str | None = None
    # Falso quando a cascata tem classe AGENTE: a tela desabilita o botão em
    # vez de deixar o usuário colher um 409.
    executavel: bool
```

- [ ] **Step 4: Modifique `app.py`**

Substitua `_WORKFLOWS = {"conciliacao": default_definition}` por:

```python
# Raiz das receitas em disco. Atributo de módulo para o teste trocar por
# tmp_path sem ler o `data/` real do desenvolvedor.
_RAIZ_RECEITAS: Path | None = None


def fabrica_de(receita: Receita):
    """Uma fábrica de workflow a partir de uma receita.

    O parâmetro chama-se `fila` PELO NOME, de propósito: `_construir_definicao`
    decide repassar a fila com `inspect.signature`, e não há import nem type
    check amarrando os dois lados. Renomear isto para `q` deixaria a suíte
    inteira verde e faria todo workflow gerado servir fila vazia em silêncio.
    Ver `tests/grill/test_fabrica.py`.

    Cliente e contexto ficam nos DEFAULTS INERTES de propósito: como `/runs`
    responde 409 para qualquer cascata com classe AGENTE (ver `_executar_memoizado`),
    nenhum workflow com agente chega a executar por um endpoint — então não
    existe caminho em que a API precise de um agente funcional, e portanto não
    existe código aqui que o construa.
    """

    def fabrica(fila: Fila) -> WorkflowDefinition:
        return construir(receita, fila=fila)

    return fabrica


def _fabricas() -> dict[str, object]:
    fabricas: dict[str, object] = {"conciliacao": default_definition}
    for receita in listar_receitas(_RAIZ_RECEITAS):
        # A embutida nunca é sobrescrita por disco: `conciliacao` é id
        # reservado no registro, e esta ordem é a segunda tranca.
        if receita.id in fabricas:
            continue
        fabricas[receita.id] = fabrica_de(receita)
    return fabricas
```

Troque os três usos de `_WORKFLOWS` (`obter_workflow`, `executar`, `_executar_memoizado`) por `_fabricas()`. Acrescente a rota:

```python
@app.get("/api/workflows", response_model=list[WorkflowResumoJSON])
def listar_workflows() -> list[WorkflowResumoJSON]:
    resumos = []
    por_id = {r.id: r for r in listar_receitas(_RAIZ_RECEITAS)}
    for workflow_id, fabrica in _fabricas().items():
        definicao = _construir_definicao(fabrica, Fila.vazia())
        classes = sorted(
            {r.cost_class.name for s in definicao.stages for r in s.cascade}
        )
        receita = por_id.get(workflow_id)
        resumos.append(
            WorkflowResumoJSON(
                id=workflow_id,
                nome=definicao.name,
                classes=classes,
                gerado_em=receita.gerado_em.isoformat() if receita else None,
                executavel=CostClass.AGENTE.name not in classes,
            )
        )
    return resumos
```

Acrescente os imports necessários: `from pathlib import Path` (já existe), `from orchestrator.grill.receita import Receita, construir`, `from orchestrator.grill.registro import listar_receitas`, `from orchestrator.workflow.cost_class import CostClass`, e `WorkflowResumoJSON` na lista de schemas.

**Cuidado com a ordem no arquivo:** `app.mount("/", StaticFiles(...))` tem que continuar sendo a ÚLTIMA instrução do módulo, ou as rotas novas ficam sombreadas pelo mount.

- [ ] **Step 5: Rode e confirme que passam**

```bash
pytest tests/grill/test_fabrica.py tests/api/test_workflows_gerados.py -v
```
Esperado: 7 passed.

- [ ] **Step 6: Mutação**

1. Renomeie o parâmetro de `fabrica` de `fila` para `q` → `test_a_fabrica_de_receita_declara_o_parametro_fila` FALHA **e** `test_a_fabrica_repassa_a_fila_ao_revisor` FALHA. Confirme os dois; é a prova de que o teste de nome não é cerimônia.
2. Mova o `app.mount` para antes da rota nova → `test_listar_inclui_a_embutida_e_as_geradas` FALHA com 404.

- [ ] **Step 7: Commit**

```bash
ruff check src tests && pytest tests/ -q
git add src/orchestrator/api tests/api/test_workflows_gerados.py tests/grill/test_fabrica.py
git commit -m "feat(api): registro de workflows gerados e GET /api/workflows"
```

---

### Task 8: O 409 e a tranca

**Files:**
- Modify: `src/orchestrator/api/app.py` (dentro de `_executar_memoizado`)
- Test: `tests/api/test_dinheiro_workflow_gerado.py`

**Interfaces:**
- Consumes: `_fabricas`, `_construir_definicao` (Task 7); `CostClass`; `ClienteAusente` (Task 1).
- Produces: `POST /api/workflows/{id}/runs` responde **409** quando a cascata contém classe `AGENTE`.

- [ ] **Step 1: Escreva os testes que falham**

`tests/api/test_dinheiro_workflow_gerado.py`:

```python
import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from orchestrator.api import app as app_mod
from orchestrator.grill import catalogo as cat_mod
from orchestrator.grill.receita import Receita, ResolverReceita, para_json


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "_RAIZ_FILA", tmp_path)
    monkeypatch.setattr(app_mod, "_RAIZ_RECEITAS", tmp_path)
    app_mod._executar_memoizado.cache_clear()
    yield
    app_mod._executar_memoizado.cache_clear()


def _gravar_pago(tmp_path) -> None:
    r = Receita(
        id="pago",
        nome="Com agente",
        justificativa="j",
        gerado_em=datetime(2026, 9, 15, tzinfo=UTC),
        resolvers=(ResolverReceita("L1", {}), ResolverReceita("agente", {})),
    )
    destino = tmp_path / "workflows"
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "pago.json").write_text(
        json.dumps(para_json(r), ensure_ascii=False), encoding="utf-8"
    )


def test_executar_workflow_com_agente_responde_409(tmp_path):
    _gravar_pago(tmp_path)
    cliente = TestClient(app_mod.app)

    resposta = cliente.post(
        "/api/workflows/pago/runs", json={"seed": 1, "n": 60, "taxa_divergencia": 0.15}
    )

    assert resposta.status_code == 409
    assert "CLI" in resposta.json()["detail"]


def test_o_modelo_nunca_e_chamado_por_um_endpoint(tmp_path, monkeypatch):
    # A outra metade: só o 409 passaria com a tranca quebrada. Espiona
    # `ClienteAusente.complete` e exige ZERO chamadas — se alguém um dia
    # trocar o sentinela por um cliente real, este teste é quem pega.
    _gravar_pago(tmp_path)
    chamadas = []
    original = cat_mod.ClienteAusente.complete

    def espiao(self, system, messages, tools):
        chamadas.append(1)
        return original(self, system, messages, tools)

    monkeypatch.setattr(cat_mod.ClienteAusente, "complete", espiao)
    cliente = TestClient(app_mod.app)

    cliente.post("/api/workflows/pago/runs", json={"seed": 1, "n": 60, "taxa_divergencia": 0.15})
    cliente.get("/api/workflows/pago")
    cliente.get("/api/workflows")

    assert chamadas == []


def test_workflow_sem_agente_continua_executando(tmp_path):
    r = Receita(
        id="gratis",
        nome="Só regras",
        justificativa="j",
        gerado_em=datetime(2026, 9, 15, tzinfo=UTC),
        resolvers=(ResolverReceita("L1", {}), ResolverReceita("L2", {})),
    )
    destino = tmp_path / "workflows"
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "gratis.json").write_text(
        json.dumps(para_json(r), ensure_ascii=False), encoding="utf-8"
    )
    cliente = TestClient(app_mod.app)

    assert (
        cliente.post(
            "/api/workflows/gratis/runs", json={"seed": 1, "n": 60, "taxa_divergencia": 0.15}
        ).status_code
        == 200
    )


def test_a_embutida_continua_executando(tmp_path):
    cliente = TestClient(app_mod.app)
    assert (
        cliente.post(
            "/api/workflows/conciliacao/runs",
            json={"seed": 1, "n": 60, "taxa_divergencia": 0.15},
        ).status_code
        == 200
    )
```

- [ ] **Step 2: Rode e confirme que falham**

```bash
pytest tests/api/test_dinheiro_workflow_gerado.py -v
```
Esperado: `test_executar_workflow_com_agente_responde_409` FALHA (vem 200 ou 500).

- [ ] **Step 3: Implemente a guarda**

Em `_executar_memoizado`, logo após `definicao = _construir_definicao(...)` e **antes** de `reconcile`:

```python
    # A regra deste módulo — nenhum endpoint gasta dinheiro — aplicada a
    # cascatas que a API não escreveu. `lru_cache` NÃO memoiza exceções, então
    # levantar aqui dentro é seguro: a chave nunca recebe valor.
    #
    # Esta é a porta educada. A tranca é `ClienteAusente`, que `construir`
    # injeta por default e que levanta se alguém chegar ao modelo por aqui.
    classes = {r.cost_class for s in definicao.stages for r in s.cascade}
    if CostClass.AGENTE in classes:
        raise HTTPException(
            status_code=409,
            detail=(
                f"o workflow {workflow_id!r} tem uma etapa paga e não pode ser "
                f"executado pela web. rode pela CLI."
            ),
        )
```

- [ ] **Step 4: Rode e confirme que passam**

```bash
pytest tests/api/test_dinheiro_workflow_gerado.py -v
pytest tests/api -v
```
Esperado: tudo verde, incluindo os testes de dinheiro que já existiam.

- [ ] **Step 5: Mutação**

1. Remova a guarda do 409 → `test_executar_workflow_com_agente_responde_409` FALHA **e** `test_o_modelo_nunca_e_chamado_por_um_endpoint` FALHA (o `Investigator` chega a chamar `complete`). As duas metades disparando juntas é a prova de que o espião discrimina.
2. Mantenha a guarda mas troque `ClienteAusente()` por um duplo que devolve resposta em vez de levantar, e remova a guarda → confirme que só o espião pega. Restaure.

- [ ] **Step 6: Commit**

```bash
ruff check src tests && pytest tests/ -q
git add src/orchestrator/api/app.py tests/api/test_dinheiro_workflow_gerado.py
git commit -m "feat(api): 409 para cascata paga, com ClienteAusente como tranca"
```

---

### Task 9: O canvas lista e desenha workflows gerados

**Files:**
- Modify: `web/index.html`
- Modify: `web/canvas.js`
- Modify: `web/style.css`
- Test: `tests/api/test_canvas_workflows.py`

**Interfaces:**
- Consumes: `GET /api/workflows` (Task 7); `GET /api/workflows/{id}`; `POST /api/workflows/{id}/runs`.
- Produces: seletor `<select id="workflow">` no topo do canvas; o id ativo vem de `location.search` (`?workflow=acme`), default `conciliacao`; botão de execução desabilitado quando `executavel` é falso.

**Aviso ao implementador:** `web/canvas.js` e `web/fila.js` já lêem `seed`, `n` e `taxa_divergencia` de `location.search` com defaults idênticos. O parâmetro `workflow` entra pelo mesmo caminho. Não introduza uma constante nova com default próprio — foi exatamente assim que as duas páginas passaram a apontar para datasets diferentes e o demo ponta a ponta quebrou.

- [ ] **Step 1: Escreva o teste que falha**

`tests/api/test_canvas_workflows.py`:

```python
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web"


def test_o_canvas_le_o_workflow_da_url():
    # Constante local com default próprio foi o que fez canvas e fila
    # apontarem para datasets diferentes e quebrou o demo inteiro.
    js = (WEB / "canvas.js").read_text(encoding="utf-8")
    assert "location.search" in js
    assert "workflow" in js


def test_o_canvas_usa_o_mesmo_default_de_workflow_que_a_api():
    js = (WEB / "canvas.js").read_text(encoding="utf-8")
    assert "conciliacao" in js


def test_o_seletor_existe_no_html():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'id="workflow"' in html
```

- [ ] **Step 2: Rode e confirme que falham**

```bash
pytest tests/api/test_canvas_workflows.py -v
```
Esperado: FAIL nos três.

- [ ] **Step 3: Implemente no front**

Em `index.html`, acrescente o seletor logo antes do container do canvas:

```html
<label class="seletor">
  workflow
  <select id="workflow"></select>
</label>
```

Em `canvas.js`, acrescente, seguindo o padrão já usado para `seed`/`n`:

```js
const params = new URLSearchParams(location.search);
const WORKFLOW = params.get("workflow") || "conciliacao";

async function popularSeletor() {
  const lista = await (await fetch("/api/workflows")).json();
  const select = document.getElementById("workflow");
  select.innerHTML = "";
  for (const w of lista) {
    const opt = document.createElement("option");
    opt.value = w.id;
    // textContent, nunca innerHTML: `nome` vem de uma receita gerada por um
    // modelo a partir do texto do parceiro. Tratar como dado, não markup.
    opt.textContent = w.executavel ? w.nome : `${w.nome} (etapa paga)`;
    opt.disabled = !w.executavel;
    if (w.id === WORKFLOW) opt.selected = true;
    select.appendChild(opt);
  }
  select.addEventListener("change", () => {
    params.set("workflow", select.value);
    location.search = params.toString();
  });
}
```

Chame `popularSeletor()` na inicialização, e troque as URLs fixas
`/api/workflows/conciliacao...` por `` `/api/workflows/${WORKFLOW}...` ``.

Em `style.css`, acrescente uma regra `.seletor` seguindo o espaçamento das
existentes.

- [ ] **Step 4: Verifique manualmente ponta a ponta**

```bash
pip install -e ".[dev,api]"
python -m uvicorn orchestrator.api.app:app --port 8000
```

Noutro terminal, gere uma receita com um entrevistador falso e confira que ela
aparece no seletor e desenha:

```bash
python -c "
import sys; sys.path.insert(0,'src')
from datetime import datetime, UTC
from orchestrator.grill.receita import Receita, ResolverReceita
from orchestrator.grill.registro import gravar_receita
gravar_receita(Receita(id='demo', nome='Demo', justificativa='j',
  gerado_em=datetime.now(UTC),
  resolvers=(ResolverReceita('L1',{}), ResolverReceita('L2',{'max_cents':20}))))
"
```

Abra `http://localhost:8000/?workflow=demo`. Confirme: o seletor mostra "Demo",
a cascata desenha L1 e L2, e a soma das taxas mais a lacuna fecha em 100%.

- [ ] **Step 5: Rode a suíte**

```bash
pytest tests/ -q
```

- [ ] **Step 6: Commit**

```bash
ruff check src tests
git add web tests/api/test_canvas_workflows.py
git commit -m "feat(web): seletor de workflow lendo o id da URL"
```

---

### Task 10: Adaptador de assinatura

**Files:**
- Create: `src/orchestrator/grill/assinatura.py`
- Modify: `pyproject.toml` (extra `assinatura`)
- Test: `tests/grill/test_assinatura.py`

**Interfaces:**
- Consumes: `LLMClient`, `LLMResponse`, `ToolCall` de `orchestrator.agent.llm`; `Cost`.
- Produces: `ClienteAssinatura` implementando `LLMClient` — `model: str` precificado e `complete(system, messages, tools) -> LLMResponse`.

**Esta tarefa é a última de propósito.** Tudo o mais já está provado sem rede. Se `ClaudeSDKClient` não aceitar uma conversa multi-turno com histórico replicado, a queda é para `AnthropicClient` (chave de API) e **nenhum outro arquivo muda** — o entrevistador fala com o protocolo, não com o SDK.

- [ ] **Step 1: Sonde a capacidade do SDK antes de escrever código**

```bash
pip install -e ".[assinatura]"
python -c "
import claude_agent_sdk as s
print([n for n in dir(s) if 'Client' in n or 'query' in n])
import inspect
print(inspect.signature(s.ClaudeSDKClient.__init__))
"
```

Decida, e **anote a decisão num comentário no topo de `assinatura.py`**:
- Se houver um cliente que aceite turnos sucessivos preservando histórico → implemente sobre ele.
- Se não houver → implemente `ClienteAssinatura` como alias documentado de `AnthropicClient` (chave de API), com comentário explicando a limitação encontrada e o que foi tentado. Registre a mudança em `docs/superpowers/DECISOES.md`, seção Plano 5.

- [ ] **Step 2: Escreva o teste que falha**

`tests/grill/test_assinatura.py`:

```python
import pytest

from orchestrator.agent.proposal import Cost


def test_o_cliente_de_assinatura_satisfaz_o_protocolo():
    # O entrevistador só conhece `LLMClient`. Esta é a única amarra.
    sdk = pytest.importorskip("claude_agent_sdk")  # noqa: F841
    from orchestrator.grill.assinatura import ClienteAssinatura

    cliente = ClienteAssinatura()
    assert hasattr(cliente, "model")
    assert callable(cliente.complete)


def test_o_modelo_do_cliente_e_precificado():
    # Mesma razão do `ClienteAusente`: um nome fora da tabela de preços faria
    # todo cálculo de orçamento levantar.
    pytest.importorskip("claude_agent_sdk")
    from orchestrator.grill.assinatura import ClienteAssinatura

    Cost.zero().microcents(ClienteAssinatura().model)


def test_o_entrevistador_nao_importa_o_sdk():
    # A prova de que o adaptador é substituível: o laço inteiro roda sem o
    # extra instalado.
    import orchestrator.grill.entrevistador as ent

    fonte = (ent.__file__).replace(".pyc", ".py")
    with open(fonte, encoding="utf-8") as f:
        assert "claude_agent_sdk" not in f.read()
```

- [ ] **Step 3: Rode e confirme que falham**

```bash
pytest tests/grill/test_assinatura.py -v
```
Esperado: os dois primeiros FALHAM (módulo não existe) ou são pulados sem o extra; o terceiro deve **passar** já — se falhar, o entrevistador vazou o SDK e isso precisa ser corrigido antes.

- [ ] **Step 4: Implemente conforme a decisão do Step 1**

Use as mesmas opções de isolamento que `eval/assinatura.py` já estabeleceu e que são obrigatórias aqui:

```python
    opcoes = ClaudeAgentOptions(
        system_prompt=system,
        # Sem isto o SDK carrega skills, comandos e memória de `~/.claude/` e
        # do `.claude/` do projeto: a entrevista passaria a depender da
        # configuração pessoal de quem rodou.
        setting_sources=[],
        # O entrevistador não lê nem escreve arquivo nenhum.
        disallowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebFetch"],
        permission_mode="bypassPermissions",
    )
```

- [ ] **Step 5: Teste manual com a assinatura**

```bash
orchestrator-grill --id piloto --descricao "Recebemos NF de fornecedores e pagamos por transferência. Às vezes o banco cobra tarifa e o valor não bate por alguns centavos."
```

Responda às perguntas. Confirme: receita gravada, número impresso com a ressalva, e a receita aparecendo em `http://localhost:8000/?workflow=piloto`.

- [ ] **Step 6: Commit**

```bash
ruff check src tests && pytest tests/ -q
git add src/orchestrator/grill/assinatura.py tests/grill/test_assinatura.py pyproject.toml docs/superpowers/DECISOES.md
git commit -m "feat(grill): adaptador de assinatura para a entrevista"
```

---

## Verificação final da fatia

Antes de encerrar, rode e confirme:

```bash
pytest tests/ -q
ruff check src tests
orchestrator --seed 1 --n 500
```

Esperado: suíte inteira verde; `orchestrator` reportando **85,3%, zero falso
positivo, zero falso negativo** — byte-idêntico ao que reporta hoje. Se esse
número mudou, a fatia tocou o conciliador embutido, o que ela não pode fazer.

Confirme também o golden:

```bash
pytest tests/ -q -k golden
```
