"""O bloco que busca o detalhe de cada item.

Entre `Input` (traz a lista) e os blocos de decisão faltava a operação mais
comum de automação: para cada item, buscar o que a lista não trouxe. Sem ela, a
única saída era pagar um turno de modelo para executar um GET que não decide
nada.
"""

import pytest

pytest.importorskip("httpx")

import httpx

from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.sources.enriquecimento import Enriquecimento
from orchestrator.sources.erros import ErroDeFonte, VariavelAusente


def _bloco(handler, **kw) -> Enriquecimento:
    base = dict(
        kind="caso",
        produz="caso_completo",
        url="https://api.exemplo.test/v1/assessments/{assessmentId}",
        transporte=httpx.MockTransport(handler),
    )
    base.update(kw)
    return Enriquecimento(**base)


def _pool(*payloads) -> WorkSet:
    return WorkSet(
        items=tuple(
            WorkItem(id=str(p["assessmentId"]), kind="caso", payload=p) for p in payloads
        )
    )


def test_os_campos_da_resposta_pousam_no_TOPO_do_payload():
    """No primeiro nível, e não aninhados sob um nome: `_prompt_do_item` usa
    `format_map`, que só alcança o primeiro nível — aninhar tornaria
    inalcançável pelo prompt justamente o dado que foi buscado para ele."""

    def handler(pedido):
        assert pedido.url.path == "/v1/assessments/a1"
        return httpx.Response(200, json={"risco": "ALTO", "motivo": "PEP"})

    saida = _bloco(handler).resolve(_pool({"assessmentId": "a1", "slaSeconds": 90}))

    (produzido,) = saida.produced
    assert produzido.kind == "caso_completo"
    assert produzido.payload == {
        "assessmentId": "a1",
        "slaSeconds": 90,
        "risco": "ALTO",
        "motivo": "PEP",
    }
    # Consome E produz: o item original sai do pool por uma resolução.
    (resolucao,) = saida.resolutions
    assert resolucao.item_ids == frozenset({"a1"})


def test_em_COLISAO_o_campo_original_do_item_vence():
    """Uma resposta de terceiro não pode reescrever o campo que IDENTIFICA o
    item: se pudesse, o id do run, a chave da fila e a decisão humana passariam
    a apontar para coisas diferentes.

    É a regra OPOSTA à do `BlocoTarefa`, onde o texto novo vence — e a
    assimetria é deliberada: lá o campo novo é a saída do trabalho, aqui é
    informação de fora chegando sobre um item que já tem identidade.
    """

    def handler(pedido):
        return httpx.Response(200, json={"assessmentId": "OUTRO", "risco": "BAIXO"})

    saida = _bloco(handler).resolve(_pool({"assessmentId": "a1"}))

    assert saida.produced[0].payload == {"assessmentId": "a1", "risco": "BAIXO"}


def test_um_item_que_FALHA_fica_no_pool_e_os_outros_seguem():
    """Falha de rede não derruba um fechamento por causa de um item — é a mesma
    forma da abstenção de um agente. O item não consumido aparece na LACUNA,
    que é a notícia certa; um payload pela metade seria lido como fato pelo
    degrau seguinte."""

    def handler(pedido):
        if pedido.url.path.endswith("a1"):
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"risco": "BAIXO"})

    saida = _bloco(handler).resolve(_pool({"assessmentId": "a1"}, {"assessmentId": "a2"}))

    assert [p.payload["assessmentId"] for p in saida.produced] == ["a2"]
    assert [r.item_ids for r in saida.resolutions] == [frozenset({"a2"})]


def test_template_citando_campo_que_o_item_NAO_TEM_abstem_nomeando_o_campo(caplog):
    """Mesma abstenção, e o log diz qual campo faltou — sem isso, quem monta o
    workflow só vê a lacuna e não tem como saber se errou o nome do campo ou se
    a API caiu."""

    def handler(pedido):  # pragma: no cover - não deve ser alcançado
        raise AssertionError("não devia chegar à rede com o template furado")

    bloco = _bloco(handler, url="https://api.exemplo.test/v1/x/{nao_existe}")

    with caplog.at_level("WARNING"):
        saida = bloco.resolve(_pool({"assessmentId": "a1"}))

    assert saida.produced == ()
    assert "nao_existe" in caplog.text


def test_token_ausente_falha_ALTO_e_nao_toca_a_rede():
    """Erro de CONFIGURAÇÃO, não abstenção: abster item a item por falta de
    credencial gastaria a fila inteira para não fazer nada."""

    def handler(pedido):  # pragma: no cover
        raise AssertionError("não devia chegar à rede sem token")

    bloco = _bloco(handler, token_env="NAO_DEFINIDA_NO_AMBIENTE")

    with pytest.raises(VariavelAusente):
        bloco.resolve(_pool({"assessmentId": "a1"}))


def test_o_token_vai_no_cabecalho_e_vem_do_NOME_da_variavel(monkeypatch):
    monkeypatch.setenv("BARRIER_TOKEN", "segredo-123")
    vistos = {}

    def handler(pedido):
        vistos["auth"] = pedido.headers.get("authorization")
        return httpx.Response(200, json={"risco": "ALTO"})

    _bloco(handler, token_env="BARRIER_TOKEN").resolve(_pool({"assessmentId": "a1"}))

    assert vistos["auth"] == "Bearer segredo-123"


def test_host_LOOPBACK_e_recusado_pela_guarda_herdada():
    """A mesma guarda de `sources/http.py`, e pela mesma razão: o servidor passa
    a fazer requisições para URLs que vêm da tela. Afrouxá-la para alcançar um
    serviço local seria trocar a proteção por conveniência.

    E ela LEVANTA em vez de abster, ao contrário de um 500 do parceiro: url de
    loopback é CONFIGURAÇÃO — todo item falharia igual, e abster na fila inteira
    para não fazer nada é o que `VariavelAusente` já recusa fazer. A primeira
    versão deste bloco abstinha, e foi este teste que pegou."""

    def handler(pedido):  # pragma: no cover
        raise AssertionError("não devia chegar à rede com host de loopback")

    bloco = _bloco(handler, url="http://127.0.0.1:8080/v1/x/{assessmentId}")

    with pytest.raises(ErroDeFonte):
        bloco.resolve(_pool({"assessmentId": "a1"}))


def test_caminho_aponta_o_objeto_dentro_do_corpo():
    """`caminho` é a ferramenta de MINIMIZAÇÃO: apontá-lo para o subobjeto que
    importa é o que mantém o cadastro inteiro fora do pool, da fila e do
    trace."""

    def handler(pedido):
        return httpx.Response(
            200,
            json={"dados": {"screening": {"risco": "ALTO"}}, "cadastro": {"nome": "Fulano"}},
        )

    saida = _bloco(handler, caminho="dados.screening").resolve(_pool({"assessmentId": "a1"}))

    assert saida.produced[0].payload == {"assessmentId": "a1", "risco": "ALTO"}


def test_resposta_que_nao_e_OBJETO_abstem():
    """Uma lista ou um número não têm campos para fundir. Fundir "de algum
    jeito" inventaria uma chave que ninguém declarou."""

    def handler(pedido):
        return httpx.Response(200, json=[1, 2, 3])

    saida = _bloco(handler).resolve(_pool({"assessmentId": "a1"}))

    assert saida.produced == ()


def test_produz_igual_ao_kind_e_recusado_na_CONSTRUCAO():
    """O ramo alimentaria a si mesmo — a mesma recusa de `condicao.py` e de
    `TarefaDeclarada`."""
    with pytest.raises(ValueError, match="mesmo kind"):
        Enriquecimento(kind="caso", produz="caso", url="https://x.test/{id}")


def test_url_que_nao_interpola_NADA_e_recusada():
    """Todo item buscaria o MESMO recurso — e uma chamada por item que devolve
    sempre a mesma coisa é uma fonte, não um enriquecimento."""
    with pytest.raises(ValueError, match="não interpola"):
        Enriquecimento(kind="caso", produz="caso_completo", url="https://x.test/fixo")


def test_a_classe_de_custo_e_REGRA():
    """Ela mede DINHEIRO, e o bloco custa 0 µ¢ — isso é verdade. O que ele
    ganha é latência e um modo de falha, e é por isso que ele nunca entra no
    caminho do golden."""
    assert _bloco(lambda p: httpx.Response(200, json={})).cost_class is CostClass.REGRA
