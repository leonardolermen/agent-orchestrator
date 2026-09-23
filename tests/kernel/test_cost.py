"""A ordem entre classes de custo — o mecanismo, não a convenção."""

from orchestrator.kernel.cost import Cost, CostClass, modelo_precificado


def test_ordem_das_classes_e_regra_agente_crew_humano():
    """A ordem é o produto, não um detalhe.

    É ela que impede um agente de rodar antes de uma regra, e `Stage.ordered()`
    ordena por ESTE valor. A asserção é sobre a ordem RELATIVA, nunca sobre os
    números: renumerar é permitido, inverter não.
    """
    assert CostClass.REGRA < CostClass.AGENTE < CostClass.CREW < CostClass.HUMANO


def test_crew_fica_entre_agente_e_humano():
    # Uma tripulação é mais cara que um agente (N laços em vez de um) e mais
    # barata que interromper uma pessoa. Ainda não há produtor de CREW; a
    # posição entra agora porque acrescentar membro no MEIO de uma enum cujo
    # valor É a semântica renumera HUMANO, e renumerar depois custa mais.
    assert CostClass.AGENTE < CostClass.CREW < CostClass.HUMANO


def test_soma_de_custo_preserva_os_cinco_campos():
    a = Cost(input_tokens=1, output_tokens=2, cached_tokens=3, cache_creation_tokens=4, calls=1)
    total = a + a
    assert (total.input_tokens, total.output_tokens) == (2, 4)
    assert (total.cached_tokens, total.cache_creation_tokens, total.calls) == (6, 8, 2)


def test_modelo_sem_preco_levanta_em_vez_de_devolver_zero():
    # Custo incalculável não pode passar por custo zero: a métrica de custo por
    # item é o número comercial deste produto.
    assert modelo_precificado("claude-opus-5")
    assert not modelo_precificado("modelo-inventado")


def test_a_lista_de_modelos_precificados_e_publica():
    """A tela e o chat precisam OFERECER exatamente o que o servidor aceita.

    Sem uma fronteira pública, cada um faria a própria lista — e a que
    divergisse ofereceria um modelo que `Cost.microcents` recusa, o que só
    aparece quando alguém tenta rodar. `modelo_precificado` já é essa fronteira
    para UM nome; faltava a lista.
    """
    from orchestrator.kernel.cost import modelo_precificado, modelos_precificados

    nomes = modelos_precificados()

    assert nomes == sorted(nomes), "ordenada: a tela mostra nesta ordem"
    assert all(modelo_precificado(n) for n in nomes)
    assert "claude-haiku-4-5" in nomes
