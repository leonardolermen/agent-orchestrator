"""Taxonomia de divergências de conciliação.

Ver spec seção 4.5. A lista é assumidamente incompleta: tipos ausentes se
anunciam pelo acúmulo de NAO_IDENTIFICADO. Adicionar um tipo deve custar uma
entrada aqui e uma classe injetora, nada mais.
"""

from enum import StrEnum


class DivergenceType(StrEnum):
    # Diferença de valor com explicação legítima
    RETENCAO_IMPOSTO = "RETENCAO_IMPOSTO"
    TARIFA_BANCARIA = "TARIFA_BANCARIA"
    JUROS_MULTA = "JUROS_MULTA"
    DESCONTO_ANTECIPACAO = "DESCONTO_ANTECIPACAO"
    DIFERENCA_CAMBIAL = "DIFERENCA_CAMBIAL"

    # Diferença de agrupamento
    PAGAMENTO_AGREGADO = "PAGAMENTO_AGREGADO"
    PAGAMENTO_PARCIAL = "PAGAMENTO_PARCIAL"

    # Diferença de tempo
    DEFASAGEM_TEMPORAL = "DEFASAGEM_TEMPORAL"

    # Erro humano
    DUPLICIDADE = "DUPLICIDADE"
    ERRO_DIGITACAO = "ERRO_DIGITACAO"
    CONTA_INCORRETA = "CONTA_INCORRETA"

    # Reversão
    ESTORNO = "ESTORNO"
    DEVOLUCAO_FUNDOS = "DEVOLUCAO_FUNDOS"

    # Sem hipótese
    NAO_IDENTIFICADO = "NAO_IDENTIFICADO"
