"""O contrato JSON, isolado do domínio.

Os schemas são construídos A PARTIR dos objetos do domínio, nunca escritos à
mão em paralelo a eles — ver o teste anti-drift.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from orchestrator.domains.reconciliation.taxonomy import DivergenceType
from orchestrator.kernel.definition import Stage, WorkflowDefinition
from orchestrator.review.decision import Veredito


class ResolverJSON(BaseModel):
    name: str
    cost_class: str
    summary: str


class StageJSON(BaseModel):
    name: str
    cascade: list[ResolverJSON]


class WorkflowJSON(BaseModel):
    id: str
    name: str
    stages: list[StageJSON]


class WorkflowResumoJSON(BaseModel):
    id: str
    nome: str
    classes: list[str]
    gerado_em: str | None = None
    # "ESTE servidor consegue rodar isto?" — a tela desabilita o botão em vez
    # de deixar o usuário colher um 409.
    #
    # Era "a cascata não tem classe AGENTE", quando `/runs` recusava toda
    # cascata paga. Com o caminho pago aberto, uma cascata com agente roda onde
    # há `ANTHROPIC_API_KEY` e leva 409 onde não há — então a resposta passou a
    # depender da chave, e é `api/app.py::_tem_chave` que a dá, a MESMA leitura
    # que a rota usa para recusar. Duas leituras divergiriam, e o sintoma seria
    # a tela desabilitar um botão para uma execução que o servidor aceitaria.
    executavel: bool


class FonteSintetica(BaseModel):
    """O benchmark sintético, agora como UMA fonte entre outras.

    Os três campos eram o corpo inteiro de `RunRequest` — e era essa a forma
    de dizer "toda execução é um benchmark". Deixaram de ser o pedido e
    viraram os parâmetros de uma origem específica.
    """

    # `extra="forbid"` aqui também, e não só no `RunRequest` de fora: sem ele,
    # `{"tipo": "sintetica", "sede": 2}` dropa `sede` em silêncio e roda com o
    # default — a MESMA falha que a trava do `RunRequest` existe para impedir,
    # um nível abaixo dela.
    model_config = ConfigDict(extra="forbid")

    tipo: Literal["sintetica"] = "sintetica"
    seed: int = Field(default=1, ge=0)
    n: int = Field(default=300, ge=1, le=5000)
    taxa_divergencia: float = Field(default=0.15, ge=0.0, le=1.0)


class FonteArquivo(BaseModel):
    """Um arquivo do usuário — CSV ou JSON — como pool de trabalho.

    `kind` e `campo_id` são OBRIGATÓRIOS e não têm default, porque não existe
    coluna que diga o que um item é nem qual campo o identifica. Inferir do
    nome do arquivo ou da primeira coluna seria adivinhação, e o `kind` é o que
    liga um degrau ao outro no grafo.
    """

    # Mesma trava. Aqui os quatro campos são obrigatórios, então um typo já
    # levava 422 por ausência; o que ela fecha é o campo A MAIS — um
    # `"max_linhas": 10` que o cliente acha que está configurando um teto e que
    # hoje seria descartado sem uma palavra.
    model_config = ConfigDict(extra="forbid")

    tipo: Literal["arquivo"]
    caminho: str
    kind: str
    campo_id: str


class FontePostgres(BaseModel):
    """Uma query num Postgres do parceiro. `dsn_env` é o NOME da variável de
    ambiente do servidor que guarda o DSN — o valor nunca passa por aqui."""

    model_config = ConfigDict(extra="forbid")

    tipo: Literal["postgres"]
    dsn_env: str = Field(min_length=1)
    query: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    campo_id: str = Field(min_length=1)


class FonteHttp(BaseModel):
    """Uma página de uma API JSON. `token_env` é o NOME da variável com o
    token; `None` é uma API sem autenticação. `caminho` aponta a lista dentro
    do corpo (`dados.itens`); vazio = o corpo é a lista."""

    model_config = ConfigDict(extra="forbid")

    tipo: Literal["http"]
    url: str = Field(min_length=1)
    token_env: str | None = None
    kind: str = Field(min_length=1)
    campo_id: str = Field(min_length=1)
    caminho: str = ""


class RunRequest(BaseModel):
    """O pedido de execução.

    `fonte` com default mantém todo chamador de hoje funcionando sem edição: um
    corpo vazio continua sendo o benchmark sintético com os mesmos números.

    `extra="forbid"`: antes desta fatia, `seed`/`n`/`taxa_divergencia` eram o
    pedido inteiro. Sem essa trava, um cliente que ainda manda esse formato
    antigo teria os três campos silenciosamente ignorados (o comportamento
    padrão do Pydantic para campo desconhecido) e a execução cairia nos
    defaults de `FonteSintetica` — um run com parâmetros DIFERENTES dos
    pedidos, sem erro nenhum. Um 422 que nomeia o campo estranho é o que faz
    esse cliente descobrir que a forma mudou, em vez de descobrir que o
    número estava errado.
    """

    model_config = ConfigDict(extra="forbid")

    fonte: FonteSintetica | FonteArquivo | FontePostgres | FonteHttp = Field(
        default_factory=FonteSintetica, discriminator="tipo"
    )
    # Teto da EXECUÇÃO inteira, em micro-centavos. `None` = o teto do próprio
    # agente (`AgentSpec.budget_total_microcents`). NÃO existe valor que
    # signifique "sem teto", e a ausência dele é deliberada: um agente sem teto
    # é um agente que gasta até o fim da fila.
    teto_microcents: int | None = Field(default=None, ge=0)


class ResolverRunJSON(BaseModel):
    """O que um resolver da cascata fez, e a que custo.

    **`matches` conta RESOLUÇÕES; `rate` é ITENS sobre `RunJSON.itens`.** Os
    dois campos existem porque as duas unidades não são a mesma: uma resolução
    de pagamento agregado consome um bancário e três contábeis. `rate` sai de
    `Run.resolved_items_by_resolver`, que o motor acumula ao lado da contagem
    de resoluções exatamente para que ninguém volte a dividir uma pela outra —
    isso dava metade do número na conciliação e o número certo num domínio de
    um item por resolução, que é erro de unidade disfarçado de métrica.
    """

    name: str
    cost_class: str
    matches: int
    rate: float
    microcents: int


class GapJSON(BaseModel):
    items: int
    rate: float


class MedidoJSON(BaseModel):
    """O que só existe quando a fonte carrega gabarito.

    `seed`, `n` e `bank_total` moravam no topo de `RunJSON` porque só existia
    uma fonte. Num CSV de issues eles não têm valor certo nem valor neutro —
    têm ausência, e é isso que esta separação passa a expressar.
    """

    seed: int
    n: int
    bank_total: int
    deterministic_rate: float


class RunJSON(BaseModel):
    """O resultado de uma execução, em unidades do MOTOR.

    `itens`, `resolvidos`, `gap.items` e `por_resolver[].rate` estão todos na
    unidade ITEM, e é isso que faz `sum(por_resolver[].rate) + gap.rate` fechar
    em 1.0. `por_resolver[].matches` é a outra unidade — RESOLUÇÕES — e está
    lá por si, nunca como numerador de uma taxa.

    A soma fechar não é garantida pelo tipo: `gap` é CONTADO
    (`len(run.unresolved.items)`) e as taxas por resolver são AFIRMADAS pelos
    resolvers (`Resolution.item_ids`). Dois resolvers citando o mesmo item
    fariam a soma passar de 1.0. É o desenho certo: a lacuna, que é o número
    que o operador lê, nunca mente; a soma estourar é sintoma visível de um
    resolver que consome o que não recebeu. Há teste.
    """

    input_ref: str
    itens: int
    resolvidos: int
    por_resolver: list[ResolverRunJSON]
    gap: GapJSON
    custo_microcents: int
    # O ESTADO do run, de `RunState`. Já existia no `Run` e em `/api/runs`, e
    # não existia aqui: a resposta do POST — a que a tela lê — não dizia se o
    # run terminou, parou num teto ou está esperando gente.
    #
    # Um run que PAROU não pode ser lido como um que terminou, e num endpoint
    # que gasta essa diferença é o que decide se vale tentar de novo. Um pedido
    # com `teto_microcents: 0` sai como `limite_de_custo`, nunca `concluido`:
    # ler o desfecho não pode exigir que o chamador cruze dois campos e deduza.
    estado: str
    # As PROPOSTAS, contadas por tipo. Um agente nunca resolve — `Agent.resolve`
    # só preenche `proposals`, por construção —, então numa cascata só de agente
    # `resolvidos` é 0 e `gap.items` é o pool inteiro, e sem este campo a
    # resposta era indistinguível de uma execução que não fez nada.
    #
    # Por TIPO e não só o total, porque o total não separa as duas coisas que
    # mais importam saber de um agente: `{"BUG": 3}` é um agente que
    # classificou, `{"NAO_SEI": 3}` é um agente que absteve em tudo, e os dois
    # dão o mesmo `3`. Abstenção é resposta legítima — não saber é resposta —,
    # mas é uma resposta DIFERENTE, e num endpoint que cobra por ela a diferença
    # é o que decide se o dinheiro comprou alguma coisa.
    #
    # `sum(propostas_por_tipo.values())` é o total, e por isso ele não existe
    # como campo à parte: dois números para a mesma contagem são dois números
    # que podem divergir.
    propostas_por_tipo: dict[str, int]
    # Quantas dessas propostas terminaram em ERRO registrado no trace
    # (`TraceKind.ERRO`): falha na chamada ao modelo, teto desta requisição
    # incluído. CONTADAS, não inferidas.
    #
    # `falhas == 0` com `propostas > 0` significa que o modelo respondeu sobre
    # todos os itens — inclusive para dizer que não sabe, que é resposta e não
    # falha.
    falhas: int
    # O teto DESTA requisição recusou ao menos uma chamada. É o que separa
    # "paramos no teto" de "a API falhou", que sem ele são o mesmo `falhas > 0`:
    # os dois viram abstenção pela captura estreita de `agent/conversa.py`, com
    # o mesmo marcador e o mesmo texto.
    #
    # `False` numa cascata sem agente é MEDIDO: não havia chamada paga para
    # recusar.
    teto_atingido: bool
    # AUSENTE, não zero. Publicar `0.0` sobre uma fonte sem verdade seria dizer
    # "errou tudo" quando o certo é "não há com o que comparar".
    contra_gabarito: MedidoJSON | None = None


class RunResumoJSON(BaseModel):
    """Um run no histórico. O que a tela de runs (M11) precisa.

    Não carrega o pool pendente — só a contagem. Ver `storage/stored.py`: o
    `WorkSet` guarda payloads do domínio, que o storage não sabe serializar.
    """

    id: str
    workflow_id: str
    workflow_version: str
    state: str
    started_at: str
    finished_at: str | None
    duration_ms: int | None
    input_ref: str
    resolved: int
    proposed: int
    unresolved: int
    microcents: int


class LancamentoJSON(BaseModel):
    id: str
    lado: str  # "banco" ou "contabil"
    data: str
    valor: int  # centavos, sempre int
    descricao: str
    contraparte: str
    documento: str | None


class ItemFilaJSON(BaseModel):
    divergence_id: str
    tipo: str
    confianca: str
    explicacao: str
    evidencia: list[str]
    acao_sugerida: str
    conciliar_com: list[str]
    lancamentos: list[LancamentoJSON]
    decidido: bool = False
    veredito: str | None = None
    tipo_decidido: str | None = None
    autor: str | None = None
    # Verdadeiro quando o humano discordou do agente — é o sinal de treino do
    # §4.7 do spec pai, exposto sem máquina nova.
    divergiu: bool = False


class FilaJSON(BaseModel):
    workflow: str
    dataset: str
    itens: list[ItemFilaJSON]
    # A taxonomia vem da API, não hardcoded no JS. Duplicar os 14 valores no
    # front criaria drift silencioso no dia em que a taxonomia crescer — o
    # mesmo defeito que a fatia anterior existiu para tornar impossível.
    tipos: list[str]


class DecisaoRequest(BaseModel):
    veredito: Veredito
    tipo: DivergenceType | None = None
    conciliar_com: list[str] | None = None
    autor: str = Field(min_length=1)
    motivo: str = ""

    @field_validator("autor")
    @classmethod
    def _autor_nao_pode_ser_so_espaco(cls, v: str) -> str:
        """`min_length=1` sozinho deixa `"   "` passar: três espaços têm
        comprimento 3. O front faz `strip()` antes de enviar, mas o backend é
        quem decide o que entra na trilha de auditoria — um autor em branco
        ali é pior que a requisição recusada.
        """
        v = v.strip()
        if not v:
            raise ValueError("autor não pode ser vazio nem só espaço em branco")
        return v

    @model_validator(mode="after")
    def _corrigir_exige_tipo(self) -> "DecisaoRequest":
        """A mesma regra de `Decision.__post_init__`, expressa aqui para que
        o FastAPI devolva 422 antes do handler rodar — sem isso, o 404 de
        proposta ausente competia com o 422 de forma inválida pela ordem em
        que alguém lembrasse de checar cada um em `app.py`.
        """
        if self.veredito is Veredito.CORRIGIR and self.tipo is None:
            raise ValueError(
                "corrigir exige `tipo`: é o que o humano afirma no lugar do "
                "que o agente propôs"
            )
        return self


def stage_json(stage: Stage) -> StageJSON:
    return StageJSON(
        name=stage.name,
        cascade=[
            ResolverJSON(name=d.name, cost_class=d.cost_class.name, summary=d.summary)
            for d in (r.describe() for r in stage.ordered())
        ],
    )


def workflow_json(definicao: WorkflowDefinition) -> WorkflowJSON:
    return WorkflowJSON(
        id=definicao.id,
        name=definicao.name,
        stages=[stage_json(s) for s in definicao.stages],
    )


# ---------------------------------------------------------------------------
# Composição: o que o canvas de autoria precisa ver e enviar.
#
# A propriedade que faz este canvas ser seguro está do lado do servidor, não do
# desenho: a ORDEM da cascata não é um campo. Quem ordena é `Stage.ordered()`,
# por `CostClass`, e não existe entrada que a inverta. O canvas escolhe QUAIS
# resolvers entram; a ordem em que rodam é derivada.
#
# É a diferença entre uma tela que desenha um fluxo e uma tela que desenha o
# fluxo QUE VAI RODAR — o §3.5 chama a primeira de decoração e a nomeia como
# modo de falha.
# ---------------------------------------------------------------------------


# O que um parametro de regra pode valer, do lado do JSON. Espelha
# `ValorDeParametro` com `list` no lugar de `tuple`: JSON nao tem tupla, e
# fingir que tem faria o Pydantic recusar a propria resposta que ele serializou.
ValorJSON = int | str | list[str]


class ParametroJSON(BaseModel):
    nome: str
    default: ValorJSON
    descricao: str
    # A tela precisa saber a diferença entre "o default serve" e "sem isto o
    # bloco não existe". Sem o campo, um bloco genérico apareceria igual a um
    # já configurado e só recusaria ao compor.
    obrigatorio: bool = False


class ResolverReceitaJSON(BaseModel):
    nome: str
    parametros: dict[str, ValorJSON] = Field(default_factory=dict)


class ReceitaRequest(BaseModel):
    """Uma cascata composta na tela.

    Sem campo de ordem, de propósito — ver o comentário acima. E sem
    `gerado_em`: o relógio é do servidor, porque um timestamp vindo do cliente
    permitiria gravar uma receita "criada" antes de outra que a antecedeu.
    """

    id: str
    nome: str
    justificativa: str = ""
    resolvers: list[ResolverReceitaJSON] = Field(min_length=1)

    @field_validator("id")
    @classmethod
    def _id_valido(cls, v: str) -> str:
        from orchestrator.grill.receita import validar_id

        # A MESMA validação que o grill usa. Uma cópia aqui divergiria na
        # primeira mudança, e o sintoma seria uma receita aceita pela tela e
        # recusada pelo disco.
        validar_id(v)
        return v


class AmbienteJSON(BaseModel):
    """O ambiente da execução. Sem segredo nenhum dentro.

    `tem_chave` é booleano de propósito: a tela precisa saber se a entrevista
    vai funcionar, e não precisa — nunca — do valor. Um campo `chave: str` aqui
    seria a chave no JSON, no cache do navegador e no print da conversa.
    """

    modelo_padrao: str
    tem_chave: bool
    seed: int
    n: int
    n_max: int
    taxa_divergencia: float


# ---------------------------------------------------------------------------
# O catálogo: tudo que a plataforma sabe compor, sem agrupamento.
#
# Antes havia UMA lista de resolvers — a de conciliação — e a tela não tinha
# como oferecer outra coisa. A correção intermediária foi particionar por
# domínio e fazer a tela perguntar "que trabalho você quer orquestrar" antes de
# mostrar qualquer bloco; a partição foi embora junto com `Dominio`, porque
# quem recusa kinds que não conectam é o grafo, não o índice do catálogo.
# ---------------------------------------------------------------------------


class FerramentaJSON(BaseModel):
    nome: str
    descricao: str


class AgenteDeclaradoJSON(BaseModel):
    """Um agente como DADO. Tudo aqui é editável na tela.

    O que NÃO está aqui: `units`, `parse` e `abstain`. Eles deixaram de ser
    funções — viraram `kind`, `prompt`, `tipos` e `abstem_com`.
    """

    name: str
    system: str
    kind: str
    prompt: str
    tipos: list[str]
    abstem_com: str
    ferramentas: list[str]
    max_turns: int
    budget_microcents: int


class RegraJSON(BaseModel):
    """Um bloco determinístico. O que a tela ajusta são os PARÂMETROS.

    Sem `prompt`, sem `tipos`, sem ferramentas — uma regra não fala com modelo.
    A ausência desses campos no schema é o que impede a tela de oferecer edição
    que o construtor não aceita.
    """

    nome: str
    cost_class: str
    resumo: str
    parametros: list[ParametroJSON]
    # Como a paleta chama o bloco e em que seção o põe. Vem do catálogo, não de
    # uma tabela no front: um de-para lá seria a segunda fonte de verdade, e um
    # bloco novo entraria sem categoria ou com um rótulo velho.
    rotulo: str = ""
    categoria: str = "OTHER"


# ---------------------------------------------------------------------------
# Composição: o formato GERAL, que a `Receita` não sabia carregar.
#
# `ReceitaRequest.resolvers` é uma lista de NOMES do catálogo. Funciona enquanto
# tudo que se compõe já existe pronto — e um agente declarado NÃO existe pronto:
# ele nasce na composição, com prompt, vocabulário e ferramentas próprios.
#
# Por isso o bloco é uma UNIÃO DISCRIMINADA e não um dicionário com campos
# opcionais. Um `parametros: dict[str, int] | None` ao lado de um `prompt: str |
# None` aceitaria os quatro cruzamentos, dois dos quais não significam nada — e
# a recusa deles viraria código de validação escrito à mão. Com `tipo` como
# discriminador, o Pydantic recusa antes do handler rodar, e a mensagem nomeia
# qual dos dois formatos ele esperava.
# ---------------------------------------------------------------------------


class BlocoRegraJSON(BaseModel):
    tipo: Literal["regra"]
    nome: str
    parametros: dict[str, ValorJSON] = Field(default_factory=dict)


class BlocoAgenteJSON(BaseModel):
    tipo: Literal["agente"]
    declaracao: AgenteDeclaradoJSON


class BlocoCrewJSON(BaseModel):
    """Uma TRIPULAÇÃO: vários agentes sobre o mesmo item.

    Sem `abstem_com`: ele é DERIVADO dos agentes, que já o declaram cada um.
    Aceitá-lo aqui criaria a segunda fonte de verdade, e o sintoma seria o Crew
    chamando de desacordo duas abstenções — o caso em que ele deveria se calar.

    Sem `manager`/`synthesizer` ainda: `Crew.__post_init__` recusa
    `hierarchical` sem gerente e `sintetizar` sem sintetizador, com texto
    escrito para ser lido, e essa recusa atravessa como 422.
    """

    tipo: Literal["crew"]
    nome: str
    agentes: list[AgenteDeclaradoJSON] = Field(min_length=1)
    process: str = "sequential"
    conflito: str = "abster"
    budget_microcents: int = Field(default=20_000_000, ge=0)


BlocoJSON = Annotated[
    BlocoRegraJSON | BlocoAgenteJSON | BlocoCrewJSON, Field(discriminator="tipo")
]


class EtapaJSON(BaseModel):
    """Um degrau: os blocos que rodam sobre o mesmo pool.

    Dentro dele a ordem é por CUSTO (o motor ordena); entre degraus é por DADO
    (o kind que um produz é o que ativa o outro). Por isso não há campo de
    ordem DENTRO da etapa e há ordem ENTRE etapas — a lista é a sequência.
    """

    nome: str
    blocos: list[BlocoJSON] = Field(min_length=1)


class ComposicaoRequest(BaseModel):
    """Uma cascata composta na tela, a partir do catálogo.

    Sem campo de ordem, pelo mesmo motivo de `ReceitaRequest`: quem ordena é
    `Stage.ordered()`, por classe de custo. Sem `gerado_em`: o relógio é do
    servidor. Sem `version`: ela é derivada do conteúdo, e aceitá-la do cliente
    deixaria duas composições diferentes alegarem a mesma.
    """

    id: str
    nome: str
    justificativa: str = ""
    # `blocos` OU `etapas`, exatamente um — o mesmo açúcar de `Composicao`.
    # `blocos` continua valendo e é o que a tela manda para um degrau só;
    # `min_length` saiu dele porque agora a lista pode legitimamente vir vazia,
    # e quem cobra "pelo menos um bloco" é a composição, com a mensagem certa.
    blocos: list[BlocoJSON] = Field(default_factory=list)
    etapas: list[EtapaJSON] = Field(default_factory=list)
    # Os kinds que SÃO a saída deste workflow — o `Output` da tela. Sem eles, um
    # bloco que ramifica produz um kind que ninguém consome, e o kernel recusa
    # por beco sem saída. É declaração e não degrau: nada roda aqui.
    entrega: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id_valido(cls, v: str) -> str:
        from orchestrator.grill.receita import validar_id

        # A MESMA validação do disco, pelo mesmo motivo de `ReceitaRequest`: uma
        # cópia aqui divergiria, e o sintoma seria uma composição aceita pela
        # tela e recusada na gravação.
        validar_id(v)
        return v


class CatalogoJSON(BaseModel):
    """Tudo que dá para compor, sem agrupamento.

    Regra e agente NÃO vão na mesma lista: o que a tela edita em cada um é
    diferente, e uma lista só obrigaria a inspecionar o tipo em cada linha de
    render.
    """

    ferramentas: list[FerramentaJSON]
    regras: list[RegraJSON]
    agentes: list[AgenteDeclaradoJSON]


class ComposicaoResumoJSON(BaseModel):
    """Uma composição em disco.

    `blocos` traz os NOMES e não a contagem: "3 blocos" não distingue uma
    cascata que começa numa regra barata de uma que começa direto no modelo, e
    essa distinção é a tese do produto.
    """

    id: str
    nome: str
    version: str
    gerado_em: str
    blocos: list[str]
