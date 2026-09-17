"""O compositor de cascata: o canvas de AUTORIA.

O §3.5 do spec de composição nomeia o modo de falha desta tela: **decoração** —
desenhar uma coisa e executar outra. A defesa não é visual, é estrutural, e
estes testes são o que a torna verificável:

  - a ORDEM não é um campo que o cliente envia; ela é derivada de `CostClass`;
  - o servidor devolve a definição CONSTRUÍDA, não a receita recebida;
  - `construir` valida, e a mensagem que a tela mostra é a do domínio.

Se um dia alguém acrescentar um campo de ordem, `test_a_ordem_enviada_e_IGNORADA`
fica vermelho — e é exatamente aí que a decoração começaria.
"""

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

import orchestrator.api.app as app_mod
from orchestrator.api.app import app

cliente = TestClient(app)


@pytest.fixture(autouse=True)
def receitas_em_tmp(tmp_path, monkeypatch):
    """Nunca o `data/` real do desenvolvedor — `gravar_receita` escreve."""
    monkeypatch.setattr(app_mod, "_RAIZ_RECEITAS", tmp_path)
    return tmp_path


def _corpo(resolvers, wid="minha-cascata"):
    return {
        "id": wid,
        "nome": "Minha cascata",
        "justificativa": "porque sim",
        "resolvers": resolvers,
    }


# -- o catálogo -------------------------------------------------------------


def test_o_catalogo_e_DERIVADO_do_CATALOGO_plano():
    """Uma lista escrita à mão na camada HTTP divergiria na primeira mudança,
    e o sintoma seria uma tela oferecendo um bloco que `construir` recusa."""
    from orchestrator.domains.registro import CATALOGO

    dados = cliente.get("/api/catalogo").json()

    assert {r["nome"] for r in dados["regras"]} == {r.nome for r in CATALOGO.regras}
    assert {a["name"] for a in dados["agentes"]} == {a.name for a in CATALOGO.agentes}


def test_as_regras_vem_na_ordem_em_que_a_CASCATA_RODA():
    """Ordem alfabética sugeriria que o autor escolhe a sequência. Ele não
    escolhe: a paleta é oferecida do mais barato ao mais caro porque é essa a
    ordem de execução."""
    classes = [r["cost_class"] for r in cliente.get("/api/catalogo").json()["regras"]]
    ordem = ["REGRA", "AGENTE", "CREW", "HUMANO"]

    assert classes == sorted(classes, key=ordem.index)


def test_o_catalogo_traz_os_parametros_com_DEFAULT_do_proprio_resolver():
    """`_param` lê o default do dataclass do resolver. A tela preenche com ele,
    então renomear o campo no resolver explode no import e não na tela.

    A comparação é contra `dataclasses.fields(ToleranceMatcher)`, e é ela que
    carrega o teste: conferir que o default é `int` passaria com um literal
    escrito à mão no catálogo, que é exatamente a divergência que `_param`
    existe para tornar impossível. O sintoma seria a tela preencher `5` num
    campo cujo resolver já mudou para outro valor — e ninguém veria.
    """
    import dataclasses

    from orchestrator.matching.tolerance import ToleranceMatcher

    dados = cliente.get("/api/catalogo").json()
    l2 = next(r for r in dados["regras"] if r["nome"] == "L2")
    do_resolver = {f.name: f.default for f in dataclasses.fields(ToleranceMatcher)}

    assert {p["nome"] for p in l2["parametros"]} == {"max_cents", "max_business_days"}
    assert {p["nome"]: p["default"] for p in l2["parametros"]} == {
        "max_cents": do_resolver["max_cents"],
        "max_business_days": do_resolver["max_business_days"],
    }
    assert all(p["descricao"] for p in l2["parametros"])


def test_o_catalogo_expoe_as_ferramentas_de_TODAS_as_origens():
    """"Todas as nossas tools disponíveis" — o pedido, na borda HTTP.

    A identidade contra `CATALOGO.ferramentas` (não só a presença de uma) é o
    que torna a lista DERIVADA: uma lista escrita à mão com seis nomes,
    incluindo `contar_palavras`, passaria por uma checagem de "está contido"
    sem nunca ser pega divergindo.
    """
    from orchestrator.domains.registro import CATALOGO

    nomes = {f["nome"] for f in cliente.get("/api/catalogo").json()["ferramentas"]}

    assert nomes == set(CATALOGO.ferramentas.names())
    # E que a ferramenta do domínio `swe` atravessou a fusão das origens.
    assert "contar_palavras" in nomes


# -- a defesa contra decoração ---------------------------------------------


def test_a_ordem_enviada_e_IGNORADA():
    """O teste que impede esta tela de virar decoração.

    O cliente manda HUMANO antes de REGRA. O servidor devolve REGRA antes de
    HUMANO, porque quem ordena é `Stage.ordered()` e não existe entrada que a
    inverta. Se este teste ficar vermelho, alguém transformou a ordem num campo
    — e aí a tela passa a poder desenhar uma execução que não acontece.
    """
    corpo = _corpo([{"nome": "revisor"}, {"nome": "L1"}])

    r = cliente.post("/api/receitas", json=corpo)

    assert r.status_code == 201, r.text
    classes = [x["cost_class"] for x in r.json()["stages"][0]["cascade"]]
    assert classes == ["REGRA", "HUMANO"]


def test_a_resposta_e_a_definicao_CONSTRUIDA_e_nao_a_receita_enviada():
    """A tela mostra o que voltou do servidor. Se ela ecoasse o que o usuário
    montou, as duas coisas poderiam divergir sem sintoma."""
    r = cliente.post("/api/receitas", json=_corpo([{"nome": "L1"}, {"nome": "L2"}]))

    cascata = r.json()["stages"][0]["cascade"]
    # `summary` não existe na receita enviada: ele vem do `describe()` do
    # resolver construído de verdade.
    assert all(x["summary"] for x in cascata)


# -- validar construindo ----------------------------------------------------


def test_resolver_desconhecido_devolve_a_mensagem_do_DOMINIO():
    """`construir` escreve erros para serem lidos — o grill depende disso para
    o modelo se corrigir, e a pessoa merece o mesmo texto."""
    r = cliente.post("/api/receitas", json=_corpo([{"nome": "inexistente"}]))

    assert r.status_code == 422
    assert "resolver desconhecido" in r.json()["detail"]
    assert "disponíveis" in r.json()["detail"]


def test_resolver_REPETIDO_e_recusado_com_o_motivo():
    """O segundo rodaria sobre o pool que o primeiro já esvaziou."""
    r = cliente.post("/api/receitas", json=_corpo([{"nome": "L1"}, {"nome": "L1"}]))

    assert r.status_code == 422
    assert "esvaziou" in r.json()["detail"]


def test_parametro_desconhecido_e_recusado():
    r = cliente.post(
        "/api/receitas",
        json=_corpo([{"nome": "L2", "parametros": {"nao_existe": 3}}]),
    )

    assert r.status_code == 422
    assert "parâmetro desconhecido" in r.json()["detail"]


def test_cascata_VAZIA_e_recusada_antes_de_chegar_no_handler():
    r = cliente.post("/api/receitas", json=_corpo([]))

    assert r.status_code == 422


def test_id_invalido_usa_a_MESMA_validacao_do_grill():
    """Uma cópia da regra aqui divergiria, e o sintoma seria uma receita aceita
    pela tela e recusada pelo disco."""
    r = cliente.post("/api/receitas", json=_corpo([{"nome": "L1"}], wid="Com Espaço"))

    assert r.status_code == 422


def test_id_JA_EXISTENTE_e_recusado_com_409():
    cliente.post("/api/receitas", json=_corpo([{"nome": "L1"}], wid="repetida"))

    r = cliente.post("/api/receitas", json=_corpo([{"nome": "L2"}], wid="repetida"))

    assert r.status_code == 409
    assert "já existe" in r.json()["detail"]


def test_receita_que_NAO_constroi_nao_vai_para_o_disco(receitas_em_tmp):
    """Gravar antes de construir deixaria lixo que a listagem teria de filtrar
    para sempre."""
    cliente.post("/api/receitas", json=_corpo([{"nome": "inexistente"}], wid="ruim"))

    assert not list(receitas_em_tmp.rglob("ruim*"))


# -- a receita composta é um workflow de verdade ----------------------------


def test_a_receita_composta_APARECE_na_listagem_de_workflows():
    """O teste de que isto não é uma tela paralela: o que foi composto vira um
    workflow como qualquer outro, no mesmo registro."""
    cliente.post("/api/receitas", json=_corpo([{"nome": "L1"}], wid="composta"))

    ids = [w["id"] for w in cliente.get("/api/workflows").json()]

    assert "composta" in ids


def test_cascata_com_AGENTE_e_marcada_como_nao_executavel_pela_API():
    """A regra que governa o módulo HTTP: nenhum endpoint gasta dinheiro. A
    tela desabilita o botão em vez de deixar o usuário colher um 409.

    "investigador", não "agente": o catálogo plano (Task 3) nomeia o bloco
    AGENTE da conciliação pelo `Resolver.name` que ele sempre teve — o
    cardápio do grill é que usava a chave "agente" só para propor este mesmo
    bloco.
    """
    cliente.post("/api/receitas", json=_corpo([{"nome": "investigador"}], wid="cara"))

    w = next(x for x in cliente.get("/api/workflows").json() if x["id"] == "cara")

    assert w["executavel"] is False


# -- a página ---------------------------------------------------------------


def test_a_pagina_do_compositor_e_servida():
    """A tela virou um app React (Vite + React Flow), buildado para `web/` e
    servido na RAIZ — a autoria é a vista `?vista=compor`. Antes ela morava em
    `/compor/`, ao lado de duas páginas estáticas, e foi essa convivência que
    produziu o defeito do modo escuro por default.

    O teste ancora no que o BUILD garante — a raiz onde o React monta e um
    módulo carregado — e não em marcação escrita à mão, que agora é gerada e
    muda de nome de arquivo a cada build (hash no asset).
    """
    r = cliente.get("/?vista=compor")

    assert r.status_code == 200
    assert 'id="raiz"' in r.text
    assert "<script" in r.text and "module" in r.text


def test_a_pagina_DIZ_que_as_SETAS_nao_sao_do_autor():
    """A restrição mais importante da tela precisa estar escrita NELA.

    Num canvas de nós, a expectativa que a pessoa traz de outras ferramentas é
    que ela desenha as arestas. Aqui elas são derivadas, e quem abre precisa
    entender isso em dez segundos — ou vai passar a sessão tentando arrastar
    uma seta que não existe.

    O texto vive no bundle JS (é JSX), então é lá que se procura. Se o build
    sumir, este teste fica vermelho junto com o de cima — que é o que se quer:
    build ausente é tela ausente.
    """
    from pathlib import Path

    import orchestrator.api.app as mod

    bundles = list((Path(mod.__file__).parents[3] / "web" / "assets").glob("*.js"))
    assert bundles, "o app não foi buildado (npm --prefix web-app run build)"
    fonte = "\n".join(b.read_text(encoding="utf-8") for b in bundles)

    assert "setas" in fonte
    assert "classe de custo" in fonte


def test_a_tela_NAO_pergunta_o_dominio_antes_de_mostrar_bloco():
    """O quadro em branco, ancorado onde ele é verdade: no bundle.

    A prova não é o texto do `<label>` que sumiu — ele poderia sumir com a
    chamada continuando lá, e a paleta seguiria particionada. A prova é a
    ORIGEM da paleta: enquanto o bundle falar com `/api/dominios`, a tela ainda
    depende de uma partição que ela não mostra, que é a versão pior do defeito
    que esta fatia remove.

    A rota já não existe (ver `test_a_rota_de_dominios_nao_existe_mais`); este
    teste continua valendo porque ele fixa a ORIGEM da paleta no bundle, e não
    a existência da rota — um bundle que voltasse a montar a paleta por
    partição quebraria aqui antes de quebrar em qualquer outro lugar.
    """
    from pathlib import Path

    import orchestrator.api.app as mod

    bundles = list((Path(mod.__file__).parents[3] / "web" / "assets").glob("*.js"))
    assert bundles, "o app não foi buildado (npm --prefix web-app run build)"
    fonte = "\n".join(b.read_text(encoding="utf-8") for b in bundles)

    assert "/api/dominios" not in fonte
    assert "/api/catalogo" in fonte


# -- o nó do agente: modelo e ferramentas ----------------------------------


# A invariante "a tela expõe as ferramentas derivadas do registro" segue
# coberta — agora ao nível do catálogo plano — por
# `test_o_catalogo_expoe_as_ferramentas_de_TODAS_as_origens`, acima. Não
# existe mais um bloco "agente" em `/api/catalogo` (o registro do grill não é
# mais servido por esta rota) para repetir o teste como estava.


def test_o_modelo_do_agente_e_PADRAO_e_nao_escolha_gravada():
    """Quem decide o modelo é a execução (`--model`). Cravar um modelo na
    receita faria o canvas prometer algo que a receita não carrega — e é a
    diferença exata para o canvas de referência, que fixa o modelo no nó.

    `AgenteDeclarado.model` é `""` — string vazia, não um nome de modelo —
    porque `construir_agente` lê `decl.model or client.model`: só o CLIENTE
    (`--model` da CLI, nunca a receita) decide de fato. Antes desta fatia
    (Task 3) a invariante equivalente vivia em
    `grill.catalogo.CATALOGO["agente"].modelo_padrao`; ela migra para o
    catálogo PLANO porque é dele que `grill.receita.construir` passou a ler o
    bloco "investigador" — `grill.catalogo.CATALOGO` não existe mais.
    """
    from datetime import UTC, datetime

    from orchestrator.agent.declarado import AgenteDeclarado
    from orchestrator.domains.registro import CATALOGO
    from orchestrator.grill.receita import Receita, ResolverReceita, para_json

    investigador = CATALOGO.bloco("investigador")
    assert isinstance(investigador, AgenteDeclarado)
    assert investigador.model == ""

    r = Receita(
        id="x", nome="x", justificativa="", gerado_em=datetime.now(UTC),
        resolvers=(ResolverReceita(nome="investigador"),),
    )
    # A receita SERIALIZADA não carrega modelo nenhum. É isso que o "padrão" na
    # tela está dizendo.
    assert "model" not in str(para_json(r)).lower()


# `test_resolver_DETERMINISTICO_do_grill_nao_tem_modelo_nem_ferramenta` não
# migra — REMOVIDO por decisão explícita da Task 3, não por descuido.
#
# Ela provava que `EntradaCatalogo` (o valor do dict `grill.catalogo.CATALOGO`)
# tinha `modelo_padrao=None` e `ferramentas=()` para os blocos determinísticos
# — um campo cada, existente só porque `EntradaCatalogo` era uma forma ÚNICA
# usada tanto para regra quanto para agente. O catálogo PLANO (Task 1) não tem
# essa forma única: `RegraDisponivel` (as regras) não tem `modelo_padrao` nem
# `ferramentas` — a ausência que o teste checava não é mais um VALOR que um
# campo pode assumir, é a FORMA do tipo. Não há mais o que construir para
# provar que ela é `None`/`()`; a pergunta que o teste fazia deixou de fazer
# sentido, e não porque a garantia enfraqueceu — porque o tipo agora a
# carrega estruturalmente.


# -- o botão Run ------------------------------------------------------------


def test_a_pagina_tem_o_botao_RUN():
    from pathlib import Path

    import orchestrator.api.app as mod

    bundles = list((Path(mod.__file__).parents[3] / "web" / "assets").glob("*.js"))
    fonte = "\n".join(b.read_text(encoding="utf-8") for b in bundles)

    assert "Run" in fonte
    # E a mensagem que explica por que ele fica desabilitado numa cascata paga.
    assert "etapa paga" in fonte


def test_a_rota_de_dominios_nao_existe_mais():
    assert cliente.get("/api/dominios").status_code == 404


def test_cascata_GRATIS_composta_pela_tela_RODA_de_verdade():
    """O fluxo inteiro: compor, gravar, executar — sem sair da web."""
    cliente.post("/api/receitas", json=_corpo([{"nome": "L1"}], wid="so-regra"))

    r = cliente.post(
        "/api/workflows/so-regra/runs",
        json={"fonte": {"tipo": "sintetica", "seed": 1, "n": 120}},
    )

    assert r.status_code == 200, r.text
    assert r.json()["deterministic_rate"] > 0
    # A LACUNA sempre aparece, mesmo quando é zero: é invariante do §1.5, e
    # esconder a linha faria o leitor não saber se foi medida.
    assert "items" in r.json()["gap"]


def test_cascata_PAGA_composta_pela_tela_e_recusada_pelo_SERVIDOR():
    """A tela desabilita o botão, mas quem garante é o servidor. Testado
    forçando o POST — que é exatamente o que fiz no navegador.

    "investigador", não "agente" — ver o comentário em
    `test_cascata_com_AGENTE_e_marcada_como_nao_executavel_pela_API`.
    """
    cliente.post("/api/receitas", json=_corpo([{"nome": "investigador"}], wid="com-agente"))

    r = cliente.post(
        "/api/workflows/com-agente/runs",
        json={"fonte": {"tipo": "sintetica", "seed": 1, "n": 60}},
    )

    assert r.status_code == 409
    assert "etapa paga" in r.json()["detail"]
