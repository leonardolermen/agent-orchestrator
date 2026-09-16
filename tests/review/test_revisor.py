from datetime import UTC, datetime

from orchestrator.kernel.cost import CostClass
from orchestrator.review.decision import Decision, Veredito
from orchestrator.review.fila import Fila
from orchestrator.review.revisor import RevisorHumano
from orchestrator.synth.generator import generate_clean_pairs
from orchestrator.taxonomy import DivergenceType
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


def test_decisao_com_um_id_valido_e_outro_fantasma_e_ignorada_por_inteiro():
    # `test_decisao_com_id_fora_do_pool_e_ignorada` não distingue "pular a
    # decisão inteira" de "aplicar só a parte válida": ali o lado contábil já
    # fica vazio nos dois casos, e `MatchResult` rejeitaria o match de
    # qualquer forma. Aqui o conciliar_com tem um id válido (id_contabil) e um
    # fantasma — se o revisor aplicasse parcialmente, os dois lados ficariam
    # não vazios e um match sairia mesmo assim, vinculando um id que ninguém
    # decidiu conciliar sozinho.
    work, id_banco, id_contabil = _work()
    fila = Fila.vazia()
    fila.gravar_decisao(_decisao(f"d-b-{id_banco}", {id_contabil, "l-fantasma"}))

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


def test_decisao_sobre_d_l_vira_match_com_os_ids_classificados_pelo_pool():
    # Toda decisão em `test_aceitar_...` decide em cima de `d-b-<id banco>`.
    # O lado contábil nunca foi exercitado como a divergência EM SI — só como
    # id de `conciliar_com` do lado bancário. Uma decisão sobre `d-l-<id>`
    # citando o id bancário em `conciliar_com` é o mesmo caminho de código
    # pelo lado oposto, e é onde os dois lados se encontram.
    work, id_banco, id_contabil = _work()
    fila = Fila.vazia()
    fila.gravar_decisao(_decisao(f"d-l-{id_contabil}", {id_banco}))

    saida = RevisorHumano(fila=fila).resolve(work)

    assert len(saida.matches) == 1
    m = saida.matches[0]
    assert m.bank_ids == frozenset({id_banco})
    assert m.ledger_ids == frozenset({id_contabil})


def test_duas_decisoes_sobre_o_mesmo_par_emitem_um_unico_match():
    # O fantasma do §3.5 do spec: uma divergência real chega ao agente
    # partida em `d-b-<id banco>` e `d-l-<id contábil>`. Se o operador aceita
    # as duas na mesma leva, `work` não encolheu entre as duas decisões — só
    # encolhe entre passagens, via `WorkSet.without()`, depois que `resolve()`
    # já retornou. Sem um `consumidos` local ao laço (o `usados` de
    # `ExactMatcher._casar` aplicado aqui), as duas decisões carimbam o mesmo
    # par e o motor conta o dinheiro duas vezes.
    work, id_banco, id_contabil = _work()
    fila = Fila.vazia()
    fila.gravar_decisao(_decisao(f"d-b-{id_banco}", {id_contabil}))
    fila.gravar_decisao(_decisao(f"d-l-{id_contabil}", {id_banco}))

    saida = RevisorHumano(fila=fila).resolve(work)

    assert len(saida.matches) == 1
    m = saida.matches[0]
    assert m.bank_ids == frozenset({id_banco})
    assert m.ledger_ids == frozenset({id_contabil})


def test_o_resolver_nao_custa_nada():
    # Trabalho humano custa, mas não em tokens. `Cost.zero()` aqui significa
    # "esta cascata não gastou API", que é a única coisa que Cost mede.
    work, id_banco, id_contabil = _work()
    fila = Fila.vazia()
    fila.gravar_decisao(_decisao(f"d-b-{id_banco}", {id_contabil}))

    assert RevisorHumano(fila=fila).resolve(work).cost.calls == 0
