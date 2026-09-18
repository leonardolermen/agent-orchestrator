"""Uma pergunta de sim ou não sobre um campo. O parâmetro compartilhado.

"Limiar" e "padrão" pareciam dois blocos, e não são: `valor > 1000` e
`assunto contém "fatura"` são o MESMO bloco com um teste diferente. O que muda
de verdade é o que se faz com o item que passa — filtrar, validar ou rotear —, e
esses são três blocos (`filtro.py`, `validacao.py`, `condicao.py`). Predicado é o
eixo ortogonal a eles.

Sem isso, o catálogo teria o produto cartesiano: filtrar-por-limiar,
filtrar-por-padrão, validar-por-limiar... A pessoa escolheria entre nove blocos
em vez de escolher um bloco e um teste.

**Não há expressão regular, e a ausência é deliberada.** Um regex escrito na tela
e compilado no servidor é negação de serviço por retrocesso catastrófico — uma
linha de texto na paleta pendura o processo. `contem`, `comeca_com` e
`termina_com` cobrem o que um regex faria na maioria dos casos, sem essa ponta.
Quando houver caso que exija, ele entra com limite de tempo e sem retrocesso, e
isso é uma decisão própria.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from orchestrator.regras.campos import valor_do_campo


class Comparacao(StrEnum):
    """O vocabulário fechado de perguntas.

    LISTA BRANCA, pela mesma razão de `_PALAVRAS_DE_SCHEMA` no `ToolRegistry`:
    um teste desconhecido precisa ser recusado na construção, com nome, e não
    virar um predicado que responde sempre não — que seria um bloco filtrando
    zero itens e parecendo que não havia o que filtrar.
    """

    MAIOR = "maior"
    MAIOR_OU_IGUAL = "maior_ou_igual"
    MENOR = "menor"
    MENOR_OU_IGUAL = "menor_ou_igual"
    IGUAL = "igual"
    DIFERENTE = "diferente"
    CONTEM = "contem"
    COMECA_COM = "comeca_com"
    TERMINA_COM = "termina_com"
    VAZIO = "vazio"
    PREENCHIDO = "preenchido"


_ORDEM = frozenset(
    {Comparacao.MAIOR, Comparacao.MAIOR_OU_IGUAL, Comparacao.MENOR, Comparacao.MENOR_OU_IGUAL}
)
_TEXTO = frozenset({Comparacao.CONTEM, Comparacao.COMECA_COM, Comparacao.TERMINA_COM})
_SEM_VALOR = frozenset({Comparacao.VAZIO, Comparacao.PREENCHIDO})


class ComparacaoImpossivel(ValueError):
    """O teste não cabe no dado — comparar grandeza com texto, por exemplo.

    Levanta em vez de responder não. Um predicado que respondesse não para todo
    item produziria um bloco que não filtra nada, não valida nada e não roteia
    nada, sem uma palavra — e o sintoma seria uma lacuna de 100% que alguém
    leria como "o workflow não deu conta".
    """


@dataclass(frozen=True)
class Predicado:
    """`campo` `teste` `valor`. Ex.: `valor maior 1000`, `assunto contem fatura`."""

    campo: str
    teste: Comparacao
    # Texto sempre, inclusive para número: é o que a tela manda e o que o JSON
    # transporta. A conversão acontece na comparação, contra o tipo do DADO —
    # que é a única hora em que se sabe qual ele é.
    valor: str = ""

    def __post_init__(self) -> None:
        # Validar é construir. Um predicado malformado que só falhasse ao rodar
        # apareceria como bloco que não faz nada.
        object.__setattr__(self, "teste", Comparacao(self.teste))
        if not self.campo.strip():
            raise ValueError("predicado sem campo: diga em qual campo perguntar")
        if self.teste in _SEM_VALOR:
            return
        if not self.valor.strip():
            raise ValueError(
                f"o teste {self.teste.value!r} precisa de um valor de comparação"
            )

    def __str__(self) -> str:
        if self.teste in _SEM_VALOR:
            return f"{self.campo} {self.teste.value}"
        return f"{self.campo} {self.teste.value} {self.valor}"

    def aprova(self, payload: Any) -> bool:
        """O item passa no teste?"""
        v = valor_do_campo(payload, self.campo)

        if self.teste is Comparacao.VAZIO:
            return v is None or v == ""
        if self.teste is Comparacao.PREENCHIDO:
            return v is not None and v != ""
        # Campo vazio não passa em teste nenhum, e não é o mesmo que falhar por
        # comparação: `None > 10` é erro em Python, e responder `False` aqui
        # trataria "não sei" como "não". O bloco que quer perguntar isso usa
        # `vazio`.
        if v is None:
            return False

        if self.teste in _ORDEM:
            return self._compara(v)
        if self.teste in _TEXTO:
            return self._texto(v)
        igual = str(v) == self.valor
        return igual if self.teste is Comparacao.IGUAL else not igual

    def _compara(self, v: Any) -> bool:
        try:
            esquerda, direita = float(v), float(self.valor)
        except (TypeError, ValueError) as erro:
            raise ComparacaoImpossivel(
                f"{self.campo!r} vale {v!r} e o teste {self.teste.value!r} compara "
                f"grandeza. use `igual`/`diferente` para texto, ou aponte o teste "
                f"para um campo numérico"
            ) from erro
        if self.teste is Comparacao.MAIOR:
            return esquerda > direita
        if self.teste is Comparacao.MAIOR_OU_IGUAL:
            return esquerda >= direita
        if self.teste is Comparacao.MENOR:
            return esquerda < direita
        return esquerda <= direita

    def _texto(self, v: Any) -> bool:
        # `str(v)` e não uma recusa: perguntar se um número "começa com 9" é
        # legítimo (prefixo de documento, DDD, código de agência), e exigir que
        # o campo já fosse texto recusaria uma pergunta que faz sentido.
        alvo = str(v)
        if self.teste is Comparacao.CONTEM:
            return self.valor in alvo
        if self.teste is Comparacao.COMECA_COM:
            return alvo.startswith(self.valor)
        return alvo.endswith(self.valor)


__all__ = ["Predicado", "Comparacao", "ComparacaoImpossivel"]
