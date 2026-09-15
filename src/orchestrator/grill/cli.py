"""`orchestrator-grill`: a entrevista no terminal.

Entrada separada, não subcomando de `orchestrator`: o `main()` de lá é argparse
plano e introduzir subcomandos quebraria a invocação de hoje sem ganho. Mesmo
padrão de `orchestrator-eval`.

A CLI PODE gastar dinheiro — é onde o investigador já roda. É a API que não
pode, e é por isso que o grill não ganhou rotas.
"""

import argparse
import sys
from pathlib import Path

from orchestrator.cli import build_benchmark
from orchestrator.grill.entrevistador import (
    Entrevistador,
    EntrevistaFalhou,
    Proposta,
    RecusaFinal,
)
from orchestrator.grill.receita import construir
from orchestrator.grill.registro import (
    caminho_da_receita,
    gravar_receita,
    gravar_recusa,
)
from orchestrator.matching.engine import reconcile
from orchestrator.metrics import evaluate

RESSALVA = "Este número é do NOSSO benchmark sintético, não dos seus dados."

# Atributo de módulo para o teste trocar por tmp_path sem escrever no
# repositório do desenvolvedor.
_RAIZ: Path | None = None


def _construir_entrevistador() -> Entrevistador:
    from orchestrator.grill.assinatura import ClienteAssinatura

    return Entrevistador(client=ClienteAssinatura())


def main(argv=None, *, entrevistador=None, responder=None) -> int:
    parser = argparse.ArgumentParser(
        description="Entrevista o parceiro e propõe uma cascata de conciliação"
    )
    parser.add_argument("--id", required=True, help="id do workflow, ex.: acme")
    fonte = parser.add_mutually_exclusive_group(required=True)
    fonte.add_argument("--descricao")
    fonte.add_argument("--descricao-arquivo")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--n", type=int, default=500)
    parser.add_argument("--taxa-divergencia", type=float, default=0.15)
    args = parser.parse_args(argv)

    # Colisão checada ANTES do primeiro turno: descobrir no fim desperdiçaria
    # a conversa inteira do parceiro.
    if caminho_da_receita(args.id, _RAIZ).exists():
        print(f"já existe uma receita com id {args.id!r}. escolha outro.", file=sys.stderr)
        return 2

    descricao = (
        args.descricao
        if args.descricao is not None
        else Path(args.descricao_arquivo).read_text(encoding="utf-8")
    )
    ent = entrevistador if entrevistador is not None else _construir_entrevistador()
    resp = responder if responder is not None else input

    try:
        resultado = ent.entrevistar(args.id, descricao, resp)
    except ValueError as erro:
        print(str(erro), file=sys.stderr)
        return 2
    except EntrevistaFalhou as erro:
        print(f"a entrevista não chegou a um desfecho: {erro}", file=sys.stderr)
        print("\n--- transcrição ---")
        for linha in erro.transcricao:
            print(linha)
        return 1

    if isinstance(resultado, RecusaFinal):
        caminho = gravar_recusa(args.id, resultado, _RAIZ)
        print(f"\nfora do catálogo: {resultado.motivo}")
        print(f"o que faltaria: {resultado.o_que_faltaria}")
        print(f"registrado em {caminho}")
        return 0

    assert isinstance(resultado, Proposta)
    caminho = gravar_receita(resultado.receita, _RAIZ)
    print(f"\n✓ {resultado.receita.nome} ({resultado.receita.id})")
    print(f"✓ {caminho}")
    _medir(resultado, args)
    print(f"→ http://localhost:8000/?workflow={args.id}")
    return 0


def _medir(proposta: Proposta, args) -> None:
    dataset = build_benchmark(args.seed, args.n, args.taxa_divergencia)
    definicao = construir(proposta.receita)
    resultado = reconcile(dataset.bank, dataset.ledger, definition=definicao)
    m = evaluate(dataset, resultado)

    total = m.bank_total
    partes = " · ".join(
        f"{nome} {(resultado.matches_by_resolver.get(nome, 0) / total if total else 0):.1%}"
        for nome in resultado.matches_by_resolver
    )
    lacuna = (total - m.bank_matched_total) / total if total else 0.0
    print(
        f"✓ benchmark (semente {args.seed}, n={args.n}): "
        f"{m.deterministic_rate:.1%} — {partes} · lacuna {lacuna:.1%}"
    )
    # Requisito, não rodapé: ver §8.2 do spec e o teste que o trava.
    print(f"  {RESSALVA}")


if __name__ == "__main__":
    raise SystemExit(main())
