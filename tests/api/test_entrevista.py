"""A entrevista por WebSocket: o chat que compõe.

É o ÚNICO caminho da camada HTTP que gasta dinheiro, e estes testes existem
para que ele gaste só o que promete. Todos rodam com `FakeLLMClient` — sem
rede, sem um centavo — que é a mesma propriedade que `grill/entrevistador.py`
documenta no cabeçalho.

O que NÃO é testado aqui e continua testado em `test_execucao.py`: que EXECUTAR
um workflow pela web não gasta nada. A regra ficou mais precisa, não mais
frouxa.
"""

import json

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

import orchestrator.api.app as app_mod
from orchestrator.agent.llm import FakeLLMClient, LLMResponse, ToolCall
from orchestrator.api.app import app
from orchestrator.grill.entrevistador import Entrevistador
from orchestrator.kernel.cost import Cost

cliente = TestClient(app)


def _resposta(nome: str, argumentos: dict) -> LLMResponse:
    return LLMResponse(
        text="",
        tool_calls=[ToolCall(id="t1", name=nome, arguments=argumentos)],
        cost=Cost(input_tokens=1000, output_tokens=120, calls=1),
    )


# Os nomes e o formato saem de `grill/ferramentas.esquemas()`, que é o que o
# modelo de verdade recebe. Inventá-los aqui faria o teste provar um contrato
# que não existe — foi o que aconteceu na primeira tentativa: `propor_cascata`
# e `recusar` não existem, e os três desfechos viraram "defeito".
def _propor(resolvers):
    return _resposta(
        "propor_workflow",
        {
            "nome": "Do chat",
            "justificativa": "porque o parceiro descreveu assim",
            "resolvers": resolvers,
        },
    )


def _perguntar(texto: str):
    return _resposta("perguntar", {"texto": texto})


def _recusar(motivo: str, faltaria: str):
    return _resposta("fora_do_catalogo", {"motivo": motivo, "o_que_faltaria": faltaria})


@pytest.fixture
def com_entrevistador(monkeypatch, tmp_path):
    """Troca o entrevistador por um de brinquedo e a raiz por tmp_path."""
    monkeypatch.setattr(app_mod, "_RAIZ_RECEITAS", tmp_path)

    def instalar(respostas, gravar=None):
        fabrica = lambda: Entrevistador(client=FakeLLMClient(list(respostas)))  # noqa: E731
        original = app_mod.entrevista

        async def rota(ws):
            from orchestrator.api.entrevista import conduzir
            from orchestrator.grill.registro import gravar_receita

            await conduzir(
                ws,
                fabrica_entrevistador=fabrica,
                # `gravar` injetável para que um teste possa exercitar o
                # gravador REAL da rota (`_gravar_receita_do_chat`, que checa o
                # `registry()`) em vez deste, que só escreve.
                gravar=gravar or (lambda r: gravar_receita(r, tmp_path)),
            )

        # Substitui o handler da rota já registrada, sem tocar no app global.
        for r in app.routes:
            if getattr(r, "path", None) == "/api/entrevista":
                monkeypatch.setattr(r, "app", _wrap(rota))
        assert original
        return tmp_path

    return instalar


def _wrap(handler):
    from starlette.routing import websocket_session

    return websocket_session(handler)


# -- os três desfechos ------------------------------------------------------


def test_o_chat_PROPOE_uma_cascata_e_ela_vira_workflow(com_entrevistador):
    """O desfecho que importa: a conversa vira uma `Receita` gravada, e a
    receita gravada é um workflow como qualquer outro."""
    raiz = com_entrevistador([_propor([{"nome": "L1"}, {"nome": "revisor"}])])

    with cliente.websocket_connect("/api/entrevista") as ws:
        ws.send_json({"workflow_id": "do-chat", "descricao": "conciliar meu extrato"})
        msg = ws.receive_json()

    assert msg["tipo"] == "proposta"
    assert [r["nome"] for r in msg["receita"]["resolvers"]] == ["L1", "revisor"]
    assert (raiz / "workflows" / "do-chat.json").exists()


def test_o_chat_PERGUNTA_e_espera_a_resposta(com_entrevistador):
    """O laço é conversacional de verdade: a pergunta chega, o servidor PARA, e
    só continua com o que a pessoa responde."""
    com_entrevistador(
        [_perguntar("seu extrato tem data de compensação?"), _propor([{"nome": "L1"}])]
    )

    with cliente.websocket_connect("/api/entrevista") as ws:
        ws.send_json({"workflow_id": "do-chat", "descricao": "conciliar"})
        pergunta = ws.receive_json()
        assert pergunta == {"tipo": "pergunta", "texto": "seu extrato tem data de compensação?"}

        ws.send_json({"texto": "tem sim"})
        final = ws.receive_json()

    assert final["tipo"] == "proposta"


def test_o_chat_RECUSA_e_diz_o_que_faltaria(com_entrevistador):
    """Recusa não é erro: é o entrevistador dizendo que o descrito não cabe no
    catálogo. "O que faltaria" é a parte útil da recusa."""
    com_entrevistador([_recusar("não é conciliação", "um resolver de cobrança")])

    with cliente.websocket_connect("/api/entrevista") as ws:
        ws.send_json({"workflow_id": "cobranca-acme", "descricao": "quero cobrar inadimplentes"})
        msg = ws.receive_json()

    assert msg["tipo"] == "recusa"
    assert msg["o_que_faltaria"] == "um resolver de cobrança"


# -- o dinheiro -------------------------------------------------------------


def test_TODO_desfecho_devolve_o_custo(com_entrevistador):
    """Gasto que não aparece na tela é gasto que ninguém revisa. É a guarda 2
    do cabeçalho de `api/entrevista.py`."""
    com_entrevistador([_propor([{"nome": "L1"}])])

    with cliente.websocket_connect("/api/entrevista") as ws:
        ws.send_json({"workflow_id": "conciliar-acme", "descricao": "conciliar"})
        msg = ws.receive_json()

    assert msg["custo_usd"] > 0


def test_orcamento_estourado_FALHA_com_a_transcricao(com_entrevistador):
    """A conversa do parceiro não se perde por um teto atingido — é o contrato
    de `EntrevistaFalhou`, e ele chega até a tela."""
    caro = LLMResponse(
        text="",
        tool_calls=[ToolCall(id="t", name="perguntar", arguments={"pergunta": "?"})],
        cost=Cost(input_tokens=10_000_000, output_tokens=10_000_000, calls=1),
    )
    monkey = com_entrevistador([caro, caro])

    with cliente.websocket_connect("/api/entrevista") as ws:
        ws.send_json({"workflow_id": "conciliar-acme", "descricao": "conciliar"})
        msg = ws.receive_json()
        if msg["tipo"] == "pergunta":
            ws.send_json({"texto": "sim"})
            msg = ws.receive_json()

    assert msg["tipo"] == "falhou"
    assert "orçamento" in msg["motivo"]
    assert msg["transcricao"], "a transcrição do parceiro não pode se perder"
    assert monkey


# -- as recusas antes de gastar --------------------------------------------


def test_SEM_CHAVE_o_chat_recusa_antes_de_qualquer_chamada(monkeypatch):
    """Guarda 3: sem `ANTHROPIC_API_KEY`, fecha com motivo legível em vez de
    deixar o SDK levantar no meio do laço e a transcrição se perder.

    Sem fixture de entrevistador: este é o caminho REAL, com o entrevistador de
    produção.

    Substitui `api/app.py::_tem_chave` em vez de mexer em `os.environ` — e é a
    prova de que a leitura é UMA. Este módulo lia a variável por conta própria;
    agora ele chama a mesma função que `/runs` e `/api/ambiente`, e patchá-la
    num lugar só muda os três. Também evita um teste que mutila o ambiente do
    processo e o restaura no `finally`, o que vaza se algo levantar no meio.
    """
    monkeypatch.setattr(app_mod, "_tem_chave", lambda: False)

    with cliente.websocket_connect("/api/entrevista") as ws:
        msg = ws.receive_json()

    assert msg["tipo"] == "indisponivel"
    assert "ANTHROPIC_API_KEY" in msg["motivo"]


def test_id_INVALIDO_e_recusado_antes_de_qualquer_turno(com_entrevistador):
    """`validar_id` levantando virava `{"tipo": "defeito"}`, que a tela mostra
    como erro NOSSO. É recusa legítima, com uma regra que a pessoa pode
    atender — achado rodando o primeiro teste desta suíte."""
    com_entrevistador([_propor([{"nome": "L1"}])])

    with cliente.websocket_connect("/api/entrevista") as ws:
        ws.send_json({"workflow_id": "x", "descricao": "conciliar"})
        msg = ws.receive_json()

    assert msg["tipo"] == "erro"
    assert "id inválido" in msg["motivo"]


def test_descricao_VAZIA_nao_chega_a_gastar(com_entrevistador):
    """Uma descrição em branco produziria um turno pago para o modelo perguntar
    o que a tela já sabia perguntar de graça."""
    com_entrevistador([_propor([{"nome": "L1"}])])

    with cliente.websocket_connect("/api/entrevista") as ws:
        ws.send_json({"workflow_id": "qualquer-coisa", "descricao": "   "})
        msg = ws.receive_json()

    assert msg["tipo"] == "erro"


# -- o ambiente -------------------------------------------------------------


def test_o_ambiente_NUNCA_devolve_o_valor_da_chave():
    """Uma tela que mostra a chave é uma tela que a vaza para quem olha por
    cima do ombro, para o print da conversa e para o cache do navegador."""
    dados = cliente.get("/api/ambiente").json()

    assert isinstance(dados["tem_chave"], bool)
    assert "chave" not in json.dumps(dados).replace("tem_chave", "")
    assert not any(
        isinstance(v, str) and v.startswith("sk-") for v in dados.values()
    )


def test_o_ambiente_traz_os_limites_que_a_execucao_APLICA():
    """Uma segunda tabela aqui divergiria, e o sintoma seria a tela oferecer um
    `n` que o servidor recusa."""
    dados = cliente.get("/api/ambiente").json()

    assert cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"fonte": {"tipo": "sintetica", "seed": dados["seed"], "n": dados["n"]}},
    ).status_code == 200
    assert cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"fonte": {"tipo": "sintetica", "seed": 1, "n": dados["n_max"] + 1}},
    ).status_code == 422


# -- a thread que morre sem falar -------------------------------------------


def test_uma_thread_que_morre_por_BaseException_NAO_PENDURA_a_conexao(
    monkeypatch, tmp_path
):
    """O pior desfecho possivel nao e um erro: e o silencio.

    `rodar()` captura `Exception`. Qualquer coisa que escape disso —
    `KeyboardInterrupt`, `SystemExit`, ou a tranca de rede da suite, que e
    `BaseException` de proposito — matava a thread sem por nada em `perguntas`,
    e `perguntas.get` bloqueava PARA SEMPRE.

    Num servidor de verdade isso e uma conexao pendurada que nunca responde nem
    fecha. Em CI e um job que queima o timeout inteiro e nao diz nada: medido
    como `PYTEST_EXIT=124`, saida vazia. Um teste que falha diz onde olhar; um
    job que trava nao diz nada, e por isso este defeito e pior que o erro que o
    causou.

    A correcao NAO e alargar a captura para `BaseException` — isso engoliria
    justamente o que precisa subir, que e o ponto inteiro da tranca de rede. E
    um `finally` que acorda quem espera: uma thread que nao pode mais falar tem
    de dizer isso antes de calar.

    O `timeout` deste teste e parte da assercao: sem a correcao ele nao falha,
    ele PENDURA, e um teste que pendura e exatamente o sintoma sob analise.
    """
    import orchestrator.api.entrevista as entrevista_mod

    monkeypatch.setattr(app_mod, "_RAIZ_RECEITAS", tmp_path)

    class _MorteQueEscapaDoExcept(BaseException):
        """Nao deriva de `Exception`, como `RedeProibida` nao deriva."""

    class _Suicida:
        client = FakeLLMClient([])

        def entrevistar(self, workflow_id, descricao, responder):
            raise _MorteQueEscapaDoExcept("a thread morreu sem dizer nada")

    async def rota(ws):
        await entrevista_mod.conduzir(ws, fabrica_entrevistador=lambda: _Suicida())

    for r in app.routes:
        if getattr(r, "path", None) == "/api/entrevista":
            monkeypatch.setattr(r, "app", _wrap(rota))

    with cliente.websocket_connect("/api/entrevista") as ws:
        ws.send_json({"workflow_id": "do-chat", "descricao": "conciliar"})
        msg = ws.receive_json()

    # "defeito" e nao "falhou": `falhou` e o entrevistador dizendo que nao deu,
    # e isto e o servidor dizendo que quebrou. A tela mostra os dois diferente.
    assert msg["tipo"] == "defeito"
    assert "interrompida" in msg["motivo"]


def test_a_thread_que_termina_NORMALMENTE_nao_muda_de_desfecho(com_entrevistador):
    """O outro lado do `finally`: a sentinela e posta SEMPRE, inclusive quando
    ha veredito.

    A fila e FIFO, entao o veredito chega primeiro e o consumidor retorna antes
    de ve-la. Se a ordem estivesse trocada, TODA entrevista bem-sucedida viraria
    "defeito" — e este teste e quem pega isso.
    """
    com_entrevistador([_propor([{"nome": "L1"}])])

    with cliente.websocket_connect("/api/entrevista") as ws:
        ws.send_json({"workflow_id": "do-chat", "descricao": "conciliar"})
        msg = ws.receive_json()

    assert msg["tipo"] == "proposta"


# -- a TERCEIRA porta de escrita --------------------------------------------


def _composicao_em(raiz, cid):
    from datetime import UTC, datetime

    from orchestrator.authoring.composicao import BlocoRegra, Composicao, gravar

    raiz.mkdir(parents=True, exist_ok=True)
    gravar(
        Composicao(
            id=cid, nome="do canvas", gerado_em=datetime.now(UTC),
            blocos=(BlocoRegra(nome="L1", parametros={}),),
        ),
        raiz,
    )


def test_o_chat_NAO_grava_por_cima_de_uma_composicao_do_canvas(
    com_entrevistador, monkeypatch, tmp_path
):
    """O chat era a terceira porta de escrita, e a única sem a tranca do id.

    `gravar_receita` só sabe se o ARQUIVO de receita existe — não consulta o
    `registry()`. Com uma composição `acme2` salva pela tela, o chat gravava
    uma receita homônima, `registry()` passava a devolver a do chat, e a
    composição sumia no pulo-com-aviso: um `stderr` do servidor que ninguém na
    tela vê, e o link `/?workflow=acme2` do painel abrindo outro workflow.

    A recusa chega como `recusa` e não como erro porque WebSocket não carrega
    status HTTP: é o desfecho que a tela já sabe mostrar, com a MESMA frase do
    409 das outras duas portas.
    """
    composicoes = tmp_path / "composicoes"
    _composicao_em(composicoes, "acme2")
    monkeypatch.setattr(app_mod, "_RAIZ_RECEITAS", tmp_path)
    monkeypatch.setattr(app_mod, "_RAIZ_COMPOSICOES", composicoes)
    com_entrevistador(
        [_propor([{"nome": "L1"}, {"nome": "revisor"}])],
        gravar=app_mod._gravar_receita_do_chat,
    )

    with cliente.websocket_connect("/api/entrevista") as ws:
        ws.send_json({"workflow_id": "acme2", "descricao": "conciliar meu extrato"})
        msg = ws.receive_json()

    assert msg["tipo"] == "recusa"
    assert "já existe um workflow com id 'acme2'" in msg["motivo"]
    # Nada foi gravado, e o `registry()` continua entregando A COMPOSIÇÃO.
    assert not (tmp_path / "workflows" / "acme2.json").exists()
    from orchestrator.workflows import registry

    assert "acme2" in registry(tmp_path, composicoes)


def test_um_id_LIVRE_continua_passando_pela_mesma_porta(
    com_entrevistador, monkeypatch, tmp_path
):
    """A tranca recusa o id tomado, não a gravação — o desfecho feliz é o mesmo
    de sempre pelo gravador REAL da rota."""
    composicoes = tmp_path / "composicoes"
    _composicao_em(composicoes, "outra-coisa")
    monkeypatch.setattr(app_mod, "_RAIZ_RECEITAS", tmp_path)
    monkeypatch.setattr(app_mod, "_RAIZ_COMPOSICOES", composicoes)
    com_entrevistador(
        [_propor([{"nome": "L1"}, {"nome": "revisor"}])],
        gravar=app_mod._gravar_receita_do_chat,
    )

    with cliente.websocket_connect("/api/entrevista") as ws:
        ws.send_json({"workflow_id": "livre", "descricao": "conciliar meu extrato"})
        msg = ws.receive_json()

    assert msg["tipo"] == "proposta"
    assert (tmp_path / "workflows" / "livre.json").exists()


def test_a_ORDEM_INVERSA_continua_no_409_de_sempre(monkeypatch, tmp_path):
    """Receita primeiro, composição depois: `/api/composicoes` já recusava, e a
    correção do chat não mexeu nisso. As três portas leem o mesmo `registry()`.
    """
    from orchestrator.grill.receita import Receita, ResolverReceita
    from orchestrator.grill.registro import gravar_receita

    composicoes = tmp_path / "composicoes"
    monkeypatch.setattr(app_mod, "_RAIZ_RECEITAS", tmp_path)
    monkeypatch.setattr(app_mod, "_RAIZ_COMPOSICOES", composicoes)
    from datetime import UTC, datetime

    gravar_receita(
        Receita(
            id="acme3", nome="Acme", justificativa="j",
            gerado_em=datetime.now(UTC),
            resolvers=(ResolverReceita("L1", {}), ResolverReceita("revisor", {})),
        ),
        tmp_path,
    )

    r = cliente.post(
        "/api/composicoes",
        json={
            "id": "acme3", "nome": "Do canvas", "justificativa": "j",
            "blocos": [{"tipo": "regra", "nome": "L1", "parametros": {}}],
        },
    )

    assert r.status_code == 409
    assert "já existe um workflow com id 'acme3'" in r.json()["detail"]
