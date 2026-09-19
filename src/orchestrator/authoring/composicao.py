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

**A terceira garantia — cada bloco é alimentado pela fonte — mora na BORDA,
não aqui.** Ela dizia: blocos cujos `WorkItem.kind` não conversam produzem
uma cascata vazia de sentido. A guarda antiga comparava o `kind` do agente
com os `kinds` de um domínio declarado, e saiu porque recusava cascata válida
depois que a tela perdeu o seletor.

O lugar certo é o grafo que VAI RODAR contra a fonte que VAI RODAR — e isso
só existe junto na borda do `/runs`. Esta função faz a metade dela: deriva
`Stage.consome` dos blocos (`consome_de`), então o degrau reserva o que não
consome e a borda tem o que ler. A outra metade, `api/app.py::_conferir_kinds`,
recusa com 422 — por resolver, nomeando o bloco — qualquer `consome` que não
cruze os kinds do pool carregado.

Uma composição continua sendo ACEITA aqui com qualquer `kind`: ela não conhece
a fonte, e "valida construindo" é a garantia desta função. Um `kind` digitado
errado é pego na execução, antes de gastar — não mais "aceito, e em execução
nunca pega item nenhum".

**Mais de um degrau, e por que isso importa.** `Composicao` carrega `etapas`, e
`blocos=(...)` é o açúcar de uma etapa só — o mesmo par que o kernel tem em
`Task()`/`Stage()`, e pela mesma razão: o caso simples não deve custar a forma
geral. Dentro de uma etapa a ordem é por CUSTO; entre etapas é por DADO. São os
dois eixos do §2 do README.

Enquanto havia um degrau só, um bloco que ramifica não tinha para onde ramificar:
o ramo virava beco sem saída e só a `entrega` o salvava. Com dois, o ramo tem
degrau de verdade depois dele.
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
    ValorDeParametro,
    construir_agente,
)
from orchestrator.agent.llm import LLMClient
from orchestrator.domains.reconciliation.revisor import RevisorHumano
from orchestrator.domains.registro import CATALOGO
from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.definition import (
    Stage,
    WorkflowDefinition,
    consome_de,
    produz_de,
)
from orchestrator.kernel.resolver import Resolver
from orchestrator.review.fila import Fila

_RAIZ_PADRAO = Path("data") / "composicoes"


@dataclass(frozen=True)
class BlocoRegra:
    """Uma regra do catálogo, com os parâmetros ajustados."""

    nome: str
    parametros: dict[str, ValorDeParametro] = field(default_factory=dict)


@dataclass(frozen=True)
class BlocoAgente:
    """Um agente declarado INLINE. É o que a `Receita` não sabia carregar."""

    declaracao: AgenteDeclarado


@dataclass(frozen=True)
class BlocoCrew:
    """Uma TRIPULAÇÃO: vários agentes sobre o mesmo item, e uma política de
    conflito.

    `Crew` já existia inteiro em `crew/crew.py`, com processo sequencial ou
    hierárquico e três maneiras de resolver desacordo — só não tinha como ser
    composto. Este bloco é a encanação que faltava.

    **`abstem_com` é DERIVADO dos agentes, não perguntado de novo.** O `Crew`
    exige saber quais valores de `Proposal.tipo` significam "não sei", e cada
    `AgenteDeclarado` já declara o seu. Perguntar outra vez criaria a segunda
    fonte de verdade de sempre — e o sintoma seria o Crew chamando de DESACORDO
    duas abstenções, que é o caso em que ele deveria se calar.

    O `manager` e o `synthesizer` não são campos daqui: `Crew.__post_init__` já
    recusa `HIERARCHICAL` sem gerente e `SINTETIZAR` sem sintetizador, com texto
    escrito para ser lido. Duplicar a recusa aqui daria duas mensagens para a
    mesma falha.
    """

    nome: str
    agentes: tuple[AgenteDeclarado, ...]
    process: str = "sequential"
    conflito: str = "abster"
    budget_microcents: int = 20_000_000


Bloco = BlocoRegra | BlocoAgente | BlocoCrew


def nome_do_bloco(b: Bloco) -> str:
    """A IDENTIDADE de um bloco, qualquer que seja o tipo dele.

    Era um ternário repetido em quatro lugares, e com um terceiro tipo de bloco
    um ternário deixa de caber. Repetir a decisão em quatro lugares é o que faz
    o quinto esquecer dela.
    """
    if isinstance(b, BlocoRegra):
        return b.nome
    if isinstance(b, BlocoCrew):
        return b.nome
    return b.declaracao.name


@dataclass(frozen=True)
class Etapa:
    """Um degrau do workflow: os blocos que rodam sobre o mesmo pool.

    **Dentro de uma etapa a ordem é por CUSTO; entre etapas é por DADO.** São os
    dois eixos do §2 do README, e é por isso que etapa não é decoração: o
    barato tenta antes do caro no MESMO trabalho, e a etapa seguinte só vê o
    que a anterior produziu.

    Uma etapa sozinha era tudo o que a tela sabia montar, e enquanto foi assim
    um bloco que ramifica não tinha para onde ramificar — o ramo virava beco sem
    saída e só a `entrega` o salvava. Com duas, o ramo tem degrau de verdade
    depois dele.
    """

    nome: str
    blocos: tuple[Bloco, ...]

    def __post_init__(self) -> None:
        if not self.blocos:
            raise ValueError(
                f"etapa {self.nome!r} sem bloco: um degrau vazio não roda e não "
                f"produz, e ficaria no desenho parecendo que faz alguma coisa"
            )
        if not self.nome.strip():
            raise ValueError("etapa sem nome: é por ele que o trace a identifica")


@dataclass(frozen=True)
class Composicao:
    id: str
    nome: str
    gerado_em: datetime
    # `blocos` OU `etapas`, exatamente um — e a assimetria é a mesma do `Task()`
    # do kernel, que existe "para que quem chega do CrewAI encontre a palavra
    # que espera, sem que o kernel ganhe um segundo conceito para manter em
    # sincronia". Aqui: `blocos=(...)` é o açúcar de uma etapa só, e é o que
    # todo chamador de hoje escreve.
    #
    # Depois de construída, `blocos` é a lista ACHATADA de todos os blocos e
    # `etapas` é a estrutura. As duas continuam verdadeiras porque uma é
    # derivada da outra, nunca escritas em paralelo.
    blocos: tuple[Bloco, ...] = ()
    etapas: tuple[Etapa, ...] = ()
    # Os `kind` que SÃO a saída deste workflow.
    #
    # É o `Output` do canvas, e é uma DECLARAÇÃO e não um degrau: nada roda
    # aqui. Um nó no canvas sugeriria execução, e um nó que não executa é
    # exatamente o tipo de coisa decorativa que este repositório evita.
    #
    # Existe porque um bloco que ramifica (`condicao`) produz um kind, e o
    # kernel recusa "beco sem saída" — item produzido que ninguém consome fica
    # no pool para sempre. `WorkflowDefinition.entrega` é a única exceção a essa
    # recusa, e o comentário de lá diz por que ela precisa ser ESCRITA: para que
    # "ninguém consome isto" seja afirmação do autor em vez de acidente. Derivar
    # sozinho (todo kind órfão vira entrega) desligaria a guarda inteira e
    # ensinaria o autor a mentir — que é textualmente o que aquele comentário
    # proíbe.
    entrega: tuple[str, ...] = ()
    justificativa: str = ""
    version: str = field(init=False)

    def __post_init__(self) -> None:
        # Exatamente um dos dois, como `Task()` exige `resolver` OU `cascade`.
        # Aceitar os dois deixaria a pergunta "qual vence?" sem resposta boa, e
        # aceitar nenhum é o workflow vazio que a linha seguinte recusa.
        if self.blocos and self.etapas:
            raise ValueError(
                "`blocos` e `etapas` juntos: `blocos` é o açúcar de uma etapa "
                "só. Para mais de um degrau, use `etapas`"
            )
        if not self.blocos and not self.etapas:
            raise ValueError("o workflow precisa de pelo menos um bloco")
        if self.gerado_em.tzinfo is None:
            raise ValueError("`gerado_em` precisa de fuso (use UTC)")
        # Normaliza para a forma GERAL e deriva a achatada. Os dois campos
        # sobrevivem porque um sai do outro: `etapas` é a estrutura, `blocos` é
        # "todos os blocos", e nenhum leitor de hoje precisou mudar.
        if self.blocos:
            object.__setattr__(
                self, "etapas", (Etapa(nome=self.nome, blocos=self.blocos),)
            )
        else:
            object.__setattr__(
                self, "blocos", tuple(b for e in self.etapas for b in e.blocos)
            )
        # Versão derivada do CONTEÚDO, como `WorkflowDefinition.version` e
        # `EvalDataset.version`. Dois resultados de benchmark só são comparáveis
        # se mediram a mesma cascata, e sem derivação nada impede duas
        # composições diferentes alegarem a mesma versão.
        # `entrega` entra no digest: duas composições com os mesmos blocos e
        # entregas diferentes são workflows diferentes — uma fecha o ramo, a
        # outra o deixa em aberto —, e dois resultados de benchmark só são
        # comparáveis se mediram a mesma coisa.
        digest = hashlib.sha256(
            json.dumps(
                {
                    # As ETAPAS, não os blocos achatados: os mesmos blocos em um
                    # degrau ou em dois são workflows diferentes — no primeiro
                    # todos disputam o mesmo pool, no segundo o de baixo só vê o
                    # que o de cima produziu. Achatar aqui daria a mesma versão
                    # para os dois, e dois resultados de benchmark passariam a
                    # alegar que mediram a mesma coisa.
                    "etapas": [
                        {"nome": e.nome, "blocos": _blocos_para_json(e.blocos)}
                        for e in self.etapas
                    ],
                    "entrega": sorted(self.entrega),
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        object.__setattr__(self, "version", digest[:12])

    @property
    def nomes(self) -> tuple[str, ...]:
        return tuple(nome_do_bloco(b) for b in self.blocos)


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
    seguro não porque composição não execute — ela executa, pelo mesmo
    `/api/workflows/{id}/runs` que roda receita — mas porque o ÚNICO caminho
    que executa uma composição, `workflows._de_composicao`, nunca chama esta
    função com o default: ele passa `fila=ctx.fila` sempre, verbatim. Quem
    chega ao default é só `/api/composicoes`, que compõe e grava e não
    executa. Quem for executar passa a fila de verdade, de propósito, e isso
    aparece no diff.

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

    # Os nomes são únicos no WORKFLOW inteiro, não por etapa. Um `L1` em dois
    # degraus não é ambíguo para o motor, mas é para as CONTAS: `Run.
    # resolved_by_resolver` é indexado por nome, e dois resolvers homônimos
    # fundiriam as contagens num número que não é de nenhum dos dois.
    vistos: set[str] = set()
    etapas: list[Stage] = []

    for etapa in c.etapas:
        etapas.append(
            _degrau(etapa, por_nome, vistos, cliente, ferramentas, fila)
        )

    return WorkflowDefinition(
        id=c.id,
        name=c.nome,
        stages=tuple(etapas),
        entrega=frozenset(c.entrega),
    )


def _tripulacao(bloco: BlocoCrew, cliente: LLMClient, ferramentas: Any) -> Resolver:
    """Um `Crew` a partir da declaração. Valida CONSTRUINDO, como tudo aqui.

    `Crew.__post_init__` recusa tripulação vazia, sequencial com um agente só,
    hierárquica sem gerente, síntese sem sintetizador e maioria com menos de
    três. As mensagens dele são escritas para serem lidas, e repetir a validação
    aqui daria duas mensagens para a mesma falha — divergindo na primeira que
    alguém mudasse.

    `abstem_com` sai dos AGENTES: cada `AgenteDeclarado` já diz qual valor de
    `Proposal.tipo` significa "não sei" para ele.
    """
    from orchestrator.crew.crew import Conflito, Crew, Process

    agentes = tuple(construir_agente(a, cliente, ferramentas) for a in bloco.agentes)
    try:
        return Crew(
            name=bloco.nome,
            agents=agentes,
            abstem_com=frozenset(a.abstem_com for a in bloco.agentes),
            process=Process(bloco.process),
            conflito=Conflito(bloco.conflito),
            budget_microcents=bloco.budget_microcents,
        )
    except ValueError as erro:
        # Re-levanta com o NOME do bloco na frente: a mensagem do `Crew` fala
        # do resolver, e quem está na tela procura o bloco que montou.
        raise ValueError(f"tripulação {bloco.nome!r}: {erro}") from erro


def _degrau(
    etapa: "Etapa",
    por_nome: dict[str, Any],
    vistos: set[str],
    cliente: LLMClient,
    ferramentas: Any,
    fila: Fila,
) -> Stage:
    """Um degrau: os blocos de uma etapa, virados resolvers.

    Separado do laço de fora porque agora há MAIS DE UM degrau, e o corpo que
    monta um deles é o mesmo para todos. Enquanto era um só, estar tudo junto
    não custava nada.
    """
    resolvers: list[Resolver] = []

    for bloco in etapa.blocos:
        nome = nome_do_bloco(bloco)
        if nome in vistos:
            raise ValueError(
                f"bloco repetido no workflow: {nome!r}. o segundo rodaria sobre "
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
        elif isinstance(bloco, BlocoCrew):
            resolvers.append(_tripulacao(bloco, cliente, ferramentas))
        else:
            # Sem checagem de `kind` AQUI, de propósito: a composição não
            # conhece a fonte. `Stage.consome` sai de `consome_de` no `return`
            # abaixo, e é a borda do `/runs` (`_conferir_kinds`) que recusa um
            # kind que a fonte não entrega — por resolver, antes de gastar.
            resolvers.append(construir_agente(bloco.declaracao, cliente, ferramentas))

    return Stage(
                name=etapa.nome,
                cascade=tuple(resolvers),
                # A fiação DESTE degrau, derivada dos blocos — a metade X7 da
                # lacuna de `kind` (ver cabeçalho do módulo).
                #
                # `produz` era default aqui, com o comentário "nenhum bloco do
                # catálogo produz item". Deixou de ser verdade com o bloco
                # `condicao`, que ramifica produzindo o kind que ativa o ramo —
                # e sem derivar, a composição PASSAVA e a execução recusava com
                # "produziu kind não declarado", um erro sobre uma escolha que
                # esta tela tinha acabado de aceitar.
                consome=consome_de(resolvers),
                produz=produz_de(resolvers),
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
        elif isinstance(b, BlocoCrew):
            saida.append(
                {
                    "tipo": "crew",
                    "nome": b.nome,
                    "agentes": [_agente_para_json(a) for a in b.agentes],
                    "process": b.process,
                    "conflito": b.conflito,
                    "budget_microcents": b.budget_microcents,
                }
            )
        else:
            saida.append(
                {"tipo": "agente", "declaracao": _agente_para_json(b.declaracao)}
            )
    return saida


def para_json(c: Composicao) -> dict[str, Any]:
    """O que vai para o disco.

    **`etapas` e `entrega` PRECISAM estar aqui**, e a ausência dos dois foi um
    defeito de verdade: a composição era gravada só com os blocos achatados, e
    recarregá-la devolvia um workflow de uma etapa só, sem a declaração de
    saída. Silencioso e sobre estrutura — a pessoa montava dois degraus, salvava,
    e o que voltava era outro workflow com a mesma cara.

    **Só `etapas`, nunca os dois.** A primeira versão gravava `blocos` junto,
    "para um arquivo novo ser legível por quem só conhece o formato antigo".
    Isso são duas fontes de verdade no mesmo arquivo, e o preço apareceu no
    mesmo dia: `test_tipo_de_bloco_desconhecido_LEVANTA_em_vez_de_sumir`
    corrompe um bloco e exige a recusa — com os dois campos, a leitura preferia
    `etapas` e a corrupção em `blocos` passava batido. A guarda deixava de
    valer para metade do arquivo.

    Quem lê ainda aceita `blocos`: é o formato dos arquivos que já estão no
    disco, e eles são de UMA etapa por construção.
    """
    return {
        "id": c.id,
        "nome": c.nome,
        "justificativa": c.justificativa,
        "gerado_em": c.gerado_em.isoformat(),
        "version": c.version,
        "etapas": [
            {"nome": e.nome, "blocos": _blocos_para_json(e.blocos)} for e in c.etapas
        ],
        "entrega": sorted(c.entrega),
    }


def _blocos_de_json(crus: list[dict[str, Any]]) -> tuple[Bloco, ...]:
    blocos: list[Bloco] = []
    for b in crus:
        if b["tipo"] == "regra":
            blocos.append(BlocoRegra(nome=b["nome"], parametros=dict(b.get("parametros", {}))))
        elif b["tipo"] == "agente":
            blocos.append(BlocoAgente(declaracao=_agente_de_json(b["declaracao"])))
        elif b["tipo"] == "crew":
            blocos.append(
                BlocoCrew(
                    nome=b["nome"],
                    agentes=tuple(_agente_de_json(a) for a in b["agentes"]),
                    process=b.get("process", "sequential"),
                    conflito=b.get("conflito", "abster"),
                    budget_microcents=b.get("budget_microcents", 20_000_000),
                )
            )
        else:
            # Tipo novo precisa de uma decisão sobre o que ele significa na
            # cascata, não de um `else` que o ignora em silêncio.
            raise ValueError(
                f"tipo de bloco desconhecido: {b['tipo']!r}. use 'regra', "
                f"'agente' ou 'crew'"
            )
    return tuple(blocos)


def de_json(d: dict[str, Any]) -> Composicao:
    # `etapas` quando o arquivo tem; `blocos` quando é de antes delas existirem.
    # Os arquivos antigos são de UMA etapa por construção, então cair no açúcar
    # reproduz exatamente o que eles significavam.
    etapas = tuple(
        Etapa(nome=e["nome"], blocos=_blocos_de_json(e["blocos"]))
        for e in d.get("etapas", [])
    )
    blocos = () if etapas else _blocos_de_json(d["blocos"])
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
        blocos=blocos,
        etapas=etapas,
        entrega=tuple(d.get("entrega", ())),
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
