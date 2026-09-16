"""`Run` e o barramento de eventos.

Como em `test_work.py`, nada aqui importa domínio: o kernel não conhece nenhum.
"""

from datetime import UTC, datetime, timedelta

import pytest

from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.definition import Stage, WorkflowDefinition
from orchestrator.kernel.event import Event, EventBus, EventKind, NullBus
from orchestrator.kernel.resolution import Resolution
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.run import Run, RunState, new_run_id
from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.runtime.engine import execute


def _pool(*ids: str) -> WorkSet:
    return WorkSet(items=tuple(WorkItem(id=i, kind="coisa", payload=i) for i in ids))


class _Resolve:
    def __init__(self, ids, cost_class=CostClass.REGRA, name="r"):
        self._ids, self.cost_class, self.name = ids, cost_class, name

    def describe(self):
        return ResolverDescription(self.name, self.cost_class, "t")

    def resolve(self, work):
        presentes = work.ids()
        return ResolverOutput(
            resolutions=[
                Resolution(item_ids=frozenset({i}), produced_by=self.name, rule="t")
                for i in self._ids
                if i in presentes
            ]
        )


def _wf(*resolvers, wid="w") -> WorkflowDefinition:
    return WorkflowDefinition(id=wid, name="W", stages=(Stage("s", tuple(resolvers)),))


# --------------------------------------------------------------------------
# identidade e tempo
# --------------------------------------------------------------------------


def test_id_de_run_ordena_por_tempo_como_string():
    """A listagem "mais recentes primeiro" sai de graça do formato do id.

    Sem essa propriedade o store precisaria de índice ou de ordenação por
    `started_at` — que empata entre runs do mesmo milissegundo.
    """
    antes = new_run_id(datetime(2026, 9, 16, 10, 0, 0, tzinfo=UTC))
    depois = new_run_id(datetime(2026, 9, 16, 10, 0, 1, tzinfo=UTC))

    assert antes < depois


def test_run_exige_fuso():
    # Mesma exigência de `Decision.quando`, e pelo mesmo motivo: horário
    # ingênuo não é um instante.
    with pytest.raises(ValueError, match="fuso"):
        Run(
            id="1",
            workflow_id="w",
            workflow_version="v",
            state=RunState.CONCLUIDO,
            started_at=datetime(2026, 9, 16, 10, 0, 0),
            input_ref="",
        )


def test_duracao_e_none_enquanto_nao_terminou():
    agora = datetime.now(UTC)
    r = Run(
        id="1",
        workflow_id="w",
        workflow_version="v",
        state=RunState.EXECUTANDO,
        started_at=agora,
        input_ref="",
    )
    assert r.duration_ms is None

    from dataclasses import replace

    assert replace(r, finished_at=agora + timedelta(seconds=2)).duration_ms == 2000


# --------------------------------------------------------------------------
# estado
# --------------------------------------------------------------------------


def test_sobrou_item_e_ha_degrau_humano_entao_o_run_espera_alguem():
    """`AGUARDANDO_HUMANO` é o estado que já existia DE FATO e não de nome.

    Antes do PR #7 ele era "sobraram itens e a cascata tem um RevisorHumano" —
    uma condição que ninguém podia consultar. Nomeá-la é o pré-requisito de
    `resume()`.
    """
    run = execute(_wf(_Resolve([]), _Resolve([], CostClass.HUMANO, "h")), _pool("a"))

    assert run.state is RunState.AGUARDANDO_HUMANO


def test_sem_degrau_humano_o_run_conclui_mesmo_com_item_sobrando():
    """A lacuna não é um estado de espera quando não há quem decida.

    É o caso de `domains/swe` sem revisor: sobrou, mas não há humano na
    cascata, então o run terminou — a lacuna fica declarada, não pendurada.
    """
    run = execute(_wf(_Resolve([])), _pool("a"))

    assert run.state is RunState.CONCLUIDO
    assert len(run.unresolved.items) == 1


def test_tudo_resolvido_conclui_mesmo_com_degrau_humano():
    run = execute(_wf(_Resolve(["a"]), _Resolve([], CostClass.HUMANO, "h")), _pool("a"))

    assert run.state is RunState.CONCLUIDO
    assert run.unresolved.items == ()


# --------------------------------------------------------------------------
# eventos
# --------------------------------------------------------------------------


def test_o_barramento_ve_o_ciclo_inteiro_em_ordem():
    vistos: list[EventKind] = []
    bus = EventBus()
    bus.subscribe(None, lambda e: vistos.append(e.kind))

    execute(_wf(_Resolve(["a"])), _pool("a", "b"), bus=bus)

    assert vistos[0] is EventKind.RUN_INICIADO
    assert vistos[-1] is EventKind.RUN_CONCLUIDO
    assert EventKind.ITEM_RESOLVIDO in vistos


def test_assinante_que_levanta_nao_derruba_a_execucao(capsys):
    """Observação não pode custar um fechamento.

    A captura larga aqui é o requisito — inversão exata da captura estreita em
    volta de `client.complete()`, e a mesma distinção que `Investigator` já
    documenta entre o laço e a execução de ferramenta. O preço é que um bug de
    assinante fica quieto; por isso ele vai para stderr.
    """
    bus = EventBus()

    def explode(_):
        raise RuntimeError("bug do assinante")

    bus.subscribe(EventKind.RUN_INICIADO, explode)

    run = execute(_wf(_Resolve(["a"])), _pool("a"), bus=bus)

    assert run.state is RunState.CONCLUIDO
    assert "bug do assinante" in capsys.readouterr().err


def test_null_bus_nao_emite_nada_e_e_o_default():
    vistos = []
    bus = NullBus()
    bus.subscribe(None, vistos.append)

    bus.emit(Event(kind=EventKind.ERRO, run_id="x", at=datetime.now(UTC)))

    assert vistos == []


def test_desligar_o_barramento_nao_muda_o_resultado():
    """Observabilidade é ortogonal ao resultado. Se não fosse, o golden
    dependeria de quem está assinando."""
    com = execute(_wf(_Resolve(["a"])), _pool("a", "b"), bus=EventBus(), run_id="fixo")
    sem = execute(_wf(_Resolve(["a"])), _pool("a", "b"), run_id="fixo")

    assert com.resolutions == sem.resolutions
    assert com.unresolved == sem.unresolved
    assert com.state is sem.state


# --------------------------------------------------------------------------
# versão da definição
# --------------------------------------------------------------------------


def test_versao_e_estavel_e_muda_com_a_forma_da_cascata():
    a = _wf(_Resolve([], name="x"))
    b = _wf(_Resolve([], name="x"))
    c = _wf(_Resolve([], name="x"), _Resolve([], CostClass.HUMANO, "h"))

    assert a.version == b.version
    assert a.version != c.version


def test_versao_NAO_muda_com_parametro_de_resolver():
    """Limite conhecido e declarado, não defeito escondido.

    A versão é a FORMA da cascata: id, stage, nome e classe de cada resolver.
    O kernel não tem como introspectar parâmetro de resolver genericamente, e
    fechar isso exige `Resolver.version` — PR #11, a mesma peça de que a chave
    de idempotência precisa.

    Este teste existe para que o limite seja uma decisão registrada em vez de
    uma surpresa no dia em que alguém comparar dois benchmarks que só diferem
    num parâmetro.
    """

    class _ComParametro(_Resolve):
        def __init__(self, tolerancia):
            super().__init__([], name="p")
            self.tolerancia = tolerancia

    assert _wf(_ComParametro(5)).version == _wf(_ComParametro(20)).version
