"""Onde o agente erra, não só quanto.

**Por que uma taxa não basta.** O estrato adversarial do `swe` deu 80%: quatro
erros em vinte. Quatro erros espalhados por tipos diferentes é limite do modelo
— não há o que fazer sem trocar de modelo. Quatro erros todos na mesma direção
(`DUVIDA` respondido como `FEATURE`, digamos) é uma linha de prompt. **São
diagnósticos opostos, e a taxa não distingue os dois.**

**Custo zero.** É o MESMO `Run` já pago, lido de outro jeito. Nenhuma chamada a
mais — a mesma propriedade que permite pontuar por dificuldade sem reexecutar.

**O que ela não faz.** Não sugere correção. Uma matriz que dissesse "ajuste o
prompt" estaria inventando causa a partir de correlação, e a causa de uma
confusão sistemática pode estar no prompt, no vocabulário do domínio, ou nos
próprios casos — inclusive em quem os escreveu. A matriz mostra o padrão; quem
o interpreta é quem conhece o domínio.
"""

from dataclasses import dataclass

from orchestrator.evaluation.case import EvalDataset
from orchestrator.kernel.run import Run

# Coluna para o que o agente respondeu quando se absteve. Fica separada dos
# tipos porque abstenção não é um erro de classificação — é a recusa de
# classificar, e somá-la aos tipos faria "não sei" competir com "BUG" numa
# tabela que pergunta "confundiu com o quê".
ABSTEVE = "(absteve)"
# Caso que o run não cobriu. Não é zero e não é erro: é ausência de medição, e
# a mesma disciplina do resto da camada manda dizer isso.
AUSENTE = "(sem proposta)"


@dataclass(frozen=True)
class Erro:
    """Um caso errado, com nome. É o que permite ir ler a issue."""

    item_id: str
    esperado: str
    dito: str


@dataclass(frozen=True)
class Confusao:
    """Linhas são o ESPERADO, colunas o que o agente DISSE."""

    matriz: dict[tuple[str, str], int]
    esperados: tuple[str, ...]
    ditos: tuple[str, ...]
    erros: tuple[Erro, ...] = ()

    @property
    def total(self) -> int:
        return sum(self.matriz.values())

    def acertos(self) -> int:
        return sum(n for (e, d), n in self.matriz.items() if e == d)

    def confusoes_dominantes(self, minimo: int = 2) -> tuple[tuple[str, str, int], ...]:
        """As trocas fora da diagonal que se repetem.

        `minimo=2` porque um erro isolado não é padrão — é um erro. Reportar
        singletons como "confusão dominante" transformaria ruído em diagnóstico,
        que é o erro que este projeto já cometeu duas vezes lendo diferença de
        um caso como resultado.
        """
        fora = [
            (e, d, n)
            for (e, d), n in self.matriz.items()
            if e != d and d not in (ABSTEVE, AUSENTE) and n >= minimo
        ]
        return tuple(sorted(fora, key=lambda t: -t[2]))

    def render(self, *, max_erros: int = 10) -> str:
        if not self.total:
            return "(nenhum caso pontuado)"
        largura = max((len(c) for c in self.ditos), default=8) + 2
        cab = " " * 14 + "".join(f"{c:>{largura}}" for c in self.ditos)
        linhas = ["esperado \\ disse", cab, "-" * len(cab)]
        for esperado in self.esperados:
            celulas = "".join(
                f"{self.matriz.get((esperado, d), 0) or '·':>{largura}}"
                for d in self.ditos
            )
            linhas.append(f"{esperado:<14}{celulas}")

        dominantes = self.confusoes_dominantes()
        if dominantes:
            linhas.append("")
            for esperado, dito, n in dominantes:
                linhas.append(
                    f"padrão: {n}x {esperado} respondido como {dito}"
                )
        elif self.erros:
            linhas.append("")
            linhas.append(
                "nenhuma confusão se repete — os erros estão espalhados, o que "
                "aponta para limite do modelo e não para regra faltando"
            )

        if self.erros:
            linhas.append("")
            linhas.append(f"casos errados ({len(self.erros)}):")
            for erro in self.erros[:max_erros]:
                linhas.append(
                    f"  {erro.item_id:<12} esperado {erro.esperado:<10} "
                    f"disse {erro.dito}"
                )
            if len(self.erros) > max_erros:
                linhas.append(f"  ... e mais {len(self.erros) - max_erros}")
        return "\n".join(linhas)


def confundir(
    run: Run,
    dataset: EvalDataset,
    *,
    abstem_com: frozenset[str],
) -> Confusao:
    """A matriz, a partir de um run já executado.

    Só pontua caso com `kind` esperado, pela mesma razão que `medir`: um caso
    colhido de um `rejeitar` afirma que a hipótese antiga estava errada e não
    qual é a certa. Contá-lo aqui inventaria uma linha para uma verdade que
    ninguém estabeleceu.
    """
    por_item = dataset.by_item_id()
    dito_por_item = {p.item_id: p.tipo for p in run.proposals}

    matriz: dict[tuple[str, str], int] = {}
    erros: list[Erro] = []
    esperados: list[str] = []
    ditos: list[str] = []

    for item_id, caso in por_item.items():
        esperado = caso.expected.kind
        if esperado is None:
            continue
        tipo = dito_por_item.get(item_id)
        if tipo is None:
            dito = AUSENTE
        elif tipo in abstem_com:
            dito = ABSTEVE
        else:
            dito = tipo
        matriz[(esperado, dito)] = matriz.get((esperado, dito), 0) + 1
        if esperado not in esperados:
            esperados.append(esperado)
        if dito not in ditos:
            ditos.append(dito)
        if dito != esperado and dito not in (ABSTEVE, AUSENTE):
            erros.append(Erro(item_id=item_id, esperado=esperado, dito=dito))

    # Ordem estável: tipos em ordem alfabética, e as duas colunas especiais por
    # último. Sem isso, a tabela mudaria de forma entre execuções do mesmo run e
    # um diff de relatório passaria a mudar sozinho.
    especiais = [c for c in (ABSTEVE, AUSENTE) if c in ditos]
    return Confusao(
        matriz=matriz,
        esperados=tuple(sorted(esperados)),
        ditos=tuple(sorted(c for c in ditos if c not in especiais)) + tuple(especiais),
        erros=tuple(sorted(erros, key=lambda e: e.item_id)),
    )
