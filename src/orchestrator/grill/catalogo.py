"""A tranca que impede qualquer construção do grill de falar com um modelo.

Até aqui este módulo também era O catálogo — a tabela `CATALOGO` de resolvers
proponíveis pela entrevista. Essa tabela era só os cinco blocos da conciliação
(`L1`, `L2`, `L3`, `agente`, `revisor`), sem noção de domínio — e é ela que a
fatia do quadro em branco removeu: `grill.receita` e `grill.ferramentas`
passaram a compor do catálogo PLANO
(`orchestrator.domains.registro.CATALOGO`), que junta as três origens. O porquê
está em `docs/superpowers/specs/2026-09-17-quadro-em-branco-design.md` (§1 —
"Há DOIS catálogos, e é por isso que o chat erra").

O que sobra aqui é ortogonal ao catálogo: `ClienteAusente` é o sentinela que
`grill.receita.construir` usa como cliente DEFAULT — permite desenhar (e
validar) uma cascata com um bloco pago sem que exista caminho de execução paga
atrás de um endpoint. Ele continua com consumidor fora deste arquivo (o
próprio `grill.receita`, mais `api/app.py` e os testes que espionam
`ClienteAusente.complete` para provar que o modelo nunca é chamado por um
endpoint), então o arquivo fica — só sem o cardápio.
"""

from typing import Any

from orchestrator.agent.llm import LLMResponse

# Um modelo REAL da tabela de preços, de propósito: `Agent.__post_init__` e
# `Investigator.__post_init__` chamam `Cost.zero().microcents(self.client.model)`
# e um nome inventado faria a construção levantar — o que impediria até de
# DESENHAR um workflow com agente.
MODELO_INERTE = "claude-opus-5"


class ClienteAusente:
    """`LLMClient` sentinela: existe para ser construído, nunca para ser chamado.

    É o que permite DESENHAR um resolver pago — listar, validar, servir a forma
    da cascata — sem que a construção abra caminho até o modelo.

    **Continua sendo a tranca, e agora ela tem exatamente uma chave.** Enquanto
    `/runs` recusava toda cascata paga com 409, o sentinela cobria o módulo
    HTTP inteiro. Hoje executar com agente é possível, e o único ponto que
    desarma a tranca é `api/app.py::_cliente_de_execucao` — chamado só quando a
    cascata tem agente e só quando há chave. Todo o resto (`/api/receitas`,
    `/api/composicoes`, `GET /api/workflows`, `GET /api/workflows/{id}`)
    constrói com este sentinela, e um `RuntimeError` daqui é o sinal de que
    algum caminho novo chegou ao modelo por onde não deveria haver caminho.
    """

    model: str = MODELO_INERTE

    def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        raise RuntimeError(
            "ClienteAusente.complete() foi chamado: algum caminho de execução "
            "chegou ao modelo por onde não deveria existir caminho nenhum"
        )
