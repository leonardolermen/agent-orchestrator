# Agente Investigador — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o que as camadas determinísticas não resolvem virar uma proposta explicada, com evidência citada, confiança declarada e custo medido — ou uma abstenção honesta.

**Architecture:** Um investigador recebe apenas as divergências que sobraram do `reconcile`, consulta ferramentas somente-leitura sobre o dataset, e devolve `Proposal` estruturada validada por schema. O cliente de LLM é uma costura trocável, o que permite três camadas de teste: cliente falso no CI, gravações reprisadas, e avaliação ao vivo contra o gabarito que a plano 1 já produz.

**Tech Stack:** Python 3.11+, `anthropic` SDK, pytest, ruff. Modelo padrão `claude-opus-5`.

**Spec:** [`2026-09-14-agent-orchestrator-design.md`](../specs/2026-09-14-agent-orchestrator-design.md) seção 4.6 e 5, mais [`2026-09-14-composicao-de-workflows-design.md`](../specs/2026-09-14-composicao-de-workflows-design.md) seção 6.

## Global Constraints

- **Valores monetários são `int` em centavos.** Ponto flutuante em dinheiro é proibido, inclusive em testes. Custo de API é contabilizado em **micro-cents de USD** (`int`), convertido para centavos de BRL só na renderização.
- **As ferramentas do agente são somente-leitura.** Nenhuma escreve em lugar nenhum. O agente produz proposta; quem escreve é o humano ao aprovar. Isso apaga compensação, idempotência e rollback deste plano — ver spec seção 3.2, Tier 2.
- **Abstenção é cidadã de primeira classe.** `NAO_IDENTIFICADO` com confiança baixa é resposta válida e deve ser barata. Proposta errada com confiança alta destrói a credibilidade mais rápido que dez abstenções.
- **O agente recebe apenas a divergência** mais o contexto que ele próprio pedir via ferramenta. Nunca o dataset inteiro.
- **Uma proposta NÃO é uma resolução.** O item continua divergente até um humano aprovar. `reconcile` não remove do pool nada que só tenha proposta.
- **Todo custo é contabilizado e todo limite é observável.** Estourar orçamento é evento registrado, nunca exceção silenciosa.
- **Nenhuma chamada de API em teste unitário.** A suíte do CI roda com cliente falso ou gravação. Só a avaliação ao vivo gasta dinheiro, e ela é explícita.
- **`calcular_retencao` e qualquer aritmética fiscal é ferramenta determinística**, nunca raciocínio do modelo.
- Python 3.11+, pytest, ruff. Comentários e docstrings em português.

---

## Correção a uma constatação anterior

A seção 6 do spec de composição afirma que o agente deve satisfazer o mesmo
protocolo das camadas determinísticas. **Isso está parcialmente errado e este
plano corrige.**

Uma regra devolve `MatchResult` — o item está resolvido. O agente devolve
`Proposal` — o item continua em aberto até um humano aprovar. Forçar os dois no
mesmo tipo de retorno seria mentira de tipo, e criaria um `MatchResult` que não
casa nada.

O que sobrevive da constatação: **a cascata continua sendo uma chamada só.**
`reconcile` passa a aceitar um investigador opcional como último passo, e
`ReconcileResult` passa a carregar propostas e custo por resolver. Sem protocolo
novo, sem adaptador, sem tocar nos três matchers existentes.

A segunda constatação — métricas por resolver — vale inteira e está na Task 7.

---

## File Structure

| Arquivo | Responsabilidade |
|---|---|
| `src/orchestrator/agent/__init__.py` | vazio |
| `src/orchestrator/agent/proposal.py` | `Confidence`, `Cost`, `Proposal`, `InvestigationOutput` |
| `src/orchestrator/agent/llm.py` | `LLMClient` protocolo, `LLMResponse`, `FakeLLMClient` |
| `src/orchestrator/agent/tools.py` | `ToolContext` e as cinco ferramentas somente-leitura |
| `src/orchestrator/agent/investigator.py` | `Investigator` — laço, orçamento, abstenção |
| `src/orchestrator/agent/anthropic_client.py` | Implementação real do `LLMClient` |
| `src/orchestrator/matching/engine.py` | *(modificar)* aceita investigador; resultado carrega propostas |
| `src/orchestrator/metrics.py` | *(modificar)* estatística por resolver e precisão das propostas |
| `src/orchestrator/eval/__init__.py` | vazio |
| `src/orchestrator/eval/agent_eval.py` | avaliação ao vivo e comparação entre modelos |

Testes espelham a estrutura em `tests/agent/` e `tests/eval/`.

---

### Task 1: Contratos de proposta e custo

**Files:**
- Create: `src/orchestrator/agent/__init__.py`
- Create: `src/orchestrator/agent/proposal.py`
- Create: `tests/agent/__init__.py`
- Test: `tests/agent/test_proposal.py`

**Interfaces:**
- Consumes: `orchestrator.taxonomy.DivergenceType`
- Produces: `Confidence`, `Cost`, `Proposal`, `InvestigationOutput`

- [ ] **Step 1: Criar os diretórios e arquivos vazios**

```bash
mkdir -p src/orchestrator/agent tests/agent
touch src/orchestrator/agent/__init__.py tests/agent/__init__.py
git add src/orchestrator/agent/__init__.py tests/agent/__init__.py
git ls-files src/orchestrator/agent tests/agent
```

Confirme que os dois aparecem na saída do `git ls-files` antes de seguir.

- [ ] **Step 2: Escrever o teste que falha**

Criar `tests/agent/test_proposal.py`:

```python
import pytest

from orchestrator.agent.proposal import (
    Confidence,
    Cost,
    InvestigationOutput,
    Proposal,
    TraceEvent,
)
from orchestrator.taxonomy import DivergenceType


def _custo() -> Cost:
    return Cost(input_tokens=1000, output_tokens=200, cached_tokens=500, calls=2)


def test_custo_soma_tokens_ao_preco_do_modelo():
    # opus-5: 500 micro-cents por token de entrada, 2500 de saída, 50 de cache.
    c = _custo()
    assert c.microcents("claude-opus-5") == 1000 * 500 + 200 * 2500 + 500 * 50


def test_custo_de_modelo_mais_barato_e_menor():
    c = _custo()
    assert c.microcents("claude-haiku-4-5") < c.microcents("claude-opus-5")


def test_custo_rejeita_modelo_desconhecido():
    with pytest.raises(ValueError):
        _custo().microcents("modelo-que-nao-existe")


def test_custo_zero_e_neutro_na_soma():
    c = _custo()
    assert c + Cost.zero() == c


def test_custos_somam_campo_a_campo():
    soma = _custo() + _custo()
    assert soma.input_tokens == 2000
    assert soma.calls == 4


def test_proposta_carrega_evidencia_e_confianca():
    p = Proposal(
        divergence_id="d-b-b00001",
        tipo=DivergenceType.RETENCAO_IMPOSTO,
        explicacao="ISS de 5% retido na fonte",
        evidencia=["l00001: bruto 254925", "b00001: líquido 242179"],
        confianca=Confidence.ALTA,
        acao_sugerida="conciliar_com:l00001",
        cost=_custo(),
    )
    assert p.confianca is Confidence.ALTA
    assert len(p.evidencia) == 2


def test_abstencao_e_proposta_valida():
    p = Proposal.abstencao(divergence_id="d-b-b00002", motivo="sem contexto suficiente")
    assert p.tipo is DivergenceType.NAO_IDENTIFICADO
    assert p.confianca is Confidence.BAIXA
    assert p.acao_sugerida == "investigar_manual"


def test_proposta_com_confianca_alta_exige_evidencia():
    # Afirmar com confiança e sem evidência é exatamente o que destrói a
    # credibilidade do produto.
    with pytest.raises(ValueError):
        Proposal(
            divergence_id="d1",
            tipo=DivergenceType.RETENCAO_IMPOSTO,
            explicacao="acho que é retenção",
            evidencia=[],
            confianca=Confidence.ALTA,
            acao_sugerida="conciliar_com:l1",
            cost=Cost.zero(),
        )


def test_proposta_carrega_trace_auditavel():
    p = Proposal.abstencao(
        "d1", "x", trace=[TraceEvent(kind="llm", detail={"turno": 1, "tokens": 50})]
    )
    assert p.trace[0].kind == "llm"
    assert p.trace[0].detail["turno"] == 1


def test_proposta_sem_trace_nasce_com_lista_vazia():
    assert Proposal.abstencao("d1", "x").trace == []


def test_saida_de_investigacao_agrega_custo():
    p1 = Proposal.abstencao("d1", "x")
    p2 = Proposal.abstencao("d2", "y")
    out = InvestigationOutput(proposals=[p1, p2], cost=_custo() + _custo())
    assert out.cost.calls == 4
    assert len(out.proposals) == 2
```

- [ ] **Step 3: Rodar e confirmar falha**

Run: `.venv/Scripts/pytest tests/agent/test_proposal.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'orchestrator.agent.proposal'`

- [ ] **Step 4: Implementar `src/orchestrator/agent/proposal.py`**

```python
"""Contratos de saída do agente investigador.

O agente nunca devolve texto livre. Ele devolve uma proposta estruturada, com
evidência citada e confiança declarada — ou uma abstenção, que é resposta
válida e deve ser barata.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from orchestrator.taxonomy import DivergenceType


class Confidence(StrEnum):
    ALTA = "ALTA"
    MEDIA = "MEDIA"
    BAIXA = "BAIXA"


# Preço por token em micro-cents de USD (1 micro-cent = 1e-6 de centavo de
# dólar). Inteiro de propósito: a constraint de dinheiro do projeto vale aqui
# também, e ponto flutuante acumulando por divergência erraria devagar.
#
# Fonte: tabela de preços da API por 1M de tokens.
#   opus-5     $5,00 entrada / $25,00 saída
#   sonnet-5   $2,00 / $10,00
#   haiku-4.5  $1,00 / $5,00
# Leitura de cache custa ~10% da entrada.
_PRECOS = {
    "claude-opus-5": (500, 2500, 50),
    "claude-sonnet-5": (200, 1000, 20),
    "claude-haiku-4-5": (100, 500, 10),
}


@dataclass(frozen=True)
class Cost:
    """O que uma investigação consumiu. Tokens, não dinheiro — o preço depende
    do modelo, e o mesmo consumo custa diferente em cada um."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    calls: int = 0

    @staticmethod
    def zero() -> "Cost":
        return Cost()

    def __add__(self, outro: "Cost") -> "Cost":
        return Cost(
            input_tokens=self.input_tokens + outro.input_tokens,
            output_tokens=self.output_tokens + outro.output_tokens,
            cached_tokens=self.cached_tokens + outro.cached_tokens,
            calls=self.calls + outro.calls,
        )

    def microcents(self, model: str) -> int:
        """Custo em micro-cents de USD para o modelo dado."""
        if model not in _PRECOS:
            raise ValueError(f"modelo sem preço conhecido: {model!r}")
        entrada, saida, cache = _PRECOS[model]
        return (
            self.input_tokens * entrada
            + self.output_tokens * saida
            + self.cached_tokens * cache
        )


@dataclass(frozen=True)
class TraceEvent:
    """Um passo do que aconteceu ao investigar uma divergência.

    O spec seção 7 exige poder reconstruir por que o sistema chegou a uma
    conclusão. Num produto que um contador vai auditar, uma proposta sem
    rastro é uma afirmação sem fonte.
    """

    kind: str  # "llm" | "tool" | "outcome"
    detail: dict[str, Any]


@dataclass(frozen=True)
class Proposal:
    """O que o agente propõe para uma divergência.

    Uma proposta NÃO resolve a divergência. Ela explica e sugere; quem resolve
    é o humano ao aprovar.
    """

    divergence_id: str
    tipo: DivergenceType
    explicacao: str
    evidencia: list[str]
    confianca: Confidence
    acao_sugerida: str
    cost: Cost = field(default_factory=Cost.zero)
    trace: list[TraceEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Confiança alta sem evidência é a combinação que destrói a
        # credibilidade do produto mais rápido que qualquer erro.
        if self.confianca is Confidence.ALTA and not self.evidencia:
            raise ValueError(
                f"proposta {self.divergence_id} declara confiança alta sem evidência"
            )

    @staticmethod
    def abstencao(
        divergence_id: str,
        motivo: str,
        cost: Cost | None = None,
        trace: list[TraceEvent] | None = None,
    ) -> "Proposal":
        """Não saber é resposta válida, e precisa ser barata de produzir."""
        return Proposal(
            divergence_id=divergence_id,
            tipo=DivergenceType.NAO_IDENTIFICADO,
            explicacao=motivo,
            evidencia=[],
            confianca=Confidence.BAIXA,
            acao_sugerida="investigar_manual",
            cost=cost or Cost.zero(),
            trace=trace or [],
        )


@dataclass(frozen=True)
class InvestigationOutput:
    """Tudo que uma passada do investigador produziu."""

    proposals: list[Proposal]
    cost: Cost
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `.venv/Scripts/pytest tests/agent/test_proposal.py -v`
Expected: 10 passed

- [ ] **Step 6: Commit**

```bash
git add src/orchestrator/agent tests/agent
git commit -m "feat: contratos de proposta, confiança e custo do agente"
```

---

### Task 2: A costura do cliente de LLM

**Files:**
- Create: `src/orchestrator/agent/llm.py`
- Test: `tests/agent/test_llm.py`

**Interfaces:**
- Consumes: `Cost` de `orchestrator.agent.proposal`
- Produces: `LLMClient` (Protocol), `LLMResponse`, `ToolCall`, `FakeLLMClient`

Esta é a costura que o spec 3.3 promete. Sem ela não existe teste determinístico
de nada que envolva o agente.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/agent/test_llm.py`:

```python
import pytest

from orchestrator.agent.llm import FakeLLMClient, LLMResponse, ToolCall
from orchestrator.agent.proposal import Cost


def test_fake_devolve_as_respostas_na_ordem():
    a = LLMResponse(text="primeira", tool_calls=[], cost=Cost(calls=1))
    b = LLMResponse(text="segunda", tool_calls=[], cost=Cost(calls=1))
    cliente = FakeLLMClient([a, b])

    assert cliente.complete(system="s", messages=[], tools=[]).text == "primeira"
    assert cliente.complete(system="s", messages=[], tools=[]).text == "segunda"


def test_fake_registra_o_que_recebeu():
    cliente = FakeLLMClient([LLMResponse(text="ok", tool_calls=[], cost=Cost.zero())])
    cliente.complete(system="instrução", messages=[{"role": "user", "content": "oi"}], tools=[])

    assert cliente.chamadas[0]["system"] == "instrução"
    assert cliente.chamadas[0]["messages"][0]["content"] == "oi"


def test_fake_estoura_quando_acabam_as_respostas():
    # Um laço que pede mais respostas do que o teste preparou é laço descontrolado,
    # e o teste precisa gritar em vez de devolver None.
    cliente = FakeLLMClient([LLMResponse(text="única", tool_calls=[], cost=Cost.zero())])
    cliente.complete(system="s", messages=[], tools=[])

    with pytest.raises(AssertionError):
        cliente.complete(system="s", messages=[], tools=[])


def test_fake_pode_simular_chamada_de_ferramenta():
    r = LLMResponse(
        text="",
        tool_calls=[ToolCall(id="t1", name="buscar_lancamentos", arguments={"valor": 1000})],
        cost=Cost(calls=1),
    )
    cliente = FakeLLMClient([r])
    resposta = cliente.complete(system="s", messages=[], tools=[])

    assert resposta.tool_calls[0].name == "buscar_lancamentos"
    assert resposta.tool_calls[0].arguments["valor"] == 1000


def test_resposta_sem_texto_e_sem_ferramenta_e_invalida():
    with pytest.raises(ValueError):
        LLMResponse(text="", tool_calls=[], cost=Cost.zero())
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/Scripts/pytest tests/agent/test_llm.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `src/orchestrator/agent/llm.py`**

```python
"""A costura do modelo.

Todo o resto do agente fala com esta interface, nunca com um SDK. É o que
permite testar o laço, o orçamento e a abstenção sem gastar um centavo, e o que
permite trocar de modelo sem tocar em lógica de domínio.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from orchestrator.agent.proposal import Cost


@dataclass(frozen=True)
class ToolCall:
    """Um pedido do modelo para executar uma ferramenta."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    cost: Cost

    def __post_init__(self) -> None:
        # Resposta vazia sem pedido de ferramenta não é resposta. Deixar passar
        # faria o laço girar sem avançar.
        if not self.text and not self.tool_calls:
            raise ValueError("resposta sem texto e sem chamada de ferramenta")


class LLMClient(Protocol):
    """O que o agente precisa de um modelo, e nada além disso."""

    model: str

    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse: ...


class FakeLLMClient:
    """Cliente de teste: devolve respostas preparadas, em ordem, e registra o
    que recebeu.

    Acaba as respostas preparadas e ele levanta AssertionError de propósito —
    um laço que pede mais turnos do que o teste previu é laço descontrolado, e
    devolver algo vazio esconderia isso.
    """

    def __init__(
        self, respostas: list[LLMResponse], model: str = "claude-opus-5"
    ) -> None:
        # O modelo padrão é um de verdade, não "fake": o investigador consulta
        # `client.model` para calcular custo contra a tabela de preços, e um
        # nome inventado faria todo teste de orçamento levantar ValueError.
        self.model = model
        self._respostas = list(respostas)
        self.chamadas: list[dict[str, Any]] = []

    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        self.chamadas.append({"system": system, "messages": messages, "tools": tools})
        assert self._respostas, (
            f"o laço pediu o turno {len(self.chamadas)} mas o teste preparou "
            f"apenas {len(self.chamadas) - 1}"
        )
        return self._respostas.pop(0)
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/pytest tests/agent/test_llm.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/agent/llm.py tests/agent/test_llm.py
git commit -m "feat: costura do cliente de LLM com cliente falso para teste"
```

---

### Task 3: Ferramentas somente-leitura

**Files:**
- Create: `src/orchestrator/agent/tools.py`
- Test: `tests/agent/test_tools.py`

**Interfaces:**
- Consumes: `BankEntry`, `LedgerEntry` de `orchestrator.models`; `business_days_between`, `add_business_days` de `orchestrator.dates`; `calcular_retencao` de `orchestrator.synth.injectors`
- Produces: `ToolContext` com os métodos `buscar_lancamentos`, `buscar_documento_fiscal`, `historico_fornecedor`, `calcular_retencao`, `calendario_bancario`; e `TOOL_SCHEMAS`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/agent/test_tools.py`:

```python
from datetime import date

import pytest

from orchestrator.agent.tools import TOOL_SCHEMAS, ToolContext
from orchestrator.synth.generator import build_dataset, generate_clean_pairs


def _contexto() -> ToolContext:
    ds = build_dataset(generate_clean_pairs(seed=3, n=20), injections=[])
    return ToolContext(bank=ds.bank, ledger=ds.ledger)


def test_busca_lancamento_por_valor():
    ctx = _contexto()
    alvo = ctx.ledger[0]

    achados = ctx.buscar_lancamentos(valor=alvo.net_amount)

    assert any(a["id"] == alvo.id for a in achados)


def test_busca_lancamento_por_fornecedor():
    ctx = _contexto()
    fornecedor = ctx.ledger[0].supplier

    achados = ctx.buscar_lancamentos(fornecedor=fornecedor)

    assert achados
    assert all(a["fornecedor"] == fornecedor for a in achados)


def test_busca_limita_o_numero_de_resultados():
    # O agente recebe só o que pede, e o que ele pede não pode virar o dataset
    # inteiro — isso é custo e é qualidade.
    ctx = _contexto()

    achados = ctx.buscar_lancamentos(limite=3)

    assert len(achados) <= 3


def test_busca_sem_criterio_nenhum_e_rejeitada():
    ctx = _contexto()
    with pytest.raises(ValueError):
        ctx.buscar_lancamentos()


def test_busca_documento_fiscal():
    ctx = _contexto()
    doc = ctx.ledger[0].document

    achado = ctx.buscar_documento_fiscal(documento=doc)

    assert achado is not None
    assert achado["documento"] == doc


def test_documento_inexistente_devolve_none():
    assert _contexto().buscar_documento_fiscal(documento="NF-INEXISTENTE") is None


def test_historico_do_fornecedor_traz_estatistica():
    ctx = _contexto()
    fornecedor = ctx.ledger[0].supplier

    h = ctx.historico_fornecedor(fornecedor=fornecedor)

    assert h["quantidade"] >= 1
    assert h["valor_total"] == sum(
        le.net_amount for le in ctx.ledger if le.supplier == fornecedor
    )


def test_calcular_retencao_e_deterministico_e_inteiro():
    # Cálculo fiscal é ferramenta, não raciocínio do modelo.
    ctx = _contexto()
    assert ctx.calcular_retencao(bruto=100_000, aliquota_bp=500) == 5_000
    assert isinstance(ctx.calcular_retencao(bruto=333, aliquota_bp=500), int)


def test_calendario_conta_dias_uteis():
    ctx = _contexto()
    r = ctx.calendario_bancario(de="2026-09-18", ate="2026-09-21")
    assert r["dias_uteis"] == 1


def test_calendario_rejeita_data_malformada():
    ctx = _contexto()
    with pytest.raises(ValueError):
        ctx.calendario_bancario(de="18/09/2026", ate="2026-09-21")


def test_todo_schema_tem_nome_descricao_e_e_estrito():
    # strict exige additionalProperties false mais required — sem isso o modelo
    # pode inventar argumento e a chamada falha em runtime.
    assert len(TOOL_SCHEMAS) == 5
    for s in TOOL_SCHEMAS:
        assert s["name"]
        assert s["description"]
        assert s["strict"] is True
        assert s["input_schema"]["additionalProperties"] is False
        assert "required" in s["input_schema"]


def test_todo_schema_tem_metodo_correspondente_no_contexto():
    ctx = _contexto()
    for s in TOOL_SCHEMAS:
        assert callable(getattr(ctx, s["name"]))
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/Scripts/pytest tests/agent/test_tools.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `src/orchestrator/agent/tools.py`**

```python
"""As ferramentas do agente investigador.

TODAS são somente-leitura. O agente não escreve em lugar nenhum — ele produz
uma proposta, e quem escreve é o humano ao aprovar. Isso elimina deste plano
compensação, idempotência e rollback.

`calcular_retencao` é ferramenta e não raciocínio do modelo de propósito:
cálculo fiscal precisa ser exato e testável.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

from orchestrator.dates import business_days_between
from orchestrator.models import BankEntry, LedgerEntry
from orchestrator.synth.injectors import calcular_retencao as _calcular_retencao

_LIMITE_PADRAO = 10


def _data(texto: str) -> date:
    """Converte ISO-8601 ou levanta. O modelo erra formato de data com
    frequência, e aceitar em silêncio produziria busca vazia inexplicável."""
    try:
        return date.fromisoformat(texto)
    except ValueError as erro:
        raise ValueError(f"data deve estar em AAAA-MM-DD: {texto!r}") from erro


@dataclass
class ToolContext:
    """O que as ferramentas podem enxergar.

    O agente recebe apenas a divergência; tudo o mais ele pede por aqui, e
    sempre com limite. Entregar o dataset inteiro seria custo e ruído.
    """

    bank: list[BankEntry]
    ledger: list[LedgerEntry]

    def buscar_lancamentos(
        self,
        valor: int | None = None,
        fornecedor: str | None = None,
        documento: str | None = None,
        limite: int | None = None,
    ) -> list[dict[str, Any]]:
        """Lançamentos contábeis por valor líquido, fornecedor ou documento."""
        if valor is None and fornecedor is None and documento is None and limite is None:
            raise ValueError("buscar_lancamentos exige pelo menos um critério")

        achados = [
            le
            for le in self.ledger
            if (valor is None or le.net_amount == valor)
            and (fornecedor is None or le.supplier == fornecedor)
            and (documento is None or le.document == documento)
        ]
        return [self._ledger_dict(le) for le in achados[: limite or _LIMITE_PADRAO]]

    def buscar_documento_fiscal(self, documento: str) -> dict[str, Any] | None:
        """Dados do lançamento que carrega este documento."""
        for le in self.ledger:
            if le.document == documento:
                return self._ledger_dict(le)
        return None

    def historico_fornecedor(self, fornecedor: str) -> dict[str, Any]:
        """Padrão histórico de pagamento do fornecedor."""
        dele = [le for le in self.ledger if le.supplier == fornecedor]
        return {
            "fornecedor": fornecedor,
            "quantidade": len(dele),
            "valor_total": sum(le.net_amount for le in dele),
            "contas_usadas": sorted({le.account for le in dele}),
        }

    def calcular_retencao(self, bruto: int, aliquota_bp: int) -> int:
        """Retenção em centavos, truncada. Determinística por construção."""
        return _calcular_retencao(bruto, aliquota_bp)

    def calendario_bancario(self, de: str, ate: str) -> dict[str, Any]:
        """Dias úteis entre duas datas ISO."""
        inicio, fim = _data(de), _data(ate)
        return {"de": de, "ate": ate, "dias_uteis": business_days_between(inicio, fim)}

    @staticmethod
    def _ledger_dict(le: LedgerEntry) -> dict[str, Any]:
        return {
            "id": le.id,
            "documento": le.document,
            "fornecedor": le.supplier,
            "bruto": le.gross_amount,
            "liquido": le.net_amount,
            "competencia": le.accrual_date.isoformat(),
            "caixa": le.cash_date.isoformat() if le.cash_date else None,
            "conta": le.account,
        }


def _schema(nome: str, descricao: str, props: dict[str, Any], obrigatorios: list[str]) -> dict[str, Any]:
    return {
        "name": nome,
        "description": descricao,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": props,
            "required": obrigatorios,
            "additionalProperties": False,
        },
    }


TOOL_SCHEMAS: list[dict[str, Any]] = [
    _schema(
        "buscar_lancamentos",
        "Busca lançamentos contábeis por valor líquido em centavos, fornecedor "
        "ou documento. Devolve no máximo 10 resultados.",
        {
            "valor": {"type": ["integer", "null"], "description": "valor líquido em centavos"},
            "fornecedor": {"type": ["string", "null"]},
            "documento": {"type": ["string", "null"]},
            "limite": {"type": ["integer", "null"], "description": "máximo de resultados"},
        },
        ["valor", "fornecedor", "documento", "limite"],
    ),
    _schema(
        "buscar_documento_fiscal",
        "Busca o lançamento contábil de um documento fiscal pelo número.",
        {"documento": {"type": "string"}},
        ["documento"],
    ),
    _schema(
        "historico_fornecedor",
        "Padrão histórico de pagamento de um fornecedor: quantidade de "
        "lançamentos, valor total e contas usadas.",
        {"fornecedor": {"type": "string"}},
        ["fornecedor"],
    ),
    _schema(
        "calcular_retencao",
        "Calcula retenção na fonte em centavos sobre um valor bruto. A alíquota "
        "vai em basis points: 500 significa 5%. Use esta ferramenta em vez de "
        "calcular de cabeça.",
        {
            "bruto": {"type": "integer", "description": "valor bruto em centavos"},
            "aliquota_bp": {"type": "integer", "description": "alíquota em basis points"},
        },
        ["bruto", "aliquota_bp"],
    ),
    _schema(
        "calendario_bancario",
        "Conta dias úteis entre duas datas no formato AAAA-MM-DD. Fins de "
        "semana não contam.",
        {"de": {"type": "string"}, "ate": {"type": "string"}},
        ["de", "ate"],
    ),
]
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/pytest tests/agent/test_tools.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/agent/tools.py tests/agent/test_tools.py
git commit -m "feat: cinco ferramentas somente-leitura do investigador"
```

---

### Task 4: O investigador — laço, orçamento e abstenção

**Files:**
- Create: `src/orchestrator/agent/investigator.py`
- Test: `tests/agent/test_investigator.py`

**Interfaces:**
- Consumes: `LLMClient`, `LLMResponse`, `ToolCall`; `ToolContext`, `TOOL_SCHEMAS`; `Proposal`, `Cost`, `Confidence`, `InvestigationOutput`; `Divergence` de `orchestrator.models`
- Produces: `Investigator(client, context, max_turns=6, budget_microcents=...)` com `investigate(divergences) -> InvestigationOutput`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/agent/test_investigator.py`:

```python
import json

from orchestrator.agent.investigator import Investigator
from orchestrator.agent.llm import FakeLLMClient, LLMResponse, ToolCall
from orchestrator.agent.proposal import Confidence, Cost
from orchestrator.agent.tools import ToolContext
from orchestrator.models import Divergence
from orchestrator.synth.generator import build_dataset, generate_clean_pairs
from orchestrator.taxonomy import DivergenceType


def _ctx() -> ToolContext:
    ds = build_dataset(generate_clean_pairs(seed=3, n=20), injections=[])
    return ToolContext(bank=ds.bank, ledger=ds.ledger)


def _div(id_: str = "d1") -> Divergence:
    return Divergence(id=id_, bank_ids=frozenset({"b00001"}), ledger_ids=frozenset())


def _proposta_json(tipo="RETENCAO_IMPOSTO", confianca="ALTA", evidencia=("l1: bruto 100",)):
    return json.dumps(
        {
            "tipo": tipo,
            "explicacao": "ISS retido na fonte",
            "evidencia": list(evidencia),
            "confianca": confianca,
            "acao_sugerida": "conciliar_com:l1",
        }
    )


def test_uma_divergencia_vira_uma_proposta():
    cliente = FakeLLMClient(
        [LLMResponse(text=_proposta_json(), tool_calls=[], cost=Cost(input_tokens=100, calls=1))]
    )
    inv = Investigator(client=cliente, context=_ctx())

    out = inv.investigate([_div()])

    assert len(out.proposals) == 1
    assert out.proposals[0].tipo is DivergenceType.RETENCAO_IMPOSTO
    assert out.proposals[0].divergence_id == "d1"


def test_ferramenta_pedida_e_executada_e_devolvida():
    cliente = FakeLLMClient(
        [
            LLMResponse(
                text="",
                tool_calls=[ToolCall(id="t1", name="calcular_retencao",
                                     arguments={"bruto": 100000, "aliquota_bp": 500})],
                cost=Cost(calls=1),
            ),
            LLMResponse(text=_proposta_json(), tool_calls=[], cost=Cost(calls=1)),
        ]
    )
    inv = Investigator(client=cliente, context=_ctx())

    out = inv.investigate([_div()])

    # o resultado da ferramenta precisa ter voltado para o modelo
    segunda_chamada = cliente.chamadas[1]["messages"]
    assert any("5000" in json.dumps(m) for m in segunda_chamada)
    assert len(out.proposals) == 1


def test_ferramenta_inexistente_vira_erro_para_o_modelo_nao_excecao():
    cliente = FakeLLMClient(
        [
            LLMResponse(text="", tool_calls=[ToolCall(id="t1", name="nao_existe", arguments={})],
                        cost=Cost(calls=1)),
            LLMResponse(text=_proposta_json(confianca="BAIXA", evidencia=()), tool_calls=[],
                        cost=Cost(calls=1)),
        ]
    )
    inv = Investigator(client=cliente, context=_ctx())

    out = inv.investigate([_div()])

    assert len(out.proposals) == 1
    assert any("nao_existe" in json.dumps(m) for m in cliente.chamadas[1]["messages"])


def test_json_invalido_vira_abstencao_e_nao_estoura():
    cliente = FakeLLMClient(
        [LLMResponse(text="isto não é json", tool_calls=[], cost=Cost(calls=1))]
        * 3
    )
    inv = Investigator(client=cliente, context=_ctx(), max_tentativas_formato=2)

    out = inv.investigate([_div()])

    assert out.proposals[0].tipo is DivergenceType.NAO_IDENTIFICADO
    assert out.proposals[0].confianca is Confidence.BAIXA


def test_tipo_fora_da_taxonomia_vira_abstencao():
    cliente = FakeLLMClient(
        [LLMResponse(text=_proposta_json(tipo="INVENTADO"), tool_calls=[], cost=Cost(calls=1))] * 3
    )
    inv = Investigator(client=cliente, context=_ctx(), max_tentativas_formato=2)

    out = inv.investigate([_div()])

    assert out.proposals[0].tipo is DivergenceType.NAO_IDENTIFICADO


def test_confianca_alta_sem_evidencia_e_rebaixada_nao_rejeitada():
    # O modelo às vezes afirma sem citar. Perder a proposta inteira seria pior
    # que registrá-la com a confiança que ela de fato merece.
    cliente = FakeLLMClient(
        [LLMResponse(text=_proposta_json(confianca="ALTA", evidencia=()), tool_calls=[],
                     cost=Cost(calls=1))]
    )
    inv = Investigator(client=cliente, context=_ctx())

    out = inv.investigate([_div()])

    assert out.proposals[0].confianca is Confidence.BAIXA


def test_laco_para_no_limite_de_turnos():
    pedido = LLMResponse(
        text="",
        tool_calls=[ToolCall(id="t", name="historico_fornecedor", arguments={"fornecedor": "X"})],
        cost=Cost(calls=1),
    )
    cliente = FakeLLMClient([pedido] * 10)
    inv = Investigator(client=cliente, context=_ctx(), max_turns=3)

    out = inv.investigate([_div()])

    assert len(cliente.chamadas) == 3
    assert out.proposals[0].tipo is DivergenceType.NAO_IDENTIFICADO


def test_orcamento_estourado_interrompe_e_abstem():
    caro = LLMResponse(
        text="",
        tool_calls=[ToolCall(id="t", name="historico_fornecedor", arguments={"fornecedor": "X"})],
        cost=Cost(input_tokens=1_000_000, calls=1),
    )
    cliente = FakeLLMClient([caro] * 10)
    inv = Investigator(client=cliente, context=_ctx(), budget_microcents=1)

    out = inv.investigate([_div()])

    assert out.proposals[0].tipo is DivergenceType.NAO_IDENTIFICADO
    assert "orçamento" in out.proposals[0].explicacao.lower()


def test_custo_total_agrega_o_de_cada_divergencia():
    cliente = FakeLLMClient(
        [LLMResponse(text=_proposta_json(), tool_calls=[], cost=Cost(input_tokens=100, calls=1))] * 2
    )
    inv = Investigator(client=cliente, context=_ctx())

    out = inv.investigate([_div("d1"), _div("d2")])

    assert out.cost.calls == 2
    assert out.cost.input_tokens == 200


def test_erro_de_api_vira_abstencao_e_nao_derruba_o_processo():
    # Um timeout num item nao pode custar a conciliacao inteira.
    class _ClienteQueFalha:
        model = "claude-opus-5"

        def complete(self, system, messages, tools):
            raise RuntimeError("timeout da API")

    out = Investigator(client=_ClienteQueFalha(), context=_ctx()).investigate([_div()])

    assert out.proposals[0].tipo is DivergenceType.NAO_IDENTIFICADO
    assert "api" in out.proposals[0].explicacao.lower()
    assert any(e.kind == "erro" for e in out.proposals[0].trace)


def test_trace_registra_turno_ferramenta_e_desfecho():
    cliente = FakeLLMClient(
        [
            LLMResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="t1",
                        name="calcular_retencao",
                        arguments={"bruto": 100000, "aliquota_bp": 500},
                    )
                ],
                cost=Cost(calls=1),
            ),
            LLMResponse(text=_proposta_json(), tool_calls=[], cost=Cost(calls=1)),
        ]
    )

    p = Investigator(client=cliente, context=_ctx()).investigate([_div()]).proposals[0]

    tipos = [e.kind for e in p.trace]
    assert "entrada" in tipos
    assert "llm" in tipos
    assert "tool" in tipos
    assert tipos[-1] == "outcome"


def test_cada_divergencia_comeca_com_contexto_limpo():
    # Divergências não podem contaminar umas às outras: o histórico de uma não
    # entra no prompt da seguinte.
    cliente = FakeLLMClient(
        [LLMResponse(text=_proposta_json(), tool_calls=[], cost=Cost(calls=1))] * 2
    )
    inv = Investigator(client=cliente, context=_ctx())

    inv.investigate([_div("d1"), _div("d2")])

    assert len(cliente.chamadas[0]["messages"]) == len(cliente.chamadas[1]["messages"])
    assert "d2" in json.dumps(cliente.chamadas[1]["messages"])
    assert "d1" not in json.dumps(cliente.chamadas[1]["messages"])
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/Scripts/pytest tests/agent/test_investigator.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `src/orchestrator/agent/investigator.py`**

```python
"""O investigador: uma divergência entra, uma proposta sai.

Nunca levanta por causa do modelo. Toda falha — JSON quebrado, tipo inventado,
ferramenta inexistente, orçamento estourado, turnos esgotados — vira abstenção
registrada. Um investigador que estoura no meio de um fechamento derruba o
processo inteiro por causa de um item.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from orchestrator.agent.llm import LLMClient
from orchestrator.agent.proposal import (
    Confidence,
    Cost,
    InvestigationOutput,
    Proposal,
    TraceEvent,
)
from orchestrator.agent.tools import TOOL_SCHEMAS, ToolContext
from orchestrator.models import Divergence
from orchestrator.taxonomy import DivergenceType

SYSTEM = """Você investiga divergências de conciliação bancária brasileira.

Recebe UMA divergência: lançamentos que as regras determinísticas não
conseguiram casar. Seu trabalho é explicar por quê, usando as ferramentas para
buscar contexto.

Regras:
- Use `calcular_retencao` para qualquer cálculo de imposto. Nunca calcule de cabeça.
- Cite evidência concreta: ids e valores que você de fato consultou.
- Não saber é resposta válida e esperada. Se não houver evidência que sustente
  uma hipótese, responda com tipo NAO_IDENTIFICADO e confiança BAIXA. Uma
  proposta errada com confiança alta custa mais caro que dez abstenções.

Quando tiver concluído, responda APENAS com um objeto JSON:
{"tipo": <um dos tipos>, "explicacao": <texto curto>, "evidencia": [<strings>],
 "confianca": "ALTA"|"MEDIA"|"BAIXA", "acao_sugerida": <texto>}

Tipos válidos: """ + ", ".join(t.value for t in DivergenceType)


@dataclass
class Investigator:
    client: LLMClient
    context: ToolContext
    max_turns: int = 6
    max_tentativas_formato: int = 2
    budget_microcents: int = 100_000  # ~US$ 0,001 por divergência
    name: str = field(default="investigador", init=False)

    def investigate(self, divergences: list[Divergence]) -> InvestigationOutput:
        propostas, total = [], Cost.zero()
        for d in divergences:
            p = self._uma(d)
            propostas.append(p)
            total = total + p.cost
        return InvestigationOutput(proposals=propostas, cost=total)

    def _uma(self, divergencia: Divergence) -> Proposal:
        entrada = self._descrever(divergencia)
        mensagens: list[dict[str, Any]] = [{"role": "user", "content": entrada}]
        custo, tentativas_formato = Cost.zero(), 0
        trace: list[TraceEvent] = [
            TraceEvent(kind="entrada", detail={"divergencia": divergencia.id})
        ]

        for turno in range(1, self.max_turns + 1):
            try:
                resposta = self.client.complete(
                    system=SYSTEM, messages=mensagens, tools=TOOL_SCHEMAS
                )
            except Exception as erro:  # noqa: BLE001
                # Timeout, rede caída, 500 da API. O SDK já tenta de novo por
                # conta própria; se chegou aqui, acabou. Abster é a saída certa:
                # derrubar o processo inteiro por causa de um item transformaria
                # falha de rede em conciliação não entregue.
                trace.append(
                    TraceEvent(kind="erro", detail={"turno": turno, "erro": str(erro)})
                )
                return Proposal.abstencao(
                    divergencia.id, f"falha de API ao investigar: {erro}", custo, trace
                )

            custo = custo + resposta.cost
            trace.append(
                TraceEvent(
                    kind="llm",
                    detail={
                        "turno": turno,
                        "tokens_entrada": resposta.cost.input_tokens,
                        "tokens_saida": resposta.cost.output_tokens,
                        "ferramentas_pedidas": [c.name for c in resposta.tool_calls],
                    },
                )
            )

            if custo.microcents(self.client.model) > self.budget_microcents:
                trace.append(TraceEvent(kind="outcome", detail={"motivo": "orçamento"}))
                return Proposal.abstencao(
                    divergencia.id, "orçamento da divergência esgotado", custo, trace
                )

            if resposta.tool_calls:
                resultados = self._executar(resposta.tool_calls)
                for c in resposta.tool_calls:
                    trace.append(
                        TraceEvent(
                            kind="tool", detail={"nome": c.name, "argumentos": c.arguments}
                        )
                    )
                mensagens.append({"role": "assistant", "content": resposta.text or ""})
                mensagens.append({"role": "user", "content": resultados})
                continue

            proposta = self._interpretar(divergencia.id, resposta.text, custo, trace)
            if proposta is not None:
                return proposta

            tentativas_formato += 1
            if tentativas_formato > self.max_tentativas_formato:
                break
            mensagens.append({"role": "assistant", "content": resposta.text})
            mensagens.append(
                {
                    "role": "user",
                    "content": "Resposta inválida. Responda APENAS o objeto JSON pedido.",
                }
            )

        trace.append(TraceEvent(kind="outcome", detail={"motivo": "sem conclusão"}))
        return Proposal.abstencao(
            divergencia.id,
            "investigação encerrada sem conclusão utilizável",
            custo,
            trace,
        )

    def _descrever(self, d: Divergence) -> str:
        banco = [e for e in self.context.bank if e.id in d.bank_ids]
        contabil = [le for le in self.context.ledger if le.id in d.ledger_ids]
        return json.dumps(
            {
                "divergencia_id": d.id,
                "lancamentos_bancarios": [
                    {
                        "id": e.id,
                        "data": e.date.isoformat(),
                        "valor": e.amount,
                        "descricao": e.description,
                        "contraparte": e.counterparty,
                        "documento": e.document,
                    }
                    for e in banco
                ],
                "lancamentos_contabeis": [
                    ToolContext._ledger_dict(le) for le in contabil
                ],
            },
            ensure_ascii=False,
        )

    def _executar(self, chamadas: list[Any]) -> str:
        """Executa as ferramentas pedidas.

        Erro de ferramenta volta para o modelo como texto, nunca como exceção —
        o modelo consegue se corrigir, o processo não consegue se recuperar de
        um estouro.
        """
        resultados = []
        for c in chamadas:
            metodo = getattr(self.context, c.name, None)
            if metodo is None or c.name not in {s["name"] for s in TOOL_SCHEMAS}:
                resultados.append({"ferramenta": c.name, "erro": "ferramenta inexistente"})
                continue
            try:
                argumentos = {k: v for k, v in c.arguments.items() if v is not None}
                resultados.append({"ferramenta": c.name, "resultado": metodo(**argumentos)})
            except (ValueError, TypeError) as erro:
                resultados.append({"ferramenta": c.name, "erro": str(erro)})
        return json.dumps(resultados, ensure_ascii=False, default=str)

    def _interpretar(
        self, divergence_id: str, texto: str, custo: Cost, trace: list[TraceEvent]
    ) -> Proposal | None:
        """Devolve None quando o texto não é uma proposta utilizável."""
        try:
            dados = json.loads(texto)
        except json.JSONDecodeError:
            return None
        if not isinstance(dados, dict):
            return None
        try:
            tipo = DivergenceType(dados.get("tipo", ""))
            confianca = Confidence(dados.get("confianca", ""))
        except ValueError:
            return None

        evidencia = [str(e) for e in dados.get("evidencia", [])]
        # Afirmar com confiança sem citar nada acontece. Rebaixar é mais útil
        # que descartar: a hipótese ainda ajuda o humano, com o peso certo.
        if confianca is Confidence.ALTA and not evidencia:
            confianca = Confidence.BAIXA

        return Proposal(
            divergence_id=divergence_id,
            tipo=tipo,
            explicacao=str(dados.get("explicacao", "")),
            evidencia=evidencia,
            confianca=confianca,
            acao_sugerida=str(dados.get("acao_sugerida", "investigar_manual")),
            cost=custo,
            trace=[*trace, TraceEvent(kind="outcome", detail={"tipo": tipo.value})],
        )
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/pytest tests/agent/test_investigator.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/agent/investigator.py tests/agent/test_investigator.py
git commit -m "feat: investigador com orçamento, abstenção e recuperação de erro"
```

---

### Task 5: Cliente real da API Anthropic

**Files:**
- Create: `src/orchestrator/agent/anthropic_client.py`
- Modify: `pyproject.toml`
- Test: `tests/agent/test_anthropic_client.py`

**Interfaces:**
- Consumes: `LLMResponse`, `ToolCall`, `Cost`
- Produces: `AnthropicClient(model="claude-opus-5")` satisfazendo `LLMClient`

O teste desta tarefa **não chama a API**. Ele verifica a tradução entre o SDK e
a costura, com um duplo do SDK. A chamada real só acontece na Task 9.

- [ ] **Step 1: Acrescentar a dependência em `pyproject.toml`**

Substituir a linha `dependencies = []` por:

```toml
dependencies = ["anthropic>=1.0"]
```

Rodar: `.venv/Scripts/pip install -e ".[dev]"`

- [ ] **Step 2: Escrever o teste que falha**

Criar `tests/agent/test_anthropic_client.py`:

```python
from types import SimpleNamespace

import pytest

from orchestrator.agent.anthropic_client import AnthropicClient


class _SDKFalso:
    """Duplo do SDK: registra o que recebeu e devolve o que foi preparado."""

    def __init__(self, resposta):
        self._resposta = resposta
        self.recebido = None
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.recebido = kwargs
        return self._resposta


def _resposta_sdk(blocos, uso):
    return SimpleNamespace(content=blocos, usage=uso)


def _uso(entrada=100, saida=50, cache=0):
    return SimpleNamespace(
        input_tokens=entrada, output_tokens=saida, cache_read_input_tokens=cache
    )


def test_traduz_bloco_de_texto():
    sdk = _SDKFalso(_resposta_sdk([SimpleNamespace(type="text", text="oi")], _uso()))
    c = AnthropicClient(model="claude-opus-5", sdk=sdk)

    r = c.complete(system="s", messages=[{"role": "user", "content": "x"}], tools=[])

    assert r.text == "oi"
    assert r.cost.input_tokens == 100
    assert r.cost.calls == 1


def test_traduz_bloco_de_ferramenta():
    bloco = SimpleNamespace(type="tool_use", id="t1", name="buscar_lancamentos",
                            input={"valor": 10})
    sdk = _SDKFalso(_resposta_sdk([bloco], _uso()))
    c = AnthropicClient(model="claude-opus-5", sdk=sdk)

    r = c.complete(system="s", messages=[], tools=[])

    assert r.tool_calls[0].name == "buscar_lancamentos"
    assert r.tool_calls[0].arguments == {"valor": 10}


def test_contabiliza_tokens_de_cache_separado():
    sdk = _SDKFalso(_resposta_sdk([SimpleNamespace(type="text", text="oi")],
                                  _uso(entrada=10, cache=990)))
    c = AnthropicClient(model="claude-opus-5", sdk=sdk)

    r = c.complete(system="s", messages=[], tools=[])

    assert r.cost.cached_tokens == 990
    assert r.cost.input_tokens == 10


def test_marca_o_system_para_cache():
    # System e ferramentas são idênticos entre divergências. Numa execução com
    # 116 delas, cachear isso é a maior economia isolada do plano.
    sdk = _SDKFalso(_resposta_sdk([SimpleNamespace(type="text", text="oi")], _uso()))
    c = AnthropicClient(model="claude-opus-5", sdk=sdk)

    c.complete(system="instrução longa", messages=[], tools=[])

    assert sdk.recebido["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_usa_o_modelo_configurado():
    sdk = _SDKFalso(_resposta_sdk([SimpleNamespace(type="text", text="oi")], _uso()))
    c = AnthropicClient(model="claude-sonnet-5", sdk=sdk)

    c.complete(system="s", messages=[], tools=[])

    assert sdk.recebido["model"] == "claude-sonnet-5"


def test_rejeita_modelo_sem_preco_conhecido():
    # Sem preço não há custo, e sem custo o produto não tem métrica.
    with pytest.raises(ValueError):
        AnthropicClient(model="claude-inventado", sdk=_SDKFalso(None))
```

- [ ] **Step 3: Rodar e confirmar falha**

Run: `.venv/Scripts/pytest tests/agent/test_anthropic_client.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 4: Implementar `src/orchestrator/agent/anthropic_client.py`**

```python
"""Implementação real da costura, sobre o SDK da Anthropic.

Este é o único arquivo do projeto que conhece o SDK. Todo o resto fala com
`LLMClient`.
"""

from typing import Any

from orchestrator.agent.llm import LLMResponse, ToolCall
from orchestrator.agent.proposal import _PRECOS, Cost

_MAX_TOKENS = 2048


class AnthropicClient:
    """Traduz entre o SDK e a costura.

    `sdk` é injetável para teste. Em produção fica None e o cliente real é
    construído na primeira chamada — assim importar o módulo não exige
    credencial.
    """

    def __init__(self, model: str = "claude-opus-5", sdk: Any = None) -> None:
        if model not in _PRECOS:
            raise ValueError(
                f"modelo sem preço conhecido: {model!r}. Sem preço não há custo, "
                f"e sem custo o produto não tem métrica."
            )
        self.model = model
        self._sdk = sdk

    def _cliente(self) -> Any:
        if self._sdk is None:
            import anthropic

            self._sdk = anthropic.Anthropic()
        return self._sdk

    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        resposta = self._cliente().messages.create(
            model=self.model,
            max_tokens=_MAX_TOKENS,
            # System e ferramentas são idênticos entre divergências; marcá-los
            # para cache é a maior economia isolada numa execução com centenas
            # de itens.
            system=[
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ],
            messages=messages,
            tools=tools,
        )

        texto = "".join(b.text for b in resposta.content if b.type == "text")
        chamadas = [
            ToolCall(id=b.id, name=b.name, arguments=dict(b.input))
            for b in resposta.content
            if b.type == "tool_use"
        ]
        uso = resposta.usage
        return LLMResponse(
            text=texto,
            tool_calls=chamadas,
            cost=Cost(
                input_tokens=getattr(uso, "input_tokens", 0),
                output_tokens=getattr(uso, "output_tokens", 0),
                cached_tokens=getattr(uso, "cache_read_input_tokens", 0) or 0,
                calls=1,
            ),
        )
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `.venv/Scripts/pytest tests/agent/test_anthropic_client.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add src/orchestrator/agent/anthropic_client.py tests/agent/test_anthropic_client.py pyproject.toml
git commit -m "feat: cliente real da API com cache de prompt e contabilidade de tokens"
```

---

### Task 6: A cascata passa a incluir o investigador

**Files:**
- Modify: `src/orchestrator/matching/engine.py`
- Test: `tests/matching/test_engine.py`

**Interfaces:**
- Consumes: `InvestigationOutput`, `Proposal`, `Cost`
- Produces: `reconcile(bank, ledger, matchers=None, investigator=None)`; `ReconcileResult` com `proposals: list[Proposal]` e `agent_cost: Cost`

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar a `tests/matching/test_engine.py` — o import vai no bloco do topo:

```python
# No topo do arquivo, junto dos imports existentes:
from orchestrator.agent.proposal import Cost, InvestigationOutput, Proposal

# Os testes abaixo vão ao final do arquivo:


class _InvestigadorFalso:
    name = "falso"

    def __init__(self):
        self.recebeu = None

    def investigate(self, divergences):
        self.recebeu = divergences
        return InvestigationOutput(
            proposals=[Proposal.abstencao(d.id, "teste") for d in divergences],
            cost=Cost(calls=len(divergences)),
        )


def test_sem_investigador_nao_ha_propostas():
    pares = generate_clean_pairs(seed=8, n=10)
    ds = build_dataset(pares, injections=[])

    r = reconcile(ds.bank, ds.ledger)

    assert r.proposals == []
    assert r.agent_cost == Cost.zero()


def test_investigador_recebe_apenas_o_que_sobrou():
    pares = generate_clean_pairs(seed=8, n=10)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])
    espiao = _InvestigadorFalso()

    r = reconcile(ds.bank, ds.ledger, investigator=espiao)

    assert espiao.recebeu == r.divergences
    assert len(r.proposals) == len(r.divergences)


def test_proposta_nao_resolve_a_divergencia():
    # O item continua divergente até um humano aprovar. Se a proposta removesse
    # do pool, a taxa determinística passaria a contar trabalho do agente.
    pares = generate_clean_pairs(seed=8, n=10)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    sem = reconcile(ds.bank, ds.ledger)
    com = reconcile(ds.bank, ds.ledger, investigator=_InvestigadorFalso())

    assert len(com.divergences) == len(sem.divergences)
    assert len(com.matches) == len(sem.matches)


def test_custo_do_agente_e_agregado_no_resultado():
    pares = generate_clean_pairs(seed=8, n=10)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    r = reconcile(ds.bank, ds.ledger, investigator=_InvestigadorFalso())

    assert r.agent_cost.calls == len(r.divergences)
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/Scripts/pytest tests/matching/test_engine.py -v`
Expected: FAIL com `TypeError: reconcile() got an unexpected keyword argument 'investigator'`

- [ ] **Step 3: Modificar `src/orchestrator/matching/engine.py`**

Acrescentar aos imports do topo:

```python
from typing import Any, Protocol

from orchestrator.agent.proposal import Cost, InvestigationOutput, Proposal
```

Acrescentar o protocolo, antes de `ReconcileResult`:

```python
class Investigator(Protocol):
    """Quem investiga o que as camadas determinísticas não resolveram.

    Diferente de um Matcher: não resolve nada. Produz proposta, e o item
    continua divergente até um humano aprovar.
    """

    name: str

    def investigate(self, divergences: list[Divergence]) -> InvestigationOutput: ...
```

Substituir a definição de `ReconcileResult` por:

```python
@dataclass(frozen=True)
class ReconcileResult:
    matches: list[MatchResult]
    divergences: list[Divergence]
    proposals: list[Proposal] = field(default_factory=list)
    agent_cost: Cost = field(default_factory=Cost.zero)
```

Acrescentar `from dataclasses import dataclass, field` se `field` ainda não estiver importado.

Substituir a assinatura e o retorno de `reconcile`:

```python
def reconcile(
    bank: list[BankEntry],
    ledger: list[LedgerEntry],
    matchers: list[Matcher] | None = None,
    investigator: Investigator | None = None,
) -> ReconcileResult:
```

e, no lugar do `return ReconcileResult(...)` atual:

```python
    if investigator is None:
        return ReconcileResult(matches=todos, divergences=divergencias)

    # O investigador recebe SÓ o que sobrou, e o que ele devolve não remove
    # nada do pool: proposta não é resolução.
    saida = investigator.investigate(divergencias)
    return ReconcileResult(
        matches=todos,
        divergences=divergencias,
        proposals=saida.proposals,
        agent_cost=saida.cost,
    )
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/pytest -v`
Expected: toda a suíte passa, incluindo os testes antigos de engine

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/matching/engine.py tests/matching/test_engine.py
git commit -m "feat: cascata aceita investigador sem que proposta resolva divergência"
```

---

### Task 7: Métricas por resolver e precisão das propostas

**Files:**
- Modify: `src/orchestrator/metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: `Proposal`, `Cost`, `ReconcileResult` com propostas
- Produces: `Metrics` com `matches_by_layer: dict[str, int]`, `proposals_total: int`, `proposals_correct: int`, `proposals_abstained: int`, `agent_cost_microcents: int`

Esta é a segunda constatação da lente do spec de composição: os selos do canvas
precisam de número por resolver, não do conjunto. E a precisão das propostas sai
de graça, porque o gabarito da plano 1 já carrega `divergence_type`.

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar a `tests/test_metrics.py` — imports no topo:

```python
# No topo do arquivo, junto dos imports existentes:
from orchestrator.agent.proposal import Confidence, Cost, InvestigationOutput, Proposal

# Os testes abaixo vão ao final do arquivo:


class _InvestigadorQueAcerta:
    """Propõe sempre o tipo que o gabarito diz."""

    name = "acerta"

    def __init__(self, truth):
        self._por_id = {}
        for gt in truth:
            for i in gt.bank_ids | gt.ledger_ids:
                self._por_id[i] = gt.divergence_type

    def investigate(self, divergences):
        propostas = []
        for d in divergences:
            ids = d.bank_ids | d.ledger_ids
            tipo = next((self._por_id[i] for i in ids if i in self._por_id), None)
            if tipo is None:
                propostas.append(Proposal.abstencao(d.id, "fora do gabarito"))
            else:
                propostas.append(
                    Proposal(
                        divergence_id=d.id,
                        tipo=tipo,
                        explicacao="acertou",
                        evidencia=["evidência"],
                        confianca=Confidence.ALTA,
                        acao_sugerida="conciliar",
                        cost=Cost(input_tokens=100, calls=1),
                    )
                )
        return InvestigationOutput(propostas, Cost(input_tokens=100 * len(propostas),
                                                   calls=len(propostas)))


def test_conta_matches_por_camada():
    pares = generate_clean_pairs(seed=9, n=20)
    ds = build_dataset(pares, injections=[])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger))

    assert m.matches_by_layer["L1"] == 20
    assert "L2" not in m.matches_by_layer or m.matches_by_layer["L2"] == 0


def test_sem_investigador_as_metricas_de_proposta_ficam_zeradas():
    pares = generate_clean_pairs(seed=9, n=10)
    ds = build_dataset(pares, injections=[])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger))

    assert m.proposals_total == 0
    assert m.proposals_correct == 0
    assert m.agent_cost_microcents == 0


def test_precisao_das_propostas_contra_o_gabarito():
    pares = generate_clean_pairs(seed=9, n=20)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    r = reconcile(ds.bank, ds.ledger, investigator=_InvestigadorQueAcerta(ds.truth))
    m = evaluate(ds, r)

    assert m.proposals_total == len(r.divergences)
    assert m.proposals_correct >= 1


def test_abstencao_nao_conta_como_acerto_nem_como_erro():
    pares = generate_clean_pairs(seed=9, n=10)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    class _SempreAbstem:
        name = "abstem"

        def investigate(self, divergences):
            ps = [Proposal.abstencao(d.id, "não sei") for d in divergences]
            return InvestigationOutput(ps, Cost.zero())

    m = evaluate(ds, reconcile(ds.bank, ds.ledger, investigator=_SempreAbstem()))

    assert m.proposals_abstained == m.proposals_total
    assert m.proposals_correct == 0


def test_custo_do_agente_aparece_em_microcents():
    pares = generate_clean_pairs(seed=9, n=20)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    r = reconcile(ds.bank, ds.ledger, investigator=_InvestigadorQueAcerta(ds.truth))
    m = evaluate(ds, r, model="claude-opus-5")

    assert m.agent_cost_microcents == r.agent_cost.microcents("claude-opus-5")


def test_render_mostra_camadas_e_propostas():
    pares = generate_clean_pairs(seed=9, n=20)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    saida = evaluate(
        ds, reconcile(ds.bank, ds.ledger, investigator=_InvestigadorQueAcerta(ds.truth))
    ).render()

    assert "L1" in saida
    assert "Propostas" in saida
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/Scripts/pytest tests/test_metrics.py -v`
Expected: FAIL com `AttributeError: 'Metrics' object has no attribute 'matches_by_layer'`

- [ ] **Step 3: Modificar `src/orchestrator/metrics.py`**

Acrescentar ao topo o único import novo que `metrics.py` de fato usa. **Não
importe `Confidence` aqui** — quem usa é o arquivo de teste, e um import morto
faz `ruff check` falhar com F401:

```python
from orchestrator.taxonomy import DivergenceType
```

Acrescentar estes campos a `Metrics`, logo após `truth_by_type`:

```python
    matches_by_layer: dict[str, int]
    proposals_total: int
    proposals_correct: int
    proposals_abstained: int
    agent_cost_microcents: int
```

Acrescentar ao final da lista de linhas em `render`, antes do bloco do gabarito
por tipo:

```python
        linhas.append("")
        linhas.append("Resoluções por camada:")
        for camada, n in sorted(self.matches_by_layer.items()):
            linhas.append(f"  {camada:<24} {n}")
        if self.proposals_total:
            linhas.append("")
            linhas.append(f"Propostas do agente:           {self.proposals_total}")
            linhas.append(f"  corretas contra o gabarito:  {self.proposals_correct}")
            linhas.append(f"  abstenções:                  {self.proposals_abstained}")
            linhas.append(
                f"  custo:                       "
                f"US$ {self.agent_cost_microcents / 100_000_000:.4f}"
            )
```

Mudar a assinatura de `evaluate` para aceitar o modelo:

```python
def evaluate(
    dataset: Dataset, result: ReconcileResult, model: str = "claude-opus-5"
) -> Metrics:
```

Acrescentar, antes do `return Metrics(...)`:

`Counter` já está importado no topo de `metrics.py` — use aquele, sem alias
local:

```python
    por_camada = dict(Counter(m.layer for m in result.matches))

    # A precisão das propostas sai de graça: o gabarito da plano 1 já carrega o
    # tipo de cada divergência injetada. Uma proposta está correta quando o tipo
    # que ela propõe é o tipo que o gabarito registra para algum id que ela toca.
    tipo_por_id: dict[str, DivergenceType] = {}
    for gt in dataset.truth:
        for i in gt.bank_ids | gt.ledger_ids:
            tipo_por_id[i] = gt.divergence_type

    divergencia_por_id = {d.id: (d.bank_ids | d.ledger_ids) for d in result.divergences}
    corretas = abstencoes = 0
    for p in result.proposals:
        if p.tipo is DivergenceType.NAO_IDENTIFICADO:
            abstencoes += 1
            continue
        ids = divergencia_por_id.get(p.divergence_id, frozenset())
        if any(tipo_por_id.get(i) is p.tipo for i in ids):
            corretas += 1
```

e acrescentar ao construtor `Metrics(...)`:

```python
        matches_by_layer=por_camada,
        proposals_total=len(result.proposals),
        proposals_correct=corretas,
        proposals_abstained=abstencoes,
        agent_cost_microcents=result.agent_cost.microcents(model)
        if result.proposals
        else 0,
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/pytest -v`
Expected: toda a suíte passa

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/metrics.py tests/test_metrics.py
git commit -m "feat: métricas por camada e precisão das propostas contra o gabarito"
```

---

### Task 8: Gravação e reprise de sessões reais

**Files:**
- Create: `src/orchestrator/eval/__init__.py`
- Create: `src/orchestrator/eval/replay.py`
- Create: `tests/eval/__init__.py`
- Test: `tests/eval/test_replay.py`

**Interfaces:**
- Consumes: `LLMClient`, `LLMResponse`, `ToolCall`, `Cost`
- Produces: `RecordingClient(inner, path)`, `ReplayClient(path)`

A camada do meio dos três níveis de teste: uma gravação feita uma vez contra a
API real vira teste determinístico e gratuito para sempre.

- [ ] **Step 1: Criar diretórios**

```bash
mkdir -p src/orchestrator/eval tests/eval
touch src/orchestrator/eval/__init__.py tests/eval/__init__.py
git add src/orchestrator/eval/__init__.py tests/eval/__init__.py
git ls-files src/orchestrator/eval tests/eval
```

Confirme que os dois `__init__.py` aparecem antes de seguir.

- [ ] **Step 2: Escrever o teste que falha**

Criar `tests/eval/test_replay.py`:

```python
import pytest

from orchestrator.agent.llm import FakeLLMClient, LLMResponse, ToolCall
from orchestrator.agent.proposal import Cost
from orchestrator.eval.replay import RecordingClient, ReplayClient


def _respostas():
    return [
        LLMResponse(
            text="",
            tool_calls=[ToolCall(id="t1", name="historico_fornecedor",
                                 arguments={"fornecedor": "ACME"})],
            cost=Cost(input_tokens=10, calls=1),
        ),
        LLMResponse(text='{"tipo":"ESTORNO"}', tool_calls=[],
                    cost=Cost(input_tokens=20, output_tokens=5, calls=1)),
    ]


def test_gravacao_devolve_o_que_o_interno_devolveu(tmp_path):
    destino = tmp_path / "sessao.jsonl"
    gravador = RecordingClient(FakeLLMClient(_respostas()), destino)

    primeira = gravador.complete(system="s", messages=[], tools=[])

    assert primeira.tool_calls[0].name == "historico_fornecedor"
    assert destino.exists()


def test_reprise_reproduz_a_gravacao_sem_cliente_interno(tmp_path):
    destino = tmp_path / "sessao.jsonl"
    gravador = RecordingClient(FakeLLMClient(_respostas()), destino)
    gravador.complete(system="s", messages=[], tools=[])
    gravador.complete(system="s", messages=[], tools=[])

    reprise = ReplayClient(destino)
    a = reprise.complete(system="s", messages=[], tools=[])
    b = reprise.complete(system="s", messages=[], tools=[])

    assert a.tool_calls[0].arguments == {"fornecedor": "ACME"}
    assert b.text == '{"tipo":"ESTORNO"}'
    assert b.cost.output_tokens == 5


def test_reprise_preserva_o_modelo_gravado(tmp_path):
    destino = tmp_path / "sessao.jsonl"
    RecordingClient(
        FakeLLMClient(_respostas()[:1], model="claude-sonnet-5"), destino
    ).complete(system="s", messages=[], tools=[])

    assert ReplayClient(destino).model == "claude-sonnet-5"


def test_reprise_estoura_quando_pedem_mais_do_que_foi_gravado(tmp_path):
    destino = tmp_path / "sessao.jsonl"
    RecordingClient(FakeLLMClient(_respostas()[:1]), destino).complete(
        system="s", messages=[], tools=[]
    )
    reprise = ReplayClient(destino)
    reprise.complete(system="s", messages=[], tools=[])

    with pytest.raises(AssertionError):
        reprise.complete(system="s", messages=[], tools=[])


def test_reprise_de_arquivo_inexistente_e_erro_claro(tmp_path):
    with pytest.raises(FileNotFoundError):
        ReplayClient(tmp_path / "nao-existe.jsonl")
```

- [ ] **Step 3: Rodar e confirmar falha**

Run: `.venv/Scripts/pytest tests/eval/test_replay.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 4: Implementar `src/orchestrator/eval/replay.py`**

```python
"""Gravação e reprise de sessões do modelo.

A camada do meio dos três níveis de teste: grava-se uma vez contra a API real, e
aquilo vira teste determinístico e gratuito para sempre. Pega regressão no laço,
no parsing e nas ferramentas — não pega mudança de comportamento do modelo, que
é trabalho da avaliação ao vivo.
"""

import json
from pathlib import Path
from typing import Any

from orchestrator.agent.llm import LLMClient, LLMResponse, ToolCall
from orchestrator.agent.proposal import Cost


def _serializar(r: LLMResponse, model: str) -> str:
    return json.dumps(
        {
            "model": model,
            "text": r.text,
            "tool_calls": [
                {"id": c.id, "name": c.name, "arguments": c.arguments} for c in r.tool_calls
            ],
            "cost": {
                "input_tokens": r.cost.input_tokens,
                "output_tokens": r.cost.output_tokens,
                "cached_tokens": r.cost.cached_tokens,
                "calls": r.cost.calls,
            },
        },
        ensure_ascii=False,
    )


def _desserializar(linha: str) -> tuple[str, LLMResponse]:
    d = json.loads(linha)
    return d["model"], LLMResponse(
        text=d["text"],
        tool_calls=[ToolCall(**c) for c in d["tool_calls"]],
        cost=Cost(**d["cost"]),
    )


class RecordingClient:
    """Repassa para o cliente interno e grava a resposta."""

    def __init__(self, inner: LLMClient, path: Path) -> None:
        self._inner = inner
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text("", encoding="utf-8")

    @property
    def model(self) -> str:
        return self._inner.model

    def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        resposta = self._inner.complete(system=system, messages=messages, tools=tools)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(_serializar(resposta, self._inner.model) + "\n")
        return resposta


class ReplayClient:
    """Reproduz uma gravação, em ordem, sem tocar em rede nenhuma."""

    def __init__(self, path: Path) -> None:
        caminho = Path(path)
        if not caminho.exists():
            raise FileNotFoundError(f"gravação não encontrada: {caminho}")
        linhas = [l for l in caminho.read_text(encoding="utf-8").splitlines() if l.strip()]
        pares = [_desserializar(l) for l in linhas]
        self.model = pares[0][0] if pares else "desconhecido"
        self._respostas = [r for _, r in pares]
        self._indice = 0

    def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        assert self._indice < len(self._respostas), (
            f"a reprise tem {len(self._respostas)} turnos gravados, mas o laço "
            f"pediu o turno {self._indice + 1} — o comportamento mudou desde a gravação"
        )
        resposta = self._respostas[self._indice]
        self._indice += 1
        return resposta
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `.venv/Scripts/pytest tests/eval/test_replay.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add src/orchestrator/eval tests/eval
git commit -m "feat: gravação e reprise de sessões para teste determinístico"
```

---

### Task 9: Avaliação ao vivo e comparação entre modelos

**Files:**
- Create: `src/orchestrator/eval/agent_eval.py`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Test: `tests/eval/test_agent_eval.py`

**Interfaces:**
- Consumes: `build_benchmark` de `orchestrator.cli`; `reconcile`, `evaluate`; `Investigator`, `AnthropicClient`, `ToolContext`
- Produces: `avaliar(model, seed, n, taxa_divergencia, client_factory) -> EvalResult`; `main(argv) -> int` registrado como `orchestrator-eval`

Esta é a terceira camada: a única que gasta dinheiro e a única que diz se o
produto presta. Ela roda os modelos contra o **mesmo** gabarito, que é o que
transforma escolha de modelo em medição em vez de intuição.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/eval/test_agent_eval.py`:

```python
from orchestrator.agent.llm import FakeLLMClient, LLMResponse
from orchestrator.agent.proposal import Cost
from orchestrator.eval.agent_eval import EvalResult, avaliar


def _fabrica_falsa(model: str):
    """Sempre devolve a mesma proposta, sem tocar em rede."""
    def fabrica():
        return FakeLLMClient(
            model=model,
            respostas=[
                LLMResponse(
                    text='{"tipo":"DEFASAGEM_TEMPORAL","explicacao":"atraso",'
                         '"evidencia":["b1"],"confianca":"MEDIA",'
                         '"acao_sugerida":"conciliar"}',
                    tool_calls=[],
                    cost=Cost(input_tokens=50, output_tokens=20, calls=1),
                )
            ]
            * 500
        )
    return fabrica


def test_avaliacao_devolve_resultado_completo():
    r = avaliar(model="claude-opus-5", seed=1, n=40, taxa_divergencia=0.15,
                client_factory=_fabrica_falsa("claude-opus-5"))

    assert isinstance(r, EvalResult)
    assert r.model == "fake"
    assert r.proposals_total > 0


def test_precisao_fica_entre_zero_e_um():
    r = avaliar(model="claude-opus-5", seed=1, n=40, taxa_divergencia=0.15,
                client_factory=_fabrica_falsa("claude-opus-5"))

    assert 0.0 <= r.precision <= 1.0


def test_custo_por_divergencia_e_inteiro_em_microcents():
    r = avaliar(model="claude-opus-5", seed=1, n=40, taxa_divergencia=0.15,
                client_factory=_fabrica_falsa("claude-opus-5"))

    assert isinstance(r.microcents_per_divergence, int)


def test_avaliacao_e_deterministica_para_a_mesma_semente():
    a = avaliar(model="claude-opus-5", seed=5, n=40, taxa_divergencia=0.15,
                client_factory=_fabrica_falsa("claude-opus-5"))
    b = avaliar(model="claude-opus-5", seed=5, n=40, taxa_divergencia=0.15,
                client_factory=_fabrica_falsa("claude-opus-5"))

    assert a.precision == b.precision
    assert a.proposals_total == b.proposals_total


def test_render_nomeia_o_modelo_e_a_precisao():
    saida = avaliar(model="claude-opus-5", seed=1, n=40, taxa_divergencia=0.15,
                    client_factory=_fabrica_falsa("claude-opus-5")).render()

    assert "claude-opus-5" in saida
    assert "Precisão" in saida
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/Scripts/pytest tests/eval/test_agent_eval.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `src/orchestrator/eval/agent_eval.py`**

```python
"""Avaliação ao vivo do investigador contra o gabarito sintético.

A terceira e última camada de teste: a única que gasta dinheiro e a única que
diz se o produto presta. Roda modelos diferentes contra o MESMO gabarito, que é
o que transforma escolha de modelo em medição.

O gabarito não precisou ser construído para isto — ele já existe desde a plano 1.
"""

import argparse
from collections.abc import Callable
from dataclasses import dataclass

from orchestrator.agent.investigator import Investigator
from orchestrator.agent.llm import LLMClient
from orchestrator.agent.tools import ToolContext
from orchestrator.cli import build_benchmark
from orchestrator.matching.engine import reconcile
from orchestrator.metrics import evaluate

MODELOS_PADRAO = ("claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5")


@dataclass(frozen=True)
class EvalResult:
    model: str
    divergences: int
    proposals_total: int
    proposals_correct: int
    proposals_abstained: int
    total_microcents: int

    @property
    def precision(self) -> float:
        """Das propostas que arriscaram um tipo, quantas acertaram."""
        arriscadas = self.proposals_total - self.proposals_abstained
        return self.proposals_correct / arriscadas if arriscadas else 0.0

    @property
    def abstention_rate(self) -> float:
        return self.proposals_abstained / self.proposals_total if self.proposals_total else 0.0

    @property
    def microcents_per_divergence(self) -> int:
        return self.total_microcents // self.divergences if self.divergences else 0

    def render(self) -> str:
        return "\n".join(
            [
                f"Modelo:                        {self.model}",
                f"Divergências investigadas:     {self.divergences}",
                f"Precisão (das que arriscaram): {self.precision:.1%}",
                f"Taxa de abstenção:             {self.abstention_rate:.1%}",
                f"Custo total:                   "
                f"US$ {self.total_microcents / 100_000_000:.4f}",
                f"Custo por divergência:         "
                f"US$ {self.microcents_per_divergence / 100_000_000:.6f}",
            ]
        )


def _fabrica_real(model: str) -> Callable[[], LLMClient]:
    def fabrica() -> LLMClient:
        from orchestrator.agent.anthropic_client import AnthropicClient

        return AnthropicClient(model=model)

    return fabrica


def avaliar(
    model: str,
    seed: int,
    n: int,
    taxa_divergencia: float,
    client_factory: Callable[[], LLMClient] | None = None,
) -> EvalResult:
    dataset = build_benchmark(seed=seed, n=n, taxa_divergencia=taxa_divergencia)
    cliente = (client_factory or _fabrica_real(model))()
    investigador = Investigator(
        client=cliente, context=ToolContext(bank=dataset.bank, ledger=dataset.ledger)
    )

    resultado = reconcile(dataset.bank, dataset.ledger, investigator=investigador)
    metricas = evaluate(dataset, resultado, model=cliente.model)

    return EvalResult(
        model=model,
        divergences=len(resultado.divergences),
        proposals_total=metricas.proposals_total,
        proposals_correct=metricas.proposals_correct,
        proposals_abstained=metricas.proposals_abstained,
        total_microcents=metricas.agent_cost_microcents,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Avalia o investigador contra o gabarito sintético. GASTA DINHEIRO."
    )
    parser.add_argument("--model", action="append", default=None,
                        help="pode repetir para comparar modelos")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--taxa-divergencia", type=float, default=0.15)
    args = parser.parse_args(argv)

    for modelo in args.model or list(MODELOS_PADRAO):
        print(avaliar(modelo, args.seed, args.n, args.taxa_divergencia).render())
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Registrar o comando em `pyproject.toml`**

Acrescentar ao bloco `[project.scripts]` existente:

```toml
orchestrator-eval = "orchestrator.eval.agent_eval:main"
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `.venv/Scripts/pytest -v`
Expected: toda a suíte passa, sem nenhuma chamada de rede

- [ ] **Step 6: Atualizar o README**

Acrescentar ao final da seção de uso:

```markdown
### Avaliar o agente (gasta dinheiro)

Exige `ANTHROPIC_API_KEY` no ambiente ou `ant auth login`.

```bash
orchestrator-eval --n 100 --seed 1
```

Sem `--model`, compara `claude-opus-5`, `claude-sonnet-5` e `claude-haiku-4-5`
contra o mesmo gabarito. A suíte de testes não faz nenhuma chamada de API.
```

- [ ] **Step 7: Rodar `ruff` e commitar**

```bash
.venv/Scripts/ruff check src tests --fix
git add src/orchestrator/eval tests/eval pyproject.toml README.md
git commit -m "feat: avaliação ao vivo com comparação entre modelos"
```

---

## Verificação final

- [ ] `.venv/Scripts/pytest -v` — toda a suíte passa
- [ ] `.venv/Scripts/ruff check src tests` — sem achados
- [ ] **Nenhum teste faz chamada de rede.** Confirmar com `grep -rn "AnthropicClient()" tests/` — não deve haver construção sem `sdk=` injetado
- [ ] `orchestrator --seed 1 --n 500` continua funcionando e reportando a mesma taxa determinística de antes — o agente não pode ter mudado o número do núcleo
- [ ] A taxa determinística e os falsos positivos/negativos continuam iguais aos da plano 1

**O resultado que importa deste plano é uma decisão, não um número:** rodar
`orchestrator-eval` e descobrir qual modelo tem precisão suficiente pelo menor
custo por divergência. Se o mais barato empatar com o mais caro, isso vale mais
que qualquer otimização de prompt.
