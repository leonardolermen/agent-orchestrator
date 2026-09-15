"""As três ferramentas. Todo turno do modelo termina em exatamente uma.

`perguntar` é FERRAMENTA, e não texto livre, de propósito: se a pergunta fosse
prosa solta, "isto é uma pergunta ou o modelo pensando alto?" viraria
heurística, e um turno em que ele apenas comenta travaria o laço esperando
resposta a nada. Como ferramenta, o fim da entrevista é evento tipado.
"""

from dataclasses import dataclass
from typing import Any

from orchestrator.agent.llm import ToolCall
from orchestrator.grill.catalogo import CATALOGO
from orchestrator.grill.receita import ResolverReceita

NOMES = ("perguntar", "propor_workflow", "fora_do_catalogo")


@dataclass(frozen=True)
class Pergunta:
    texto: str


@dataclass(frozen=True)
class PropostaBruta:
    """Ainda não é `Receita`: falta o id (que vem da CLI) e a validação por
    construção (que é da Task 2)."""

    nome: str
    justificativa: str
    resolvers: tuple[ResolverReceita, ...]


@dataclass(frozen=True)
class Recusa:
    motivo: str
    o_que_faltaria: str


def _catalogo_em_texto() -> str:
    linhas = []
    for chave in sorted(CATALOGO):
        e = CATALOGO[chave]
        if e.parametros:
            params = "; ".join(
                f"{p.nome} (int, default {p.default}) — {p.descricao}" for p in e.parametros
            )
        else:
            params = "sem parâmetros"
        linhas.append(f"- {e.nome} [{e.cost_class.name}]: {e.resumo}. Parâmetros: {params}")
    return "\n".join(linhas)


def esquemas() -> list[dict[str, Any]]:
    return [
        {
            "name": "perguntar",
            "description": "Faz UMA pergunta ao parceiro e espera a resposta.",
            "input_schema": {
                "type": "object",
                "properties": {"texto": {"type": "string"}},
                "required": ["texto"],
            },
        },
        {
            "name": "propor_workflow",
            "description": (
                "Encerra a entrevista propondo a cascata. Resolvers disponíveis:\n"
                + _catalogo_em_texto()
                + "\n\nOmita um parâmetro para usar o default. Todo parâmetro é "
                "inteiro. Não repita um resolver na mesma cascata."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "nome": {
                        "type": "string",
                        "description": "rótulo legível, ex.: 'Conciliação Acme'",
                    },
                    "justificativa": {
                        "type": "string",
                        "description": "por que esta cascata resolve o caso descrito",
                    },
                    "resolvers": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                # Do catálogo, nunca literal: ver o teste que trava isto.
                                "nome": {"type": "string", "enum": sorted(CATALOGO)},
                                "parametros": {"type": "object"},
                            },
                            "required": ["nome"],
                        },
                    },
                },
                "required": ["nome", "justificativa", "resolvers"],
            },
        },
        {
            "name": "fora_do_catalogo",
            "description": (
                "Encerra a entrevista declarando que o caso não cabe no catálogo. "
                "Desfecho legítimo, não erro."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "motivo": {"type": "string"},
                    "o_que_faltaria": {
                        "type": "string",
                        "description": "que resolver precisaria existir",
                    },
                },
                "required": ["motivo", "o_que_faltaria"],
            },
        },
    ]


def _texto(args: dict[str, Any], chave: str) -> str:
    valor = args.get(chave)
    if not isinstance(valor, str):
        raise ValueError(f"argumento {chave!r} ausente ou não é texto")
    if not valor.strip():
        raise ValueError(f"argumento {chave!r} veio vazio")
    return valor


def interpretar(chamada: ToolCall) -> Pergunta | PropostaBruta | Recusa:
    args = chamada.arguments
    if chamada.name == "perguntar":
        return Pergunta(texto=_texto(args, "texto"))
    if chamada.name == "fora_do_catalogo":
        return Recusa(
            motivo=_texto(args, "motivo"),
            o_que_faltaria=_texto(args, "o_que_faltaria"),
        )
    if chamada.name == "propor_workflow":
        brutos = args.get("resolvers")
        if not isinstance(brutos, list) or not brutos:
            raise ValueError("argumento 'resolvers' ausente ou vazio")
        resolvers = []
        for item in brutos:
            if not isinstance(item, dict) or not isinstance(item.get("nome"), str):
                raise ValueError(f"item de 'resolvers' malformado: {item!r}")
            params = item.get("parametros") or {}
            if not isinstance(params, dict):
                raise ValueError(f"'parametros' de {item['nome']!r} não é objeto")
            limpos: dict[str, int] = {}
            for k, v in params.items():
                # `isinstance(True, int)` é True em Python: bool precisa de
                # exclusão explícita, senão `max_cents=true` viraria 1.
                if isinstance(v, bool) or not isinstance(v, int):
                    raise ValueError(
                        f"parâmetro {k!r} de {item['nome']!r} precisa ser inteiro, "
                        f"veio {v!r}"
                    )
                limpos[k] = v
            resolvers.append(ResolverReceita(nome=item["nome"], parametros=limpos))
        return PropostaBruta(
            nome=_texto(args, "nome"),
            justificativa=_texto(args, "justificativa"),
            resolvers=tuple(resolvers),
        )
    raise ValueError(f"ferramenta desconhecida: {chamada.name!r}. use uma de {list(NOMES)}")
