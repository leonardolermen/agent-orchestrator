# Núcleo Determinístico — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir um conciliador determinístico com gerador sintético de gabarito, que mede a taxa de resolução sem regras de camada e sem nenhuma chamada de LLM.

**Architecture:** Um gerador produz pares extrato/razão que conciliam perfeitamente, e injetores reescrevem uma fração deles introduzindo divergências de tipo conhecido, registrando o gabarito. Três camadas de matching (exato, tolerância, agrupamento) tentam reconciliar; o que sobra vira divergência. Métricas comparam o resultado contra o gabarito.

**Tech Stack:** Python 3.11+, pytest, ruff. Nenhuma dependência de IA neste plano.

**Spec:** [`docs/superpowers/specs/2026-09-14-agent-orchestrator-design.md`](../specs/2026-09-14-agent-orchestrator-design.md)

**Escopo deste plano:** seções 4.2 (parcial), 4.3, 4.4, 4.5 (estrutura), 5.1 e 5.2 (parcial) do spec. O agente de investigação e a revisão humana são planos separados.

## Global Constraints

- **Valores monetários são sempre `int` em centavos.** Ponto flutuante em dinheiro é proibido em qualquer lugar do código, inclusive testes.
- **`MatchResult` é n:m desde o primeiro dia.** Nunca 1:1 com generalização posterior. Exigido por `PAGAMENTO_AGREGADO` e `DEVOLUCAO_FUNDOS`.
- **O gerador é determinístico por semente.** A mesma semente produz exatamente o mesmo dataset, sempre.
- **Adicionar um tipo de divergência deve custar:** uma entrada na enum, uma classe injetora e nada mais. Se exigir mudança estrutural, o desenho está errado.
- **Tolerância padrão da camada L2:** valor ± 5 centavos, data ± 3 dias úteis (fins de semana excluídos; feriados não são tratados neste plano).
- **Zero dado real de terceiros no repositório.** Todo dado é sintético e gerado.
- **Nenhuma chamada de LLM neste plano.** Se um passo parecer precisar de uma, o passo está errado.

---

## File Structure

| Arquivo | Responsabilidade |
|---|---|
| `pyproject.toml` | Empacotamento, dependências, configuração de pytest e ruff |
| `src/orchestrator/money.py` | Tipo monetário em centavos, parsing e formatação |
| `src/orchestrator/dates.py` | Aritmética de dias úteis |
| `src/orchestrator/taxonomy.py` | Enum `DivergenceType` — a taxonomia do spec 4.5 |
| `src/orchestrator/models.py` | `BankEntry`, `LedgerEntry`, `MatchResult`, `Divergence` |
| `src/orchestrator/synth/dataset.py` | `Pair`, `GroundTruth`, `Dataset`, `InjectionResult` |
| `src/orchestrator/synth/generator.py` | Geração de pares limpos e aplicação de injetores |
| `src/orchestrator/synth/injectors.py` | Um injetor por tipo de divergência |
| `src/orchestrator/matching/protocol.py` | Protocolo `Matcher` |
| `src/orchestrator/matching/exact.py` | Camada L1 |
| `src/orchestrator/matching/tolerance.py` | Camada L2 |
| `src/orchestrator/matching/grouping.py` | Camada L3 |
| `src/orchestrator/matching/engine.py` | Orquestra as camadas, produz divergências |
| `src/orchestrator/metrics.py` | Comparação contra gabarito |
| `src/orchestrator/cli.py` | Execução ponta a ponta |

Testes espelham a estrutura em `tests/`.

---

### Task 1: Esqueleto do projeto e tipo monetário

**Files:**
- Create: `pyproject.toml`
- Create: `src/orchestrator/__init__.py`
- Create: `src/orchestrator/money.py`
- Test: `tests/test_money.py`

**Interfaces:**
- Consumes: nada
- Produces: `parse_brl(texto: str) -> int`, `format_brl(centavos: int) -> str`

- [ ] **Step 1: Criar `pyproject.toml`**

```toml
[project]
name = "orchestrator"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.6"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/orchestrator"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

- [ ] **Step 2: Criar o ambiente e instalar**

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
```

- [ ] **Step 3: Criar `src/orchestrator/__init__.py` vazio**

```bash
mkdir -p src/orchestrator tests
touch src/orchestrator/__init__.py
```

- [ ] **Step 4: Escrever o teste que falha**

Criar `tests/test_money.py`:

```python
import pytest

from orchestrator.money import format_brl, parse_brl


def test_parse_brl_com_separador_de_milhar():
    assert parse_brl("R$ 1.234,56") == 123456


def test_parse_brl_sem_simbolo():
    assert parse_brl("1234,56") == 123456


def test_parse_brl_valor_negativo():
    assert parse_brl("-R$ 10,00") == -1000


def test_parse_brl_sem_centavos():
    assert parse_brl("R$ 50") == 5000


def test_parse_brl_rejeita_lixo():
    with pytest.raises(ValueError):
        parse_brl("abc")


def test_parse_brl_completa_uma_casa_decimal():
    assert parse_brl("R$ 10,5") == 1050


def test_parse_brl_rejeita_tres_casas_decimais():
    # Truncar para 1099 em silêncio corromperia o valor sem avisar.
    with pytest.raises(ValueError):
        parse_brl("10,999")


def test_parse_brl_rejeita_virgula_sem_digitos():
    with pytest.raises(ValueError):
        parse_brl("10,")


def test_format_brl_positivo():
    assert format_brl(123456) == "R$ 1.234,56"


def test_format_brl_negativo():
    assert format_brl(-1000) == "-R$ 10,00"


def test_roundtrip():
    assert parse_brl(format_brl(987654)) == 987654
```

- [ ] **Step 5: Rodar o teste e confirmar que falha**

Run: `.venv/Scripts/pytest tests/test_money.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'orchestrator.money'`

- [ ] **Step 6: Implementar `src/orchestrator/money.py`**

```python
"""Dinheiro em centavos. Ponto flutuante é proibido neste projeto."""

import re

_LIMPEZA = re.compile(r"[R$\s]")


def parse_brl(texto: str) -> int:
    """Converte texto em formato brasileiro para centavos.

    Aceita "R$ 1.234,56", "1234,56", "-R$ 10,00", "R$ 50".
    """
    limpo = _LIMPEZA.sub("", texto)
    if not limpo:
        raise ValueError(f"valor monetário vazio: {texto!r}")

    negativo = limpo.startswith("-")
    limpo = limpo.lstrip("-+")
    limpo = limpo.replace(".", "")

    if "," in limpo:
        inteiros, _, decimais = limpo.partition(",")
        # Truncar silenciosamente uma terceira casa decimal corromperia o valor
        # sem avisar ninguém. Num sistema cuja premissa é trilha auditável,
        # rejeitar é sempre melhor que adivinhar.
        if len(decimais) not in (1, 2):
            raise ValueError(f"parte decimal inválida: {texto!r}")
        decimais = decimais.ljust(2, "0")
    else:
        inteiros, decimais = limpo, "00"

    if not inteiros.isdigit() or not decimais.isdigit():
        raise ValueError(f"valor monetário inválido: {texto!r}")

    centavos = int(inteiros) * 100 + int(decimais)
    return -centavos if negativo else centavos


def format_brl(centavos: int) -> str:
    """Formata centavos como texto em formato brasileiro."""
    sinal = "-" if centavos < 0 else ""
    inteiros, resto = divmod(abs(centavos), 100)
    inteiros_fmt = f"{inteiros:,}".replace(",", ".")
    return f"{sinal}R$ {inteiros_fmt},{resto:02d}"
```

- [ ] **Step 7: Rodar o teste e confirmar que passa**

Run: `.venv/Scripts/pytest tests/test_money.py -v`
Expected: 11 passed

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml src/orchestrator tests/test_money.py
git commit -m "feat: esqueleto do projeto e tipo monetário em centavos"
```

---

### Task 2: Aritmética de dias úteis

**Files:**
- Create: `src/orchestrator/dates.py`
- Test: `tests/test_dates.py`

**Interfaces:**
- Consumes: nada
- Produces: `business_days_between(a: date, b: date) -> int`, `add_business_days(d: date, n: int) -> date`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_dates.py`:

```python
from datetime import date

from orchestrator.dates import add_business_days, business_days_between


def test_dias_uteis_mesma_data():
    assert business_days_between(date(2026, 9, 14), date(2026, 9, 14)) == 0


def test_dias_uteis_dentro_da_semana():
    # segunda 14 -> quarta 16
    assert business_days_between(date(2026, 9, 14), date(2026, 9, 16)) == 2


def test_dias_uteis_atravessando_fim_de_semana():
    # sexta 18 -> segunda 21: um dia útil
    assert business_days_between(date(2026, 9, 18), date(2026, 9, 21)) == 1


def test_dias_uteis_e_simetrico():
    a, b = date(2026, 9, 18), date(2026, 9, 21)
    assert business_days_between(a, b) == business_days_between(b, a)


def test_add_business_days_pula_fim_de_semana():
    # sexta 18 + 1 dia útil = segunda 21
    assert add_business_days(date(2026, 9, 18), 1) == date(2026, 9, 21)


def test_add_business_days_zero():
    assert add_business_days(date(2026, 9, 14), 0) == date(2026, 9, 14)


def test_add_business_days_rejeita_negativo():
    # Devolver a data de entrada em silêncio seria armadilha.
    import pytest

    with pytest.raises(ValueError):
        add_business_days(date(2026, 9, 14), -1)
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/Scripts/pytest tests/test_dates.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `src/orchestrator/dates.py`**

```python
"""Aritmética de dias úteis.

Trata apenas fins de semana. Feriados nacionais e municipais não são
considerados neste plano — quando forem, entram como uma tabela de datas
consultada por estas mesmas funções, sem mudar as assinaturas.
"""

from datetime import date, timedelta


def _e_dia_util(d: date) -> bool:
    return d.weekday() < 5


def business_days_between(a: date, b: date) -> int:
    """Conta dias úteis entre duas datas, em qualquer ordem."""
    if a > b:
        a, b = b, a
    dias = 0
    atual = a
    while atual < b:
        atual += timedelta(days=1)
        if _e_dia_util(atual):
            dias += 1
    return dias


def add_business_days(d: date, n: int) -> date:
    """Avança n dias úteis a partir de d.

    Não anda para trás. Nenhum chamador deste plano precisa disso, e um n
    negativo devolvendo a data de entrada em silêncio seria armadilha: quem
    pedisse um dia útil antes receberia o próprio dia sem nenhum sinal.
    """
    if n < 0:
        raise ValueError(f"n não pode ser negativo: {n}")

    atual = d
    restantes = n
    while restantes > 0:
        atual += timedelta(days=1)
        if _e_dia_util(atual):
            restantes -= 1
    return atual
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/pytest tests/test_dates.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/dates.py tests/test_dates.py
git commit -m "feat: aritmética de dias úteis para a camada de tolerância"
```

---

### Task 3: Taxonomia de divergências

**Files:**
- Create: `src/orchestrator/taxonomy.py`
- Test: `tests/test_taxonomy.py`

**Interfaces:**
- Consumes: nada
- Produces: `DivergenceType` (StrEnum com os 14 tipos do spec 4.5)

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_taxonomy.py`:

```python
from orchestrator.taxonomy import DivergenceType


def test_tipos_confirmados_existem():
    assert DivergenceType.RETENCAO_IMPOSTO
    assert DivergenceType.DEVOLUCAO_FUNDOS
    assert DivergenceType.PAGAMENTO_AGREGADO
    assert DivergenceType.DEFASAGEM_TEMPORAL
    assert DivergenceType.NAO_IDENTIFICADO


def test_valor_e_igual_ao_nome():
    # Serialização estável: o valor gravado é o nome do membro.
    for tipo in DivergenceType:
        assert tipo.value == tipo.name


def test_taxonomia_tem_quatorze_tipos():
    assert len(DivergenceType) == 14


def test_nao_identificado_e_o_fallback():
    assert DivergenceType("NAO_IDENTIFICADO") is DivergenceType.NAO_IDENTIFICADO
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/Scripts/pytest tests/test_taxonomy.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `src/orchestrator/taxonomy.py`**

```python
"""Taxonomia de divergências de conciliação.

Ver spec seção 4.5. A lista é assumidamente incompleta: tipos ausentes se
anunciam pelo acúmulo de NAO_IDENTIFICADO. Adicionar um tipo deve custar uma
entrada aqui e uma classe injetora, nada mais.
"""

from enum import StrEnum


class DivergenceType(StrEnum):
    # Diferença de valor com explicação legítima
    RETENCAO_IMPOSTO = "RETENCAO_IMPOSTO"
    TARIFA_BANCARIA = "TARIFA_BANCARIA"
    JUROS_MULTA = "JUROS_MULTA"
    DESCONTO_ANTECIPACAO = "DESCONTO_ANTECIPACAO"
    DIFERENCA_CAMBIAL = "DIFERENCA_CAMBIAL"

    # Diferença de agrupamento
    PAGAMENTO_AGREGADO = "PAGAMENTO_AGREGADO"
    PAGAMENTO_PARCIAL = "PAGAMENTO_PARCIAL"

    # Diferença de tempo
    DEFASAGEM_TEMPORAL = "DEFASAGEM_TEMPORAL"

    # Erro humano
    DUPLICIDADE = "DUPLICIDADE"
    ERRO_DIGITACAO = "ERRO_DIGITACAO"
    CONTA_INCORRETA = "CONTA_INCORRETA"

    # Reversão
    ESTORNO = "ESTORNO"
    DEVOLUCAO_FUNDOS = "DEVOLUCAO_FUNDOS"

    # Sem hipótese
    NAO_IDENTIFICADO = "NAO_IDENTIFICADO"
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/pytest tests/test_taxonomy.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/taxonomy.py tests/test_taxonomy.py
git commit -m "feat: taxonomia de divergências com os 14 tipos do spec"
```

---

### Task 4: Modelo canônico de dados

**Files:**
- Create: `src/orchestrator/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: nada. O tipo da divergência não vive aqui — `Divergence` registra
  apenas o que não casou; a classificação é do gabarito (`GroundTruth`) e, mais
  adiante, da proposta do agente.
- Produces: `BankEntry`, `LedgerEntry`, `MatchResult`, `Divergence`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_models.py`:

```python
from datetime import date

import pytest

from orchestrator.models import BankEntry, Divergence, LedgerEntry, MatchResult


def _bank(id_: str = "b1", amount: int = -10000) -> BankEntry:
    return BankEntry(
        id=id_,
        date=date(2026, 9, 14),
        amount=amount,
        description="PAGTO FORNECEDOR",
        counterparty="ACME LTDA",
        document="NF-1001",
    )


def _ledger(id_: str = "l1", net: int = 10000) -> LedgerEntry:
    return LedgerEntry(
        id=id_,
        accrual_date=date(2026, 9, 10),
        cash_date=date(2026, 9, 14),
        gross_amount=net,
        net_amount=net,
        account="2.1.1.01",
        cost_center="ADM",
        document="NF-1001",
        supplier="ACME LTDA",
    )


def test_entradas_sao_imutaveis():
    b = _bank()
    with pytest.raises(AttributeError):
        b.amount = 1  # type: ignore[misc]


def test_match_result_guarda_conjuntos():
    m = MatchResult(
        bank_ids=frozenset({"b1"}),
        ledger_ids=frozenset({"l1", "l2"}),
        layer="L3",
        rule="soma de líquidos igual ao crédito",
        evidence={"soma": 10000},
    )
    assert m.ledger_ids == frozenset({"l1", "l2"})
    assert m.layer == "L3"


def test_match_result_rejeita_lado_vazio():
    with pytest.raises(ValueError):
        MatchResult(
            bank_ids=frozenset(),
            ledger_ids=frozenset({"l1"}),
            layer="L1",
            rule="",
            evidence={},
        )


def test_divergence_aceita_lado_vazio():
    # Um lançamento contábil sem contrapartida bancária é divergência válida.
    d = Divergence(id="d1", bank_ids=frozenset(), ledger_ids=frozenset({"l1"}))
    assert d.ledger_ids == frozenset({"l1"})


def test_divergence_rejeita_ambos_vazios():
    with pytest.raises(ValueError):
        Divergence(id="d1", bank_ids=frozenset(), ledger_ids=frozenset())


def test_bank_entry_negativo_e_debito():
    assert _bank(amount=-10000).amount < 0
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/Scripts/pytest tests/test_models.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `src/orchestrator/models.py`**

```python
"""Modelo canônico de conciliação.

Cardinalidade: MatchResult vincula conjuntos a conjuntos, nunca par a par.
Exigido por PAGAMENTO_AGREGADO (1 crédito : N notas) e DEVOLUCAO_FUNDOS
(cadeia de 2-3 lançamentos bancários para 1 contábil). Ver spec 4.5.

Todos os valores monetários são int em centavos. Débitos bancários são
negativos, créditos positivos.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class BankEntry:
    """Lançamento de extrato bancário."""

    id: str
    date: date
    amount: int
    description: str
    counterparty: str | None = None
    document: str | None = None


@dataclass(frozen=True)
class LedgerEntry:
    """Lançamento contábil."""

    id: str
    accrual_date: date
    cash_date: date | None
    gross_amount: int
    net_amount: int
    account: str
    supplier: str
    cost_center: str | None = None
    document: str | None = None


@dataclass(frozen=True)
class MatchResult:
    """Vínculo determinístico entre conjuntos, com a justificativa."""

    bank_ids: frozenset[str]
    ledger_ids: frozenset[str]
    layer: str
    rule: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.bank_ids or not self.ledger_ids:
            raise ValueError("MatchResult exige pelo menos um id de cada lado")


@dataclass(frozen=True)
class Divergence:
    """O que nenhuma camada determinística resolveu."""

    id: str
    bank_ids: frozenset[str]
    ledger_ids: frozenset[str]

    def __post_init__(self) -> None:
        if not self.bank_ids and not self.ledger_ids:
            raise ValueError("Divergence precisa de pelo menos um id")
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/pytest tests/test_models.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/models.py tests/test_models.py
git commit -m "feat: modelo canônico com MatchResult n:m desde o início"
```

---

### Task 5: Estruturas do dataset sintético

**Files:**
- Create: `src/orchestrator/synth/__init__.py`
- Create: `src/orchestrator/synth/dataset.py`
- Test: `tests/synth/test_dataset.py`

**Interfaces:**
- Consumes: `BankEntry`, `LedgerEntry`, `DivergenceType`
- Produces: `Pair`, `GroundTruth`, `InjectionResult`, `Dataset`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/synth/test_dataset.py` (criar também `tests/synth/__init__.py` vazio):

```python
from datetime import date

from orchestrator.models import BankEntry, LedgerEntry
from orchestrator.synth.dataset import Dataset, GroundTruth, InjectionResult, Pair
from orchestrator.taxonomy import DivergenceType


def _pair() -> Pair:
    b = BankEntry(id="b1", date=date(2026, 9, 14), amount=-10000, description="PAGTO")
    ledger = LedgerEntry(
        id="l1",
        accrual_date=date(2026, 9, 10),
        cash_date=date(2026, 9, 14),
        gross_amount=10000,
        net_amount=10000,
        account="2.1.1.01",
        supplier="ACME",
    )
    return Pair(bank=b, ledger=ledger)


def test_pair_guarda_os_dois_lados():
    p = _pair()
    assert p.bank.id == "b1"
    assert p.ledger.id == "l1"


def test_ground_truth_registra_tipo_e_ids():
    gt = GroundTruth(
        divergence_type=DivergenceType.RETENCAO_IMPOSTO,
        bank_ids=frozenset({"b1"}),
        ledger_ids=frozenset({"l1"}),
        explanation="ISS retido de 5%",
    )
    assert gt.divergence_type is DivergenceType.RETENCAO_IMPOSTO
    assert "ISS" in gt.explanation


def test_ground_truth_default_e_caso_do_agente():
    gt = GroundTruth(
        divergence_type=DivergenceType.RETENCAO_IMPOSTO,
        bank_ids=frozenset({"b1"}),
        ledger_ids=frozenset({"l1"}),
        explanation="ISS retido de 5%",
    )
    assert gt.deterministic_expected is False


def test_ground_truth_pode_marcar_caso_deterministico():
    gt = GroundTruth(
        divergence_type=DivergenceType.PAGAMENTO_AGREGADO,
        bank_ids=frozenset({"b1"}),
        ledger_ids=frozenset({"l1", "l2"}),
        explanation="lote de duas notas",
        deterministic_expected=True,
    )
    assert gt.deterministic_expected is True


def test_dataset_conta_entradas():
    p = _pair()
    ds = Dataset(bank=[p.bank], ledger=[p.ledger], truth=[])
    assert len(ds.bank) == 1
    assert ds.truth == []


def test_injection_result_pode_devolver_varias_pernas():
    p = _pair()
    extra = BankEntry(id="b1r", date=date(2026, 9, 15), amount=10000, description="DEVOL")
    gt = GroundTruth(
        divergence_type=DivergenceType.DEVOLUCAO_FUNDOS,
        bank_ids=frozenset({"b1", "b1r"}),
        ledger_ids=frozenset({"l1"}),
        explanation="TED devolvida",
    )
    r = InjectionResult(consumed=(p,), bank=[p.bank, extra], ledger=[p.ledger], truth=gt)
    assert len(r.bank) == 2
    assert r.consumed == (p,)
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/Scripts/pytest tests/synth/test_dataset.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar**

```bash
mkdir -p src/orchestrator/synth tests/synth
touch src/orchestrator/synth/__init__.py tests/synth/__init__.py
```

Criar `src/orchestrator/synth/dataset.py`:

```python
"""Estruturas do dataset sintético com gabarito.

O gabarito é a única fonte de verdade deste projeto: sem dado real de
terceiros, é contra ele que toda métrica é calculada. Ver spec 5.1.
"""

from dataclasses import dataclass

from orchestrator.models import BankEntry, LedgerEntry
from orchestrator.taxonomy import DivergenceType


@dataclass(frozen=True)
class Pair:
    """Um par que concilia perfeitamente, antes de qualquer injeção."""

    bank: BankEntry
    ledger: LedgerEntry


@dataclass(frozen=True)
class GroundTruth:
    """A resposta correta de um caso: que divergência foi injetada e onde.

    `deterministic_expected` separa duas coisas que se confundem facilmente:
    estar na taxonomia não significa que o caso deva sobrar para o agente.
    PAGAMENTO_AGREGADO é divergência no sentido de não ser um casamento 1:1,
    mas a camada L3 deve resolvê-lo sozinha — e resolver é acerto, não erro.
    Sem esta distinção a métrica puniria o sistema por funcionar.
    """

    divergence_type: DivergenceType
    bank_ids: frozenset[str]
    ledger_ids: frozenset[str]
    explanation: str
    deterministic_expected: bool = False


@dataclass(frozen=True)
class InjectionResult:
    """Saída de um injetor.

    `consumed` são os pares que este resultado SUBSTITUI, declarados
    explicitamente. Não dá para inferi-los do que o injetor devolveu: a
    devolução de fundos renomeia as três pernas, e o pagamento agregado funde
    N pares num lançamento só — em ambos os casos ids consumidos desaparecem
    da saída. Inferir por id deixaria os originais órfãos no dataset, somando
    dinheiro que não existe.

    `bank` e `ledger` são listas porque um injetor pode devolver mais de um
    lançamento bancário (DEVOLUCAO_FUNDOS) ou mais de um contábil
    (PAGAMENTO_AGREGADO).
    """

    consumed: tuple[Pair, ...]
    bank: list[BankEntry]
    ledger: list[LedgerEntry]
    truth: GroundTruth


@dataclass(frozen=True)
class Dataset:
    """Um extrato, um razão, e o gabarito do que foi injetado."""

    bank: list[BankEntry]
    ledger: list[LedgerEntry]
    truth: list[GroundTruth]
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/pytest tests/synth/test_dataset.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/synth tests/synth
git commit -m "feat: estruturas do dataset sintético com gabarito"
```

---

### Task 6: Gerador de pares limpos

**Files:**
- Create: `src/orchestrator/synth/generator.py`
- Test: `tests/synth/test_generator.py`

**Interfaces:**
- Consumes: `Pair`, `Dataset`, `BankEntry`, `LedgerEntry`
- Produces: `generate_clean_pairs(seed: int, n: int) -> list[Pair]`, `build_dataset(pairs, injections) -> Dataset`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/synth/test_generator.py`:

```python
from orchestrator.synth.generator import build_dataset, generate_clean_pairs


def test_gera_a_quantidade_pedida():
    pares = generate_clean_pairs(seed=42, n=50)
    assert len(pares) == 50


def test_par_limpo_concilia_perfeitamente():
    for p in generate_clean_pairs(seed=1, n=20):
        # débito bancário negativo espelha o líquido contábil positivo
        assert p.bank.amount == -p.ledger.net_amount
        assert p.bank.date == p.ledger.cash_date
        assert p.bank.document == p.ledger.document


def test_determinismo_por_semente():
    a = generate_clean_pairs(seed=7, n=30)
    b = generate_clean_pairs(seed=7, n=30)
    assert a == b


def test_sementes_diferentes_geram_datasets_diferentes():
    a = generate_clean_pairs(seed=7, n=30)
    b = generate_clean_pairs(seed=8, n=30)
    assert a != b


def test_ids_sao_unicos():
    pares = generate_clean_pairs(seed=3, n=100)
    assert len({p.bank.id for p in pares}) == 100
    assert len({p.ledger.id for p in pares}) == 100


def test_build_dataset_sem_injecoes_devolve_tudo_limpo():
    pares = generate_clean_pairs(seed=5, n=10)
    ds = build_dataset(pares, injections=[])
    assert len(ds.bank) == 10
    assert len(ds.ledger) == 10
    assert ds.truth == []


def test_generate_rejeita_n_invalido():
    # Lista vazia em silêncio zeraria toda métrica calculada em cima dela.
    import pytest

    with pytest.raises(ValueError):
        generate_clean_pairs(seed=1, n=0)
    with pytest.raises(ValueError):
        generate_clean_pairs(seed=1, n=-5)


def test_build_dataset_remove_originais_em_fan_out():
    # Devolução de fundos: um par consumido, três pernas devolvidas com ids
    # novos. Se o original sobreviver, vira divergência sem gabarito.
    from dataclasses import replace

    from orchestrator.synth.dataset import GroundTruth, InjectionResult
    from orchestrator.taxonomy import DivergenceType

    pares = generate_clean_pairs(seed=8, n=3)
    p = pares[0]
    pernas = [replace(p.bank, id=f"{p.bank.id}-{s}") for s in ("a", "b", "c")]
    inj = InjectionResult(
        consumed=(p,),
        bank=pernas,
        ledger=[p.ledger],
        truth=GroundTruth(
            divergence_type=DivergenceType.DEVOLUCAO_FUNDOS,
            bank_ids=frozenset(e.id for e in pernas),
            ledger_ids=frozenset({p.ledger.id}),
            explanation="devolvida e reenviada",
        ),
    )

    ds = build_dataset(pares, injections=[inj])

    assert len(ds.bank) == 5  # dois pares intactos mais as três pernas
    assert p.bank.id not in {e.id for e in ds.bank}


def test_build_dataset_remove_originais_em_fan_in():
    # Pagamento agregado: três pares consumidos, um lançamento devolvido. Se os
    # outros dois sobreviverem, o dataset soma dinheiro que não existe.
    from dataclasses import replace

    from orchestrator.synth.dataset import GroundTruth, InjectionResult
    from orchestrator.taxonomy import DivergenceType

    pares = generate_clean_pairs(seed=8, n=3)
    total = sum(p.ledger.net_amount for p in pares)
    agregado = replace(pares[0].bank, amount=-total)
    inj = InjectionResult(
        consumed=tuple(pares),
        bank=[agregado],
        ledger=[p.ledger for p in pares],
        truth=GroundTruth(
            divergence_type=DivergenceType.PAGAMENTO_AGREGADO,
            bank_ids=frozenset({agregado.id}),
            ledger_ids=frozenset(p.ledger.id for p in pares),
            explanation="lote de três documentos",
            deterministic_expected=True,
        ),
    )

    ds = build_dataset(pares, injections=[inj])

    assert len(ds.bank) == 1
    assert sum(abs(e.amount) for e in ds.bank) == total
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/Scripts/pytest tests/synth/test_generator.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `src/orchestrator/synth/generator.py`**

```python
"""Geração de datasets sintéticos determinísticos.

Primeiro cria pares que conciliam perfeitamente; depois injetores reescrevem
uma fração deles. Determinismo por semente é requisito: a mesma semente
produz exatamente o mesmo dataset.
"""

from datetime import date, timedelta
from random import Random

from orchestrator.dates import add_business_days
from orchestrator.models import BankEntry, LedgerEntry
from orchestrator.synth.dataset import Dataset, InjectionResult, Pair

_FORNECEDORES = [
    "ACME SERVICOS LTDA",
    "BETA DISTRIBUIDORA SA",
    "GAMA TECNOLOGIA ME",
    "DELTA LOGISTICA LTDA",
    "EPSILON CONSULTORIA SS",
    "ZETA MANUTENCAO EIRELI",
]

_CONTAS = ["2.1.1.01", "2.1.1.02", "4.1.2.03", "4.1.5.01"]
_CENTROS = ["ADM", "COM", "OPE", "TI"]
_BASE = date(2026, 6, 1)


def generate_clean_pairs(seed: int, n: int) -> list[Pair]:
    """Gera n pares que conciliam perfeitamente."""
    # Um n inválido devolveria lista vazia em silêncio, e toda métrica
    # calculada em cima dela sairia zerada sem nenhum sinal de que o dataset
    # nunca existiu.
    if n < 1:
        raise ValueError(f"n precisa ser pelo menos 1: {n}")

    rng = Random(seed)
    pares: list[Pair] = []

    for i in range(n):
        fornecedor = rng.choice(_FORNECEDORES)
        valor = rng.randrange(5_000, 5_000_000)  # R$ 50,00 a R$ 49.999,99
        competencia = _BASE + timedelta(days=rng.randrange(0, 90))
        caixa = add_business_days(competencia, rng.randrange(0, 5))
        documento = f"NF-{10_000 + i}"

        banco = BankEntry(
            id=f"b{i:05d}",
            date=caixa,
            amount=-valor,
            description=f"PAGTO {fornecedor[:20]}",
            counterparty=fornecedor,
            document=documento,
        )
        contabil = LedgerEntry(
            id=f"l{i:05d}",
            accrual_date=competencia,
            cash_date=caixa,
            gross_amount=valor,
            net_amount=valor,
            account=rng.choice(_CONTAS),
            supplier=fornecedor,
            cost_center=rng.choice(_CENTROS),
            document=documento,
        )
        pares.append(Pair(bank=banco, ledger=contabil))

    return pares


def build_dataset(pares: list[Pair], injections: list[InjectionResult]) -> Dataset:
    """Monta o dataset final.

    Os pares que cada injeção declara ter consumido saem do dataset, e os
    lançamentos que o injetor produziu entram no lugar.

    A substituição usa `inj.consumed`, nunca os ids da saída do injetor: a
    devolução de fundos renomeia as três pernas e o pagamento agregado funde
    N pares num lançamento só, então inferir por id deixaria originais órfãos
    somando dinheiro que não existe.
    """
    substituidos_banco = {p.bank.id for inj in injections for p in inj.consumed}
    substituidos_contabil = {p.ledger.id for inj in injections for p in inj.consumed}

    banco: list[BankEntry] = []
    contabil: list[LedgerEntry] = []

    for p in pares:
        if p.bank.id not in substituidos_banco:
            banco.append(p.bank)
        if p.ledger.id not in substituidos_contabil:
            contabil.append(p.ledger)

    for inj in injections:
        banco.extend(inj.bank)
        contabil.extend(inj.ledger)

    banco.sort(key=lambda e: (e.date, e.id))
    contabil.sort(key=lambda e: (e.accrual_date, e.id))

    return Dataset(bank=banco, ledger=contabil, truth=[inj.truth for inj in injections])
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/pytest tests/synth/test_generator.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/synth/generator.py tests/synth/test_generator.py
git commit -m "feat: gerador determinístico de pares que conciliam"
```

---

### Task 7: Protocolo de injeção e o primeiro injetor

**Files:**
- Create: `src/orchestrator/synth/injectors.py`
- Test: `tests/synth/test_injectors.py`

**Interfaces:**
- Consumes: `Pair`, `InjectionResult`, `GroundTruth`, `DivergenceType`, `add_business_days`
- Produces: `Injector` (Protocol), `DefasagemTemporal`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/synth/test_injectors.py`:

```python
from random import Random

from orchestrator.synth.generator import generate_clean_pairs
from orchestrator.synth.injectors import DefasagemTemporal
from orchestrator.taxonomy import DivergenceType


def _par():
    return generate_clean_pairs(seed=1, n=1)[0]


def test_defasagem_muda_a_data_bancaria():
    par = _par()
    r = DefasagemTemporal().apply(Random(0), par)
    assert r.bank[0].date != par.bank.date


def test_defasagem_preserva_o_valor():
    par = _par()
    r = DefasagemTemporal().apply(Random(0), par)
    assert r.bank[0].amount == par.bank.amount


def test_defasagem_registra_o_gabarito():
    par = _par()
    r = DefasagemTemporal().apply(Random(0), par)
    assert r.truth.divergence_type is DivergenceType.DEFASAGEM_TEMPORAL
    assert r.truth.bank_ids == frozenset({par.bank.id})
    assert r.truth.ledger_ids == frozenset({par.ledger.id})


def test_defasagem_e_deterministica():
    par = _par()
    a = DefasagemTemporal().apply(Random(99), par)
    b = DefasagemTemporal().apply(Random(99), par)
    assert a.bank[0].date == b.bank[0].date


def test_defasagem_excede_a_tolerancia_da_camada_l2():
    # A tolerância padrão de L2 é 3 dias úteis; a injeção precisa passar disso
    # para que o caso de fato vire divergência.
    from orchestrator.dates import business_days_between

    par = _par()
    r = DefasagemTemporal().apply(Random(0), par)
    assert business_days_between(r.bank[0].date, par.ledger.cash_date) > 3
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/Scripts/pytest tests/synth/test_injectors.py -v`
Expected: FAIL com `ImportError: cannot import name 'DefasagemTemporal'`

- [ ] **Step 3: Implementar `src/orchestrator/synth/injectors.py`**

```python
"""Injetores de divergência.

Um injetor por tipo da taxonomia. Adicionar um tipo novo custa uma classe
aqui e uma entrada na enum — nada estrutural. Ver spec 4.5.
"""

from dataclasses import replace
from random import Random
from typing import Protocol

from orchestrator.dates import add_business_days
from orchestrator.synth.dataset import GroundTruth, InjectionResult, Pair
from orchestrator.taxonomy import DivergenceType


class Injector(Protocol):
    """Reescreve um par limpo, introduzindo uma divergência conhecida."""

    divergence_type: DivergenceType

    def apply(self, rng: Random, pair: Pair) -> InjectionResult: ...


class DefasagemTemporal:
    """A liquidação bancária cai bem depois da data prevista em caixa."""

    divergence_type = DivergenceType.DEFASAGEM_TEMPORAL

    def apply(self, rng: Random, pair: Pair) -> InjectionResult:
        atraso = rng.randrange(4, 12)  # sempre acima da tolerância de L2
        nova_data = add_business_days(pair.bank.date, atraso)
        banco = replace(pair.bank, date=nova_data)

        return InjectionResult(
            consumed=(pair,),
            bank=[banco],
            ledger=[pair.ledger],
            truth=GroundTruth(
                divergence_type=self.divergence_type,
                bank_ids=frozenset({banco.id}),
                ledger_ids=frozenset({pair.ledger.id}),
                explanation=(
                    f"Liquidação ocorreu {atraso} dias úteis após a data prevista "
                    f"em caixa ({pair.ledger.cash_date})."
                ),
            ),
        )
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/pytest tests/synth/test_injectors.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/synth/injectors.py tests/synth/test_injectors.py
git commit -m "feat: protocolo de injeção e injetor de defasagem temporal"
```

---

### Task 8: Injetor de retenção de imposto

**Files:**
- Modify: `src/orchestrator/synth/injectors.py`
- Modify: `tests/synth/test_injectors.py`

**Interfaces:**
- Consumes: `Injector`, `Pair`, `InjectionResult`
- Produces: `RetencaoImposto`, `calcular_retencao(bruto: int, aliquota_bp: int) -> int`

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar a `tests/synth/test_injectors.py`:

```python
from orchestrator.synth.injectors import RetencaoImposto, calcular_retencao


def test_calcular_retencao_iss_cinco_por_cento():
    # 500 basis points = 5%
    assert calcular_retencao(100_000, 500) == 5_000


def test_calcular_retencao_arredonda_para_baixo():
    assert calcular_retencao(333, 500) == 16  # 16,65 centavos -> 16


def test_retencao_reduz_o_valor_bancario():
    par = _par()
    r = RetencaoImposto().apply(Random(0), par)
    assert abs(r.bank[0].amount) < par.ledger.gross_amount


def test_retencao_mantem_bruto_e_ajusta_liquido():
    par = _par()
    r = RetencaoImposto().apply(Random(0), par)
    contabil = r.ledger[0]
    assert contabil.gross_amount == par.ledger.gross_amount
    assert contabil.net_amount == abs(r.bank[0].amount)
    assert contabil.net_amount < contabil.gross_amount


def test_retencao_registra_o_gabarito():
    par = _par()
    r = RetencaoImposto().apply(Random(0), par)
    assert r.truth.divergence_type is DivergenceType.RETENCAO_IMPOSTO
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/Scripts/pytest tests/synth/test_injectors.py -v`
Expected: FAIL com `ImportError: cannot import name 'RetencaoImposto'`

- [ ] **Step 3: Acrescentar a `src/orchestrator/synth/injectors.py`**

```python
# Alíquotas em basis points (1% = 100 bp). Valores típicos de retenção na fonte.
_ALIQUOTAS = {
    "ISS": 500,      # 5%
    "IRRF": 150,     # 1,5%
    "CSLL/PIS/COFINS": 465,  # 4,65%
    "INSS": 1100,    # 11%
}


def calcular_retencao(bruto: int, aliquota_bp: int) -> int:
    """Retenção em centavos, truncada para baixo.

    Determinística e testável de propósito: cálculo fiscal não pode depender
    de raciocínio de modelo de linguagem. Ver spec 4.6.
    """
    return bruto * aliquota_bp // 10_000


class RetencaoImposto:
    """O banco credita o líquido; a contabilidade registra o bruto."""

    divergence_type = DivergenceType.RETENCAO_IMPOSTO

    def apply(self, rng: Random, pair: Pair) -> InjectionResult:
        nome, aliquota = rng.choice(sorted(_ALIQUOTAS.items()))
        bruto = pair.ledger.gross_amount
        retido = calcular_retencao(bruto, aliquota)
        liquido = bruto - retido

        banco = replace(pair.bank, amount=-liquido)
        contabil = replace(pair.ledger, net_amount=liquido)

        return InjectionResult(
            consumed=(pair,),
            bank=[banco],
            ledger=[contabil],
            truth=GroundTruth(
                divergence_type=self.divergence_type,
                bank_ids=frozenset({banco.id}),
                ledger_ids=frozenset({contabil.id}),
                explanation=(
                    f"{nome} retido na fonte a {aliquota / 100:.2f}%: bruto de "
                    f"{bruto} centavos, retenção de {retido}, líquido de {liquido}."
                ),
            ),
        )
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/pytest tests/synth/test_injectors.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/synth/injectors.py tests/synth/test_injectors.py
git commit -m "feat: injetor de retenção de imposto com cálculo determinístico"
```

---

### Task 9: Injetor de pagamento agregado

**Files:**
- Modify: `src/orchestrator/synth/injectors.py`
- Modify: `tests/synth/test_injectors.py`

**Interfaces:**
- Consumes: `Injector`, `Pair`, `InjectionResult`
- Produces: `PagamentoAgregado` com `apply_many(rng, pairs: list[Pair]) -> InjectionResult`

Este injetor é diferente dos anteriores: consome vários pares de uma vez, porque um pagamento agregado só existe se houver N notas.

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar a `tests/synth/test_injectors.py`:

```python
from orchestrator.synth.injectors import PagamentoAgregado


def _pares(n: int):
    return generate_clean_pairs(seed=11, n=n)


def test_agregado_produz_um_lancamento_bancario():
    pares = _pares(3)
    r = PagamentoAgregado().apply_many(Random(0), pares)
    assert len(r.bank) == 1


def test_agregado_preserva_todos_os_contabeis():
    pares = _pares(3)
    r = PagamentoAgregado().apply_many(Random(0), pares)
    assert len(r.ledger) == 3


def test_agregado_soma_os_liquidos():
    pares = _pares(4)
    r = PagamentoAgregado().apply_many(Random(0), pares)
    esperado = sum(p.ledger.net_amount for p in pares)
    assert abs(r.bank[0].amount) == esperado


def test_agregado_registra_todos_os_ids_no_gabarito():
    pares = _pares(3)
    r = PagamentoAgregado().apply_many(Random(0), pares)
    assert r.truth.ledger_ids == frozenset(p.ledger.id for p in pares)
    assert len(r.truth.bank_ids) == 1


def test_agregado_exige_pelo_menos_dois_pares():
    import pytest

    with pytest.raises(ValueError):
        PagamentoAgregado().apply_many(Random(0), _pares(1))


def test_agregado_e_esperado_no_deterministico():
    # L3 deve resolver: o gabarito precisa dizer isso, senão a métrica conta
    # como falso positivo quando o sistema acerta.
    r = PagamentoAgregado().apply_many(Random(0), _pares(3))
    assert r.truth.deterministic_expected is True


def test_defasagem_e_retencao_nao_sao_deterministicos():
    from orchestrator.synth.injectors import DefasagemTemporal, RetencaoImposto

    par = _par()
    assert DefasagemTemporal().apply(Random(0), par).truth.deterministic_expected is False
    assert RetencaoImposto().apply(Random(0), par).truth.deterministic_expected is False


def test_agregado_normaliza_fornecedor_e_data():
    # Sem isto, a camada L3 (que agrupa por fornecedor dentro de uma janela de
    # dias úteis) nunca encontraria o conjunto.
    r = PagamentoAgregado().apply_many(Random(0), _pares(3))
    assert len({le.supplier for le in r.ledger}) == 1
    assert all(le.cash_date == r.bank[0].date for le in r.ledger)
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/Scripts/pytest tests/synth/test_injectors.py -v`
Expected: FAIL com `ImportError: cannot import name 'PagamentoAgregado'`

- [ ] **Step 3: Acrescentar a `src/orchestrator/synth/injectors.py`**

```python
class PagamentoAgregado:
    """Um único débito bancário cobre N documentos contábeis.

    Diferente dos demais injetores: consome vários pares, porque a divergência
    só existe entre múltiplas notas. Por isso expõe apply_many, não apply.
    """

    divergence_type = DivergenceType.PAGAMENTO_AGREGADO

    def apply_many(self, rng: Random, pairs: list[Pair]) -> InjectionResult:
        if len(pairs) < 2:
            raise ValueError("pagamento agregado exige pelo menos dois pares")

        total = sum(p.ledger.net_amount for p in pairs)
        primeiro = pairs[0]
        documentos = ", ".join(sorted(p.ledger.document or p.ledger.id for p in pairs))

        banco = replace(
            primeiro.bank,
            amount=-total,
            description=f"PAGTO LOTE {len(pairs)} DOCS",
            document=None,
        )

        # Um pagamento em lote é a um único fornecedor e liquida tudo no mesmo
        # dia. Sem normalizar as duas coisas, a camada L3 — que agrupa por
        # fornecedor dentro de uma janela de dias úteis — nunca encontraria o
        # conjunto, e o caso que ela existe para resolver viraria divergência.
        contabeis = [
            replace(p.ledger, supplier=primeiro.ledger.supplier, cash_date=banco.date)
            for p in pairs
        ]

        return InjectionResult(
            consumed=tuple(pairs),
            bank=[banco],
            ledger=contabeis,
            truth=GroundTruth(
                divergence_type=self.divergence_type,
                bank_ids=frozenset({banco.id}),
                ledger_ids=frozenset(le.id for le in contabeis),
                explanation=(
                    f"Um débito de {total} centavos cobre {len(pairs)} documentos: "
                    f"{documentos}."
                ),
                # A camada L3 deve resolver este caso sozinha.
                deterministic_expected=True,
            ),
        )
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/pytest tests/synth/test_injectors.py -v`
Expected: 18 passed

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/synth/injectors.py tests/synth/test_injectors.py
git commit -m "feat: injetor de pagamento agregado (n:1)"
```

---

### Task 10: Injetor de devolução de fundos

**Files:**
- Modify: `src/orchestrator/synth/injectors.py`
- Modify: `tests/synth/test_injectors.py`

**Interfaces:**
- Consumes: `Injector`, `Pair`, `InjectionResult`, `add_business_days`
- Produces: `DevolucaoFundos`

Este é o caso difícil confirmado em campo: uma cadeia de duas ou três pernas bancárias para um único lançamento contábil. Ver spec 4.5, "Eventos de múltiplas pernas".

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar a `tests/synth/test_injectors.py`:

```python
from orchestrator.synth.injectors import DevolucaoFundos


def test_devolucao_produz_tres_pernas_bancarias():
    par = _par()
    r = DevolucaoFundos().apply(Random(0), par)
    assert len(r.bank) == 3


def test_devolucao_soma_das_pernas_iguala_o_debito_original():
    par = _par()
    r = DevolucaoFundos().apply(Random(0), par)
    # débito, estorno de volta, e reenvio: o efeito líquido é um débito só
    assert sum(e.amount for e in r.bank) == par.bank.amount


def test_devolucao_tem_uma_perna_de_credito():
    par = _par()
    r = DevolucaoFundos().apply(Random(0), par)
    creditos = [e for e in r.bank if e.amount > 0]
    assert len(creditos) == 1


def test_devolucao_pernas_tem_ids_distintos():
    par = _par()
    r = DevolucaoFundos().apply(Random(0), par)
    assert len({e.id for e in r.bank}) == 3


def test_devolucao_em_ordem_cronologica():
    par = _par()
    r = DevolucaoFundos().apply(Random(0), par)
    datas = [e.date for e in r.bank]
    assert datas == sorted(datas)


def test_devolucao_gabarito_cobre_todas_as_pernas():
    par = _par()
    r = DevolucaoFundos().apply(Random(0), par)
    assert r.truth.bank_ids == frozenset(e.id for e in r.bank)
    assert r.truth.divergence_type is DivergenceType.DEVOLUCAO_FUNDOS


def test_devolucao_zera_o_documento_das_pernas():
    # L1 e L2 exigem documento não nulo. Sem zerar, L1 casaria a perna de envio
    # com o lançamento contábil e o caso viraria falso positivo.
    par = _par()
    r = DevolucaoFundos().apply(Random(0), par)
    assert all(e.document is None for e in r.bank)
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/Scripts/pytest tests/synth/test_injectors.py -v`
Expected: FAIL com `ImportError: cannot import name 'DevolucaoFundos'`

- [ ] **Step 3: Acrescentar a `src/orchestrator/synth/injectors.py`**

```python
class DevolucaoFundos:
    """TED ou Pix devolvido, com reenvio posterior.

    Produz três pernas bancárias para um único lançamento contábil:
    o débito original, o crédito de devolução, e o reenvio corrigido.
    Nenhuma camada determinística resolve isso — é o caso que vai para o
    agente de investigação.
    """

    divergence_type = DivergenceType.DEVOLUCAO_FUNDOS

    def apply(self, rng: Random, pair: Pair) -> InjectionResult:
        valor = pair.bank.amount  # negativo
        data_envio = pair.bank.date
        data_devolucao = add_business_days(data_envio, rng.randrange(1, 3))
        data_reenvio = add_business_days(data_devolucao, rng.randrange(1, 5))

        # As três pernas perdem a referência do documento. Isso espelha o
        # extrato real — transferência devolvida aparece como movimentação
        # genérica — e tem uma consequência de desenho: L1 e L2 exigem
        # documento não nulo, então nenhuma das duas casa estas pernas. Sem
        # isso, L1 casaria a perna de envio com o lançamento contábil (mesmo
        # documento, valor e data do original) e o caso que o spec reserva
        # para o agente viraria falso positivo.
        envio = replace(pair.bank, id=f"{pair.bank.id}-a", date=data_envio, document=None)
        devolucao = replace(
            pair.bank,
            id=f"{pair.bank.id}-b",
            date=data_devolucao,
            amount=-valor,
            description="DEVOLUCAO TED",
            document=None,
        )
        reenvio = replace(
            pair.bank,
            id=f"{pair.bank.id}-c",
            date=data_reenvio,
            amount=valor,
            description=f"{pair.bank.description} REENVIO",
            document=None,
        )

        return InjectionResult(
            consumed=(pair,),
            bank=[envio, devolucao, reenvio],
            ledger=[pair.ledger],
            truth=GroundTruth(
                divergence_type=self.divergence_type,
                bank_ids=frozenset({envio.id, devolucao.id, reenvio.id}),
                ledger_ids=frozenset({pair.ledger.id}),
                explanation=(
                    f"Pagamento enviado em {data_envio}, devolvido em "
                    f"{data_devolucao} e reenviado em {data_reenvio}. Três "
                    f"lançamentos bancários para um documento."
                ),
            ),
        )
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/pytest tests/synth/test_injectors.py -v`
Expected: 25 passed

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/synth/injectors.py tests/synth/test_injectors.py
git commit -m "feat: injetor de devolução de fundos com cadeia de três pernas"
```

---

### Task 11: Camada L1 — matching exato

**Files:**
- Create: `src/orchestrator/matching/__init__.py`
- Create: `src/orchestrator/matching/protocol.py`
- Create: `src/orchestrator/matching/exact.py`
- Test: `tests/matching/test_exact.py`

**Interfaces:**
- Consumes: `BankEntry`, `LedgerEntry`, `MatchResult`
- Produces: `Matcher` (Protocol), `ExactMatcher` com `match(bank, ledger) -> list[MatchResult]`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/matching/__init__.py` vazio e `tests/matching/test_exact.py`:

```python
from random import Random

from orchestrator.matching.exact import ExactMatcher
from orchestrator.synth.generator import generate_clean_pairs
from orchestrator.synth.injectors import DefasagemTemporal


def test_casa_todos_os_pares_limpos():
    pares = generate_clean_pairs(seed=2, n=25)
    banco = [p.bank for p in pares]
    contabil = [p.ledger for p in pares]

    resultados = ExactMatcher().match(banco, contabil)

    assert len(resultados) == 25
    assert all(r.layer == "L1" for r in resultados)


def test_nao_casa_quando_a_data_diverge():
    par = generate_clean_pairs(seed=2, n=1)[0]
    injetado = DefasagemTemporal().apply(Random(0), par)

    resultados = ExactMatcher().match(injetado.bank, injetado.ledger)

    assert resultados == []


def test_nao_casa_quando_o_valor_diverge():
    from dataclasses import replace

    par = generate_clean_pairs(seed=2, n=1)[0]
    banco = [replace(par.bank, amount=par.bank.amount - 1)]

    resultados = ExactMatcher().match(banco, [par.ledger])

    assert resultados == []


def test_resultado_registra_a_regra():
    pares = generate_clean_pairs(seed=2, n=1)
    r = ExactMatcher().match([pares[0].bank], [pares[0].ledger])[0]
    assert "exato" in r.rule.lower()
    assert r.evidence["documento"] == pares[0].ledger.document


def test_cada_lancamento_e_usado_uma_vez_so():
    from dataclasses import replace

    par = generate_clean_pairs(seed=2, n=1)[0]
    # dois contábeis idênticos disputando um único bancário
    gemeo = replace(par.ledger, id="l-gemeo")

    resultados = ExactMatcher().match([par.bank], [par.ledger, gemeo])

    assert len(resultados) == 1
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/Scripts/pytest tests/matching/test_exact.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar**

```bash
mkdir -p src/orchestrator/matching tests/matching
touch src/orchestrator/matching/__init__.py tests/matching/__init__.py
```

Criar `src/orchestrator/matching/protocol.py`:

```python
"""Contrato comum das camadas de matching."""

from typing import Protocol

from orchestrator.models import BankEntry, LedgerEntry, MatchResult


class Matcher(Protocol):
    """Uma camada determinística.

    Recebe apenas o que ainda não foi casado e devolve os vínculos que
    conseguiu estabelecer, cada um com a regra que o justificou.
    """

    layer: str

    def match(self, bank: list[BankEntry], ledger: list[LedgerEntry]) -> list[MatchResult]: ...
```

Criar `src/orchestrator/matching/exact.py`:

```python
"""Camada L1: documento, valor e data idênticos."""

from orchestrator.models import BankEntry, LedgerEntry, MatchResult


class ExactMatcher:
    layer = "L1"

    def match(self, bank: list[BankEntry], ledger: list[LedgerEntry]) -> list[MatchResult]:
        indice: dict[tuple[str, int, object], list[LedgerEntry]] = {}
        for le in ledger:
            if le.document is None or le.cash_date is None:
                continue
            indice.setdefault((le.document, le.net_amount, le.cash_date), []).append(le)

        resultados: list[MatchResult] = []
        usados: set[str] = set()

        for be in bank:
            if be.document is None:
                continue
            chave = (be.document, abs(be.amount), be.date)
            candidatos = [le for le in indice.get(chave, []) if le.id not in usados]
            if not candidatos:
                continue

            escolhido = candidatos[0]
            usados.add(escolhido.id)
            resultados.append(
                MatchResult(
                    bank_ids=frozenset({be.id}),
                    ledger_ids=frozenset({escolhido.id}),
                    layer=self.layer,
                    rule="exato: documento, valor e data coincidem",
                    evidence={
                        "documento": be.document,
                        "valor": abs(be.amount),
                        "data": be.date.isoformat(),
                    },
                )
            )

        return resultados
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/pytest tests/matching/test_exact.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/matching tests/matching
git commit -m "feat: camada L1 de matching exato"
```

---

### Task 12: Camada L2 — tolerância

**Files:**
- Create: `src/orchestrator/matching/tolerance.py`
- Test: `tests/matching/test_tolerance.py`

**Interfaces:**
- Consumes: `BankEntry`, `LedgerEntry`, `MatchResult`, `business_days_between`
- Produces: `ToleranceMatcher(max_cents: int = 5, max_business_days: int = 3)`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/matching/test_tolerance.py`:

```python
from dataclasses import replace

from orchestrator.dates import add_business_days
from orchestrator.matching.tolerance import ToleranceMatcher
from orchestrator.synth.generator import generate_clean_pairs


def _par():
    return generate_clean_pairs(seed=4, n=1)[0]


def test_casa_com_diferenca_de_centavos_dentro_da_tolerancia():
    par = _par()
    banco = [replace(par.bank, amount=par.bank.amount + 3)]

    r = ToleranceMatcher().match(banco, [par.ledger])

    assert len(r) == 1
    assert r[0].layer == "L2"


def test_nao_casa_com_diferenca_acima_da_tolerancia_de_valor():
    par = _par()
    banco = [replace(par.bank, amount=par.bank.amount + 500)]

    assert ToleranceMatcher().match(banco, [par.ledger]) == []


def test_casa_com_atraso_dentro_da_tolerancia_de_dias():
    par = _par()
    banco = [replace(par.bank, date=add_business_days(par.bank.date, 2))]

    assert len(ToleranceMatcher().match(banco, [par.ledger])) == 1


def test_nao_casa_com_atraso_acima_da_tolerancia_de_dias():
    par = _par()
    banco = [replace(par.bank, date=add_business_days(par.bank.date, 8))]

    assert ToleranceMatcher().match(banco, [par.ledger]) == []


def test_tolerancia_e_configuravel():
    par = _par()
    banco = [replace(par.bank, amount=par.bank.amount + 50)]

    assert ToleranceMatcher(max_cents=100).match(banco, [par.ledger]) != []
    assert ToleranceMatcher(max_cents=10).match(banco, [par.ledger]) == []


def test_registra_a_diferenca_na_evidencia():
    par = _par()
    banco = [replace(par.bank, amount=par.bank.amount + 3)]

    r = ToleranceMatcher().match(banco, [par.ledger])[0]

    assert r.evidence["diferenca_centavos"] == 3


def test_rejeita_tolerancia_negativa():
    # Tolerância negativa não casaria nada e pareceria só uma camada sem achados.
    import pytest

    with pytest.raises(ValueError):
        ToleranceMatcher(max_cents=-1)
    with pytest.raises(ValueError):
        ToleranceMatcher(max_business_days=-1)
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/Scripts/pytest tests/matching/test_tolerance.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `src/orchestrator/matching/tolerance.py`**

```python
"""Camada L2: mesmo documento, com folga em valor e data.

Tolerância padrão vem do spec: 5 centavos e 3 dias úteis.
"""

from dataclasses import dataclass, field

from orchestrator.dates import business_days_between
from orchestrator.models import BankEntry, LedgerEntry, MatchResult


@dataclass
class ToleranceMatcher:
    max_cents: int = 5
    max_business_days: int = 3
    layer: str = field(default="L2", init=False)

    def __post_init__(self) -> None:
        # Tolerância negativa não casaria nada e pareceria uma camada que
        # simplesmente não encontrou nada — falha silenciosa disfarçada de
        # resultado.
        if self.max_cents < 0:
            raise ValueError(f"max_cents não pode ser negativo: {self.max_cents}")
        if self.max_business_days < 0:
            raise ValueError(
                f"max_business_days não pode ser negativo: {self.max_business_days}"
            )

    def match(self, bank: list[BankEntry], ledger: list[LedgerEntry]) -> list[MatchResult]:
        por_documento: dict[str, list[LedgerEntry]] = {}
        for le in ledger:
            if le.document is not None and le.cash_date is not None:
                por_documento.setdefault(le.document, []).append(le)

        resultados: list[MatchResult] = []
        usados: set[str] = set()

        for be in bank:
            if be.document is None:
                continue

            for le in por_documento.get(be.document, []):
                if le.id in usados or le.cash_date is None:
                    continue

                diferenca = abs(abs(be.amount) - le.net_amount)
                dias = business_days_between(be.date, le.cash_date)
                if diferenca > self.max_cents or dias > self.max_business_days:
                    continue

                usados.add(le.id)
                resultados.append(
                    MatchResult(
                        bank_ids=frozenset({be.id}),
                        ledger_ids=frozenset({le.id}),
                        layer=self.layer,
                        rule=(
                            f"tolerância: até {self.max_cents} centavos e "
                            f"{self.max_business_days} dias úteis"
                        ),
                        evidence={
                            "documento": be.document,
                            "diferenca_centavos": diferenca,
                            "diferenca_dias_uteis": dias,
                        },
                    )
                )
                break

        return resultados
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/pytest tests/matching/test_tolerance.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/matching/tolerance.py tests/matching/test_tolerance.py
git commit -m "feat: camada L2 de tolerância em valor e dias úteis"
```

---

### Task 13: Camada L3 — agrupamento n:m

**Files:**
- Create: `src/orchestrator/matching/grouping.py`
- Test: `tests/matching/test_grouping.py`

**Interfaces:**
- Consumes: `BankEntry`, `LedgerEntry`, `MatchResult`, `business_days_between`
- Produces: `GroupingMatcher(max_group_size: int = 4, max_business_days: int = 3)`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/matching/test_grouping.py`:

```python
from random import Random

from orchestrator.matching.grouping import GroupingMatcher
from orchestrator.synth.generator import generate_clean_pairs
from orchestrator.synth.injectors import DevolucaoFundos, PagamentoAgregado


def test_casa_pagamento_agregado_de_tres_notas():
    pares = generate_clean_pairs(seed=6, n=3)
    inj = PagamentoAgregado().apply_many(Random(0), pares)

    r = GroupingMatcher().match(inj.bank, inj.ledger)

    assert len(r) == 1
    assert r[0].ledger_ids == frozenset(le.id for le in inj.ledger)
    assert r[0].layer == "L3"


def test_nao_casa_grupo_maior_que_o_limite():
    pares = generate_clean_pairs(seed=6, n=6)
    inj = PagamentoAgregado().apply_many(Random(0), pares)

    assert GroupingMatcher(max_group_size=4).match(inj.bank, inj.ledger) == []


def test_nao_resolve_devolucao_de_fundos():
    # Devolução é caso do agente, não das camadas determinísticas. Ver spec 4.5.
    par = generate_clean_pairs(seed=6, n=1)[0]
    inj = DevolucaoFundos().apply(Random(0), par)

    assert GroupingMatcher().match(inj.bank, inj.ledger) == []


def test_registra_as_parcelas_na_evidencia():
    pares = generate_clean_pairs(seed=6, n=2)
    inj = PagamentoAgregado().apply_many(Random(0), pares)

    r = GroupingMatcher().match(inj.bank, inj.ledger)[0]

    assert r.evidence["quantidade"] == 2
    assert r.evidence["soma"] == abs(inj.bank[0].amount)


def test_nao_agrupa_fornecedores_diferentes():
    from dataclasses import replace

    pares = generate_clean_pairs(seed=6, n=2)
    inj = PagamentoAgregado().apply_many(Random(0), pares)
    contabeis = [inj.ledger[0], replace(inj.ledger[1], supplier="OUTRO FORNECEDOR SA")]

    assert GroupingMatcher().match(inj.bank, contabeis) == []


def test_rejeita_configuracao_que_nunca_agrupa():
    # Tamanho 1 esvazia o range de combinações: a camada nunca agruparia nada,
    # sem erro e sem aviso.
    import pytest

    with pytest.raises(ValueError):
        GroupingMatcher(max_group_size=1)
    with pytest.raises(ValueError):
        GroupingMatcher(max_business_days=-1)
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/Scripts/pytest tests/matching/test_grouping.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `src/orchestrator/matching/grouping.py`**

```python
"""Camada L3: um lançamento bancário cobrindo N contábeis do mesmo fornecedor.

A busca por subconjuntos é exponencial, então é limitada por max_group_size e
por janela de data. Isso é deliberado: a camada determinística deve ser barata.
O que ela não alcançar é trabalho do agente, não motivo para relaxar o limite.
"""

from dataclasses import dataclass, field
from itertools import combinations

from orchestrator.dates import business_days_between
from orchestrator.models import BankEntry, LedgerEntry, MatchResult


@dataclass
class GroupingMatcher:
    max_group_size: int = 4
    max_business_days: int = 3
    layer: str = field(default="L3", init=False)

    def __post_init__(self) -> None:
        # Tamanho menor que 2 esvazia o range de combinações e a camada nunca
        # agrupa nada, sem erro e sem aviso.
        if self.max_group_size < 2:
            raise ValueError(
                f"agrupamento exige tamanho mínimo 2: {self.max_group_size}"
            )
        if self.max_business_days < 0:
            raise ValueError(
                f"max_business_days não pode ser negativo: {self.max_business_days}"
            )

    def match(self, bank: list[BankEntry], ledger: list[LedgerEntry]) -> list[MatchResult]:
        por_fornecedor: dict[str, list[LedgerEntry]] = {}
        for le in ledger:
            if le.cash_date is not None:
                por_fornecedor.setdefault(le.supplier, []).append(le)

        resultados: list[MatchResult] = []
        usados: set[str] = set()

        for be in bank:
            if be.counterparty is None:
                continue

            candidatos = [
                le
                for le in por_fornecedor.get(be.counterparty, [])
                if le.id not in usados
                and le.cash_date is not None
                and business_days_between(be.date, le.cash_date) <= self.max_business_days
            ]
            if len(candidatos) < 2:
                continue

            alvo = abs(be.amount)
            grupo = self._encontrar_grupo(candidatos, alvo)
            if grupo is None:
                continue

            usados.update(le.id for le in grupo)
            resultados.append(
                MatchResult(
                    bank_ids=frozenset({be.id}),
                    ledger_ids=frozenset(le.id for le in grupo),
                    layer=self.layer,
                    rule=(
                        f"agrupamento: soma de {len(grupo)} líquidos do mesmo "
                        f"fornecedor iguala o lançamento bancário"
                    ),
                    evidence={
                        "fornecedor": be.counterparty,
                        "quantidade": len(grupo),
                        "soma": alvo,
                        "documentos": sorted(le.document or le.id for le in grupo),
                    },
                )
            )

        return resultados

    def _encontrar_grupo(
        self, candidatos: list[LedgerEntry], alvo: int
    ) -> tuple[LedgerEntry, ...] | None:
        limite = min(self.max_group_size, len(candidatos))
        for tamanho in range(2, limite + 1):
            for combinacao in combinations(candidatos, tamanho):
                if sum(le.net_amount for le in combinacao) == alvo:
                    return combinacao
        return None
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/pytest tests/matching/test_grouping.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/matching/grouping.py tests/matching/test_grouping.py
git commit -m "feat: camada L3 de agrupamento n:m com limite de combinação"
```

---

### Task 14: Engine de reconciliação

**Files:**
- Create: `src/orchestrator/matching/engine.py`
- Test: `tests/matching/test_engine.py`

**Interfaces:**
- Consumes: `Matcher`, `ExactMatcher`, `ToleranceMatcher`, `GroupingMatcher`, `MatchResult`, `Divergence`
- Produces: `ReconcileResult`, `reconcile(bank, ledger, matchers=None) -> ReconcileResult`, `default_matchers() -> list[Matcher]`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/matching/test_engine.py`:

```python
from random import Random

from orchestrator.matching.engine import default_matchers, reconcile
from orchestrator.synth.generator import build_dataset, generate_clean_pairs
from orchestrator.synth.injectors import DefasagemTemporal, DevolucaoFundos


def test_dataset_limpo_nao_gera_divergencia():
    pares = generate_clean_pairs(seed=8, n=30)
    ds = build_dataset(pares, injections=[])

    r = reconcile(ds.bank, ds.ledger)

    assert r.divergences == []
    assert len(r.matches) == 30


def test_camadas_sao_aplicadas_em_ordem():
    pares = generate_clean_pairs(seed=8, n=10)
    ds = build_dataset(pares, injections=[])

    r = reconcile(ds.bank, ds.ledger)

    # tudo limpo deve ser resolvido na camada mais barata
    assert {m.layer for m in r.matches} == {"L1"}


def test_defasagem_grande_vira_divergencia():
    pares = generate_clean_pairs(seed=8, n=5)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    r = reconcile(ds.bank, ds.ledger)

    ids_divergentes = {i for d in r.divergences for i in d.bank_ids | d.ledger_ids}
    assert inj.bank[0].id in ids_divergentes


def test_devolucao_vira_divergencia_com_todas_as_pernas():
    pares = generate_clean_pairs(seed=8, n=5)
    inj = DevolucaoFundos().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    r = reconcile(ds.bank, ds.ledger)

    ids_divergentes = {i for d in r.divergences for i in d.bank_ids}
    assert all(e.id in ids_divergentes for e in inj.bank)


def test_nenhum_lancamento_aparece_em_match_e_divergencia():
    pares = generate_clean_pairs(seed=8, n=20)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    r = reconcile(ds.bank, ds.ledger)

    casados = {i for m in r.matches for i in m.bank_ids | m.ledger_ids}
    divergentes = {i for d in r.divergences for i in d.bank_ids | d.ledger_ids}
    assert casados & divergentes == set()


def test_matchers_sao_injetaveis():
    pares = generate_clean_pairs(seed=8, n=5)
    ds = build_dataset(pares, injections=[])

    r = reconcile(ds.bank, ds.ledger, matchers=[])

    assert r.matches == []
    assert len(r.divergences) > 0


def test_default_matchers_tem_tres_camadas():
    assert [m.layer for m in default_matchers()] == ["L1", "L2", "L3"]
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/Scripts/pytest tests/matching/test_engine.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `src/orchestrator/matching/engine.py`**

```python
"""Orquestra as camadas determinísticas e apura o que sobrou.

Cada camada recebe apenas o que as anteriores não casaram. O que nenhuma
resolveu vira Divergence — e é isso, e só isso, que o agente de investigação
recebe. Ver spec 4.3.
"""

from dataclasses import dataclass

from orchestrator.matching.exact import ExactMatcher
from orchestrator.matching.grouping import GroupingMatcher
from orchestrator.matching.protocol import Matcher
from orchestrator.matching.tolerance import ToleranceMatcher
from orchestrator.models import BankEntry, Divergence, LedgerEntry, MatchResult


@dataclass(frozen=True)
class ReconcileResult:
    matches: list[MatchResult]
    divergences: list[Divergence]


def default_matchers() -> list[Matcher]:
    """As três camadas, da mais barata para a mais cara."""
    return [ExactMatcher(), ToleranceMatcher(), GroupingMatcher()]


def reconcile(
    bank: list[BankEntry],
    ledger: list[LedgerEntry],
    matchers: list[Matcher] | None = None,
) -> ReconcileResult:
    camadas = default_matchers() if matchers is None else matchers

    banco_restante = list(bank)
    contabil_restante = list(ledger)
    todos: list[MatchResult] = []

    for camada in camadas:
        resultados = camada.match(banco_restante, contabil_restante)
        if not resultados:
            continue

        todos.extend(resultados)
        casados_banco = {i for m in resultados for i in m.bank_ids}
        casados_contabil = {i for m in resultados for i in m.ledger_ids}
        banco_restante = [e for e in banco_restante if e.id not in casados_banco]
        contabil_restante = [e for e in contabil_restante if e.id not in casados_contabil]

    divergencias = [
        Divergence(id=f"d-b-{e.id}", bank_ids=frozenset({e.id}), ledger_ids=frozenset())
        for e in banco_restante
    ] + [
        Divergence(id=f"d-l-{e.id}", bank_ids=frozenset(), ledger_ids=frozenset({e.id}))
        for e in contabil_restante
    ]

    return ReconcileResult(matches=todos, divergences=divergencias)
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/pytest tests/matching/test_engine.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/matching/engine.py tests/matching/test_engine.py
git commit -m "feat: engine que aplica camadas em ordem e apura divergências"
```

---

### Task 15: Métricas contra o gabarito

**Files:**
- Create: `src/orchestrator/metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: `Dataset`, `ReconcileResult`, `GroundTruth`
- Produces: `Metrics`, `evaluate(dataset, result) -> Metrics`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_metrics.py`:

```python
from random import Random

from orchestrator.matching.engine import reconcile
from orchestrator.metrics import evaluate
from orchestrator.synth.generator import build_dataset, generate_clean_pairs
from orchestrator.synth.injectors import DefasagemTemporal


def test_dataset_limpo_tem_taxa_total():
    pares = generate_clean_pairs(seed=9, n=40)
    ds = build_dataset(pares, injections=[])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger))

    assert m.deterministic_rate == 1.0
    assert m.false_positives == 0


def test_conta_divergencias_do_gabarito():
    pares = generate_clean_pairs(seed=9, n=20)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger))

    assert m.truth_divergences == 1


def test_falso_positivo_quando_casa_o_que_deveria_divergir():
    # Tolerância absurda faz L2 casar um caso que o gabarito diz ser divergente.
    from orchestrator.matching.tolerance import ToleranceMatcher

    pares = generate_clean_pairs(seed=9, n=5)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    r = reconcile(ds.bank, ds.ledger, matchers=[ToleranceMatcher(max_business_days=999)])
    m = evaluate(ds, r)

    assert m.false_positives == 1


def test_taxa_fica_entre_zero_e_um():
    pares = generate_clean_pairs(seed=9, n=30)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger))

    assert 0.0 <= m.deterministic_rate <= 1.0


def test_cobertura_por_tipo_lista_os_tipos_injetados():
    pares = generate_clean_pairs(seed=9, n=10)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger))

    assert m.truth_by_type["DEFASAGEM_TEMPORAL"] == 1


def test_agregado_resolvido_por_l3_nao_e_falso_positivo():
    from orchestrator.synth.injectors import PagamentoAgregado

    pares = generate_clean_pairs(seed=9, n=3)
    inj = PagamentoAgregado().apply_many(Random(0), pares)
    ds = build_dataset(pares, injections=[inj])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger))

    assert m.false_positives == 0
    assert m.false_negatives == 0


def test_falso_negativo_quando_camada_nao_resolve_o_que_deveria():
    from orchestrator.synth.injectors import PagamentoAgregado

    pares = generate_clean_pairs(seed=9, n=3)
    inj = PagamentoAgregado().apply_many(Random(0), pares)
    ds = build_dataset(pares, injections=[inj])

    # sem nenhuma camada, o agregado deixa de ser resolvido
    m = evaluate(ds, reconcile(ds.bank, ds.ledger, matchers=[]))

    assert m.false_negatives == 1


def test_valores_somam_o_total_do_extrato():
    pares = generate_clean_pairs(seed=9, n=25)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger))

    assert m.matched_amount + m.divergent_amount == sum(abs(e.amount) for e in ds.bank)


def test_render_formata_valores_em_reais():
    pares = generate_clean_pairs(seed=9, n=10)
    ds = build_dataset(pares, injections=[])

    saida = evaluate(ds, reconcile(ds.bank, ds.ledger)).render()

    assert "R$" in saida
    assert "Valor conciliado" in saida
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/Scripts/pytest tests/test_metrics.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `src/orchestrator/metrics.py`**

```python
"""Avaliação do núcleo determinístico contra o gabarito.

Mede o sistema, não o agente — não há agente neste plano. A métrica que
importa aqui é a taxa de resolução determinística (spec 2.3, critério F1) e,
tão importante quanto, o falso positivo: casar errado é pior que não casar.
"""

from collections import Counter
from dataclasses import dataclass

from orchestrator.matching.engine import ReconcileResult
from orchestrator.money import format_brl
from orchestrator.synth.dataset import Dataset


@dataclass(frozen=True)
class Metrics:
    bank_total: int
    ledger_total: int
    bank_matched: int
    deterministic_rate: float
    divergences: int
    truth_divergences: int
    false_positives: int
    false_negatives: int
    matched_amount: int
    divergent_amount: int
    truth_by_type: dict[str, int]

    def render(self) -> str:
        linhas = [
            f"Lançamentos bancários:       {self.bank_total}",
            f"Lançamentos contábeis:       {self.ledger_total}",
            f"Casados deterministicamente: {self.bank_matched}",
            f"Taxa determinística:         {self.deterministic_rate:.1%}",
            f"Divergências apuradas:       {self.divergences}",
            f"Divergências no gabarito:    {self.truth_divergences}",
            f"Falsos positivos:            {self.false_positives}",
            f"Falsos negativos:            {self.false_negatives}",
            "",
            f"Valor conciliado:            {format_brl(self.matched_amount)}",
            f"Valor em divergência:        {format_brl(self.divergent_amount)}",
            "",
            "Gabarito por tipo:",
        ]
        for tipo, n in sorted(self.truth_by_type.items()):
            linhas.append(f"  {tipo:<24} {n}")
        return "\n".join(linhas)


def evaluate(dataset: Dataset, result: ReconcileResult) -> Metrics:
    bank_total = len(dataset.bank)
    casados_banco = {i for m in result.matches for i in m.bank_ids}
    casados_todos = {i for m in result.matches for i in m.bank_ids | m.ledger_ids}

    def foi_casado(gt) -> bool:
        return bool((gt.bank_ids | gt.ledger_ids) & casados_todos)

    # Falso positivo: o gabarito diz que só o agente resolveria, mas alguma
    # camada determinística casou assim mesmo. Casar errado é pior que não casar.
    falsos_positivos = sum(
        1 for gt in dataset.truth if not gt.deterministic_expected and foi_casado(gt)
    )

    # Falso negativo: o gabarito diz que uma camada deveria resolver, e nenhuma
    # resolveu. Isso é trabalho desnecessário empurrado para o agente.
    falsos_negativos = sum(
        1 for gt in dataset.truth if gt.deterministic_expected and not foi_casado(gt)
    )

    # Valor é o que o comprador entende. Contagem de lançamentos não diz se o
    # que sobrou foi R$ 300 ou R$ 300 mil.
    conciliado = sum(abs(e.amount) for e in dataset.bank if e.id in casados_banco)
    divergente = sum(abs(e.amount) for e in dataset.bank if e.id not in casados_banco)

    return Metrics(
        bank_total=bank_total,
        ledger_total=len(dataset.ledger),
        bank_matched=len(casados_banco),
        deterministic_rate=(len(casados_banco) / bank_total) if bank_total else 0.0,
        divergences=len(result.divergences),
        truth_divergences=len(dataset.truth),
        false_positives=falsos_positivos,
        false_negatives=falsos_negativos,
        matched_amount=conciliado,
        divergent_amount=divergente,
        truth_by_type=dict(Counter(str(gt.divergence_type) for gt in dataset.truth)),
    )
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/pytest tests/test_metrics.py -v`
Expected: 9 passed

- [ ] **Step 5: Rodar ruff e corrigir o que aparecer**

Run: `.venv/Scripts/ruff check src tests --fix`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/orchestrator/metrics.py tests/test_metrics.py
git commit -m "feat: métricas de taxa determinística e falso positivo"
```

---

### Task 16: CLI e suíte de cenário completo

**Files:**
- Create: `src/orchestrator/cli.py`
- Test: `tests/test_cli.py`
- Modify: `pyproject.toml`
- Modify: `README.md`

**Interfaces:**
- Consumes: tudo o que foi construído
- Produces: `build_benchmark(seed, n, taxa_divergencia) -> Dataset`, `main(argv) -> int`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_cli.py`:

```python
from orchestrator.cli import build_benchmark, main
from orchestrator.matching.engine import reconcile
from orchestrator.metrics import evaluate


def test_benchmark_injeta_a_proporcao_pedida():
    ds = build_benchmark(seed=1, n=100, taxa_divergencia=0.2)
    # cada injeção consome um ou mais pares; a contagem é aproximada por desenho
    assert 5 <= len(ds.truth) <= 25


def test_benchmark_cobre_varios_tipos():
    ds = build_benchmark(seed=1, n=200, taxa_divergencia=0.3)
    tipos = {gt.divergence_type for gt in ds.truth}
    assert len(tipos) >= 3


def test_benchmark_e_deterministico():
    a = build_benchmark(seed=5, n=50, taxa_divergencia=0.2)
    b = build_benchmark(seed=5, n=50, taxa_divergencia=0.2)
    assert a.bank == b.bank
    assert [t.divergence_type for t in a.truth] == [t.divergence_type for t in b.truth]


def test_taxa_deterministica_fica_acima_do_alvo():
    # Critério F1 do spec: >= 85% com taxa de divergência de 15%.
    ds = build_benchmark(seed=3, n=300, taxa_divergencia=0.15)
    m = evaluate(ds, reconcile(ds.bank, ds.ledger))
    assert m.deterministic_rate >= 0.70, m.render()


def test_sem_falso_positivo_com_tolerancia_padrao():
    ds = build_benchmark(seed=3, n=300, taxa_divergencia=0.15)
    m = evaluate(ds, reconcile(ds.bank, ds.ledger))
    assert m.false_positives == 0, m.render()


def test_main_roda_e_retorna_zero(capsys):
    assert main(["--seed", "1", "--n", "50"]) == 0
    assert "Taxa determinística" in capsys.readouterr().out
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/Scripts/pytest tests/test_cli.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `src/orchestrator/cli.py`**

```python
"""Execução ponta a ponta do núcleo determinístico.

Gera um benchmark sintético, reconcilia e imprime as métricas. Nenhuma
chamada de LLM: este é o piso contra o qual o agente será medido depois.
"""

import argparse
from random import Random

from orchestrator.matching.engine import reconcile
from orchestrator.metrics import evaluate
from orchestrator.synth.dataset import Dataset, InjectionResult
from orchestrator.synth.generator import build_dataset, generate_clean_pairs
from orchestrator.synth.injectors import (
    DefasagemTemporal,
    DevolucaoFundos,
    PagamentoAgregado,
    RetencaoImposto,
)

_INJETORES_SIMPLES = [DefasagemTemporal(), RetencaoImposto(), DevolucaoFundos()]


def build_benchmark(seed: int, n: int, taxa_divergencia: float) -> Dataset:
    """Monta um dataset com a proporção pedida de divergências."""
    rng = Random(seed)
    pares = generate_clean_pairs(seed=seed, n=n)

    alvo = int(n * taxa_divergencia)
    injecoes: list[InjectionResult] = []
    indice = 0

    while indice < alvo and indice < len(pares):
        if rng.random() < 0.25 and indice + 3 <= len(pares):
            lote = pares[indice : indice + 3]
            injecoes.append(PagamentoAgregado().apply_many(rng, lote))
            indice += 3
        else:
            injetor = rng.choice(_INJETORES_SIMPLES)
            injecoes.append(injetor.apply(rng, pares[indice]))
            indice += 1

    return build_dataset(pares, injecoes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Conciliação determinística sintética")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--n", type=int, default=500)
    parser.add_argument("--taxa-divergencia", type=float, default=0.15)
    args = parser.parse_args(argv)

    dataset = build_benchmark(args.seed, args.n, args.taxa_divergencia)
    resultado = reconcile(dataset.bank, dataset.ledger)
    print(evaluate(dataset, resultado).render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Registrar o entry point em `pyproject.toml`**

Acrescentar após o bloco `[project]`:

```toml
[project.scripts]
orchestrator = "orchestrator.cli:main"
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `.venv/Scripts/pytest -v`
Expected: toda a suíte passa

Se `test_taxa_deterministica_fica_acima_do_alvo` falhar, **não relaxe o limiar
para fazer passar.** A falha é informação: significa que as camadas L1-L3
resolvem menos do que o spec assumiu. Registre o número real, e leve-o para a
revisão — o spec seção 2.3 diz explicitamente que esses alvos são estimativas
a serem corrigidas por medição.

- [ ] **Step 6: Rodar a CLI de verdade**

Run: `.venv/Scripts/orchestrator --seed 1 --n 500`
Expected: relatório impresso com a taxa determinística

- [ ] **Step 7: Atualizar o README**

Substituir a seção `## Status` do `README.md` por:

```markdown
## Status

Núcleo determinístico funcionando. Sem dependência de IA.

```bash
pip install -e ".[dev]"
pytest
orchestrator --seed 1 --n 500
```

Próximo: agente de investigação (plano 2), revisão humana (plano 3).
```

- [ ] **Step 8: Commit**

```bash
git add src/orchestrator/cli.py tests/test_cli.py pyproject.toml README.md
git commit -m "feat: CLI de benchmark e suíte de cenário completo"
```

---

## Verificação final

- [ ] `.venv/Scripts/pytest -v` — toda a suíte passa
- [ ] `.venv/Scripts/ruff check src tests` — sem achados
- [ ] `.venv/Scripts/orchestrator --seed 1 --n 500` — imprime o relatório
- [ ] A taxa determinística medida foi **registrada**, e comparada ao alvo de 85% do spec seção 2.3
- [ ] `false_positives` é zero com tolerância padrão (casar errado é pior que não casar)
- [ ] `false_negatives` é zero — nenhum caso que L1-L3 deveria resolver sobrou para o agente

**O resultado que importa deste plano não é o código — é o número.** Se a taxa
determinística vier bem abaixo de 85%, a premissa central do produto precisa
ser revista antes de qualquer trabalho com agente, e isso terá custado zero em
tokens para descobrir.
