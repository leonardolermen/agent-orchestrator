"""A entrevista por WebSocket: o chat que compõe a cascata.

**Este módulo GASTA DINHEIRO.** Foi o primeiro da camada HTTP a gastar, e por
um tempo foi o único.

A regra de `api/app.py` era *"nenhum endpoint daqui pode gastar dinheiro"*, e
ela existia para proteger o caminho de EXECUÇÃO: rodar um workflow pela web não
podia virar uma conta. A entrevista foi a primeira exceção, porque ela não
executa nada — ela COMPÕE, e não há como compor conversando sem falar com um
modelo. Hoje `/runs` também gasta, sob as MESMAS três guardas (ver o cabeçalho
de `api/app.py`), e a regra ficou:

    EXECUTAR pela web gasta quando a cascata tem agente, com teto, e o teto é
    dito antes.
    COMPOR por conversa gasta, com teto, e o teto é dito antes.

O custo de ser mais preciso: este endpoint é um caminho pelo qual quem alcança o
servidor gasta o crédito de quem o hospeda. As três guardas abaixo são o que
torna isso aceitável, nenhuma delas é opcional, e são elas que `api/app.py`
copia — este arquivo é a referência citada lá.

**Guarda 1 — teto por entrevista.** `Entrevistador.budget_microcents` já existe
e já é testado; aqui ele é aplicado por conexão, não por processo.

**Guarda 2 — o custo volta em cada desfecho.** `Proposta`, `RecusaFinal` e
`EntrevistaFalhou` carregam `Cost`, e a tela mostra. Gasto que não aparece na
tela é gasto que ninguém revisa.

**Guarda 3 — sem chave, recusa explícita.** Sem `ANTHROPIC_API_KEY` o endpoint
fecha com um motivo legível, em vez de deixar o SDK levantar no meio do laço e
a transcrição do parceiro se perder.

**Por que WebSocket e não POST.** `Entrevistador.entrevistar` recebe
`responder: Callable[[str], str]` — um callback BLOQUEANTE. Reimplementá-lo como
uma máquina de estados sem bloqueio significaria uma segunda cópia do laço, com
o próprio orçamento, o próprio retry de formato e os próprios três desfechos.
Duas cópias de um laço que gasta dinheiro divergiriam, e a que diverge é sempre
a que ninguém testa.

Aqui o laço original roda numa thread e `responder` bloqueia numa fila; o
WebSocket é só o cano. O que a CLI do grill exercita é literalmente o mesmo
código.
"""

import queue
import threading
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from orchestrator.authoring.composicao import para_json
from orchestrator.grill.entrevistador import (
    Entrevistador,
    EntrevistaFalhou,
    Proposta,
    RecusaFinal,
)
from orchestrator.grill.receita import validar_id
from orchestrator.kernel.cost import Cost

# Sentinela para acordar a thread quando o cliente desconecta no meio da
# conversa. Sem ela, `responder` ficaria bloqueado na fila para sempre e a
# thread vazaria — uma por aba fechada.
_DESISTIU = object()

# Sentinela posta no `finally` da thread: ela ACABOU, tenha dito o que disser.
#
# **Defeito real, e ele não é dos testes.** `rodar()` capturava `Exception`, e
# qualquer coisa que escape disso — `BaseException`, e portanto
# `KeyboardInterrupt`, `SystemExit` e a tranca de rede da suíte — matava a
# thread sem pôr nada em `perguntas`. O consumidor ficava bloqueado para sempre
# em `perguntas.get`: num servidor de verdade, uma conexão pendurada que nunca
# responde nem fecha; em CI, um job que queima o timeout inteiro e não diz nada,
# que é o pior sinal que existe. Medido: `PYTEST_EXIT=124`, saída vazia.
#
# A correção não é alargar a captura — alargá-la para `BaseException` engoliria
# justamente o que precisa subir. É garantir que a MORTE da thread, por qualquer
# motivo, acorde quem espera por ela. Uma thread que não pode mais falar tem de
# dizer isso antes de calar.
_MORREU = object()


def _usd(cost: Cost, modelo: str) -> float:
    return cost.microcents(modelo) / 100_000_000


def _sem_chave() -> str | None:
    # Import ADIADO, e pelos dois motivos de uma vez. `api/app.py` importa este
    # módulo no topo, então um import no topo aqui formaria ciclo. E adiado ele
    # resolve o atributo na HORA DA CHAMADA, o que faz "uma leitura só" ser
    # verdade inclusive sob `monkeypatch` — em vez de uma frase sobre produção
    # que o teste desmente. Antes desta linha havia TRÊS leituras de
    # `os.environ` para a mesma pergunta; agora há uma função.
    from orchestrator.api.app import _tem_chave

    if _tem_chave():
        return None
    return (
        "sem ANTHROPIC_API_KEY no ambiente do servidor: a entrevista fala com o "
        "modelo e não tem como começar. Configure a chave e recarregue."
    )


async def conduzir(
    ws: WebSocket,
    *,
    fabrica_entrevistador=None,
    gravar=None,
) -> None:
    """Conduz uma entrevista. Uma conexão, uma entrevista, um teto.

    `fabrica_entrevistador` e `gravar` são injetáveis para teste — é a mesma
    costura que `grill/cli.py` usa, e pela mesma razão: provar os três desfechos
    com `FakeLLMClient`, sem rede e sem um centavo.
    """
    await ws.accept()

    motivo = _sem_chave() if fabrica_entrevistador is None else None
    if motivo:
        await ws.send_json({"tipo": "indisponivel", "motivo": motivo})
        await ws.close()
        return

    try:
        abertura = await ws.receive_json()
    except (WebSocketDisconnect, ValueError):
        return

    workflow_id = str(abertura.get("workflow_id", "")).strip()
    descricao = str(abertura.get("descricao", "")).strip()
    if not descricao:
        await ws.send_json({"tipo": "erro", "motivo": "descreva o que você precisa"})
        await ws.close()
        return

    # O id é validado AQUI, antes de qualquer turno pago — que é a mesma razão
    # pela qual `entrevistar` o valida antes do primeiro turno: descobrir um id
    # inválido no fim desperdiçaria a conversa inteira.
    #
    # Sem isto, o `ValueError` de `validar_id` caía na captura larga da thread e
    # virava `{"tipo": "defeito"}` — que a tela mostra como "erro nosso". É
    # recusa legítima, com uma regra que a pessoa pode atender, e tem de ser
    # dita assim. Achado rodando o primeiro teste.
    try:
        validar_id(workflow_id)
    except ValueError as erro:
        await ws.send_json({"tipo": "erro", "motivo": str(erro)})
        await ws.close()
        return

    entrevistador = (
        fabrica_entrevistador() if fabrica_entrevistador else _entrevistador_real()
    )
    modelo = entrevistador.client.model

    # A ponte entre o laço bloqueante e o WebSocket: a thread põe a pergunta em
    # `perguntas` e espera em `respostas`.
    perguntas: queue.Queue[Any] = queue.Queue()
    respostas: queue.Queue[Any] = queue.Queue()

    def responder(pergunta: str) -> str:
        perguntas.put({"tipo": "pergunta", "texto": pergunta})
        resposta = respostas.get()
        if resposta is _DESISTIU:
            # Aborta o laço de dentro. A `EntrevistaFalhou` resultante carrega a
            # transcrição, que é o contrato do entrevistador — nada se perde por
            # causa de uma aba fechada.
            raise EntrevistaFalhou("o parceiro desconectou", ())
        return str(resposta)

    def rodar() -> None:
        try:
            resultado = entrevistador.entrevistar(workflow_id, descricao, responder)
            perguntas.put(("fim", resultado))
        except EntrevistaFalhou as erro:
            perguntas.put(("falhou", erro))
        except Exception as erro:  # noqa: BLE001
            # Qualquer outra coisa é defeito NOSSO, e vai para a tela dizendo
            # isso — em vez de virar uma desconexão muda que o parceiro leria
            # como "a internet caiu".
            perguntas.put(("defeito", erro))
        finally:
            # A thread acabou. SEMPRE. Ver `_MORREU`: sem esta linha, o que
            # escapa dos `except` acima deixa o consumidor bloqueado para
            # sempre. Posta depois do veredito quando há veredito — a fila é
            # FIFO, o consumidor lê o veredito primeiro e retorna, e esta
            # sentinela fica sem leitor, que é inofensivo.
            perguntas.put(_MORREU)

    thread = threading.Thread(target=rodar, daemon=True)
    thread.start()

    try:
        while True:
            item = await run_in_threadpool(perguntas.get)

            if item is _MORREU:
                # A thread morreu sem veredito. O que a matou já está no
                # `threading.excepthook` (stderr), com traceback — aqui só
                # importa que o parceiro receba uma resposta em vez de uma
                # conexão pendurada. "defeito" e não "falhou": `falhou` é o
                # entrevistador dizendo que não deu, e isto é o servidor
                # dizendo que quebrou.
                await ws.send_json(
                    {
                        "tipo": "defeito",
                        "motivo": (
                            "a entrevista foi interrompida por uma falha que o "
                            "servidor não conseguiu capturar; nada foi gravado"
                        ),
                    }
                )
                await ws.close()
                return

            if isinstance(item, dict):
                await ws.send_json(item)
                try:
                    dados = await ws.receive_json()
                except (WebSocketDisconnect, ValueError):
                    respostas.put(_DESISTIU)
                    return
                respostas.put(str(dados.get("texto", "")))
                continue

            marca, carga = item
            if marca == "fim" and isinstance(carga, Proposta):
                if gravar:
                    try:
                        gravar(carga.composicao)
                    except ValueError as erro:
                        # Gravar pode RECUSAR — hoje por id já tomado no
                        # `registry()` (a mesma recusa que `/api/receitas`
                        # devolve como 409) ou por arquivo já existente. Um
                        # WebSocket não carrega status HTTP, então a recusa
                        # entra pelo desfecho que já existe: `recusa` é
                        # exatamente "não dá, e eis o que faltaria", e a tela
                        # já a mostra assim. Sem esta captura o `ValueError`
                        # subia por `conduzir` e o parceiro via a conexão cair
                        # depois de ter pago a conversa inteira.
                        await ws.send_json(
                            {
                                "tipo": "recusa",
                                "motivo": str(erro),
                                "o_que_faltaria": (
                                    "um id livre: recomece a entrevista com "
                                    "outro id para este workflow"
                                ),
                                "custo_usd": _usd(carga.cost, modelo),
                            }
                        )
                        await ws.close()
                        return
                await ws.send_json(
                    {
                        "tipo": "proposta",
                        # A COMPOSIÇÃO, com as etapas. `receita` aqui deixaria
                        # a tela empilhando todo bloco no primeiro degrau —
                        # que é o que ela fazia enquanto este era o formato.
                        "composicao": para_json(carga.composicao),
                        "custo_usd": _usd(carga.cost, modelo),
                        "transcricao": list(carga.transcricao),
                    }
                )
            elif marca == "fim" and isinstance(carga, RecusaFinal):
                # Recusa NÃO é erro: é o entrevistador dizendo que o que foi
                # descrito não cabe no catálogo. Dizer "o que faltaria" é a
                # parte útil, e é por isso que ela existe no tipo.
                await ws.send_json(
                    {
                        "tipo": "recusa",
                        "motivo": carga.motivo,
                        "o_que_faltaria": carga.o_que_faltaria,
                        "custo_usd": _usd(carga.cost, modelo),
                    }
                )
            elif marca == "falhou":
                await ws.send_json(
                    {
                        "tipo": "falhou",
                        "motivo": str(carga),
                        "transcricao": list(getattr(carga, "transcricao", ())),
                    }
                )
            else:
                await ws.send_json({"tipo": "defeito", "motivo": str(carga)})
            await ws.close()
            return
    finally:
        # Nunca deixa a thread pendurada esperando uma resposta que não vem.
        if thread.is_alive():
            respostas.put(_DESISTIU)


def _entrevistador_real() -> Entrevistador:
    from orchestrator.agent.anthropic_client import AnthropicClient

    return Entrevistador(client=AnthropicClient())
