"""Avaliação: o conjunto de casos, as métricas e a detecção de regressão.

Esta camada PONTUA execuções; não as produz. `PERMITIDO["evaluation"]` é
`{kernel, storage, observability}` — sem `runtime` e sem `agent`. Quem executa é
a borda, e o executor entra no benchmark por injeção.

O efeito é que dá para avaliar um run lido do disco meses depois, um run de
produção, ou um run de um motor que ainda não existe, sem tocar aqui.
"""
