import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from orchestrator.api.app import app
from orchestrator.models import banco, conciliacao, contabil

cliente = TestClient(app)


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

    def _registry_com_extra(raiz=None):
        fabricas = _registry_original(raiz)
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
    """O teste que existe por causa de um bug real.

    Antes desta fatia, compor uma cascata de compras e rodar devolvia `200` com
    `deterministic_rate: 0.0` e lacuna de 100% — um número que parece medido e
    não é. AUSENTE é a forma de dizer "não medido contra verdade"; `0.0` seria
    a mesma mentira com outra roupa.
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

    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["contra_gabarito"] is None
    assert corpo["itens"] == 2
    assert corpo["input_ref"].startswith("file:")


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


def test_a_fila_de_uma_fonte_de_arquivo_e_ESCOPADA_por_conteudo(tmp_path, monkeypatch):
    """A chave que o ENDPOINT de fato usa, observada — não recalculada.

    A primeira versão deste teste comparava `dataset_de_ref(ref_antes)` com
    `dataset_de_ref(ref_depois)`: duas funções puras contra elas mesmas. Ela
    passava com a chave da fila FIXADA em `"synth:s1-n30-t0.15"` dentro de
    `_executar` — ou seja, provava que o `ref` muda com o conteúdo e nada sobre
    a fila. Aqui o `caminho_da_fila` do módulo é espionado, então o que a
    asserção vê é o caminho que o servidor abriu.
    """
    import orchestrator.api.app as api_app
    from orchestrator.review.fila import caminho_da_fila, dataset_de_ref

    raiz = tmp_path / "entradas"
    raiz.mkdir()
    alvo = raiz / "itens.csv"
    alvo.write_text("id,texto\na,um\n", encoding="utf-8")
    monkeypatch.setattr(api_app, "_RAIZ_ENTRADAS", raiz)

    abertas: list[tuple[str, str]] = []

    def _espiao(workflow_id, dataset, raiz=None):
        abertas.append((workflow_id, dataset))
        return caminho_da_fila(workflow_id, dataset, raiz=raiz)

    monkeypatch.setattr(api_app, "caminho_da_fila", _espiao)

    def _rodar() -> str:
        return cliente.post(
            "/api/workflows/conciliacao/runs",
            json={"fonte": {"tipo": "arquivo", "caminho": "itens.csv",
                            "kind": "k", "campo_id": "id"}},
        ).json()["input_ref"]

    antes = _rodar()
    alvo.write_text("id,texto\na,OUTRO\n", encoding="utf-8")
    depois = _rodar()

    assert antes != depois
    # O endpoint abriu UMA fila por execução, no workflow certo, com a chave
    # derivada do `ref` da fonte de ARQUIVO — nunca a de uma sintética.
    assert [w for w, _ in abertas] == ["conciliacao", "conciliacao"]
    assert [d for _, d in abertas] == [dataset_de_ref(antes), dataset_de_ref(depois)]
    assert abertas[0][1] != abertas[1][1]
    for _, chave in abertas:
        assert chave.startswith("file-")


def _registrar(monkeypatch, workflow_id: str, fabrica) -> None:
    """Acrescenta um workflow ao registro, preservando os reais.

    `registry()` monta um dict NOVO a cada chamada; envolver a função original
    é o mesmo padrão de
    `test_resolver_com_layer_diferente_do_name_e_reportado_pelo_proprio_nome`.
    """
    from orchestrator.workflows import registry as _original

    def _com_extra(raiz=None):
        fabricas = _original(raiz)
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

    `ArquivoSource` entrega dicionário; `ExactMatcher` lê `be.document`. Com
    `kind="banco"` o CSV cai direto no `banco()` da conciliação e o resultado
    era um 500 de `AttributeError`, vindo de três camadas abaixo de quem
    escolheu as duas pontas.

    A recusa nomeia o RESOLVER e o KIND, porque é a combinação que está errada
    e não nenhuma das duas escolhas sozinha.
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
    assert "L1" in detalhe
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
    from orchestrator.synth.benchmark import SyntheticSource

    def _explode(self):
        raise ValueError("defeito do gerador, não do pedido")

    monkeypatch.setattr(SyntheticSource, "load", _explode)

    with pytest.raises(ValueError, match="defeito do gerador"):
        cliente.post("/api/workflows/conciliacao/runs", json={})
