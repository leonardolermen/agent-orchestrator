"""Os subcomandos. Um por função, todos lendo a mesma `Config`.

Nenhum deles gasta dinheiro. O único que pode é `bench` — e ele roda a cascata
SEM agente, a mesma que a API serve, pela mesma razão: não existe caminho de
código daqui até o modelo. Comparar modelos continua sendo `orchestrator-eval`,
que anuncia "GASTA DINHEIRO" no cabeçalho.
"""

import sys
from argparse import Namespace

from orchestrator.cli.config import carregar
from orchestrator.observability.render import render
from orchestrator.storage.jsonl.run_store import JsonlRunStore
from orchestrator.storage.jsonl.trace_store import JsonlTraceStore


def _config():
    return carregar()


def version(args: Namespace) -> int:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _v

    try:
        print(_v("orchestrator"))
    except PackageNotFoundError:
        # Rodando do source sem instalar. Dizer isso é mais útil que estourar.
        print("0.1.0 (não instalado; rodando do source)")
    return 0


def bench(args: Namespace) -> int:
    """O benchmark do conciliador. Mesma saída da invocação legada.

    Delega para o `main` antigo em vez de reimplementar: a linha que o CI faz
    `grep` sai de UM lugar, e duas formatações que precisam concordar seriam o
    join frágil de sempre.
    """
    from orchestrator.cli.conciliador import main as legado

    return legado(
        [
            "--seed",
            str(args.seed),
            "--n",
            str(args.n),
            "--taxa-divergencia",
            str(args.taxa_divergencia),
        ]
    )


def runs(args: Namespace) -> int:
    cfg = _config()
    achados = JsonlRunStore(cfg.raiz_dados / "runs.jsonl").list(limit=args.limit)
    if not achados:
        print(
            f"nenhum run em {cfg.raiz_dados / 'runs.jsonl'}.\n"
            f"rode `orchestrator bench` ou a API para produzir um.",
            file=sys.stderr,
        )
        return 1
    print(f"{'run':<24} {'workflow':<16} {'estado':<20} {'dur':>7} {'custo US$':>10}")
    for s in achados:
        custo = sum(
            c.microcents(cfg.model) if c.calls else 0
            for c in s.cost_by_resolver.values()
        )
        dur = f"{s.duration_ms}ms" if s.duration_ms is not None else "—"
        print(
            f"{s.id:<24} {s.workflow_id:<16} {s.state.value:<20} {dur:>7} "
            f"{custo / 100_000_000:>10.4f}"
        )
    return 0


def trace(args: Namespace) -> int:
    cfg = _config()
    if not args.run_id:
        return runs(Namespace(limit=20))
    achado = JsonlTraceStore(cfg.raiz_dados).get(args.run_id)
    if achado is None:
        print(f"sem trace para o run {args.run_id!r}.", file=sys.stderr)
        return 1
    print(render(achado, model=cfg.model, max_itens=args.max_itens))
    return 0


def workflows(args: Namespace) -> int:
    """Lista ou descreve. A cascata sai da DEFINIÇÃO, não de uma descrição
    paralela — `kernel/definition.py` declara que não existe "definição servida"
    separada da "definição executada", e isto aqui é mais um consumidor da
    mesma."""
    from orchestrator.workflows import descrever

    cfg = _config()
    achados = dict(descrever(cfg.raiz_receitas))
    if not args.workflow_id:
        print(f"{'id':<20} {'versão':<14} {'classes'}")
        for wid, definicao in achados.items():
            classes = sorted(
                {r.cost_class.name for s in definicao.stages for r in s.cascade}
            )
            print(f"{wid:<20} {definicao.version:<14} {', '.join(classes)}")
        return 0

    definicao = achados.get(args.workflow_id)
    if definicao is None:
        print(
            f"workflow desconhecido: {args.workflow_id!r}. "
            f"disponíveis: {sorted(achados)}",
            file=sys.stderr,
        )
        return 1
    print(f"{definicao.name}  ({definicao.id}@{definicao.version})")
    for stage in definicao.stages:
        print(f"\n  {stage.name}")
        # `ordered()`, não `cascade`: a ordem que aparece é a ordem que RODA.
        # Mostrar a ordem autoral seria desenhar uma coisa e executar outra —
        # a decoração que o §3.5 do spec de composição nomeia como modo de falha.
        for r in stage.ordered():
            d = r.describe()
            print(f"    {d.cost_class.name:<8} {d.name:<16} {d.summary}")
    return 0


def init(args: Namespace) -> int:
    from orchestrator.cli.scaffold import criar

    try:
        raiz = criar(args.nome)
    except FileExistsError as erro:
        print(str(erro), file=sys.stderr)
        return 2
    print(f"projeto criado em {raiz}\n")
    print("  cd", raiz.name)
    print("  python -m pip install -e .")
    print("  python -m workflows.triagem")
    return 0


def avaliar(args: Namespace) -> int:
    """`orchestrator eval <dominio>` — a avaliação ao vivo. GASTA DINHEIRO.

    Subcomando separado do `bench` de propósito. `bench` é determinístico,
    gratuito e roda no CI a cada push; este chama modelo e cobra. Um único
    comando com uma flag `--ao-vivo` faria a diferença entre os dois caber num
    caractere esquecido, e a diferença é dinheiro.
    """
    if args.dominio != "swe":
        print(
            f"domínio sem avaliação ao vivo: {args.dominio!r}. disponíveis: swe",
            file=sys.stderr,
        )
        return 1

    from orchestrator.agent.anthropic_client import AnthropicClient
    from orchestrator.cli.execucao import avaliar as executar
    from orchestrator.domains.swe import avaliacao

    cliente = AnthropicClient(model=args.model)
    dataset = avaliacao.conjunto()
    print(
        f"Avaliação ao vivo de {args.dominio!r} com {args.model} — GASTA "
        f"DINHEIRO. Dois braços ({args.bracos}) sobre {len(dataset)} casos "
        f"curados."
    )
    print()
    montar = (
        avaliacao.bracos_tripulacao
        if args.bracos == "tripulacao"
        else avaliacao.bracos
    )
    resultado, economias = executar(
        dataset,
        montar(cliente),
        cliente,
        abstem_com=avaliacao.ABSTEM_COM,
    )
    print(avaliacao.render(resultado, economias))
    return 0
