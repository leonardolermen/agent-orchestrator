"""O registro de workflows: de um id para uma definição executável.

Este módulo existe para matar uma coisa específica —
`api/app.py::_construir_definicao`, que decidia repassar a fila de revisão
inspecionando o **nome** do parâmetro da fábrica com `inspect.signature`. O
docstring de lá era honesto sobre o preço:

> "O nome `fila` é o único contrato entre este módulo e `default_definition`
> (e `fabrica_de`) — não há import de tipo nem checagem estrutural que os
> amarre. Renomear isto para `q` deixaria a suíte inteira verde e faria todo
> workflow gerado servir fila vazia em silêncio."

Injeção de dependência por reflexão sobre nome de parâmetro é um defeito
silencioso esperando um rename — a classe de falha que este repositório já
corrigiu seis vezes em outros lugares.

**A correção não é inspecionar melhor: é não precisar inspecionar.** Toda
fábrica passa a ter a MESMA assinatura, `(WorkflowContext) -> WorkflowDefinition`,
e quem não precisa do contexto simplesmente o ignora. A uniformidade é a mesma
disciplina que `agent.declarado.RegraDisponivel.construir` aplica no catálogo, e
pelo mesmo motivo declarado lá: assinatura variável exigiria introspecção para
saber o que passar — e é exatamente esse padrão que já nos deu um defeito
silencioso no `_construir_definicao` da API.

**Por que `WorkflowContext` é um dataclass tipado e não um `dict[str, Any]`.**
Um saco de serviços com chave `"fila"` trocaria um contrato fraco (nome de
parâmetro) por outro igualmente fraco (chave de dicionário), e o defeito
original voltaria com outra roupa. Ele ganha um campo quando aparece uma
necessidade — `cliente` entrou quando executar com agente pela web passou a
existir — e cada um deles some do `TypeError` para dentro do type checker.
"""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from orchestrator.agent.llm import LLMClient
from orchestrator.authoring.composicao import Composicao, construir_composicao
from orchestrator.authoring.composicao import listar as listar_composicoes
from orchestrator.domains.reconciliation import default_definition
from orchestrator.grill.receita import Receita, construir
from orchestrator.grill.registro import listar_receitas
from orchestrator.kernel.definition import WorkflowDefinition
from orchestrator.review.fila import Fila

ID_EMBUTIDO = "conciliacao"


@dataclass(frozen=True)
class WorkflowContext:
    """O ambiente que uma fábrica de workflow recebe.

    `fila` é a fila de decisões humanas, e ela entra na CONSTRUÇÃO e não na
    execução porque o revisor precisa dela para existir como resolver — ver
    `conciliacao.default_definition`.
    """

    fila: Fila
    # O cliente que a EXECUÇÃO usa. `None` mantém o comportamento de todos os
    # chamadores de hoje: a fábrica cai no `ClienteAusente`, que é a tranca.
    # Desarmá-la continua sendo ato explícito de quem executa — o que muda é
    # que agora existe por onde fazê-lo sem inventar um segundo caminho.
    #
    # Uma cascata com agente precisa de um `LLMClient` de verdade para ser
    # CONSTRUÍDA (o cliente entra no `Agent`, não numa chamada posterior), e
    # `construir_definicao(fabrica, ctx)` não tinha por onde passá-lo: a
    # definição saía montada com a tranca e o agente levantava ao primeiro
    # turno.
    cliente: "LLMClient | None" = None

    @staticmethod
    def vazio() -> "WorkflowContext":
        """Contexto sem decisão nenhuma, e sem cliente.

        É o que `GET /api/workflows` usa: aquela rota só descreve a FORMA da
        cascata, que não muda com o conteúdo da fila — nem com quem pagaria a
        conta se ela rodasse.
        """
        return WorkflowContext(fila=Fila.vazia())


class WorkflowFactory(Protocol):
    """Um id de workflow vira uma definição executável por aqui.

    Assinatura ÚNICA, e é o ponto inteiro do módulo. Uma fábrica que não
    precisa do contexto ignora o argumento; nenhuma precisa ser inspecionada.
    """

    def __call__(self, ctx: WorkflowContext) -> WorkflowDefinition: ...


def _de_receita(receita: Receita) -> WorkflowFactory:
    """Fábrica para um workflow gerado pelo grill.

    `ctx.cliente` é repassado VERBATIM, incluindo `None`. Não há `or` e não há
    default escrito aqui: quem decide o que `None` significa é `construir`, que
    cai no `ClienteAusente` — a tranca. Um default nesta camada seria uma
    segunda resposta para a mesma pergunta, e a que divergisse seria a que
    ninguém testa.

    `context` (o `ToolContext` dos dados) continua no default inerte: ele é
    insumo de FERRAMENTA, não de cliente, e ligá-lo é outra fatia.
    """

    def fabrica(ctx: WorkflowContext) -> WorkflowDefinition:
        return construir(receita, fila=ctx.fila, cliente=ctx.cliente)

    return fabrica


def _de_composicao(composicao: Composicao) -> WorkflowFactory:
    """Fábrica para uma cascata composta no canvas. O espelho de `_de_receita`.

    `ctx.cliente` repassado VERBATIM, inclusive `None`: quem decide o que
    `None` significa é `construir_composicao`, que cai em `ClienteDeValidacao`
    — a tranca. O docstring de `construir_composicao` previu esta linha: "para
    que o dia em que uma composição ganhar caminho de execução seja um
    `fila=ctx.fila` a mais, e não uma segunda via de configuração".
    """

    def fabrica(ctx: WorkflowContext) -> WorkflowDefinition:
        return construir_composicao(composicao, fila=ctx.fila, cliente=ctx.cliente)

    return fabrica


def registry(
    raiz: Path | None = None, raiz_composicoes: Path | None = None
) -> dict[str, WorkflowFactory]:
    """Os workflows disponíveis: o embutido, os gerados em disco, os compostos.

    Saiu de `api/app.py`: quais workflows existem não é assunto da camada HTTP.
    A CLI e o benchmark precisam da mesma resposta, e duas listas paralelas
    seriam o join frágil que P3.2 já custou uma correção.

    A ORDEM é a tranca: embutida → receitas → composições. `conciliacao` é id
    reservado; disco nunca sobrescreve a embutida; uma composição nunca
    sobrescreve uma receita. Composições ficam em raiz própria porque são
    outro formato com outra serialização — um diretório só obrigaria o leitor
    a farejar o formato pelo conteúdo.
    """
    fabricas: dict[str, WorkflowFactory] = {
        ID_EMBUTIDO: lambda ctx: default_definition(ctx.fila)
    }
    for receita in listar_receitas(raiz):
        # A embutida nunca é sobrescrita por disco: `conciliacao` é id
        # reservado no registro, e esta ordem é a segunda tranca.
        if receita.id in fabricas:
            continue
        fabricas[receita.id] = _de_receita(receita)
    for composicao in listar_composicoes(raiz_composicoes):
        if composicao.id in fabricas:
            # Não some em silêncio, não derruba a listagem: o mesmo isolamento
            # que `descrever()` dá a uma receita que não constrói.
            print(
                f"aviso: composição {composicao.id!r} ignorada — já existe um "
                f"workflow com esse id (embutido ou receita)",
                file=sys.stderr,
            )
            continue
        fabricas[composicao.id] = _de_composicao(composicao)
    return fabricas


def construir_definicao(
    fabrica: WorkflowFactory, ctx: WorkflowContext
) -> WorkflowDefinition:
    """Uma chamada. Sem inspeção, sem caso especial, sem `TypeError` possível.

    Fica como função (em vez de `fabrica(ctx)` escrito em cada chamador) porque
    é aqui que entram, depois, as coisas que valem para TODA construção —
    `PolicyEngine` (PR #10) e versionamento de definição.
    """
    return fabrica(ctx)


def descrever(
    raiz: Path | None = None, raiz_composicoes: Path | None = None
) -> list[tuple[str, WorkflowDefinition]]:
    """Todos os workflows construtíveis, com a receita ruim isolada.

    Mesmo isolamento que `listar_receitas` já aplica ao PARSE, agora também na
    CONSTRUÇÃO — as duas metades da mesma frase: um arquivo ruim não pode
    derrubar a listagem inteira, mas também não pode sumir em silêncio.

    Sem isto, UMA receita que parseia e não constrói (um resolver que saiu do
    catálogo, um parâmetro renomeado — o catálogo é feito para crescer) devolve
    500 em `GET /api/workflows` e mata o seletor do canvas para TODOS os
    workflows, enquanto cada um deles, individualmente, continua respondendo
    200.
    """
    achados = []
    for workflow_id, fabrica in registry(raiz, raiz_composicoes).items():
        try:
            achados.append(
                (workflow_id, construir_definicao(fabrica, WorkflowContext.vazio()))
            )
        except (ValueError, TypeError) as erro:
            print(
                f"workflow ignorado, receita não construível: {workflow_id} ({erro})",
                file=sys.stderr,
            )
    return achados
