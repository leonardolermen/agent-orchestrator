"""O app HTTP do canvas.

**A regra que governa este módulo ficou MAIS PRECISA outra vez, e desta vez ela
deixou de ser uma proibição.**

Ela nasceu como *"nenhum endpoint daqui pode gastar dinheiro"*. Depois virou
*"EXECUTAR não gasta; COMPOR por conversa gasta, com teto"* — a entrevista
(`api/entrevista.py`) é a exceção que compõe sem executar. Agora:

    EXECUTAR pela web GASTA quando a cascata tem agente, com teto, e o teto é
    dito antes.
    COMPOR por conversa gasta, com teto, e o teto é dito antes.

**O que a proibição protegia, e por que ela não servia mais.** Ela impedia que
rodar um workflow pela web virasse uma conta. O preço era que uma cascata com
agente simplesmente não rodava por aqui: quem compôs na tela tinha de abrir um
terminal. E o preço era pago por INTEIRO — até aqui nenhum bloco do catálogo
executável por `/runs` consumia um CSV, porque as regras exigem payload tipado
e os três agentes, os únicos que leem dicionário, eram os barrados. A tela
compunha o que ela mesma não conseguia rodar.

**Este é o caminho pelo qual quem alcança o servidor gasta o crédito de quem o
hospeda.** As três guardas abaixo são o que torna isso aceitável, são as mesmas
de `api/entrevista.py`, e nenhuma é opcional:

**Guarda 1 — teto por REQUISIÇÃO, e ele é OBRIGATÓRIO aqui.**
`RunRequest.teto_microcents` vira um `ClienteComTeto` (`agent/teto.py`) que toda
chamada paga da execução atravessa. Pela web, com agente, omiti-lo é 422: a
guarda inteira é *"gasta com teto, e o teto é dito ANTES"*, e um pedido que o
omite não disse teto nenhum — ele herda o do agente, que são US$ 4,00 por
requisição, numa rota sem autenticação e sem cache que qualquer F5 dispara de
novo. Herdar em silêncio é o fallback que a primeira regra do projeto proíbe.
(No schema `None` continua válido, para a CLI e para quem chama a biblioteca, e
lá ele significa o teto do próprio agente — nunca ilimitado.)

**Guarda 2 — o custo volta em CADA desfecho, e o DESFECHO também.** No caminho
feliz, `RunJSON` leva `custo_microcents`, `estado`, `propostas_por_tipo`,
`falhas` e `teto_atingido`, e o run vai para o `RunStore`. No caminho de erro, o
custo vai no corpo do 500. Gasto que não aparece na tela é gasto que ninguém
revisa — e "não achamos nada", "paramos no teto" e "a API falhou" precisam ser
três respostas diferentes, porque `agent/conversa.py` as faz virar a mesma
abstenção.

**Guarda 3 — sem chave, recusa legível.** Sem `ANTHROPIC_API_KEY` a cascata com
agente é recusada com 409 ANTES de executar, em vez de o SDK levantar no meio
do laço com metade do trabalho feito.

**A tranca continua sendo `ClienteAusente`**, o default de
`grill.receita.construir`. `_cliente_de_execucao` — o único caminho de código
daqui até o modelo por `/runs` — só é construído quando a cascata tem agente E
há chave. Desarmar a tranca é ato explícito, e só acontece nesse ponto.
"""

import os
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi.staticfiles import StaticFiles

from orchestrator.agent.declarado import AgenteDeclarado, RegraDisponivel
from orchestrator.agent.teto import ClienteComTeto
from orchestrator.agent.tools.registry import ToolRegistry
from orchestrator.api.entrevista import conduzir
from orchestrator.api.schemas import (
    AgenteDeclaradoJSON,
    AmbienteJSON,
    BlocoJSON,
    CatalogoJSON,
    ComposicaoRequest,
    ComposicaoResumoJSON,
    DecisaoRequest,
    FerramentaJSON,
    FilaJSON,
    GapJSON,
    ItemFilaJSON,
    LancamentoJSON,
    MedidoJSON,
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
    BlocoCrew,
    BlocoRegra,
    Composicao,
    Etapa,
    construir_composicao,
    gravar,
    listar,
)
from orchestrator.domains.reconciliation import ReconcileResult
from orchestrator.domains.reconciliation.synth.benchmark import SyntheticSource, build_benchmark
from orchestrator.domains.reconciliation.synth.dataset import Dataset
from orchestrator.domains.reconciliation.taxonomy import DivergenceType
from orchestrator.domains.registro import CATALOGO
from orchestrator.grill.catalogo import MODELO_INERTE
from orchestrator.grill.receita import Receita, ResolverReceita, construir
from orchestrator.grill.registro import gravar_receita, listar_receitas
from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.definition import WorkflowDefinition
from orchestrator.kernel.event import EventBus
from orchestrator.kernel.resolution import TraceKind
from orchestrator.kernel.run import RunState
from orchestrator.kernel.work import WorkSet
from orchestrator.metrics import evaluate
from orchestrator.observability.collector import SpanCollector
from orchestrator.review.decision import Decision, Veredito, ids_de_conciliar_com
from orchestrator.review.fila import Fila, caminho_da_fila, dataset_de_ref
from orchestrator.runtime.engine import execute
from orchestrator.sources.arquivo import ArquivoSource, RaizViolada
from orchestrator.sources.erros import ErroDeFonte
from orchestrator.sources.http import HttpSource
from orchestrator.sources.postgres import PostgresSource
from orchestrator.storage.jsonl.run_store import JsonlRunStore
from orchestrator.storage.jsonl.trace_store import JsonlTraceStore
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

# A CERCA das fontes de arquivo. `caminho` chega pela rede e vira uma leitura
# de disco aqui dentro; sem raiz, `/runs` é um leitor de arquivos arbitrários
# do servidor. O alvo que importa não é `/etc/passwd` — é `data/fila/**`, que
# devolveria a trilha de decisões humanas de OUTRO workflow.
#
# Concreta e não `Path | None` como as duas acima: elas têm um default no
# consumidor (`Path("data")`), esta é o próprio default. Continua sendo
# atributo de módulo para o teste trocá-la por um `tmp_path`.
_RAIZ_ENTRADAS = Path(__file__).resolve().parents[3] / "data" / "entradas"


def _tem_chave() -> bool:
    """O servidor tem credencial para falar com o modelo?

    Função de MÓDULO, e é isso que a torna substituível por `monkeypatch` num
    teste sem tocar no ambiente de verdade — que é o que impede a suíte de
    depender de a variável estar ou não posta na máquina de quem roda.

    Uma leitura só, usada por `/api/ambiente` (que anuncia) e pela guarda 3 de
    `_executar` (que recusa). Duas leituras seriam duas respostas para a mesma
    pergunta, e a tela acabaria oferecendo o botão que o servidor recusa.
    """
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _cliente_de_execucao(teto_microcents: int | None) -> ClienteComTeto:
    """O cliente REAL, com o teto DESTA requisição. Um por execução.

    **É o único caminho de código daqui até o modelo pela rota `/runs`**, e por
    isso ele é chamado num ponto só: depois de saber que a cascata tem agente e
    que há chave. Fora dali a construção cai no `ClienteAusente`, que levanta se
    alguém chegar ao modelo por onde não deveria existir caminho.

    Construir NÃO fala com a rede: `AnthropicClient` só instancia o SDK na
    primeira chamada (ver o docstring de lá), então até aqui nada foi gasto e
    nada foi contatado.

    `teto_microcents=None` NÃO é "sem teto" — ver `agent/teto.py`.
    """
    from orchestrator.agent.anthropic_client import AnthropicClient

    return ClienteComTeto(AnthropicClient(), teto_microcents=teto_microcents)


@app.get("/api/workflows", response_model=list[WorkflowResumoJSON])
def listar_workflows() -> list[WorkflowResumoJSON]:
    """Os workflows, e se ESTE servidor consegue rodar cada um.

    `executavel` era "a cascata não tem AGENTE", porque `/runs` recusava toda
    cascata paga. A pergunta que a tela faz nunca foi essa — é "o botão Run vai
    funcionar?" —, e com o caminho pago aberto a resposta passou a depender da
    chave. Manter a fórmula antiga faria a API desabilitar um botão para uma
    execução que ela própria aceitaria: uma tela mentindo sobre o servidor que
    a serve.
    """
    # UMA leitura do ambiente para a listagem inteira. Ler por workflow deixaria
    # a mesma resposta variar dentro de uma resposta só, se a variável mudasse
    # no meio.
    com_chave = _tem_chave()
    resumos = []
    por_id = {r.id: r for r in listar_receitas(_RAIZ_RECEITAS)}
    por_id.update({c.id: c for c in listar(_RAIZ_COMPOSICOES)})
    # `descrever` já isola a receita que parseia e não constrói: um arquivo
    # ruim não derruba a listagem inteira, mas também não some em silêncio.
    # A lógica saiu daqui para `workflows.py` porque a CLI precisa da mesma
    # resposta, e duas cópias seriam o join frágil de sempre.
    for workflow_id, definicao in descrever(_RAIZ_RECEITAS, _RAIZ_COMPOSICOES):
        classes = sorted(
            {r.cost_class.name for s in definicao.stages for r in s.cascade}
        )
        origem = por_id.get(workflow_id)
        resumos.append(
            WorkflowResumoJSON(
                id=workflow_id,
                nome=definicao.name,
                classes=classes,
                gerado_em=origem.gerado_em.isoformat() if origem else None,
                executavel=CostClass.AGENTE.name not in classes or com_chave,
            )
        )
    return resumos


def _ferramenta_json(ferramentas: ToolRegistry, nome: str) -> FerramentaJSON:
    """A descrição vem do `ToolSpec`. Nunca escrita à mão nesta camada."""
    return FerramentaJSON(nome=nome, descricao=ferramentas.spec(nome).description)


def _declaracao(d: AgenteDeclaradoJSON) -> AgenteDeclarado:
    """Um `AgenteDeclarado` a partir do JSON. Levanta `ValueError` do DOMÍNIO.

    Extraído porque agora há dois lugares que declaram agente — o bloco de
    agente e o de tripulação —, e duplicar a conversão faria a recusa divergir
    entre os dois.
    """
    return AgenteDeclarado(
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


def _blocos_de(pedidos: list[BlocoJSON]) -> list[Bloco]:
    """Os blocos de UMA etapa, do JSON para o domínio.

    Era o corpo do laço da rota, quando havia um degrau só. Virou função porque
    agora há uma lista de etapas e cada uma tem os seus — e duplicar este
    tratamento por etapa faria a recusa do agente declarado divergir entre a
    primeira e as demais.
    """
    blocos: list[Bloco] = []
    for b in pedidos:
        if b.tipo == "regra":
            blocos.append(BlocoRegra(nome=b.nome, parametros=dict(b.parametros)))
            continue
        if b.tipo == "crew":
            try:
                blocos.append(
                    BlocoCrew(
                        nome=b.nome,
                        agentes=tuple(_declaracao(a) for a in b.agentes),
                        process=b.process,
                        conflito=b.conflito,
                        budget_microcents=b.budget_microcents,
                    )
                )
            except ValueError as erro:
                raise HTTPException(status_code=422, detail=str(erro)) from erro
            continue
        d = b.declaracao
        try:
            # `AgenteDeclarado.__post_init__` recusa vocabulário vazio, prompt
            # que não interpola nada e `abstem_com` colidindo com um tipo. São
            # recusas de DOMÍNIO, com texto escrito para ser lido, e viram o
            # 422 — não um erro de schema do Pydantic, que diria "field
            # required" onde a verdade é "isso mediria errado".
            blocos.append(BlocoAgente(declaracao=_declaracao(d)))
        except ValueError as erro:
            raise HTTPException(status_code=422, detail=str(erro)) from erro
    return blocos


def _regra_json(r: RegraDisponivel) -> RegraJSON:
    """Todo campo é lido da `RegraDisponivel`. Nenhum digitado aqui.

    Existiam duas rotas servindo isto (`/api/catalogo` e `/api/dominios`), e a
    extração era o que impedia as duas de divergirem. Sobrou uma — e a regra
    continua valendo pelo motivo maior: um valor escrito à mão na camada HTTP
    faria a tela oferecer um parâmetro que `construir` recusa.
    """
    return RegraJSON(
        nome=r.nome,
        cost_class=r.cost_class.name,
        resumo=r.resumo,
        # `or r.nome`: bloco sem rótulo aparece com o nome de identidade em vez
        # de aparecer vazio. A tela nunca mostra um botão em branco.
        rotulo=r.rotulo or r.nome,
        categoria=r.categoria,
        parametros=[
            ParametroJSON(
                nome=p.nome,
                # `list` e não `tuple`: o JSON não tem tupla, e o Pydantic
                # recusaria a própria resposta que serializou.
                default=list(p.default) if isinstance(p.default, tuple) else p.default,
                descricao=p.descricao,
                obrigatorio=p.obrigatorio,
            )
            for p in r.parametros
        ],
    )


def _agente_json(a: AgenteDeclarado) -> AgenteDeclaradoJSON:
    """Projeção do `AgenteDeclarado`, campo a campo — nada inventado aqui.

    O que a tela edita é o que o catálogo declara: um default escrito nesta
    camada viraria um agente que o canvas mostra e `construir_agente` recusa.
    """
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
        # A MESMA leitura que a guarda 3 de `_executar` usa para recusar. Duas
        # leituras divergiriam no dia em que uma das duas mudasse de critério, e
        # o sintoma seria a tela anunciar que dá para rodar o que a rota recusa.
        tem_chave=_tem_chave(),
        seed=1,
        n=300,
        n_max=5000,
        taxa_divergencia=0.15,
    )


def _gravar_receita_do_chat(receita: Receita) -> None:
    """A TERCEIRA porta de escrita, com a mesma tranca das outras duas.

    `gravar_receita` só sabe se o ARQUIVO de receita existe — não consulta o
    `registry()`. Sem esta checagem, o chat gravava uma receita com o id de uma
    composição do canvas, e a composição sumia no pulo-com-aviso de
    `registry()`: um `stderr` do servidor, invisível para quem usa a tela, e o
    link `/?workflow=<id>` do painel passava a abrir outro workflow.

    O id é um espaço só para embutido, receita e composição — então as três
    portas recusam pela MESMA leitura e com a MESMA frase. `ValueError` e não
    `HTTPException` porque um WebSocket não carrega status HTTP: `conduzir`
    traduz esta recusa no desfecho `recusa` que a tela já sabe mostrar.
    """
    if receita.id in registry(_RAIZ_RECEITAS, _RAIZ_COMPOSICOES):
        raise ValueError(f"já existe um workflow com id {receita.id!r}; escolha outro")
    gravar_receita(receita, _RAIZ_RECEITAS)


@app.websocket("/api/entrevista")
async def entrevista(ws: WebSocket) -> None:
    """O chat que compõe. GASTA DINHEIRO — ver `api/entrevista.py`."""
    await conduzir(ws, gravar=_gravar_receita_do_chat)


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

    if pedido.id in registry(_RAIZ_RECEITAS, _RAIZ_COMPOSICOES):
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
    """Compõe uma cascata a partir do catálogo. VALIDA CONSTRUINDO.

    É o irmão de `/api/receitas` para o formato geral. A diferença que importa
    está no corpo: uma receita é uma lista de nomes do catálogo; uma composição
    carrega o agente INTEIRO — prompt, vocabulário, ferramentas, orçamento —
    porque esse agente não existe em catálogo nenhum até a pessoa criá-lo.

    **Não passa `contexto`.** Compor não executa, e sem dados o registro segue
    sendo catálogo: se alguém executasse esta definição, as ferramentas
    recusariam com texto em vez de estourar sobre dados ausentes.

    **Não passa `cliente`.** O default de `construir_composicao` é
    `ClienteDeValidacao`, que constrói o agente e recusa falar com modelo. É a
    mesma tranca de `/api/receitas`, e é o que mantém verdadeira a regra deste
    módulo: compor pela web não gasta dinheiro. (A entrevista gasta, com teto, e
    é a exceção declarada no cabeçalho.)
    """
    blocos = _blocos_de(pedido.blocos)

    try:
        composicao = Composicao(
            id=pedido.id,
            nome=pedido.nome,
            justificativa=pedido.justificativa,
            # Relógio do SERVIDOR, como em `/api/receitas`: um timestamp do
            # cliente permitiria gravar uma composição "criada" antes de outra
            # que a antecedeu.
            gerado_em=datetime.now(UTC),
            # `blocos` OU `etapas`, nunca os dois — `Composicao` recusa, e a
            # recusa chega à tela como o 422 que ela já sabe mostrar.
            blocos=tuple(blocos) if not pedido.etapas else (),
            etapas=tuple(
                Etapa(nome=e.nome, blocos=tuple(_blocos_de(e.blocos)))
                for e in pedido.etapas
            ),
            entrega=tuple(pedido.entrega),
        )
        definicao = construir_composicao(composicao)
    except ValueError as erro:
        raise HTTPException(status_code=422, detail=str(erro)) from erro

    if pedido.id in registry(_RAIZ_RECEITAS, _RAIZ_COMPOSICOES):
        # Simétrico a `/api/receitas` e a `_gravar_receita_do_chat`: o id é um
        # só espaço para embutido, receitas e composições. As TRÊS portas de
        # escrita recusam pela mesma leitura — e é isso que faz o
        # pulo-com-aviso de `registry()` ser um caso de disco editado à mão,
        # não de tela. Enquanto o chat gravava sem checar, era caso de tela.
        raise HTTPException(
            status_code=409,
            detail=f"já existe um workflow com id {pedido.id!r}; escolha outro",
        )
    try:
        gravar(composicao, _RAIZ_COMPOSICOES)
    except FileExistsError as erro:
        raise HTTPException(status_code=409, detail=str(erro)) from erro
    return workflow_json(definicao)


@app.get("/api/composicoes", response_model=list[ComposicaoResumoJSON])
def listar_composicoes() -> list[ComposicaoResumoJSON]:
    """As composições em disco.

    Existe para que gravar não seja escrever num buraco: sem esta rota, uma
    composição criada pela tela sumiria de vista antes mesmo de aparecer no
    seletor. Composições entram no `registry()` por `workflows._de_composicao`
    e são executadas pelo MESMO `/api/workflows/{id}/runs` que já executa
    receitas — não há uma segunda rota de execução para composição. "Compor
    pela web não gasta" continua valendo para ESTA rota, que só valida e
    grava; quem gasta, com teto e cliente de verdade, é `/runs`.
    """
    return [
        ComposicaoResumoJSON(
            id=c.id,
            nome=c.nome,
            version=c.version,
            gerado_em=c.gerado_em.isoformat(),
            blocos=list(c.nomes),
        )
        for c in listar(_RAIZ_COMPOSICOES)
    ]


@app.get("/api/workflows/{workflow_id}", response_model=WorkflowJSON)
def obter_workflow(workflow_id: str) -> WorkflowJSON:
    fabrica = registry(_RAIZ_RECEITAS, _RAIZ_COMPOSICOES).get(workflow_id)
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
    fabrica = registry(_RAIZ_RECEITAS, _RAIZ_COMPOSICOES).get(workflow_id)
    if fabrica is None:
        # 404 antes do cache, de propósito: um id desconhecido nunca deve
        # entrar em `_executar`, nem para virar um run persistido de um
        # workflow que não existe.
        raise HTTPException(status_code=404, detail=f"workflow desconhecido: {workflow_id}")
    return _executar(workflow_id, pedido)


def _fonte_de(
    pedido: RunRequest,
) -> tuple[SyntheticSource | ArquivoSource | PostgresSource | HttpSource, Dataset | None]:
    """A fonte e o gabarito, quando existe.

    Quem sabe se há gabarito é a FONTE — não um `if` sobre o id do workflow.
    `SyntheticSource` tem `dataset()`; uma fonte de dado real não tem, e é
    exatamente por isso que `metrics.evaluate` continua exigindo um `Dataset`.

    `Dataset | None` em vez de um método no protocolo: `kernel/source.py` diz
    que gabarito é insumo de AVALIAÇÃO e o motor não deve recebê-lo. Pôr
    `gabarito()` no `Source` obrigaria toda fonte de dado real a implementar um
    método que devolve `None` — e convidaria alguém a chamá-lo no motor.
    """
    f = pedido.fonte
    if f.tipo == "sintetica":
        fonte = SyntheticSource(seed=f.seed, n=f.n, taxa_divergencia=f.taxa_divergencia)
        return fonte, fonte.dataset()
    if f.tipo == "postgres":
        return (
            PostgresSource(dsn_env=f.dsn_env, query=f.query, kind=f.kind, campo_id=f.campo_id),
            None,
        )
    if f.tipo == "http":
        return (
            HttpSource(
                url=f.url,
                token_env=f.token_env,
                kind=f.kind,
                campo_id=f.campo_id,
                caminho=f.caminho,
            ),
            None,
        )
    try:
        return (
            # `_RAIZ_ENTRADAS / f.caminho` com um `f.caminho` ABSOLUTO não
            # concatena: o `Path` da direita vence, e o resultado cai fora da
            # raiz. É a cerca do `ArquivoSource` que recusa, e é por isso que
            # não há validação de forma escrita à mão aqui.
            ArquivoSource(
                caminho=_RAIZ_ENTRADAS / f.caminho,
                kind=f.kind,
                campo_id=f.campo_id,
                raiz=_RAIZ_ENTRADAS,
            ),
            None,
        )
    except RaizViolada as erro:
        # A mensagem do `RaizViolada` cita os dois caminhos ABSOLUTOS, e ela é
        # a certa para um log do servidor. Aqui ela é reescrita com o que o
        # CLIENTE pediu e nada mais: devolver a raiz resolvida entregaria a
        # árvore de diretórios do servidor a quem sondar com nomes errados —
        # a mesma informação que esta cerca existe para negar, saindo pela
        # porta dos fundos.
        raise HTTPException(
            status_code=422,
            detail=f"{f.caminho!r} está fora da raiz de entradas",
        ) from erro


# O `tipo` do discriminador vira prosa. Escrito uma vez, aqui, para que uma
# mensagem ao cliente nunca precise adivinhar como chamar a fonte que ele usou.
_NOME_DA_FONTE = {
    "arquivo": "de arquivo",
    "postgres": "postgres",
    "http": "http",
    "sintetica": "sintética",
}


def _ler(
    fonte: SyntheticSource | ArquivoSource | PostgresSource | HttpSource, pedido: RunRequest
) -> tuple[str, WorkSet]:
    """O `ref` e o pool, na MESMA leitura.

    Os dois juntos de propósito: `ArquivoSource` memoiza os bytes, então pedir
    os dois aqui é UMA leitura de disco, e o `ref` nomeia exatamente o
    conteúdo que virou trabalho.

    E juntos também porque falham juntos. A leitura do `ArquivoSource` é
    PREGUIÇOSA — `__post_init__` só confere a raiz —, então um arquivo que não
    existe, que não é UTF-8, que estoura o teto ou que tem uma linha
    malformada não falha na construção: falha aqui. Sem este `try`, cada um
    desses vira 500, que diz "o servidor quebrou" sobre um arquivo que o
    usuário pode consertar.
    """
    try:
        return fonte.ref, fonte.load()
    except ErroDeFonte as erro:
        # Toda mensagem desta hierarquia foi escrita para o cliente: sem DSN,
        # sem token, sem o que o driver ecoou. Ver `sources/erros.py`.
        raise HTTPException(status_code=422, detail=str(erro)) from erro
    except (OSError, ValueError) as erro:
        if pedido.fonte.tipo == "sintetica":
            # A ÚNICA fonte cujo erro é defeito do SERVIDOR. Ela não lê disco,
            # não conecta em nada e é gerada por nós a partir de três números:
            # se ela levantou, ninguém do lado de fora tem o que consertar, e um
            # 422 culparia o cliente por um bug nosso.
            #
            # A condição era `!= "arquivo"`, escrita quando as duas únicas
            # fontes eram arquivo e sintética. Com `postgres` e `http`, aquela
            # frase passou a significar "toda fonte conectada é defeito do
            # servidor": um `ValueError` puro vindo de `WorkSet.__post_init__`
            # — id repetido, que um `JOIN` do parceiro produz sem esforço —
            # subia como 500 pelas fontes novas e voltava 422 pela de arquivo,
            # sobre o MESMO dado. A lista que merece re-raise é `{sintetica}`.
            raise
        if isinstance(erro, OSError):
            # NUNCA `str(erro)` para um erro de SO: a mensagem do errno embute
            # o caminho ABSOLUTO resolvido. As `ValueError` do `ArquivoSource`
            # citam só `caminho.name`, por desenho, e podem passar inteiras.
            motivo = (
                "arquivo não encontrado"
                if isinstance(erro, FileNotFoundError)
                else "não foi possível ler o arquivo"
            )
        else:
            motivo = str(erro)
        # QUEM falhou. `caminho` só existe (com esse sentido) na fonte de
        # arquivo: `FontePostgres` não tem o campo, e o `caminho` da fonte HTTP
        # é o caminho DENTRO do JSON. Ler `pedido.fonte.caminho` para as duas
        # novas era um `AttributeError` — um 500 dentro do `except` que existe
        # para não devolver 500.
        onde = (
            repr(pedido.fonte.caminho)
            if pedido.fonte.tipo == "arquivo"
            else f"fonte {pedido.fonte.tipo}"
        )
        raise HTTPException(status_code=422, detail=f"{onde}: {motivo}") from erro


def _conferir_payload(definicao: WorkflowDefinition, pool: WorkSet, tipo_da_fonte: str) -> None:
    """A fonte entrega o que os resolvers deste workflow exigem?

    **Esta borda existe porque é a única que junta uma FONTE a um WORKFLOW**, e
    a combinação errada não falhava: estourava. `ArquivoSource` entrega
    `dict`; `ExactMatcher` lê `be.document`. Rodar conciliação sobre um CSV com
    `kind="banco"` devolvia 500 com `AttributeError: 'dict' object has no
    attribute 'document'`, de três camadas abaixo — um erro de SERVIDOR sobre
    uma escolha do CLIENTE, sem dizer qual das duas escolhas estava errada.

    **Não é um `except AttributeError` em volta de `execute()`.** Esse `except`
    engoliria um bug de verdade do motor e o devolveria como um 422 confiante,
    que é pior do que o 500 que ele substituiria. E não é uma lista de nomes de
    resolver nesta camada: ela apodreceria no dia em que alguém escrevesse o
    próximo resolver tipado, em silêncio, exatamente como o `_construir_definicao`
    por `inspect.signature` que `workflows.py` existe para ter matado.

    A exigência é DECLARADA pelo resolver (`ResolverDescription.payloads`) e
    lida aqui. Um resolver que não declara nada não é checado — e está certo:
    `Agent` monta o prompt a partir dos CAMPOS do item e aceita dataclass ou
    dict (ver `agent/declarado.py::_campos`), então um agente declarado roda
    sobre um CSV sem nada a exigir.

    **LIMITE, dito em voz alta: só o pool INICIAL é conferido.** Um stage que
    PRODUZ itens (`ResolverOutput.produced`) os injeta no pool depois daqui, e
    um produtor genérico alimentando um consumidor tipado traz de volta o 500
    original. Fechar isso exige uma declaração do lado do PRODUTOR — que tipo
    ele emite por kind — e o ponto de aplicação seria `runtime/engine.py`, onde
    o motor por desenho nunca inspeciona payload. Inalcançável por
    configuração publicada (nenhum bloco do catálogo produz), e com dois
    testes de plantão em `tests/api/test_execucao.py`: um `xfail(strict)` sobre
    a lacuna e um que falha no dia em que ela virar alcançável pela tela.
    """
    tipos: dict[str, set[type]] = {}
    for item in pool.items:
        tipos.setdefault(item.kind, set()).add(type(item.payload))
    for stage in definicao.stages:
        for resolver in stage.ordered():
            for kind, exigido in resolver.describe().payloads.items():
                entregues = sorted(
                    (t for t in tipos.get(kind, ()) if not issubclass(t, exigido)),
                    key=lambda t: t.__name__,
                )
                if not entregues:
                    continue
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"o resolver {resolver.name!r} exige que itens de kind "
                        f"{kind!r} carreguem {exigido.__name__}, e a fonte "
                        f"entregou {', '.join(t.__name__ for t in entregues)}. "
                        # O TIPO que o pedido usou, e não "uma fonte de
                        # arquivo": a frase foi escrita quando dict só vinha de
                        # arquivo, e hoje três fontes entregam dict — mandava a
                        # pessoa procurar um arquivo que ela não usou.
                        f"uma fonte {_NOME_DA_FONTE.get(tipo_da_fonte, tipo_da_fonte)} "
                        f"entrega dicionários: escolha um "
                        f"workflow cujos blocos leiam campos genéricos, ou um "
                        f"`kind` que esta cascata não consuma."
                    ),
                )


def _conferir_kinds(definicao: WorkflowDefinition, pool: WorkSet) -> None:
    """Cada resolver que declara o que consome é alimentado por esta fonte?

    A irmã de `_conferir_payload`, para a outra pergunta: aquela confere o
    TIPO do payload de um kind que o resolver exige; esta confere se o KIND
    que o resolver pega do pool existe na fonte. Sem ela, um CSV de issues na
    conciliação devolvia 200 com lacuna de 100% — o stage não enxergava nada,
    não rodava, e a resposta parecia medida. É a frase do README que esta
    guarda apaga: "não achei nada" indistinguível de "não procurei".

    **Por RESOLVER, não pela união do degrau.** A união deixaria passar um
    agente cego dentro de um degrau vivo: `L1` alimentado por `banco`
    satisfaz a união, e o agente que consome outro kind roda sem ver item
    nenhum. Foi o caso do `investigador` do catálogo até o conserto.

    **Aqui, e não no motor.** `runtime/engine.py` reserva os kinds que um
    degrau não consome e pula o degrau sem trabalho — semântica certa para um
    grafo de vários degraus. Recusar o RUN inteiro por kind errado é decisão
    de borda: só aqui existem, juntos, a fonte e o workflow.

    Pool vazio é recusa própria, não passe: sem item não há execução, e um
    run "concluído" com zero itens seria mais um número com cara de medido.

    **`entregues` CRESCE a cada degrau, pelo `produz` declarado do stage —
    não fica fixo no pool inicial.** Sem isto, um stage que PRODUZ um kind
    para o próximo (`Stage.produz`, o mesmo grafo do canvas) seria recusado
    aqui mesmo quando o stage seguinte está corretamente alimentado pelo
    anterior: a união do degrau é proibida acima por esconder um agente cego
    dentro de um mesmo stage, mas isso não autoriza fingir que o stage
    seguinte não existe. `Stage.produz` já é a declaração ANTES da execução
    que este módulo pede — é o mesmo grafo que a recusa de beco sem saída em
    `kernel/definition.py` valida.
    """
    if not pool.items:
        raise HTTPException(status_code=422, detail="a fonte não entregou item nenhum")
    entregues = frozenset(item.kind for item in pool.items)
    for stage in definicao.stages:
        for resolver in stage.ordered():
            consome = resolver.describe().consome
            if consome and not (consome & entregues):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"o bloco {resolver.name!r} consome {sorted(consome)}, "
                        f"e a fonte entrega {sorted(entregues)}"
                    ),
                )
        entregues = entregues | stage.produz


def _executar(workflow_id: str, pedido: RunRequest) -> RunJSON:
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

    **Esta rota pode GASTAR, e um F5 a dispara de novo.** Era o contrário —
    nenhuma definição servida aqui tinha agente — e é essa mudança que torna as
    três guardas do cabeçalho deste módulo carga estrutural e não decoração.
    Sem cache não há entrada envenenada para reexecutar de graça, mas também
    não há memoização que segure um segundo clique: o teto por requisição é o
    que limita o estrago de um F5 nervoso, e ele é por requisição justamente
    por isso.

    **Um caminho só, com um ramo no fim.** Chamava `conciliacao.reconcile()`, e
    por isso só sabia executar sobre um extrato e um razão. Agora chama
    `runtime.execute()` sobre o `WorkSet` que a FONTE entregar — é o mesmo
    motor para as duas formas, e o único `if` que sobra é o do gabarito.
    """
    # O coletor assina o barramento. O domínio não sabe que está sendo
    # observado — ver `observability/collector.py`.
    bus = EventBus()
    coletor = SpanCollector().subscribe(bus)
    fonte, gabarito = _fonte_de(pedido)
    fabrica = registry(_RAIZ_RECEITAS, _RAIZ_COMPOSICOES)[workflow_id]
    # A FORMA da cascata, antes de qualquer leitura: `WorkflowContext.vazio()`
    # é o mesmo contexto que `GET /api/workflows` usa para publicar `classes`,
    # e a forma não muda com o conteúdo da fila nem com quem pagaria a conta.
    #
    # Ela existe aqui por causa da guarda logo abaixo: saber se a cascata GASTA
    # é o que permite recusar um pedido sem teto ANTES de tocar a fonte. A
    # definição de verdade — com a fila e, se for o caso, com o cliente — é
    # construída depois, sobre a mesma fábrica.
    forma = construir_definicao(fabrica, WorkflowContext.vazio())
    tem_agente = CostClass.AGENTE in {r.cost_class for s in forma.stages for r in s.cascade}

    # Guarda 1, hasteada para ANTES da fonte, e esta é a razão.
    #
    # Ela é uma checagem PURA sobre o pedido e a cascata: não olha uma linha do
    # pool. Enquanto as fontes eram sintética e arquivo, rodá-la depois da
    # leitura custava trabalho local e barato. Com fontes conectadas, a borda
    # gastava recurso de TERCEIRO — conectava no Postgres do parceiro e esperava
    # a query inteira — para então recusar por um campo ausente do próprio
    # pedido. Repetido, isso é uma torneira contra o banco do parceiro, sem
    # autenticação, disparável por qualquer um que alcance a rota.
    #
    # "Erro do PEDIDO antes de erro do AMBIENTE" continua valendo abaixo; o que
    # esta fatia acrescenta é "erro do pedido antes de TOCAR o parceiro".
    #
    # A guarda inteira é "gasta com teto, E O TETO É DITO ANTES". Um pedido que
    # omite `teto_microcents` não disse teto nenhum: ele HERDA o do agente, que
    # é 400.000.000 µ¢ — US$ 4,00 por requisição — e herdar em silêncio é
    # exatamente o fallback que a primeira regra deste projeto proíbe.
    #
    # `None` continua VÁLIDO no schema, e de propósito: para a CLI e para quem
    # chama a biblioteca, "use o teto do agente" é uma escolha legítima feita
    # por quem já sabe qual é. O que não é legítimo é um cliente HTTP anônimo
    # fazer essa escolha sem escrevê-la.
    if tem_agente and pedido.teto_microcents is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"o workflow {workflow_id!r} tem etapa paga: informe "
                f"`teto_microcents` (micro-centavos de USD, 1e-8 USD cada) "
                f"neste pedido. executar pela web gasta COM TETO, e o teto "
                f"é dito antes — omiti-lo herdaria em silêncio o do agente, "
                f"que é generoso por ser um default."
            ),
        )

    # O `ref` vem ANTES da fila porque a fila depende dele: a chave de
    # `data/fila/**` sai do `ref` da fonte (ver `dataset_de_ref`), e não mais
    # de `(seed, n, taxa)` — que uma fonte de arquivo não tem.
    ref, pool = _ler(fonte, pedido)
    fila, _ = _abrir_fila(workflow_id, ref)
    # A definição com a TRANCA. `cliente=None` é o default de
    # `WorkflowContext`, e `construir` o traduz em `ClienteAusente` — o
    # sentinela que levanta se algum caminho chegar ao modelo por onde não
    # deveria existir caminho nenhum.
    definicao = construir_definicao(fabrica, WorkflowContext(fila=fila))

    # ANTES da guarda de chave, e a ordem inverteu de propósito nesta fatia.
    #
    # O 409 de antes dizia "esta cascata é paga e nunca roda por aqui": uma
    # propriedade permanente da CASCATA, que precedia qualquer coisa sobre o
    # formato do dado. O 409 de agora diz "falta uma chave NO SERVIDOR" —
    # estado do hospedeiro, não do pedido, e que quem manda o POST em geral não
    # pode consertar. Devolvê-lo primeiro mandaria a pessoa atrás de um
    # administrador para, depois da chave posta, descobrir que o CSV dela seria
    # recusado do mesmo jeito. Erro do PEDIDO antes de erro do AMBIENTE.
    _conferir_payload(definicao, pool, pedido.fonte.tipo)
    _conferir_kinds(definicao, pool)

    cliente: ClienteComTeto | None = None
    if tem_agente:
        # A guarda de teto (guarda 1) já rodou lá em cima, antes de a fonte ser
        # tocada — é checagem pura sobre o pedido. Aqui sobra o que depende do
        # AMBIENTE, e ele fica DEPOIS das duas conferências acima de propósito.
        #
        # Guarda 3. ANTES de executar, e não no meio: sem isto o SDK levantaria
        # no primeiro turno com o pool já pela metade, e o que a pessoa veria
        # seria um 500 sobre um problema que tem conserto e nome.
        if not _tem_chave():
            raise HTTPException(
                status_code=409,
                detail=(
                    f"o workflow {workflow_id!r} tem etapa paga e não há "
                    f"ANTHROPIC_API_KEY no ambiente deste servidor. configure a "
                    f"chave ou rode pela CLI."
                ),
            )
        # Guarda 1: o teto do PEDIDO, não o default do agente — que é generoso
        # por ser um default. Só aqui a tranca é desarmada.
        cliente = _cliente_de_execucao(pedido.teto_microcents)
        # Construída OUTRA VEZ, e é o preço de não construir um cliente pago
        # antes de saber que ele é necessário: o cliente entra no `Agent` na
        # CONSTRUÇÃO, então saber se há agente exige uma definição, e ter o
        # cliente certo exige saber se há agente. As duas chamadas passam por
        # `construir_definicao` sobre a mesma fábrica e a mesma fila — a forma
        # é idêntica, e a única diferença é qual cliente mora dentro do agente.
        # A alternativa seria construir o cliente pago sempre, inclusive para
        # cascatas que nunca falam com modelo: mais barato em CPU, e mais caro
        # em tudo que importa aqui.
        definicao = construir_definicao(
            fabrica, WorkflowContext(fila=fila, cliente=cliente)
        )

    # O MESMO modelo que a conversão de custo vai usar, passado explicitamente
    # em vez de deixado no default de `execute`. As duas strings já eram
    # iguais; passar fecha a coincidência — converter custo com um nome
    # diferente do que rodou daria um número que não corresponde a nada.
    modelo = MODELO_INERTE
    # Guarda 2, a metade difícil: o custo precisa sobreviver ao caminho de erro.
    #
    # `Run.cost_by_resolver` só existe se `execute()` RETORNAR. Uma cascata que
    # gastou e depois levantou perdia o número junto com a exceção — dinheiro
    # queimado que nunca aparecia em resposta nenhuma. `ClienteComTeto` é do
    # chamador e vive fora do motor, então o gasto continua legível aqui
    # depois de qualquer falha lá dentro.
    #
    # A captura cobre `execute` E as duas persistências, que é a região em que
    # já se gastou e o trabalho ainda está no ar. A projeção para JSON fica de
    # fora de propósito: quando ela roda, o run já está no store COM o custo, e
    # uma falha ali é defeito nosso que um 500 com traceback relata melhor do
    # que um corpo estruturado que finge saber o que houve.
    try:
        run = execute(definicao, pool, input_ref=ref, bus=bus, model=modelo)
        # O teto DESTA requisição recusou alguma chamada? Uma pergunta, um
        # lugar, uma variável — e é ela que alimenta o `estado` E o campo
        # `teto_atingido` da resposta. Dois cálculos para a mesma pergunta são
        # dois cálculos que divergem, e o sintoma seria uma resposta em que os
        # dois campos se contradizem.
        parou_no_teto = cliente is not None and cliente.recusas > 0
        if parou_no_teto:
            # O MOTOR não tem como saber disto: o teto por requisição vive no
            # cliente, e `execute()` por desenho não inspeciona cliente nenhum —
            # da janela dele, todo item foi processado e o run CONCLUIU. Da
            # janela de quem impôs o teto, o run parou antes de trabalhar.
            #
            # A correção é feita no `Run`, ANTES de persistir, e não só na
            # projeção. Corrigir só a projeção deixaria `/runs` dizendo
            # `limite_de_custo` e `/api/runs` dizendo `concluido` sobre a MESMA
            # execução — duas verdades sobre um fato, que é o defeito que este
            # próprio campo existe para não cometer.
            #
            # Vence `AGUARDANDO_HUMANO` quando os dois se aplicam, pela mesma
            # precedência que o motor já usa para `LIMITE_DE_RONDAS`: o teto é
            # POR QUE existe lacuna, e mandar o operador para a fila de revisão
            # esconderia a causa atrás do sintoma.
            run = replace(run, state=RunState.LIMITE_DE_CUSTO)
        # O run vai para o store ANTES de qualquer projeção para JSON: o que a
        # tela mostra é derivado, o que o store guarda é o fato.
        _run_store().save(run)
        _trace_store().save(coletor.trace(run))
    except Exception as erro:
        raise HTTPException(
            status_code=500,
            detail={
                # O TIPO da exceção, não `str(erro)`: uma mensagem arbitrária
                # do fundo da pilha pode carregar caminho absoluto do servidor,
                # e `_ler` já documenta por que isso não sai por esta porta. O
                # traceback inteiro continua no log — `from erro` o encadeia —,
                # que é onde ele serve para quem opera.
                "motivo": f"a execução falhou: {type(erro).__name__}",
                # O número que a guarda 2 existe para não perder. Sem agente
                # este zero é MEDIDO e não inventado: sem `_cliente_de_execucao`
                # não há caminho até o modelo, e `ClienteAusente` levanta se
                # alguém tentar — nada foi gasto porque nada podia ser.
                "custo_microcents": cliente.gasto_microcents() if cliente else 0,
            },
        ) from erro

    # ITENS do pool, não lançamentos bancários. `bank_total` era a unidade de
    # uma fonte só; num CSV de issues não existe "lado bancário".
    total = len(pool.items)
    # A lacuna passa a sair do `Run`: o pool que SOBROU, contado, e não
    # inferido da soma das contagens por resolver.
    #
    # O comentário que estava aqui explicava por que a lacuna usava
    # `bank_matched_total` em vez daquela soma: ela assumiria que todo match
    # carrega exatamente um id bancário — verdade hoje, não garantida pelo
    # tipo — e, no dia em que deixasse de ser, a lacuna iria a negativo em vez
    # de crescer. Com `run.unresolved` a suposição deixa de existir: o resto é
    # contado. O defeito que ele registra continua real, e é por isso que ele
    # sobrevive aqui em vez de ser apagado.
    #
    # Todas as classes, não só REGRA: o revisor humano é classe HUMANO, e uma
    # decisão aprovada precisa fechar a lacuna do canvas em vez de continuar
    # contada como aberta. `run.unresolved` já é isso por construção — o pool
    # encolhe a cada resolução, de qualquer classe.
    resolvidos = total - len(run.unresolved.items)
    por_resolver = [
        ResolverRunJSON(
            name=d.name,
            cost_class=d.cost_class.name,
            # Os dois chaveados por IDENTIDADE do resolver — não por
            # PROVENIÊNCIA (`Resolution.produced_by`). Os dois coincidem hoje
            # (P3.2 em DECISOES.md), mas só a identidade responde "quanto este
            # resolver da cascata resolveu" por construção.
            #
            # `matches` conta RESOLUÇÕES; `rate` divide ITENS por ITENS. São
            # dois campos do `Run` de propósito: dividir a contagem de
            # resoluções pelo tamanho do pool daria metade do número na
            # conciliação, onde toda resolução casa ao menos um bancário com um
            # contábil — e o número certo num domínio de um item por resolução.
            matches=run.resolved_by_resolver.get(d.name, 0),
            rate=run.resolved_items_by_resolver.get(d.name, 0) / total if total else 0.0,
            # A mesma guarda de `metrics.evaluate`: um resolver que não gastou
            # token nenhum converte para zero em qualquer modelo, e uma cascata
            # só de regras não deve exigir tabela de preços para ler zero.
            microcents=(
                c.microcents(modelo)
                if (c := run.cost_by_resolver.get(d.name, Cost.zero())) != Cost.zero()
                else 0
            ),
        )
        for stage in definicao.stages
        for d in (r.describe() for r in stage.ordered())
    ]

    medido = None
    if gabarito is not None:
        # `evaluate` exige um `ReconcileResult`, e ele é um invólucro FINO do
        # `Run`: das seis coisas que carrega, `evaluate` lê exatamente duas —
        # `matches` e `matches_by_class`. `divergences` fica vazio de propósito
        # e isso NÃO é uma meia-verdade escondida: traduzir o resto do pool em
        # `Divergence` é trabalho do domínio, para a CLI, e `evaluate` não o
        # consulta. Adaptar `metrics.evaluate` para receber um `Run` seria mais
        # limpo e arrastaria os outros dois chamadores (CLI e grill) para
        # dentro desta fatia — troca que não vale aqui.
        m = evaluate(
            gabarito,
            ReconcileResult(
                matches=list(run.resolutions),
                divergences=[],
                proposals=list(run.proposals),
                cost_by_resolver=run.cost_by_resolver,
                matches_by_resolver=run.resolved_by_resolver,
                matches_by_class=run.resolutions_by_class,
            ),
            model=modelo,
        )
        # `fonte.seed`/`fonte.n` e não `pedido.fonte.*`: este ramo só roda para
        # a fonte que TEM gabarito, e é ela quem carrega os dois. Ler do pedido
        # daria o mesmo número por um caminho que o tipo não garante.
        medido = MedidoJSON(
            seed=fonte.seed,
            n=fonte.n,
            bank_total=m.bank_total,
            deterministic_rate=m.deterministic_rate,
        )

    return RunJSON(
        input_ref=ref,
        itens=total,
        resolvidos=resolvidos,
        por_resolver=por_resolver,
        gap=GapJSON(
            items=total - resolvidos,
            rate=(total - resolvidos) / total if total else 0.0,
        ),
        custo_microcents=run.custo_total_microcents(modelo),
        # O DESFECHO, e ele existe porque três coisas diferentes chegavam aqui
        # com a mesma cara: "o modelo não achou nada", "paramos no teto" e "a
        # API falhou". As duas últimas viram abstenção pela captura estreita de
        # `agent/conversa.py` — que é o comportamento certo para o laço, porque
        # uma queda de rede não pode derrubar um fechamento por causa de um
        # item — mas o RUN precisa dizer o que de fato aconteceu com ele.
        #
        # Os números são CONTADOS, cada um na sua origem, e nenhum é derivado
        # dos outros: `estado` sai do `Run` PERSISTIDO (o mesmo objeto que
        # `/api/runs` devolve, então os dois não podem discordar),
        # `propostas_por_tipo`/`falhas` do que o motor devolveu, e
        # `teto_atingido` da MESMA variável que corrigiu o estado. Uma subtração
        # entre eles seria o join frágil de sempre.
        estado=run.state.value,
        propostas_por_tipo=Counter(p.tipo for p in run.proposals),
        falhas=sum(
            1 for p in run.proposals if any(e.kind is TraceKind.ERRO for e in p.trace)
        ),
        teto_atingido=parou_no_teto,
        contra_gabarito=medido,
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


def _abrir_fila(workflow_id: str, ref: str) -> tuple[Fila, str]:
    """A fila de decisões humanas de `(workflow, conjunto)`.

    Recebia `(seed, n, taxa)` e chamava `dataset_id`. Passou a receber o `ref`
    da FONTE porque uma fonte de arquivo não tem seed, n nem taxa — e porque o
    `ref` sempre foi a identidade do conjunto. Para a sintética a chave é
    byte a byte a mesma de antes (ver `dataset_de_ref`), então nenhuma fila já
    gravada em `data/fila/**` deixa de ser encontrada.
    """
    dataset = dataset_de_ref(ref)
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
    # `!=` e não `is not`: funcionava por identidade porque os dois lados eram
    # membros do MESMO enum, e enum é singleton. Com `tipo` sendo `str` — que é
    # o que `Proposal.tipo` e `Decision.tipo` declaram —, `is` passa a depender
    # de interning do CPython, e o sintoma seria "o humano discordou do agente"
    # aparecendo para decisões idênticas. Falha silenciosa, na tela, sobre
    # concordância.
    divergiu = decisao is not None and (
        decisao.tipo != proposta.tipo or decisao.conciliar_com != ids
    )
    return ItemFilaJSON(
        divergence_id=proposta.item_id,
        tipo=proposta.tipo,
        confianca=proposta.confianca.value,
        explicacao=proposta.explicacao,
        evidencia=list(proposta.evidencia),
        acao_sugerida=proposta.acao_sugerida,
        conciliar_com=sorted(ids),
        lancamentos=lancamentos,
        decidido=decisao is not None,
        veredito=decisao.veredito.value if decisao else None,
        tipo_decidido=decisao.tipo if decisao else None,
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
    if workflow_id not in registry(_RAIZ_RECEITAS, _RAIZ_COMPOSICOES):
        raise HTTPException(status_code=404, detail=f"workflow desconhecido: {workflow_id}")
    # A chave da fila sai do `ref` da fonte, e a fonte desta rota é a
    # sintética — as duas telas precisam concordar sobre qual arquivo abrir, e
    # montar a chave aqui à mão seria o join frágil de sempre.
    fila, dataset = _abrir_fila(
        workflow_id,
        SyntheticSource(seed=seed, n=n, taxa_divergencia=taxa_divergencia).ref,
    )
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
    if workflow_id not in registry(_RAIZ_RECEITAS, _RAIZ_COMPOSICOES):
        raise HTTPException(status_code=404, detail=f"workflow desconhecido: {workflow_id}")
    fila, _ = _abrir_fila(
        workflow_id,
        SyntheticSource(seed=seed, n=n, taxa_divergencia=taxa_divergencia).ref,
    )

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
