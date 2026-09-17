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

A terceira garantia era "um domínio só": blocos cujos `WorkItem.kind` não
conversam produzem uma cascata vazia de sentido, porque o segundo roda sobre um
pool que o primeiro nem enxerga. Ela não sumiu — mudou de lugar e ficou mais
forte. `Stage.consome`/`Stage.produz` declara a fiação POR DEGRAU e
`WorkflowDefinition.__post_init__` recusa um grafo cujos kinds não conectam, o
que valida o grafo que VAI RODAR em vez de uma partição de catálogo.
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
from orchestrator.kernel.definition import Stage, WorkflowDefinition
from orchestrator.kernel.resolver import Resolver

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
    cliente: LLMClient | None = None,
    contexto: Any = None,
) -> WorkflowDefinition:
    """Valida construindo. Se retorna, a cascata roda.

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
    cliente = cliente or ClienteDeValidacao()

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
            resolvers.append(regra.construir(dict(bloco.parametros)))
        else:
            # Sem checagem de `kind` contra uma lista de domínio: quem recusa
            # kinds que não conectam é `WorkflowDefinition.__post_init__`, sobre
            # o grafo que vai rodar. Ver o cabeçalho do módulo.
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
        stages=(Stage(name=c.nome, cascade=tuple(resolvers)),),
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
