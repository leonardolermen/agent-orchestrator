"""A ordem entre classes de custo.

Esta enum é o mecanismo que impede a armadilha mais cara do produto: montar
uma cascata que chama inteligência antes de tentar a regra de graça. A ordem
não é uma convenção que alguém segue — é o valor pelo qual a cascata é
ordenada, e não existe entrada que a inverta.
"""

from enum import IntEnum


class CostClass(IntEnum):
    REGRA = 0
    AGENTE = 1
    HUMANO = 2
