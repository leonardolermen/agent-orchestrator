"""Cálculo de tributos retidos na fonte.

Módulo neutro de propósito: tanto o gerador sintético (que injeta a
divergência) quanto a ferramenta do agente (que a explica) importam daqui.
Antes, a ferramenta importava a mesma função de `synth/injectors.py` — o
gerador de benchmark vazando para dentro do código de produção, e a acurácia
de RETENCAO_IMPOSTO ficava parcialmente circular: o agente calculava a
retenção com a função exata que fabricou a divergência.
"""

# Alíquotas em basis points (1% = 100 bp). Valores típicos de retenção na fonte.
_ALIQUOTAS = {
    "ISS": 500,  # 5%
    "IRRF": 150,  # 1,5%
    "CSLL/PIS/COFINS": 465,  # 4,65%
    "INSS": 1100,  # 11%
}


def calcular_retencao(bruto: int, aliquota_bp: int) -> int:
    """Retenção em centavos, truncada para baixo.

    Determinística e testável de propósito: cálculo fiscal não pode depender
    de raciocínio de modelo de linguagem. Ver spec 4.6.
    """
    return bruto * aliquota_bp // 10_000
