"""O registro de workflows, e o fim da injeção por nome de parâmetro.

Este arquivo substitui `tests/grill/test_fabrica.py`, que existia para travar o
mecanismo frágil em vez da garantia:

    assert "fila" in inspect.signature(fabrica_de(_r())).parameters

Aquele teste protegia um NOME. Ele era honesto sobre isso — o comentário dizia
"renomear para `q` deixa tudo verde e faz o workflow gerado servir fila vazia em
silêncio" —, mas um teste que trava um nome de parâmetro é a confissão de que o
contrato é um nome de parâmetro.

Com `WorkflowFactory` tipada, renomear o parâmetro deixou de ter consequência
NENHUMA: o contrato passou a ser a assinatura. Não há mais nada para travar, e
é por isso que o teste some em vez de ser adaptado.
"""

from datetime import UTC, datetime

import pytest

from orchestrator.grill.receita import Receita, ResolverReceita
from orchestrator.grill.registro import gravar_receita
from orchestrator.kernel.definition import WorkflowDefinition
from orchestrator.review.fila import Fila
from orchestrator.workflows import (
    ID_EMBUTIDO,
    WorkflowContext,
    construir_definicao,
    descrever,
    registry,
)


def _receita(rid: str = "acme") -> Receita:
    return Receita(
        id=rid,
        nome="Acme",
        justificativa="j",
        gerado_em=datetime(2026, 9, 15, tzinfo=UTC),
        resolvers=(ResolverReceita("L1", {}), ResolverReceita("revisor", {})),
    )


def test_o_embutido_esta_sempre_no_registro():
    assert ID_EMBUTIDO in registry()


def test_a_fila_chega_ao_revisor_pelo_contexto():
    """O que o teste antigo queria provar, provado sem olhar nome nenhum."""
    fila = Fila.vazia()

    definicao = construir_definicao(
        registry()[ID_EMBUTIDO], WorkflowContext(fila=fila)
    )

    revisor = next(r for r in definicao.stages[0].ordered() if r.name == "revisor")
    assert revisor.fila is fila


def test_workflow_gerado_tambem_recebe_a_fila(tmp_path):
    gravar_receita(_receita(), raiz=tmp_path)
    fila = Fila.vazia()

    definicao = construir_definicao(
        registry(tmp_path)["acme"], WorkflowContext(fila=fila)
    )

    revisor = next(r for r in definicao.stages[0].ordered() if r.name == "revisor")
    assert revisor.fila is fila


def test_toda_fabrica_tem_a_MESMA_assinatura(tmp_path):
    """A propriedade que substitui a inspeção.

    Antes, `_construir_definicao` olhava `inspect.signature(fabrica)` e
    decidia entre `fabrica(fila)`, `fabrica()` e `TypeError`. Três caminhos,
    escolhidos por reflexão sobre um nome.

    Agora há um caminho, porque toda fábrica aceita exatamente um contexto. Este
    teste chama TODAS do mesmo jeito — se alguma precisasse de tratamento
    especial, ela falharia aqui em vez de num endpoint.
    """
    gravar_receita(_receita(), raiz=tmp_path)
    ctx = WorkflowContext.vazio()

    for fabrica in registry(tmp_path).values():
        assert isinstance(construir_definicao(fabrica, ctx), WorkflowDefinition)


def test_o_embutido_nunca_e_sobrescrito_por_disco(tmp_path):
    """`conciliacao` é id reservado no registro, e esta ordem é a segunda
    tranca."""
    gravar_receita(_receita(rid="conciliacao-b"), raiz=tmp_path)
    (tmp_path / "workflows" / f"{ID_EMBUTIDO}.json").write_text(
        (tmp_path / "workflows" / "conciliacao-b.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    definicao = construir_definicao(
        registry(tmp_path)[ID_EMBUTIDO], WorkflowContext.vazio()
    )

    assert definicao.name == "Conciliação bancária"


def test_receita_que_nao_constroi_nao_derruba_a_listagem(tmp_path, capsys):
    """Um arquivo ruim não pode derrubar a listagem inteira, mas também não
    pode sumir em silêncio — as duas metades da mesma frase.

    Sem isto, UMA receita que parseia e não constrói devolve 500 em
    `GET /api/workflows` e mata o seletor do canvas para TODOS os workflows.
    """
    gravar_receita(_receita(), raiz=tmp_path)
    ruim = _receita(rid="quebrada")
    gravar_receita(ruim, raiz=tmp_path)
    caminho = tmp_path / "workflows" / "quebrada.json"
    caminho.write_text(
        caminho.read_text(encoding="utf-8").replace('"L1"', '"resolver-que-nao-existe"'),
        encoding="utf-8",
    )

    ids = [wid for wid, _ in descrever(tmp_path)]

    assert "acme" in ids and ID_EMBUTIDO in ids
    assert "quebrada" not in ids
    assert "quebrada" in capsys.readouterr().err


def test_contexto_vazio_nao_aplica_decisao_nenhuma():
    """`GET /api/workflows` usa o contexto vazio: aquela rota só descreve a
    FORMA da cascata, que não muda com o conteúdo da fila."""
    revisor = next(
        r
        for r in construir_definicao(
            registry()[ID_EMBUTIDO], WorkflowContext.vazio()
        ).stages[0].ordered()
        if r.name == "revisor"
    )

    assert revisor.fila.pendentes() == []


@pytest.mark.parametrize("nome_do_parametro", ["fila", "q", "seja_la_o_que_for"])
def test_renomear_o_parametro_da_fabrica_deixou_de_ter_consequencia(nome_do_parametro):
    """O defeito que este PR fechou, verificado como não-defeito.

    O teste antigo travava o NOME `fila` porque renomeá-lo faria todo workflow
    gerado servir fila vazia em silêncio. Com a assinatura tipada, o nome do
    parâmetro é escolha de quem escreve a fábrica e não significa nada para
    quem a chama.
    """
    fila = Fila.vazia()
    corpo = (
        f"def fabrica({nome_do_parametro}):\n"
        f"    return construir_definicao_embutida({nome_do_parametro})\n"
    )
    espaco = {
        "construir_definicao_embutida": lambda ctx: construir_definicao(
            registry()[ID_EMBUTIDO], ctx
        )
    }
    exec(corpo, espaco)  # noqa: S102

    definicao = espaco["fabrica"](WorkflowContext(fila=fila))

    revisor = next(r for r in definicao.stages[0].ordered() if r.name == "revisor")
    assert revisor.fila is fila
