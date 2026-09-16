"""A árvore de uma execução, em texto.

É a tela do §13.1 do spec de migração, e a saída de `orchestrator-trace`. O
mesmo `Trace` alimenta o dashboard (M10) — quem desenha muda, o que é desenhado
não.

Nenhum número é inventado aqui. Se um span não tem custo, a coluna sai vazia em
vez de `US$ 0,0000` — a mesma disciplina do canvas, que diz "não medido" em vez
de zero, e de `EvalResult.custo_medido`, que existe para não relatar ausência de
medição como medição.
"""

from orchestrator.kernel.cost import Cost
from orchestrator.kernel.trace import Span, SpanKind, SpanStatus, Trace

_MARCA = {
    SpanStatus.OK: "",
    SpanStatus.ERRO: " ✗",
    SpanStatus.ABSTENCAO: " ~",
    SpanStatus.PULADO: " ·",
}


def _custo(span: Span, model: str) -> str:
    if span.cost == Cost.zero():
        return ""
    return f"US$ {span.cost.microcents(model) / 100_000_000:.4f}"


def _tempo(span: Span) -> str:
    if not span.duration_ms:
        return ""
    if span.duration_ms < 1000:
        return f"{span.duration_ms}ms"
    return f"{span.duration_ms / 1000:.1f}s"


def _detalhe(span: Span) -> str:
    a = span.attributes
    if span.kind is SpanKind.POLICY:
        return f"{a.get('rota', '')}: {a.get('motivo', '')}"
    if span.kind is SpanKind.RESOLVER:
        partes = [f"{a.get('cost_class', '')}"]
        if a.get("resolveu"):
            partes.append(f"resolveu {a['resolveu']}")
        if a.get("propos"):
            partes.append(f"propôs {a['propos']}")
        return "  ".join(p for p in partes if p)
    if span.kind is SpanKind.ITEM and a.get("tipo"):
        return f"{a['tipo']}  confiança={a.get('confianca', '?')}"
    if span.kind is SpanKind.ITEM and a.get("motivo"):
        return str(a["motivo"])
    if span.kind is SpanKind.LLM:
        return f"in {span.cost.input_tokens} out {span.cost.output_tokens}"
    if span.kind is SpanKind.TOOL:
        return span.error or ""
    if span.kind is SpanKind.GAP:
        return f"{a.get('itens', 0)} itens sem resolução"
    if span.kind is SpanKind.RUN:
        return f"{a.get('estado', '')}"
    return ""


def render(trace: Trace, model: str = "claude-opus-5", max_itens: int = 5) -> str:
    """A árvore inteira, com custo e latência em cada nível.

    `max_itens` limita os filhos de um resolver: um run de 300 divergências
    produziria 300 subárvores e a saída deixaria de ser legível — que é o
    oposto do que um trace serve. O corte é declarado na saída ("... e mais N"),
    nunca silencioso.
    """
    raiz = trace.raiz()
    if raiz is None:
        return "(trace vazio)"
    linhas: list[str] = []
    _desenhar(trace, raiz, "", True, linhas, model, max_itens)
    total = trace.custo_total(model)
    linhas.append("")
    linhas.append(f"custo total: US$ {total / 100_000_000:.4f}")
    return "\n".join(linhas)


def _desenhar(trace, span, prefixo, ultimo, linhas, model, max_itens):
    conector = "" if not prefixo and span.parent_id is None else ("└── " if ultimo else "├── ")
    rotulo = f"{span.kind.value:<9}{span.name}{_MARCA[span.status]}"
    colunas = "  ".join(c for c in (_tempo(span), _custo(span, model)) if c)
    detalhe = _detalhe(span)
    linha = f"{prefixo}{conector}{rotulo}"
    if colunas or detalhe:
        linha = f"{linha:<52} {colunas:<20} {detalhe}".rstrip()
    linhas.append(linha)

    filhos = list(trace.filhos(span.id))
    # Itens são cortados; resolver, política e lacuna nunca — são poucos e são
    # o esqueleto da árvore.
    itens = [f for f in filhos if f.kind is SpanKind.ITEM and f.parent_id == span.id]
    if len(itens) > max_itens:
        cortados = len(itens) - max_itens
        filhos = [f for f in filhos if f not in itens[max_itens:]]
    else:
        cortados = 0

    novo_prefixo = prefixo + ("" if span.parent_id is None else ("    " if ultimo else "│   "))
    for i, filho in enumerate(filhos):
        _desenhar(
            trace,
            filho,
            novo_prefixo,
            i == len(filhos) - 1 and not cortados,
            linhas,
            model,
            max_itens,
        )
    if cortados:
        linhas.append(f"{novo_prefixo}└── ... e mais {cortados} itens")
