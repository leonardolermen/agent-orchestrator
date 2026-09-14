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
