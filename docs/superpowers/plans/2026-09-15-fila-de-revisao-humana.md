# Fila de Revisão Humana — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fechar a terceira classe de custo da cascata — propostas do agente viram fila, um humano aceita/rejeita/corrige, e a `Decision` vira `MatchResult`.

**Architecture:** Um `RevisorHumano` de classe `HUMANO` lê uma fila em JSONL append-only e transforma decisões em matches. `reconcile` continua puro: resolvers só leem a fila; o CLI grava propostas, a API grava decisões. As métricas passam a distinguir match por classe de custo — lendo a classe do resolver que produziu, nunca de `MatchResult.layer` — porque a regra de falso positivo atual registraria uma aprovação humana correta como erro.

**Tech Stack:** Python 3.11+, pytest, ruff (line-length 100), FastAPI no extra `[api]`, front em HTML/CSS/JS sem build step.

**Spec:** [`2026-09-15-fila-de-revisao-humana-design.md`](../specs/2026-09-15-fila-de-revisao-humana-design.md)

## Global Constraints

- **Valores monetários são `int` em centavos.** Ponto flutuante em dinheiro é proibido, inclusive em testes. Custo de API é `int` em **micro-cents de USD**.
- **`tests/golden/cascata_12_sementes.json` fica byte-idêntico.** É a autoridade. Se quebrar, o código é que está errado — nunca regenere para fazer um teste passar.
- **`proposals` nunca remove do pool.** Nenhuma expressão que calcula o pool restante pode mencionar `proposals`. `Decision` é o único caminho humano até um match.
- **`reconcile` não escreve.** Resolvers apenas leem a fila. Quem grava é o CLI (propostas) e a API (decisões).
- **Nenhum endpoint gasta dinheiro.** Nenhuma rota monta cascata com resolver de classe `AGENTE`. Não é flag: é caminho inexistente.
- **Nenhuma chamada de API em teste.** A suíte roda inteira sem rede e sem credencial.
- **Classe de custo nunca sai de `MatchResult.layer`.** `layer` é proveniência, `Resolver.name` é identidade, `CostClass` é classe. Ver P3.2 em `DECISOES.md`.
- **Comentários e docstrings em português**, no tom do que já existe.
- **Ruff limpo em tudo que a tarefa toca** (rules E, F, I, UP, B).
- **Não reformate arquivo que a tarefa não está mudando por outro motivo.**

## Comandos do ambiente

Venv em `.venv`, shell Git Bash no Windows:

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q
./.venv/Scripts/python.exe -m ruff check src/ tests/
```

Há 274 testes passando no início deste plano.

---

## Mapa de arquivos

**Criados:**

| Arquivo | Responsabilidade |
|---|---|
| `src/orchestrator/review/__init__.py` | pacote |
| `src/orchestrator/review/decision.py` | `Veredito`, `Decision`, `ids_de_conciliar_com` |
| `src/orchestrator/review/serial.py` | ida e volta JSON de `Proposal` e `Decision` |
| `src/orchestrator/review/fila.py` | `Fila`, `dataset_id`, caminho do JSONL |
| `src/orchestrator/review/revisor.py` | `RevisorHumano` — o resolver de classe HUMANO |
| `web/fila.html`, `web/fila.css`, `web/fila.js` | a tela da fila |
| `tests/review/test_*.py`, `tests/api/test_fila.py` | testes das peças novas |

**Modificados:**

| Arquivo | O que muda |
|---|---|
| `src/orchestrator/matching/engine.py` | `matches_by_class` no `ReconcileResult` |
| `src/orchestrator/metrics.py` | métricas por classe de custo + dois campos novos |
| `src/orchestrator/agent/investigator.py` | guarda de idempotência pela fila |
| `src/orchestrator/workflow/definition.py` | `default_definition(fila=None)` inclui o revisor |
| `src/orchestrator/api/app.py`, `schemas.py` | rotas da fila, `cache_clear` no POST |
| `src/orchestrator/eval/agent_eval.py` | grava propostas na fila após a passagem |
| `tests/workflow/test_definition.py` | o teste que muda de propósito |
| `.gitignore` | `data/` já coberto — conferir |

---

## Task 1: `Decision` e o parser de `conciliar_com`

**Files:**
- Create: `src/orchestrator/review/__init__.py`, `src/orchestrator/review/decision.py`
- Create: `tests/review/__init__.py`, `tests/review/test_decision.py`

**Interfaces:**
- Consumes: `orchestrator.taxonomy.DivergenceType`
- Produces:
  - `Veredito(StrEnum)` com `ACEITAR = "aceitar"`, `REJEITAR = "rejeitar"`, `CORRIGIR = "corrigir"`
  - `Decision(divergence_id: str, veredito: Veredito, tipo: DivergenceType | None, conciliar_com: frozenset[str], autor: str, quando: datetime, motivo: str = "")`, frozen
  - `ids_de_conciliar_com(acao: str) -> frozenset[str]`

- [ ] **Step 1: Escrever os testes**

`tests/review/__init__.py` vazio. `tests/review/test_decision.py`:

```python
from datetime import UTC, datetime

import pytest

from orchestrator.review.decision import Decision, Veredito, ids_de_conciliar_com
from orchestrator.taxonomy import DivergenceType


def test_parser_extrai_um_id():
    assert ids_de_conciliar_com("conciliar_com(l00003)") == frozenset({"l00003"})


def test_parser_extrai_varios_ids_separados_por_virgula():
    # O agente pode propor conciliar contra mais de uma contraparte — um
    # pagamento agregado é exatamente isso.
    assert ids_de_conciliar_com("conciliar_com(l1, l2 ,l3)") == frozenset(
        {"l1", "l2", "l3"}
    )


def test_parser_devolve_vazio_para_acao_que_nao_concilia():
    # `investigar_manual` e `ajustar` são ações válidas que NÃO conciliam.
    # Vazio aqui não é erro: aceitar uma proposta assim é concordar que ela
    # não casa nada.
    assert ids_de_conciliar_com("investigar_manual") == frozenset()
    assert ids_de_conciliar_com("ajustar(1500)") == frozenset()


def test_parser_devolve_vazio_para_forma_quebrada():
    assert ids_de_conciliar_com("conciliar_com(") == frozenset()
    assert ids_de_conciliar_com("conciliar_com()") == frozenset()
    assert ids_de_conciliar_com("") == frozenset()


def test_rejeitar_nao_carrega_tipo_nem_ids():
    d = Decision(
        divergence_id="d-1",
        veredito=Veredito.REJEITAR,
        tipo=None,
        conciliar_com=frozenset(),
        autor="controller@cliente",
        quando=datetime(2026, 9, 15, 12, 0, tzinfo=UTC),
    )

    assert d.tipo is None
    assert d.conciliar_com == frozenset()


def test_corrigir_exige_tipo():
    # Corrigir é aceitar com edição: sem o tipo que o humano afirma, não há
    # correção nenhuma, e a decisão não teria o que aplicar.
    with pytest.raises(ValueError, match="tipo"):
        Decision(
            divergence_id="d-1",
            veredito=Veredito.CORRIGIR,
            tipo=None,
            conciliar_com=frozenset({"l1"}),
            autor="controller@cliente",
            quando=datetime(2026, 9, 15, 12, 0, tzinfo=UTC),
        )


def test_quando_sem_fuso_e_rejeitado():
    # Um horário sem fuso não é um instante: comparar duas decisões de
    # máquinas diferentes daria ordem errada, e a trilha de auditoria depende
    # de ordem.
    with pytest.raises(ValueError, match="UTC"):
        Decision(
            divergence_id="d-1",
            veredito=Veredito.ACEITAR,
            tipo=DivergenceType.DEFASAGEM_TEMPORAL,
            conciliar_com=frozenset({"l1"}),
            autor="a",
            quando=datetime(2026, 9, 15, 12, 0),
        )
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/review/test_decision.py -q
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'orchestrator.review'`.

- [ ] **Step 3: Implementar**

`src/orchestrator/review/__init__.py` vazio. `src/orchestrator/review/decision.py`:

```python
"""O que um humano afirma sobre uma divergência.

Uma `Proposal` explica e sugere; ela nunca resolve. Uma `Decision` é o único
caminho humano até um `MatchResult` — é ela que tira o item do pool.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from orchestrator.taxonomy import DivergenceType

_PREFIXO = "conciliar_com("


class Veredito(StrEnum):
    ACEITAR = "aceitar"
    REJEITAR = "rejeitar"
    CORRIGIR = "corrigir"


def ids_de_conciliar_com(acao: str) -> frozenset[str]:
    """Extrai os ids de `conciliar_com(a, b)`.

    Até agora `acao_sugerida` só era validada por `startswith`: bastava para
    despachar, não para aplicar. Aceitar uma proposta precisa dos ids de
    verdade.

    Qualquer forma que não seja exatamente essa devolve vazio — inclusive
    `ajustar(...)` e `investigar_manual`, que são ações válidas que não
    conciliam nada. Vazio não é erro aqui; é "esta decisão não casa ninguém".
    """
    texto = acao.strip()
    if not texto.startswith(_PREFIXO) or not texto.endswith(")"):
        return frozenset()
    dentro = texto[len(_PREFIXO) : -1]
    return frozenset(p.strip() for p in dentro.split(",") if p.strip())


@dataclass(frozen=True)
class Decision:
    divergence_id: str
    veredito: Veredito
    tipo: DivergenceType | None
    conciliar_com: frozenset[str]
    autor: str
    quando: datetime
    motivo: str = ""

    def __post_init__(self) -> None:
        if self.veredito is Veredito.CORRIGIR and self.tipo is None:
            raise ValueError(
                "corrigir exige `tipo`: é o que o humano afirma no lugar do "
                "que o agente propôs"
            )
        if self.quando.tzinfo is None:
            raise ValueError(
                "`quando` precisa de fuso (use UTC): horário ingênuo não é um "
                "instante, e a trilha de auditoria depende de ordem"
            )

    @property
    def concilia(self) -> bool:
        """Verdadeiro quando esta decisão deve virar um match."""
        return self.veredito is not Veredito.REJEITAR and bool(self.conciliar_com)
```

- [ ] **Step 4: Rodar e ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/review/ -q
./.venv/Scripts/python.exe -m ruff check src/orchestrator/review/ tests/review/
```

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/review/ tests/review/
git commit -m "feat: Decision e o parser de conciliar_com"
```

---

## Task 2: Serialização de `Proposal` e `Decision`

**Files:**
- Create: `src/orchestrator/review/serial.py`
- Create: `tests/review/test_serial.py`

**Interfaces:**
- Consumes: `Decision`, `Veredito`, `orchestrator.agent.proposal.{Proposal, Cost, TraceEvent, TraceKind, Confidence}`, `DivergenceType`
- Produces:
  - `proposta_para_dict(p: Proposal) -> dict`, `proposta_de_dict(d: dict) -> Proposal`
  - `decisao_para_dict(d: Decision) -> dict`, `decisao_de_dict(d: dict) -> Decision`

- [ ] **Step 1: Escrever os testes**

`tests/review/test_serial.py`:

```python
from datetime import UTC, datetime

from orchestrator.agent.proposal import (
    Confidence,
    Cost,
    Proposal,
    TraceEvent,
    TraceKind,
)
from orchestrator.review.decision import Decision, Veredito
from orchestrator.review.serial import (
    decisao_de_dict,
    decisao_para_dict,
    proposta_de_dict,
    proposta_para_dict,
)
from orchestrator.taxonomy import DivergenceType


def _proposta() -> Proposal:
    return Proposal(
        divergence_id="d-b-b00003",
        tipo=DivergenceType.DEFASAGEM_TEMPORAL,
        explicacao="liquidou 8 dias úteis depois",
        evidencia=["b00003: data 2026-08-26", "l00003: caixa 2026-08-15"],
        confianca=Confidence.ALTA,
        acao_sugerida="conciliar_com(l00003)",
        cost=Cost(input_tokens=11, output_tokens=22, cached_tokens=33,
                  cache_creation_tokens=44, calls=5),
        trace=[TraceEvent(kind=TraceKind.LLM, detail={"turnos": 6})],
    )


def test_proposta_sobrevive_a_ida_e_volta_inteira():
    # Os cinco campos de Cost e o trace precisam voltar. Uma serialização que
    # perde um campo em silêncio faz a fila reportar custo menor que o real e
    # uma auditoria perder o passo que explica a proposta.
    original = _proposta()

    voltou = proposta_de_dict(proposta_para_dict(original))

    assert voltou == original
    assert voltou.cost == original.cost
    assert voltou.trace[0].kind is TraceKind.LLM
    assert voltou.trace[0].detail == {"turnos": 6}


def test_decisao_sobrevive_a_ida_e_volta_inteira():
    original = Decision(
        divergence_id="d-b-b00003",
        veredito=Veredito.CORRIGIR,
        tipo=DivergenceType.RETENCAO_IMPOSTO,
        conciliar_com=frozenset({"l00003", "l00004"}),
        autor="controller@cliente",
        quando=datetime(2026, 9, 15, 12, 30, 45, tzinfo=UTC),
        motivo="é retenção de ISS, não defasagem",
    )

    voltou = decisao_de_dict(decisao_para_dict(original))

    assert voltou == original
    assert voltou.quando == original.quando
    assert voltou.conciliar_com == original.conciliar_com


def test_rejeitar_com_tipo_none_sobrevive():
    original = Decision(
        divergence_id="d-1", veredito=Veredito.REJEITAR, tipo=None,
        conciliar_com=frozenset(), autor="a",
        quando=datetime(2026, 9, 15, tzinfo=UTC),
    )

    assert decisao_de_dict(decisao_para_dict(original)).tipo is None


def test_ids_saem_ordenados_para_o_arquivo_ser_diffavel():
    d = Decision(
        divergence_id="d-1", veredito=Veredito.ACEITAR,
        tipo=DivergenceType.DEFASAGEM_TEMPORAL,
        conciliar_com=frozenset({"z", "a", "m"}), autor="a",
        quando=datetime(2026, 9, 15, tzinfo=UTC),
    )

    assert decisao_para_dict(d)["conciliar_com"] == ["a", "m", "z"]
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/review/test_serial.py -q
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'orchestrator.review.serial'`.

- [ ] **Step 3: Implementar**

`src/orchestrator/review/serial.py`:

```python
"""Ida e volta JSON de `Proposal` e `Decision`.

Mesmo idioma de `eval/replay.py`: campo a campo, explícito, sem mágica de
introspecção. Enum vira `.value`, `datetime` vira ISO-8601, `frozenset` vira
lista ORDENADA — o arquivo é append-only e precisa ser diffável.
"""

from datetime import datetime
from typing import Any

from orchestrator.agent.proposal import (
    Confidence,
    Cost,
    Proposal,
    TraceEvent,
    TraceKind,
)
from orchestrator.review.decision import Decision, Veredito
from orchestrator.taxonomy import DivergenceType


def proposta_para_dict(p: Proposal) -> dict[str, Any]:
    return {
        "divergence_id": p.divergence_id,
        "tipo": p.tipo.value,
        "explicacao": p.explicacao,
        "evidencia": list(p.evidencia),
        "confianca": p.confianca.value,
        "acao_sugerida": p.acao_sugerida,
        "cost": {
            "input_tokens": p.cost.input_tokens,
            "output_tokens": p.cost.output_tokens,
            "cached_tokens": p.cost.cached_tokens,
            # Os cinco campos de Cost, como em replay.py: perder um faz a fila
            # reportar custo menor que o real.
            "cache_creation_tokens": p.cost.cache_creation_tokens,
            "calls": p.cost.calls,
        },
        "trace": [{"kind": e.kind.value, "detail": e.detail} for e in p.trace],
    }


def proposta_de_dict(d: dict[str, Any]) -> Proposal:
    return Proposal(
        divergence_id=d["divergence_id"],
        tipo=DivergenceType(d["tipo"]),
        explicacao=d["explicacao"],
        evidencia=list(d["evidencia"]),
        confianca=Confidence(d["confianca"]),
        acao_sugerida=d["acao_sugerida"],
        cost=Cost(**d["cost"]),
        trace=[
            TraceEvent(kind=TraceKind(e["kind"]), detail=e["detail"])
            for e in d["trace"]
        ],
    )


def decisao_para_dict(d: Decision) -> dict[str, Any]:
    return {
        "divergence_id": d.divergence_id,
        "veredito": d.veredito.value,
        "tipo": d.tipo.value if d.tipo is not None else None,
        # Ordenado: o JSONL é append-only e revisado por humano em diff.
        "conciliar_com": sorted(d.conciliar_com),
        "autor": d.autor,
        "quando": d.quando.isoformat(),
        "motivo": d.motivo,
    }


def decisao_de_dict(d: dict[str, Any]) -> Decision:
    return Decision(
        divergence_id=d["divergence_id"],
        veredito=Veredito(d["veredito"]),
        tipo=DivergenceType(d["tipo"]) if d["tipo"] is not None else None,
        conciliar_com=frozenset(d["conciliar_com"]),
        autor=d["autor"],
        quando=datetime.fromisoformat(d["quando"]),
        motivo=d["motivo"],
    )
```

- [ ] **Step 4: Rodar e ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/review/ -q
./.venv/Scripts/python.exe -m ruff check src/orchestrator/review/ tests/review/
```

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/review/serial.py tests/review/test_serial.py
git commit -m "feat: serialização de Proposal e Decision para a fila"
```

---

## Task 3: `Fila` — o JSONL append-only

**Files:**
- Create: `src/orchestrator/review/fila.py`
- Create: `tests/review/test_fila.py`

**Interfaces:**
- Consumes: `Proposal`, `Decision`, as quatro funções da Task 2
- Produces:
  - `dataset_id(seed: int, n: int, taxa: float) -> str` devolvendo `f"s{seed}-n{n}-t{taxa}"`
  - `caminho_da_fila(workflow_id: str, dataset: str, raiz: Path | None = None) -> Path` → `<raiz ou data>/fila/<workflow_id>/<dataset>.jsonl`
  - `Fila(caminho: Path)` com `proposta(id)`, `decisao(id)`, `pendentes()`, `decididas()`, `gravar_proposta(p)`, `gravar_decisao(d)`
  - `Fila.vazia() -> Fila` — em memória, não escreve em lugar nenhum

- [ ] **Step 1: Escrever os testes**

`tests/review/test_fila.py`:

```python
from datetime import UTC, datetime

from orchestrator.agent.proposal import Confidence, Proposal
from orchestrator.review.decision import Decision, Veredito
from orchestrator.review.fila import Fila, caminho_da_fila, dataset_id
from orchestrator.taxonomy import DivergenceType


def _proposta(divergence_id: str, tipo=DivergenceType.DEFASAGEM_TEMPORAL) -> Proposal:
    return Proposal(
        divergence_id=divergence_id,
        tipo=tipo,
        explicacao="x",
        evidencia=["e"],
        confianca=Confidence.MEDIA,
        acao_sugerida="conciliar_com(l1)",
    )


def _decisao(divergence_id: str, motivo: str = "") -> Decision:
    return Decision(
        divergence_id=divergence_id,
        veredito=Veredito.ACEITAR,
        tipo=DivergenceType.DEFASAGEM_TEMPORAL,
        conciliar_com=frozenset({"l1"}),
        autor="controller@cliente",
        quando=datetime(2026, 9, 15, tzinfo=UTC),
        motivo=motivo,
    )


def test_dataset_id_distingue_sementes():
    # O id `d-b-b00003` existe em TODA semente. Sem este escopo, uma decisão
    # tomada olhando a semente 1 se aplicaria ao b00003 da semente 7, que é
    # outro lançamento.
    assert dataset_id(1, 300, 0.15) != dataset_id(7, 300, 0.15)
    assert dataset_id(1, 300, 0.15) == "s1-n300-t0.15"


def test_caminho_separa_workflows(tmp_path):
    a = caminho_da_fila("conciliacao", "s1-n30-t0.15", raiz=tmp_path)
    b = caminho_da_fila("outro", "s1-n30-t0.15", raiz=tmp_path)

    assert a != b
    assert a.suffix == ".jsonl"


def test_grava_e_le_proposta(tmp_path):
    f = Fila(caminho_da_fila("w", "d", raiz=tmp_path))
    f.gravar_proposta(_proposta("d-1"))

    recarregada = Fila(caminho_da_fila("w", "d", raiz=tmp_path))

    assert recarregada.proposta("d-1") == _proposta("d-1")
    assert [p.divergence_id for p in recarregada.pendentes()] == ["d-1"]


def test_primeira_proposta_vence_e_a_segunda_nem_e_gravada(tmp_path):
    # O agente não se repete. Se uma segunda proposta chegasse, ela apagaria
    # o que o revisor já leu — e o custo de reinvestigar já teria sido pago.
    caminho = caminho_da_fila("w", "d", raiz=tmp_path)
    f = Fila(caminho)
    f.gravar_proposta(_proposta("d-1", DivergenceType.DEFASAGEM_TEMPORAL))
    f.gravar_proposta(_proposta("d-1", DivergenceType.RETENCAO_IMPOSTO))

    assert f.proposta("d-1").tipo is DivergenceType.DEFASAGEM_TEMPORAL
    assert len(caminho.read_text(encoding="utf-8").strip().splitlines()) == 1


def test_ultima_decisao_vence_mas_o_log_guarda_as_duas(tmp_path):
    # Um humano muda de ideia. O estado é a última decisão; a auditoria é
    # todas elas.
    caminho = caminho_da_fila("w", "d", raiz=tmp_path)
    f = Fila(caminho)
    f.gravar_proposta(_proposta("d-1"))
    f.gravar_decisao(_decisao("d-1", motivo="primeira"))
    f.gravar_decisao(_decisao("d-1", motivo="reconsiderei"))

    assert f.decisao("d-1").motivo == "reconsiderei"
    linhas = caminho.read_text(encoding="utf-8").strip().splitlines()
    assert sum(1 for x in linhas if '"decisao"' in x) == 2


def test_pendentes_exclui_o_que_ja_foi_decidido(tmp_path):
    f = Fila(caminho_da_fila("w", "d", raiz=tmp_path))
    f.gravar_proposta(_proposta("d-1"))
    f.gravar_proposta(_proposta("d-2"))
    f.gravar_decisao(_decisao("d-1"))

    assert [p.divergence_id for p in f.pendentes()] == ["d-2"]
    assert [p.divergence_id for p, _ in f.decididas()] == ["d-1"]


def test_fila_vazia_nao_escreve_nada(tmp_path, monkeypatch):
    # A definição padrão usa uma fila vazia. Se ela tocasse o disco, o golden
    # e a CLI passariam a depender de estado fora do processo.
    monkeypatch.chdir(tmp_path)
    f = Fila.vazia()

    assert f.pendentes() == []
    assert f.proposta("qualquer") is None
    assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/review/test_fila.py -q
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'orchestrator.review.fila'`.

- [ ] **Step 3: Implementar**

`src/orchestrator/review/fila.py`:

```python
"""As propostas e decisões de um workflow sobre um dataset.

Um JSONL append-only por `(workflow, dataset)`. Append-only NÃO é economia de
esforço: é a trilha de auditoria que o Tier 1 do spec pai pede, saindo como
subproduto do formato em vez de funcionalidade construída depois.

Escrita concorrente de dois processos não tem lock. Uma máquina, um usuário,
`open("a")` por linha é seguro o bastante; multiusuário é multi-tenant, Tier 4.
"""

import json
from pathlib import Path
from typing import Any

from orchestrator.agent.proposal import Proposal
from orchestrator.review.decision import Decision
from orchestrator.review.serial import (
    decisao_de_dict,
    decisao_para_dict,
    proposta_de_dict,
    proposta_para_dict,
)

_RAIZ_PADRAO = Path("data")


def dataset_id(seed: int, n: int, taxa: float) -> str:
    """A identidade do conjunto sobre o qual uma decisão foi tomada.

    `d-b-b00003` existe em toda semente. Sem este escopo, uma decisão tomada
    olhando a semente 1 se aplicaria a um lançamento diferente na semente 7.
    """
    return f"s{seed}-n{n}-t{taxa}"


def caminho_da_fila(workflow_id: str, dataset: str, raiz: Path | None = None) -> Path:
    return (raiz or _RAIZ_PADRAO) / "fila" / workflow_id / f"{dataset}.jsonl"


class Fila:
    def __init__(self, caminho: Path | None) -> None:
        self._caminho = caminho
        self._propostas: dict[str, Proposal] = {}
        self._decisoes: dict[str, Decision] = {}
        self._ordem: list[str] = []
        if caminho is not None and caminho.exists():
            for linha in caminho.read_text(encoding="utf-8").splitlines():
                if linha.strip():
                    self._aplicar(json.loads(linha))

    @staticmethod
    def vazia() -> "Fila":
        """Uma fila em memória que nunca toca o disco.

        É o que `default_definition()` usa quando ninguém passa fila: o
        revisor existe na cascata, não emite nada, e o golden segue idêntico.
        """
        return Fila(None)

    def _aplicar(self, registro: dict[str, Any]) -> None:
        if registro["kind"] == "proposta":
            p = proposta_de_dict(registro["dados"])
            # PRIMEIRA vence: o agente não se repete, e uma segunda proposta
            # apagaria o que o revisor já leu.
            if p.divergence_id not in self._propostas:
                self._propostas[p.divergence_id] = p
                self._ordem.append(p.divergence_id)
        else:
            # ÚLTIMA vence: um humano muda de ideia, e o estado é a decisão
            # mais recente. O log guarda todas — é ele a auditoria.
            d = decisao_de_dict(registro["dados"])
            self._decisoes[d.divergence_id] = d

    def _acrescentar(self, kind: str, dados: dict[str, Any]) -> None:
        if self._caminho is None:
            return
        self._caminho.parent.mkdir(parents=True, exist_ok=True)
        with self._caminho.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"kind": kind, "dados": dados}, ensure_ascii=False) + "\n")

    def proposta(self, divergence_id: str) -> Proposal | None:
        return self._propostas.get(divergence_id)

    def decisao(self, divergence_id: str) -> Decision | None:
        return self._decisoes.get(divergence_id)

    def pendentes(self) -> list[Proposal]:
        return [
            self._propostas[i] for i in self._ordem if i not in self._decisoes
        ]

    def decididas(self) -> list[tuple[Proposal, Decision]]:
        return [
            (self._propostas[i], self._decisoes[i])
            for i in self._ordem
            if i in self._decisoes
        ]

    def gravar_proposta(self, p: Proposal) -> None:
        """Ignora proposta para id que já tem uma — ver `_aplicar`."""
        if p.divergence_id in self._propostas:
            return
        self._acrescentar("proposta", proposta_para_dict(p))
        self._propostas[p.divergence_id] = p
        self._ordem.append(p.divergence_id)

    def gravar_decisao(self, d: Decision) -> None:
        self._acrescentar("decisao", decisao_para_dict(d))
        self._decisoes[d.divergence_id] = d
```

- [ ] **Step 4: Rodar e ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/review/ -q
./.venv/Scripts/python.exe -m ruff check src/orchestrator/review/ tests/review/
```

- [ ] **Step 5: Conferir que `data/` está ignorado**

```bash
grep -n "^data" .gitignore
```

Se não houver linha cobrindo `data/`, acrescente `data/` ao `.gitignore`. A fila guarda decisões sobre dados que um dia serão reais.

- [ ] **Step 6: Commit**

```bash
git add src/orchestrator/review/fila.py tests/review/test_fila.py .gitignore
git commit -m "feat: fila append-only escopada por workflow e dataset"
```

---

## Task 4: `RevisorHumano` — a terceira classe de custo

**Files:**
- Create: `src/orchestrator/review/revisor.py`
- Create: `tests/review/test_revisor.py`

**Interfaces:**
- Consumes: `Fila`, `Decision`, `Veredito`, `CostClass`, `WorkSet`, `ResolverOutput`, `ResolverDescription`, `MatchResult`
- Produces: `RevisorHumano(fila: Fila)` com `name = "revisor"`, `cost_class = CostClass.HUMANO`, `resolve(work)`, `describe()`

- [ ] **Step 1: Escrever os testes**

`tests/review/test_revisor.py`:

```python
from datetime import UTC, datetime

from orchestrator.review.decision import Decision, Veredito
from orchestrator.review.fila import Fila
from orchestrator.review.revisor import RevisorHumano
from orchestrator.synth.generator import generate_clean_pairs
from orchestrator.taxonomy import DivergenceType
from orchestrator.workflow.cost_class import CostClass
from orchestrator.workflow.workset import WorkSet


def _work() -> tuple[WorkSet, str, str]:
    pares = generate_clean_pairs(seed=2, n=2)
    work = WorkSet(bank=[pares[0].bank], ledger=[pares[1].ledger])
    return work, pares[0].bank.id, pares[1].ledger.id


def _decisao(divergence_id: str, ids: set[str], veredito=Veredito.ACEITAR) -> Decision:
    return Decision(
        divergence_id=divergence_id,
        veredito=veredito,
        tipo=None if veredito is Veredito.REJEITAR else DivergenceType.DEFASAGEM_TEMPORAL,
        conciliar_com=frozenset(ids),
        autor="controller@cliente",
        quando=datetime(2026, 9, 15, tzinfo=UTC),
    )


def test_e_um_resolver_da_classe_humano():
    r = RevisorHumano(fila=Fila.vazia())

    assert r.name == "revisor"
    assert r.cost_class is CostClass.HUMANO
    d = r.describe()
    assert (d.name, d.cost_class) == (r.name, r.cost_class)
    assert d.summary


def test_fila_vazia_nao_emite_nada():
    # É o que mantém o golden intacto: o revisor entra na definição padrão e,
    # sem decisão nenhuma, é como se não estivesse lá.
    work, _, _ = _work()

    saida = RevisorHumano(fila=Fila.vazia()).resolve(work)

    assert saida.matches == []
    assert saida.proposals == []


def test_aceitar_vira_match_com_os_ids_classificados_pelo_pool():
    # O lado de cada id NÃO se infere do prefixo nem do tipo da divergência:
    # sai do pool, que é a única fonte que não mente.
    work, id_banco, id_contabil = _work()
    fila = Fila.vazia()
    fila.gravar_decisao(_decisao(f"d-b-{id_banco}", {id_contabil}))

    saida = RevisorHumano(fila=fila).resolve(work)

    assert len(saida.matches) == 1
    m = saida.matches[0]
    assert m.bank_ids == frozenset({id_banco})
    assert m.ledger_ids == frozenset({id_contabil})
    assert m.layer == "revisor"
    assert m.evidence["autor"] == "controller@cliente"


def test_rejeitar_nao_emite_match():
    work, id_banco, id_contabil = _work()
    fila = Fila.vazia()
    fila.gravar_decisao(
        _decisao(f"d-b-{id_banco}", {id_contabil}, veredito=Veredito.REJEITAR)
    )

    assert RevisorHumano(fila=fila).resolve(work).matches == []


def test_decisao_com_id_fora_do_pool_e_ignorada():
    # Decisão obsoleta: uma regra passou a resolver o caso, ou outra decisão
    # já o tirou do pool. Emitir aqui fabricaria um match com id fantasma.
    work, id_banco, _ = _work()
    fila = Fila.vazia()
    fila.gravar_decisao(_decisao(f"d-b-{id_banco}", {"l-que-nao-existe"}))

    assert RevisorHumano(fila=fila).resolve(work).matches == []


def test_decisao_sobre_divergencia_fora_do_pool_e_ignorada():
    work, _, id_contabil = _work()
    fila = Fila.vazia()
    fila.gravar_decisao(_decisao("d-b-b-inexistente", {id_contabil}))

    assert RevisorHumano(fila=fila).resolve(work).matches == []


def test_decidir_duas_vezes_nao_duplica_o_match():
    # O estado é a última decisão, não a soma delas. Se o revisor iterasse o
    # log em vez do índice, reconsiderar produziria dois matches para o mesmo
    # par — e a taxa de resolução passaria de 100%.
    work, id_banco, id_contabil = _work()
    fila = Fila.vazia()
    fila.gravar_decisao(_decisao(f"d-b-{id_banco}", {id_contabil}))
    fila.gravar_decisao(_decisao(f"d-b-{id_banco}", {id_contabil}))

    assert len(RevisorHumano(fila=fila).resolve(work).matches) == 1


def test_o_resolver_nao_custa_nada():
    # Trabalho humano custa, mas não em tokens. `Cost.zero()` aqui significa
    # "esta cascata não gastou API", que é a única coisa que Cost mede.
    work, id_banco, id_contabil = _work()
    fila = Fila.vazia()
    fila.gravar_decisao(_decisao(f"d-b-{id_banco}", {id_contabil}))

    assert RevisorHumano(fila=fila).resolve(work).cost.calls == 0
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/review/test_revisor.py -q
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'orchestrator.review.revisor'`.

- [ ] **Step 3: Implementar**

`src/orchestrator/review/revisor.py`:

```python
"""O resolver de classe HUMANO: decisão vira vínculo.

O §4.4 do spec de composição: aprovação humana não é feature especial, é o
último resolver de uma cascata. Nenhum mecanismo novo, nenhum modo de execução
separado.

Este módulo só LÊ a fila. Quem grava é o CLI (propostas) e a API (decisões) —
`reconcile` continua puro, e é disso que o golden e o teste do dinheiro
dependem.
"""

from dataclasses import dataclass, field

from orchestrator.agent.proposal import Cost
from orchestrator.models import MatchResult
from orchestrator.review.fila import Fila
from orchestrator.workflow.cost_class import CostClass
from orchestrator.workflow.resolver import ResolverDescription, ResolverOutput
from orchestrator.workflow.workset import WorkSet


@dataclass
class RevisorHumano:
    fila: Fila

    name: str = field(default="revisor", init=False)
    cost_class: CostClass = field(default=CostClass.HUMANO, init=False)

    def describe(self) -> ResolverDescription:
        return ResolverDescription(
            name=self.name,
            cost_class=self.cost_class,
            summary="aplica as decisões aprovadas na fila de revisão",
        )

    def resolve(self, work: WorkSet) -> ResolverOutput:
        no_banco = {e.id for e in work.bank}
        no_contabil = {e.id for e in work.ledger}
        por_divergencia = {d.id: d for d in work.as_divergences()}

        matches: list[MatchResult] = []
        for _proposta, decisao in self.fila.decididas():
            if not decisao.concilia:
                continue
            divergencia = por_divergencia.get(decisao.divergence_id)
            if divergencia is None:
                # Decisão obsoleta: a divergência não está mais no pool,
                # porque uma regra a resolveu ou outra decisão já a fechou.
                continue

            bank = set(divergencia.bank_ids)
            ledger = set(divergencia.ledger_ids)
            # O lado de cada id vem do POOL, nunca do prefixo do id nem do
            # tipo da divergência. Um id que não está em nenhum dos dois lados
            # é obsoleto, e a decisão inteira é descartada — emitir um match
            # parcial seria fabricar vínculo com id fantasma.
            obsoleta = False
            for i in decisao.conciliar_com:
                if i in no_banco:
                    bank.add(i)
                elif i in no_contabil:
                    ledger.add(i)
                else:
                    obsoleta = True
                    break
            if obsoleta or not bank or not ledger:
                continue

            matches.append(
                MatchResult(
                    bank_ids=frozenset(bank),
                    ledger_ids=frozenset(ledger),
                    layer=self.name,
                    rule="decisão humana",
                    evidence={
                        "autor": decisao.autor,
                        "quando": decisao.quando.isoformat(),
                        "veredito": decisao.veredito.value,
                        "motivo": decisao.motivo,
                    },
                )
            )
        # Trabalho humano custa, mas não em tokens — e `Cost` só mede tokens.
        return ResolverOutput(matches=matches, cost=Cost.zero())
```

- [ ] **Step 4: Rodar e ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/review/ tests/test_golden.py -q
./.venv/Scripts/python.exe -m ruff check src/orchestrator/review/ tests/review/
```

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/review/revisor.py tests/review/test_revisor.py
git commit -m "feat: RevisorHumano, a terceira classe de custo da cascata"
```

---

## Task 5: As métricas aprendem classe de custo

**Nota de escopo:** esta tarefa corrige um defeito que a conferência do spec achou, não uma funcionalidade nova. A regra de falso positivo atual registraria uma aprovação humana correta como erro.

**Files:**
- Modify: `src/orchestrator/matching/engine.py`
- Modify: `src/orchestrator/metrics.py`
- Modify: `tests/test_metrics.py`

**Interfaces:**
- Consumes: `CostClass`, `RevisorHumano` (para os testes)
- Produces:
  - `ReconcileResult.matches_by_class: dict[CostClass, list[MatchResult]]`
  - `Metrics.bank_matched_total: int`, `Metrics.resolution_rate: float`

- [ ] **Step 1: Escrever os testes**

Acrescente em `tests/test_metrics.py` (os imports de `CostClass`, `ResolverOutput`, `ResolverDescription`, `MatchResult` já existem ou devem ser adicionados no topo):

```python
class _ResolverHumanoFalso:
    """Casa o primeiro bancário com o primeiro contábil, como um humano faria."""

    name = "revisor"
    cost_class = CostClass.HUMANO

    def resolve(self, work):
        if not work.bank or not work.ledger:
            return ResolverOutput()
        return ResolverOutput(
            matches=[
                MatchResult(
                    bank_ids=frozenset({work.bank[0].id}),
                    ledger_ids=frozenset({work.ledger[0].id}),
                    layer="revisor",
                    rule="decisão humana",
                )
            ]
        )

    def describe(self):
        return ResolverDescription(self.name, self.cost_class, "humano falso")


def _com_humano():
    from orchestrator.matching.engine import default_resolvers
    from orchestrator.workflow.definition import Stage, WorkflowDefinition

    return WorkflowDefinition(
        id="com-humano",
        name="com humano",
        stages=(
            Stage("conciliar", (*default_resolvers(), _ResolverHumanoFalso())),
        ),
    )


def test_match_humano_nao_conta_como_falso_positivo():
    """O defeito que esta tarefa corrige.

    A regra de falso positivo conta QUALQUER toque num caso reservado ao
    agente. Escrita quando todo match era determinístico, ela estava certa.
    Com um humano na cascata ela se volta contra o produto: um controller
    aprovando o que o agente propôs seria registrado como erro.
    """
    dataset = build_benchmark(seed=1, n=300, taxa_divergencia=0.15)
    so_regras = evaluate(dataset, reconcile(dataset.bank, dataset.ledger))
    com_humano = evaluate(
        dataset, reconcile(dataset.bank, dataset.ledger, definition=_com_humano())
    )

    assert com_humano.false_positives == so_regras.false_positives


def test_match_humano_nao_move_a_taxa_deterministica():
    # "Determinística" está no nome. Somar trabalho humano ali faria o número
    # que vende o produto — quanto as REGRAS resolvem — subir sem que nenhuma
    # regra tivesse melhorado.
    dataset = build_benchmark(seed=1, n=300, taxa_divergencia=0.15)
    so_regras = evaluate(dataset, reconcile(dataset.bank, dataset.ledger))
    com_humano = evaluate(
        dataset, reconcile(dataset.bank, dataset.ledger, definition=_com_humano())
    )

    assert com_humano.deterministic_rate == so_regras.deterministic_rate
    assert com_humano.bank_matched == so_regras.bank_matched


def test_match_humano_sobe_a_taxa_de_resolucao_total():
    dataset = build_benchmark(seed=1, n=300, taxa_divergencia=0.15)
    so_regras = evaluate(dataset, reconcile(dataset.bank, dataset.ledger))
    com_humano = evaluate(
        dataset, reconcile(dataset.bank, dataset.ledger, definition=_com_humano())
    )

    assert com_humano.bank_matched_total == so_regras.bank_matched_total + 1
    assert com_humano.resolution_rate > so_regras.resolution_rate


def test_dinheiro_conciliado_conta_o_trabalho_humano():
    # `divergent_amount` responde "quanto ainda está em aberto". Dinheiro que
    # um humano conciliou não está em aberto.
    dataset = build_benchmark(seed=1, n=300, taxa_divergencia=0.15)
    so_regras = evaluate(dataset, reconcile(dataset.bank, dataset.ledger))
    com_humano = evaluate(
        dataset, reconcile(dataset.bank, dataset.ledger, definition=_com_humano())
    )

    assert com_humano.matched_amount > so_regras.matched_amount
    assert com_humano.divergent_amount < so_regras.divergent_amount


def test_so_regras_o_total_e_o_deterministico_coincidem():
    # Enquanto a cascata é só de regras, os dois números são o mesmo — é isso
    # que mantém o golden intacto.
    dataset = build_benchmark(seed=1, n=300, taxa_divergencia=0.15)

    m = evaluate(dataset, reconcile(dataset.bank, dataset.ledger))

    assert m.bank_matched_total == m.bank_matched
    assert m.resolution_rate == m.deterministic_rate
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_metrics.py -q -k "humano or resolucao or deterministico_coincidem"
```

Esperado: FAIL com `AttributeError: 'Metrics' object has no attribute 'bank_matched_total'`.

- [ ] **Step 3: O motor para de descartar a classe**

Em `src/orchestrator/matching/engine.py`, acrescente ao `ReconcileResult`:

```python
    # Os matches agrupados pela CLASSE do resolver que os produziu, capturada
    # no laço. Sem isto, a única forma de separar match de regra de match
    # humano seria olhar `MatchResult.layer` — proveniência, não classe — que
    # é o mesmo join frágil que P3.2 manda evitar.
    matches_by_class: dict[CostClass, list[MatchResult]] = field(default_factory=dict)
```

com `from orchestrator.workflow.cost_class import CostClass` no topo. No laço, ao lado das outras acumulações:

```python
            matches_por_classe.setdefault(resolver.cost_class, []).extend(saida.matches)
```

inicializando `matches_por_classe: dict[CostClass, list[MatchResult]] = {}` antes do laço e passando `matches_by_class=matches_por_classe` no retorno.

- [ ] **Step 4: As métricas separam por classe**

Em `src/orchestrator/metrics.py`, dentro de `evaluate`, logo após `ids_contabil`:

```python
    # Só REGRA: `deterministic_rate` tem "determinística" no nome, e falso
    # positivo/negativo medem o CATÁLOGO DE REGRAS. Somar trabalho humano
    # aqui faria o número subir sem que nenhuma regra tivesse melhorado, e
    # transformaria uma aprovação correta em falso positivo.
    de_regra = result.matches_by_class.get(CostClass.REGRA, result.matches)
    casados_banco = {i for m in de_regra for i in m.bank_ids} & ids_banco
    casados_todos = ({i for m in de_regra for i in m.bank_ids | m.ledger_ids}
                      & (ids_banco | ids_contabil))

    # Todas as classes: estas duas respondem "quanto foi resolvido" e "quanto
    # ainda está em aberto" — perguntas de negócio, não do catálogo.
    casados_banco_total = {i for m in result.matches for i in m.bank_ids} & ids_banco
```

`de_regra` cai para `result.matches` quando `matches_by_class` está vazio, o que só acontece se alguém construir um `ReconcileResult` à mão — o motor sempre preenche.

Troque as duas somas de dinheiro para usarem `casados_banco_total`:

```python
    conciliado = sum(abs(e.amount) for e in dataset.bank if e.id in casados_banco_total)
    divergente = sum(
        abs(e.amount) for e in dataset.bank if e.id not in casados_banco_total
    )
```

Acrescente aos campos de `Metrics`, ao lado de `bank_matched`:

```python
    # Todas as classes, não só REGRA: é a taxa que um operador lê como
    # "quanto do fechamento está fechado".
    bank_matched_total: int
    resolution_rate: float
```

e ao `return Metrics(...)`:

```python
        bank_matched_total=len(casados_banco_total),
        resolution_rate=(
            (len(casados_banco_total) / bank_total) if bank_total else 0.0
        ),
```

No `render()`, logo abaixo da linha da taxa determinística:

```python
        if self.bank_matched_total != self.bank_matched:
            linhas.append(
                f"Taxa de resolução total:       {self.resolution_rate:.1%} "
                f"(inclui revisão humana)"
            )
```

- [ ] **Step 5: Rodar tudo, com o golden como juiz**

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q
./.venv/Scripts/python.exe -m ruff check src/ tests/
```

O golden precisa passar. Se falhar, a separação por classe mudou um número onde não devia — conserte o código, nunca o golden.

- [ ] **Step 6: Provar que o teste do falso positivo discrimina**

Troque temporariamente `de_regra` por `result.matches` em `metrics.py` e rode:

```bash
./.venv/Scripts/python.exe -m pytest tests/test_metrics.py -q -k "falso_positivo"
```

Esperado: FALHA. Restaure e confirme `git diff --exit-code src/orchestrator/metrics.py` limpo. Relate o que viu.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "fix: métricas distinguem match por classe de custo"
```

---

## Task 6: A guarda de idempotência no `Investigator`

**Files:**
- Modify: `src/orchestrator/agent/investigator.py`
- Modify: `tests/agent/test_investigator.py`

**Interfaces:**
- Consumes: `Fila`
- Produces: `Investigator(client, context, fila: Fila | None = None)`

- [ ] **Step 1: Escrever o teste**

Em `tests/agent/test_investigator.py`:

```python
def test_divergencia_ja_proposta_nao_chama_o_modelo_de_novo():
    """Idempotência do Tier 1, aplicada à chamada mais cara do sistema.

    O agente é classe AGENTE e o revisor é HUMANO, então o agente roda ANTES
    em toda passagem. Sem esta guarda, a passagem 2 reinvestigaria tudo o que
    a passagem 1 já investigou — e pagaria de novo por respostas que já estão
    na fila.
    """
    from orchestrator.review.fila import Fila
    from orchestrator.workflow.workset import WorkSet

    pares = generate_clean_pairs(seed=2, n=1)
    work = WorkSet(bank=[pares[0].bank], ledger=[])
    ja_proposta = work.as_divergences()[0]

    fila = Fila.vazia()
    fila.gravar_proposta(
        Proposal(
            divergence_id=ja_proposta.id,
            tipo=DivergenceType.DEFASAGEM_TEMPORAL,
            explicacao="da passagem anterior",
            evidencia=["e"],
            confianca=Confidence.MEDIA,
            acao_sugerida="conciliar_com(l1)",
        )
    )

    class _ClienteQueAcusa:
        model = "claude-haiku-4-5"

        def complete(self, system, messages, tools):
            raise AssertionError("o agente reinvestigou o que já estava na fila")

    saida = Investigator(
        client=_ClienteQueAcusa(), context=CONTEXTO_DE_TESTE, fila=fila
    ).resolve(work)

    assert len(saida.proposals) == 1
    assert saida.proposals[0].explicacao == "da passagem anterior"
    assert saida.cost.calls == 0
```

`CONTEXTO_DE_TESTE`: reaproveite o que o arquivo já monta; se estiver inline nos testes, extraia para uma constante no topo sem mudar o conteúdo.

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/agent/test_investigator.py -q -k "ja_proposta"
```

Esperado: FAIL — `Investigator.__init__() got an unexpected keyword argument 'fila'`.

- [ ] **Step 3: Implementar**

Em `src/orchestrator/agent/investigator.py`, acrescente ao dataclass, antes dos campos `init=False`:

```python
    # Idempotência: divergência que já tem proposta na fila não é
    # reinvestigada. O agente roda antes do revisor em toda passagem, então
    # sem isto a passagem 2 pagaria de novo por tudo.
    fila: "Fila | None" = None
```

com o import guardado por `TYPE_CHECKING` (`from orchestrator.review.fila import Fila`) para não criar dependência de import em tempo de execução. E no início de `_uma`:

```python
        if self.fila is not None:
            guardada = self.fila.proposta(divergencia.id)
            if guardada is not None:
                return guardada
```

- [ ] **Step 4: Rodar tudo**

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q
./.venv/Scripts/python.exe -m ruff check src/ tests/
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: agente não reinvestiga divergência que já tem proposta"
```

---

## Task 7: O revisor entra na definição padrão

**Files:**
- Modify: `src/orchestrator/workflow/definition.py`
- Modify: `tests/workflow/test_definition.py`
- Modify: `tests/api/test_definicao.py` se alguma asserção contar resolvers

**Interfaces:**
- Consumes: `RevisorHumano`, `Fila`
- Produces: `default_definition(fila: Fila | None = None) -> WorkflowDefinition` com quatro resolvers

- [ ] **Step 1: Escrever os testes**

Em `tests/workflow/test_definition.py`, **substitua** `test_definicao_padrao_nao_tem_agente` por:

```python
def test_definicao_padrao_nao_gasta_dinheiro():
    # A propriedade que importa nunca foi "só existem regras" — foi "nada
    # aqui gasta dinheiro". Com o revisor na cascata a definição tem duas
    # classes, e trocar só a asserção sem trocar o nome transformaria um
    # guarda de dinheiro num guarda de forma.
    d = default_definition()

    classes = {r.cost_class for s in d.stages for r in s.cascade}
    assert CostClass.AGENTE not in classes
```

e acrescente:

```python
def test_definicao_padrao_inclui_o_revisor_por_ultimo():
    d = default_definition()

    cascata = d.stages[0].ordered()
    assert [r.name for r in cascata] == ["L1", "L2", "L3", "revisor"]
    assert cascata[-1].cost_class is CostClass.HUMANO


def test_definicao_padrao_sem_fila_nao_resolve_nada_pelo_revisor():
    # Sem fila, o revisor existe na cascata e é inerte. É isso que mantém a
    # CLI e o golden exatamente como estavam.
    from orchestrator.cli import build_benchmark
    from orchestrator.matching.engine import reconcile
    from orchestrator.workflow.cost_class import CostClass as C

    ds = build_benchmark(seed=1, n=60, taxa_divergencia=0.15)
    r = reconcile(ds.bank, ds.ledger)

    assert r.matches_by_class.get(C.HUMANO, []) == []
    assert r.matches_by_resolver["revisor"] == 0
```

Atualize também `test_definicao_padrao_tem_as_tres_regras_num_stage`: a lista passa a ser `["L1", "L2", "L3", "revisor"]`. **Nenhum outro valor esperado muda.**

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/workflow/test_definition.py -q
```

Esperado: FAIL — a cascata tem três resolvers, não quatro.

- [ ] **Step 3: Implementar**

Em `src/orchestrator/workflow/definition.py`:

```python
def default_definition(fila: "Fila | None" = None) -> WorkflowDefinition:
    """O conciliador: três regras e o revisor humano.

    Sem agente — ele é opcional, custa dinheiro, e a definição que a API serve
    precisa ser executável sem gastar um centavo.

    O revisor entra SEMPRE. Sem fila ele usa uma vazia e não emite nada, então
    a CLI e o golden ficam idênticos; com fila, ele aplica o que foi aprovado.
    Não há "definição servida" separada da "definição executada".
    """
    from orchestrator.review.fila import Fila
    from orchestrator.review.revisor import RevisorHumano

    revisor = RevisorHumano(fila=fila if fila is not None else Fila.vazia())
    return WorkflowDefinition(
        id="conciliacao",
        name="Conciliação bancária",
        stages=(
            Stage(
                name="conciliar lançamentos",
                cascade=(*default_resolvers(), revisor),
            ),
        ),
    )
```

O import é local pela mesma razão que o de `engine.py`: `revisor.py` importa de `workflow/`, e um import de topo nos dois sentidos seria circular. Acrescente o `TYPE_CHECKING` para a anotação.

- [ ] **Step 4: Rodar tudo, golden incluído**

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q
./.venv/Scripts/python.exe -m ruff check src/ tests/
```

Se o golden falhar, o revisor emitiu algo com fila vazia — conserte o revisor.

- [ ] **Step 5: Ver o canvas com a terceira classe**

```bash
./.venv/Scripts/python.exe -m uvicorn orchestrator.api.app:app --port 8000
```

`http://localhost:8000` deve mostrar quatro linhas, a última `revisor · HUMANO` com 0,0%, e a soma das taxas mais a lacuna continuar 100%.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: o revisor entra na definição padrão, inerte sem fila"
```

---

## Task 8: As rotas da fila

**Files:**
- Modify: `src/orchestrator/api/schemas.py`, `src/orchestrator/api/app.py`
- Create: `tests/api/test_fila.py`

**Interfaces:**
- Consumes: `Fila`, `dataset_id`, `caminho_da_fila`, `Decision`, `Veredito`, `ids_de_conciliar_com`
- Produces:
  - `GET /api/fila/{workflow_id}` com query `seed`, `n`, `taxa_divergencia`, `estado`
  - `POST /api/fila/{workflow_id}/{divergence_id}/decisao`

- [ ] **Step 1: Escrever os testes**

`tests/api/test_fila.py`:

```python
import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from orchestrator.api.app import app  # noqa: E402

cliente = TestClient(app)

PARAMS = {"seed": 1, "n": 30, "taxa_divergencia": 0.15}


@pytest.fixture(autouse=True)
def _fila_isolada(tmp_path, monkeypatch):
    """Cada teste com a sua raiz de fila, e o cache da execução limpo.

    Sem isolar a raiz, um teste escreveria decisões que outro leria. Sem
    limpar o cache, a execução memoizada serviria o estado anterior.
    """
    import orchestrator.api.app as modulo

    monkeypatch.setattr(modulo, "_RAIZ_FILA", tmp_path)
    modulo._executar_memoizado.cache_clear()
    yield
    modulo._executar_memoizado.cache_clear()


def test_fila_vazia_devolve_lista_vazia():
    corpo = cliente.get("/api/fila/conciliacao", params=PARAMS).json()

    assert corpo["itens"] == []
    assert corpo["dataset"] == "s1-n30-t0.15"


def test_workflow_desconhecido_da_404():
    r = cliente.get("/api/fila/nao-existe", params=PARAMS)

    assert r.status_code == 404


def test_decidir_divergencia_sem_proposta_da_404():
    r = cliente.post(
        "/api/fila/conciliacao/d-b-inexistente/decisao",
        params=PARAMS,
        json={"veredito": "aceitar", "autor": "a"},
    )

    assert r.status_code == 404


def test_corrigir_sem_tipo_da_422():
    r = cliente.post(
        "/api/fila/conciliacao/d-b-b00003/decisao",
        params=PARAMS,
        json={"veredito": "corrigir", "autor": "a"},
    )

    assert r.status_code == 422


def test_ler_a_fila_nao_chama_o_modelo(monkeypatch):
    # A mesma regra do endpoint de execução: nenhuma rota tem caminho até o
    # modelo. Asserção sobre o estado do espião, nunca sobre exceção
    # propagada — a técnica por exceção foi provada vazia (P3.8).
    import orchestrator.agent.anthropic_client as ac

    chamadas = []
    monkeypatch.setattr(
        ac.AnthropicClient, "complete",
        lambda self, system, messages, tools: chamadas.append(1),
    )

    assert cliente.get("/api/fila/conciliacao", params=PARAMS).status_code == 200
    assert chamadas == []


def test_execucao_so_serve_classes_que_nao_gastam():
    corpo = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"seed": 1, "n": 30, "taxa_divergencia": 0.15},
    ).json()

    assert all(r["cost_class"] != "AGENTE" for r in corpo["by_resolver"])
    assert "revisor" in [r["name"] for r in corpo["by_resolver"]]
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/api/test_fila.py -q
```

Esperado: FAIL com 404 em `/api/fila/conciliacao` — a rota não existe.

- [ ] **Step 3: Os schemas**

Acrescente a `src/orchestrator/api/schemas.py`:

```python
class LancamentoJSON(BaseModel):
    id: str
    lado: str          # "banco" ou "contabil"
    data: str
    valor: int         # centavos, sempre int
    descricao: str
    contraparte: str
    documento: str | None


class ItemFilaJSON(BaseModel):
    divergence_id: str
    tipo: str
    confianca: str
    explicacao: str
    evidencia: list[str]
    acao_sugerida: str
    conciliar_com: list[str]
    lancamentos: list[LancamentoJSON]
    decidido: bool = False
    veredito: str | None = None
    tipo_decidido: str | None = None
    autor: str | None = None
    # Verdadeiro quando o humano discordou do agente — é o sinal de treino do
    # §4.7 do spec pai, exposto sem máquina nova.
    divergiu: bool = False


class FilaJSON(BaseModel):
    workflow: str
    dataset: str
    itens: list[ItemFilaJSON]
    # A taxonomia vem da API, não hardcoded no JS. Duplicar os 14 valores no
    # front criaria drift silencioso no dia em que a taxonomia crescer — o
    # mesmo defeito que a fatia anterior existiu para tornar impossível.
    tipos: list[str]


class DecisaoRequest(BaseModel):
    veredito: Veredito
    tipo: DivergenceType | None = None
    conciliar_com: list[str] | None = None
    autor: str = Field(min_length=1)
    motivo: str = ""
```

com `from orchestrator.review.decision import Veredito` e `from orchestrator.taxonomy import DivergenceType` no topo.

- [ ] **Step 4: As rotas**

Em `src/orchestrator/api/app.py`, **antes** do `app.mount` final:

```python
# Raiz da fila em disco. É atributo de módulo para o teste poder trocá-la por
# um tmp_path sem escrever no repositório.
_RAIZ_FILA: Path | None = None


def _abrir_fila(workflow_id: str, seed: int, n: int, taxa: float) -> tuple[Fila, str]:
    dataset = dataset_id(seed, n, taxa)
    return Fila(caminho_da_fila(workflow_id, dataset, raiz=_RAIZ_FILA)), dataset


@app.get("/api/fila/{workflow_id}", response_model=FilaJSON)
def ler_fila(
    workflow_id: str,
    seed: int = 1,
    n: int = 300,
    taxa_divergencia: float = 0.15,
    estado: str = "pendente",
) -> FilaJSON:
    if workflow_id not in _WORKFLOWS:
        raise HTTPException(status_code=404, detail=f"workflow desconhecido: {workflow_id}")
    fila, dataset = _abrir_fila(workflow_id, seed, n, taxa_divergencia)
    ds = build_benchmark(seed=seed, n=n, taxa_divergencia=taxa_divergencia)
    por_id = {e.id: ("banco", e) for e in ds.bank}
    por_id.update({e.id: ("contabil", e) for e in ds.ledger})

    pares = (
        [(p, None) for p in fila.pendentes()]
        if estado == "pendente"
        else list(fila.decididas())
    )
    return FilaJSON(
        workflow=workflow_id,
        dataset=dataset,
        itens=[_item(p, d, por_id) for p, d in pares],
        tipos=[t.value for t in DivergenceType],
    )


@app.post("/api/fila/{workflow_id}/{divergence_id}/decisao", response_model=ItemFilaJSON)
def decidir(
    workflow_id: str,
    divergence_id: str,
    pedido: DecisaoRequest,
    seed: int = 1,
    n: int = 300,
    taxa_divergencia: float = 0.15,
) -> ItemFilaJSON:
    if workflow_id not in _WORKFLOWS:
        raise HTTPException(status_code=404, detail=f"workflow desconhecido: {workflow_id}")
    fila, _ = _abrir_fila(workflow_id, seed, n, taxa_divergencia)
    proposta = fila.proposta(divergence_id)
    if proposta is None:
        raise HTTPException(
            status_code=404,
            detail=f"sem proposta para {divergence_id}; decidir sem proposta do "
                   f"agente está fora do escopo desta fatia",
        )
    if pedido.veredito is Veredito.CORRIGIR and pedido.tipo is None:
        raise HTTPException(status_code=422, detail="corrigir exige `tipo`")

    if pedido.veredito is Veredito.ACEITAR:
        tipo, ids = proposta.tipo, ids_de_conciliar_com(proposta.acao_sugerida)
    elif pedido.veredito is Veredito.CORRIGIR:
        tipo = pedido.tipo
        ids = frozenset(pedido.conciliar_com or [])
    else:
        tipo, ids = None, frozenset()

    fila.gravar_decisao(
        Decision(
            divergence_id=divergence_id, veredito=pedido.veredito, tipo=tipo,
            conciliar_com=ids, autor=pedido.autor,
            quando=datetime.now(UTC), motivo=pedido.motivo,
        )
    )
    # A execução memoizada deixou de ser função só de (workflow, seed, n,
    # taxa): ela agora depende do conteúdo da fila. Sem limpar, aprovar uma
    # proposta e recarregar o canvas mostraria o estado anterior, e o revisor
    # concluiria que a aprovação não funcionou.
    _executar_memoizado.cache_clear()

    ds = build_benchmark(seed=seed, n=n, taxa_divergencia=taxa_divergencia)
    por_id = {e.id: ("banco", e) for e in ds.bank}
    por_id.update({e.id: ("contabil", e) for e in ds.ledger})
    return _item(proposta, fila.decisao(divergence_id), por_id)
```

E o montador de item, acima das rotas:

**Atenção:** `BankEntry` e `LedgerEntry` **não têm os mesmos campos**.
`BankEntry` tem `date`, `amount`, `description`, `counterparty`;
`LedgerEntry` tem `accrual_date`, `cash_date`, `gross_amount`, `net_amount`,
`account`, `supplier` — nenhum `description`, nenhum `counterparty`. Um
construtor que tente `e.description` nos dois estoura no primeiro item
contábil. Por isso há uma função por lado:

```python
def _do_banco(e) -> LancamentoJSON:
    return LancamentoJSON(
        id=e.id, lado="banco", data=e.date.isoformat(), valor=e.amount,
        descricao=e.description, contraparte=e.counterparty or "",
        documento=e.document,
    )


def _do_contabil(e) -> LancamentoJSON:
    # `net_amount` é o que se compara com o extrato; `cash_date` é a data que
    # importa para conciliar, com `accrual_date` como reserva quando o caixa
    # ainda não foi registrado.
    return LancamentoJSON(
        id=e.id, lado="contabil",
        data=(e.cash_date or e.accrual_date).isoformat(), valor=e.net_amount,
        descricao=e.account, contraparte=e.supplier, documento=e.document,
    )


def _item(proposta, decisao, por_id) -> ItemFilaJSON:
    ids = ids_de_conciliar_com(proposta.acao_sugerida)
    # O revisor precisa ver extrato e contábil lado a lado — o veredito do
    # agente sozinho não dá para julgar nada.
    do_item = _ids_da_divergencia(proposta.divergence_id) | ids
    lancamentos = []
    for i in sorted(do_item):
        par = por_id.get(i)
        if par is None:
            continue
        lado, e = par
        lancamentos.append(_do_banco(e) if lado == "banco" else _do_contabil(e))
    divergiu = decisao is not None and (
        decisao.tipo is not proposta.tipo or decisao.conciliar_com != ids
    )
    return ItemFilaJSON(
        divergence_id=proposta.divergence_id,
        tipo=proposta.tipo.value,
        confianca=proposta.confianca.value,
        explicacao=proposta.explicacao,
        evidencia=list(proposta.evidencia),
        acao_sugerida=proposta.acao_sugerida,
        conciliar_com=sorted(ids),
        lancamentos=lancamentos,
        decidido=decisao is not None,
        veredito=decisao.veredito.value if decisao else None,
        tipo_decidido=decisao.tipo.value if decisao and decisao.tipo else None,
        autor=decisao.autor if decisao else None,
        divergiu=divergiu,
    )


def _ids_da_divergencia(divergence_id: str) -> set[str]:
    """`d-b-<id>` e `d-l-<id>` carregam o id do lançamento no próprio nome."""
    for prefixo in ("d-b-", "d-l-"):
        if divergence_id.startswith(prefixo):
            return {divergence_id[len(prefixo):]}
    return set()
```

- [ ] **Step 5: A lacuna do canvas passa a contar o trabalho humano**

Em `_executar_memoizado`, a lacuna hoje usa `m.bank_matched` — que a Task 5
restringiu à classe `REGRA`. Deixá-la assim faria o canvas contar como **aberto**
o que um humano já fechou, e a soma das taxas mais a lacuna deixaria de dar 1,0
assim que existisse uma decisão. Troque:

```python
    total_resolvido = m.bank_matched_total
```

mantendo o comentário que já está lá sobre por que não se usa a soma das
contagens por resolver — a razão continua valendo, e agora a grandeza também
inclui as outras classes.

Acrescente a `tests/api/test_fila.py`:

```python
def test_a_soma_das_taxas_mais_a_lacuna_continua_um():
    corpo = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"seed": 1, "n": 300, "taxa_divergencia": 0.15},
    ).json()

    soma = sum(r["rate"] for r in corpo["by_resolver"]) + corpo["gap"]["rate"]
    assert abs(soma - 1.0) < 1e-9
```

- [ ] **Step 6: Rodar tudo**

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q
./.venv/Scripts/python.exe -m ruff check src/ tests/
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: rotas da fila de revisão, com cache invalidado na decisão"
```

---

## Task 9: A tela da fila

**Files:**
- Create: `web/fila.html`, `web/fila.css`, `web/fila.js`
- Create: `tests/api/test_fila_estatica.py`

**Interfaces:**
- Consumes: `GET /api/fila/conciliacao`, `POST /api/fila/conciliacao/{id}/decisao`
- Produces: `GET /fila.html`

- [ ] **Step 1: Escrever o teste**

`tests/api/test_fila_estatica.py`:

```python
import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from orchestrator.api.app import app  # noqa: E402

cliente = TestClient(app)


def test_a_pagina_da_fila_e_servida():
    r = cliente.get("/fila.html")

    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    # Âncoras estruturais: o ponto de montagem que o JS escreve e o script
    # sem o qual a página não desenha nada. Existem por razão própria, ao
    # contrário de uma palavra plantada para o teste.
    assert 'id="itens"' in r.text
    assert "fila.js" in r.text
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/api/test_fila_estatica.py -q
```

Esperado: FAIL com 404.

- [ ] **Step 3: A página**

`web/fila.html`:

```html
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Fila de revisão — Agent Orchestrator</title>
  <link rel="stylesheet" href="/fila.css">
</head>
<body>
  <header>
    <h1>Fila de revisão</h1>
    <p class="proveniencia" id="proveniencia">carregando…</p>
    <label>Seu identificador
      <input id="autor" placeholder="controller@cliente">
    </label>
  </header>
  <main id="itens"></main>
  <noscript>Esta página precisa de JavaScript para conciliar lançamentos.</noscript>
  <script src="/fila.js"></script>
</body>
</html>
```

`web/fila.js`:

```js
// A tela não decide nada: ela mostra o que a API mediu e manda de volta o que
// o humano escolheu. Nenhum número é escrito aqui.
const PARAMS = new URLSearchParams({ seed: 1, n: 30, taxa_divergencia: 0.15 });

function autor() {
  const campo = document.getElementById("autor");
  try {
    if (!campo.value) campo.value = localStorage.getItem("autor") || "";
  } catch (e) { /* armazenamento bloqueado: segue sem lembrar */ }
  return campo.value.trim();
}

async function carregar() {
  const r = await fetch(`/api/fila/conciliacao?${PARAMS}`);
  if (!r.ok) throw new Error(`${r.status} ao ler a fila`);
  const corpo = await r.json();

  document.getElementById("proveniencia").textContent =
    `${corpo.itens.length} pendente(s) — dataset ${corpo.dataset}`;

  const alvo = document.getElementById("itens");
  alvo.innerHTML = "";
  for (const item of corpo.itens) alvo.appendChild(desenhar(item));
}

function desenhar(item) {
  const el = document.createElement("section");
  el.className = "item";
  const lancamentos = item.lancamentos
    .map((l) => `<tr><td>${l.lado}</td><td>${l.id}</td><td>${l.data}</td>
                 <td class="num">${(l.valor / 100).toFixed(2)}</td>
                 <td>${l.contraparte}</td><td>${l.documento ?? "—"}</td></tr>`)
    .join("");
  const evidencia = item.evidencia.map((e) => `<li>${e}</li>`).join("");

  el.innerHTML = `
    <h2>${item.divergence_id}</h2>
    <table class="lancamentos"><tbody>${lancamentos}</tbody></table>
    <p class="proposta">
      <span class="tipo">${item.tipo}</span>
      <span class="confianca conf-${item.confianca.toLowerCase()}">${item.confianca}</span>
      ${item.explicacao}
    </p>
    <ul class="evidencia">${evidencia}</ul>
    <div class="acoes">
      <button data-v="aceitar">Aceitar</button>
      <button data-v="corrigir">Corrigir</button>
      <button data-v="rejeitar">Rejeitar</button>
    </div>
    <div class="correcao" hidden>
      <select class="tipo-corrigido"></select>
      <input class="ids-corrigidos" placeholder="ids a conciliar, separados por vírgula">
    </div>`;

  const correcao = el.querySelector(".correcao");
  el.querySelectorAll(".acoes button").forEach((b) => {
    b.addEventListener("click", () => {
      if (b.dataset.v === "corrigir" && correcao.hidden) {
        correcao.hidden = false;
        return;
      }
      decidir(item, b.dataset.v, correcao, el);
    });
  });
  return el;
}

async function decidir(item, veredito, correcao, el) {
  const quem = autor();
  if (!quem) { alert("preencha seu identificador antes de decidir"); return; }
  try { localStorage.setItem("autor", quem); } catch (e) { /* segue */ }

  const corpo = { veredito, autor: quem };
  if (veredito === "corrigir") {
    corpo.tipo = correcao.querySelector(".tipo-corrigido").value;
    corpo.conciliar_com = correcao.querySelector(".ids-corrigidos").value
      .split(",").map((s) => s.trim()).filter(Boolean);
  }

  const r = await fetch(
    `/api/fila/conciliacao/${item.divergence_id}/decisao?${PARAMS}`,
    { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify(corpo) });
  if (!r.ok) { alert(`falhou: ${r.status}`); return; }
  el.remove();
}

carregar().catch((erro) => {
  document.getElementById("proveniencia").textContent = `falhou ao carregar: ${erro}`;
});
```

O `<select>` de tipos é preenchido a partir de `corpo.tipos`, que a API serve —
nunca de uma lista escrita no JS. Em `carregar()`, antes do laço de itens:

```js
  TIPOS = corpo.tipos;
```

com `let TIPOS = [];` no topo do arquivo, e em `desenhar()` o select sai de
`TIPOS.map((t) => `<option>${t}</option>`).join("")` no lugar do `<select>`
vazio.

`web/fila.css`:

```css
/* Os tokens de cor moram em style.css e são a única definição deles. */
@import url("/style.css");

header label {
  display: block;
  margin-top: .75rem;
  font-size: .85rem;
  color: #6b6660;
}
header input {
  display: block;
  margin-top: .25rem;
  padding: .35rem .5rem;
  border: 1px solid var(--borda);
  border-radius: 4px;
  min-width: 18rem;
  max-width: 100%;
  font: inherit;
}

.item {
  border: 1px solid var(--borda);
  border-radius: 8px;
  background: #fff;
  padding: 1rem 1.25rem;
  margin-bottom: 1rem;
}
.item h2 {
  font-size: .95rem;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  margin: 0 0 .75rem;
}

.lancamentos { width: 100%; border-collapse: collapse; font-size: .85rem; }
.lancamentos td { padding: .3rem .5rem; border-top: 1px solid #efece7; }
.lancamentos td.num {
  text-align: right;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
}

.proposta { margin: .75rem 0 .25rem; }
.tipo {
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  font-size: .8rem;
  margin-right: .4rem;
}
.confianca {
  font-size: .7rem;
  letter-spacing: .04em;
  padding: .15rem .4rem;
  border-radius: 4px;
  border: 1px solid currentColor;
  margin-right: .5rem;
}
.conf-alta  { color: var(--regra); }
.conf-media { color: var(--agente); }
.conf-baixa { color: #6b6660; }

.evidencia { margin: .25rem 0 .75rem 1rem; padding: 0; font-size: .85rem; color: #4a4640; }
.evidencia li { margin: .15rem 0; }

.acoes { display: flex; gap: .5rem; flex-wrap: wrap; }
.acoes button {
  padding: .4rem .9rem;
  border: 1px solid var(--borda);
  border-radius: 4px;
  background: #fff;
  font: inherit;
  cursor: pointer;
}
.acoes button:hover { border-color: var(--tinta); }

.correcao { display: flex; gap: .5rem; margin-top: .6rem; flex-wrap: wrap; }
.correcao select, .correcao input {
  padding: .35rem .5rem;
  border: 1px solid var(--borda);
  border-radius: 4px;
  font: inherit;
}
.correcao input { flex: 1; min-width: 14rem; }

@media (max-width: 34rem) {
  .lancamentos { font-size: .78rem; }
  .acoes button { flex: 1; }
}
```

- [ ] **Step 4: Ver com os próprios olhos**

Gere propostas e abra a tela:

```bash
./.venv/Scripts/python.exe -m orchestrator.eval.agent_eval --via assinatura --seed 1 --n 30
./.venv/Scripts/python.exe -m uvicorn orchestrator.api.app:app --port 8000
```

Em `http://localhost:8000/fila.html`: dois itens, cada um com os lançamentos, a proposta e três botões. Aceitar um deve removê-lo da lista. Nada pode mostrar `NaN`, `undefined` ou `[object Object]`.

- [ ] **Step 5: Rodar tudo e commitar**

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q
./.venv/Scripts/python.exe -m ruff check src/ tests/
git add -A
git commit -m "feat: tela da fila de revisão"
```

---

## Task 10: O CLI grava as propostas, e a prova de ponta a ponta

**Files:**
- Modify: `src/orchestrator/eval/agent_eval.py`
- Modify: `docs/superpowers/DECISOES.md`, `README.md`
- Create: `tests/eval/test_grava_fila.py`

**Interfaces:**
- Consumes: `Fila`, `dataset_id`, `caminho_da_fila`
- Produces: `avaliar(..., gravar_fila: bool = False)`; flag `--fila` em `main`

- [ ] **Step 1: Escrever o teste**

`tests/eval/test_grava_fila.py`:

```python
from orchestrator.eval.agent_eval import avaliar
from orchestrator.review.fila import Fila, caminho_da_fila, dataset_id
from orchestrator.workflow.cost_class import CostClass
from orchestrator.workflow.resolver import ResolverDescription, ResolverOutput


class _AgenteFalso:
    name = "investigador"
    cost_class = CostClass.AGENTE

    def resolve(self, work):
        from orchestrator.agent.proposal import Proposal
        return ResolverOutput(
            proposals=[
                Proposal.abstencao(d.id, "não sei") for d in work.as_divergences()
            ]
        )

    def describe(self):
        return ResolverDescription(self.name, self.cost_class, "falso")


def test_propostas_vao_para_a_fila_quando_pedido(tmp_path, monkeypatch):
    import orchestrator.eval.agent_eval as modulo

    monkeypatch.setattr(modulo, "_RAIZ_FILA", tmp_path)

    avaliar(
        model="assinatura", seed=1, n=30, taxa_divergencia=0.15, via="assinatura",
        investigator_factory=lambda ctx: _AgenteFalso(), gravar_fila=True,
    )

    fila = Fila(caminho_da_fila("conciliacao", dataset_id(1, 30, 0.15), raiz=tmp_path))
    assert len(fila.pendentes()) == 2


def test_sem_pedir_nada_e_gravado(tmp_path, monkeypatch):
    import orchestrator.eval.agent_eval as modulo

    monkeypatch.setattr(modulo, "_RAIZ_FILA", tmp_path)

    avaliar(
        model="assinatura", seed=1, n=30, taxa_divergencia=0.15, via="assinatura",
        investigator_factory=lambda ctx: _AgenteFalso(),
    )

    assert not (tmp_path / "fila").exists()
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/eval/test_grava_fila.py -q
```

Esperado: FAIL — `avaliar() got an unexpected keyword argument 'gravar_fila'`.

- [ ] **Step 3: Implementar**

Em `src/orchestrator/eval/agent_eval.py`, acrescente `_RAIZ_FILA: Path | None = None` no topo do módulo, o parâmetro `gravar_fila: bool = False` em `avaliar`, e depois de `resultado = reconcile(...)`:

```python
    if gravar_fila:
        # Quem grava é o CLI, nunca `reconcile`. O motor continua puro, e é
        # disso que o golden e o teste do dinheiro dependem.
        fila = Fila(
            caminho_da_fila(
                "conciliacao", dataset_id(seed, n, taxa_divergencia), raiz=_RAIZ_FILA
            )
        )
        for p in resultado.proposals:
            fila.gravar_proposta(p)
```

Em `main`, uma flag `--fila` (`action="store_true"`, help: `"grava as propostas na fila de revisão"`) repassada como `gravar_fila=args.fila`.

- [ ] **Step 4: A prova de ponta a ponta**

Com a suíte verde, execute o roteiro e **relate o que viu em cada passo**:

```bash
./.venv/Scripts/python.exe -m orchestrator.eval.agent_eval --via assinatura --seed 1 --n 30 --fila
./.venv/Scripts/python.exe -m uvicorn orchestrator.api.app:app --port 8000
```

1. `data/fila/conciliacao/s1-n30-t0.15.jsonl` tem duas linhas `"kind": "proposta"`.
2. Em `/fila.html`, aceitar a `DEFASAGEM_TEMPORAL` de `d-b-b00003`.
3. Em `/`, o canvas mostra `revisor` com 1 match e a lacuna menor que antes.
4. **`d-l-l00003` sumiu da fila** — os dois ids saíram do pool juntos, e o meio-item fantasma deixou de existir sem nenhum código especial para isso.

Se o passo 4 não acontecer, pare e relate: é a propriedade que o §3.5 do spec prevê, e ela falhando significa que a classificação de lado pelo pool está errada.

- [ ] **Step 5: Registrar as decisões**

Acrescente a `docs/superpowers/DECISOES.md` uma seção `# Plano 4 — fila de revisão humana`, seguindo o formato dos planos anteriores (`#` para a seção, `##` por decisão, cada uma com a alternativa rejeitada e o custo de estar errado). No mínimo: escopo por `dataset_id`; primeira-proposta-vence contra última-decisão-vence; classificação de lado pelo pool; `matches_by_class` em vez de filtrar por `layer`; dinheiro contando todas as classes enquanto a taxa determinística não conta; `cache_clear` no POST; `Fila.vazia()` sem disco; o teste que mudou de propósito.

- [ ] **Step 6: README**

Acrescente uma subseção sobre a fila: gerar propostas com `--fila`, abrir `/fila.html`, e a frase que importa — **decisão é o que resolve; proposta nunca resolve**.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: CLI grava propostas na fila; fecha o plano 4"
```

---

## Verificação final do plano

- [ ] `pytest tests/ -q` verde, golden incluído
- [ ] `./.venv/Scripts/python.exe tests/golden/gerar.py` seguido de `git diff --exit-code tests/golden/cascata_12_sementes.json` limpo
- [ ] `ruff check src/ tests/` limpo
- [ ] CLI na semente 1, n=500: **85,3%**, zero FP, zero FN
- [ ] `grep -rn "proposals" src/orchestrator/matching/engine.py` não mostra `proposals` em nenhuma expressão que calcule o pool
- [ ] `grep -rn "layer" src/orchestrator/metrics.py` só aparece em `matches_by_layer`, nunca para decidir classe
- [ ] Nenhuma rota HTTP monta cascata com resolver de classe `AGENTE`
- [ ] O roteiro de ponta a ponta da Task 10 passa nos quatro passos
