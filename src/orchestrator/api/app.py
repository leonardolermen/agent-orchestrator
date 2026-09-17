"""O app HTTP do canvas.

**A regra que governa este módulo ficou MAIS PRECISA, não mais frouxa.**

Ela era: *"nenhum endpoint daqui pode gastar dinheiro"*. O que ela protegia é o
caminho de EXECUÇÃO — rodar um workflow pela web nunca pode virar uma conta —, e
isso continua valendo e continua testado (`tests/api/test_execucao.py`): uma
cascata com classe `AGENTE` é recusada com 409, e não existe caminho de código
daqui até o modelo por `/runs`.

A entrevista (`api/entrevista.py`) não executa nada: ela COMPÕE, conversando. E
não há como compor conversando sem falar com um modelo. Então:

    EXECUTAR um workflow pela web nunca gasta dinheiro.
    COMPOR por conversa gasta, com teto, e o teto é dito antes.

A exceção é UMA, mora em outro arquivo, e carrega as três guardas que a tornam
aceitável — teto por entrevista, custo devolvido em cada desfecho, e recusa
explícita sem chave. Ver o cabeçalho de `api/entrevista.py`.
"""

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi.staticfiles import StaticFiles

from orchestrator.agent.declarado import AgenteDeclarado, RegraDisponivel
from orchestrator.agent.tools.registry import ToolRegistry
from orchestrator.api.entrevista import conduzir
from orchestrator.api.schemas import (
    AgenteDeclaradoJSON,
    AmbienteJSON,
    CatalogoJSON,
    ComposicaoRequest,
    ComposicaoResumoJSON,
    DecisaoRequest,
    DominioJSON,
    FerramentaJSON,
    FilaJSON,
    GapJSON,
    ItemFilaJSON,
    LancamentoJSON,
    ParametroJSON,
    ReceitaRequest,
    RegraJSON,
    ResolverRunJSON,
    RunJSON,
    RunRequest,
    RunResumoJSON,
    WorkflowJSON,
    WorkflowResumoJSON,
    workflow_json,
)
from orchestrator.authoring.composicao import (
    Bloco,
    BlocoAgente,
    BlocoRegra,
    Composicao,
    construir_composicao,
    gravar,
    listar,
)
from orchestrator.conciliacao import reconcile
from orchestrator.domains.registro import CATALOGO, DOMINIOS
from orchestrator.grill.catalogo import MODELO_INERTE
from orchestrator.grill.receita import Receita, ResolverReceita, construir
from orchestrator.grill.registro import gravar_receita, listar_receitas
from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.event import EventBus
from orchestrator.kernel.run import RunState
from orchestrator.metrics import evaluate
from orchestrator.observability.collector import SpanCollector
from orchestrator.review.decision import Decision, Veredito, ids_de_conciliar_com
from orchestrator.review.fila import Fila, caminho_da_fila, dataset_id
from orchestrator.storage.jsonl.run_store import JsonlRunStore
from orchestrator.storage.jsonl.trace_store import JsonlTraceStore
from orchestrator.synth.benchmark import SyntheticSource, build_benchmark
from orchestrator.taxonomy import DivergenceType
from orchestrator.workflows import (
    WorkflowContext,
    construir_definicao,
    descrever,
    registry,
)

app = FastAPI(title="Agent Orchestrator — canvas")

# Raiz das receitas em disco. Atributo de módulo para o teste trocar por
# tmp_path sem ler o `data/` real do desenvolvedor.
_RAIZ_RECEITAS: Path | None = None

# Raiz das composições em disco, pelo mesmo motivo — `gravar` escreve.
_RAIZ_COMPOSICOES: Path | None = None


@app.get("/api/workflows", response_model=list[WorkflowResumoJSON])
def listar_workflows() -> list[WorkflowResumoJSON]:
    resumos = []
    por_id = {r.id: r for r in listar_receitas(_RAIZ_RECEITAS)}
    # `descrever` já isola a receita que parseia e não constrói: um arquivo
    # ruim não derruba a listagem inteira, mas também não some em silêncio.
    # A lógica saiu daqui para `workflows.py` porque a CLI precisa da mesma
    # resposta, e duas cópias seriam o join frágil de sempre.
    for workflow_id, definicao in descrever(_RAIZ_RECEITAS):
        classes = sorted(
            {r.cost_class.name for s in definicao.stages for r in s.cascade}
        )
        receita = por_id.get(workflow_id)
        resumos.append(
            WorkflowResumoJSON(
                id=workflow_id,
                nome=definicao.name,
                classes=classes,
                gerado_em=receita.gerado_em.isoformat() if receita else None,
                executavel=CostClass.AGENTE.name not in classes,
            )
        )
    return resumos


def _ferramenta_json(ferramentas: ToolRegistry, nome: str) -> FerramentaJSON:
    return FerramentaJSON(nome=nome, descricao=ferramentas.spec(nome).description)


def _regra_json(r: RegraDisponivel) -> RegraJSON:
    return RegraJSON(
        nome=r.nome,
        cost_class=r.cost_class.name,
        resumo=r.resumo,
        parametros=[
            ParametroJSON(nome=p.nome, default=p.default, descricao=p.descricao)
            for p in r.parametros
        ],
    )


def _agente_json(a: AgenteDeclarado) -> AgenteDeclaradoJSON:
    return AgenteDeclaradoJSON(
        name=a.name,
        system=a.system,
        kind=a.kind,
        prompt=a.prompt,
        tipos=list(a.tipos),
        abstem_com=a.abstem_com,
        ferramentas=list(a.ferramentas),
        max_turns=a.max_turns,
        budget_microcents=a.budget_microcents,
    )


@app.get("/api/catalogo", response_model=CatalogoJSON)
def catalogo() -> CatalogoJSON:
    """Tudo que dá para compor. Derivado do `CATALOGO`, nunca escrito à mão.

    As regras saem ordenadas por classe de custo e depois por nome: é a ordem
    em que a cascata VAI RODAR, então é a ordem em que a tela deve oferecer.
    Uma paleta em ordem alfabética sugeriria que o autor escolhe a sequência —
    e ele não escolhe.

    Esta rota SUBSTITUIU o cardápio do grill, que era só de conciliação. Foi
    ele que fez o chat propor `L1`/`L2`/`L3` para triagem de issues.
    """
    return CatalogoJSON(
        ferramentas=[
            _ferramenta_json(CATALOGO.ferramentas, n) for n in CATALOGO.ferramentas.names()
        ],
        regras=[
            _regra_json(r)
            for r in sorted(CATALOGO.regras, key=lambda r: (r.cost_class, r.nome))
        ],
        agentes=[_agente_json(a) for a in CATALOGO.agentes],
    )


@app.get("/api/dominios", response_model=list[DominioJSON])
def dominios() -> list[DominioJSON]:
    """O que a plataforma sabe orquestrar, e com que blocos.

    É a primeira pergunta da tela de composição. Antes ela não existia: a
    paleta era o `CATALOGO` do grill, que é o cardápio da CONCILIAÇÃO, e por
    isso o canvas só oferecia blocos de conciliação por seis meses de
    desenvolvimento sem ninguém notar.

    As ferramentas saem do CATÁLOGO do domínio — sem dados. Um registro ligado
    a um `ToolContext` vazio listaria igual e executaria devolvendo nada, que é
    a falha silenciosa que `ToolRegistry.ligado` agora torna impossível.
    """
    return [
        DominioJSON(
            id=d.id,
            nome=d.nome,
            kinds=list(d.kinds),
            ferramentas=[_ferramenta_json(d.ferramentas, n) for n in d.ferramentas.names()],
            regras=[_regra_json(r) for r in d.regras],
            agentes=[_agente_json(a) for a in d.agentes],
        )
        for d in DOMINIOS.values()
    ]


@app.get("/api/ambiente", response_model=AmbienteJSON)
def ambiente() -> AmbienteJSON:
    """O que uma execução usa, e o que o servidor tem configurado.

    **Nunca devolve o valor de segredo nenhum** — só se ele EXISTE. Uma tela que
    mostra a chave é uma tela que vaza a chave para quem olhar por cima do
    ombro, para o print da conversa e para o cache do navegador.

    Os defaults saem dos MESMOS lugares que a execução lê: os limites de `seed`,
    `n` e `taxa_divergencia` são os de `Query` em `/runs`, e o modelo é o
    default do `AnthropicClient`. Uma segunda tabela aqui divergiria, e o
    sintoma seria a tela oferecer um `n` que o servidor recusa.
    """
    return AmbienteJSON(
        modelo_padrao=MODELO_INERTE,
        tem_chave=bool(os.environ.get("ANTHROPIC_API_KEY")),
        seed=1,
        n=300,
        n_max=5000,
        taxa_divergencia=0.15,
    )


@app.websocket("/api/entrevista")
async def entrevista(ws: WebSocket) -> None:
    """O chat que compõe. GASTA DINHEIRO — ver `api/entrevista.py`."""
    await conduzir(ws, gravar=lambda r: gravar_receita(r, _RAIZ_RECEITAS))


@app.post("/api/receitas", response_model=WorkflowJSON, status_code=201)
def criar_receita(pedido: ReceitaRequest) -> WorkflowJSON:
    """Compõe uma cascata. VALIDA CONSTRUINDO.

    `construir` é a mesma função que o entrevistador do grill usa, e ela
    levanta `ValueError` com mensagem escrita para ser lida. Aqui essa
    mensagem vira o corpo do 422 — a tela mostra o texto do domínio em vez de
    um erro genérico, e não existe uma segunda lista de regras na camada HTTP
    para divergir da primeira.

    Devolve a definição CONSTRUÍDA, não a receita enviada. É o que faz a tela
    mostrar a cascata na ordem em que ela roda (`Stage.ordered()`) em vez de na
    ordem em que o autor clicou.
    """
    receita = Receita(
        id=pedido.id,
        nome=pedido.nome,
        justificativa=pedido.justificativa,
        # Relógio do SERVIDOR. Ver `ReceitaRequest`.
        gerado_em=datetime.now(UTC),
        resolvers=tuple(
            ResolverReceita(nome=r.nome, parametros=dict(r.parametros))
            for r in pedido.resolvers
        ),
    )
    try:
        definicao = construir(receita)
    except ValueError as erro:
        raise HTTPException(status_code=422, detail=str(erro)) from erro

    if pedido.id in registry(_RAIZ_RECEITAS):
        raise HTTPException(
            status_code=409,
            detail=f"já existe um workflow com id {pedido.id!r}; escolha outro",
        )
    # Grava só DEPOIS de construir: uma receita que não roda não vai para o
    # disco. Mesma ordem de `gravar_receita` no grill, e pelo mesmo motivo.
    gravar_receita(receita, _RAIZ_RECEITAS)
    return workflow_json(definicao)


@app.post("/api/composicoes", response_model=WorkflowJSON, status_code=201)
def criar_composicao(pedido: ComposicaoRequest) -> WorkflowJSON:
    """Compõe uma cascata de QUALQUER domínio. VALIDA CONSTRUINDO.

    É o irmão de `/api/receitas` para o formato geral. A diferença que importa
    está no corpo: uma receita é uma lista de nomes do catálogo; uma composição
    carrega o agente INTEIRO — prompt, vocabulário, ferramentas, orçamento —
    porque esse agente não existe em catálogo nenhum até a pessoa criá-lo.

    **Não passa `contexto`.** Compor não executa, e sem dados o registro do
    domínio segue sendo catálogo: se alguém executasse esta definição, as
    ferramentas recusariam com texto em vez de estourar sobre dados ausentes.

    **Não passa `cliente`.** O default de `construir_composicao` é
    `ClienteDeValidacao`, que constrói o agente e recusa falar com modelo. É a
    mesma tranca de `/api/receitas`, e é o que mantém verdadeira a regra deste
    módulo: compor pela web não gasta dinheiro. (A entrevista gasta, com teto, e
    é a exceção declarada no cabeçalho.)
    """
    blocos: list[Bloco] = []
    for b in pedido.blocos:
        if b.tipo == "regra":
            blocos.append(BlocoRegra(nome=b.nome, parametros=dict(b.parametros)))
        else:
            d = b.declaracao
            try:
                # `AgenteDeclarado.__post_init__` recusa vocabulário vazio,
                # prompt que não interpola nada e `abstem_com` colidindo com um
                # tipo. São recusas de DOMÍNIO, com texto escrito para ser lido,
                # e viram o 422 — não um erro de schema do Pydantic, que diria
                # "field required" onde a verdade é "isso mediria errado".
                blocos.append(
                    BlocoAgente(
                        declaracao=AgenteDeclarado(
                            name=d.name,
                            system=d.system,
                            kind=d.kind,
                            prompt=d.prompt,
                            tipos=tuple(d.tipos),
                            abstem_com=d.abstem_com,
                            ferramentas=tuple(d.ferramentas),
                            max_turns=d.max_turns,
                            budget_microcents=d.budget_microcents,
                        )
                    )
                )
            except ValueError as erro:
                raise HTTPException(status_code=422, detail=str(erro)) from erro

    try:
        composicao = Composicao(
            id=pedido.id,
            nome=pedido.nome,
            dominio=pedido.dominio,
            justificativa=pedido.justificativa,
            # Relógio do SERVIDOR, como em `/api/receitas`: um timestamp do
            # cliente permitiria gravar uma composição "criada" antes de outra
            # que a antecedeu.
            gerado_em=datetime.now(UTC),
            blocos=tuple(blocos),
        )
        definicao = construir_composicao(composicao)
    except KeyError as erro:
        # Domínio desconhecido. `KeyError` formata com aspas extras em `str()`,
        # então usa o argumento — a mensagem já lista os disponíveis.
        raise HTTPException(status_code=422, detail=erro.args[0]) from erro
    except ValueError as erro:
        raise HTTPException(status_code=422, detail=str(erro)) from erro

    try:
        gravar(composicao, _RAIZ_COMPOSICOES)
    except FileExistsError as erro:
        raise HTTPException(status_code=409, detail=str(erro)) from erro
    return workflow_json(definicao)


@app.get("/api/composicoes", response_model=list[ComposicaoResumoJSON])
def listar_composicoes() -> list[ComposicaoResumoJSON]:
    """As composições em disco.

    Existe para que gravar não seja escrever num buraco: sem esta rota, uma
    composição criada pela tela sumiria de vista — ela não entra no `registry()`
    dos workflows, que lê receitas do grill. **Executar uma composição ainda não
    tem caminho**, e essa lacuna fica visível aqui em vez de escondida.
    """
    return [
        ComposicaoResumoJSON(
            id=c.id,
            nome=c.nome,
            dominio=c.dominio,
            version=c.version,
            gerado_em=c.gerado_em.isoformat(),
            blocos=list(c.nomes),
        )
        for c in listar(_RAIZ_COMPOSICOES)
    ]


@app.get("/api/workflows/{workflow_id}", response_model=WorkflowJSON)
def obter_workflow(workflow_id: str) -> WorkflowJSON:
    fabrica = registry(_RAIZ_RECEITAS).get(workflow_id)
    if fabrica is None:
        raise HTTPException(status_code=404, detail=f"workflow desconhecido: {workflow_id}")
    # Mesma construção de `_executar`, nunca uma segunda via direto
    # por `fabrica(...)`: `definition.py` declara que não existe "definição
    # servida" separada da "definição executada", e duas chamadas para o
    # mesmo objeto são exatamente o jeito de esse invariante parar de ser
    # estrutural. A fila vazia é inofensiva aqui — esta rota só descreve a
    # FORMA da cascata, que não muda com o conteúdo da fila.
    return workflow_json(construir_definicao(fabrica, WorkflowContext.vazio()))


@app.post("/api/workflows/{workflow_id}/runs", response_model=RunJSON)
def executar(workflow_id: str, pedido: RunRequest) -> RunJSON:
    fabrica = registry(_RAIZ_RECEITAS).get(workflow_id)
    if fabrica is None:
        # 404 antes do cache, de propósito: um id desconhecido nunca deve
        # entrar em `_executar`, nem para virar um run persistido de um
        # workflow que não existe.
        raise HTTPException(status_code=404, detail=f"workflow desconhecido: {workflow_id}")
    return _executar(workflow_id, pedido.seed, pedido.n, pedido.taxa_divergencia)


def _executar(workflow_id: str, seed: int, n: int, taxa: float) -> RunJSON:
    """Executa e PERSISTE o run. Sem cache.

    Era `@lru_cache(maxsize=64)`, e o docstring de então já admitia o problema:
    a função tinha deixado de ser pura nos três parâmetros (ela lê a fila em
    disco), e por isso o POST de decisão precisava chamar `cache_clear()` ou
    uma aprovação recente ficaria invisível.

    Um cache que precisa ser invalidado à mão por outro endpoint não é cache —
    é um store com o nome errado. O `RunStore` do PR #7 é o store de verdade, e
    não invalida errado porque não finge ser cache. A execução voltou a rodar a
    cada chamada: para uma cascata só de regras sobre n=300 isso é dezenas de
    milissegundos, e ADR-14 registra o gatilho para revisitar.

    A definição servida aqui não tem agente: a execução não faz rede e não
    gasta em tokens. É isso que torna seguro um endpoint que qualquer F5
    dispara.
    """
    # O coletor assina o barramento. O domínio não sabe que está sendo
    # observado — ver `observability/collector.py`.
    bus = EventBus()
    coletor = SpanCollector().subscribe(bus)
    fonte = SyntheticSource(seed=seed, n=n, taxa_divergencia=taxa)
    dataset = fonte.dataset()
    fila, _ = _abrir_fila(workflow_id, seed, n, taxa)
    definicao = construir_definicao(
        registry(_RAIZ_RECEITAS)[workflow_id], WorkflowContext(fila=fila)
    )

    # A regra deste módulo — nenhum endpoint gasta dinheiro — aplicada a
    # cascatas que a API não escreveu. Levantar aqui é seguro e agora é
    # trivialmente seguro: sem cache, não há entrada para envenenar.
    #
    # Esta é a porta educada. A tranca é `ClienteAusente`, que `construir`
    # injeta por default e que levanta se alguém chegar ao modelo por aqui.
    classes = {r.cost_class for s in definicao.stages for r in s.cascade}
    if CostClass.AGENTE in classes:
        raise HTTPException(
            status_code=409,
            detail=(
                f"o workflow {workflow_id!r} tem uma etapa paga e não pode ser "
                f"executado pela web. rode pela CLI."
            ),
        )

    resultado = reconcile(
        dataset.bank,
        dataset.ledger,
        definition=definicao,
        # O `ref` vem da FONTE, não montado aqui: duas expressões que precisam
        # concordar sobre o formato de um id são o join frágil de sempre.
        input_ref=fonte.ref,
        bus=bus,
    )
    # O run vai para o store ANTES de qualquer projeção para JSON: o que a tela
    # mostra é derivado, o que o store guarda é o fato.
    if resultado.run is not None:
        _run_store().save(resultado.run)
        _trace_store().save(coletor.trace(resultado.run))
    m = evaluate(dataset, resultado)

    total = m.bank_total
    por_resolver = [
        ResolverRunJSON(
            name=d.name,
            cost_class=d.cost_class.name,
            # `resultado.matches_by_resolver`, chaveado por IDENTIDADE do
            # resolver — não `m.matches_by_layer`, que é chaveado por
            # PROVENIÊNCIA (`MatchResult.layer`). Os dois coincidem hoje
            # (P3.2 em DECISOES.md), mas só um deles responde "quanto este
            # resolver da cascata resolveu" por construção.
            matches=resultado.matches_by_resolver.get(d.name, 0),
            rate=resultado.matches_by_resolver.get(d.name, 0) / total if total else 0.0,
            microcents=m.cost_by_resolver_microcents.get(d.name, 0),
        )
        for stage in definicao.stages
        for d in (r.describe() for r in stage.ordered())
    ]
    # A lacuna usa `bank_matched_total`, não a soma das contagens por
    # resolver. A soma assumiria que todo MatchResult carrega exatamente um id
    # bancário — verdade hoje, mas não garantida pelo tipo — e, se algum dia
    # deixasse de ser, a lacuna iria a negativo em vez de crescer.
    # `bank_matched_total` já é o conjunto de ids bancários casados
    # intersectado com o dataset real (ver `evaluate`), então não depende
    # dessa suposição. Como consequência, a soma
    # `sum(rate por resolver) + gap.rate == 1.0` deixa de assumir a invariante
    # "um id bancário por match" e passa a VERIFICÁ-LA.
    #
    # `_total` (todas as classes), não `bank_matched` (só REGRA — Task 5): o
    # revisor humano é classe HUMANO, e uma decisão aprovada precisa fechar a
    # lacuna do canvas, não continuar contada como aberta.
    total_resolvido = m.bank_matched_total
    return RunJSON(
        seed=seed,
        n=n,
        bank_total=total,
        deterministic_rate=m.deterministic_rate,
        by_resolver=por_resolver,
        gap=GapJSON(
            items=total - total_resolvido,
            rate=(total - total_resolvido) / total if total else 0.0,
        ),
    )


# Raiz da fila em disco. É atributo de módulo para o teste poder trocá-la por
# um tmp_path sem escrever no repositório.
_RAIZ_FILA: Path | None = None


def _run_store() -> JsonlRunStore:
    """O store de runs, sob a MESMA raiz isolada da fila.

    Sem isso, `conftest.py` isolaria a fila e não os runs, e a suíte passaria a
    escrever em `data/runs.jsonl` do desenvolvedor — exatamente o defeito que a
    fixture autouse de `conftest` existe para impedir, e que o docstring dela
    descreve.
    """
    return JsonlRunStore((_RAIZ_FILA or Path("data")) / "runs.jsonl")


def _trace_store() -> JsonlTraceStore:
    """Sob a MESMA raiz isolada do run store, pelo mesmo motivo: sem isso a
    suíte passaria a escrever `data/traces/` na máquina do desenvolvedor."""
    return JsonlTraceStore(_RAIZ_FILA or Path("data"))


def _abrir_fila(workflow_id: str, seed: int, n: int, taxa: float) -> tuple[Fila, str]:
    dataset = dataset_id(seed, n, taxa)
    return Fila(caminho_da_fila(workflow_id, dataset, raiz=_RAIZ_FILA)), dataset


def _do_banco(e) -> LancamentoJSON:
    return LancamentoJSON(
        id=e.id, lado="banco", data=e.date.isoformat(), valor=e.amount,
        descricao=e.description, contraparte=e.counterparty or "",
        documento=e.document,
    )


def _do_contabil(e) -> LancamentoJSON:
    # `net_amount` é o que se compara com o extrato; `cash_date` é a data que
    # importa para conciliar, com `accrual_date` como reserva quando o caixa
    # ainda não foi registrado.
    return LancamentoJSON(
        id=e.id, lado="contabil",
        data=(e.cash_date or e.accrual_date).isoformat(), valor=e.net_amount,
        descricao=e.account, contraparte=e.supplier, documento=e.document,
    )


def _ids_da_divergencia(divergence_id: str) -> set[str]:
    """`d-b-<id>` e `d-l-<id>` carregam o id do lançamento no próprio nome."""
    for prefixo in ("d-b-", "d-l-"):
        if divergence_id.startswith(prefixo):
            return {divergence_id[len(prefixo):]}
    return set()


def _item(proposta, decisao, por_id) -> ItemFilaJSON:
    ids = ids_de_conciliar_com(proposta.acao_sugerida)
    # O revisor precisa ver extrato e contábil lado a lado — o veredito do
    # agente sozinho não dá para julgar nada.
    do_item = _ids_da_divergencia(proposta.item_id) | ids
    lancamentos = []
    for i in sorted(do_item):
        par = por_id.get(i)
        if par is None:
            continue
        lado, e = par
        lancamentos.append(_do_banco(e) if lado == "banco" else _do_contabil(e))
    divergiu = decisao is not None and (
        decisao.tipo is not proposta.tipo or decisao.conciliar_com != ids
    )
    return ItemFilaJSON(
        divergence_id=proposta.item_id,
        tipo=proposta.tipo.value,
        confianca=proposta.confianca.value,
        explicacao=proposta.explicacao,
        evidencia=list(proposta.evidencia),
        acao_sugerida=proposta.acao_sugerida,
        conciliar_com=sorted(ids),
        lancamentos=lancamentos,
        decidido=decisao is not None,
        veredito=decisao.veredito.value if decisao else None,
        tipo_decidido=decisao.tipo.value if decisao and decisao.tipo else None,
        autor=decisao.autor if decisao else None,
        divergiu=divergiu,
    )


@app.get("/api/fila/{workflow_id}", response_model=FilaJSON)
def ler_fila(
    workflow_id: str,
    # Mesmos limites de `RunRequest` (schemas.py), pelo mesmo motivo: sem
    # eles, `build_benchmark` recebe um valor fora de faixa e levanta
    # `ValueError`, que o FastAPI transforma em 500 — em vez do 422 que um
    # parâmetro de query inválido deveria produzir.
    seed: int = Query(1, ge=0),
    n: int = Query(300, ge=1, le=5000),
    taxa_divergencia: float = Query(0.15, ge=0.0, le=1.0),
    # `Literal`, não `str`: um valor que não seja exatamente "pendente" fazia
    # a rota tratar QUALQUER outra coisa — inclusive um typo como
    # "pendentes" — como "decidida", devolvendo os itens já resolvidos sem
    # aviso nenhum.
    estado: Literal["pendente", "decidida"] = "pendente",
) -> FilaJSON:
    if workflow_id not in registry(_RAIZ_RECEITAS):
        raise HTTPException(status_code=404, detail=f"workflow desconhecido: {workflow_id}")
    fila, dataset = _abrir_fila(workflow_id, seed, n, taxa_divergencia)
    ds = build_benchmark(seed=seed, n=n, taxa_divergencia=taxa_divergencia)
    por_id = {e.id: ("banco", e) for e in ds.bank}
    por_id.update({e.id: ("contabil", e) for e in ds.ledger})

    pares = (
        [(p, None) for p in fila.pendentes()]
        if estado == "pendente"
        else list(fila.decididas())
    )
    return FilaJSON(
        workflow=workflow_id,
        dataset=dataset,
        itens=[_item(p, d, por_id) for p, d in pares],
        tipos=[t.value for t in DivergenceType],
    )


@app.post("/api/fila/{workflow_id}/{divergence_id}/decisao", response_model=ItemFilaJSON)
def decidir(
    workflow_id: str,
    divergence_id: str,
    pedido: DecisaoRequest,
    seed: int = Query(1, ge=0),
    n: int = Query(300, ge=1, le=5000),
    taxa_divergencia: float = Query(0.15, ge=0.0, le=1.0),
) -> ItemFilaJSON:
    if workflow_id not in registry(_RAIZ_RECEITAS):
        raise HTTPException(status_code=404, detail=f"workflow desconhecido: {workflow_id}")
    fila, _ = _abrir_fila(workflow_id, seed, n, taxa_divergencia)

    # `corrigir` sem `tipo` nunca chega aqui: `DecisaoRequest._corrigir_exige_tipo`
    # (schemas.py) é um `@model_validator`, e o FastAPI devolve 422 antes de o
    # handler rodar — logo antes de qualquer busca, sem depender de ordem
    # escrita à mão contra o 404 de proposta ausente.
    proposta = fila.proposta(divergence_id)
    if proposta is None:
        raise HTTPException(
            status_code=404,
            detail=f"sem proposta para {divergence_id}; decidir sem proposta do "
                   f"agente está fora do escopo desta fatia",
        )

    # Construído ANTES de qualquer escrita, de propósito: `seed`/`n`/
    # `taxa_divergencia` já são validados pelos limites de `Query` acima, mas
    # se algo mesmo assim levantasse aqui, ele precisa levantar antes de
    # `gravar_decisao` — nunca depois. Uma exceção depois da escrita chega ao
    # cliente como falha, e a escrita já é durável (append-only); um retry
    # razoável do cliente grava uma SEGUNDA decisão para o mesmo clique.
    # `por_id` também é reusado no fim da função, então só monta uma vez.
    ds = build_benchmark(seed=seed, n=n, taxa_divergencia=taxa_divergencia)
    por_id = {e.id: ("banco", e) for e in ds.bank}
    por_id.update({e.id: ("contabil", e) for e in ds.ledger})

    if pedido.veredito is Veredito.ACEITAR:
        tipo = proposta.tipo
        ids = ids_de_conciliar_com(proposta.acao_sugerida)
        # `acao_sugerida` só é validada, antes de chegar aqui, por
        # `startswith` (ver `investigator.py`) — um prefixo correto com forma
        # quebrada, como `"conciliar_com:l1"` (faltam os parênteses), passa
        # por aquela checagem e chega até aqui. Aceitar isso em silêncio
        # gravaria uma decisão "aceita" que concilia ZERO lançamentos: o item
        # some da tela de pendentes, mas nenhum vínculo é criado, e ninguém
        # percebe. Uma ação que LEGITIMAMENTE concilia nada
        # (`investigar_manual`, `ajustar(...)`) não começa com
        # `conciliar_com` e não cai aqui.
        if proposta.acao_sugerida.startswith("conciliar_com") and not ids:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"ação sugerida pelo agente é malformada: "
                    f"{proposta.acao_sugerida!r} não extrai nenhum id; use "
                    f"`corrigir` para informar os ids a conciliar"
                ),
            )
    elif pedido.veredito is Veredito.CORRIGIR:
        tipo = pedido.tipo
        ids = frozenset(pedido.conciliar_com or [])
        # Mesma falha que o guard de `aceitar` acima, só que do lado humano:
        # um id que não existe em NENHUM dos dois lados do dataset chega
        # intacto até `revisor.py`, que marca a decisão inteira "obsoleta" e
        # a descarta — sem match, sem erro. O reviewer vê 200, o item some de
        # `pendentes()`, `divergiu` acusa divergência do agente, o log de
        # auditoria registra uma "correção aprovada", e nenhum vínculo é
        # criado. Uma lista VAZIA continua legítima: corrigir só o tipo, sem
        # conciliar nada, é a mesma abstenção que `investigar_manual` já é.
        desconhecidos = sorted(ids - por_id.keys())
        if desconhecidos:
            raise HTTPException(
                status_code=422,
                detail=f"ids inexistentes neste dataset: {desconhecidos}",
            )
    else:
        tipo, ids = None, frozenset()

    fila.gravar_decisao(
        Decision(
            divergence_id=divergence_id, veredito=pedido.veredito, tipo=tipo,
            conciliar_com=ids, autor=pedido.autor,
            quando=datetime.now(UTC), motivo=pedido.motivo,
        )
    )
    # Não há cache para invalidar desde o PR #7. Aprovar uma proposta e
    # recarregar o canvas mostra o estado novo porque a execução roda de novo,
    # não porque alguém lembrou de limpar uma memoização.

    return _item(proposta, fila.decisao(divergence_id), por_id)


def _resumo_json(s) -> RunResumoJSON:
    return RunResumoJSON(
        id=s.id,
        workflow_id=s.workflow_id,
        workflow_version=s.workflow_version,
        state=s.state.value,
        started_at=s.started_at.isoformat(),
        finished_at=s.finished_at.isoformat() if s.finished_at else None,
        duration_ms=s.duration_ms,
        input_ref=s.input_ref,
        resolved=s.resolved,
        proposed=s.proposed,
        unresolved=s.unresolved,
        # Um resolver que não gastou token nenhum converte para zero em
        # qualquer modelo — a mesma guarda de `metrics.evaluate`, para que uma
        # cascata só de regras não exija um `model` válido para ler zero.
        microcents=sum(
            c.microcents("claude-opus-5") if c != Cost.zero() else 0
            for c in s.cost_by_resolver.values()
        ),
    )


@app.get("/api/runs", response_model=list[RunResumoJSON])
def listar_runs(
    workflow_id: str | None = None,
    state: str | None = None,
    limit: int = Query(50, ge=1, le=500),
) -> list[RunResumoJSON]:
    """O histórico de execuções. Mais recentes primeiro.

    Antes do PR #7 isto era impossível: a "execução" era uma entrada num
    `lru_cache` de 64 posições, sem id, sem timestamp e sem estado. "O que
    aconteceu no fechamento de agosto" não tinha resposta.
    """
    try:
        estado = RunState(state) if state else None
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"estado desconhecido: {state!r}; use um de "
            f"{[e.value for e in RunState]}",
        ) from None
    return [
        _resumo_json(s)
        for s in _run_store().list(workflow_id=workflow_id, state=estado, limit=limit)
    ]


@app.get("/api/runs/{run_id}", response_model=RunResumoJSON)
def obter_run(run_id: str) -> RunResumoJSON:
    achado = _run_store().get(run_id)
    if achado is None:
        raise HTTPException(status_code=404, detail=f"run desconhecido: {run_id}")
    return _resumo_json(achado)


# De `src/orchestrator/api/app.py`: parents[0] é `api`, [1] é `orchestrator`,
# [2] é `src`, [3] é a raiz do repositório — é lá que mora `web/`.
_WEB = Path(__file__).resolve().parents[3] / "web"

# Este `mount("/")` PRECISA ser a última linha do arquivo. `StaticFiles` com
# `html=True` responde por qualquer caminho não reconhecido (inclusive `/`,
# servindo `index.html`), então se ele viesse antes das rotas `/api/...`
# elas nunca seriam alcançadas — o mount as engoliria todas.
app.mount("/", StaticFiles(directory=_WEB, html=True), name="web")
