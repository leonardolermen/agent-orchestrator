"""O teste de generalidade: a abstração serve a mais de um domínio?

Este arquivo é o substituto de engenharia para a regra dos três usos, que o
dono do projeto suspendeu em 2026-09-16 (§1.3 do spec de migração). A regra
existia porque abstração desenhada a partir de uma instância costuma estar
errada — e isso continua verdade independentemente de quem decide.

O substituto barato não é esperar três clientes: é escrever as outras duas
instâncias como esqueletos executáveis ENQUANTO o kernel ainda está mole. Cada
atrito que elas encontram vira uma correção de um dia em vez de uma descoberta
de um mês.

**Já funcionou.** Escrever estes dois domínios achou dois defeitos que nenhuma
análise prévia tinha visto:

  1. `Proposal.tipo` era `DivergenceType` — a taxonomia de conciliação dentro
     do tipo que todo resolver de classe paga devolve. Um domínio novo não
     conseguia propor nada.
  2. `Proposal.divergence_id` — "divergência" é vocabulário de conciliação. Um
     pedido de compra não é uma divergência.

Os dois foram achados na PRIMEIRA linha de código de domínio, não por leitura.

**O quarto domínio, `redacao` (Task 8), achou um terceiro — não no kernel de
execução, na camada de catálogo:**

  3. `Dominio`/`AgenteDeclarado`, em `agent/declarado.py`, só sabe descrever
     um resolver que JULGA um item e devolve `Proposal`/`Resolution` sobre
     ELE MESMO. `redacao` é `Tarefa` (Task 7): cada degrau TRANSFORMA o item
     num item de outro `kind`, para o próximo degrau consumir. Não existe
     campo em `AgenteDeclarado` para "que `kind` isto produz" — e sem ele,
     catalogar `redacao` em `domains/registro.py` exigiria mentir sobre o
     que o domínio faz (declará-lo como `AgenteDeclarado` que nunca
     transforma nada) ou registrá-lo vazio (sem regra nem agente, o que
     `test_os_TRES_dominios_se_declaram` — fixo em três, sem editar —
     corretamente recusa como item de catálogo sem conteúdo). `redacao` roda
     de verdade (`domains/redacao/workflow.py`, três testes verdes) e
     simplesmente NÃO entra em `DOMINIOS`; a nota em
     `domains/registro.py` explica por quê. O kernel de execução (Tasks
     1–7) não teve nenhum atrito — a `Tarefa`, o `Stage.consome/produz` e a
     `entrega` bastaram sem alteração nenhuma. O atrito é uma camada acima:
     o catálogo declarativo ainda descreve só a metade JULGA do mundo, não a
     metade TRANSFORMA. Dos dois itens que o plano de execução-como-grafo
     reservava para depois deste domínio existir, o X7 — `consome` declarado,
     derivado por `consome_de` e recusado na borda de `/runs` — está FECHADO;
     o X8 — `AgenteDeclarado` declarar o `kind` que PRODUZ — continua aberto,
     e é dele que este atrito fala. Este achado é a confirmação de que a
     reserva estava certa, não uma surpresa.
"""

from orchestrator.domains.procurement.workflow import (
    BuscadorDeFornecedor,
    ComprasAnteriores,
    Fornecedor,
    FornecedorPreferido,
    Requisicao,
)
from orchestrator.domains.procurement.workflow import definition as def_procurement
from orchestrator.domains.procurement.workflow import pool as pool_procurement
from orchestrator.domains.swe.workflow import Issue
from orchestrator.domains.swe.workflow import definition as def_swe
from orchestrator.domains.swe.workflow import pool as pool_swe
from orchestrator.kernel.cost import CostClass
from orchestrator.runtime.engine import execute


def _mercado():
    reqs = [
        Requisicao("r1", "papel", 10),
        Requisicao("r2", "toner", 2),
        Requisicao("r3", "drone", 1),
    ]
    forns = [
        Fornecedor("f1", "Papelaria", frozenset({"papel"}), preferido=True),
        Fornecedor("f2", "InfoSupri", frozenset({"toner"})),
        Fornecedor("f3", "Generica", frozenset({"papel"})),
    ]
    return reqs, forns


# ---------------------------------------------------------------------------
# Procurement: cascata completa, cardinalidade e vocabulário diferentes
# ---------------------------------------------------------------------------


def test_procurement_roda_a_cascata_inteira_do_barato_ao_caro():
    reqs, forns = _mercado()

    r = execute(def_procurement(), pool_procurement(reqs, forns))

    # As duas regras resolveram o que sabiam, de graça.
    assert {x.produced_by for x in r.resolutions} == {"preferido", "anteriores"}
    # O agente só propôs para o que sobrou, e proposta NÃO resolve.
    assert [p.item_id for p in r.proposals] == ["r3"]
    assert "r3" in r.unresolved.ids()


def test_procurement_a_decisao_humana_fecha_o_que_a_regra_nao_fechou():
    reqs, forns = _mercado()

    r = execute(def_procurement(aprovacoes={"r3": "f3"}), pool_procurement(reqs, forns))

    assert r.unresolved.items == ()
    assert any(x.produced_by == "comprador" for x in r.resolutions)


def test_procurement_decisao_obsoleta_vira_silencio_nao_erro():
    """Mesma política que `RevisorHumano` aplica na conciliação, num resolver
    que não tem nada a ver com ela."""
    reqs, forns = _mercado()

    r = execute(
        def_procurement(aprovacoes={"r1": "f1", "nao-existe": "f3"}),
        pool_procurement(reqs, forns),
    )

    assert all(x.produced_by != "comprador" for x in r.resolutions)


def test_procurement_o_agente_nunca_devolve_resolucao():
    """A invariante nº 1 do §1.5, verificada fora da conciliação.

    Se ela só valesse para o `Investigator`, seria disciplina daquele arquivo.
    Vale porque `ResolverOutput` tem dois campos separados.
    """
    reqs, forns = _mercado()
    saida = BuscadorDeFornecedor().resolve(pool_procurement(reqs, forns))

    assert saida.resolutions == []
    assert saida.proposals


def test_procurement_ordem_de_custo_vale_fora_da_conciliacao():
    cascata = def_procurement().stages[0].ordered()
    assert [r.cost_class for r in cascata] == sorted(r.cost_class for r in cascata)
    assert cascata[0].cost_class is CostClass.REGRA
    assert cascata[-1].cost_class is CostClass.HUMANO


def test_procurement_regra_barata_roda_antes_da_generica():
    """`sorted` é estável: dentro de uma classe, vence a ordem que o autor
    escreveu. `preferido` e `anteriores` são ambos REGRA, e `preferido` tem de
    ficar com o fornecedor preferido."""
    reqs, forns = _mercado()
    work = pool_procurement(reqs, forns)

    preferido = FornecedorPreferido().resolve(work).resolutions
    restante = work.without(preferido)
    anteriores = ComprasAnteriores().resolve(restante).resolutions

    assert [sorted(x.item_ids) for x in preferido] == [["f1", "r1"]]
    assert all("f1" not in x.item_ids for x in anteriores)


# ---------------------------------------------------------------------------
# Software Eng: o CASO DEGENERADO — cascata sem nenhum resolver de classe REGRA
# ---------------------------------------------------------------------------


def test_swe_cascata_sem_nenhuma_regra_barata_roda():
    """O teste mais duro da abstração.

    Se o kernel só soubesse expressar cascatas que começam com regra, ele não
    seria genérico — seria a conciliação com nomes trocados. O spec de
    composição §1.3 chama este de "o caso degenerado", e diz que o fato de ele
    caber sem forçar é o teste de generalidade.
    """
    issues = [Issue("i1", "Erro ao salvar", "..."), Issue("i2", "Export", "...")]

    r = execute(def_swe(), pool_swe(issues))

    assert [p.tipo for p in r.proposals] == ["BUG", "FEATURE"]
    # tupla, não lista: `Run` é imutável de verdade (PR #7).
    assert r.resolutions == ()
    # Nada resolveu, então tudo continua pendente. Não é falha: é a LACUNA,
    # declarada em vez de escondida.
    assert len(r.unresolved.items) == 2


def test_swe_nao_produz_a_chave_REGRA_em_resolutions_by_class():
    """A guarda que `metrics` documenta e que nunca tinha sido exercida.

    O comentário em `metrics.evaluate` diz que o default de `de_regra` é `[]` e
    não `result.matches` porque "uma cascata sem resolver REGRA nenhum
    legitimamente não tem match determinístico algum". Até este domínio existir,
    nenhum caso real produzia essa situação — a guarda estava correta e não
    testada.
    """
    r = execute(def_swe(), pool_swe([Issue("i1", "Erro", "...")]))

    assert CostClass.REGRA not in r.resolutions_by_class


def test_swe_um_kind_so_e_suficiente():
    """A assimetria da conciliação (dois lados) é do domínio, não do kernel."""
    work = pool_swe([Issue("i1", "x", "y")])

    assert {i.kind for i in work.items} == {"issue"}
    assert work.of_kind("issue")


# ---------------------------------------------------------------------------
# M2: um agente DECLARADO num domínio que não é conciliação
# ---------------------------------------------------------------------------


def test_swe_declara_um_agente_de_verdade_sem_escrever_um_laco():
    """A prova do M2, do outro lado da extração.

    `test_investigator.py` prova que o laço genérico não perdeu nada (714
    linhas passando contra `Agent`). Este prova o inverso: declarar um agente
    NOVO, num domínio que não é conciliação, custa uma `AgentSpec`, um
    `ToolRegistry` e três funções — nenhuma linha de laço.

    Se isto exigisse mais, a extração teria falhado.
    """
    from orchestrator.agent.llm import FakeLLMClient, LLMResponse
    from orchestrator.domains.swe.workflow import definition_com_agente
    from orchestrator.kernel.cost import Cost

    resposta = LLMResponse(
        text='{"tipo":"BUG","explicacao":"stack trace","evidencia":["linha 3"],'
        '"confianca":"ALTA"}',
        tool_calls=[],
        cost=Cost(input_tokens=50, output_tokens=20, calls=1),
    )
    cliente = FakeLLMClient([resposta])

    run = execute(
        definition_com_agente(cliente),
        pool_swe([Issue("i1", "Erro ao salvar", "Traceback...")]),
    )

    p = run.proposals[0]
    assert (p.item_id, p.tipo, p.confianca.value) == ("i1", "BUG", "ALTA")
    # O custo é contabilizado pelo mesmo mecanismo da conciliação.
    assert run.cost_by_resolver["triador-llm"].microcents("claude-opus-5") > 0


def test_o_agente_do_swe_rebaixa_confianca_ALTA_sem_evidencia():
    """A disciplina não é do `Investigator` — é do parser de cada domínio, e o
    swe a repete porque ela é certa, não porque foi herdada.

    Afirmar com confiança sem citar nada acontece. Rebaixar é mais útil que
    descartar: a hipótese ainda ajuda, com o peso certo.
    """
    from orchestrator.agent.llm import FakeLLMClient, LLMResponse
    from orchestrator.domains.swe.workflow import definition_com_agente
    from orchestrator.kernel.cost import Cost

    resposta = LLMResponse(
        text='{"tipo":"FEATURE","explicacao":"acho","evidencia":[],"confianca":"ALTA"}',
        tool_calls=[],
        cost=Cost(input_tokens=10, output_tokens=5, calls=1),
    )

    run = execute(
        definition_com_agente(FakeLLMClient([resposta])),
        pool_swe([Issue("i1", "Export", "...")]),
    )

    assert run.proposals[0].confianca.value == "BAIXA"


def test_tipo_fora_do_vocabulario_dispara_retry_e_acaba_em_abstencao():
    """Vocabulário fechado, como na conciliação — e o "não sei" é do DOMÍNIO
    (`NAO_SEI` aqui, `NAO_IDENTIFICADO` lá). O kernel não decide qual.

    Era `DUVIDA` até 2026-09-16 e estava errado: `DUVIDA` também é um TIPO
    legítimo ("esta issue é uma pergunta"), então uma classificação correta
    como DUVIDA era contada como abstenção. Num conjunto de 50 casos com 16
    dúvidas, um terço não era pontuado.

    A invariante agora é verificada em `evaluation.metrics.medir`, que levanta
    quando um rótulo de abstenção é também tipo esperado no conjunto.
    """
    from orchestrator.agent.llm import FakeLLMClient, LLMResponse
    from orchestrator.domains.swe.workflow import definition_com_agente
    from orchestrator.kernel.cost import Cost

    lixo = LLMResponse(
        text='{"tipo":"INVENTADO","explicacao":"x","evidencia":[],"confianca":"BAIXA"}',
        tool_calls=[],
        cost=Cost(input_tokens=10, output_tokens=5, calls=1),
    )

    run = execute(
        definition_com_agente(FakeLLMClient([lixo, lixo, lixo])),
        pool_swe([Issue("i1", "x", "y")]),
    )

    assert run.proposals[0].tipo == "NAO_SEI"
    # E `DUVIDA` continua sendo um tipo que o agente PODE responder.
    from orchestrator.domains.swe.workflow import TIPOS

    assert "DUVIDA" in TIPOS and "NAO_SEI" in TIPOS
