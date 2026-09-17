"""Isolamento global de fila para toda a suíte.

Dois módulos guardam uma raiz de fila em atributo de módulo (`_RAIZ_FILA`) que
por padrão cai em `Path("data")`, relativo ao CWD: `orchestrator.api.app` e
`orchestrator.eval.agent_eval`. Sem isolar essa raiz, qualquer teste que passe
por eles (direto ou via `TestClient`) lê e escreve em `data/fila/`, que é
exatamente onde `orchestrator-eval --fila` e o `/fila.html` de uma sessão
normal do desenvolvedor deixam `*.jsonl` — e tudo sob `data/` é ignorado pelo
`.gitignore` (allowlist, desde esta fatia; antes era a regra `*.jsonl`, que
cobria a fila por acidente do formato), então o CI nunca vê o problema e só a
máquina local falha, sem nada em `git status` para apontar a causa.

Esta fixture é autouse e cobre toda a suíte, não só `tests/api/`: qualquer
teste futuro que chame `avaliar(..., gravar_fila=True)` ou bata numa rota da
API herda o isolamento sem precisar lembrar de pedir.

Desde o PR #7 ela isola também o `RunStore`, que vive sob a MESMA raiz
(`api.app._run_store()`). Sem isso a suíte passaria a escrever
`data/runs.jsonl` na máquina do desenvolvedor — o mesmo defeito que esta
fixture existe para impedir, com um arquivo novo.

O `cache_clear()` do `_executar` sumiu junto com a memoização: não há
mais cache para invalidar.
"""

import pytest


@pytest.fixture(autouse=True)
def _raiz_da_fila_isolada(tmp_path, monkeypatch):
    try:
        import orchestrator.api.app as api_app
    except ImportError:
        # fastapi é extra opcional (`pyproject.toml`, grupo `api`); sem ele,
        # os próprios testes de API já se pulam via `pytest.importorskip`.
        api_app = None
    if api_app is not None:
        monkeypatch.setattr(api_app, "_RAIZ_FILA", tmp_path)

    import orchestrator.eval.agent_eval as agent_eval

    monkeypatch.setattr(agent_eval, "_RAIZ_FILA", tmp_path)

    yield


class RedeProibida(BaseException):
    """Um teste chegou a construir o cliente REAL da Anthropic.

    **Deriva de `BaseException`, e isso é a peça inteira.** Todo caminho pago
    deste repositório passa por `agent/conversa.py`, que captura `Exception` em
    volta de `client.complete()` — de propósito, para que uma falha de rede vire
    abstenção em vez de derrubar um fechamento por causa de um item. Uma guarda
    que levantasse `AssertionError` seria engolida por essa captura exatamente
    como uma falha de rede: o teste veria 200, a suíte ficaria verde, e a
    chamada paga teria acontecido. Medido — foi assim que os quatro testes
    abaixo passaram a ir à rede sem ninguém notar.
    """


@pytest.fixture(autouse=True)
def _rede_proibida(monkeypatch):
    """NENHUM teste fala com a API de verdade. Estrutural, não por disciplina.

    **O defeito que esta fixture existe para impedir foi MEDIDO, não imaginado.**
    Quando `/runs` passou a poder executar cascatas pagas, quatro testes que
    postavam sobre um workflow com agente continuaram verdes na máquina onde
    `ANTHROPIC_API_KEY` está ausente — e, com a variável preenchida, o mesmo
    POST construía um cliente de verdade e ia à rede. A rota devolvia 200,
    porque a falha virava abstenção; numa conta com chave VÁLIDA teria gastado
    dinheiro em silêncio.

    "Não gasta porque a variável não está posta" não é garantia: é a ausência de
    uma garantia, na máquina de quem escreveu o teste.

    **A costura é `anthropic.Anthropic`**, e não `AnthropicClient._cliente` nem
    `complete`: é o construtor do SDK, o ponto exato onde "falar com a API"
    deixa de ser hipótese. Patchá-lo aqui deixa intacto o único teste que
    precisa exercitar `_cliente()` de verdade
    (`test_cliente_real_configura_timeout_e_tentativas`, que troca a mesma
    classe pela sua própria e, sendo o patch mais recente, vence), e deixa
    intacta a injeção de `sdk` que `tests/agent/test_anthropic_client.py` usa
    para provar o protocolo de mensagens sem rede.
    """
    import anthropic

    def _proibido(*args, **kwargs):
        raise RedeProibida(
            "um teste chegou a construir o SDK real da Anthropic. nenhum teste "
            "pode falar com a API paga: injete um `sdk`, use `FakeLLMClient`, "
            "ou troque `_cliente_de_execucao`/`_tem_chave` por um dublê"
        )

    monkeypatch.setattr(anthropic, "Anthropic", _proibido)
