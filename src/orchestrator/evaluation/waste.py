"""Economia de ferramenta: quanto uma ferramenta custa e o que ela compra.

**De onde isto veio.** Rodando o domínio `swe` contra um modelo de verdade
(2026-09-16), o agente chamou `contar_palavras` em 5 de 5 issues. O turno 1
custou ~US$ 0,0012 e o turno 2, que só existe porque houve chamada de
ferramenta, custou ~US$ 0,0016. Cerca de 57% do custo era uma ida e volta que
não mudou nenhuma classificação. O prompt diz *"use se precisar"*; o modelo leu
*"sempre"*.

Dois achados de custo neste projeto vieram de RODAR, e nenhum dos dois apareceu
na suíte: este e o de 21% gasto investigando o mesmo par duas vezes. Um teste
verde não é evidência de que o dinheiro está bem gasto, porque nenhum teste
olhava para o dinheiro.

**O que este módulo faz, e o que ele se recusa a fazer.** Ele MEDE: quanto
custou cada ferramenta, em quantos itens foi chamada, e quantas vezes o item
terminou em abstenção mesmo depois de pagá-la. Ele NÃO decide que a ferramenta
é desperdício — isso exige contrafactual, e o contrafactual tem nome nesta
camada: dois `BenchmarkArm`, um com a ferramenta e outro sem, sobre o mesmo
conjunto. Este módulo aponta o candidato; o benchmark julga.

Chamar de "desperdício" o que não foi comparado seria a mesma classe de erro
que relatar custo zero quando nada foi medido.
"""

from dataclasses import dataclass

from orchestrator.kernel.trace import Span, SpanKind, Trace


@dataclass(frozen=True)
class UsoDeFerramenta:
    """O que uma ferramenta custou e em que ela participou."""

    nome: str
    chamadas: int
    itens_alcancados: int
    # Custo dos turnos de modelo que vieram DEPOIS da primeira chamada dentro
    # do mesmo item. É a melhor atribuição disponível a partir do trace: o
    # turno seguinte carrega o resultado da ferramenta no contexto e por isso
    # existe por causa dela. Não é o custo da ferramenta em si — as locais
    # custam zero — é o custo que a decisão de chamá-la PROVOCOU.
    microcents_provocados: int
    # Itens em que a ferramenta foi chamada e o resultado ainda assim foi
    # abstenção. Pagou e continuou sem saber.
    itens_que_abstiveram: int

    def fracao_de(self, total_microcents: int) -> float:
        if total_microcents <= 0:
            return 0.0
        return self.microcents_provocados / total_microcents


@dataclass(frozen=True)
class EconomiaDeFerramentas:
    total_microcents: int
    itens: int
    usos: tuple[UsoDeFerramenta, ...] = ()

    def candidatos(self, *, cobertura_minima: float = 0.9) -> tuple[UsoDeFerramenta, ...]:
        """Ferramentas chamadas em quase TODO item.

        Cobertura alta é o sinal: uma ferramenta que o prompt oferece como
        condicional (*"use se precisar"*) e que é chamada em 100% dos itens não
        está sendo usada condicionalmente. Ou o prompt não está sendo lido como
        escrito, ou a condição é sempre verdadeira e a ferramenta deveria ser
        parte da entrada em vez de uma ida e volta paga.

        Nenhum julgamento aqui: é uma lista para o benchmark comparar.
        """
        if not self.itens:
            return ()
        return tuple(
            u
            for u in self.usos
            if u.itens_alcancados / self.itens >= cobertura_minima
        )

    def render(self) -> str:
        if not self.usos:
            return "(nenhuma ferramenta foi chamada)"
        cab = f"{'ferramenta':<24} {'chamadas':>9} {'itens':>7} {'US$':>10} {'% custo':>8}"
        linhas = [cab, "-" * len(cab)]
        for u in self.usos:
            linhas.append(
                f"{u.nome:<24} {u.chamadas:>9} "
                f"{u.itens_alcancados:>3}/{self.itens:<3} "
                f"{u.microcents_provocados / 100_000_000:>10.4f} "
                f"{100 * u.fracao_de(self.total_microcents):>7.1f}%"
            )
            if u.itens_que_abstiveram:
                linhas.append(
                    f"{'':24} └─ {u.itens_que_abstiveram} item(ns) abstiveram "
                    f"mesmo depois de chamá-la"
                )
        for c in self.candidatos():
            linhas.append(
                f"\ncandidato a braço de benchmark: {c.nome} foi chamada em "
                f"{c.itens_alcancados} de {self.itens} itens e provocou "
                f"{100 * c.fracao_de(self.total_microcents):.1f}% do custo. "
                f"Compare um braço sem ela."
            )
        return "\n".join(linhas)


def _ordem(trace: Trace) -> dict[str, int]:
    """Posição de cada span na ordem em que o coletor os gravou.

    O `SpanCollector` numera em sequência (`_novo_id`), então a ordem da tupla
    É a ordem temporal. Depender de `started_at` pararia de funcionar com dois
    spans no mesmo milissegundo, que acontece com ferramenta local.
    """
    return {s.id: i for i, s in enumerate(trace.spans)}


def medir_ferramentas(
    trace: Trace,
    *,
    model: str,
    abstiveram: frozenset[str] = frozenset(),
) -> EconomiaDeFerramentas:
    """Atribui custo às decisões de chamar ferramenta, item a item.

    `model` é OBRIGATÓRIO. As spans de LLM que o `SpanCollector` grava guardam
    tokens mas não o modelo, e sem tabela de preço `Cost.microcents` não tem o
    que converter. Um default aqui faria toda ferramenta custar zero — um
    relatório inteiro de economia dizendo que nada custou nada, com a aparência
    exata de "não há desperdício". É o mesmo modo de falha do bug de unidade
    que fez a política econômica pular 20 de 20 divergências.
    """
    posicao = _ordem(trace)
    itens = [s for s in trace.spans if s.kind is SpanKind.ITEM]
    por_ferramenta: dict[str, list[Span]] = {}
    provocado: dict[str, int] = {}
    alcancados: dict[str, set[str]] = {}
    abstiveram_apos: dict[str, set[str]] = {}
    custo_total = 0

    for item in itens:
        filhos = sorted(trace.filhos(item.id), key=lambda s: posicao[s.id])
        ferramentas = [f for f in filhos if f.kind is SpanKind.TOOL]
        llms = [f for f in filhos if f.kind is SpanKind.LLM]
        custo_total += sum(_tokens_em_microcents(s, model) for s in llms)
        if not ferramentas:
            continue
        primeira = posicao[ferramentas[0].id]
        # Tudo que o modelo gastou DEPOIS da primeira chamada dentro deste
        # item. Atribuído à primeira porque é ela que criou o turno extra;
        # ratear entre várias inventaria uma precisão que o trace não tem.
        depois = sum(
            _tokens_em_microcents(s, model) for s in llms if posicao[s.id] > primeira
        )
        nome = ferramentas[0].name
        por_ferramenta.setdefault(nome, []).extend(ferramentas)
        provocado[nome] = provocado.get(nome, 0) + depois
        alcancados.setdefault(nome, set()).add(item.name)
        if item.name in abstiveram:
            abstiveram_apos.setdefault(nome, set()).add(item.name)

    usos = tuple(
        UsoDeFerramenta(
            nome=nome,
            chamadas=len(spans),
            itens_alcancados=len(alcancados.get(nome, ())),
            microcents_provocados=provocado.get(nome, 0),
            itens_que_abstiveram=len(abstiveram_apos.get(nome, ())),
        )
        for nome, spans in sorted(
            por_ferramenta.items(), key=lambda kv: -provocado.get(kv[0], 0)
        )
    )
    return EconomiaDeFerramentas(
        total_microcents=custo_total, itens=len(itens), usos=usos
    )


def _tokens_em_microcents(span: Span, model: str) -> int:
    return span.cost.microcents(model)
