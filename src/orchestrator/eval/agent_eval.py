"""Avaliação ao vivo do investigador contra o gabarito sintético.

A terceira e última camada de teste: a única que gasta dinheiro e a única que
diz se o produto presta. Roda modelos diferentes contra o MESMO gabarito, que é
o que transforma escolha de modelo em medição.

O gabarito não precisou ser construído para isto — ele já existe desde a plano 1.
"""

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from orchestrator.agent.investigator import Investigator
from orchestrator.agent.llm import LLMClient
from orchestrator.agent.proposal import TraceKind
from orchestrator.agent.tools import ToolContext
from orchestrator.cli import build_benchmark
from orchestrator.conciliacao import default_resolvers, reconcile
from orchestrator.kernel.definition import Stage, WorkflowDefinition
from orchestrator.metrics import evaluate
from orchestrator.review.fila import Fila, caminho_da_fila, dataset_id

MODELOS_PADRAO = ("claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5")

# "api" gasta crédito da Console; "assinatura" usa o processo local do
# Claude Code e serve só para avaliar — não exercita anthropic_client.py.
VIAS = ("api", "assinatura")

# Raiz da fila em disco. Atributo de módulo, mesmo padrão de
# `api/app.py::_RAIZ_FILA`, para o teste poder trocá-la por um tmp_path sem
# escrever no repositório.
_RAIZ_FILA: Path | None = None


@dataclass(frozen=True)
class EvalResult:
    model: str
    divergences: int
    proposals_total: int
    proposals_correct: int
    proposals_abstained: int
    total_microcents: int
    # Propostas que nunca chegaram a falar com o modelo: rede caída, 401,
    # conta sem crédito. Sem este contador, uma execução que não fez
    # chamada NENHUMA sai com exatamente os mesmos números de uma em que o
    # modelo tentou e errou tudo — MEDIDO em 2026-09-15, ver o teste.
    proposals_api_failed: int = 0
    # Falso quando a execução foi pela assinatura: ela consome, mas não tem
    # preço por chamada. Imprimir US$ 0,0000 nesse caso seria relatar
    # ausência de medição como medição — o defeito que esta avaliação já
    # cometeu uma vez com falha de API.
    custo_medido: bool = True

    @property
    def precision(self) -> float:
        """Das propostas que arriscaram um tipo, quantas acertaram."""
        arriscadas = self.proposals_total - self.proposals_abstained
        return self.proposals_correct / arriscadas if arriscadas else 0.0

    @property
    def abstention_rate(self) -> float:
        return self.proposals_abstained / self.proposals_total if self.proposals_total else 0.0

    @property
    def mediu_algo(self) -> bool:
        """Falso quando nenhuma investigação chegou a falar com o modelo."""
        return self.proposals_total > self.proposals_api_failed

    @property
    def microcents_per_divergence(self) -> int:
        return self.total_microcents // self.divergences if self.divergences else 0

    def render(self) -> str:
        linhas = [
            f"Modelo:                        {self.model}",
            f"Divergências investigadas:     {self.divergences}",
        ]
        if not self.mediu_algo:
            # Sair pelos números normais aqui seria relatar uma falha como
            # medição: precisão 0,0% e custo US$ 0,0000 por FALTA DE CHAMADA
            # são idênticos a precisão 0,0% e custo zero por desempenho.
            linhas += [
                "",
                f"*** FALHA DE API em {self.proposals_api_failed}/"
                f"{self.proposals_total} investigações — NADA foi medido. ***",
                "Nenhuma chamada ao modelo teve sucesso. Os números de precisão,",
                "abstenção e custo sairiam zerados por falta de chamada, não por",
                "desempenho, e por isso foram omitidos.",
                "O motivo de cada falha está no rastro da proposta (TraceKind.ERRO).",
            ]
            return "\n".join(linhas)
        linhas += [
            f"Precisão (das que arriscaram): {self.precision:.1%}",
            f"Taxa de abstenção:             {self.abstention_rate:.1%}",
        ]
        if self.custo_medido:
            linhas += [
                f"Custo total:                   "
                f"US$ {self.total_microcents / 100_000_000:.4f}",
                f"Custo por divergência:         "
                f"US$ {self.microcents_per_divergence / 100_000_000:.6f}",
            ]
        else:
            linhas.append(
                "Custo:                         não medido — execução por "
                "assinatura não tem preço por chamada"
            )
        if self.proposals_api_failed:
            linhas.append(
                f"ATENÇÃO — FALHA DE API em {self.proposals_api_failed} de "
                f"{self.proposals_total} investigações; os números acima "
                f"cobrem apenas as restantes."
            )
        return "\n".join(linhas)


def _fabrica_real(model: str) -> Callable[[], LLMClient]:
    def fabrica() -> LLMClient:
        from orchestrator.agent.anthropic_client import AnthropicClient

        return AnthropicClient(model=model)

    return fabrica


def avaliar(
    model: str,
    seed: int,
    n: int,
    taxa_divergencia: float,
    client_factory: Callable[[], LLMClient] | None = None,
    via: str = "api",
    investigator_factory: Callable[[ToolContext], object] | None = None,
    gravar_fila: bool = False,
) -> EvalResult:
    if via not in VIAS:
        raise ValueError(f"via desconhecida: {via!r}; use uma de {VIAS}")

    dataset = build_benchmark(seed=seed, n=n, taxa_divergencia=taxa_divergencia)
    contexto = ToolContext(bank=dataset.bank, ledger=dataset.ledger)

    # Assinatura consome, mas não tem preço por chamada. Sem esta distinção o
    # relatório imprimiria US$ 0,0000 e passaria por medição.
    custo_medido = via == "api"

    if investigator_factory is not None:
        investigador = investigator_factory(contexto)
    elif via == "assinatura":
        # Import local: o extra `[assinatura]` é opcional e o núcleo não pode
        # depender do Claude Code para importar este módulo.
        from orchestrator.eval.assinatura import InvestigadorAssinatura

        investigador = InvestigadorAssinatura(context=contexto)
    else:
        cliente = (client_factory or _fabrica_real(model))()
        # O rótulo do resultado vem do modelo PEDIDO; o preço vem do modelo que
        # o cliente REPORTA. Se divergirem, o relatório sai precificado numa
        # tabela e rotulado como outra — corrupção silenciosa que derrota
        # exatamente o propósito desta avaliação.
        if cliente.model != model:
            raise ValueError(
                f"a fábrica devolveu um cliente de {cliente.model!r} quando "
                f"{model!r} foi pedido; o custo sairia precificado errado"
            )
        investigador = Investigator(client=cliente, context=contexto)

    definicao = WorkflowDefinition(
        id="conciliacao-com-agente",
        name="Conciliação bancária com investigador",
        stages=(
            Stage(
                name="conciliar lançamentos",
                cascade=(*default_resolvers(), investigador),
            ),
        ),
    )
    resultado = reconcile(dataset.bank, dataset.ledger, definition=definicao)
    if gravar_fila:
        # Quem grava é o CLI, nunca `reconcile`. O motor continua puro, e é
        # disso que o golden e o teste do dinheiro dependem.
        fila = Fila(
            caminho_da_fila(
                "conciliacao", dataset_id(seed, n, taxa_divergencia), raiz=_RAIZ_FILA
            )
        )
        for p in resultado.proposals:
            fila.gravar_proposta(p)
    # Pela assinatura `model` não está na tabela de preços; isso só não
    # estoura porque todo custo é Cost.zero() e `metrics` curto-circuita
    # antes de converter. O teste de `via=assinatura` pina esse caminho.
    metricas = evaluate(dataset, resultado, model=model)
    falhas_api = sum(
        1
        for p in resultado.proposals
        if any(e.kind is TraceKind.ERRO for e in p.trace)
    )

    return EvalResult(
        model=model,
        divergences=len(resultado.divergences),
        proposals_total=metricas.proposals_total,
        proposals_correct=metricas.proposals_correct,
        proposals_abstained=metricas.proposals_abstained,
        total_microcents=metricas.agent_cost_microcents,
        proposals_api_failed=falhas_api,
        custo_medido=custo_medido,
    )


def _tabela(resultados: list[EvalResult]) -> str:
    """Compara os modelos lado a lado numa tabela.

    O entregável desta avaliação é uma DECISÃO — qual modelo usar —, e blocos
    empilhados (um `render()` por modelo) obrigam quem lê a fazer a
    comparação de cabeça. Colunas lado a lado fazem isso por ele.
    """
    cabecalho = (
        "Modelo", "Precisão", "Abstenção", "US$/divergência", "US$ total", "Situação"
    )
    linhas = [cabecalho]
    for r in resultados:
        if not r.mediu_algo:
            # Um modelo cuja execução falhou inteira aparecendo com "0.0%" ao
            # lado de um que mediu de verdade convida à conclusão errada: que
            # ele foi testado e perdeu. Não foi testado.
            linhas.append(
                (
                    r.model, "—", "—", "—", "—",
                    f"falha de API em {r.proposals_api_failed}/{r.proposals_total}",
                )
            )
            continue
        linhas.append(
            (
                r.model,
                f"{r.precision:.1%}",
                f"{r.abstention_rate:.1%}",
                f"{r.microcents_per_divergence / 100_000_000:.6f}",
                f"{r.total_microcents / 100_000_000:.4f}",
                "—"
                if not r.proposals_api_failed
                else f"falha de API em {r.proposals_api_failed}/{r.proposals_total}",
            )
        )
    larguras = [max(len(linha[i]) for linha in linhas) for i in range(len(cabecalho))]

    def _formatar(linha: tuple[str, ...]) -> str:
        pares = zip(linha, larguras, strict=True)
        return "  ".join(valor.ljust(largura) for valor, largura in pares)

    saida = [_formatar(cabecalho), "  ".join("-" * largura for largura in larguras)]
    saida.extend(_formatar(linha) for linha in linhas[1:])
    return "\n".join(saida)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Avalia o investigador contra o gabarito sintético. GASTA DINHEIRO."
    )
    parser.add_argument("--model", action="append", default=None,
                        help="pode repetir para comparar modelos")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--taxa-divergencia", type=float, default=0.15)
    parser.add_argument(
        "--via",
        choices=VIAS,
        default="api",
        help="api gasta crédito da Console; assinatura usa o Claude Code local "
             "e NÃO exercita anthropic_client.py",
    )
    parser.add_argument(
        "--fila", action="store_true", help="grava as propostas na fila de revisão"
    )
    args = parser.parse_args(argv)

    if args.via == "assinatura":
        # O modelo é o que o Claude Code local estiver usando — não é escolha
        # nossa, e por isso não faz sentido varrer a lista de modelos aqui.
        modelos = ["assinatura"]
        print(
            "Avaliação ao vivo pela ASSINATURA (Claude Code local). Não gasta "
            "crédito da Console e não mede custo."
        )
        print(
            "NÃO exercita anthropic_client.py: o protocolo de ferramentas da "
            "Messages API continua sem prova por este caminho."
        )
    else:
        modelos = args.model or list(MODELOS_PADRAO)
        print(f"Avaliação ao vivo — GASTA DINHEIRO. Modelos: {', '.join(modelos)}")
    print()
    resultados = []
    for modelo in modelos:
        r = avaliar(
            modelo, args.seed, args.n, args.taxa_divergencia, via=args.via,
            gravar_fila=args.fila,
        )
        print(r.render())
        print()
        resultados.append(r)

    if len(resultados) > 1:
        print("Comparação entre modelos:")
        print(_tabela(resultados))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
