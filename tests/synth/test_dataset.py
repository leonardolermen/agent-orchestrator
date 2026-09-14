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
