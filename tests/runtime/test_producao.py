"""O pool que transforma: um stage vê o que o anterior produziu.

Nenhum teste aqui menciona conciliação, e é o ponto — a mesma disciplina de
`tests/kernel/test_work.py`.
"""

import pytest

from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.definition import Stage, WorkflowDefinition
from orchestrator.kernel.resolution import Resolution
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.run import RunState
from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.runtime.engine import execute


class Transformador:
    """Consome todo item de um kind e produz um de outro. Resolver de teste."""

    cost_class = CostClass.REGRA

    def __init__(self, name: str, de: str, para: str) -> None:
        self.name = name
        self._de = de
        self._para = para

    def describe(self) -> ResolverDescription:
        return ResolverDescription(self.name, self.cost_class, "teste")

    def resolve(self, work: WorkSet) -> ResolverOutput:
        resolucoes, produzidos = [], []
        for item in work.of_kind(self._de):
            resolucoes.append(
                Resolution(
                    item_ids=frozenset({item.id}),
                    produced_by=self.name,
                    rule="transformou",
                )
            )
            produzidos.append(
                WorkItem(
                    id=f"{item.id}+{self._para}",
                    kind=self._para,
                    payload=f"{item.payload}/{self.name}",
                    origem=self.name,
                )
            )
        return ResolverOutput(
            resolutions=resolucoes, produced=tuple(produzidos), cost=Cost.zero()
        )


def test_produced_default_e_vazio():
    """Todo resolver de hoje devolve `ResolverOutput` sem `produced`. O default
    é o que mantém os 844 testes intocados."""
    assert ResolverOutput().produced == ()


def test_o_stage_seguinte_ve_o_que_o_anterior_produziu():
    """A asserção que não passava antes desta fatia: encadeamento por DADO.

    Sem `produced`, o stage 2 receberia só o que o stage 1 não resolveu — e o
    stage 1 resolveu tudo. O pipeline inteiro devolveria pool vazio.
    """
    d = WorkflowDefinition(
        id="pipeline",
        name="dois passos",
        stages=(
            Stage(
                name="um",
                cascade=(Transformador("um", "a", "b"),),
                produz=frozenset({"b"}),
            ),
            Stage(
                name="dois",
                cascade=(Transformador("dois", "b", "c"),),
                produz=frozenset({"c"}),
            ),
        ),
        # Só "c" é terminal. "b" NÃO entra aqui: ele é intermediário, e
        # declará-lo em `entrega` — como esta definição precisava fazer antes
        # da correção da guarda — era escrever uma mentira no objeto para
        # conseguir construí-lo.
        entrega=frozenset({"c"}),
    )
    pool = WorkSet(items=(WorkItem(id="i", kind="a", payload="x"),))

    r = execute(d, pool)

    # O item atravessou os dois degraus: a -> b -> c.
    assert [i.kind for i in r.unresolved.items] == ["c"]
    assert r.unresolved.items[0].payload == "x/um/dois"
    # Proveniência preservada em cada salto.
    assert r.unresolved.items[0].origem == "dois"
    # Duas resoluções: cada transformação CONSOME o item que leu.
    assert len(r.resolutions) == 2


def test_producao_nao_apaga_a_resolucao_que_a_acompanha():
    """Transformar É resolver: o item lido sai do pool pela porta de sempre."""
    d = WorkflowDefinition(
        id="um",
        name="um passo",
        stages=(
            Stage(
                name="um",
                cascade=(Transformador("um", "a", "b"),),
                produz=frozenset({"b"}),
            ),
        ),
        # "b" é o fim de linha deste pipeline de um único stage.
        entrega=frozenset({"b"}),
    )
    pool = WorkSet(items=(WorkItem(id="i", kind="a", payload="x"),))

    r = execute(d, pool)

    assert "i" not in r.unresolved.ids()
    assert r.resolutions[0].item_ids == frozenset({"i"})


def test_o_stage_so_ve_os_kinds_que_declara_consumir():
    """`consome` é o que separa dois caminhos num pool heterogêneo."""
    d = WorkflowDefinition(
        id="dois-caminhos",
        name="dois caminhos",
        stages=(
            Stage(
                name="cuida do a",
                cascade=(Transformador("ta", "a", "z"),),
                consome=frozenset({"a"}),
                produz=frozenset({"z"}),
            ),
        ),
        # "z" é o fim de linha: nenhum outro stage o consome.
        entrega=frozenset({"z"}),
    )
    pool = WorkSet(
        items=(
            WorkItem(id="i1", kind="a", payload="x"),
            WorkItem(id="i2", kind="b", payload="y"),
        )
    )

    r = execute(d, pool)

    # O item de kind "b" nunca foi oferecido ao stage, e continua intacto.
    assert {i.id for i in r.unresolved.items} == {"i1+z", "i2"}


def test_o_stage_sem_item_do_seu_kind_nao_roda():
    """A CONDICIONAL do kernel: ausência de item, nunca um predicado.

    É isto que dá ramificação sem o kernel ganhar linguagem de expressão — e
    é por isso que a §10 do spec pode dizer "não vira n8n" e ser verdade.
    """
    d = WorkflowDefinition(
        id="ramo-morto",
        name="ramo morto",
        stages=(
            Stage(
                name="urgente",
                cascade=(Transformador("u", "urgente", "z"),),
                consome=frozenset({"urgente"}),
                produz=frozenset({"z"}),
            ),
        ),
        # "z" é o fim de linha: nenhum outro stage o consome.
        entrega=frozenset({"z"}),
    )
    pool = WorkSet(items=(WorkItem(id="i", kind="normal", payload="x"),))

    r = execute(d, pool)

    assert r.resolutions == ()
    # O resolver não rodou: não há custo registrado para ele.
    assert "u" not in r.cost_by_resolver
    assert [i.id for i in r.unresolved.items] == ["i"]


def test_consome_vazio_continua_vendo_o_pool_inteiro():
    """O default reproduz a semântica de hoje. É o que mantém as 9 definições
    existentes e os 844 testes sem edição."""
    d = WorkflowDefinition(
        id="tudo",
        name="tudo",
        stages=(
            Stage(
                name="um",
                cascade=(Transformador("um", "a", "b"),),
                # `consome` FICA vazio de propósito — é o que este teste
                # prova. `produz` continua declarado porque a guarda de
                # RUNTIME (`produziu kind não declarado`) é incondicional, ao
                # contrário da de construção.
                produz=frozenset({"b"}),
            ),
        ),
        # "b" é o fim de linha deste pipeline de um único stage.
        entrega=frozenset({"b"}),
    )
    pool = WorkSet(
        items=(
            WorkItem(id="i1", kind="a", payload="x"),
            WorkItem(id="i2", kind="a", payload="y"),
        )
    )

    r = execute(d, pool)

    assert len(r.resolutions) == 2


def test_produzir_kind_nao_declarado_e_erro_alto():
    """`produz` DECLARADO só vale se o runtime o impuser.

    Sem esta guarda, `produz` seria documentação — e documentação que o
    runtime não impõe desatualiza em silêncio, levando a recusa de beco sem
    saída (Task 4) e as arestas do canvas a mentirem juntas.
    """
    d = WorkflowDefinition(
        id="mentiroso",
        name="mentiroso",
        stages=(
            Stage(
                name="um",
                cascade=(Transformador("um", "a", "b"),),
                consome=frozenset({"a"}),
                produz=frozenset({"outro"}),  # promete "outro", entrega "b"
            ),
        ),
        # "outro" é o que a definição PROMETE entregar — a guarda de beco sem
        # saída olha só a promessa, na construção. Só em runtime o resolver
        # trai a promessa, que é o que este teste verifica.
        entrega=frozenset({"outro"}),
    )
    pool = WorkSet(items=(WorkItem(id="i", kind="a", payload="x"),))

    with pytest.raises(ValueError, match="produziu kind não declarado"):
        execute(d, pool)


def test_a_guarda_nao_exige_humano():
    """LIMITAÇÃO DOCUMENTADA, não acidente — e por isso ela tem um teste.

    Este grafo passa por `WorkflowDefinition.__post_init__` sem reclamar: "z"
    está em `entrega`, logo nenhum kind fica órfão. Não há um único resolver de
    classe `HUMANO` na cascata. O run termina `CONCLUIDO`, e o que ele entrega
    é a saída de um resolver, sem ninguém conferindo.

    O que a guarda de beco sem saída compra é reachability ESTÁTICA no grafo de
    kinds: ela pega o kind digitado errado e o esquecido, e obriga o autor a
    declarar que um kind é terminal. O que ela NÃO compra — e o docstring de
    `agent/tarefa.py` chegou a afirmar que sim — é humano em lugar nenhum.
    `domains/redacao` tem exatamente esta forma.

    Se um dia alguém exigir humano no fim, este teste é o que vai QUEBRAR, e é
    para isso que ele existe: o próximo leitor encontra a limitação como fato
    fixado pela suíte, não como surpresa em produção.
    """
    d = WorkflowDefinition(
        id="sem-humano",
        name="sem humano",
        stages=(
            Stage(
                name="unico",
                cascade=(Transformador("modelo", "a", "z"),),
                consome=frozenset({"a"}),
                produz=frozenset({"z"}),
            ),
        ),
        entrega=frozenset({"z"}),
    )
    pool = WorkSet(items=(WorkItem(id="i", kind="a", payload="x"),))

    r = execute(d, pool)

    assert r.state is RunState.CONCLUIDO
    assert not any(
        res.cost_class >= CostClass.HUMANO for s in d.stages for res in s.cascade
    )
    # O veredito do resolver É a entrega do run. Nada o conferiu.
    assert [i.kind for i in r.unresolved.items] == ["z"]


def test_stages_nao_sao_reordenados_por_custo():
    """Os DOIS EIXOS, e a §5.1 do spec vira asserção aqui.

    Dentro de um stage a ordem é CUSTO — quem tenta primeiro no mesmo
    trabalho. Entre stages a ordem é DADO — quem precisa da saída de quem.
    Ordenar por custo entre stages seria escrever antes de pesquisar.

    O teste monta um pipeline em que o segundo degrau é MAIS BARATO que o
    primeiro. Se alguém algum dia aplicar `ordered()` globalmente, o barato
    rodaria antes, não acharia item do seu kind, e o pipeline devolveria o
    item parado no meio.
    """

    class Caro(Transformador):
        cost_class = CostClass.AGENTE

    d = WorkflowDefinition(
        id="ordem",
        name="ordem",
        stages=(
            Stage(
                name="caro primeiro",
                cascade=(Caro("caro", "a", "b"),),
                consome=frozenset({"a"}),
                produz=frozenset({"b"}),
            ),
            Stage(
                name="barato depois",
                cascade=(Transformador("barato", "b", "c"),),  # REGRA, mais barato
                consome=frozenset({"b"}),
                produz=frozenset({"c"}),
            ),
        ),
        # "c" é o fim de linha: nenhum outro stage o consome.
        entrega=frozenset({"c"}),
    )
    pool = WorkSet(items=(WorkItem(id="i", kind="a", payload="x"),))

    r = execute(d, pool)

    assert [i.kind for i in r.unresolved.items] == ["c"]
