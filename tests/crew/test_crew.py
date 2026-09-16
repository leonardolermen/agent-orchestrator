"""A tripulação: um resolver, e as invariantes que ela não pode furar."""

import json

import pytest

from orchestrator.agent.agent import Agent, AgentSpec, AgentTask
from orchestrator.agent.llm import LLMResponse
from orchestrator.agent.tools.registry import ToolRegistry
from orchestrator.crew import Conflito, Crew, Process
from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.resolution import Confidence, Proposal
from orchestrator.kernel.work import WorkItem, WorkSet

MODELO = "claude-haiku-4-5"
ABSTEM = frozenset({"NAO_SEI"})


class _Modelo:
    """Responde sempre o mesmo tipo. `vistos` guarda os prompts recebidos."""

    model = MODELO

    def __init__(self, tipo: str, confianca: str = "MEDIA") -> None:
        self.tipo = tipo
        self.confianca = confianca
        self.vistos: list[str] = []

    def complete(self, system, messages, tools):
        self.vistos.append(str(messages[0]["content"]))
        return LLMResponse(
            text=json.dumps(
                {
                    "tipo": self.tipo,
                    "explicacao": f"eu acho {self.tipo}",
                    "evidencia": [f"pista-{self.tipo}"],
                    "confianca": self.confianca,
                }
            ),
            tool_calls=[],
            cost=Cost(input_tokens=100, output_tokens=20, calls=1),
        )


def _parse(item_id, texto, cost, trace):
    d = json.loads(texto)
    return Proposal(
        item_id=item_id,
        tipo=d["tipo"],
        explicacao=d["explicacao"],
        evidencia=d["evidencia"],
        confianca=Confidence(d["confianca"]),
        acao_sugerida="revisar",
        cost=cost,
        trace=trace,
    )


def _abstain(item_id, motivo, cost=None, trace=None):
    return Proposal.abstencao(item_id, "NAO_SEI", motivo, cost, trace)


def _agente(nome: str, cliente) -> Agent:
    return Agent(
        spec=AgentSpec(
            name=nome,
            system="classifique",
            model=MODELO,
            units=lambda work: [
                AgentTask(id=i.id, prompt=f"item {i.id}") for i in work.items
            ],
            parse=_parse,
            abstain=_abstain,
            max_turns=2,
        ),
        client=cliente,
        tools=ToolRegistry([]),
    )


POOL = WorkSet(items=(WorkItem(id="w-1", kind="k", payload=None),))


def _crew(tipos, **kw) -> tuple[Crew, list[_Modelo]]:
    modelos = [_Modelo(t) for t in tipos]
    agentes = tuple(_agente(f"ag{n}", m) for n, m in enumerate(modelos, 1))
    return Crew(name="time", agents=agentes, abstem_com=ABSTEM, **kw), modelos


# -- a invariante mais cara do projeto -------------------------------------


def test_crew_devolve_PROPOSTA_e_nunca_resolucao():
    """Um Crew é mais opinião, não mais autoridade. Se um agente sozinho não
    pode resolver, três também não podem."""
    time, _ = _crew(["BUG", "BUG"])

    saida = time.resolve(POOL)

    assert saida.proposals and saida.resolutions == []


def test_a_classe_de_custo_e_CREW_e_nao_da_para_mudar():
    """`init=False`: a classe é do tipo, não configuração. Uma tripulação que
    se declarasse `REGRA` rodaria antes dos agentes baratos."""
    time, _ = _crew(["BUG", "BUG"])

    assert time.cost_class is CostClass.CREW
    with pytest.raises(TypeError):
        Crew(name="x", agents=time.agents, abstem_com=ABSTEM, cost_class=CostClass.REGRA)


# -- o quadro branco -------------------------------------------------------


def test_o_segundo_agente_LE_o_que_o_primeiro_escreveu():
    time, modelos = _crew(["BUG", "BUG"])

    time.resolve(POOL)

    assert "ag1" in modelos[1].vistos[0]
    assert "eu acho BUG" in modelos[1].vistos[0]


def test_o_PRIMEIRO_agente_recebe_a_tarefa_crua():
    """Enriquecer com um quadro vazio acrescentaria cabeçalho inútil a todo
    primeiro turno — e o primeiro turno é o que a marcação de cache protege."""
    time, modelos = _crew(["BUG", "BUG"])

    time.resolve(POOL)

    assert modelos[0].vistos[0] == "item w-1"


def test_rodada_que_nao_muda_o_quadro_PARA_o_laco():
    """O modo de falha do §10.4: N agentes concordando educadamente por seis
    turnos, cada turno pago.

    Com `max_rounds=3` o laço para em DUAS rodadas, não em três — e não em uma.
    Duas é o mínimo possível e a razão é inerente: a rodada 1 sempre muda o
    quadro (ele começa vazio), então só a rodada 2 pode mostrar que ninguém
    revisou. Detectar estabilidade custa uma rodada; é o preço de deixar
    agentes mudarem de ideia.
    """
    time, modelos = _crew(["BUG", "BUG"], max_rounds=3)

    time.resolve(POOL)

    assert [len(m.vistos) for m in modelos] == [2, 2]


# -- conflito: o default ---------------------------------------------------


def test_desacordo_vira_ABSTENCAO_com_as_duas_hipoteses():
    """Descartar as hipóteses jogaria fora a parte cara: a tripulação teria
    custado dinheiro para produzir um "não sei" igual ao de um agente só."""
    time, _ = _crew(["BUG", "FEATURE"])

    (p,) = time.resolve(POOL).proposals

    assert p.tipo == "NAO_SEI"
    assert any("BUG" in e for e in p.evidencia)
    assert any("FEATURE" in e for e in p.evidencia)


def test_concordancia_une_evidencia_e_NAO_eleva_confianca():
    """O ponto mais importante do módulo. No sequencial o agente 2 LEU a
    resposta do 1 — eles não são independentes, então concordar é em parte
    ancoragem, não corroboração."""
    modelos = [_Modelo("BUG", "MEDIA"), _Modelo("BUG", "ALTA")]
    agentes = tuple(_agente(f"ag{n}", m) for n, m in enumerate(modelos, 1))
    time = Crew(name="t", agents=agentes, abstem_com=ABSTEM)

    (p,) = time.resolve(POOL).proposals

    assert p.tipo == "BUG"
    assert p.confianca is Confidence.MEDIA  # a MENOR, não a maior
    assert len(p.evidencia) == 1  # mesma pista dos dois, unida sem repetir


def test_toda_a_tripulacao_abstendo_vira_uma_abstencao_so():
    time, _ = _crew(["NAO_SEI", "NAO_SEI"])

    (p,) = time.resolve(POOL).proposals

    assert p.tipo == "NAO_SEI"
    assert "toda a tripulação se absteve" in p.explicacao


def test_abstencao_de_um_nao_conta_como_DESACORDO():
    """Sem `abstem_com`, o Crew compararia um "não sei" com uma resposta e
    chamaria de desacordo — desperdiçando a única resposta que teve."""
    time, _ = _crew(["BUG", "NAO_SEI"])

    (p,) = time.resolve(POOL).proposals

    assert p.tipo == "BUG"


# -- conflito: maioria e síntese -------------------------------------------


def test_maioria_escolhe_o_mais_votado():
    time, _ = _crew(["BUG", "BUG", "FEATURE"], conflito=Conflito.MAIORIA)

    (p,) = time.resolve(POOL).proposals

    assert p.tipo == "BUG"


def test_maioria_EMPATADA_abstem_e_preserva_as_hipoteses():
    """Empate por maioria é abstenção com passos extras; melhor dizer o nome
    certo."""
    time, _ = _crew(["BUG", "FEATURE", "DUVIDA"], conflito=Conflito.MAIORIA)

    (p,) = time.resolve(POOL).proposals

    assert p.tipo == "NAO_SEI"
    assert len(p.evidencia) == 3


def test_maioria_com_dois_agentes_e_RECUSADA_na_construcao():
    with pytest.raises(ValueError, match="não há maioria"):
        _crew(["BUG", "FEATURE"], conflito=Conflito.MAIORIA)


def test_sintese_chama_o_sintetizador_com_o_quadro_branco():
    sint = _Modelo("BUG")
    time, _ = _crew(
        ["BUG", "FEATURE"],
        conflito=Conflito.SINTETIZAR,
        synthesizer=_agente("sintetizador", sint),
    )

    (p,) = time.resolve(POOL).proposals

    assert p.tipo == "BUG"
    assert "ag1" in sint.vistos[0] and "ag2" in sint.vistos[0]


def test_sintese_sem_sintetizador_e_RECUSADA_na_construcao():
    with pytest.raises(ValueError, match="synthesizer"):
        _crew(["BUG", "FEATURE"], conflito=Conflito.SINTETIZAR)


# -- hierárquico -----------------------------------------------------------


def test_o_gerente_ROTEIA_e_o_tipo_dele_e_descartado():
    """Sem essa restrição, "hierárquico" vira "um agente grande com ferramentas
    caras" — o modo de falha mais comum do padrão."""
    gerente = _Modelo("ag2")  # o gerente "responde" citando o especialista
    esp1, esp2 = _Modelo("BUG"), _Modelo("FEATURE")
    time = Crew(
        name="t",
        agents=(_agente("ag1", esp1), _agente("ag2", esp2)),
        abstem_com=ABSTEM,
        process=Process.HIERARCHICAL,
        manager=_agente("gerente", gerente),
    )

    (p,) = time.resolve(POOL).proposals

    assert p.tipo == "FEATURE"  # quem respondeu foi o ag2, não o gerente
    assert esp1.vistos == []  # o ag1 nem foi chamado


def test_hierarquico_sem_gerente_e_RECUSADO_na_construcao():
    time, _ = _crew(["BUG", "BUG"])
    with pytest.raises(ValueError, match="manager"):
        Crew(
            name="t",
            agents=time.agents,
            abstem_com=ABSTEM,
            process=Process.HIERARCHICAL,
        )


def test_gerente_que_nao_cita_ninguem_cai_no_primeiro_e_isso_e_EXPLICITO():
    """Casar por nome é frágil; a queda é declarada em vez de silenciosa."""
    gerente = _Modelo("sei lá")
    esp1, esp2 = _Modelo("BUG"), _Modelo("FEATURE")
    time = Crew(
        name="t",
        agents=(_agente("ag1", esp1), _agente("ag2", esp2)),
        abstem_com=ABSTEM,
        process=Process.HIERARCHICAL,
        manager=_agente("gerente", gerente),
    )

    (p,) = time.resolve(POOL).proposals

    assert p.tipo == "BUG"


# -- orçamento e custo -----------------------------------------------------


def test_o_custo_da_proposta_SOMA_todos_os_agentes():
    """Se o Crew reportasse só o custo do último, a comparação contra um
    agente sozinho no benchmark sairia a favor da tripulação por construção."""
    time, _ = _crew(["BUG", "BUG"])

    (p,) = time.resolve(POOL).proposals

    assert p.cost.calls == 2
    assert p.cost.input_tokens == 200


def test_orcamento_estourado_abstem_SEM_chamar_modelo():
    modelos = [_Modelo("BUG"), _Modelo("BUG")]
    agentes = tuple(_agente(f"ag{n}", m) for n, m in enumerate(modelos, 1))
    time = Crew(name="t", agents=agentes, abstem_com=ABSTEM, budget_microcents=1)
    pool = WorkSet(
        items=(
            WorkItem(id="w-1", kind="k", payload=None),
            WorkItem(id="w-2", kind="k", payload=None),
        )
    )

    propostas = time.resolve(pool).proposals

    assert propostas[1].tipo == "NAO_SEI"
    assert "orçamento" in propostas[1].explicacao
    # `[1, 0]`, e é o comportamento certo em DOIS níveis. O teto estourou
    # DENTRO do primeiro item, então o ag2 nem foi chamado — e a proposta do
    # item 1 saiu com a opinião do ag1 sozinho. O teto do item 2 foi checado
    # antes de qualquer chamada.
    #
    # A consequência merece estar escrita: sob orçamento apertado, uma
    # tripulação degenera em agente único SEM mudar de classe de custo. O
    # trace registra o motivo, e é por isso que ele registra.
    assert [len(m.vistos) for m in modelos] == [1, 0]


# -- as construções que o módulo recusa ------------------------------------


def test_tripulacao_VAZIA_e_recusada():
    with pytest.raises(ValueError, match="sem agente"):
        Crew(name="t", agents=(), abstem_com=ABSTEM)


def test_sequencial_com_UM_agente_e_recusado():
    """Isso é um `Agent`. Pagar `CostClass.CREW` por ele faria a cascata
    colocá-lo depois de agentes mais baratos sem motivo."""
    with pytest.raises(ValueError, match="sequencial com um agente"):
        _crew(["BUG"])


def test_agentes_que_trabalham_itens_DIFERENTES_sao_recusados():
    """O desacordo medido seria entre respostas a perguntas diferentes."""
    a1 = _agente("ag1", _Modelo("BUG"))
    a2 = _agente("ag2", _Modelo("BUG"))
    object.__setattr__(
        a2.spec, "units", lambda work: [AgentTask(id="outro", prompt="x")]
    )
    time = Crew(name="t", agents=(a1, a2), abstem_com=ABSTEM)

    with pytest.raises(ValueError, match="MESMOS itens"):
        time.resolve(POOL)


def test_o_trace_dos_AGENTES_entra_no_da_proposta():
    """Sem isto a proposta sai com o custo certo e sem os eventos que o
    produziram: a árvore mostra o Crew como caixa opaca e `waste.py` relata
    "nenhuma ferramenta foi chamada" numa execução que chamou cinco.

    Achado na PRIMEIRA execução ao vivo da tripulação, pelo relatório de
    economia — não por um teste. Este teste existe para que não volte.
    """
    from orchestrator.kernel.resolution import TraceKind

    time, _ = _crew(["BUG", "BUG"])

    (p,) = time.resolve(POOL).proposals

    llms = [e for e in p.trace if e.kind is TraceKind.LLM]
    assert len(llms) == 2, "um evento de LLM por agente"
    assert p.cost.calls == len(llms), "custo e trace contam as mesmas chamadas"


def test_o_trace_do_crew_tem_UM_marcador_de_entrada_por_item():
    """`TraceKind.ENTRADA` é o que abre um span de ITEM no coletor. Com dois
    agentes emitindo o seu mais o do Crew, o relatório de economia imprimiu
    `29/71` itens num conjunto de 50 — número impossível.

    Só apareceu porque a saída mostra o denominador. Métrica que imprimisse só
    a porcentagem teria escondido.
    """
    from orchestrator.kernel.resolution import TraceKind

    time, _ = _crew(["BUG", "BUG"])

    (p,) = time.resolve(POOL).proposals

    entradas = [e for e in p.trace if e.kind is TraceKind.ENTRADA]
    assert len(entradas) == 1
    # E os eventos que atribuem custo continuam lá.
    assert len([e for e in p.trace if e.kind is TraceKind.LLM]) == 2
