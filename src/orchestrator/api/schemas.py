"""O contrato JSON, isolado do domínio.

Os schemas são construídos A PARTIR dos objetos do domínio, nunca escritos à
mão em paralelo a eles — ver o teste anti-drift.
"""

from pydantic import BaseModel, Field, field_validator, model_validator

from orchestrator.review.decision import Veredito
from orchestrator.taxonomy import DivergenceType
from orchestrator.workflow.definition import Stage, WorkflowDefinition


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
