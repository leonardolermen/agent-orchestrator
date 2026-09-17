import pytest

from orchestrator.agent.llm import FakeLLMClient, LLMResponse
from orchestrator.eval.agent_eval import EvalResult, _tabela, avaliar
from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput

# Valores MEDIDOS com n=100 na semente 1. A amostra de n=40 foi descartada de
# propósito: ela dava 2 corretas de 2 arriscadas, e 2/2 é 1,0 tanto com a
# fórmula certa quanto com ela invertida — pinar contadores numa amostra que não
# distingue a fórmula é teatro.
#
# Com estes números, a fórmula invertida daria 12/6 = 2,0, fora de [0,1].
PRECISAO_ESPERADA = {"total": 12, "abstidas": 0, "corretas": 6}


def _fabrica_falsa(model: str):
    """Sempre devolve a mesma proposta, sem tocar em rede."""
    def fabrica():
        return FakeLLMClient(
            model=model,
            respostas=[
                LLMResponse(
                    text='{"tipo":"DEFASAGEM_TEMPORAL","explicacao":"atraso",'
                         '"evidencia":["b1"],"confianca":"MEDIA",'
                         '"acao_sugerida":"conciliar"}',
                    tool_calls=[],
                    cost=Cost(input_tokens=50, output_tokens=20, calls=1),
                )
            ]
            * 500
        )
    return fabrica


def test_avaliacao_devolve_resultado_completo():
    r = avaliar(model="claude-opus-5", seed=1, n=40, taxa_divergencia=0.15,
                client_factory=_fabrica_falsa("claude-opus-5"))

    assert isinstance(r, EvalResult)
    # NOTA (mantida de rounds anteriores, precisão da razão confirmada pelo
    # revisor no round 1): o brief pede `assert r.model == "fake"` aqui. Isso é
    # irrealizável sob qualquer implementação que combine com o resto do
    # próprio brief — `avaliar` monta `EvalResult(model=model)` a partir do
    # PARÂMETRO `model`, nunca de `cliente.model`; `r.model` jamais poderia
    # ser "fake" com `model="claude-opus-5"` passado explicitamente. O
    # literal "fake" é resquício de uma versão anterior de `FakeLLMClient`,
    # cujo modelo padrão foi trocado para um nome real — ver o comentário em
    # `orchestrator/agent/llm.py`. Corrigido para o valor que a própria
    # `avaliar` sempre produz. Reportado ao coordenador nos rounds 0 e 1; o
    # brief regenerado no round 2 ainda cola o literal antigo.
    assert r.model == "claude-opus-5"
    assert r.proposals_total > 0


def test_precisao_pina_os_contadores_e_o_valor():
    # Uma asserção de faixa (0 <= x <= 1) é satisfeita por qualquer
    # implementação, inclusive uma com numerador e denominador trocados. Com os
    # três contadores brutos E o valor resultante fixos, trocar a fórmula
    # quebra o teste.
    #
    # Os números abaixo são MEDIDOS nesta semente, não escolhidos: rode
    # `avaliar` e copie o que sair. Se o benchmark mudar de forma, este teste
    # falha — e esse é exatamente o momento em que alguém deveria olhar para
    # ele.
    r = avaliar(model="claude-opus-5", seed=1, n=100, taxa_divergencia=0.15,
                client_factory=_fabrica_falsa("claude-opus-5"))

    arriscadas = r.proposals_total - r.proposals_abstained
    assert r.proposals_total == PRECISAO_ESPERADA["total"]
    assert r.proposals_abstained == PRECISAO_ESPERADA["abstidas"]
    assert r.proposals_correct == PRECISAO_ESPERADA["corretas"]
    assert r.precision == PRECISAO_ESPERADA["corretas"] / arriscadas


def test_so_abstencoes_zera_a_precisao_sem_dividir_por_zero():
    # Sem este caso, o denominador `total - abstidas` nunca é exercido com
    # abstenções maiores que zero, e o ramo de denominador zero não é tocado
    # por teste nenhum. Medido: 12 propostas, todas abstenções.
    def fabrica():
        return FakeLLMClient(
            model="claude-opus-5",
            respostas=[
                LLMResponse(
                    text='{"tipo":"NAO_IDENTIFICADO","explicacao":"nao sei",'
                         '"evidencia":[],"confianca":"BAIXA",'
                         '"acao_sugerida":"investigar_manual"}',
                    tool_calls=[],
                    cost=Cost(input_tokens=50, output_tokens=20, calls=1),
                )
            ]
            * 500,
        )

    r = avaliar(model="claude-opus-5", seed=1, n=100, taxa_divergencia=0.15,
                client_factory=fabrica)

    assert r.proposals_abstained == r.proposals_total
    assert r.proposals_correct == 0
    assert r.precision == 0.0
    assert r.abstention_rate == 1.0


def test_fabrica_que_devolve_outro_modelo_e_rejeitada():
    # Pedir um modelo e medir outro produziria um relatório precificado numa
    # tabela e rotulado como outra.
    with pytest.raises(ValueError):
        avaliar(model="claude-opus-5", seed=1, n=40, taxa_divergencia=0.15,
                client_factory=_fabrica_falsa("claude-haiku-4-5"))


def test_custo_por_divergencia_e_inteiro_em_microcents():
    r = avaliar(model="claude-opus-5", seed=1, n=40, taxa_divergencia=0.15,
                client_factory=_fabrica_falsa("claude-opus-5"))

    assert isinstance(r.microcents_per_divergence, int)


def test_avaliacao_e_deterministica_para_a_mesma_semente():
    a = avaliar(model="claude-opus-5", seed=5, n=40, taxa_divergencia=0.15,
                client_factory=_fabrica_falsa("claude-opus-5"))
    b = avaliar(model="claude-opus-5", seed=5, n=40, taxa_divergencia=0.15,
                client_factory=_fabrica_falsa("claude-opus-5"))

    assert a.precision == b.precision
    assert a.proposals_total == b.proposals_total


def test_render_nomeia_o_modelo_e_a_precisao():
    saida = avaliar(model="claude-opus-5", seed=1, n=40, taxa_divergencia=0.15,
                    client_factory=_fabrica_falsa("claude-opus-5")).render()

    assert "claude-opus-5" in saida
    assert "Precisão" in saida


def test_tabela_compara_todos_os_modelos_lado_a_lado():
    # O entregável declarado é uma DECISÃO entre modelos. Blocos empilhados
    # (um `render()` por modelo) obrigam o leitor a comparar de cabeça; a
    # tabela bota as colunas que importam lado a lado.
    a = avaliar(model="claude-opus-5", seed=1, n=40, taxa_divergencia=0.15,
                client_factory=_fabrica_falsa("claude-opus-5"))
    b = avaliar(model="claude-haiku-4-5", seed=1, n=40, taxa_divergencia=0.15,
                client_factory=_fabrica_falsa("claude-haiku-4-5"))

    saida = _tabela([a, b])
    linhas = saida.splitlines()

    assert "claude-opus-5" in saida
    assert "claude-haiku-4-5" in saida
    # uma linha de modelo não pode vir antes do cabeçalho
    cabecalho = next(i for i, linha in enumerate(linhas) if "Modelo" in linha)
    linha_opus = next(i for i, linha in enumerate(linhas) if "claude-opus-5" in linha)
    assert linha_opus > cabecalho


def test_tabela_com_um_unico_modelo_nao_estoura():
    a = avaliar(model="claude-opus-5", seed=1, n=40, taxa_divergencia=0.15,
                client_factory=_fabrica_falsa("claude-opus-5"))

    assert "claude-opus-5" in _tabela([a])


class _ClienteQueFalha:
    """Cliente que sempre estoura na chamada — rede caída, 401, sem crédito."""

    model = "claude-haiku-4-5"

    def complete(self, system, messages, tools):
        raise RuntimeError("Your credit balance is too low")


def test_falha_total_de_api_nao_e_relatada_como_medicao():
    """MEDIDO em 2026-09-15: sem crédito na conta, a avaliação imprimia
    `Precisão 0.0% / Abstenção 100.0% / Custo US$ 0.0000` — indistinguível de
    um modelo que tentou e foi inútil. Zero chamada havia sido feita. Um
    operador comparando modelos concluiria que o modelo é ruim; a conclusão
    certa é que a execução não mediu nada.
    """
    r = avaliar(model="claude-haiku-4-5", seed=1, n=30, taxa_divergencia=0.15,
                client_factory=lambda: _ClienteQueFalha())

    assert r.proposals_total > 0
    assert r.proposals_api_failed == r.proposals_total
    assert r.mediu_algo is False

    saida = r.render()
    assert "FALHA DE API" in saida
    # A precisão não pode aparecer como número de medição quando nada foi medido.
    assert "0.0%" not in saida.split("FALHA DE API")[0]


def test_tabela_nao_apresenta_percentual_de_execucao_que_nao_mediu_nada():
    """A tabela é o artefato de DECISÃO entre modelos. Um modelo cuja execução
    falhou inteira aparecendo com `0.0%` ao lado de um que mediu de verdade
    convida exatamente à conclusão errada: que ele foi testado e perdeu.
    """
    ok = avaliar(model="claude-opus-5", seed=1, n=40, taxa_divergencia=0.15,
                 client_factory=_fabrica_falsa("claude-opus-5"))
    falhou = avaliar(model="claude-haiku-4-5", seed=1, n=40, taxa_divergencia=0.15,
                     client_factory=lambda: _ClienteQueFalha())

    linhas = _tabela([ok, falhou]).splitlines()
    linha_falhou = next(x for x in linhas if "claude-haiku-4-5" in x)

    assert "%" not in linha_falhou
    assert "US$" not in linha_falhou or "0.0000" not in linha_falhou
    assert "falha" in linha_falhou.lower()


def test_execucao_por_assinatura_nao_reporta_custo_como_medido():
    """Assinatura não tem preço por chamada — imprimir US$ 0,0000 seria mentira.

    É o mesmo modo de falha que esta avaliação já cometeu uma vez, relatando
    falha total de API como se fosse medição. Aqui o número não é zero, é
    inexistente, e a saída precisa dizer isso. A precisão, que É medível por
    este caminho, continua aparecendo.
    """
    r = EvalResult(
        model="assinatura",
        divergences=2,
        proposals_total=2,
        proposals_correct=1,
        proposals_abstained=0,
        total_microcents=0,
        custo_medido=False,
    )

    saida = r.render()

    assert "não medido" in saida
    assert "US$" not in saida
    assert "50.0%" in saida


class _ResolverMudo:
    """Um resolver que não resolve, não propõe e não fala com ninguém."""

    name = "investigador"
    cost_class = CostClass.AGENTE

    def resolve(self, work):
        return ResolverOutput()

    def describe(self):
        return ResolverDescription(self.name, self.cost_class, "mudo")


def test_via_assinatura_marca_o_custo_como_nao_medido():
    r = avaliar(
        model="assinatura", seed=1, n=40, taxa_divergencia=0.15,
        via="assinatura", investigator_factory=lambda contexto: _ResolverMudo(),
    )

    assert r.custo_medido is False


def test_via_api_continua_marcando_o_custo_como_medido():
    r = avaliar(
        model="claude-opus-5", seed=1, n=40, taxa_divergencia=0.15,
        client_factory=_fabrica_falsa("claude-opus-5"),
    )

    assert r.custo_medido is True


def test_main_aceita_via_assinatura_e_nao_anuncia_gasto(capsys):
    """`--n 20` não produz divergência nenhuma, então nada chama o modelo.

    O que este teste pina é o anúncio: a via paga avisa que GASTA DINHEIRO, e
    a via por assinatura não pode repetir esse aviso — nem imprimir cifra.
    """
    import pytest

    pytest.importorskip("claude_agent_sdk")
    from orchestrator.eval.agent_eval import main

    assert main(["--via", "assinatura", "--n", "20"]) == 0

    saida = capsys.readouterr().out
    assert "GASTA DINHEIRO" not in saida
    assert "assinatura" in saida.lower()
    assert "US$" not in saida


def test_a_via_por_ASSINATURA_esta_sob_a_tranca_de_rede_da_suite():
    """A tranca cobre DOIS pacotes, e por um tempo cobriu so um.

    `eval/assinatura.py` nao usa `anthropic`: usa `claude_agent_sdk`, cujo
    `query` fala com o modelo pela assinatura do Claude Code. Ele ficava fora de
    `tests/conftest.py::_rede_proibida`, e
    `test_main_aceita_via_assinatura_e_nao_anuncia_gasto` so nao gastava porque
    `--n 20` por acaso nao produz divergencia nenhuma — um acidente de DADO,
    exatamente a forma do defeito que aquela fixture nasceu para pegar. Bastava
    alguem mexer no `n` daquele teste.

    Aqui o `n` PRODUZ divergencias, entao o caminho de verdade e percorrido ate
    o ponto em que a tranca fecha. `BaseException` e nao `Exception`: se a
    tranca fosse capturavel, `assinatura.py` a transformaria em abstencao e este
    `raises` falharia — que e o sinal desejado.
    """
    pytest.importorskip("claude_agent_sdk")
    from orchestrator.eval.agent_eval import main

    with pytest.raises(BaseException, match="falar com o modelo de verdade"):
        main(["--via", "assinatura", "--n", "100"])
