"""Detecção de regressão: comparar contra a linha de base e falhar o CI.

**Por MÍNIMO entre sementes, não por média.** Preservado da decisão 26 do
repositório: *"um teste de regressão precisa pegar ALGUMA semente colapsar, não
a média deslizar; a média esconde exatamente o caso que interessa."* Cinco
sementes a 90% e uma a 20% dão média 78% — que passa em quase qualquer limiar e
esconde um colapso total. O mínimo entre sementes vê o 20%.

A redução é PESSIMISTA em cada dimensão, e as duas direções são diferentes de
propósito: qualidade reduz por `min` (a pior semente manda), custo reduz por
`max` (a semente mais cara manda). Reduzir custo por média deixaria uma semente
que estourou dez vezes o orçamento passar despercebida entre cinco baratas.

**O que já existe e não é substituído.** O job `conciliador` do CI trava
`85.3%`, `Falsos positivos: 0` e `Falsos negativos: 0` com `grep` na saída da
CLI. Essa é a forma primitiva deste módulo e ela funciona — o §14.6 é explícito
em não trocá-la. Este módulo é o segundo job: roda o conjunto acumulado, falha
nos mesmos critérios, e cobre o que o `grep` não alcança (custo por acerto,
abstenção, e qualquer domínio que não seja conciliação).
"""

from collections.abc import Sequence
from dataclasses import dataclass

from orchestrator.evaluation.metrics import EvalMetrics

# Os campos de `EvalMetrics` que são contagens de erro: zero é o único valor
# aceitável e nenhuma folga percentual se aplica a eles.
_CONTAGENS_DE_ERRO = ("false_positives", "false_negatives", "api_failures")


@dataclass(frozen=True)
class Violacao:
    """Uma regra quebrada, com os dois números que a quebraram.

    Guarda `base` e `atual` porque uma mensagem de CI que diz apenas "precisão
    caiu" obriga quem lê a ir rodar de novo para saber quanto. O custo de
    carregar dois floats é zero; o de não carregá-los é um ciclo de CI.
    """

    regra: str
    base: float
    atual: float
    detalhe: str

    def __str__(self) -> str:
        return f"{self.regra}: {self.detalhe} (base {self.base:g} → atual {self.atual:g})"


@dataclass(frozen=True)
class RegressionReport:
    violacoes: tuple[Violacao, ...] = ()
    sementes: int = 0

    @property
    def passou(self) -> bool:
        return not self.violacoes

    def render(self) -> str:
        if self.passou:
            return f"sem regressão ({self.sementes} semente(s), redução pessimista)"
        return "\n".join(
            [f"{len(self.violacoes)} regressão(ões) em {self.sementes} semente(s):"]
            + [f"  - {v}" for v in self.violacoes]
        )


@dataclass(frozen=True)
class RegressionCheck:
    """Os limiares. Explícitos, e cada um com uma razão.

    `max_precision_drop=0.05` — cinco pontos. Abaixo disso, a variação entre
    execuções de um modelo não determinístico produziria alarme falso, e um CI
    que dá alarme falso é um CI que as pessoas aprendem a ignorar.

    `max_cost_increase=0.20` — vinte por cento. Custo sobe legitimamente quando
    o agente investiga mais fundo; o limiar existe para pegar a ordem de
    grandeza, não o ruído. Foi assim que o consumo do harness do Claude Code
    apareceria: 28 mil tokens onde havia dois.

    `zero_tolerance=("false_positives",)` — e só ele. O falso negativo custa um
    agente; o falso positivo fecha errado e ninguém olha. A assimetria de
    gravidade já está na decisão 24 do repositório, e aqui ela vira limiar.
    """

    max_precision_drop: float = 0.05
    max_cost_increase: float = 0.20
    zero_tolerance: tuple[str, ...] = ("false_positives",)
    max_abstention_increase: float = 0.15

    def __post_init__(self) -> None:
        desconhecidos = [c for c in self.zero_tolerance if c not in _CONTAGENS_DE_ERRO]
        if desconhecidos:
            raise ValueError(
                f"zero_tolerance cita campo que não é contagem de erro: "
                f"{desconhecidos}. use um de {_CONTAGENS_DE_ERRO} — aplicar "
                f"tolerância zero a uma TAXA travaria o CI em qualquer variação"
            )
        for nome, valor in (
            ("max_precision_drop", self.max_precision_drop),
            ("max_cost_increase", self.max_cost_increase),
            ("max_abstention_increase", self.max_abstention_increase),
        ):
            if valor < 0:
                raise ValueError(f"{nome} negativo ({valor}) inverteria a comparação")

    def verificar(
        self,
        baseline: Sequence[EvalMetrics],
        atual: Sequence[EvalMetrics],
    ) -> RegressionReport:
        """Compara duas famílias de medições, uma por semente.

        Exige o MESMO número de sementes dos dois lados. Comparar três sementes
        contra dez deixaria a redução pessimista mais severa de um lado só, e o
        resultado diria mais sobre quantas sementes rodaram do que sobre o
        código — que é a forma mais silenciosa de um teste de regressão mentir.
        """
        if not baseline or not atual:
            raise ValueError(
                "comparação exige medições dos dois lados; uma lista vazia "
                "produziria 'sem regressão' por ausência de dado"
            )
        if len(baseline) != len(atual):
            raise ValueError(
                f"sementes diferentes: base tem {len(baseline)}, atual tem "
                f"{len(atual)}. a redução pessimista fica mais severa do lado "
                f"com mais sementes, e a comparação mediria isso"
            )

        violacoes: list[Violacao] = []

        # -- tolerância zero: a PIOR semente, nunca a soma ------------------
        for campo in self.zero_tolerance:
            pior = max(getattr(m, campo) for m in atual)
            if pior > 0:
                violacoes.append(
                    Violacao(
                        regra=f"zero_tolerance:{campo}",
                        base=0,
                        atual=pior,
                        detalhe=f"a pior semente tem {pior}; o limite é 0",
                    )
                )

        # -- qualidade: min entre sementes ---------------------------------
        base_prec = min(m.proposal_precision for m in baseline)
        atual_prec = min(m.proposal_precision for m in atual)
        if base_prec - atual_prec > self.max_precision_drop:
            violacoes.append(
                Violacao(
                    regra="max_precision_drop",
                    base=base_prec,
                    atual=atual_prec,
                    detalhe=f"queda de {base_prec - atual_prec:.3f} na pior "
                    f"semente; o limite é {self.max_precision_drop:.3f}",
                )
            )

        # Abstenção que sobe é qualidade que cai sem a precisão cair: o agente
        # deixa de arriscar e a precisão das que sobraram até melhora. Sem esta
        # regra, "não responder nada" seria a estratégia ótima contra o CI.
        base_abst = max(m.abstention_rate for m in baseline)
        atual_abst = max(m.abstention_rate for m in atual)
        if atual_abst - base_abst > self.max_abstention_increase:
            violacoes.append(
                Violacao(
                    regra="max_abstention_increase",
                    base=base_abst,
                    atual=atual_abst,
                    detalhe=f"alta de {atual_abst - base_abst:.3f} na pior "
                    f"semente; o limite é {self.max_abstention_increase:.3f}",
                )
            )

        # -- custo: max entre sementes, e POR ACERTO -----------------------
        # Por acerto, não total: um braço que ficou 30% mais caro porque passou
        # a acertar o dobro não é regressão, é o melhor negócio disponível.
        base_custo = _pior_custo_por_acerto(baseline)
        atual_custo = _pior_custo_por_acerto(atual)
        if base_custo is not None and atual_custo is None:
            violacoes.append(
                Violacao(
                    regra="max_cost_increase",
                    base=base_custo,
                    atual=-1,
                    detalhe="alguma semente deixou de produzir proposta correta, "
                    "e sem acerto o custo por acerto não existe",
                )
            )
        elif base_custo and atual_custo is not None:
            alta = (atual_custo - base_custo) / base_custo
            if alta > self.max_cost_increase:
                violacoes.append(
                    Violacao(
                        regra="max_cost_increase",
                        base=base_custo,
                        atual=atual_custo,
                        detalhe=f"custo por acerto subiu {100 * alta:.1f}% na "
                        f"pior semente; o limite é "
                        f"{100 * self.max_cost_increase:.1f}%",
                    )
                )

        return RegressionReport(violacoes=tuple(violacoes), sementes=len(atual))


def _pior_custo_por_acerto(medicoes: Sequence[EvalMetrics]) -> float | None:
    """O maior custo por acerto entre sementes, ou `None` se ALGUMA não tem.

    `None` propaga de propósito: uma semente sem proposta correta não tem custo
    por acerto, e substituí-la por zero (ou ignorá-la) faria o colapso total de
    uma semente melhorar a métrica agregada.
    """
    valores = [m.microcents_per_correct_proposal for m in medicoes]
    if any(v is None for v in valores):
        return None
    return float(max(valores))
