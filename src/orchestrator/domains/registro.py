"""Os domínios que a plataforma conhece.

**O que muda aqui.** Até este módulo, "o que dá para compor" era o `CATALOGO` do
grill — cinco resolvers de conciliação. A pergunta do dono foi direta: *"por que
só tem blocos de conciliação? eu quero uma plataforma geral."* Estava certo, e
havia seis resolvers escritos que o canvas não oferecia.

**A forma da generalidade, e por que ela não é uma lista maior.** Um domínio
declara três coisas:

    kinds        — que tipos de `WorkItem` ele trabalha
    ferramentas  — o CATÁLOGO delas (sem dados; `com_contexto` liga na execução)
    agentes      — declarações, que `construir_agente` valida construindo

E uma coisa que ele NÃO declara aqui: as regras determinísticas. Casar por
documento e valor é lógica de domínio — não há declaração que a substitua, e
fingir que há produziria uma linguagem de regras pela metade. Regra é código, e
entra na cascata pelo módulo do próprio domínio.

**Por que domínios não se misturam.** `L1` trabalha `kind="lancamento"`,
`FornecedorPreferido` trabalha `"requisicao"`, o triador trabalha `"issue"`. Uma
cascata com resolvers de dois domínios não é ruim — é vazia de sentido, porque o
segundo roda sobre um pool que o primeiro nem enxerga. `Dominio.kinds` é o que
torna isso verificável em vez de convenção.
"""

from orchestrator.agent.declarado import AgenteDeclarado, Dominio
from orchestrator.agent.tools.registry import ToolRegistry
from orchestrator.conciliacao.ferramentas import catalogo_de_ferramentas
from orchestrator.domains.swe.workflow import ISSUE, PROMPT
from orchestrator.domains.swe.workflow import ferramentas as ferramentas_swe

# --------------------------------------------------------------------------
# Conciliação — a implementação de referência (§1.3)
# --------------------------------------------------------------------------

_PROMPT_INVESTIGADOR = """Você investiga divergências de conciliação bancária.

Responda APENAS com um objeto JSON:
{"tipo": <um dos tipos>, "explicacao": <texto curto>,
 "evidencia": [<strings>], "confianca": "ALTA"|"MEDIA"|"BAIXA"}

Use as ferramentas para buscar o que falta. Não saber é resposta válida:
responda NAO_IDENTIFICADO com confiança BAIXA."""

CONCILIACAO = Dominio(
    id="conciliacao",
    nome="Conciliação bancária",
    kinds=("lancamento",),
    ferramentas=catalogo_de_ferramentas(),
    agentes=(
        AgenteDeclarado(
            name="investigador",
            system=_PROMPT_INVESTIGADOR,
            kind="lancamento",
            prompt="Divergência {id}: {descricao}",
            tipos=(
                "DEFASAGEM_TEMPORAL",
                "DEVOLUCAO_FUNDOS",
                "PAGAMENTO_AGREGADO",
                "RETENCAO_IMPOSTO",
            ),
            abstem_com="NAO_IDENTIFICADO",
            ferramentas=catalogo_de_ferramentas().names(),
            max_turns=6,
        ),
    ),
)

# --------------------------------------------------------------------------
# Engenharia de software
# --------------------------------------------------------------------------

SWE = Dominio(
    id="swe",
    nome="Triagem de issues",
    kinds=(ISSUE,),
    ferramentas=ferramentas_swe(),
    agentes=(
        AgenteDeclarado(
            name="triador",
            system=PROMPT,
            kind=ISSUE,
            prompt="{titulo}\n\n{corpo}",
            # `NAO_SEI` fora de `tipos`: `DUVIDA` é um TIPO legítimo ("esta
            # issue é uma pergunta"), e confundir os dois custou 16 de 50 casos
            # fora do denominador da precisão (P6.86).
            tipos=("BUG", "FEATURE", "DUVIDA"),
            abstem_com="NAO_SEI",
            ferramentas=("contar_palavras",),
            max_turns=3,
        ),
    ),
)

# --------------------------------------------------------------------------
# Compras
# --------------------------------------------------------------------------

_PROMPT_COMPRADOR = """Você procura fornecedor para uma requisição de compra.

Responda APENAS com um objeto JSON:
{"tipo": "FORNECEDOR_NOVO"|"REQUISICAO_INVIABIL"|"NAO_SEI",
 "explicacao": <texto curto>, "evidencia": [<strings>],
 "confianca": "ALTA"|"MEDIA"|"BAIXA"}

Não saber é resposta válida: responda NAO_SEI com confiança BAIXA."""

PROCUREMENT = Dominio(
    id="procurement",
    nome="Compras",
    kinds=("requisicao", "fornecedor"),
    # Sem ferramentas ainda: o domínio é esqueleto, e um registro vazio DIZ
    # isso. Inventar ferramentas para preencher a tela seria pior que a lacuna.
    ferramentas=ToolRegistry(contexto=None),
    agentes=(
        AgenteDeclarado(
            name="buscador",
            system=_PROMPT_COMPRADOR,
            kind="requisicao",
            prompt="Requisição de {quantidade}x {item}",
            tipos=("FORNECEDOR_NOVO", "REQUISICAO_INVIABIL"),
            abstem_com="NAO_SEI",
            max_turns=3,
        ),
    ),
)


DOMINIOS: dict[str, Dominio] = {d.id: d for d in (CONCILIACAO, SWE, PROCUREMENT)}


def dominio(id: str) -> Dominio:
    if id not in DOMINIOS:
        raise KeyError(f"domínio desconhecido: {id!r}. disponíveis: {sorted(DOMINIOS)}")
    return DOMINIOS[id]
