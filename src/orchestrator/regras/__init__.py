"""Regras determinísticas que não conhecem domínio nenhum.

Uma regra sempre foi CÓDIGO neste projeto, e o comentário de `RegraDisponivel`
explicava por quê: "casar por documento e valor é lógica de domínio; não há
declaração que a substitua". O mesmo comentário reservava a saída — "tipos de
regra genéricos, quando existirem, entram aqui como mais entradas, sem mudar
este contrato". Este pacote é isso.

**O que muda de lugar.** Continua sendo código; o que sai do código são os
NOMES DOS CAMPOS. `ExactMatcher` lê `be.document` porque sabe que ali vem um
`BankEntry`; `Igualdade` lê o campo que quem montou o workflow escolheu na
tela. É a mesma jogada que o agente já tinha feito — `AgentSpec` declara
prompt, ferramentas e modelo como dados, e o laço é genérico —, agora do lado
determinístico.

**A camada.** `regras` importa só `kernel`, como `sources`. Ela não conhece
domínio (seria o defeito que ela existe para corrigir) e domínio nenhum precisa
conhecê-la para funcionar — quem a usa é quem COMPÕE, e a conciliação a usa
apenas como qualquer outro domínio poderia.
"""

from orchestrator.regras.campos import CampoAusente, valor_do_campo
from orchestrator.regras.igualdade import Igualdade
from orchestrator.regras.pares import Par
from orchestrator.regras.tolerancia import Tolerancia

__all__ = ["CampoAusente", "Igualdade", "Par", "Tolerancia", "valor_do_campo"]
