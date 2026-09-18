"""O `investigador` DECLARADO do catálogo — não o de `agent/investigator.py`.

Ele estava cego desde o rename do domínio: declarava `kind="lancamento"`, que
nenhuma fonte produz, e um prompt sobre `{descricao}`, campo que `BankEntry`
não tem. Compor `L1 + investigador` rodava com o agente sem ver item nenhum —
o modo de falha que o cabeçalho de `authoring/composicao.py` descreve, dentro
do próprio catálogo.
"""

from orchestrator.agent.declarado import construir_agente
from orchestrator.agent.llm import FakeLLMClient
from orchestrator.domains.reconciliation.synth.benchmark import SyntheticSource
from orchestrator.domains.registro import CATALOGO


def _investigador():
    return next(a for a in CATALOGO.agentes if a.name == "investigador")


def test_o_investigador_do_catalogo_consome_um_kind_que_a_fonte_PRODUZ():
    kinds = {i.kind for i in SyntheticSource(seed=1, n=30, taxa_divergencia=0.15).load().items}
    assert _investigador().kind in kinds


def test_o_investigador_do_catalogo_VE_itens_e_o_prompt_RENDERIZA():
    """Sem estas duas linhas, um agente cego e um agente que vê são iguais
    para a suíte: nenhum dos dois falha. `units` vazio é o sintoma da
    cegueira; `KeyError` no prompt seria o sintoma de trocar só o kind."""
    pool = SyntheticSource(seed=1, n=30, taxa_divergencia=0.15).load()
    agente = construir_agente(_investigador(), FakeLLMClient([]), CATALOGO.ferramentas)

    tarefas = agente.spec.units(pool)

    assert tarefas, "o investigador não montou tarefa nenhuma: continua cego"
    assert all("{" not in t.prompt for t in tarefas), "campo sem interpolar no prompt"
    assert agente.describe().consome == frozenset({"banco"})
