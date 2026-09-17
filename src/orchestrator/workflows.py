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
original voltaria com outra roupa. Ele tem um campo hoje porque há um domínio;
quando houver mais, ganha campos — e cada um deles some do `TypeError` para
dentro do type checker.
"""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from orchestrator.conciliacao import default_definition
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

    @staticmethod
    def vazio() -> "WorkflowContext":
        """Contexto sem decisão nenhuma.

        É o que `GET /api/workflows` usa: aquela rota só descreve a FORMA da
        cascata, que não muda com o conteúdo da fila.
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

    Cliente e contexto ficam nos DEFAULTS INERTES de `construir` de propósito:
    como `/runs` responde 409 para qualquer cascata com classe AGENTE, nenhum
    workflow com agente chega a executar por um endpoint — então não existe
    caminho em que a API precise de um agente funcional, e portanto não existe
    código aqui que o construa.
    """

    def fabrica(ctx: WorkflowContext) -> WorkflowDefinition:
        return construir(receita, fila=ctx.fila)

    return fabrica


def registry(raiz: Path | None = None) -> dict[str, WorkflowFactory]:
    """Os workflows disponíveis: o embutido mais os gerados em disco.

    Saiu de `api/app.py`: quais workflows existem não é assunto da camada HTTP.
    A CLI e o benchmark precisam da mesma resposta, e duas listas paralelas
    seriam o join frágil que P3.2 já custou uma correção.
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


def descrever(raiz: Path | None = None) -> list[tuple[str, WorkflowDefinition]]:
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
    for workflow_id, fabrica in registry(raiz).items():
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
