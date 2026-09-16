"""O contrato JSON, isolado do domínio.

Os schemas são construídos A PARTIR dos objetos do domínio, nunca escritos à
mão em paralelo a eles — ver o teste anti-drift.
"""

from pydantic import BaseModel, Field, field_validator, model_validator

from orchestrator.kernel.definition import Stage, WorkflowDefinition
from orchestrator.review.decision import Veredito
from orchestrator.taxonomy import DivergenceType


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
    # Falso quando a cascata tem classe AGENTE: a tela desabilita o botão em
    # vez de deixar o usuário colher um 409.
    executavel: bool


class RunRequest(BaseModel):
    """O pedido de execução do benchmark sintético.

    Os limites de `Field` são o que faz o FastAPI devolver 422 sozinho para
    uma `taxa_divergencia` fora de [0, 1] — em vez de deixar `build_benchmark`
    levantar `ValueError` e a rota devolver 500.
    """

    seed: int = Field(default=1, ge=0)
    n: int = Field(default=300, ge=1, le=5000)
    taxa_divergencia: float = Field(default=0.15, ge=0.0, le=1.0)


class ResolverRunJSON(BaseModel):
    name: str
    cost_class: str
    matches: int
    rate: float
    microcents: int


class GapJSON(BaseModel):
    items: int
    rate: float


class RunJSON(BaseModel):
    seed: int
    n: int
    bank_total: int
    deterministic_rate: float
    by_resolver: list[ResolverRunJSON]
    gap: GapJSON


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


class ParametroJSON(BaseModel):
    nome: str
    default: int
    descricao: str


class EntradaCatalogoJSON(BaseModel):
    nome: str
    cost_class: str
    resumo: str
    parametros: list[ParametroJSON]
    ferramentas: list[str] = Field(default_factory=list)
    # `None` para resolver determinístico. A tela usa a AUSÊNCIA para não
    # desenhar uma linha de modelo onde não há modelo — dizer "modelo: —" num
    # resolver de regra sugeriria que houve uma escolha.
    modelo_padrao: str | None = None


class ResolverReceitaJSON(BaseModel):
    nome: str
    parametros: dict[str, int] = Field(default_factory=dict)


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
