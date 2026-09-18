"""Uma cascata composta a partir do catálogo, com agente declarado inline.

**Por que não estender a `Receita` do grill.** Ela é `resolvers: tuple[
ResolverReceita(nome, parametros)]` — uma lista de NOMES do `CATALOGO`, que é o
cardápio da conciliação. Isso funciona enquanto tudo que se compõe já existe
pronto. Um agente declarado não existe pronto: ele é criado na composição, com
prompt, vocabulário e ferramentas próprios, e não tem nome no catálogo de
ninguém.

Tentar encaixá-lo em `ResolverReceita` daria um `parametros: dict[str, int]`
carregando um prompt — e o `int` no tipo é o aviso de que não cabe.

**A `Receita` continua existindo e não é depreciada.** O entrevistador do grill
a produz e os testes dela valem. `Composicao` é o formato geral; `Receita` é o
caso particular em que todos os blocos já existem por nome.

**O que uma composição garante, e a garantia é estrutural:**

1. **A ordem não é do autor.** `Stage.ordered()` ordena por `CostClass`, e não
   existe campo de ordem aqui. É a mesma defesa contra decoração que o canvas
   tem, agora no formato persistido.
2. **Valida construindo.** Se `construir_composicao` retorna, a cascata roda.

**A terceira garantia era "um domínio só", e hoje ela NÃO TEM DONO aqui.
Dito em voz alta porque a meia-verdade é pior que a lacuna.**

Ela dizia: blocos cujos `WorkItem.kind` não conversam produzem uma cascata vazia
de sentido, porque o segundo roda sobre um pool que o primeiro nem enxerga. A
guarda antiga a fazia comparando o `kind` do agente com os `kinds` do domínio
declarado na composição — e ela PRECISAVA sair. Com a tela sem seletor, toda
composição chegava com o domínio default, e a checagem passou a recusar qualquer
agente cujo kind não fosse `"lancamento"`: guarda certa aplicada ao pedido
errado, recusando cascata válida.

O lugar certo é o grafo — `Stage.consome`/`Stage.produz` declara a fiação POR
DEGRAU, e o que se valida é o grafo que VAI RODAR, não uma partição de catálogo.
Só que, para uma composição construída AQUI, essa guarda está **inerte**, por
dois motivos que se somam:

1. `construir_composicao` devolve UM stage com `consome`/`produz` nos defaults,
   e `WorkflowDefinition.__post_init__` desliga a checagem de beco sem saída no
   grafo inteiro assim que um único stage usa o default — o custo está dito em
   voz alta em `kernel/definition.py`, e vale aqui;
2. mesmo se rodasse, não acharia nada: esta função não POPULA `consome`/`produz`
   a partir dos blocos, e a checagem de lá procura `produz` órfão — ela nunca
   compara o `kind` de um agente com coisa nenhuma.

Logo: um agente com `kind` digitado errado é aceito, e em execução simplesmente
nunca pega item nenhum. Religar isso precisa das DUAS pontas — o X7/X8 (ensinar
`AgenteDeclarado` a declarar o que PRODUZ) e a fiação aqui, derivando
`consome`/`produz` dos blocos. Enquanto as duas não existirem, quem escreve um
agente na tela é quem garante o `kind`.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from orchestrator.agent.declarado import (
    AgenteDeclarado,
    ClienteDeValidacao,
    construir_agente,
)
from orchestrator.agent.llm import LLMClient
from orchestrator.domains.registro import CATALOGO
from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.definition import Stage, WorkflowDefinition, consome_de
from orchestrator.kernel.resolver import Resolver
from orchestrator.review.fila import Fila
from orchestrator.review.revisor import RevisorHumano

_RAIZ_PADRAO = Path("data") / "composicoes"


@dataclass(frozen=True)
class BlocoRegra:
    """Uma regra do catálogo, com os parâmetros ajustados."""

    nome: str
    parametros: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class BlocoAgente:
    """Um agente declarado INLINE. É o que a `Receita` não sabia carregar."""

    declaracao: AgenteDeclarado


Bloco = BlocoRegra | BlocoAgente


@dataclass(frozen=True)
class Composicao:
    id: str
    nome: str
    blocos: tuple[Bloco, ...]
    gerado_em: datetime
    justificativa: str = ""
    version: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.blocos:
            raise ValueError("a cascata precisa de pelo menos um bloco")
        if self.gerado_em.tzinfo is None:
            raise ValueError("`gerado_em` precisa de fuso (use UTC)")
        # Versão derivada do CONTEÚDO, como `WorkflowDefinition.version` e
        # `EvalDataset.version`. Dois resultados de benchmark só são comparáveis
        # se mediram a mesma cascata, e sem derivação nada impede duas
        # composições diferentes alegarem a mesma versão.
        digest = hashlib.sha256(
            json.dumps(_blocos_para_json(self.blocos), sort_keys=True, ensure_ascii=False)
            .encode("utf-8")
        ).hexdigest()
        object.__setattr__(self, "version", digest[:12])

    @property
    def nomes(self) -> tuple[str, ...]:
        return tuple(
            b.nome if isinstance(b, BlocoRegra) else b.declaracao.name
            for b in self.blocos
        )


def construir_composicao(
    c: Composicao,
    *,
    fila: Fila | None = None,
    cliente: LLMClient | None = None,
    contexto: Any = None,
) -> WorkflowDefinition:
    """Valida construindo. Se retorna, a cascata roda.

    **`fila` é a MESMA costura de `grill.receita.construir`, de propósito.**
    Um bloco de classe `HUMANO` precisa da fila de decisões já tomadas para
    existir como resolver, e ela não cabe em `RegraDisponivel.construir`, cuja
    assinatura é uniforme `(parametros) -> Resolver`. Lá a fila entra por
    palavra-chave e `workflows._de_receita` a liga ao `WorkflowContext.fila`;
    aqui a palavra-chave é a mesma, para que o dia em que uma composição ganhar
    caminho de execução seja um `fila=ctx.fila` a mais, e não uma segunda via
    de configuração inventada ao lado da primeira.

    **O default `Fila.vazia()` vale SÓ para validar, e é por isso que está
    dito aqui em voz alta.** `domains.registro._revisor_precisa_da_fila` existe
    exatamente para impedir que uma fila vazia entre em silêncio: um revisor
    sobre fila vazia CONSTRÓI, a cascata fica desenhável, e nenhuma decisão
    aprovada chega à execução — sem erro nenhum avisando. O default aqui é
    seguro pelo mesmo motivo que `ClienteDeValidacao` é: a chamada default não
    EXECUTA nada (`/api/composicoes` só compõe e grava, e composição não entra
    no `registry()` dos workflows — ver `listar_composicoes`). Quem for
    executar passa a fila de verdade, de propósito, e isso aparece no diff.

    **O cliente default é a TRANCA, não um modelo.** `ClienteDeValidacao`
    constrói o agente e recusa falar com modelo. É a mesma escolha do
    `ClienteAusente` em `grill.receita.construir`, e pelo mesmo motivo: a
    chamada mais frequente é "só quero validar", e ela não pode exigir que
    alguém lembre de desarmar a execução. Quem vai EXECUTAR passa um cliente de
    verdade, de propósito, e isso aparece no diff.

    Mesma disciplina de `grill.receita.construir`, e as mensagens são escritas
    para serem LIDAS — o arquiteto (§9 do spec da plataforma) devolve o erro ao
    modelo para ele se corrigir, e a pessoa na tela merece o mesmo texto.

    `contexto` é o que as ferramentas precisam para EXECUTAR — `ToolContext` nas
    de conciliação, e nada nas que não leem dados. Ele é ligado ao registro
    aqui, na construção, e não fica guardado no catálogo (ver
    `ToolRegistry.ligado`).
    """
    por_nome = {r.nome: r for r in CATALOGO.regras}
    # Sem contexto, o registro do catálogo passa INTACTO — e catálogo recusa
    # executar. É o que faz "compor" e "executar" serem coisas diferentes:
    # `com_contexto(None)` ligaria o registro a nada e as ferramentas
    # estourariam em `None.bank` na primeira chamada, o que é pior que a recusa
    # clara de um registro não ligado.
    ferramentas = (
        CATALOGO.ferramentas
        if contexto is None
        else CATALOGO.ferramentas.com_contexto(contexto)
    )
    # `is None`, não `or` — a MESMA disciplina de `grill.receita.construir`, que
    # a documenta, e que esta linha contrariava. Não é teórico: o cliente que
    # `api/app.py` passa hoje é um `ClienteComTeto`, e um `or` aqui trocaria por
    # `ClienteDeValidacao` qualquer cliente que viesse a ser falsy — trocando um
    # teto de verdade por um sentinela que recusa falar, o que a pessoa leria
    # como "o agente não fez nada".
    if cliente is None:
        cliente = ClienteDeValidacao()
    # `is None`, não `or`: mesma disciplina de `grill.receita.construir`. `Fila`
    # não define `__bool__` nem `__len__` hoje, mas no dia em que definir um
    # `or` trocaria silenciosamente uma fila vazia EXPLÍCITA pelo default.
    if fila is None:
        fila = Fila.vazia()

    vistos: set[str] = set()
    resolvers: list[Resolver] = []

    for bloco in c.blocos:
        nome = bloco.nome if isinstance(bloco, BlocoRegra) else bloco.declaracao.name
        if nome in vistos:
            raise ValueError(
                f"bloco repetido na cascata: {nome!r}. o segundo rodaria sobre "
                f"o pool que o primeiro já esvaziou e resolveria zero"
            )
        vistos.add(nome)

        if isinstance(bloco, BlocoRegra):
            regra = por_nome.get(bloco.nome)
            if regra is None:
                raise ValueError(
                    f"bloco desconhecido no catálogo: {bloco.nome!r}. "
                    f"disponíveis: {sorted(por_nome)}"
                )
            conhecidos = {p.nome for p in regra.parametros}
            desconhecidos = sorted(set(bloco.parametros) - conhecidos)
            if desconhecidos:
                raise ValueError(
                    f"parâmetro desconhecido para {bloco.nome!r}: "
                    f"{desconhecidos}. aceitos: {sorted(conhecidos)}"
                )
            if regra.cost_class is CostClass.HUMANO:
                # A CLASSE, não a grafia do nome — mesmo desvio que
                # `grill.receita.construir` faz, e pelo mesmo motivo: um bloco
                # HUMANO depende da FILA, que não cabe na assinatura uniforme
                # `(parametros) -> Resolver`. Sem este ramo, `revisor` estava
                # na paleta do canvas e era o único bloco que "Compor e
                # validar" não conseguia compor: `regra.construir({})` caía em
                # `_revisor_precisa_da_fila` e devolvia 422 com um texto
                # escrito para quem implementa. O degrau humano é justamente o
                # que FECHA a cascata — a razão declarada de o `revisor` ter
                # sido carregado para o catálogo plano —, então a composição
                # ficaria sem o único degrau que a fatia existe para publicar.
                resolvers.append(RevisorHumano(fila=fila))
            else:
                resolvers.append(regra.construir(dict(bloco.parametros)))
        else:
            # Sem checagem de `kind`: a antiga comparava com os `kinds` do
            # domínio e recusava cascata válida depois que a tela perdeu o
            # seletor. O lugar certo é o grafo, e agora o grafo desta
            # composição não está mais inerte: `consome` abaixo é derivado dos
            # blocos, então um `kind` errado deixa de casar item na execução
            # em vez de passar em silêncio.
            resolvers.append(construir_agente(bloco.declaracao, cliente, ferramentas))

    return WorkflowDefinition(
        id=c.id,
        name=c.nome,
        # Um estágio só. Vários estágios são uma decisão de produto que ainda
        # não tem caso — e `Stage.ordered()` já dá a cascata inteira ordenada
        # por custo dentro de um.
        #
        # O estágio herda o nome da COMPOSIÇÃO. Antes ele herdava o nome do
        # domínio, e o domínio era o mesmo para toda cascata composta sobre
        # ele — o que fazia todo estágio de conciliação se chamar "Conciliação
        # bancária", independentemente do que a pessoa tinha montado.
        stages=(
            Stage(
                name=c.nome,
                cascade=tuple(resolvers),
                # A fiação DESTE degrau, derivada dos blocos — a ponta X7 que
                # o cabeçalho deste módulo dizia faltar. `produz` continua no
                # default: nenhum bloco do catálogo produz item.
                consome=consome_de(resolvers),
            ),
        ),
    )


# -- serialização -----------------------------------------------------------


def _agente_para_json(a: AgenteDeclarado) -> dict[str, Any]:
    return {
        "name": a.name,
        "system": a.system,
        "kind": a.kind,
        "prompt": a.prompt,
        "tipos": list(a.tipos),
        "abstem_com": a.abstem_com,
        "ferramentas": list(a.ferramentas),
        "model": a.model,
        "max_turns": a.max_turns,
        "max_format_retries": a.max_format_retries,
        "budget_microcents": a.budget_microcents,
        "budget_total_microcents": a.budget_total_microcents,
        "acao_sugerida": a.acao_sugerida,
    }


def _agente_de_json(d: dict[str, Any]) -> AgenteDeclarado:
    return AgenteDeclarado(
        name=d["name"],
        system=d["system"],
        kind=d["kind"],
        prompt=d["prompt"],
        tipos=tuple(d["tipos"]),
        abstem_com=d["abstem_com"],
        ferramentas=tuple(d.get("ferramentas", ())),
        model=d.get("model", ""),
        max_turns=d.get("max_turns", 6),
        max_format_retries=d.get("max_format_retries", 2),
        budget_microcents=d.get("budget_microcents", 4_000_000),
        budget_total_microcents=d.get("budget_total_microcents", 400_000_000),
        acao_sugerida=d.get("acao_sugerida", "revisar_manual"),
    )


def _blocos_para_json(blocos: tuple[Bloco, ...]) -> list[dict[str, Any]]:
    saida = []
    for b in blocos:
        if isinstance(b, BlocoRegra):
            saida.append({"tipo": "regra", "nome": b.nome, "parametros": b.parametros})
        else:
            saida.append(
                {"tipo": "agente", "declaracao": _agente_para_json(b.declaracao)}
            )
    return saida


def para_json(c: Composicao) -> dict[str, Any]:
    return {
        "id": c.id,
        "nome": c.nome,
        "justificativa": c.justificativa,
        "gerado_em": c.gerado_em.isoformat(),
        "version": c.version,
        "blocos": _blocos_para_json(c.blocos),
    }


def de_json(d: dict[str, Any]) -> Composicao:
    blocos: list[Bloco] = []
    for b in d["blocos"]:
        if b["tipo"] == "regra":
            blocos.append(BlocoRegra(nome=b["nome"], parametros=dict(b.get("parametros", {}))))
        elif b["tipo"] == "agente":
            blocos.append(BlocoAgente(declaracao=_agente_de_json(b["declaracao"])))
        else:
            # Tipo novo precisa de uma decisão sobre o que ele significa na
            # cascata, não de um `else` que o ignora em silêncio.
            raise ValueError(
                f"tipo de bloco desconhecido: {b['tipo']!r}. use 'regra' ou 'agente'"
            )
    gerado = datetime.fromisoformat(d["gerado_em"])
    if gerado.tzinfo is None:
        raise ValueError(
            f"composição {d['id']!r} no disco tem `gerado_em` sem fuso. horário "
            f"ingênuo não é um instante, e a ordem entre composições depende disso"
        )
    return Composicao(
        id=d["id"],
        nome=d["nome"],
        justificativa=d.get("justificativa", ""),
        gerado_em=gerado,
        blocos=tuple(blocos),
    )


# -- disco ------------------------------------------------------------------


def caminho(composicao_id: str, raiz: Path | None = None) -> Path:
    return (raiz or _RAIZ_PADRAO) / f"{composicao_id}.json"


def gravar(c: Composicao, raiz: Path | None = None) -> Path:
    """Grava. RECUSA sobrescrever.

    Mesma recusa de `gravar_receita`, do scaffold e do `CaseStore`. Aqui o
    motivo é que uma composição já executada aparece em `Run.workflow_version`;
    trocar o conteúdo sob o mesmo id faria um run antigo apontar para uma
    cascata que nunca rodou.
    """
    destino = caminho(c.id, raiz)
    if destino.exists():
        raise FileExistsError(
            f"já existe uma composição com id {c.id!r} em {destino}. runs "
            f"antigos apontam para ela pela versão; escolha outro id"
        )
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(para_json(c), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return destino


def ler(composicao_id: str, raiz: Path | None = None) -> Composicao:
    return de_json(json.loads(caminho(composicao_id, raiz).read_text(encoding="utf-8")))


def listar(raiz: Path | None = None) -> list[Composicao]:
    """As composições em disco. Uma que não parseia é PULADA com aviso.

    Mesma política de `descrever` em `workflows.py`: um arquivo ruim não derruba
    a listagem inteira, mas também não some em silêncio.
    """
    base = raiz or _RAIZ_PADRAO
    if not base.exists():
        return []
    saida = []
    for arquivo in sorted(base.glob("*.json")):
        try:
            saida.append(de_json(json.loads(arquivo.read_text(encoding="utf-8"))))
        except (ValueError, KeyError) as erro:  # noqa: PERF203
            import sys

            print(f"composição ilegível em {arquivo}: {erro}", file=sys.stderr)
    return saida


def agora() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "Bloco",
    "BlocoAgente",
    "BlocoRegra",
    "Composicao",
    "agora",
    "caminho",
    "construir_composicao",
    "de_json",
    "gravar",
    "listar",
    "ler",
    "para_json",
]
