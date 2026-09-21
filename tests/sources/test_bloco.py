"""A fonte como degrau: o `Input` do canvas.

O que estes testes protegem não é a leitura — cada fonte tem os seus. É o
CONTRATO do bloco: que ele consome a semente, produz o trabalho, e não lê duas
vezes.
"""

from dataclasses import dataclass, field

import pytest

from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.sources.bloco import INICIO, Entrada


@dataclass
class FonteFalsa:
    """Uma fonte que CONTA quantas vezes foi lida.

    A contagem é o ponto: `HttpSource.ref` busca na rede para calcular o hash do
    conteúdo, então cada acesso a `.ref` é uma requisição. Um bloco que o
    escrevesse duas vezes somaria duas idas à API do parceiro por leitura, e
    nada no tipo avisaria.
    """

    itens: tuple[WorkItem, ...] = ()
    leituras: int = 0
    refs: int = 0
    _ref: str = field(default="falsa:1", init=False)

    @property
    def ref(self) -> str:
        self.refs += 1
        return self._ref

    def load(self) -> WorkSet:
        self.leituras += 1
        return WorkSet(items=self.itens)


def _semente() -> WorkSet:
    return WorkSet(items=(WorkItem(id="s", kind=INICIO, payload=None, origem="borda"),))


def _fonte(n: int = 2) -> FonteFalsa:
    return FonteFalsa(
        itens=tuple(
            WorkItem(id=f"i{k}", kind="pedido", payload={"v": k}, origem="falsa")
            for k in range(n)
        )
    )


def test_consome_a_semente_e_produz_o_trabalho():
    fonte = _fonte()

    saida = Entrada(fonte=fonte, produz=("pedido",)).resolve(_semente())

    assert [sorted(r.item_ids) for r in saida.resolutions] == [["s"]]
    assert [i.id for i in saida.produced] == ["i0", "i1"]


def test_le_a_fonte_UMA_vez_e_pede_o_ref_UMA_vez():
    fonte = _fonte()

    Entrada(fonte=fonte, produz=("pedido",)).resolve(_semente())

    assert fonte.leituras == 1
    assert fonte.refs == 1


def test_sem_semente_NAO_le():
    """O degrau roda uma vez por ronda. Sem esta guarda, um workflow com duas
    rondas leria a fonte duas vezes e duplicaria o trabalho inteiro."""
    fonte = _fonte()
    vazio = WorkSet(items=(WorkItem(id="x", kind="pedido", payload=None, origem="t"),))

    saida = Entrada(fonte=fonte, produz=("pedido",)).resolve(vazio)

    assert fonte.leituras == 0
    assert saida.resolutions == []
    assert saida.produced == ()


def test_declara_a_fiacao_antes_de_rodar():
    d = Entrada(fonte=_fonte(), produz=("pedido",)).describe()

    # `consome` NÃO é vazio, e é o ponto: vazio significa "vejo o pool inteiro"
    # e desligaria a guarda de beco sem saída no grafo todo.
    assert d.consome == frozenset({INICIO})
    assert d.produz == frozenset({"pedido"})


def test_produzir_a_propria_semente_e_recusado():
    with pytest.raises(ValueError, match="a si mesmo"):
        Entrada(fonte=_fonte(), produz=(INICIO,))


def test_sem_kind_declarado_e_recusado():
    with pytest.raises(ValueError, match="kind"):
        Entrada(fonte=_fonte(), produz=())


def test_a_fonte_NAO_e_lida_ao_construir():
    """Compor não pode tocar em banco nem em rede: `/api/composicoes` valida sem
    executar, e uma fonte lida na construção faria "validar" abrir conexão."""
    fonte = _fonte()

    Entrada(fonte=fonte, produz=("pedido",))

    assert fonte.leituras == 0
    assert fonte.refs == 0


def test_de_ponta_a_ponta_o_run_comeca_pela_SEMENTE():
    """A prova de que o workflow se basta: o pool começa com um item só — a
    semente — e o trabalho de verdade aparece porque o bloco leu.

    Sem a semente o pool começaria vazio, e a borda recusa pool vazio. Sem o
    bloco consumi-la, ela sobraria na lacuna como um item que ninguém deu conta.
    """
    from orchestrator.kernel.definition import Stage, WorkflowDefinition
    from orchestrator.regras import Filtro
    from orchestrator.runtime.engine import execute

    fonte = _fonte(3)
    d = WorkflowDefinition(
        id="w",
        name="W",
        stages=(
            Stage(
                name="ler",
                cascade=(Entrada(fonte=fonte, produz=("pedido",)),),
                consome=frozenset({INICIO}),
                produz=frozenset({"pedido"}),
            ),
            Stage(
                name="tratar",
                cascade=(Filtro(kind="pedido", campo="v", teste="preenchido"),),
                consome=frozenset({"pedido"}),
            ),
        ),
    )

    run = execute(d, _semente(), model="claude-opus-5")

    # A semente saiu, os três itens entraram, e o filtro tratou os que tinham
    # `v` preenchido — `v=0` é vazio? Não: `0` não é `None` nem `""`.
    resolvidos = {i for r in run.resolutions for i in r.item_ids}
    assert "s" in resolvidos
    assert {"i0", "i1", "i2"} <= resolvidos
    assert run.unresolved.items == ()


def test_a_LACUNA_nao_mente_quando_o_pool_CRESCE():
    """O defeito que só apareceu rodando contra um Postgres de verdade.

    A borda contava `resolvidos = pool_inicial - sobrou`, o que pressupõe que o
    pool nunca cresce. Com um bloco que produz, ele cresce: um run que leu 8
    pedidos reportou `resolvidos: -7` e lacuna de 800%. Num produto cuja tese é
    "a lacuna nunca mente", esse é o pior número possível.

    O denominador honesto é TODO item que existiu — e o `Run` precisou aprender
    a contar o que criou, porque `len(unresolved)` não distingue um item que
    veio da fonte de um que um resolver fabricou.
    """
    from orchestrator.kernel.definition import Stage, WorkflowDefinition
    from orchestrator.runtime.engine import execute

    fonte = _fonte(8)
    d = WorkflowDefinition(
        id="w",
        name="W",
        stages=(
            Stage(
                name="ler",
                cascade=(Entrada(fonte=fonte, produz=("pedido",)),),
                consome=frozenset({INICIO}),
                produz=frozenset({"pedido"}),
            ),
        ),
        # Ninguém consome `pedido`: o run entrega os 8 e eles ficam no pool.
        entrega=frozenset({"pedido"}),
    )

    run = execute(d, _semente(), model="claude-opus-5")

    assert run.produzidos == 8
    # A conta da borda, reproduzida: 1 semente + 8 produzidos - 1 semente = 8.
    total = len(_semente().items) + run.produzidos - 1
    assert total == 8
    assert total - len(run.unresolved.items) == 0
