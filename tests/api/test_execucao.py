import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from orchestrator.api.app import app
from orchestrator.domains.reconciliation.models import banco, conciliacao, contabil

cliente = TestClient(app)


@pytest.fixture(autouse=True)
def _sem_composicoes_do_desenvolvedor(tmp_path, monkeypatch):
    """Os dois `descrever()` sem raiz de composições (o de `produz` e o de
    política) liam `data/composicoes` do desenvolvedor. Mexer no default os
    mantém do jeito que estão escritos — a chamada pelada é a propriedade — sem
    deixar que uma composição salva pela tela mude o que eles varrem."""
    from orchestrator.authoring import composicao as composicao_mod

    monkeypatch.setattr(composicao_mod, "_RAIZ_PADRAO", tmp_path / "padrao-vazia")


@pytest.fixture(autouse=True)
def _cache_limpo():
    """`executar()` delega para `_executar`, que é `lru_cache`d.

    Duas funções neste arquivo postam o EXATO mesmo corpo
    (`{"fonte": {"tipo": "sintetica", "seed": 1, "n": 100, "taxa_divergencia": 0.15}}`): o canário
    (`test_execucao_nao_chama_o_modelo_de_jeito_nenhum`) e
    `test_execucao_nao_serve_resolver_que_gasta_dinheiro`. Se uma rodar depois da
    outra com o cache ainda quente, a segunda vira cache hit — o corpo de
    `_executar` nem executa — e uma asserção sobre "o que foi
    chamado" passa vazia, sem ter provado nada. Hoje isso só não acontece por
    acidente de ordem no arquivo; `-k`, um teste novo inserido antes, ou um
    plugin de ordem aleatória destruiriam essa garantia em silêncio.
    """


def test_execucao_nao_chama_o_modelo_de_jeito_nenhum(monkeypatch):
    """A promessa do §5.2 do spec, virada teste — versão que de fato pina algo.

    A primeira versão deste teste levantava `AssertionError` de dentro de
    `AnthropicClient.complete` e checava só `status_code == 200`. Isso é
    vazio: `Investigator.investigar()` (ver `investigator.py`) envolve exatamente
    essa chamada num `try/except Exception` largo e PROPOSITAL — qualquer
    exceção vinda do modelo, canário incluído, vira uma abstenção silenciosa
    e a rota devolve 200 do mesmo jeito. Medido: liguei um `Investigator` de
    verdade na definição servida e o teste antigo continuou passando. Uma
    exceção que o próprio domínio existe para engolir não prova que nada foi
    chamado.

    Por isso o canário aqui NUNCA levanta. Ele grava a chamada numa lista e
    devolve uma resposta válida — e a asserção é sobre a lista, não sobre
    propagação. Não existe `except` que esconda um `append`.
    """

    chamadas: list[dict] = []

    def _espiao(self, system, messages, tools):
        chamadas.append({"system": system, "messages": messages, "tools": tools})
        from orchestrator.agent.llm import LLMResponse
        from orchestrator.kernel.cost import Cost

        return LLMResponse(text="{}", tool_calls=[], cost=Cost.zero())

    # Qualquer construção de cliente real passa por aqui.
    import orchestrator.agent.anthropic_client as ac

    monkeypatch.setattr(ac.AnthropicClient, "complete", _espiao)

    resposta = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"fonte": {"tipo": "sintetica", "seed": 1, "n": 100, "taxa_divergencia": 0.15}},
    )

    assert resposta.status_code == 200
    assert chamadas == []


def test_execucao_nao_serve_resolver_que_gasta_dinheiro():
    """Segunda perna da mesma garantia, sem monkeypatch nenhum.

    Pina a propriedade direto na saída do endpoint: nenhum resolver de
    `cost_class` AGENTE participou da execução. Isso pega até um agente que
    foi ligado mas ABSTEVE em toda divergência sem nunca chamar o modelo —
    caso que o espião do teste acima não pegaria, porque para ele nada de
    errado aconteceria (a lista de chamadas continuaria vazia mesmo com o
    agente presente). As duas asserções são independentes: uma pega quem
    chama o modelo, a outra pega quem foi apenas colocado na cascata.

    A asserção é "nenhum AGENTE", não "só REGRA": com o revisor (`HUMANO`) na
    definição padrão, a cascata já tem duas classes, e a propriedade que
    importa sempre foi "nada aqui gasta dinheiro" — nunca "só existem regras".
    """
    corpo = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"fonte": {"tipo": "sintetica", "seed": 1, "n": 100, "taxa_divergencia": 0.15}},
    ).json()

    assert "AGENTE" not in [r["cost_class"] for r in corpo["por_resolver"]]


def test_execucao_reporta_taxa_e_custo_por_resolver():
    corpo = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"fonte": {"tipo": "sintetica", "seed": 1, "n": 300, "taxa_divergencia": 0.15}},
    ).json()

    nomes = [r["name"] for r in corpo["por_resolver"]]
    assert nomes == ["L1", "L2", "L3", "revisor"]
    assert all(r["microcents"] == 0 for r in corpo["por_resolver"])
    # A taxa contra gabarito mudou de lugar, não de valor: ela só existe
    # quando a fonte carrega verdade, e por isso deixou de morar no topo.
    assert 0.80 < corpo["contra_gabarito"]["deterministic_rate"] < 0.95
    assert corpo["custo_microcents"] == 0


def test_a_lacuna_e_reportada_explicitamente():
    # A definição padrão não tem agente. O que as regras não resolvem não
    # some do relatório: vira lacuna com tamanho. É o §3.4 do spec de
    # composição — o ponto mais valioso da tela.
    corpo = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"fonte": {"tipo": "sintetica", "seed": 1, "n": 300, "taxa_divergencia": 0.15}},
    ).json()

    assert corpo["gap"]["items"] > 0
    # A soma fecha porque as duas pontas estão na MESMA unidade: `rate` é
    # itens consumidos sobre itens do pool (`Run.resolved_items_by_resolver`),
    # e a lacuna é o pool que sobrou. Enquanto `rate` dividia CONTAGEM DE
    # RESOLUÇÕES pelo pool, esta soma dava 0.575 na conciliação.
    soma = sum(r["rate"] for r in corpo["por_resolver"]) + corpo["gap"]["rate"]
    assert abs(soma - 1.0) < 1e-9
    # E a conta em itens absolutos, que é a mesma afirmação sem as divisões.
    assert corpo["resolvidos"] + corpo["gap"]["items"] == corpo["itens"]
    # `matches` continua sendo a OUTRA unidade, e aqui ela é estritamente
    # menor: toda resolução da conciliação consome dois itens ou mais.
    assert 0 < sum(r["matches"] for r in corpo["por_resolver"]) < corpo["resolvidos"]


def test_n_invalido_da_422_em_vez_de_estourar():
    resposta = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"fonte": {"tipo": "sintetica", "seed": 1, "n": 300, "taxa_divergencia": 5.0}},
    )
    assert resposta.status_code == 422


def test_resolver_com_layer_diferente_do_name_e_reportado_pelo_proprio_nome(monkeypatch):
    """Pina P3.2 (DECISOES.md): `Resolver.name` é identidade, `Resolution.produced_by`
    é proveniência — dois conceitos que hoje coincidem para L1/L2/L3, mas não
    são o mesmo campo. Um resolver com `name` diferente do `layer` que ele
    estampa nas próprias resoluções ainda precisa aparecer com a contagem REAL na
    resposta do endpoint. Se o endpoint voltasse a ler `matches_by_layer`
    (proveniência) chaveado por `name` (identidade), este resolver reportaria
    0% mesmo tendo casado lançamentos de verdade — o defeito de zero silencioso
    que este teste existe para travar.
    """
    from orchestrator.kernel.cost import CostClass
    from orchestrator.kernel.definition import Stage, WorkflowDefinition
    from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput

    class _NomeDiferenteDaProveniencia:
        name = "resolver_x"
        cost_class = CostClass.REGRA

        def resolve(self, work):
            n = min(3, len(banco(work)), len(contabil(work)))
            return ResolverOutput(
                resolutions=[
                    conciliacao(
                        work,
                        frozenset({banco(work)[i].id, contabil(work)[i].id}),
                        # Proveniência deliberadamente != `name` acima.
                        produced_by="proveniencia_y",
                        rule="teste",
                    )
                    for i in range(n)
                ]
            )

        def describe(self) -> ResolverDescription:
            return ResolverDescription(self.name, self.cost_class, "name != layer, de propósito")

    def _fabrica(ctx):
        return WorkflowDefinition(
            id="layer_diferente",
            name="teste — name != layer",
            stages=(Stage(name="s", cascade=(_NomeDiferenteDaProveniencia(),)),),
        )

    # `registry()` monta um dict NOVO a cada chamada (embutida + disco); não
    # há mais um `_WORKFLOWS` mutável para `setitem`. Envolve a fábrica
    # original e acrescenta a entrada de teste por cima, preservando as
    # entradas reais (`conciliacao`).
    from orchestrator.workflows import registry as _registry_original

    def _registry_com_extra(raiz=None, raiz_composicoes=None):
        fabricas = _registry_original(raiz, raiz_composicoes)
        fabricas["layer_diferente"] = _fabrica
        return fabricas

    monkeypatch.setattr("orchestrator.api.app.registry", _registry_com_extra)

    corpo = cliente.post(
        "/api/workflows/layer_diferente/runs",
        json={"fonte": {"tipo": "sintetica", "seed": 1, "n": 100, "taxa_divergencia": 0.15}},
    ).json()

    (resolvido,) = corpo["por_resolver"]
    assert resolvido["name"] == "resolver_x"
    assert resolvido["matches"] == 3
    # Cada uma das três resoluções casa um bancário com um contábil: TRÊS
    # resoluções, SEIS itens. `rate` é a segunda unidade, nunca a primeira —
    # `3 / itens` era a fórmula errada, e ela passava porque nada mais a
    # contradizia.
    assert corpo["resolvidos"] == 6
    assert resolvido["rate"] == pytest.approx(6 / corpo["itens"])
    assert corpo["resolvidos"] + corpo["gap"]["items"] == corpo["itens"]

    soma = sum(r["rate"] for r in corpo["por_resolver"]) + corpo["gap"]["rate"]
    assert soma == pytest.approx(1.0)


def test_pedido_SEM_fonte_continua_valendo():
    """A compatibilidade que mantém o canvas, a CLI do grill e os testes de
    hoje sem edição. O default é a sintética com os mesmos números."""
    from orchestrator.api.schemas import RunRequest

    r = RunRequest()

    assert r.fonte.tipo == "sintetica"
    assert (r.fonte.seed, r.fonte.n, r.fonte.taxa_divergencia) == (1, 300, 0.15)
    assert r.teto_microcents is None


def test_a_fonte_e_uma_UNIAO_DISCRIMINADA_por_tipo():
    """Um objeto com `seed?` ao lado de `caminho?` aceitaria os cruzamentos que
    não significam nada — uma fonte sintética com caminho, um arquivo com
    semente. `tipo` é o que torna os quatro cruzamentos dois."""
    from orchestrator.api.schemas import RunRequest

    r = RunRequest.model_validate(
        {"fonte": {"tipo": "arquivo", "caminho": "issues.csv",
                   "kind": "issue", "campo_id": "numero"}}
    )

    assert r.fonte.tipo == "arquivo"
    assert r.fonte.caminho == "issues.csv"
    assert not hasattr(r.fonte, "seed")


def test_fonte_de_arquivo_EXIGE_kind_e_campo_id():
    """Nenhum dos dois é inferível. `kind` é o que liga um degrau ao outro no
    grafo, e `campo_id` é o que dá identidade ao item — adivinhar qualquer um
    seria conveniência com cara de defeito."""
    import pydantic

    from orchestrator.api.schemas import RunRequest

    with pytest.raises(pydantic.ValidationError):
        RunRequest.model_validate({"fonte": {"tipo": "arquivo", "caminho": "x.csv"}})


def test_teto_negativo_e_recusado_pelo_SCHEMA():
    """Fora do handler, como `taxa_divergencia` já é: o FastAPI devolve 422
    sozinho em vez de deixar a aritmética de orçamento levantar mais fundo."""
    import pydantic

    from orchestrator.api.schemas import RunRequest

    with pytest.raises(pydantic.ValidationError):
        RunRequest(teto_microcents=-1)


def test_a_forma_ANTIGA_do_pedido_e_recusada_em_voz_alta():
    """`seed` no topo era o pedido inteiro até esta fatia. Aceitar e ignorar
    daria um run com parâmetros diferentes dos pedidos, sem erro — e um número
    silenciosamente errado é pior que uma recusa."""
    r = cliente.post("/api/workflows/conciliacao/runs", json={"seed": 2, "n": 60})

    assert r.status_code == 422


def _nao_vaza(detalhe: str, raiz) -> None:
    r"""Nenhum caminho do SERVIDOR pode aparecer num corpo de erro.

    Checa TRÊS grafias, e as três são necessárias. `str(raiz)` sozinho é uma
    asserção vazia no Windows: `OSError.__str__` interpola o nome do arquivo
    com `repr()`, então a mensagem do errno carrega `C:\\Users\\...` — com as
    barras DOBRADAS —, e a comparação contra a grafia simples passa enquanto o
    caminho inteiro está ali. Medido: trocar o `motivo` seguro do `_ler` por
    `str(erro)` deixava a suíte verde com a árvore de diretórios no corpo.

    A terceira grafia (`as_posix`) é o mesmo furo no CI, onde não há `\` para
    dobrar mas o separador da mensagem pode diferir do de `str()`.
    """
    for forma in (str(raiz), str(raiz).replace("\\", "\\\\"), raiz.as_posix()):
        assert forma not in detalhe, f"vazou {forma!r}"
        assert str(raiz.parent) not in detalhe


def test_a_fonte_SINTETICA_continua_medindo_contra_gabarito():
    """O caminho de hoje, com a forma nova. A conciliação não perde nada."""
    r = cliente.post("/api/workflows/conciliacao/runs", json={})

    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["contra_gabarito"] is not None
    assert corpo["contra_gabarito"]["bank_total"] > 0
    assert 0.0 <= corpo["contra_gabarito"]["deterministic_rate"] <= 1.0
    assert corpo["input_ref"].startswith("synth:")


def test_a_fonte_de_ARQUIVO_nao_inventa_taxa_de_acerto(tmp_path, monkeypatch):
    """Este teste provava que o arquivo é lido, hasheado e vira pool — usando um
    kind que NENHUM resolver consome, e recebendo 200 com lacuna de 100%. Era
    o "200 sobre um pool que ninguém leu" do README. Com a borda por resolver
    isso é 422, e a prova de que o arquivo É lido mora em
    `test_um_CSV_de_verdade_e_CONSUMIDO_e_produz_resolucao`, que consome o kind
    do arquivo e lê um campo dele.
    """
    import orchestrator.api.app as api_app

    raiz = tmp_path / "entradas"
    raiz.mkdir()
    (raiz / "itens.csv").write_text("id,texto\na,um\nb,dois\n", encoding="utf-8")
    monkeypatch.setattr(api_app, "_RAIZ_ENTRADAS", raiz)

    r = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"fonte": {"tipo": "arquivo", "caminho": "itens.csv",
                        "kind": "lancamento", "campo_id": "id"}},
    )

    assert r.status_code == 422, r.text
    detalhe = r.json()["detail"]
    assert "'L1'" in detalhe
    assert "lancamento" in detalhe


def test_caminho_fora_da_raiz_vira_422_e_nao_500(tmp_path, monkeypatch):
    import orchestrator.api.app as api_app

    raiz = tmp_path / "entradas"
    raiz.mkdir()
    monkeypatch.setattr(api_app, "_RAIZ_ENTRADAS", raiz)

    r = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"fonte": {"tipo": "arquivo", "caminho": "../segredo.csv",
                        "kind": "k", "campo_id": "id"}},
    )

    assert r.status_code == 422
    assert "raiz" in r.json()["detail"]


def test_arquivo_inexistente_vira_422_e_NAO_VAZA_a_raiz(tmp_path, monkeypatch):
    """Um caminho que passa na cerca mas não existe em disco.

    A leitura do `ArquivoSource` é preguiçosa — o `__post_init__` só confere a
    raiz —, então este caminho não falha na CONSTRUÇÃO: ele falha no `stat()`
    de `_bytes()`, e sem tratamento vira 500.

    A mensagem cita só o que o cliente pediu. `_RAIZ_ENTRADAS` é um caminho do
    SERVIDOR, e devolvê-lo num erro entrega a árvore de diretórios a quem
    sondar com nomes errados — a mesma informação que a cerca existe para
    negar, vazando pela porta dos fundos.
    """
    import orchestrator.api.app as api_app

    raiz = tmp_path / "entradas"
    raiz.mkdir()
    monkeypatch.setattr(api_app, "_RAIZ_ENTRADAS", raiz)

    r = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"fonte": {"tipo": "arquivo", "caminho": "nao-existe.csv",
                        "kind": "k", "campo_id": "id"}},
    )

    assert r.status_code == 422, r.text
    detalhe = r.json()["detail"]
    assert "nao-existe.csv" in detalhe
    _nao_vaza(detalhe, raiz)


def test_arquivo_malformado_vira_422_com_a_linha_e_NAO_500(tmp_path, monkeypatch):
    """O `ArquivoSource` recusa alto, com o número da linha. Essa recusa é
    sobre a ENTRADA do cliente, então ela é 422 — deixá-la subir daria 500, que
    diz "o servidor quebrou" sobre um arquivo que o usuário pode consertar."""
    import orchestrator.api.app as api_app

    raiz = tmp_path / "entradas"
    raiz.mkdir()
    (raiz / "itens.csv").write_text("id,texto\n,um\n", encoding="utf-8")
    monkeypatch.setattr(api_app, "_RAIZ_ENTRADAS", raiz)

    r = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"fonte": {"tipo": "arquivo", "caminho": "itens.csv",
                        "kind": "k", "campo_id": "id"}},
    )

    assert r.status_code == 422, r.text
    assert "linha 1" in r.json()["detail"]
    _nao_vaza(r.json()["detail"], raiz)


def test_o_custo_da_execucao_volta_na_resposta():
    """`Run.cost_by_resolver` já acumula entre rondas. Gasto que não aparece na
    tela é gasto que ninguém revisa."""
    corpo = cliente.post("/api/workflows/conciliacao/runs", json={}).json()

    assert "custo_microcents" in corpo
    assert corpo["custo_microcents"] >= 0


def test_a_fila_de_uma_fonte_de_arquivo_CONSUMIDA_e_ESCOPADA_por_conteudo(
    tmp_path, monkeypatch
):
    """A chave que o ENDPOINT de fato usa, observada — não recalculada.

    A primeira versão deste teste comparava `dataset_de_ref(ref_antes)` com
    `dataset_de_ref(ref_depois)`: duas funções puras contra elas mesmas. Ela
    passava com a chave da fila FIXADA em `"synth:s1-n30-t0.15"` dentro de
    `_executar` — ou seja, provava que o `ref` muda com o conteúdo e nada sobre
    a fila. Aqui o `caminho_da_fila` do módulo é espionado, então o que a
    asserção vê é o caminho que o servidor abriu.

    A propriedade é da FILA, não do kind — mas com a borda por resolver, um
    `kind` que nenhum bloco consome (`"k"`, contra a conciliação, o caso do
    teste original) nem chega a `_abrir_fila`: vira 422 antes. A observação
    migrou para cá, sobre a mesma cascata CONSUMIDORA de
    `test_um_CSV_de_verdade_e_CONSUMIDO_e_produz_resolucao` (`_triagem`,
    kind `issue`), onde a execução completa de verdade e a fila é aberta. O
    teste com o nome original (`..._ESCOPADA_por_conteudo`) continua
    existindo, agora provando a recusa — ver o docstring dele.
    """
    import orchestrator.api.app as api_app
    from orchestrator.review.fila import caminho_da_fila, dataset_de_ref

    raiz = tmp_path / "entradas"
    raiz.mkdir()
    alvo = raiz / "issues.csv"
    alvo.write_text("numero,prioridade\n1,baixa\n", encoding="utf-8")
    monkeypatch.setattr(api_app, "_RAIZ_ENTRADAS", raiz)
    _registrar(monkeypatch, "triagem", _triagem())

    abertas: list[tuple[str, str]] = []

    def _espiao(workflow_id, dataset, raiz=None):
        abertas.append((workflow_id, dataset))
        return caminho_da_fila(workflow_id, dataset, raiz=raiz)

    monkeypatch.setattr(api_app, "caminho_da_fila", _espiao)

    def _rodar() -> str:
        return cliente.post(
            "/api/workflows/triagem/runs",
            json={"fonte": {"tipo": "arquivo", "caminho": "issues.csv",
                            "kind": "issue", "campo_id": "numero"}},
        ).json()["input_ref"]

    antes = _rodar()
    alvo.write_text("numero,prioridade\n1,OUTRO\n", encoding="utf-8")
    depois = _rodar()

    assert antes != depois
    # O endpoint abriu UMA fila por execução, no workflow certo, com a chave
    # derivada do `ref` da fonte de ARQUIVO — nunca a de uma sintética.
    assert [w for w, _ in abertas] == ["triagem", "triagem"]
    assert [d for _, d in abertas] == [dataset_de_ref(antes), dataset_de_ref(depois)]
    assert abertas[0][1] != abertas[1][1]
    for _, chave in abertas:
        assert chave.startswith("file-")


def test_a_fila_de_uma_fonte_de_arquivo_e_ESCOPADA_por_conteudo(tmp_path, monkeypatch):
    """Este teste provava que o arquivo é lido, hasheado e vira pool — usando um
    kind que NENHUM resolver consome, e recebendo 200 com lacuna de 100%. Era
    o "200 sobre um pool que ninguém leu" do README. Com a borda por resolver
    isso é 422, e a prova de que o arquivo É lido mora em
    `test_um_CSV_de_verdade_e_CONSUMIDO_e_produz_resolucao`, que consome o kind
    do arquivo e lê um campo dele. A propriedade da FILA escopada por
    conteúdo, que este teste provava sobre um caminho `200` que não existe
    mais para este `kind`, sobrevive em
    `test_a_fila_de_uma_fonte_de_arquivo_CONSUMIDA_e_ESCOPADA_por_conteudo`.
    """
    import orchestrator.api.app as api_app

    raiz = tmp_path / "entradas"
    raiz.mkdir()
    alvo = raiz / "itens.csv"
    alvo.write_text("id,texto\na,um\n", encoding="utf-8")
    monkeypatch.setattr(api_app, "_RAIZ_ENTRADAS", raiz)

    r = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"fonte": {"tipo": "arquivo", "caminho": "itens.csv",
                        "kind": "k", "campo_id": "id"}},
    )

    assert r.status_code == 422, r.text
    detalhe = r.json()["detail"]
    assert "'L1'" in detalhe
    assert "'k'" in detalhe


def _registrar(monkeypatch, workflow_id: str, fabrica) -> None:
    """Acrescenta um workflow ao registro, preservando os reais.

    `registry()` monta um dict NOVO a cada chamada; envolver a função original
    é o mesmo padrão de
    `test_resolver_com_layer_diferente_do_name_e_reportado_pelo_proprio_nome`.
    """
    from orchestrator.workflows import registry as _original

    def _com_extra(raiz=None, raiz_composicoes=None):
        fabricas = _original(raiz, raiz_composicoes)
        fabricas[workflow_id] = fabrica
        return fabricas

    monkeypatch.setattr("orchestrator.api.app.registry", _com_extra)


def _triagem():
    """Uma cascata GENÉRICA: um resolver que lê o payload como MAPA.

    É a forma que uma fonte de arquivo entrega (`ArquivoSource` monta
    `payload=linha`, um `dict`) e a que `agent/declarado.py::_campos` já
    aceita — ou seja, o caminho principal de quem compõe no canvas sobre um
    CSV.
    """
    from orchestrator.kernel.cost import CostClass
    from orchestrator.kernel.definition import Stage, WorkflowDefinition
    from orchestrator.kernel.resolution import Resolution
    from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput

    class FechaBaixa:
        name = "fecha_baixa"
        cost_class = CostClass.REGRA

        def describe(self) -> ResolverDescription:
            # SEM `payloads`: este resolver não exige tipo nenhum, e é por isso
            # que ele roda sobre um CSV.
            return ResolverDescription(
                self.name, self.cost_class, "fecha prioridade baixa"
            )

        def resolve(self, work):
            return ResolverOutput(
                resolutions=[
                    Resolution(
                        item_ids=frozenset({i.id}),
                        produced_by=self.name,
                        rule="prioridade baixa fecha sozinha",
                    )
                    for i in work.items
                    if i.payload.get("prioridade") == "baixa"
                ]
            )

    def fabrica(ctx):
        return WorkflowDefinition(
            id="triagem",
            name="triagem de issues",
            stages=(Stage(name="triar", cascade=(FechaBaixa(),)),),
        )

    return fabrica


def test_um_CSV_de_verdade_e_CONSUMIDO_e_produz_resolucao(tmp_path, monkeypatch):
    """A evidência que esta fatia existe para produzir.

    Os outros testes de fonte de arquivo usam `kind` que NENHUM resolver
    consome (`lancamento`, `k`) — então eles provam que o arquivo é lido,
    hasheado e vira pool, e não provam que alguém o TOCA. Uma suíte verde
    inteira sobre um CSV que ninguém abre é a forma mais cara de teste que
    existe, e foi o que escondeu o `AttributeError` do `kind="banco"`.

    Aqui a cascata consome o kind do arquivo e lê um campo dele.
    """
    import orchestrator.api.app as api_app

    raiz = tmp_path / "entradas"
    raiz.mkdir()
    (raiz / "issues.csv").write_text(
        "numero,titulo,prioridade\n"
        "1,quebra no login,baixa\n"
        "2,vazamento de memoria,alta\n"
        "3,typo no rodape,baixa\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(api_app, "_RAIZ_ENTRADAS", raiz)
    _registrar(monkeypatch, "triagem", _triagem())

    r = cliente.post(
        "/api/workflows/triagem/runs",
        json={"fonte": {"tipo": "arquivo", "caminho": "issues.csv",
                        "kind": "issue", "campo_id": "numero"}},
    )

    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["itens"] == 3
    # As duas de prioridade baixa foram resolvidas LENDO o campo do CSV. Se o
    # arquivo não fosse tocado, isto seria 0.
    assert corpo["resolvidos"] == 2
    assert corpo["gap"]["items"] == 1
    (linha,) = corpo["por_resolver"]
    assert (linha["name"], linha["matches"]) == ("fecha_baixa", 2)
    assert linha["rate"] == pytest.approx(2 / 3)
    assert corpo["contra_gabarito"] is None
    assert corpo["input_ref"].startswith("file:issues.csv@")
    soma = sum(x["rate"] for x in corpo["por_resolver"]) + corpo["gap"]["rate"]
    assert soma == pytest.approx(1.0)


def test_a_borda_recusa_bloco_que_a_fonte_NAO_alimenta(tmp_path, monkeypatch):
    """A frase do README que esta fatia apaga: "200 com lacuna de 100% sobre
    um pool que ninguém leu". Um CSV de issues na conciliação: L1 consome
    {banco, contabil}, a fonte entrega {issue}. Antes desta guarda o stage não
    enxergava nada, não rodava, e a resposta era 200 com tudo por resolver —
    um número com cara de medido sobre o que não foi medido."""

    _csv_de_issues(tmp_path, monkeypatch, linhas=2)

    r = cliente.post("/api/workflows/conciliacao/runs", json={"fonte": _FONTE_ISSUES})

    assert r.status_code == 422, r.text
    detalhe = r.json()["detail"]
    assert "'L1'" in detalhe and "banco" in detalhe and "issue" in detalhe


def test_a_borda_e_POR_RESOLVER_e_nao_pela_uniao_do_degrau(tmp_path, monkeypatch):
    """Pela união do degrau, um agente cego dentro de um degrau vivo passaria:
    L1 consome banco, a fonte traz banco, união satisfeita — e o agente que
    consome outra coisa roda sem ver item nenhum. Era o catálogo até a Task 3.
    Aqui uma receita `L1 + triador` sobre a fonte SINTÉTICA: L1 é alimentado,
    o triador (issue) não — e é o triador que a mensagem nomeia."""
    import orchestrator.api.app as api_app

    monkeypatch.setattr(api_app, "_RAIZ_RECEITAS", tmp_path / "receitas")
    criada = cliente.post("/api/receitas", json={
        "id": "mista", "nome": "m", "justificativa": "j",
        "resolvers": [{"nome": "L1"}, {"nome": "triador"}]})
    assert criada.status_code == 201, criada.text
    # `_executar` constrói o cliente ANTES da borda: sem este stub, a tranca de
    # rede do conftest levantaria `RedeProibida` no `AnthropicClient()` e o
    # teste morreria antes do 422. `_cliente_falso` também stuba `_tem_chave`.
    _cliente_falso(monkeypatch, [])

    r = cliente.post("/api/workflows/mista/runs", json={"teto_microcents": 1_000_000})

    assert r.status_code == 422, r.text
    detalhe = r.json()["detail"]
    assert "'triador'" in detalhe and "issue" in detalhe and "banco" in detalhe


def test_pool_VAZIO_e_recusado_e_nao_um_run_concluido_com_zero(tmp_path, monkeypatch):
    """Um CSV só com cabeçalho não é uma execução: é ausência de trabalho.
    Devolver 200 com zero itens seria outro número com cara de medido."""
    import orchestrator.api.app as api_app

    raiz = tmp_path / "entradas"
    raiz.mkdir()
    (raiz / "vazio.csv").write_text("id,titulo\n", encoding="utf-8")
    monkeypatch.setattr(api_app, "_RAIZ_ENTRADAS", raiz)

    r = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"fonte": {"tipo": "arquivo", "caminho": "vazio.csv",
                        "kind": "banco", "campo_id": "id"}},
    )

    assert r.status_code == 422, r.text
    assert "item nenhum" in r.json()["detail"]


def test_o_run_de_um_CSV_e_PERSISTIDO_com_o_ref_do_arquivo(tmp_path, monkeypatch):
    """A execução sobre arquivo entra no histórico como qualquer outra."""
    import orchestrator.api.app as api_app

    raiz = tmp_path / "entradas"
    raiz.mkdir()
    (raiz / "issues.csv").write_text("numero,prioridade\n1,baixa\n", encoding="utf-8")
    monkeypatch.setattr(api_app, "_RAIZ_ENTRADAS", raiz)
    _registrar(monkeypatch, "triagem", _triagem())

    corpo = cliente.post(
        "/api/workflows/triagem/runs",
        json={"fonte": {"tipo": "arquivo", "caminho": "issues.csv",
                        "kind": "issue", "campo_id": "numero"}},
    ).json()

    (resumo,) = cliente.get("/api/runs", params={"workflow_id": "triagem"}).json()
    assert resumo["input_ref"] == corpo["input_ref"]
    assert resumo["resolved"] == 1


def test_payload_de_dict_contra_resolver_TIPADO_e_422_e_nao_500(tmp_path, monkeypatch):
    """A combinação que estourava.

    `ArquivoSource` entrega dicionário; um resolver TIPADO lê `be.document`. Com
    `kind="banco"` o CSV cai direto no `banco()` da conciliação e o resultado
    era um 500 de `AttributeError`, vindo de três camadas abaixo de quem
    escolheu as duas pontas.

    A recusa nomeia o RESOLVER e o KIND, porque é a combinação que está errada
    e não nenhuma das duas escolhas sozinha.

    **Quem é nomeado mudou, e a mudança é o ganho.** Era o `L1`, e hoje é o
    `L2`: o L1 virou `regras.Igualdade` configurada com nomes de campo, então
    ele não exige tipo nenhum e passa a rodar sobre o dicionário do CSV. Quem
    ainda recusa é o L2, que continua tipado porque conta dias úteis. A
    asserção abaixo cobra as duas metades — o L2 recusando E o L1 não
    aparecendo —, porque só a primeira deixaria passar uma regressão que
    retipasse o L1.
    """
    import orchestrator.api.app as api_app

    raiz = tmp_path / "entradas"
    raiz.mkdir()
    (raiz / "itens.csv").write_text("id,texto\na,um\n", encoding="utf-8")
    monkeypatch.setattr(api_app, "_RAIZ_ENTRADAS", raiz)

    r = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"fonte": {"tipo": "arquivo", "caminho": "itens.csv",
                        "kind": "banco", "campo_id": "id"}},
    )

    assert r.status_code == 422, r.text
    detalhe = r.json()["detail"]
    assert "L2" in detalhe
    assert "L1" not in detalhe
    assert "banco" in detalhe
    assert "BankEntry" in detalhe
    assert "dict" in detalhe


def test_a_fonte_SINTETICA_atravessa_a_mesma_conferencia_de_payload():
    """A guarda não pode ter transformado o caminho de hoje em 422 — ela é uma
    recusa de COMBINAÇÃO, e `SyntheticSource` entrega exatamente os tipos que a
    conciliação declara exigir."""
    r = cliente.post("/api/workflows/conciliacao/runs", json={})

    assert r.status_code == 200, r.text


def test_um_resolver_que_NAO_declara_payload_nao_e_conferido(tmp_path, monkeypatch):
    """O outro lado da guarda, e o que a mantém honesta.

    Exigir declaração de todo resolver tornaria impossível rodar qualquer
    cascata genérica sobre um arquivo — que é a tese desta fatia. `payloads`
    vazio significa "não inspeciono o payload", e um resolver assim roda sobre
    qualquer fonte.
    """
    import orchestrator.api.app as api_app
    from orchestrator.kernel.resolver import ResolverDescription

    fabrica = _triagem()
    (stage,) = fabrica(None).stages
    (resolver,) = stage.cascade
    assert resolver.describe().payloads == {}
    # E o default da própria descrição, para o dia em que alguém "arrumar" o
    # campo para exigir valor.
    assert ResolverDescription("x", resolver.cost_class, "y").payloads == {}

    raiz = tmp_path / "entradas"
    raiz.mkdir()
    (raiz / "issues.csv").write_text("numero,prioridade\n1,baixa\n", encoding="utf-8")
    monkeypatch.setattr(api_app, "_RAIZ_ENTRADAS", raiz)
    _registrar(monkeypatch, "triagem", fabrica)

    r = cliente.post(
        "/api/workflows/triagem/runs",
        json={"fonte": {"tipo": "arquivo", "caminho": "issues.csv",
                        "kind": "issue", "campo_id": "numero"}},
    )

    assert r.status_code == 200, r.text


def test_campo_desconhecido_DENTRO_da_fonte_e_recusado():
    """A trava um nível abaixo do `RunRequest`.

    `extra="forbid"` no `RunRequest` de fora não desce para os modelos da
    união: sem a trava nos dois, `{"tipo": "sintetica", "sede": 2}` dropava
    `sede` em silêncio e rodava com `seed=1` — um run com parâmetro diferente
    do pedido, exatamente o defeito que a trava de fora existe para impedir.
    """
    r = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"fonte": {"tipo": "sintetica", "sede": 2}},
    )

    assert r.status_code == 422, r.text
    assert "sede" in r.text


def test_campo_desconhecido_dentro_da_fonte_de_ARQUIVO_e_recusado():
    """O irmão do de cima. Aqui os quatro campos são obrigatórios, então um
    typo já levava 422 por ausência; o que a trava fecha é o campo A MAIS —
    um `max_linhas` que o cliente acha que está configurando um teto."""
    r = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"fonte": {"tipo": "arquivo", "caminho": "x.csv", "kind": "k",
                        "campo_id": "id", "max_linhas": 10}},
    )

    assert r.status_code == 422, r.text
    assert "max_linhas" in r.text


def test_uma_falha_da_fonte_SINTETICA_sobe_como_erro_de_SERVIDOR(monkeypatch):
    """O `_ler` traduz falha de leitura em 422, e só para a fonte de ARQUIVO.

    Uma fonte sintética não toca o disco: se ela levanta, é defeito do
    servidor. Traduzir isso em 422 diria ao cliente que o pedido dele estava
    errado sobre um bug que não é dele — um erro confiante, que é pior que o
    500 honesto.
    """
    from orchestrator.domains.reconciliation.synth.benchmark import SyntheticSource

    def _explode(self):
        raise ValueError("defeito do gerador, não do pedido")

    monkeypatch.setattr(SyntheticSource, "load", _explode)

    with pytest.raises(ValueError, match="defeito do gerador"):
        cliente.post("/api/workflows/conciliacao/runs", json={})


def _transformador():
    """Um stage que CONSOME `issue` e PRODUZ `banco`, com payload de dicionário.

    `produced` e `WorkSet.com()` existem desde a fatia do grafo: um resolver
    pode criar itens de outro `kind`, e o stage seguinte os consome.
    """
    from orchestrator.domains.reconciliation.resolvers.exact import ExactMatcher
    from orchestrator.kernel.cost import CostClass
    from orchestrator.kernel.definition import Stage, WorkflowDefinition
    from orchestrator.kernel.resolution import Resolution
    from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
    from orchestrator.kernel.work import WorkItem

    class Transforma:
        name = "transforma"
        cost_class = CostClass.REGRA

        def describe(self) -> ResolverDescription:
            return ResolverDescription(self.name, self.cost_class, "issue vira lançamento")

        def resolve(self, work):
            return ResolverOutput(
                resolutions=[
                    Resolution(item_ids=frozenset({i.id}), produced_by=self.name, rule="t")
                    for i in work.items
                ],
                produced=tuple(
                    # Payload de DICIONÁRIO, que é o que uma fonte de arquivo
                    # entrega e o que este resolver genérico repassa.
                    WorkItem(id=f"b-{i.id}", kind="banco", payload=dict(i.payload),
                             origem=self.name)
                    for i in work.items
                ),
            )

    def fabrica(ctx):
        return WorkflowDefinition(
            id="produz",
            name="produz lançamento a partir de issue",
            stages=(
                Stage(name="transformar", cascade=(Transforma(),),
                      consome=frozenset({"issue"}), produz=frozenset({"banco"})),
                # L1 EXIGE `BankEntry` para o kind `banco` — e vai receber dict.
                Stage(name="conciliar", cascade=(ExactMatcher(),),
                      consome=frozenset({"banco"})),
            ),
        )

    return fabrica


@pytest.mark.xfail(
    strict=True,
    reason=(
        "LACUNA CONHECIDA: `_conferir_payload` inspeciona o pool INICIAL. Um "
        "stage que PRODUZ itens os injeta depois da conferência, então um "
        "produtor genérico alimentando um consumidor tipado traz de volta o "
        "500 original. Fechar isso exige uma declaração do lado do PRODUTOR "
        "(que tipo ele emite por kind), que não existe, e o ponto de "
        "aplicação seria `runtime/engine.py` — onde `produced` entra no pool "
        "e onde o motor, por desenho, nunca inspeciona payload. Inalcançável "
        "por configuração publicada: nenhum bloco do catálogo produz."
    ),
)
def test_um_stage_PRODUTOR_ainda_fura_a_conferencia_de_payload(tmp_path, monkeypatch):
    """A borda protege o que entra pela FONTE, não o que nasce no meio do run.

    Este teste falha de propósito, e o `strict=True` é o catraca: no dia em que
    alguém fechar a lacuna, ele passa a dar XPASS e a suíte fica vermelha até
    que a marcação saia junto. Um `xfail` frouxo viraria um teste que ninguém
    percebe ter sido consertado — ou quebrado de novo.
    """
    import orchestrator.api.app as api_app

    raiz = tmp_path / "entradas"
    raiz.mkdir()
    (raiz / "issues.csv").write_text("id,texto\n1,um\n", encoding="utf-8")
    monkeypatch.setattr(api_app, "_RAIZ_ENTRADAS", raiz)
    _registrar(monkeypatch, "produz", _transformador())

    local = TestClient(api_app.app, raise_server_exceptions=False)
    r = local.post(
        "/api/workflows/produz/runs",
        json={"fonte": {"tipo": "arquivo", "caminho": "issues.csv",
                        "kind": "issue", "campo_id": "id"}},
    )

    # O que DEVERIA acontecer. Hoje é 500, com `AttributeError: 'dict' object
    # has no attribute 'document'` vindo de `matching/exact.py`.
    assert r.status_code == 422, r.status_code


def test_a_lacuna_do_produtor_nao_e_alcancavel_pelo_CATALOGO():
    """O que torna a lacuna acima documentável em vez de urgente.

    Nenhum bloco do catálogo produz item nenhum: `produz` é declarado no
    `Stage`, e as duas vias de composição (`grill.receita.construir` e
    `authoring.composicao.construir_composicao`) montam stages sem ele. Se
    isso mudar, a lacuna passa a ser alcançável pela tela e este teste é quem
    avisa.
    """
    # `descrever` em vez de `registry` + `construir_definicao`: ela isola a
    # receita que não constrói, então uma receita quebrada no `data/` de um
    # desenvolvedor não transforma esta asserção num erro sobre outro assunto.
    from orchestrator.workflows import descrever

    for workflow_id, definicao in descrever():
        for stage in definicao.stages:
            assert stage.produz == frozenset(), (workflow_id, stage.name)


# ===========================================================================
# EXECUTAR COM AGENTE, COM TETO
#
# A regra deste módulo ficou MAIS PRECISA, não mais frouxa. Era "nenhum
# endpoint gasta dinheiro", e o 409 de "etapa paga" era a porta. Agora:
#
#     EXECUTAR pela web GASTA quando a cascata tem agente, com teto, e o teto
#     é dito antes.
#
# As três guardas são as de `api/entrevista.py`, e nenhuma é opcional:
#   1. teto por unidade de trabalho, aplicado por REQUISIÇÃO;
#   2. o custo volta em CADA desfecho — inclusive no que falhou;
#   3. sem chave, recusa legível.
# ===========================================================================


# 100 tokens de entrada + 50 de saída em `claude-opus-5`: 100*500 + 50*2500.
# Escrito uma vez, derivado da tabela de preços, usado nas asserções de teto.
_POR_CHAMADA = 100 * 500 + 50 * 2500  # 175.000 µ¢


def _resposta(tipo: str = "BUG", *, entrada: int = 100, saida: int = 50):
    """Uma resposta de modelo válida para o vocabulário do `triador`."""
    from orchestrator.agent.llm import LLMResponse
    from orchestrator.kernel.cost import Cost

    return LLMResponse(
        text=(
            '{"tipo": "' + tipo + '", "explicacao": "porque sim", '
            '"evidencia": ["o titulo"], "confianca": "ALTA"}'
        ),
        tool_calls=[],
        cost=Cost(input_tokens=entrada, output_tokens=saida),
    )


def _declarado(**kw):
    from orchestrator.agent.declarado import AgenteDeclarado

    base = dict(
        name="gastador",
        system="classifique",
        kind="issue",
        prompt="{titulo}",
        tipos=("BUG", "FEATURE"),
        abstem_com="NAO_SEI",
        max_turns=1,
    )
    base.update(kw)
    return AgenteDeclarado(**base)


def _fabrica_com_agentes(*declaracoes, workflow_id="com-agente"):
    """Uma cascata de agentes declarados que HONRA `ctx.cliente_para`.

    É a mesma costura de `workflows._de_receita`: `None` continua significando
    `ClienteAusente` — a tranca —, e quem executa passa um cliente de verdade.
    """
    from orchestrator.agent.declarado import construir_agente
    from orchestrator.grill.catalogo import ClienteAusente
    from orchestrator.kernel.definition import Stage, WorkflowDefinition

    def fabrica(ctx):
        # A MESMA costura de `workflows._de_receita`: a fábrica é chamada com o
        # modelo que o bloco declarou, e `None` continua significando a tranca.
        para = ctx.cliente_para or (lambda _model: ClienteAusente())
        return WorkflowDefinition(
            id=workflow_id,
            name="cascata com agente",
            stages=(
                Stage(
                    name="triar",
                    cascade=tuple(
                        construir_agente(d, para(d.model)) for d in declaracoes
                    ),
                ),
            ),
        )

    return fabrica


def _csv_de_issues(tmp_path, monkeypatch, linhas: int = 3) -> None:
    import orchestrator.api.app as api_app

    raiz = tmp_path / "entradas"
    raiz.mkdir(exist_ok=True)
    corpo = "numero,titulo,corpo\n" + "".join(
        f"{i},titulo {i},corpo {i}\n" for i in range(1, linhas + 1)
    )
    (raiz / "issues.csv").write_text(corpo, encoding="utf-8")
    monkeypatch.setattr(api_app, "_RAIZ_ENTRADAS", raiz)


_FONTE_ISSUES = {
    "tipo": "arquivo",
    "caminho": "issues.csv",
    "kind": "issue",
    "campo_id": "numero",
}


def _cliente_falso(monkeypatch, respostas, teto_visto: dict | None = None):
    """Troca SÓ a ponta de rede. O teto continua passando por `ClienteComTeto`.

    Monkeypatchar `_cliente_de_execucao` para devolver um `FakeLLMClient` cru
    provaria o roteamento e nada sobre o teto — o teto seria um argumento que
    o teste recebe e joga fora. Aqui o embrulho REAL é construído, com o teto
    REAL do pedido, e só o cliente de dentro é falso.
    """
    import orchestrator.api.app as api_app
    from orchestrator.agent.llm import FakeLLMClient
    from orchestrator.agent.teto import ClienteComTeto, Orcamento

    fake = FakeLLMClient(list(respostas))

    def _de_execucao(teto):
        if teto_visto is not None:
            teto_visto["teto"] = teto
        # Um orçamento para a requisição, e uma fábrica que devolve o MESMO
        # embrulho para qualquer modelo: estes testes medem teto e gasto, não
        # roteamento de modelo.
        orcamento = Orcamento(teto)
        return (lambda _model: ClienteComTeto(fake, orcamento=orcamento)), orcamento

    monkeypatch.setattr(api_app, "_tem_chave", lambda: True)
    monkeypatch.setattr(api_app, "_cliente_de_execucao", _de_execucao)
    return fake


# -- guarda 3: sem chave, recusa legível ------------------------------------


def test_sem_chave_a_execucao_com_agente_e_recusada_com_MOTIVO(tmp_path, monkeypatch):
    """Guarda 3, a mesma do chat. Sem chave, recusa legível — em vez de o SDK
    levantar no meio do laço com o trabalho já pela metade.

    A fonte precisa alimentar o agente (`kind="issue"`) — desde a borda de
    `_conferir_kinds` a fonte sintética padrão (`banco`/`contabil`) não faz
    isso, e este teste não é sobre kind nenhum."""
    import orchestrator.api.app as api_app

    _csv_de_issues(tmp_path, monkeypatch, linhas=1)
    monkeypatch.setattr(api_app, "_tem_chave", lambda: False)
    _registrar(monkeypatch, "com-agente", _fabrica_com_agentes(_declarado()))

    # COM teto: o teto é exigência do PEDIDO e é conferida antes, então um
    # pedido sem ele levaria 422 e este teste não chegaria a observar o 409.
    r = cliente.post(
        "/api/workflows/com-agente/runs",
        json={"fonte": _FONTE_ISSUES, "teto_microcents": 1_000_000},
    )

    assert r.status_code == 409, r.text
    assert "chave" in r.json()["detail"].lower()
    # E o texto diz o que fazer, nas DUAS saídas: configurar, ou rodar pela CLI.
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_cascata_SEM_agente_nao_exige_chave(monkeypatch):
    """A regra ficou mais precisa, não mais frouxa: só gasta quem tem agente."""
    import orchestrator.api.app as api_app

    monkeypatch.setattr(api_app, "_tem_chave", lambda: False)

    r = cliente.post("/api/workflows/conciliacao/runs", json={})

    assert r.status_code == 200, r.text


def test_sem_agente_o_cliente_de_execucao_NUNCA_e_construido(monkeypatch):
    """A tranca, não a porta. `ClienteAusente` continua sendo o default, e
    `_cliente_de_execucao` — o único caminho daqui até o modelo — não é sequer
    chamado quando não há agente na cascata."""
    import orchestrator.api.app as api_app

    def _proibido(teto):  # pragma: no cover - o teste falha se isto rodar
        raise AssertionError("cascata sem agente construiu cliente de execução")

    monkeypatch.setattr(api_app, "_cliente_de_execucao", _proibido)
    monkeypatch.setattr(api_app, "_tem_chave", lambda: True)

    assert cliente.post("/api/workflows/conciliacao/runs", json={}).status_code == 200


# -- guarda 1: o teto, dito antes ------------------------------------------


def test_o_teto_do_pedido_chega_ao_agente(tmp_path, monkeypatch):
    """Guarda 1. O teto é dito ANTES, e é o do pedido que vale — não o default
    do agente, que é generoso por ser um default."""
    _csv_de_issues(tmp_path, monkeypatch, linhas=1)
    vistos: dict = {}
    _cliente_falso(monkeypatch, [_resposta()], teto_visto=vistos)
    _registrar(
        monkeypatch, "com-teto", _fabrica_com_agentes(_declarado(), workflow_id="com-teto")
    )

    cliente.post(
        "/api/workflows/com-teto/runs",
        json={"fonte": _FONTE_ISSUES, "teto_microcents": 12345},
    )

    assert vistos["teto"] == 12345


def test_o_teto_do_pedido_PARA_o_gasto(tmp_path, monkeypatch):
    """O teto não é decoração: ele para de gastar.

    Três issues, uma chamada por issue, 175.000 µ¢ cada. Com teto de 100.000 µ¢
    a PRIMEIRA passa — nada tinha sido gasto ainda — e as duas seguintes nem
    chegam ao modelo.

    E é por isso que o gasto final (175.000) fica ACIMA do teto (100.000): não
    há como saber o custo de uma chamada sem fazê-la, então o teto é conferido
    ANTES de cada uma e a última pode ultrapassá-lo por um turno. É a mesma
    forma do orçamento por item em `agent/conversa.py`, está dita no
    `ClienteComTeto`, e o teste a fixa em vez de escolher números que a
    escondam — um teto lido como "limite exato" viraria um relatório de bug.
    """
    _csv_de_issues(tmp_path, monkeypatch, linhas=3)
    fake = _cliente_falso(monkeypatch, [_resposta()] * 3)
    _registrar(monkeypatch, "com-agente", _fabrica_com_agentes(_declarado()))

    r = cliente.post(
        "/api/workflows/com-agente/runs",
        json={"fonte": _FONTE_ISSUES, "teto_microcents": 100_000},
    )

    assert r.status_code == 200, r.text
    assert len(fake.chamadas) == 1
    assert r.json()["custo_microcents"] == _POR_CHAMADA > 100_000


def test_pedido_com_agente_SEM_teto_e_RECUSADO_pela_web(tmp_path, monkeypatch):
    """"Gasta com teto, E O TETO É DITO ANTES" — a segunda metade é a regra.

    Um pedido que omite `teto_microcents` não disse teto nenhum: ele HERDA o do
    agente, que é 400.000.000 µ¢ = **US$ 4,00 por requisição**. Sem esta guarda,
    `POST /api/workflows/<pago>/runs` com corpo `{}`, sem autenticação, sem
    cache e sem limite de taxa, é uma torneira de US$ 4 por F5 — e a herança
    silenciosa é exatamente o fallback que a primeira regra do projeto proíbe.

    A recusa é 422 e não 409: falta um campo do PEDIDO. E vem ANTES da guarda de
    chave, pela mesma ordem que o resto desta rota segue — erro do pedido antes
    de erro do ambiente. A `fonte` vai no corpo (alimenta o agente, kind
    `issue`), e o que falta continua sendo só o teto.
    """
    import orchestrator.api.app as api_app

    _csv_de_issues(tmp_path, monkeypatch, linhas=1)
    monkeypatch.setattr(api_app, "_tem_chave", lambda: True)
    _registrar(monkeypatch, "com-agente", _fabrica_com_agentes(_declarado()))

    r = cliente.post(
        "/api/workflows/com-agente/runs", json={"fonte": _FONTE_ISSUES}
    )

    assert r.status_code == 422, r.text
    # A recusa diz O QUE MANDAR, com a unidade. Uma recusa que não diz isso
    # manda a pessoa adivinhar entre dólar, centavo e micro-centavo.
    assert "teto_microcents" in r.json()["detail"]
    assert "micro-centavos" in r.json()["detail"]


def test_o_teto_AUSENTE_continua_valido_para_quem_NAO_e_a_web(monkeypatch):
    """A exigência é da BORDA HTTP, não do schema nem da biblioteca.

    `RunRequest.teto_microcents` continua aceitando `None`, e `ClienteComTeto`
    continua traduzindo `None` como "o teto do agente" — para a CLI e para quem
    chama a biblioteca, escolher o teto do agente é escolha legítima de quem já
    sabe qual é. O que não é legítimo é um cliente HTTP anônimo fazer essa
    escolha sem escrevê-la.

    E uma cascata SEM agente não precisa de teto nenhum, porque não há o que
    limitar: exigi-lo ali seria cerimônia sobre uma execução que não gasta.
    """
    from orchestrator.api.schemas import RunRequest

    assert RunRequest().teto_microcents is None
    assert cliente.post("/api/workflows/conciliacao/runs", json={}).status_code == 200


def test_um_teto_GENEROSO_nao_desliga_o_teto_do_AGENTE(tmp_path, monkeypatch):
    """Não existe valor que signifique "sem teto" — nem um valor enorme.

    Cinco issues, um agente com teto total de 200.000 µ¢, e um teto de pedido
    mil vezes maior. O gasto para em DUAS chamadas: o teto do agente continua
    operante por baixo do teto da requisição, e os dois são pisos um do outro,
    nunca substituição.
    """
    _csv_de_issues(tmp_path, monkeypatch, linhas=5)
    fake = _cliente_falso(monkeypatch, [_resposta()] * 5)
    _registrar(
        monkeypatch,
        "com-agente",
        _fabrica_com_agentes(_declarado(budget_total_microcents=200_000)),
    )

    r = cliente.post(
        "/api/workflows/com-agente/runs",
        json={"fonte": _FONTE_ISSUES, "teto_microcents": 200_000_000},
    )

    assert r.status_code == 200, r.text
    # 2 chamadas: a 3ª encontra 350.000 > 200.000 e abstém sem chamar o modelo.
    assert len(fake.chamadas) == 2
    assert r.json()["custo_microcents"] == 2 * _POR_CHAMADA
    # E quem parou foi o AGENTE, não o teto do pedido — que nem chegou perto.
    assert r.json()["teto_atingido"] is False


def test_o_embrulho_de_teto_nao_inventa_ilimitado():
    """A outra metade da mesma garantia, na unidade: `teto=None` deixa o teto
    do agente valer, e nunca troca um teto por ausência de teto."""
    import orchestrator.api.app as api_app
    from orchestrator.agent.teto import ClienteComTeto

    # Construir NÃO fala com rede: `AnthropicClient` só instancia o SDK na
    # primeira chamada, e aqui nenhuma é feita.
    # Devolve a FÁBRICA e o orçamento: com `model` por bloco, um cliente só
    # faria todo bloco falar com o mesmo modelo.
    para, orcamento = api_app._cliente_de_execucao(None)

    assert isinstance(para(""), ClienteComTeto)
    assert orcamento.teto_microcents is None
    assert api_app._cliente_de_execucao(7)[1].teto_microcents == 7
    # E o mesmo modelo devolve o MESMO cliente: uma cascata de dez blocos
    # iguais não abre dez clientes.
    outra, _ = api_app._cliente_de_execucao(None)
    assert outra("claude-haiku-4-5") is outra("claude-haiku-4-5")


# -- guarda 2: o custo volta em CADA desfecho -------------------------------


def test_um_run_que_GASTOU_e_FALHOU_devolve_quanto_gastou(tmp_path, monkeypatch):
    """Guarda 2, e é o buraco que o plano não cobria.

    Gasto que não aparece na tela é gasto que ninguém revisa. Sem isto, uma
    cascata que gasta e depois levanta devolve um 500 nu e o dinheiro morre
    com a exceção.

    O segundo agente cita no prompt um campo que o CSV não tem —
    `declarado._units` levanta `KeyError` de propósito, em vez de mandar ao
    modelo um prompt com buracos. É um caminho de erro REAL e alcançável por
    configuração: basta compor um agente cujo template não case com as colunas
    do arquivo. Note que um cliente que levanta DENTRO de `complete` não serve
    para provar isto: `agent/conversa.py` captura exatamente essa chamada e a
    transforma em abstenção, de propósito.
    """
    _csv_de_issues(tmp_path, monkeypatch, linhas=2)
    _cliente_falso(monkeypatch, [_resposta()] * 2)
    _registrar(
        monkeypatch,
        "com-agente",
        _fabrica_com_agentes(
            _declarado(),
            _declarado(name="quebrado", prompt="{coluna_que_nao_existe}"),
        ),
    )

    r = cliente.post(
        "/api/workflows/com-agente/runs",
        json={"fonte": _FONTE_ISSUES, "teto_microcents": 10_000_000},
    )

    assert r.status_code == 500, r.text
    detalhe = r.json()["detail"]
    assert detalhe["custo_microcents"] == 2 * _POR_CHAMADA
    assert "KeyError" in detalhe["motivo"]


def test_um_run_que_falhou_SEM_gastar_reporta_zero_MEDIDO(monkeypatch):
    """O outro lado: zero aqui é MEDIDO, não inventado.

    Sem agente na cascata não existe caminho até o modelo — `ClienteAusente` é
    a tranca —, então `0` é o gasto de fato, e não um número que finge medição
    onde nada foi medido.
    """
    import orchestrator.api.app as api_app

    def _explode(*a, **kw):
        raise RuntimeError("defeito do motor")

    monkeypatch.setattr(api_app, "execute", _explode)

    r = cliente.post("/api/workflows/conciliacao/runs", json={})

    assert r.status_code == 500, r.text
    assert r.json()["detail"]["custo_microcents"] == 0


def test_um_run_que_GASTOU_e_deu_certo_fica_no_HISTORICO_com_o_custo(
    tmp_path, monkeypatch
):
    """A outra metade da guarda 2: no caminho feliz o custo não depende de o
    corpo da resposta sobreviver — ele está no store, e `/api/runs` o devolve.
    """
    _csv_de_issues(tmp_path, monkeypatch, linhas=2)
    _cliente_falso(monkeypatch, [_resposta()] * 2)
    _registrar(monkeypatch, "com-agente", _fabrica_com_agentes(_declarado()))

    corpo = cliente.post(
        "/api/workflows/com-agente/runs",
        json={"fonte": _FONTE_ISSUES, "teto_microcents": 10_000_000},
    ).json()

    (resumo,) = cliente.get("/api/runs", params={"workflow_id": "com-agente"}).json()
    assert resumo["microcents"] == corpo["custo_microcents"] == 2 * _POR_CHAMADA
    # `proposed == 2` sozinho valeria igual para um agente que absteve nas duas
    # — abstenção É uma `Proposal`. O que ele diz é o que separa as duas.
    assert resumo["proposed"] == 2
    assert corpo["propostas_por_tipo"] == {"BUG": 2}
    assert corpo["falhas"] == 0


# -- a ordem entre o 409 e o 422 -------------------------------------------


def test_o_422_de_PAYLOAD_vem_ANTES_do_409_de_chave(tmp_path, monkeypatch):
    """A ordem mudou junto com o significado do 409, e de propósito.

    Antes, o 409 dizia "esta cascata é paga e nunca roda por aqui" — uma
    propriedade permanente da cascata, que precede qualquer coisa sobre o
    formato do dado. Agora ele diz "falta uma chave NO SERVIDOR" — estado do
    hospedeiro, não do pedido. Devolver isso primeiro mandaria o usuário
    procurar o administrador para depois descobrir que o CSV dele seria
    recusado de qualquer jeito.

    Erro do PEDIDO antes de erro do AMBIENTE.

    O `teto_microcents` vai no corpo porque a guarda de teto passou a rodar
    ANTES da fonte (ela é checagem pura sobre o pedido, e conectar no banco do
    parceiro para depois recusar por um campo ausente é gastar recurso de
    terceiro à toa). Sem ele, o 422 que voltaria seria o do teto, e este teste
    — que é sobre payload-vs-chave — não chegaria a observar o que mede.
    """
    import orchestrator.api.app as api_app
    from orchestrator.agent.declarado import construir_agente
    from orchestrator.domains.reconciliation.resolvers.exact import ExactMatcher
    from orchestrator.grill.catalogo import ClienteAusente
    from orchestrator.kernel.definition import Stage, WorkflowDefinition

    raiz = tmp_path / "entradas"
    raiz.mkdir()
    (raiz / "itens.csv").write_text("id,texto\na,um\n", encoding="utf-8")
    monkeypatch.setattr(api_app, "_RAIZ_ENTRADAS", raiz)
    monkeypatch.setattr(api_app, "_tem_chave", lambda: False)

    def fabrica(ctx):
        # A MESMA costura de `workflows._de_receita`: a fábrica é chamada com o
        # modelo que o bloco declarou, e `None` continua significando a tranca.
        para = ctx.cliente_para or (lambda _model: ClienteAusente())
        return WorkflowDefinition(
            id="misto",
            name="regra tipada mais agente",
            stages=(
                Stage(
                    name="s",
                    cascade=(
                        ExactMatcher(),
                        construir_agente(_declarado(), para(_declarado().model)),
                    ),
                ),
            ),
        )

    _registrar(monkeypatch, "misto", fabrica)

    r = cliente.post(
        "/api/workflows/misto/runs",
        json={"fonte": {"tipo": "arquivo", "caminho": "itens.csv",
                        "kind": "banco", "campo_id": "id"},
              "teto_microcents": 1_000_000},
    )

    assert r.status_code == 422, r.text
    assert "L1" in r.json()["detail"]


# -- o objetivo da fatia: compor na tela e rodar sobre um arquivo -----------


def test_um_CSV_de_issues_roda_no_TRIADOR_composto_pela_WEB(tmp_path, monkeypatch):
    """A evidência do objetivo desta fatia, de ponta a ponta.

    Até aqui NENHUM bloco do catálogo executável por `/runs` consumia
    dicionário: as seis regras exigem payload tipado, e os três agentes são
    `AGENTE` — barrados pelo 409. O teste de CSV da Task 3 precisou de um
    resolver construído dentro do próprio teste, então a máquina estava
    provada e nenhuma configuração ENTREGUE estava.

    Com o 409 fora, o `triador` do catálogo roda: `kind="issue"`, prompt sobre
    campos do payload, e `agent/declarado.py::_campos` aceita dicionário — que
    é exatamente o que `ArquivoSource` entrega. Compor pela web
    (`/api/receitas`) e rodar sobre um arquivo do usuário, sem sair da tela.
    """
    import orchestrator.api.app as api_app

    monkeypatch.setattr(api_app, "_RAIZ_RECEITAS", tmp_path / "receitas")
    _csv_de_issues(tmp_path, monkeypatch, linhas=3)
    fake = _cliente_falso(monkeypatch, [_resposta()] * 3)

    criada = cliente.post("/api/receitas", json={
        "id": "triagem-web", "nome": "Triagem", "justificativa": "j",
        "resolvers": [{"nome": "triador"}]})
    assert criada.status_code == 201, criada.text

    r = cliente.post(
        "/api/workflows/triagem-web/runs",
        json={"fonte": _FONTE_ISSUES, "teto_microcents": 10_000_000},
    )

    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["itens"] == 3
    assert corpo["input_ref"].startswith("file:issues.csv@")
    # O agente LEU o arquivo: o prompt do `triador` é "{titulo}\n\n{corpo}",
    # e o que chegou ao modelo são as colunas do CSV. Sem isto, a cascata
    # poderia ter rodado sobre um pool vazio e o teste continuaria verde.
    assert len(fake.chamadas) == 3
    enviados = [c["messages"][0]["content"] for c in fake.chamadas]
    assert enviados == [f"titulo {i}\n\ncorpo {i}" for i in (1, 2, 3)]
    # O custo volta, e é de AGENTE — não de regra.
    (linha,) = corpo["por_resolver"]
    assert (linha["name"], linha["cost_class"]) == ("triador", "AGENTE")
    assert linha["microcents"] == corpo["custo_microcents"] == 3 * _POR_CHAMADA
    # E o agente CLASSIFICOU as três — não abstém em nenhuma, e nenhuma chamada
    # falhou. Sem estas duas linhas o teste passaria igual com um triador que
    # respondesse "NAO_SEI" em tudo ou com a API caída, porque abstenção também
    # é `Proposal`: seria a fatia declarando vitória sobre o próprio objetivo
    # com um agente que não entregou nada.
    assert corpo["propostas_por_tipo"] == {"BUG": 3}
    assert corpo["falhas"] == 0
    assert corpo["teto_atingido"] is False
    # Agente PROPÕE, nunca resolve: a lacuna continua inteira, e é isso que
    # manda as três issues para a revisão humana.
    assert corpo["resolvidos"] == 0
    assert corpo["gap"]["items"] == 3
    assert corpo["contra_gabarito"] is None


def _issues_http(monkeypatch, itens):
    """Transporte falso injetado no MÓDULO: a fonte que `_fonte_de` constrói
    não recebe `transporte`, então o default `_transporte_padrao` é o que se
    troca. Nenhum socket."""
    import httpx

    import orchestrator.sources.http as mod

    def handler(pedido):
        return httpx.Response(200, json=itens, headers={"ETag": '"v1"'})

    monkeypatch.setattr(mod, "_transporte_padrao", lambda: httpx.MockTransport(handler))
    monkeypatch.setenv("CRM_TOKEN", "SEGREDO-4F2A")


def _issues_pg(monkeypatch, linhas):
    import orchestrator.sources.postgres as mod

    class _Cursor:
        def execute(self, q): ...
        # `fetchmany(n)`, como o cursor de verdade: o teto de linhas existe
        # justamente para o driver nunca ser mandado trazer tudo.
        def fetchmany(self, quantas): return list(linhas)[:quantas]

    class _Conexao:
        def cursor(self): return _Cursor()
        def close(self): ...

    monkeypatch.setattr(mod, "_conectar_padrao", lambda dsn: _Conexao())
    monkeypatch.setenv("ERP_DSN", "postgresql://u:SEGREDO-4F2A@h/db")


_ISSUES = [{"id": i, "titulo": f"titulo {i}", "corpo": f"corpo {i}"} for i in (1, 2, 3)]


@pytest.mark.parametrize(
    "fonte, preparar",
    [
        ({"tipo": "http", "url": "https://api.exemplo/issues", "token_env": "CRM_TOKEN",
          "kind": "issue", "campo_id": "id"}, _issues_http),
        ({"tipo": "postgres", "dsn_env": "ERP_DSN", "query": "SELECT id, titulo, corpo FROM issues",
          "kind": "issue", "campo_id": "id"}, _issues_pg),
    ],
    ids=["http", "postgres"],
)
def test_uma_fonte_CONECTADA_roda_no_triador_pela_borda(tmp_path, monkeypatch, fonte, preparar):
    """O mesmo fim-a-fim do arquivo, pelas duas fontes novas: nada na borda
    muda, e é isso que o teste prova."""
    import orchestrator.api.app as api_app

    monkeypatch.setattr(api_app, "_RAIZ_RECEITAS", tmp_path / "receitas")
    preparar(monkeypatch, _ISSUES)
    fake = _cliente_falso(monkeypatch, [_resposta()] * 3)
    criada = cliente.post("/api/receitas", json={
        "id": "triagem-conectada", "nome": "T", "justificativa": "j",
        "resolvers": [{"nome": "triador"}]})
    assert criada.status_code == 201, criada.text

    r = cliente.post("/api/workflows/triagem-conectada/runs",
                     json={"fonte": fonte, "teto_microcents": 10_000_000})

    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["itens"] == 3 and len(fake.chamadas) == 3
    assert corpo["propostas_por_tipo"] == {"BUG": 3} and corpo["falhas"] == 0
    assert corpo["contra_gabarito"] is None
    assert corpo["input_ref"].startswith(("http:", "pg:"))
    assert "SEGREDO-4F2A" not in r.text


_FONTE_PG = {
    "tipo": "postgres", "dsn_env": "ERP_DSN",
    "query": "SELECT id, titulo, corpo FROM issues", "kind": "issue", "campo_id": "id",
}
_FONTE_HTTP = {
    "tipo": "http", "url": "https://api.exemplo/issues", "token_env": "CRM_TOKEN",
    "kind": "issue", "campo_id": "id",
}


@pytest.mark.parametrize(
    "fonte, preparar", [(_FONTE_HTTP, _issues_http), (_FONTE_PG, _issues_pg)],
    ids=["http", "postgres"],
)
def test_id_REPETIDO_numa_fonte_conectada_e_422_e_nao_500(monkeypatch, fonte, preparar):
    """Um `JOIN` que duplica a chave, ou uma página de API com o mesmo `id`
    duas vezes.

    `WorkSet.__post_init__` levanta um `ValueError` PURO — não um `ErroDeFonte`
    —, e o `except` de `_ler` só o virava em 422 quando o tipo era `arquivo`.
    O MESMO dado num CSV devolvia 422 com mensagem e pelas fontes novas subia
    como 500: uma regressão em relação à fonte que já existia, e um "o servidor
    quebrou" sobre um dado que quem pediu consegue consertar.
    """
    preparar(monkeypatch, [{"id": 1, "titulo": "a"}, {"id": 1, "titulo": "b"}])
    r = cliente.post("/api/workflows/conciliacao/runs", json={"fonte": fonte})
    assert r.status_code == 422, r.text
    assert "id repetido" in r.json()["detail"]
    # E a recusa continua sem carregar o que o pedido nomeou por variável.
    assert "SEGREDO-4F2A" not in r.text


def test_o_erro_de_PAYLOAD_nomeia_a_fonte_que_o_pedido_USOU(monkeypatch):
    """A frase dizia "uma fonte de arquivo entrega dicionários" para QUALQUER
    fonte — escrita quando dict só vinha de arquivo. Hoje três fontes entregam
    dict, e a mensagem mandava a pessoa procurar um arquivo que ela não usou."""
    _issues_pg(monkeypatch, _ISSUES)
    r = cliente.post("/api/workflows/conciliacao/runs",
                     json={"fonte": {**_FONTE_PG, "kind": "banco"}})
    assert r.status_code == 422, r.text
    detalhe = r.json()["detail"]
    assert "uma fonte postgres entrega dicionários" in detalhe
    assert "fonte de arquivo" not in detalhe


@pytest.mark.parametrize("fonte", [_FONTE_HTTP, _FONTE_PG], ids=["http", "postgres"])
def test_pedido_sem_teto_e_recusado_ANTES_de_TOCAR_a_fonte(monkeypatch, fonte):
    """A costura entre a guarda de teto e as fontes conectadas.

    A guarda de `teto_microcents` é checagem PURA sobre o pedido e a cascata —
    não olha uma linha do pool. Rodando depois de `_ler`, a borda conectava no
    Postgres do parceiro (ou fazia a requisição à API dele) e esperava a query
    inteira para então recusar por um campo ausente do PRÓPRIO pedido.
    Repetido, é uma torneira contra o banco do parceiro, sem autenticação,
    disparável por qualquer um que alcance a rota.

    O dublê aqui não devolve dado: ele FALHA se for chamado. É a única forma de
    o teste medir "não tocou" em vez de "tocou e deu certo".
    """
    import orchestrator.api.app as api_app
    import orchestrator.sources.http as mod_http
    import orchestrator.sources.postgres as mod_pg

    def _nao_deveria(*args, **kwargs):
        raise AssertionError("a borda tocou a fonte antes de recusar o pedido")

    monkeypatch.setenv("ERP_DSN", "postgresql://u:SEGREDO-4F2A@h/db")
    monkeypatch.setenv("CRM_TOKEN", "SEGREDO-4F2A")
    monkeypatch.setattr(mod_pg, "_conectar_padrao", _nao_deveria)
    monkeypatch.setattr(mod_http, "_transporte_padrao", _nao_deveria)
    monkeypatch.setattr(api_app, "_tem_chave", lambda: True)
    _registrar(monkeypatch, "com-agente", _fabrica_com_agentes(_declarado()))

    r = cliente.post("/api/workflows/com-agente/runs", json={"fonte": fonte})

    assert r.status_code == 422, r.text
    assert "teto_microcents" in r.json()["detail"]


def test_variavel_de_ambiente_ausente_e_422_com_o_NOME(monkeypatch):
    monkeypatch.delenv("ERP_DSN", raising=False)
    r = cliente.post("/api/workflows/conciliacao/runs", json={"fonte": {
        "tipo": "postgres", "dsn_env": "ERP_DSN", "query": "SELECT 1",
        "kind": "banco", "campo_id": "id"}})
    assert r.status_code == 422, r.text
    assert "ERP_DSN" in r.json()["detail"]


def test_query_de_escrita_e_422_antes_de_conectar(monkeypatch):
    monkeypatch.setenv("ERP_DSN", "postgresql://u:SEGREDO-4F2A@h/db")
    import orchestrator.sources.postgres as mod

    def _nao_deveria_conectar(dsn):
        raise AssertionError("a guarda de SELECT deixou conectar")

    monkeypatch.setattr(mod, "_conectar_padrao", _nao_deveria_conectar)
    r = cliente.post("/api/workflows/conciliacao/runs", json={"fonte": {
        "tipo": "postgres", "dsn_env": "ERP_DSN", "query": "DELETE FROM x",
        "kind": "banco", "campo_id": "id"}})
    assert r.status_code == 422 and "SELECT" in r.json()["detail"]
    assert "SEGREDO" not in r.text


def test_sem_o_extra_fontes_e_422_e_nao_500(monkeypatch):
    monkeypatch.setenv("CRM_TOKEN", "x")
    monkeypatch.setitem(__import__("sys").modules, "httpx", None)
    r = cliente.post("/api/workflows/conciliacao/runs", json={"fonte": {
        "tipo": "http", "url": "https://api.exemplo/x", "token_env": "CRM_TOKEN",
        "kind": "banco", "campo_id": "id"}})
    assert r.status_code == 422 and "[fontes]" in r.json()["detail"]


def test_a_forma_antiga_sem_tipo_conhecido_continua_422(monkeypatch):
    r = cliente.post("/api/workflows/conciliacao/runs", json={"fonte": {"tipo": "mysql", "x": 1}})
    assert r.status_code == 422


def test_o_triador_composto_pela_WEB_e_LISTADO_como_executavel(tmp_path, monkeypatch):
    """A tela não pode desabilitar um botão que o servidor aceitaria.

    `executavel` era "a cascata não tem AGENTE". Com o caminho pago aberto, a
    pergunta que a tela faz é outra — "este servidor consegue rodar isto?" — e
    a resposta depende da chave. Uma cascata paga num servidor COM chave é
    executável, e dizer o contrário faria a API mentir sobre a própria rota.
    """
    import orchestrator.api.app as api_app

    monkeypatch.setattr(api_app, "_RAIZ_RECEITAS", tmp_path / "receitas")
    cliente.post("/api/receitas", json={
        "id": "triagem-web", "nome": "Triagem", "justificativa": "j",
        "resolvers": [{"nome": "triador"}]})

    monkeypatch.setattr(api_app, "_tem_chave", lambda: True)
    com = next(
        w for w in cliente.get("/api/workflows").json() if w["id"] == "triagem-web"
    )
    monkeypatch.setattr(api_app, "_tem_chave", lambda: False)
    sem = next(
        w for w in cliente.get("/api/workflows").json() if w["id"] == "triagem-web"
    )

    assert com["executavel"] is True
    assert sem["executavel"] is False
    assert com["classes"] == sem["classes"] == ["AGENTE"]


# -- a política, que o 409 segurava em pé -----------------------------------


def test_a_politica_economica_continua_INERTE_com_o_409_fora(tmp_path, monkeypatch):
    """Tirar o 409 derruba UMA das pernas que seguram a política inerte. As
    outras duas seguem de pé, e isto é o que as prende.

    A revisão da Task 3 registrou que `POLITICA_ECONOMICA`/`max_cost_ratio`
    está inerte por acidente, sobre três coincidências: (a) nenhum formato de
    composição expressa política; (b) o 409 barra `AGENTE`; (c)
    `custo_estimado` devolve 0 fora do `investigador`. Esta task remove (b).

    Política que às vezes se aplica é pior que política nenhuma, porque
    ninguém sabe qual das duas está olhando. Então a escolha é EXPLÍCITA:
    neste caminho ela continua totalmente desligada, e as afirmações abaixo
    são o que impede alguém de religá-la pela metade sem perceber.
    """
    import orchestrator.api.app as api_app
    from orchestrator.kernel.policy import ExecutionPolicy
    from orchestrator.workflows import descrever

    # (a) Nenhum workflow publicado carrega razão de custo nem predicado.
    #     `descrever` cobre o embutido e tudo que veio de receita.
    monkeypatch.setattr(api_app, "_RAIZ_RECEITAS", tmp_path / "receitas")
    cliente.post("/api/receitas", json={
        "id": "triagem-web", "nome": "Triagem", "justificativa": "j",
        "resolvers": [{"nome": "triador"}]})
    for workflow_id, definicao in descrever(tmp_path / "receitas"):
        for stage in definicao.stages:
            assert stage.policy.max_cost_ratio is None, (workflow_id, stage.name)
            assert stage.policy.skip_when is None, (workflow_id, stage.name)
            assert stage.policy.escalate_when is None, (workflow_id, stage.name)
    assert ExecutionPolicy().max_cost_ratio is None

    # (c) E, mesmo que alguém ligasse uma razão de custo, `/runs` não passa
    #     `PolicyContext` — sem `value_at_risk`/`estimated_cost` a regra 7 do
    #     motor devolve `None` e não pula item nenhum. A observação é sobre a
    #     CHAMADA que o endpoint faz, não sobre uma leitura do código.
    vistos: dict = {}
    original = api_app.execute

    def _espiao(definicao, pool, **kw):
        vistos.update(kw)
        return original(definicao, pool, **kw)

    monkeypatch.setattr(api_app, "execute", _espiao)
    _csv_de_issues(tmp_path, monkeypatch, linhas=1)
    _cliente_falso(monkeypatch, [_resposta()])

    r = cliente.post(
        "/api/workflows/triagem-web/runs",
        json={"fonte": _FONTE_ISSUES, "teto_microcents": 10_000_000},
    )

    assert r.status_code == 200, r.text
    assert vistos.get("policy") is None


def test_a_tranca_de_REDE_da_suite_e_ALTA_e_nao_engolida(tmp_path, monkeypatch):
    """A guarda que impede esta fatia de gastar dinheiro em CI, provada.

    `tests/conftest.py::_rede_proibida` troca `anthropic.Anthropic` por algo que
    levanta. Ela existe porque quatro testes desta suite passaram a ir a rede no
    dia em que `/runs` aprendeu a executar cascata paga, e ninguem notou: a
    falha virava abstencao em `agent/conversa.py` e a rota devolvia 200.

    Por isso `RedeProibida` deriva de `BaseException` — e por isso este teste
    existe. Sem ele a tranca seria uma linha de conftest que ninguem exercita, e
    a proxima pessoa a "arrumar" a heranca para `Exception` a desligaria sem que
    nada ficasse vermelho.

    Aqui `_cliente_de_execucao` NAO e substituido de proposito: e o unico teste
    do repositorio que deixa o caminho de rede de verdade ser percorrido, ate o
    ponto exato em que a tranca fecha.
    """
    import orchestrator.api.app as api_app

    _csv_de_issues(tmp_path, monkeypatch, linhas=1)
    monkeypatch.setattr(api_app, "_tem_chave", lambda: True)
    _registrar(monkeypatch, "com-agente", _fabrica_com_agentes(_declarado()))

    # `BaseException`, e nao `Exception`: se a tranca fosse uma `Exception`,
    # `conversar` a capturaria, o POST devolveria 200, e este `raises` falharia
    # — que e exatamente o sinal que se quer.
    with pytest.raises(BaseException, match="falar com o modelo de verdade"):
        cliente.post(
            "/api/workflows/com-agente/runs",
            json={"fonte": _FONTE_ISSUES, "teto_microcents": 10_000_000},
        )


# -- os TRES desfechos, que eram um so ---------------------------------------
#
# `agent/conversa.py` captura a falha da chamada ao modelo e a transforma em
# abstencao — comportamento CERTO para o laco, porque uma queda de rede nao pode
# derrubar um fechamento por causa de um item. O preco e que, do lado de fora,
# "o modelo nao achou nada", "paramos no teto" e "a API falhou" chegavam com a
# mesma cara: 200, `resolvidos: 0`, `gap` inteiro, e nada dizendo o que houve.
#
# Num endpoint que GASTA, essa e a diferenca que decide se vale tentar de novo.


def _corpo_com_agente(monkeypatch, tmp_path, respostas, *, teto=10_000_000, linhas=3):
    _csv_de_issues(tmp_path, monkeypatch, linhas=linhas)
    _cliente_falso(monkeypatch, respostas)
    _registrar(monkeypatch, "com-agente", _fabrica_com_agentes(_declarado()))
    r = cliente.post(
        "/api/workflows/com-agente/runs",
        json={"fonte": _FONTE_ISSUES, "teto_microcents": teto},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_desfecho_o_modelo_RESPONDEU_em_todos_os_itens(tmp_path, monkeypatch):
    """Desfecho 1: deu certo. O agente classificou as tres issues."""
    corpo = _corpo_com_agente(monkeypatch, tmp_path, [_resposta("BUG")] * 3)

    assert corpo["propostas_por_tipo"] == {"BUG": 3}
    assert corpo["falhas"] == 0
    assert corpo["teto_atingido"] is False
    assert corpo["estado"] == "concluido"


def test_desfecho_o_modelo_ABSTEVE_em_todos_os_itens(tmp_path, monkeypatch):
    """Desfecho 2: nao achou nada — e isso NAO e falha.

    Nao saber e resposta, e o agente a deu em todos os itens. `falhas == 0` diz
    que o modelo respondeu; `propostas_por_tipo` diz o que ele respondeu. Sem o
    segundo campo, este desfecho e o de cima sao byte a byte iguais.
    """
    corpo = _corpo_com_agente(monkeypatch, tmp_path, [_resposta("NAO_SEI")] * 3)

    assert corpo["propostas_por_tipo"] == {"NAO_SEI": 3}
    assert corpo["falhas"] == 0
    assert corpo["teto_atingido"] is False
    # `concluido`, e sem ressalva: o agente foi perguntado sobre as tres issues
    # e respondeu as tres. Nao saber e resposta.
    assert corpo["estado"] == "concluido"


def test_desfecho_a_API_FALHOU_e_isso_NAO_e_abstencao_do_modelo(tmp_path, monkeypatch):
    """Desfecho 3: a API caiu, e o run precisa dizer isso.

    O rotulo da proposta e o mesmo `NAO_SEI` do teste acima — `agent/conversa.py`
    desiste pelo caminho da abstencao, de proposito. `falhas` e o que separa os
    dois, e ele e CONTADO no trace (`TraceKind.ERRO`), nao inferido.
    """
    import orchestrator.api.app as api_app
    from orchestrator.agent.teto import ClienteComTeto, Orcamento

    _csv_de_issues(tmp_path, monkeypatch, linhas=3)

    class _CaiSempre:
        model = "claude-opus-5"

        def complete(self, system, messages, tools):
            raise ConnectionError("a rede caiu")

    monkeypatch.setattr(api_app, "_tem_chave", lambda: True)

    def _de_execucao(teto):
        # A rede cai para QUALQUER modelo: a fabrica ignora o nome de proposito,
        # senao este teste passaria a medir roteamento em vez de `falhas`.
        orcamento = Orcamento(teto)
        return (lambda _model: ClienteComTeto(_CaiSempre(), orcamento=orcamento)), orcamento

    monkeypatch.setattr(api_app, "_cliente_de_execucao", _de_execucao)
    _registrar(monkeypatch, "com-agente", _fabrica_com_agentes(_declarado()))

    corpo = cliente.post(
        "/api/workflows/com-agente/runs",
        json={"fonte": _FONTE_ISSUES, "teto_microcents": 10_000_000},
    ).json()

    assert corpo["propostas_por_tipo"] == {"NAO_SEI": 3}
    assert corpo["falhas"] == 3
    # E NAO foi o teto: a distincao inteira desta guarda.
    assert corpo["teto_atingido"] is False
    assert corpo["custo_microcents"] == 0
    # DECISAO EXPLICITA: aqui `concluido` e HONESTO, e nao uma omissao.
    #
    # `RunState` descreve o CICLO DE VIDA do run — a cascata percorreu o pool? —,
    # nao a qualidade do que saiu. Com a API caida, TODO item foi tentado; a
    # tentativa e que nao rendeu. Com o teto, item nenhum foi tentado: o run
    # parou antes, por ordem de quem pediu. "Tentei e nao consegui" e "fui
    # proibido de tentar" sao fatos de ciclo de vida diferentes, e so o segundo
    # e "nao terminou".
    #
    # E se `falhas > 0` derrubasse o estado, uma oscilacao de rede em 1 de 300
    # itens marcaria o run inteiro como nao-concluido, e `estado` deixaria de
    # significar "a cascata rodou" para significar "deu tudo certo" — um juizo
    # de qualidade que `falhas` ja reporta em numero, e que um booleano so
    # empobrece.
    assert corpo["estado"] == "concluido"


def test_desfecho_PAROU_NO_TETO_nao_se_confunde_com_falha_de_API(tmp_path, monkeypatch):
    """Desfecho 4, e o que motivou o campo: `teto_microcents: 0`.

    Antes deste campo, um teto de 0 devolvia 200, `resolvidos: 0`, `gap` inteiro,
    `custo_microcents: 0`, ZERO chamadas ao modelo, a palavra "teto" em lugar
    nenhum do corpo, e o run gravado como `concluido`. Era indistinguivel de uma
    cascata que rodou e nao achou nada — sobre um pedido que explicitamente
    mandou nao gastar.

    `teto_atingido` vem do PROPRIO embrulho que recusou (`ClienteComTeto.recusas`),
    contado na origem. Inferi-lo por subtracao entre `falhas` e outra coisa seria
    o join fragil de sempre.

    **E o `estado` diz isso sozinho.** A primeira versao deste campo devolvia
    `concluido` aqui: um run que o pedido PROIBIU de trabalhar, publicado como se
    tivesse terminado. `teto_atingido` desambiguava — para quem soubesse cruzar
    dois campos —, e o ponto deste round e justamente que o chamador nao precise
    deduzir o desfecho. `limite_de_custo` e irmao de `LIMITE_DE_RONDAS`, e
    separado dele porque dizer "limite de rondas" sobre um teto de dinheiro
    mandaria quem opera mexer em `max_rondas` para resolver um problema de
    orcamento.
    """
    corpo = _corpo_com_agente(monkeypatch, tmp_path, [_resposta()] * 3, teto=0)

    assert corpo["estado"] == "limite_de_custo"
    assert corpo["teto_atingido"] is True
    assert corpo["falhas"] == 3
    assert corpo["custo_microcents"] == 0
    assert corpo["propostas_por_tipo"] == {"NAO_SEI": 3}


def test_o_estado_de_LIMITE_DE_CUSTO_e_o_MESMO_no_historico(tmp_path, monkeypatch):
    """A correcao e feita no `Run`, antes de persistir — nao so na projecao.

    So na projecao, `/runs` diria `limite_de_custo` e `/api/runs` diria
    `concluido` sobre a MESMA execucao: duas verdades sobre um fato, que e
    exatamente o defeito que este campo existe para nao cometer. Quem investiga
    um gasto depois olha o historico, nao a resposta que passou.
    """
    corpo = _corpo_com_agente(monkeypatch, tmp_path, [_resposta()] * 3, teto=0)

    (resumo,) = cliente.get("/api/runs", params={"workflow_id": "com-agente"}).json()
    assert resumo["state"] == corpo["estado"] == "limite_de_custo"


def test_o_teto_VENCE_aguardando_humano_quando_os_dois_valem(tmp_path, monkeypatch):
    """Quando os dois se aplicam, o TETO ganha — e nao e arbitrario.

    O teto e POR QUE existe lacuna; a fila humana e o sintoma. Mandar o operador
    para a revisao esconderia a causa atras do efeito, e ele aprovaria itens sem
    saber que o agente nem chegou a olha-los. E a mesma precedencia que o motor
    ja usa: `LIMITE_DE_RONDAS` vence `AGUARDANDO_HUMANO` em `runtime/engine.py`.

    `RevisorHumano.describe().consome` é fixo em `{banco, contabil}` — a
    conferência de PAYLOAD (`_conferir_payload`) exige que esses kinds
    carreguem `BankEntry`/`LedgerEntry`, e uma fonte de arquivo só entrega
    `dict`. Usar o `RevisorHumano` de verdade aqui acoplaria este teste — que
    é sobre a PRECEDÊNCIA teto-vs-fila, não sobre conciliação — ao domínio
    errado. `_RevisorSemFila` é um dublê LOCAL: a mesma forma (fila vazia,
    nada resolvido, produz `aguardando_humano`), sem a declaração de kind do
    domínio de conciliação. `RevisorHumano` de verdade tem cobertura própria
    em `tests/review/`.
    """
    from orchestrator.agent.declarado import construir_agente
    from orchestrator.grill.catalogo import ClienteAusente
    from orchestrator.kernel.cost import CostClass
    from orchestrator.kernel.definition import Stage, WorkflowDefinition
    from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput

    class _RevisorSemFila:
        name = "revisor"
        cost_class = CostClass.HUMANO

        def describe(self) -> ResolverDescription:
            return ResolverDescription(
                self.name, self.cost_class, "gate humano (dublê de teste)"
            )

        def resolve(self, work):
            return ResolverOutput(resolutions=[])

    def fabrica(ctx):
        # A MESMA costura de `workflows._de_receita`: a fábrica é chamada com o
        # modelo que o bloco declarou, e `None` continua significando a tranca.
        para = ctx.cliente_para or (lambda _model: ClienteAusente())
        return WorkflowDefinition(
            id="com-humano",
            name="agente mais revisor",
            stages=(
                Stage(
                    name="triar",
                    cascade=(
                        construir_agente(_declarado(), para(_declarado().model)),
                        _RevisorSemFila(),
                    ),
                ),
            ),
        )

    _csv_de_issues(tmp_path, monkeypatch, linhas=3)
    _cliente_falso(monkeypatch, [_resposta()] * 3)
    _registrar(monkeypatch, "com-humano", fabrica)

    sem_teto = cliente.post(
        "/api/workflows/com-humano/runs",
        json={"fonte": _FONTE_ISSUES, "teto_microcents": 10_000_000},
    ).json()
    com_teto = cliente.post(
        "/api/workflows/com-humano/runs",
        json={"fonte": _FONTE_ISSUES, "teto_microcents": 0},
    ).json()

    # A cascata TEM degrau humano e sobra pool nos dois casos, entao o motor
    # diria `aguardando_humano` nos dois. O teto e o que muda a resposta.
    assert sem_teto["estado"] == "aguardando_humano"
    assert com_teto["estado"] == "limite_de_custo"


def test_LIMITE_conhecido_o_teto_do_PROPRIO_AGENTE_nao_muda_o_estado(
    tmp_path, monkeypatch
):
    """LACUNA CONHECIDA, pinada para nao virar surpresa.

    `estado == limite_de_custo` cobre o teto DA REQUISICAO, que e o unico que
    esta camada consegue observar: `ClienteComTeto` e um objeto dela e conta as
    proprias recusas. O teto do PROPRIO AGENTE
    (`AgentSpec.budget_total_microcents`) tambem para itens sem sequer tenta-los
    — mesma natureza de fato —, mas ele para DENTRO de `Agent.resolve`, e nada
    sai de la contando isso: a unica marca e um `TraceKind.OUTCOME` com
    `detail={"motivo": "orçamento total"}`.

    Nao fechei a lacuna casando essa string na camada HTTP. Um `if` sobre texto
    em portugues dentro de um `detail` e o join fragil que este repositorio ja
    matou seis vezes: renomear o motivo deixaria a suite verde e o estado
    errado, em silencio. Fechar de verdade pede um contador no `Agent`, ao lado
    do custo, e isso e mudanca no laco que gasta — fora desta fatia.

    Enquanto isso, `custo_microcents` mostra o gasto e a lacuna mostra o resto.
    Este teste falha no dia em que alguem fechar a lacuna, e e ai que ele deve
    ser trocado por um que exija `limite_de_custo`.
    """
    _csv_de_issues(tmp_path, monkeypatch, linhas=5)
    _cliente_falso(monkeypatch, [_resposta()] * 5)
    _registrar(
        monkeypatch,
        "com-agente",
        _fabrica_com_agentes(_declarado(budget_total_microcents=200_000)),
    )

    corpo = cliente.post(
        "/api/workflows/com-agente/runs",
        json={"fonte": _FONTE_ISSUES, "teto_microcents": 200_000_000},
    ).json()

    assert corpo["estado"] == "concluido"
    assert corpo["teto_atingido"] is False
    # E o gasto PAROU — a lacuna e de RELATO, nao de contencao.
    assert corpo["custo_microcents"] == 2 * _POR_CHAMADA


def test_uma_cascata_SEM_agente_reporta_os_tres_campos_como_MEDIDOS(monkeypatch):
    """Zero e `False` aqui sao fatos, nao ausencia disfarcada de numero.

    Sem agente nao ha chamada paga para falhar nem para o teto recusar, e
    `propostas_por_tipo` vazio e o que a conciliacao so de regras de fato
    produz.
    """
    corpo = cliente.post("/api/workflows/conciliacao/runs", json={}).json()

    assert corpo["propostas_por_tipo"] == {}
    assert corpo["falhas"] == 0
    assert corpo["teto_atingido"] is False
    # O estado do run passa a aparecer na resposta do POST, e nao so em
    # `/api/runs`: a conciliacao tem degrau HUMANO e sobra pool, entao ela
    # ESPERA alguem — que e diferente de ter terminado.
    assert corpo["estado"] == "aguardando_humano"


def test_o_ESTADO_do_POST_e_o_MESMO_que_o_historico_guarda():
    """Um campo novo na projecao nao pode ser uma segunda verdade.

    `/runs` e `/api/runs` passam a devolver o estado do mesmo run, e se um dia
    eles divergirem sera porque alguem calculou um dos dois em vez de ler.
    """
    corpo = cliente.post("/api/workflows/conciliacao/runs", json={}).json()

    (resumo,) = cliente.get("/api/runs", params={"workflow_id": "conciliacao"}).json()
    assert resumo["state"] == corpo["estado"]
    assert resumo["input_ref"] == corpo["input_ref"]


# -- o teto negativo, que nao tinha teste -----------------------------------


def test_teto_NEGATIVO_e_recusado_na_construcao_do_embrulho():
    """A guarda existia e nada a exercitava: trocar a condicao por `if False:`
    deixava a suite inteira verde.

    Um teto negativo nasce estourado — a primeira comparacao ja recusa —, entao
    TODO item abstem sem nunca chamar o modelo. Sem esta recusa isso pareceria
    um agente funcionando com orcamento zerado, em vez da configuracao invalida
    que e. Mesma guarda de `Agent.__post_init__` e de `Budget.__post_init__`.
    """
    from orchestrator.agent.llm import FakeLLMClient
    from orchestrator.agent.teto import ClienteComTeto

    with pytest.raises(ValueError, match="negativo"):
        ClienteComTeto(FakeLLMClient([]), teto_microcents=-1)

    # E as duas vizinhas continuam valendo, para que a recusa seja do SINAL e
    # nao de "qualquer numero pequeno".
    assert ClienteComTeto(FakeLLMClient([]), teto_microcents=0).teto_microcents == 0
    assert ClienteComTeto(FakeLLMClient([])).teto_microcents is None


def test_teto_negativo_tambem_e_recusado_pelo_SCHEMA_antes_da_rota():
    """A mesma recusa um nivel acima, onde ela vira 422 em vez de 500.

    As duas existem de proposito: o schema protege a BORDA HTTP, e o embrulho
    protege todo chamador — CLI e biblioteca incluidos, que nao passam pelo
    Pydantic.
    """
    r = cliente.post(
        "/api/workflows/conciliacao/runs", json={"teto_microcents": -1}
    )

    assert r.status_code == 422, r.text


def test_um_CSV_de_issues_roda_numa_COMPOSICAO_do_CANVAS(tmp_path, monkeypatch):
    """A frase do dono, de ponta a ponta: compor um agente na tela e rodar de
    verdade. A fatia anterior provou isto sobre uma RECEITA; uma composição
    vivia em data/composicoes/ e o registry não a conhecia — o botão do canvas
    recebia 404. Agora ela entra no registry e este é o mesmo teste, pela
    porta que a tela usa."""
    import orchestrator.api.app as api_app

    monkeypatch.setattr(api_app, "_RAIZ_RECEITAS", tmp_path / "receitas")
    monkeypatch.setattr(api_app, "_RAIZ_COMPOSICOES", tmp_path / "composicoes")
    _csv_de_issues(tmp_path, monkeypatch, linhas=3)
    fake = _cliente_falso(monkeypatch, [_resposta()] * 3)

    criada = cliente.post("/api/composicoes", json={
        "id": "triagem-canvas", "nome": "Triagem", "justificativa": "",
        "blocos": [{"tipo": "agente", "declaracao": {
            "name": "meu-triador", "system": "classifique a issue",
            "kind": "issue", "prompt": "{titulo}\n\n{corpo}",
            "tipos": ["BUG", "FEATURE"], "abstem_com": "NAO_SEI",
            "ferramentas": [], "max_turns": 3, "budget_microcents": 4_000_000}}]})
    assert criada.status_code == 201, criada.text

    listados = {w["id"]: w for w in cliente.get("/api/workflows").json()}
    assert "triagem-canvas" in listados
    assert listados["triagem-canvas"]["gerado_em"] is not None

    r = cliente.post(
        "/api/workflows/triagem-canvas/runs",
        json={"fonte": _FONTE_ISSUES, "teto_microcents": 10_000_000},
    )

    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["itens"] == 3
    assert len(fake.chamadas) == 3
    assert corpo["propostas_por_tipo"] == {"BUG": 3}
    assert corpo["falhas"] == 0
    assert corpo["teto_atingido"] is False
    assert corpo["contra_gabarito"] is None


def test_compor_com_id_de_workflow_EXISTENTE_e_409(tmp_path, monkeypatch):
    """O id é um só espaço para embutido, receitas e composições.

    `"conciliacao"` (o embutido) já é recusado por `validar_id` no schema, com
    422 — a mesma tranca que `/api/receitas` tem. O 409 desta fatia é o outro
    caso: um id que NÃO é reservado, mas já está ocupado por uma receita em
    disco. É aí que só `registry()` sabe responder.
    """
    import orchestrator.api.app as api_app

    monkeypatch.setattr(api_app, "_RAIZ_RECEITAS", tmp_path / "receitas")
    monkeypatch.setattr(api_app, "_RAIZ_COMPOSICOES", tmp_path / "composicoes")
    receita = cliente.post("/api/receitas", json={
        "id": "ja-existe", "nome": "x", "justificativa": "j",
        "resolvers": [{"nome": "L1"}]})
    assert receita.status_code == 201, receita.text

    r = cliente.post("/api/composicoes", json={
        "id": "ja-existe", "nome": "x", "justificativa": "",
        "blocos": [{"tipo": "regra", "nome": "L1", "parametros": {}}]})
    assert r.status_code == 409, r.text
    assert "ja-existe" in r.json()["detail"]


def test_dois_agentes_em_MODELOS_diferentes_dao_duas_linhas_com_precos_diferentes(
    tmp_path, monkeypatch
):
    """O criterio que fecha a fatia: os MESMOS tokens custam 5x mais em opus que
    em haiku, e a tabela precisa dizer isso.

    Antes, a borda convertia a tabela inteira com UM modelo — o padrao do
    servidor. Medido contra a API do Barrier: um bloco declarado em
    `claude-haiku-4-5` apareceu no relatorio com 4.494.000 µ¢, preco de opus
    para uma chamada que deveria custar um quinto. O campo `model` do bloco era
    cosmetico dos dois lados: nem escolhia com quem falar, nem precificava.

    `vistos` e a outra metade, e sem ela o teste passaria com a chamada indo
    para o modelo errado desde que a CONTA saisse certa — que e o defeito com
    roupa melhor.
    """
    import orchestrator.api.app as api_app
    from orchestrator.agent.llm import FakeLLMClient
    from orchestrator.agent.teto import ClienteComTeto, Orcamento

    _csv_de_issues(tmp_path, monkeypatch, linhas=1)
    vistos: list[str] = []

    def _de_execucao(teto):
        orcamento = Orcamento(teto)

        def fabrica(model: str):
            vistos.append(model)
            return ClienteComTeto(
                FakeLLMClient([_resposta()] * 4, model=model), orcamento=orcamento
            )

        return fabrica, orcamento

    monkeypatch.setattr(api_app, "_tem_chave", lambda: True)
    monkeypatch.setattr(api_app, "_cliente_de_execucao", _de_execucao)
    _registrar(
        monkeypatch,
        "dois-modelos",
        _fabrica_com_agentes(
            _declarado(name="barato", model="claude-haiku-4-5"),
            _declarado(name="caro", model="claude-opus-5"),
            workflow_id="dois-modelos",
        ),
    )

    r = cliente.post(
        "/api/workflows/dois-modelos/runs",
        json={"fonte": _FONTE_ISSUES, "teto_microcents": 100_000_000},
    )

    assert r.status_code == 200, r.text
    linhas = {p["name"]: p["microcents"] for p in r.json()["por_resolver"]}
    # Mesmos tokens, precos diferentes: opus e 5x haiku na tabela de `_PRECOS`.
    assert linhas["caro"] == 5 * linhas["barato"], linhas
    # E o total e a SOMA das linhas, nao uma conversao unica.
    assert r.json()["custo_microcents"] == linhas["caro"] + linhas["barato"]
    # A chamada foi para o modelo que o BLOCO declarou, na ordem da cascata.
    assert vistos == ["claude-haiku-4-5", "claude-opus-5"]


def test_o_STORE_precifica_por_linha_igual_a_RESPOSTA(tmp_path, monkeypatch):
    """Os dois endpoints falam do MESMO run e precisam dizer o mesmo numero.

    `test_o_custo_do_caminho_feliz_tambem_esta_no_STORE` ja fixa essa igualdade,
    e ela passava porque havia um modelo so: os dois lados convertiam com ele.
    Com `model` por bloco, `_resumo_json` continuou convertendo a tabela inteira
    com `claude-opus-5` fixo, e as duas respostas divergiram 5x.

    Medido contra o Barrier em 2026-09-23, o mesmo run: `POST /runs` devolveu
    541.300 µ¢ (haiku, certo) e `GET /api/runs` devolveu 2.706.500 µ¢ (opus).
    Duas verdades sobre um fato — e a que fica em disco e alimenta a tela de
    custo era a errada.

    O modelo do resolver e um FATO do run, entao ele passou a ser gravado com o
    custo, e nao reconstruido de um default na hora de ler.
    """
    import orchestrator.api.app as api_app
    from orchestrator.agent.llm import FakeLLMClient
    from orchestrator.agent.teto import ClienteComTeto, Orcamento

    _csv_de_issues(tmp_path, monkeypatch, linhas=1)

    def _de_execucao(teto):
        orcamento = Orcamento(teto)
        return (
            lambda model: ClienteComTeto(
                FakeLLMClient([_resposta()] * 4, model=model), orcamento=orcamento
            )
        ), orcamento

    monkeypatch.setattr(api_app, "_tem_chave", lambda: True)
    monkeypatch.setattr(api_app, "_cliente_de_execucao", _de_execucao)
    _registrar(
        monkeypatch,
        "dois-modelos-store",
        _fabrica_com_agentes(
            _declarado(name="barato", model="claude-haiku-4-5"),
            _declarado(name="caro", model="claude-opus-5"),
            workflow_id="dois-modelos-store",
        ),
    )

    corpo = cliente.post(
        "/api/workflows/dois-modelos-store/runs",
        json={"fonte": _FONTE_ISSUES, "teto_microcents": 100_000_000},
    ).json()

    (resumo,) = cliente.get(
        "/api/runs", params={"workflow_id": "dois-modelos-store"}
    ).json()
    assert resumo["microcents"] == corpo["custo_microcents"]
    # E o numero e o de DOIS precos, nao o de um: sem esta linha a igualdade
    # acima passaria com os dois lados errados do mesmo jeito.
    linhas = {p["name"]: p["microcents"] for p in corpo["por_resolver"]}
    assert resumo["microcents"] == linhas["caro"] + linhas["barato"]
    assert linhas["caro"] == 5 * linhas["barato"]
