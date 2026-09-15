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
