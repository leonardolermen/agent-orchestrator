"""O app HTTP do canvas.

Regra que governa este módulo: NENHUM endpoint daqui pode gastar dinheiro.
Não é uma flag a desligar — não existe caminho de código deste arquivo até o
modelo. Ver o §5 do spec desta fatia e o teste em `tests/api/test_execucao.py`.
"""

import inspect
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from orchestrator.api.schemas import (
    DecisaoRequest,
    FilaJSON,
    GapJSON,
    ItemFilaJSON,
    LancamentoJSON,
    ResolverRunJSON,
    RunJSON,
    RunRequest,
    WorkflowJSON,
    WorkflowResumoJSON,
    workflow_json,
)
from orchestrator.cli import build_benchmark
from orchestrator.grill.receita import Receita, construir
from orchestrator.grill.registro import listar_receitas
from orchestrator.matching.engine import reconcile
from orchestrator.metrics import evaluate
from orchestrator.review.decision import Decision, Veredito, ids_de_conciliar_com
from orchestrator.review.fila import Fila, caminho_da_fila, dataset_id
from orchestrator.taxonomy import DivergenceType
from orchestrator.workflow.cost_class import CostClass
from orchestrator.workflow.definition import WorkflowDefinition, default_definition

app = FastAPI(title="Agent Orchestrator — canvas")

# Raiz das receitas em disco. Atributo de módulo para o teste trocar por
# tmp_path sem ler o `data/` real do desenvolvedor.
_RAIZ_RECEITAS: Path | None = None


def fabrica_de(receita: Receita):
    """Uma fábrica de workflow a partir de uma receita.

    O parâmetro chama-se `fila` PELO NOME, de propósito: `_construir_definicao`
    decide repassar a fila com `inspect.signature`, e não há import nem type
    check amarrando os dois lados. Renomear isto para `q` deixaria a suíte
    inteira verde e faria todo workflow gerado servir fila vazia em silêncio.
    Ver `tests/grill/test_fabrica.py`.

    Cliente e contexto ficam nos DEFAULTS INERTES de propósito: como `/runs`
    responde 409 para qualquer cascata com classe AGENTE (ver `_executar_memoizado`),
    nenhum workflow com agente chega a executar por um endpoint — então não
    existe caminho em que a API precise de um agente funcional, e portanto não
    existe código aqui que o construa.
    """

    def fabrica(fila: Fila) -> WorkflowDefinition:
        return construir(receita, fila=fila)

    return fabrica


def _fabricas() -> dict[str, object]:
    fabricas: dict[str, object] = {"conciliacao": default_definition}
    for receita in listar_receitas(_RAIZ_RECEITAS):
        # A embutida nunca é sobrescrita por disco: `conciliacao` é id
        # reservado no registro, e esta ordem é a segunda tranca.
        if receita.id in fabricas:
            continue
        fabricas[receita.id] = fabrica_de(receita)
    return fabricas


@app.get("/api/workflows", response_model=list[WorkflowResumoJSON])
def listar_workflows() -> list[WorkflowResumoJSON]:
    resumos = []
    por_id = {r.id: r for r in listar_receitas(_RAIZ_RECEITAS)}
    for workflow_id, fabrica in _fabricas().items():
        definicao = _construir_definicao(fabrica, Fila.vazia())
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


@app.get("/api/workflows/{workflow_id}", response_model=WorkflowJSON)
def obter_workflow(workflow_id: str) -> WorkflowJSON:
    fabrica = _fabricas().get(workflow_id)
    if fabrica is None:
        raise HTTPException(status_code=404, detail=f"workflow desconhecido: {workflow_id}")
    # Mesma construção de `_executar_memoizado`, nunca uma segunda via direto
    # por `fabrica()`: `definition.py` declara que não existe "definição
    # servida" separada da "definição executada", e duas chamadas para o
    # mesmo objeto são exatamente o jeito de esse invariante parar de ser
    # estrutural. A fila vazia é inofensiva aqui — esta rota só descreve a
    # FORMA da cascata, que não muda com o conteúdo da fila.
    return workflow_json(_construir_definicao(fabrica, Fila.vazia()))


@app.post("/api/workflows/{workflow_id}/runs", response_model=RunJSON)
def executar(workflow_id: str, pedido: RunRequest) -> RunJSON:
    fabrica = _fabricas().get(workflow_id)
    if fabrica is None:
        # 404 antes do cache, de propósito: um id desconhecido nunca deve
        # entrar em `_executar_memoizado`, nem para ficar registrado como
        # "chave inválida" numa memoização que não sabe o que fazer com isso.
        raise HTTPException(status_code=404, detail=f"workflow desconhecido: {workflow_id}")
    return _executar_memoizado(workflow_id, pedido.seed, pedido.n, pedido.taxa_divergencia)


def _construir_definicao(fabrica, fila: Fila) -> WorkflowDefinition:
    """Repassa a fila só para fábricas que a declaram no próprio parâmetro.

    `_fabricas()["conciliacao"]` é `default_definition(fila=...)`, que lê a
    fila para aplicar decisões humanas. Testes registram fábricas de zero
    argumentos direto (ver `test_execucao.py`); chamar essas com `fila`
    estouraria `TypeError` sem esta checagem de assinatura.

    O nome `fila` é o único contrato entre este módulo e `default_definition`
    (e `fabrica_de`) — não há import de tipo nem checagem estrutural que os
    amarre. Uma fábrica cuja assinatura não seja "aceita `fila`" nem "não
    aceita nada" é um caso não previsto: levanta em vez de cair
    silenciosamente para `fabrica()`, que aplicaria o argumento errado a um
    parâmetro qualquer ou simplesmente ignoraria a fila sem avisar ninguém.
    """
    parametros = inspect.signature(fabrica).parameters
    if "fila" in parametros:
        return fabrica(fila)
    if not parametros:
        return fabrica()
    raise TypeError(
        f"fábrica de workflow com assinatura não reconhecida: esperado um "
        f"parâmetro `fila` ou nenhum parâmetro, recebido {list(parametros)}"
    )


@lru_cache(maxsize=64)
def _executar_memoizado(workflow_id: str, seed: int, n: int, taxa: float) -> RunJSON:
    """Cacheável por construção — mas não mais pura só dos três parâmetros.

    A definição servida aqui não tem agente: a execução não faz rede e não
    gasta em tokens. É isso que torna seguro um endpoint que qualquer F5
    dispara. A chave do cache inclui `workflow_id` além dos três parâmetros do
    benchmark — dois workflows diferentes com os mesmos parâmetros não podem
    colidir na mesma entrada.

    Ela agora também lê a fila em disco (via `_RAIZ_FILA`) para que o revisor
    humano aplique as decisões já tomadas. Isso quebra a pureza formal da
    função nos três parâmetros — por isso o POST de decisão precisa chamar
    `cache_clear()` depois de gravar, ou uma aprovação recente ficaria
    invisível para quem recarrega o canvas.
    """
    dataset = build_benchmark(seed=seed, n=n, taxa_divergencia=taxa)
    fila, _ = _abrir_fila(workflow_id, seed, n, taxa)
    definicao = _construir_definicao(_fabricas()[workflow_id], fila)
    resultado = reconcile(dataset.bank, dataset.ledger, definition=definicao)
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
    do_item = _ids_da_divergencia(proposta.divergence_id) | ids
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
        divergence_id=proposta.divergence_id,
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
    if workflow_id not in _fabricas():
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
    if workflow_id not in _fabricas():
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
    # A execução memoizada deixou de ser função só de (workflow, seed, n,
    # taxa): ela agora depende do conteúdo da fila. Sem limpar, aprovar uma
    # proposta e recarregar o canvas mostraria o estado anterior, e o revisor
    # concluiria que a aprovação não funcionou.
    _executar_memoizado.cache_clear()

    return _item(proposta, fila.decisao(divergence_id), por_id)


# De `src/orchestrator/api/app.py`: parents[0] é `api`, [1] é `orchestrator`,
# [2] é `src`, [3] é a raiz do repositório — é lá que mora `web/`.
_WEB = Path(__file__).resolve().parents[3] / "web"

# Este `mount("/")` PRECISA ser a última linha do arquivo. `StaticFiles` com
# `html=True` responde por qualquer caminho não reconhecido (inclusive `/`,
# servindo `index.html`), então se ele viesse antes das rotas `/api/...`
# elas nunca seriam alcançadas — o mount as engoliria todas.
app.mount("/", StaticFiles(directory=_WEB, html=True), name="web")
