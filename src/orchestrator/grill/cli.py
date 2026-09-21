"""`orchestrator-grill`: a entrevista no terminal.

Entrada separada, não subcomando de `orchestrator`: o `main()` de lá é argparse
plano e introduzir subcomandos quebraria a invocação de hoje sem ganho. Mesmo
padrão de `orchestrator-eval`.

A CLI PODE gastar dinheiro — a entrevista fala com um modelo de verdade. É a
API que não pode, e é por isso que o grill não ganhou rotas.

O benchmark do fim é a exceção dentro da exceção: ele NÃO roda o resolver
pago da receita proposta (ver `_medir`). Gastar por divergência investigada é
decisão do dono da conta, não efeito colateral de imprimir um percentual.
"""

import argparse
import sys
from pathlib import Path

from orchestrator.authoring.composicao import caminho as caminho_da_composicao
from orchestrator.authoring.composicao import construir_composicao, gravar
from orchestrator.domains.reconciliation import reconcile
from orchestrator.domains.reconciliation.synth.benchmark import build_benchmark
from orchestrator.grill.entrevistador import (
    Entrevistador,
    EntrevistaFalhou,
    Proposta,
    RecusaFinal,
)
from orchestrator.grill.registro import (
    gravar_recusa,
)
from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.definition import Stage, WorkflowDefinition
from orchestrator.metrics import evaluate

RESSALVA = "Este número é do NOSSO benchmark sintético, não dos seus dados."

# Limites de `--seed`, `--n` e `--taxa-divergencia`. São os MESMOS de
# `RunRequest` (api/schemas.py) de propósito: o último passo desta CLI imprime
# `?workflow=<id>` para o canvas, e um número medido aqui com parâmetros que a
# API recusa com 422 não poderia ser reproduzido lá.
_SEED_MIN = 0
_N_MIN, _N_MAX = 1, 5000
_TAXA_MIN, _TAXA_MAX = 0.0, 1.0

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
    if caminho_da_composicao(args.id, _RAIZ / "composicoes").exists():
        print(f"já existe uma composição com id {args.id!r}. escolha outro.", file=sys.stderr)
        return 2

    # Pelo MESMO motivo, e no mesmo lugar: `build_benchmark` já recusa `n < 1`
    # e taxa fora de [0, 1], mas só dentro de `_medir` — que roda DEPOIS da
    # entrevista inteira e DEPOIS de `gravar_receita`. Sem esta checagem aqui,
    # `--taxa-divergencia 1.5` conversa os doze turnos, grava a receita,
    # imprime os dois `✓` e então sobe um traceback cru na linha do benchmark:
    # o parceiro fica sem número, e o id já foi queimado — re-rodar bate em
    # "já existe uma receita". Config inválida falha alto e cedo, antes do
    # primeiro turno e antes de qualquer escrita.
    erro_de_parametro = _validar_parametros(args)
    if erro_de_parametro is not None:
        print(erro_de_parametro, file=sys.stderr)
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
    # `gravar` da COMPOSIÇÃO, e não `gravar_receita`: um entrevistador com duas
    # saídas seria o join frágil de sempre. A `Receita` continua carregando do
    # disco por `workflows._de_receita` — o que muda é o que se PRODUZ.
    caminho = gravar(resultado.composicao, _RAIZ / "composicoes")
    print(f"\n✓ {resultado.composicao.nome} ({resultado.composicao.id})")
    print(f"✓ {caminho}")
    _medir(resultado, args)
    print(f"→ http://localhost:8000/?workflow={args.id}")
    return 0


def _validar_parametros(args) -> str | None:
    """A mensagem de erro do primeiro parâmetro fora de faixa, ou `None`.

    Devolve em vez de imprimir para que `main` decida o destino e o código de
    saída num lugar só — e para que o teste possa asserir a mensagem sem
    capturar stream.
    """
    if args.seed < _SEED_MIN:
        return f"--seed precisa ser {_SEED_MIN} ou maior: {args.seed}"
    if not _N_MIN <= args.n <= _N_MAX:
        return f"--n precisa estar entre {_N_MIN} e {_N_MAX}: {args.n}"
    if not _TAXA_MIN <= args.taxa_divergencia <= _TAXA_MAX:
        return (
            f"--taxa-divergencia precisa estar entre {_TAXA_MIN} e {_TAXA_MAX}: "
            f"{args.taxa_divergencia}"
        )
    return None


def _medir(proposta: Proposta, args) -> None:
    dataset = build_benchmark(args.seed, args.n, args.taxa_divergencia)
    definicao = construir_composicao(proposta.composicao)

    # A cascata construída carrega os resolvers de verdade — inclusive um
    # `Investigator` ligado ao `ClienteAusente` que `construir` injeta por
    # default, porque esta chamada não passa `cliente=` nem `context=`.
    # Executá-lo aqui NÃO consulta modelo nenhum: `complete()` levanta, o
    # `except Exception` de `Investigator._uma` engole, e cada divergência
    # vira abstenção. O que aparecia na tela era `agente 0,0%` — que se lê
    # como "o agente tentou e não achou nada" quando a verdade é "o agente
    # nunca foi chamado". É exatamente o pecado que o §8.2 do spec existe
    # para impedir, cometido pela própria função que imprime a ressalva.
    #
    # Passar um cliente de verdade não é a correção: rodar o agente custa
    # dinheiro POR DIVERGÊNCIA, e gastar a conta do dono não é decisão desta
    # função. Então o resolver pago sai da medição e ganha uma linha que diz
    # que ele não foi consultado — a lacuna impressa é o que sobra para ele.
    pagos = [
        r.name
        for s in definicao.stages
        for r in s.cascade
        if r.cost_class is CostClass.AGENTE
    ]
    medida = WorkflowDefinition(
        id=definicao.id,
        name=definicao.name,
        stages=tuple(
            Stage(
                name=s.name,
                cascade=tuple(r for r in s.cascade if r.cost_class is not CostClass.AGENTE),
            )
            for s in definicao.stages
        ),
    )

    resultado = reconcile(dataset.bank, dataset.ledger, definition=medida)
    m = evaluate(dataset, resultado)

    total = m.bank_total
    # CONTAGEM DE RESOLUÇÕES sobre LANÇAMENTOS BANCÁRIOS, e isto está certo —
    # não é o erro de unidade que a API tinha. Aqui o denominador é o lado
    # bancário, e toda resolução da conciliação carrega exatamente um id
    # bancário, então a razão é de fato "que fração do extrato esta regra
    # fechou". A suposição é real e não é garantida pelo tipo; ela está dita
    # aqui para que ninguém "conserte" isto para
    # `run.resolved_items_by_resolver`, que conta os DOIS lados e daria o
    # dobro contra este denominador.
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
    for nome in pagos:
        print(
            f"  {nome} não foi consultado neste benchmark: cada divergência "
            f"investigada custa dinheiro de verdade, e essa decisão é sua. "
            f"A lacuna acima é o que sobrou para ele."
        )


if __name__ == "__main__":
    raise SystemExit(main())
