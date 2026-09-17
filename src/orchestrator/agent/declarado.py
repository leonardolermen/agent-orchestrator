"""Um agente descrito como DADO, não como código.

**Por que isto é a peça central do produto.** Até aqui, declarar um agente exigia
escrever três funções Python — `units`, `parse` e `abstain`. Isso é pouco (o
`swe` faz em quinze linhas) e ainda assim é código: não dá para compor pela
tela, não dá para versionar como configuração, e não dá para um catálogo
oferecer "acrescente um agente" sem que alguém abra um editor.

O catálogo do `grill` contornou isso oferecendo agentes PRONTOS — `L1`, `L2`,
`agente` — e foi assim que a plataforma virou um cardápio de conciliação sem
ninguém decidir que viraria.

**A observação que destrava.** Os três callables não são arbitrários; eles são
dado disfarçado. No `swe`:

    units   → um `kind` e um template sobre o payload
    parse   → um vocabulário fechado e um schema JSON
    abstain → um rótulo

Nenhum dos três precisa de Python. O que precisa de Python é a REGRA
determinística — casar por documento e valor é lógica de domínio e continua
sendo código. Agente, não.

**A invariante que virou estrutura.** `abstem_com` não pode estar em `tipos`. No
`swe`, `DUVIDA` significava ao mesmo tempo "esta issue é uma pergunta" e "não
consegui classificar"; 16 de 50 casos saíam do denominador da precisão e a taxa
de abstenção reportada era a fatia de DUVIDA do conjunto (P6.86). Lá a colisão
foi descoberta medindo; aqui ela é recusada na construção.
"""

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

from orchestrator.agent.agent import Agent, AgentSpec, AgentTask
from orchestrator.agent.llm import LLMClient
from orchestrator.agent.tools.registry import ToolRegistry
from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.resolution import Confidence, Proposal, TraceEvent, TraceKind
from orchestrator.kernel.work import WorkSet


@dataclass(frozen=True)
class AgenteDeclarado:
    """Tudo que um agente é, como dado serializável."""

    name: str
    system: str
    # Qual `WorkItem.kind` ele trabalha. Sem isto o agente pegaria o pool
    # inteiro, inclusive itens de outra natureza — e produziria proposta sobre
    # coisa que não sabe ler.
    kind: str
    # Template sobre o payload do item: `"{titulo}\n\n{corpo}"`. É o que vira
    # `AgentTask.prompt`.
    prompt: str
    # Vocabulário FECHADO de saída. Um tipo fora dele dispara o retry de
    # formato, exatamente como na conciliação — é o que impede o modelo de
    # inventar uma categoria que nenhum consumidor sabe tratar.
    tipos: tuple[str, ...]
    # O rótulo de "não sei" DESTE agente.
    abstem_com: str
    ferramentas: tuple[str, ...] = ()
    model: str = ""
    max_turns: int = 6
    max_format_retries: int = 2
    budget_microcents: int = 4_000_000
    budget_total_microcents: int = 400_000_000
    acao_sugerida: str = "revisar_manual"

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("agente sem nome: o trace não teria como atribuí-lo")
        if not self.kind.strip():
            raise ValueError(
                f"{self.name!r} não declara `kind`. sem ele o agente pegaria o "
                f"pool inteiro, inclusive itens de outra natureza, e proporia "
                f"sobre coisa que não sabe ler"
            )
        if not self.tipos:
            raise ValueError(
                f"{self.name!r} sem vocabulário: um agente que pode responder "
                f"qualquer coisa produz saída que nenhum consumidor sabe tratar"
            )
        # A invariante do P6.86, agora estrutural.
        if self.abstem_com in self.tipos:
            raise ValueError(
                f"{self.name!r}: {self.abstem_com!r} é o rótulo de abstenção E "
                f"um tipo do vocabulário. Os casos com esse tipo esperado "
                f"sairiam do denominador da precisão e entrariam na taxa de "
                f"abstenção — medido no `swe`, onde custou um terço de um "
                f"conjunto de avaliação. Separe o 'não sei' dos tipos"
            )
        if "{" not in self.prompt:
            raise ValueError(
                f"{self.name!r}: o prompt não interpola campo nenhum do payload "
                f"({self.prompt[:40]!r}...). todo item receberia o MESMO texto, "
                f"e o agente responderia sem ler o item"
            )
        if self.max_turns < 1:
            raise ValueError(f"max_turns precisa ser >= 1: {self.max_turns}")
        for nome, valor in (
            ("budget_microcents", self.budget_microcents),
            ("budget_total_microcents", self.budget_total_microcents),
        ):
            if valor < 0:
                raise ValueError(f"{nome} negativo ({valor}) nasceria estourado")

    @property
    def vocabulario(self) -> str:
        """O vocabulário como o prompt deve anunciá-lo."""
        return "|".join(f'"{t}"' for t in (*self.tipos, self.abstem_com))


def _campos(payload: Any) -> dict[str, Any]:
    if is_dataclass(payload) and not isinstance(payload, type):
        return asdict(payload)
    if isinstance(payload, dict):
        return dict(payload)
    raise TypeError(
        f"payload de tipo {type(payload).__name__} não é interpolável: um "
        f"agente declarado monta o prompt a partir dos CAMPOS do item, então o "
        f"payload precisa ser um dataclass ou um dict"
    )


def _units(decl: AgenteDeclarado):
    def units(work: WorkSet) -> list[AgentTask]:
        tarefas = []
        for item in work.of_kind(decl.kind):
            campos = _campos(item.payload)
            try:
                prompt = decl.prompt.format_map(campos)
            except KeyError as erro:
                # Falha ALTO e nomeia o que falta. A alternativa — um
                # `defaultdict` que devolve vazio — produziria um prompt com
                # buracos silenciosos, e o modelo responderia sobre um item que
                # não leu inteiro.
                raise KeyError(
                    f"{decl.name!r}: o prompt cita {erro} e o payload de "
                    f"{item.id!r} não tem esse campo. disponíveis: "
                    f"{sorted(campos)}"
                ) from erro
            tarefas.append(AgentTask(id=item.id, prompt=prompt))
        return tarefas

    return units


def _parse(decl: AgenteDeclarado):
    def parse(item_id: str, texto: str, cost: Cost, trace: list[TraceEvent]):
        limpo = texto.strip()
        # Cerca de código é o erro de formato mais comum e o mais barato de
        # tolerar. Preservado de `swe._parse` e de `interpretar_proposta`.
        for cerca in ("```json", "```"):
            limpo = limpo.removeprefix(cerca)
        try:
            dados = json.loads(limpo.removesuffix("```").strip())
        except json.JSONDecodeError:
            return None
        if not isinstance(dados, dict):
            return None

        tipo = dados.get("tipo")
        # Vocabulário fechado, incluindo o rótulo de abstenção: o modelo PODE
        # dizer que não sabe, e isso não é erro de formato.
        if tipo not in (*decl.tipos, decl.abstem_com):
            return None

        evidencia = dados.get("evidencia", [])
        if not isinstance(evidencia, list):
            return None
        try:
            confianca = Confidence(dados.get("confianca", "BAIXA"))
        except ValueError:
            return None

        # Confiança alta sem evidência é REBAIXADA, não descartada: a hipótese
        # ainda ajuda, com o peso certo. É a mesma regra da conciliação e do
        # `swe`, e ela é do PRODUTO — não de um domínio —, por isso mora aqui.
        if confianca is Confidence.ALTA and not evidencia:
            confianca = Confidence.BAIXA

        return Proposal(
            item_id=item_id,
            tipo=tipo,
            explicacao=str(dados.get("explicacao", "")),
            evidencia=[str(e) for e in evidencia],
            confianca=confianca,
            acao_sugerida=decl.acao_sugerida,
            cost=cost,
            trace=[*trace, TraceEvent(kind=TraceKind.OUTCOME, detail={"tipo": tipo})],
        )

    return parse


def _abstain(decl: AgenteDeclarado):
    def abstain(item_id, motivo, cost=None, trace=None):
        return Proposal.abstencao(item_id, decl.abstem_com, motivo, cost, trace)

    return abstain


def construir_agente(
    decl: AgenteDeclarado,
    client: LLMClient,
    ferramentas: ToolRegistry | None = None,
) -> Agent:
    """A declaração vira um `Agent` de verdade. VALIDA CONSTRUINDO.

    O `Agent` resultante é o MESMO do M2 — mesmo laço, mesmo orçamento em dois
    níveis, mesmo retry de formato, mesma captura estreita em volta de
    `client.complete()`. Nada aqui reimplementa nada; o que muda é de onde vêm
    `units`, `parse` e `abstain`.

    `ferramentas` é filtrado por `decl.ferramentas`: um agente recebe as
    ferramentas que ele DECLARA, não as que por acaso existem no registro. Sem
    esse recorte, acrescentar uma ferramenta ao catálogo mudaria o custo e o
    comportamento de todo agente composto sobre ele, sem ninguém pedir.
    """
    registro = ferramentas or ToolRegistry([])
    desconhecidas = sorted(set(decl.ferramentas) - set(registro.names()))
    if desconhecidas:
        raise ValueError(
            f"{decl.name!r} declara ferramenta inexistente: {desconhecidas}. "
            f"disponíveis: {sorted(registro.names())}"
        )
    # `recortar` e não `ToolRegistry([registro.spec(n) for n in ...])`: a
    # segunda forma PERDIA O CONTEXTO. Um agente composto sobre um registro
    # ligado a dados recebia um registro desligado, e como `call` nunca levanta,
    # toda ferramenta voltava como erro, o laço continuava e a conta crescia.
    escolhidas = registro.recortar(decl.ferramentas)

    return Agent(
        spec=AgentSpec(
            name=decl.name,
            system=decl.system,
            model=decl.model or client.model,
            units=_units(decl),
            parse=_parse(decl),
            abstain=_abstain(decl),
            max_turns=decl.max_turns,
            max_format_retries=decl.max_format_retries,
            budget_microcents=decl.budget_microcents,
            budget_total_microcents=decl.budget_total_microcents,
        ),
        client=client,
        tools=escolhidas,
    )


@dataclass(frozen=True)
class ParametroDeRegra:
    """O que uma regra aceita ser ajustada. DESCREVE, não valida.

    Sem faixa (mínimo/máximo) de propósito: as restrições já vivem nos
    `__post_init__` dos resolvers, e duplicá-las aqui criaria duas fontes de
    verdade que divergiriam na primeira mudança. Mesma decisão de
    `ParametroSpec` no grill, pelo mesmo motivo.
    """

    nome: str
    default: int
    descricao: str


@dataclass(frozen=True)
class RegraDisponivel:
    """Uma regra determinística que o catálogo oferece para compor.

    **Por que regra continua sendo CÓDIGO e não declaração.** Casar por
    documento e valor é lógica de domínio; não há declaração que a substitua, e
    fingir que há produziria uma linguagem de regras pela metade. O que a tela
    compõe é QUAIS regras entram e com que parâmetros — não o corpo delas.

    (Tipos de regra genéricos — igualdade, tolerância, agrupamento, tabela,
    padrão, limiar — são o G3 do spec da plataforma geral. Quando existirem,
    entram aqui como mais entradas, sem mudar este contrato.)
    """

    nome: str
    cost_class: CostClass
    resumo: str
    # `construir(parametros) -> Resolver`. Assinatura UNIFORME, como
    # `EntradaCatalogo.construir` no grill: variável exigiria introspecção para
    # saber o que passar, e é esse padrão que já deu um defeito silencioso.
    construir: Callable[[dict[str, int]], Any]
    parametros: tuple[ParametroDeRegra, ...] = ()

    def __post_init__(self) -> None:
        if self.cost_class is CostClass.AGENTE:
            raise ValueError(
                f"regra {self.nome!r} se declara AGENTE. uma regra não chama "
                f"modelo — se ela chama, é agente, e declará-la como regra a "
                f"faria rodar ANTES dos agentes baratos na cascata"
            )


class ClienteDeValidacao:
    """Cliente inerte: constrói o agente, recusa falar com modelo.

    Público, e é o DEFAULT de `construir_composicao`, pela mesma razão que
    `ClienteAusente` é o default de `grill.receita.construir`: quem só quer
    validar não deve precisar lembrar de passar a tranca. Quem quer executar
    passa um cliente de verdade, de propósito.

    O modelo é um REAL da tabela de preços: `Agent.__post_init__` chama
    `Cost.zero().microcents(model)` e um nome inventado faria a validação
    levantar por um motivo errado. Mesmo cuidado do `ClienteAusente` do grill.
    """

    model = "claude-opus-5"

    def complete(self, system, messages, tools):  # pragma: no cover
        raise RuntimeError(
            "cliente de validação não fala com modelo: alguém tentou EXECUTAR "
            "um agente construído só para checar a declaração"
        )
