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
from dataclasses import dataclass
from typing import Any

from orchestrator.agent.agent import Agent, AgentSpec, AgentTask
from orchestrator.agent.llm import LLMClient
from orchestrator.agent.tarefa import SaidaDaTarefa, Tarefa, TarefaSpec
from orchestrator.agent.tools.registry import ToolRegistry
from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.resolution import (
    Confidence,
    Proposal,
    Resolution,
    TraceEvent,
    TraceKind,
)
from orchestrator.kernel.work import WorkItem, WorkSet, campos_de


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


@dataclass(frozen=True)
class TarefaDeclarada:
    """Tudo que uma TAREFA é, como dado serializável. O irmão do
    `AgenteDeclarado` para o resolver que transforma.

    **Por que não um campo `produz` no `AgenteDeclarado`.** Foi o que a §6.2 do
    spec de 2026-09-17 propôs, e o formato mudou desde então: com `produz`
    preenchido, `tipos` e `abstem_com` deixam de significar qualquer coisa —
    uma transformação não tem vocabulário de julgamento a rotular —, e um
    agente com os três é um dos cruzamentos que a união discriminada de
    `api/schemas.py` existe para recusar antes do handler rodar. O sintoma
    seria um bloco onde metade dos campos é ignorada em silêncio conforme
    outro campo.

    Sem `tipos` e sem `abstem_com`, então, e a ausência é a mesma que
    `tarefa.py::_abster` já justifica: "não há tipo a escolher: não transformar
    é a ausência de resolução, e ausência é a mesma em todo domínio".
    """

    name: str
    system: str
    # O que consome. Mesmo papel do `kind` do agente declarado.
    kind: str
    # O kind que SAI. É o que liga este bloco ao próximo: o degrau seguinte
    # declara `consome={produz}` e só roda quando houver item dele.
    produz: str
    # Template sobre o payload do item, como no agente declarado.
    prompt: str
    ferramentas: tuple[str, ...] = ()
    model: str = ""
    max_turns: int = 6
    max_format_retries: int = 2
    budget_microcents: int = 4_000_000
    budget_total_microcents: int = 400_000_000

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("tarefa sem nome: o trace não teria como atribuí-la")
        if not self.kind.strip():
            raise ValueError(
                f"{self.name!r} não declara `kind`. sem ele a tarefa pegaria o "
                f"pool inteiro, inclusive itens de outra natureza, e tentaria "
                f"transformar coisa que não sabe ler"
            )
        if not self.produz.strip():
            raise ValueError(
                f"{self.name!r}: `produz` vazio. a tarefa consumiria o item sem "
                f"entregá-lo a ninguém — o item sumiria do run, e para descartar "
                f"de propósito existe o `filtro`"
            )
        if self.produz == self.kind:
            raise ValueError(
                f"{self.name!r}: produz o mesmo kind que consome ({self.kind!r}). "
                f"o ramo alimentaria a si mesmo, e o degrau rodaria sobre a "
                f"própria saída até o teto de rondas"
            )
        if "{" not in self.prompt:
            raise ValueError(
                f"{self.name!r}: o prompt não interpola campo nenhum do payload "
                f"({self.prompt[:40]!r}...). todo item receberia o MESMO texto, "
                f"e o modelo transformaria sem ler o item"
            )
        if self.max_turns < 1:
            raise ValueError(f"max_turns precisa ser >= 1: {self.max_turns}")
        for nome, valor in (
            ("budget_microcents", self.budget_microcents),
            ("budget_total_microcents", self.budget_total_microcents),
        ):
            if valor < 0:
                raise ValueError(f"{nome} negativo ({valor}) nasceria estourado")


def _prompt_do_item(nome: str, template: str, item: WorkItem) -> str:
    """O template do autor, preenchido com os campos do item.

    EXTRAÍDO de `_units` em vez de copiado para a tarefa: duas cópias divergem,
    e a que divergir é a que ninguém testa. A mensagem de campo ausente é a
    parte que não pode se perder — ela nomeia o campo E lista os disponíveis,
    que é o que permite corrigir o prompt sem abrir o payload.
    """
    campos = campos_de(item.payload)
    try:
        return template.format_map(campos)
    except KeyError as erro:
        # Falha ALTO e nomeia o que falta. A alternativa — um `defaultdict` que
        # devolve vazio — produziria um prompt com buracos silenciosos, e o
        # modelo responderia sobre um item que não leu inteiro.
        raise KeyError(
            f"{nome!r}: o prompt cita {erro} e o payload de {item.id!r} não tem "
            f"esse campo. disponíveis: {sorted(campos)}"
        ) from erro


def _ferramentas_de(
    nome: str, declaradas: tuple[str, ...], registro: ToolRegistry
) -> ToolRegistry:
    """As ferramentas que a declaração pede, recortadas do registro.

    `recortar` e NÃO `ToolRegistry([registro.spec(n) for n in ...])`: a segunda
    forma perde o contexto em silêncio, e como `call` nunca levanta, toda
    ferramenta volta como erro, o laço continua e a conta cresce.
    """
    desconhecidas = sorted(set(declaradas) - set(registro.names()))
    if desconhecidas:
        raise ValueError(
            f"{nome!r} declara ferramenta inexistente: {desconhecidas}. "
            f"disponíveis: {sorted(registro.names())}"
        )
    return registro.recortar(declaradas)


def _units(decl: AgenteDeclarado):
    def units(work: WorkSet) -> list[AgentTask]:
        return [
            AgentTask(id=item.id, prompt=_prompt_do_item(decl.name, decl.prompt, item))
            for item in work.of_kind(decl.kind)
        ]

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
    # `is None`, não `or`, e aqui a diferença é a que o parágrafo abaixo já
    # descreve custando caro: um registro LIGADO a dados mas sem ferramenta
    # nenhuma, se algum dia `ToolRegistry` ganhar `__len__`, seria trocado por
    # um registro NÃO LIGADO — e como `call` nunca levanta, toda ferramenta
    # voltaria como erro, o laço continuaria e a conta cresceria. Mesma
    # disciplina de `grill.receita.construir`.
    registro = ToolRegistry([]) if ferramentas is None else ferramentas
    escolhidas = _ferramentas_de(decl.name, decl.ferramentas, registro)

    return Agent(
        spec=AgentSpec(
            name=decl.name,
            system=decl.system,
            model=decl.model or client.model,
            units=_units(decl),
            # Um kind só, porque `AgenteDeclarado.kind: str`. É o mesmo kind
            # que `_units` filtra com `work.of_kind(decl.kind)`.
            consome=frozenset({decl.kind}),
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


def _transformar(decl: TarefaDeclarada):
    """Como o texto do modelo vira o item do próximo degrau.

    É a MESMA forma que `domains/redacao/_degrau` escreve três vezes à mão —
    generalizada aqui porque, declarada, ela é sempre esta: o texto final vira
    o payload de um item novo do kind declarado.
    """

    def transformar(
        item_id: str, texto: str, custo: Cost, trace: list[TraceEvent]
    ) -> SaidaDaTarefa | None:
        if not texto.strip():
            # Texto vazio não é transformação. `None` dispara o retry de
            # formato de `conversar`; esgotado, o item fica no pool para o
            # próximo degrau.
            return None
        rastro = tuple(trace)
        return SaidaDaTarefa(
            cost=custo,
            trace=rastro,
            resolution=Resolution(
                item_ids=frozenset({item_id}),
                produced_by=decl.name,
                rule=decl.name,
                # Sem o rastro esta resolução é uma afirmação sem fonte — a
                # mesma regra que `kernel/resolution.py` aplica à proposta.
                evidence={"trace": rastro},
            ),
            produced=(
                WorkItem(
                    id=f"{item_id}+{decl.produz}",
                    kind=decl.produz,
                    # Chaveado pelo NOME DO KIND, não por um "texto" fixo: dois
                    # ramos de um `Parallel` que se reúnem num `Merge` trariam
                    # `texto` os dois, e quem lê não distinguiria de qual ramo
                    # veio. E dict, nunca string crua: `_campos` recusa payload
                    # que não seja dict ou dataclass, então texto cru quebraria
                    # o bloco seguinte ao montar o prompt — que é exatamente o
                    # encadeamento que este bloco existe para permitir.
                    payload={decl.produz: texto.strip()},
                    origem=decl.name,
                ),
            ),
        )

    return transformar


def construir_tarefa(
    decl: TarefaDeclarada,
    client: LLMClient,
    ferramentas: ToolRegistry | None = None,
) -> Tarefa:
    """A declaração vira uma `Tarefa` de verdade. VALIDA CONSTRUINDO.

    O espelho de `construir_agente`, e a `Tarefa` resultante é a MESMA que
    `domains/redacao` monta à mão — mesmo laço, mesmo orçamento em dois níveis,
    mesmo retry de formato. O que muda é de onde vêm `prompt_de` e
    `transformar`.
    """
    registro = ToolRegistry([]) if ferramentas is None else ferramentas
    escolhidas = _ferramentas_de(decl.name, decl.ferramentas, registro)

    return Tarefa(
        spec=TarefaSpec(
            name=decl.name,
            system=decl.system,
            model=decl.model or client.model,
            prompt_de=lambda item: _prompt_do_item(decl.name, decl.prompt, item),
            transformar=_transformar(decl),
            kind=decl.kind,
            produz=decl.produz,
            max_turns=decl.max_turns,
            max_format_retries=decl.max_format_retries,
            budget_microcents=decl.budget_microcents,
            budget_total_microcents=decl.budget_total_microcents,
        ),
        client=client,
        tools=escolhidas,
    )


# O que um parâmetro de regra pode valer.
#
# Era `int`, e o `int` era o teto de quanto uma regra podia ser configurada: com
# ele, a tela ajusta folga e limite, e nada mais. Uma regra GENÉRICA precisa
# receber NOME DE CAMPO — em quais campos ela casa —, e nome de campo é `str`,
# quando não uma lista deles.
#
# A assimetria estava documentada como defeito conhecido em
# `authoring/composicao.py`: "um `parametros: dict[str, int]` carregando um
# prompt — e o `int` no tipo é o aviso de que não cabe". O aviso valia também
# para o lado determinístico.
#
# FECHADO e não `Any`: os três casos são o que a tela sabe editar (número, texto
# e lista de textos) e o que o JSON transporta sem ambiguidade. `Any` aceitaria
# um dicionário aninhado que nenhum editor renderiza e nenhum construtor espera.
ValorDeParametro = int | str | tuple[str, ...]


@dataclass(frozen=True)
class ParametroDeRegra:
    """O que uma regra aceita ser ajustada. DESCREVE, não valida.

    Sem faixa (mínimo/máximo) de propósito: as restrições já vivem nos
    `__post_init__` dos resolvers — `ToleranceMatcher.__post_init__` recusa
    `max_cents` negativo, e é lá que a recusa tem o contexto para explicar por
    quê —, e duplicá-las aqui criaria duas fontes de verdade que divergiriam na
    primeira mudança.

    O TIPO do parâmetro é o tipo do `default`, e não um campo à parte: um campo
    `tipo: str` ao lado de um `default` seria a segunda fonte de verdade que o
    parágrafo acima recusa, e os dois divergiriam no primeiro parâmetro novo.
    """

    nome: str
    default: ValorDeParametro
    descricao: str
    # Parâmetro que a pessoa PRECISA preencher para o bloco existir.
    #
    # Nasceu com as regras genéricas, e elas são a razão de ele não ter existido
    # antes: enquanto todo bloco era de um domínio, todo bloco já vinha
    # configurado — o `L2` sabe que casa por documento, e o que a tela ajusta é
    # só a folga. `igualdade` não sabe nada; sem alguém dizer em quais campos
    # ela casa, ela não é uma regra, é a forma de uma.
    #
    # Sem isto, o bloco entraria no catálogo com um default que não funciona, e
    # a recusa apareceria como "não casou nada" ao rodar — ou, pior, um default
    # PLAUSÍVEL (`esquerda="banco"`) casaria zero em silêncio sobre qualquer
    # fonte que não seja conciliação.
    obrigatorio: bool = False


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

    **`rotulo` e `categoria` são para a PALETA, e moram aqui de propósito.** A
    tela agrupa os blocos em seções e os chama por um nome curto em inglês; uma
    tabela de-para no front seria a segunda fonte de verdade de sempre, e o
    sintoma dela é conhecido — um bloco novo entraria na paleta sem categoria,
    ou com um rótulo que envelheceu. Quem declara o bloco declara como ele
    aparece.

    `nome` continua sendo a IDENTIDADE — é o que a composição manda e o que o
    catálogo indexa. `rotulo` é só o que se lê.
    """

    nome: str
    cost_class: CostClass
    resumo: str
    # `construir(parametros) -> Resolver`. Assinatura UNIFORME, como
    # `workflows.WorkflowFactory`: variável exigiria introspecção para saber o
    # que passar, e é esse padrão que já deu um defeito silencioso — o
    # `_construir_definicao` da API, que decidia repassar a fila olhando o NOME
    # do parâmetro da fábrica.
    construir: Callable[[dict[str, ValorDeParametro]], Any]
    parametros: tuple[ParametroDeRegra, ...] = ()
    # Como a paleta chama e onde o coloca. Vazio cai no `nome` e em "OTHER" —
    # um bloco sem categoria aparece, e aparecer num balde chamado "outros" é
    # sintoma visível, diferente de sumir da tela.
    rotulo: str = ""
    categoria: str = "OTHER"

    @property
    def obrigatorios(self) -> tuple[str, ...]:
        """Os parâmetros sem os quais este bloco não constrói.

        Vazio para todo bloco que um domínio já configurou — que era o caso de
        todos até as regras genéricas existirem.
        """
        return tuple(p.nome for p in self.parametros if p.obrigatorio)

    def faltando(self, parametros: dict[str, ValorDeParametro]) -> tuple[str, ...]:
        """O que a pessoa ainda não preencheu. Para a recusa NOMEAR o que falta.

        Vazio conta como ausente: a tela manda `""` e `[]` para campo que nunca
        foi tocado, e tratá-los como preenchidos faria o bloco construir com
        nada e casar zero — exatamente o silêncio que `obrigatorio` existe para
        impedir.
        """
        return tuple(
            nome
            for nome in self.obrigatorios
            if not parametros.get(nome)
        )

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
