"""Checar uma exigência e mandar o que falhou para o humano. Sem resolver nada.

A diferença entre este bloco e o `filtro.py` é o destino do item, e é a coisa
mais importante deste pacote: **o filtro RESOLVE (o item sai do pool) e a
validação PROPÕE (o item fica).** Uma `Proposal` explica e sugere; quem resolve
é o humano ao aprovar — é a invariante que o `ResolverOutput` torna estrutural,
porque `proposals` não aparece nem em `without()` nem em `com()`.

É a mesma forma de "o agente propõe, a Decision decide", aplicada a uma regra
determinística. E o fato de ser determinística muda um número: a confiança é
sempre ALTA. Um agente diz "acho que"; esta regra CONFERIU. Confiança alta exige
evidência, e a evidência aqui é o campo e o valor que reprovaram — o que a fila
precisa mostrar para o humano decidir sem reabrir o dado.

Repare na inversão: a proposta sai para quem **falha** o predicado. Escrever a
exigência ("valor menor_ou_igual 10000") é mais natural do que escrever a
violação, e é assim que uma política é redigida.
"""

from dataclasses import dataclass, field

from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.resolution import Confidence, Proposal
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkSet
from orchestrator.regras.predicado import Comparacao, Predicado


@dataclass(frozen=True)
class Validacao:
    """Item que NÃO passa no predicado vira proposta para revisão humana."""

    kind: str
    campo: str
    teste: str
    valor: str = ""
    # O vocabulário do domínio, não do bloco: `Proposal.tipo` é `str` justamente
    # para que cada domínio nomeie o que achou. "FORA_DA_POLITICA" é um default
    # que serve de exemplo, não uma taxonomia imposta.
    tipo: str = "FORA_DA_POLITICA"
    acao_sugerida: str = "revisar_manual"
    name: str = "validacao"
    resumo: str = "quem falha o teste vira proposta para revisão humana"
    cost_class: CostClass = field(default=CostClass.REGRA, init=False)

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ValueError(f"{self.name!r}: diga sobre qual kind ele roda")
        if not self.tipo.strip():
            raise ValueError(
                f"{self.name!r}: `tipo` vazio. é o rótulo que o humano lê na fila, "
                f"e uma proposta sem rótulo não diz o que foi encontrado"
            )
        object.__setattr__(
            self,
            "_predicado",
            Predicado(campo=self.campo, teste=Comparacao(self.teste), valor=self.valor),
        )

    @property
    def predicado(self) -> Predicado:
        return self._predicado  # type: ignore[attr-defined]

    def describe(self) -> ResolverDescription:
        return ResolverDescription(
            name=self.name,
            cost_class=self.cost_class,
            summary=self.resumo,
            consome=frozenset({self.kind}),
        )

    def resolve(self, work: WorkSet) -> ResolverOutput:
        propostas = []
        for item in work.of_kind(self.kind):
            if self.predicado.aprova(item.payload):
                continue
            valor = self.predicado.campo
            propostas.append(
                Proposal(
                    item_id=item.id,
                    tipo=self.tipo,
                    explicacao=f"a exigência «{self.predicado}» não foi atendida",
                    # Confiança ALTA exige evidência não vazia, e aqui ela nunca
                    # é: o campo conferido e o valor que reprovou são exatamente
                    # o que o humano precisa ver para decidir.
                    evidencia=[
                        f"{valor}={_texto(item.payload, valor)}",
                        f"exigido: {self.predicado}",
                    ],
                    confianca=Confidence.ALTA,
                    acao_sugerida=self.acao_sugerida,
                )
            )
        return ResolverOutput(proposals=propostas)


def _texto(payload: object, campo: str) -> str:
    from orchestrator.regras.campos import valor_do_campo

    return str(valor_do_campo(payload, campo))


__all__ = ["Validacao"]
