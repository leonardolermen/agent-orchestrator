"""Ida e volta JSON de `Proposal` e `Decision`.

Mesmo idioma de `eval/replay.py`: campo a campo, explícito, sem mágica de
introspecção. Enum vira `.value`, `datetime` vira ISO-8601, `frozenset` vira
lista ORDENADA — o arquivo é append-only e precisa ser diffável.
"""

from datetime import datetime
from typing import Any

from orchestrator.kernel.cost import Cost
from orchestrator.kernel.resolution import Confidence, Proposal, TraceEvent, TraceKind
from orchestrator.review.decision import Decision, Veredito


def proposta_para_dict(p: Proposal) -> dict[str, Any]:
    return {
        "divergence_id": p.item_id,
        "tipo": p.tipo,
        "explicacao": p.explicacao,
        "evidencia": list(p.evidencia),
        "confianca": p.confianca.value,
        "acao_sugerida": p.acao_sugerida,
        "cost": {
            "input_tokens": p.cost.input_tokens,
            "output_tokens": p.cost.output_tokens,
            "cached_tokens": p.cost.cached_tokens,
            # Os cinco campos de Cost, como em replay.py: perder um faz a fila
            # reportar custo menor que o real.
            "cache_creation_tokens": p.cost.cache_creation_tokens,
            "calls": p.cost.calls,
        },
        "trace": [{"kind": e.kind.value, "detail": e.detail} for e in p.trace],
    }


def proposta_de_dict(d: dict[str, Any]) -> Proposal:
    return Proposal(
        item_id=d["divergence_id"],
        # `Proposal.tipo` é `str` desde o PR #6 — validar contra a taxonomia de
        # conciliação aqui só reinstalava, na serialização, o acoplamento que a
        # generalização tirou do tipo. Quem sabe quais valores valem é o
        # domínio que escreveu a proposta.
        tipo=d["tipo"],
        explicacao=d["explicacao"],
        evidencia=list(d["evidencia"]),
        confianca=Confidence(d["confianca"]),
        acao_sugerida=d["acao_sugerida"],
        cost=Cost(**d["cost"]),
        trace=[
            TraceEvent(kind=TraceKind(e["kind"]), detail=e["detail"])
            for e in d["trace"]
        ],
    )


def decisao_para_dict(d: Decision) -> dict[str, Any]:
    return {
        "divergence_id": d.divergence_id,
        "veredito": d.veredito.value,
        "tipo": d.tipo,
        # Ordenado: o JSONL é append-only e revisado por humano em diff.
        "conciliar_com": sorted(d.conciliar_com),
        "autor": d.autor,
        "quando": d.quando.isoformat(),
        "motivo": d.motivo,
    }


def decisao_de_dict(d: dict[str, Any]) -> Decision:
    return Decision(
        divergence_id=d["divergence_id"],
        veredito=Veredito(d["veredito"]),
        tipo=d["tipo"],
        conciliar_com=frozenset(d["conciliar_com"]),
        autor=d["autor"],
        quando=datetime.fromisoformat(d["quando"]),
        motivo=d["motivo"],
    )
