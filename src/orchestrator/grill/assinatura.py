"""O adaptador de assinatura para a entrevista — Task 10, a última do plano.

**A sonda (Step 1) e o que ela encontrou.**

Rodado contra `claude-agent-sdk` instalado (o mesmo extra `[assinatura]` que
`eval/assinatura.py` já usa)::

    >>> import claude_agent_sdk as s
    >>> [n for n in dir(s) if "Client" in n or "query" in n]
    ['ClaudeSDKClient', 'query']
    >>> import inspect
    >>> inspect.signature(s.ClaudeSDKClient.__init__)
    (self, options: ClaudeAgentOptions | None = None, transport: Transport | None = None)
    >>> inspect.signature(s.ClaudeSDKClient.query)
    (self, prompt: str | AsyncIterable[dict] | None, session_id: str = "default") -> None
    >>> inspect.signature(s.query)
    (*, prompt: str | AsyncIterable[dict], options: ClaudeAgentOptions | None = None, ...)

`ClaudeSDKClient` de fato SUPORTA multi-turno: `connect()` uma vez, depois
`query()`/`receive_response()` repetidos preservam a conversa — mas o
histórico mora no PROCESSO do Claude Code que o SDK sobe (`session_id`,
`resume`, `continue_conversation`), nunca numa lista que o chamador constrói,
inspeciona e devolve. Não existe um método com a forma que `LLMClient` exige:

- `complete(system, messages, tools) -> LLMResponse` recebe `system`,
  `messages` (histórico REPLICADO pelo chamador — é o que `blocos_assistente`
  em `agent/llm.py` existe para produzir) e `tools` (schemas JSON) a CADA
  chamada, e devolve UM turno cru do assistente: texto e `tool_calls` NÃO
  executadas, para o chamador decidir o que fazer.
- `ClaudeSDKClient.query()`/`connect()` recebem só um `prompt` (string ou um
  fluxo assíncrono de dicts num envelope próprio do SDK —
  `{"type": "user", "message": {...}, "parent_tool_use_id": None,
  "session_id": ...}`, documentado no docstring de `query()`, não o formato
  de `messages` da Messages API). Não há parâmetro para passar histórico
  replicado nem lista de ferramentas por chamada.
- Ferramentas no SDK são registradas como servidor MCP com handlers Python
  (é o que `eval/assinatura.py._montar_servidor` já faz) e EXECUTADAS pelo
  próprio SDK dentro do laço interno dele — o chamador nunca recebe uma
  `tool_call` pendente para inspecionar e decidir.

Isso quebra exatamente a costura de que a entrevista depende. O laço em
`entrevistador.py` intercepta a chamada de ferramenta "Pergunta" ANTES de
qualquer coisa ser executada, pausa para chamar `responder()` — que fala com
um humano, fora do SDK — e só então constrói o `tool_result` e chama
`complete()` de novo, mais o histórico crescido. Para reproduzir isso sobre
`ClaudeSDKClient` seria preciso: (a) registrar "Pergunta" como ferramenta MCP
cujo handler assíncrono chama `responder()` por dentro — o que moveria o
controle da entrevista para dentro do handler da ferramenta, invertendo quem
manda no laço; e (b) abrir mão inteiramente do formato `messages`/`tools`
por chamada que `LLMClient` promete a QUALQUER cliente — inclusive ao
`FakeLLMClient` que prova o laço hoje sem rede. Nenhuma das duas é "usar o
SDK sobre o protocolo"; as duas são reescrever o protocolo em torno do SDK,
o que o brief da Task 10 explicitamente proíbe (o entrevistador muda UMA
classe, nenhum outro arquivo).

**Decisão:** não há, no `claude-agent-sdk` instalado, um cliente que aceite
turnos sucessivos com histórico REPLICADO pelo chamador (`messages` +
`tools` por chamada, resposta com `tool_calls` cruas). `ClienteAssinatura`
é portanto um alias documentado do cliente de chave de API já provado em
`agent/anthropic_client.py` — mesmo desfecho que `eval/assinatura.py`
registrou como aceitável para o Investigador (linha "não farei a chamada
real..." em `DECISOES.md`, Plano 2), agora estendido à entrevista. Ver
`docs/superpowers/DECISOES.md`, seção "Plano 5", para o registro formal.

Consequência prática: rodar `orchestrator-grill` gasta crédito de API (chave
em `ANTHROPIC_API_KEY`), não a assinatura do Claude Code. O nome do módulo
e da classe ficam como o plano pediu — "assinatura" é o VOCABULÁRIO do
plano para "o adaptador que fala com um modelo de verdade", não uma garantia
de que o transporte seja a assinatura pessoal.
"""

from orchestrator.agent.anthropic_client import AnthropicClient


class ClienteAssinatura(AnthropicClient):
    """`LLMClient` de verdade para a entrevista — hoje, o cliente de chave de
    API por baixo. Ver o docstring do módulo para a sonda que levou a essa
    escolha e a limitação exata que a descartou de usar o SDK do Claude Code.
    """
