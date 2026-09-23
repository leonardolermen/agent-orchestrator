"""Custo e a ordem entre classes de custo.

Primeiro módulo do `kernel`, e a razão de ele vir primeiro é estrutural: `Cost`
morava em `agent/proposal.py` e era importado por `workflow/resolver.py` — o
contrato genérico de resolução dependendo do pacote do agente. Custo não é um
conceito de agente. `RevisorHumano` devolve `Cost.zero()` e o comentário lá diz
"trabalho humano custa, mas não em tokens — e `Cost` só mede tokens": isso é
uma lacuna do TIPO, não do revisor, e ela só pode ser fechada com `Cost` num
lugar que o revisor possa importar sem arrastar a tabela de preços de LLM.

`kernel/` não importa nada — nem domínio, nem provider, nem pydantic. Ver
`tests/arquitetura/test_camadas.py`.
"""

from dataclasses import dataclass
from enum import IntEnum


class CostClass(IntEnum):
    """A ordem que impede a armadilha mais cara do produto: montar uma cascata
    que chama inteligência antes de tentar a regra de graça.

    A ordem não é uma convenção que alguém segue — é o valor pelo qual a
    cascata é ordenada (`Stage.ordered()`), e não existe entrada que a inverta.

    `CREW` entra entre `AGENTE` e `HUMANO` porque uma tripulação é mais cara
    que um agente (N laços em vez de um) e mais barata que interromper uma
    pessoa. Ela ainda não tem produtor — nada constrói um `Crew` hoje, e por
    isso a chave nunca aparece em `matches_by_class`. Entra mesmo assim, e é a
    única concessão a capacidade futura neste módulo: acrescentar um membro no
    MEIO de uma enum cujo valor numérico é a semântica renumera `HUMANO`, e
    renumerar mais tarde custaria mexer na ordenação com mais código dependendo
    dela. Fazer agora custa um commit, com 468 testes de testemunha.

    O que NÃO entrou junto, apesar de estar no plano: `Budget`. Ele não tem
    chamador até o motor de política (M3), e tipo novo sem chamador é
    capacidade especulativa — a mesma disciplina que este repositório já
    aplicou em `add_business_days` (decisão 9). Estender uma ordem que já
    existe e inventar um tipo que ninguém usa são coisas diferentes.
    """

    REGRA = 0
    AGENTE = 1
    CREW = 2
    HUMANO = 3


# Preço por token em micro-cents de USD (1 micro-cent = 1e-6 de centavo de
# dólar). Inteiro de propósito: a constraint de dinheiro do projeto vale aqui
# também, e ponto flutuante acumulando por divergência erraria devagar.
#
# Fonte: tabela de preços da API por 1M de tokens.
#   opus-5     $5,00 entrada / $25,00 saída
#   sonnet-5   $2,00 / $10,00
#   haiku-4.5  $1,00 / $5,00
#
# Ler do cache custa ~10% da entrada. ESCREVER no cache custa ~125% — e esses
# tokens de escrita não aparecem nem em input_tokens nem em cached_tokens na
# resposta da API. Ignorá-los subcontaria o custo real em toda primeira chamada
# de cada janela de cache, e custo por divergência é o número comercial deste
# produto.
#
# Ordem: entrada, saída, leitura de cache, escrita de cache.
_PRECOS = {
    "claude-opus-5": (500, 2500, 50, 625),
    "claude-sonnet-5": (200, 1000, 20, 250),
    "claude-haiku-4-5": (100, 500, 10, 125),
}


@dataclass(frozen=True)
class Cost:
    """O que uma unidade de trabalho consumiu. Tokens, não dinheiro — o preço
    depende do modelo, e o mesmo consumo custa diferente em cada um."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cache_creation_tokens: int = 0
    calls: int = 0

    @staticmethod
    def zero() -> "Cost":
        return Cost()

    def __add__(self, outro: "Cost") -> "Cost":
        return Cost(
            input_tokens=self.input_tokens + outro.input_tokens,
            output_tokens=self.output_tokens + outro.output_tokens,
            cached_tokens=self.cached_tokens + outro.cached_tokens,
            cache_creation_tokens=self.cache_creation_tokens
            + outro.cache_creation_tokens,
            calls=self.calls + outro.calls,
        )

    def microcents(self, model: str) -> int:
        """Custo em micro-cents de USD para o modelo dado."""
        if model not in _PRECOS:
            raise ValueError(f"modelo sem preço conhecido: {model!r}")
        entrada, saida, leitura, escrita = _PRECOS[model]
        return (
            self.input_tokens * entrada
            + self.output_tokens * saida
            + self.cached_tokens * leitura
            + self.cache_creation_tokens * escrita
        )


def modelos_precificados() -> list[str]:
    """Os modelos que o produto sabe cobrar, em ordem.

    Fronteira pública, como `modelo_precificado`, e pelo mesmo motivo — só que
    para a LISTA: a tela e o chat precisam OFERECER exatamente o que o servidor
    aceita. Sem ela, cada um faria a própria cópia, e a que divergisse
    ofereceria um modelo que `microcents` recusa — o que só aparece quando
    alguém aperta rodar.
    """
    return sorted(_PRECOS)


def modelo_precificado(model: str) -> bool:
    """Verdadeiro quando o modelo tem preço conhecido na tabela.

    Fronteira pública para código fora deste módulo (ex.: `AnthropicClient`)
    que precisa validar um modelo sem importar a tabela de preços privada
    diretamente.
    """
    return model in _PRECOS
