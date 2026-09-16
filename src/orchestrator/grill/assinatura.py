"""O adaptador de assinatura para a entrevista — Task 10, a última do plano.

**Rodada de correção 1.** A primeira versão deste docstring afirmava que "o
chamador nunca recebe uma `tool_call` pendente" e que o histórico "nunca"
fica numa lista que o chamador replica. As duas são FALSAS — refutadas por
execução, não por leitura de assinatura. O que segue é o resultado
re-sondado com código rodado de verdade (`Transport` falso, zero rede, zero
subprocesso — os experimentos, reproduzíveis, viviam em
`sonda_sdk.py`/`sonda_sdk2.py` no scratchpad da sessão que fez a revisão).

**O que o SDK EXPÕE de verdade (provado por execução).**

1. Interceptação de ferramenta ANTES da execução — dois caminhos:
   - `ClaudeAgentOptions.can_use_tool` (tipo `CanUseTool`, `types.py`): um
     callback assíncrono chamado com `(tool_name, tool_input,
     ToolPermissionContext)` — `ToolPermissionContext.tool_use_id` garantido
     não-nulo pelo protocolo — ANTES de qualquer execução. Confirmado
     despachando o frame `control_request`/`can_use_tool` direto em
     `Query._handle_control_request`: o callback recebeu
     `{"nome": "Pergunta", "entrada": {"texto": "..."}, "tool_use_id":
     "toolu_abc123"}`.
   - Hook `PreToolUse` devolvendo `{"hookSpecificOutput": {"hookEventName":
     "PreToolUse", "permissionDecision": "defer"}}`: o turno PARA sem
     executar a ferramenta, e a chamada não-executada volta em
     `ResultMessage.deferred_tool_use` — `DeferredToolUse(id, name, input)`
     (`types.py`, classe `DeferredToolUse`, campo documentado como "Tool use
     that was deferred by a PreToolUse hook"). Confirmado: o hook recebeu o
     `tool_input` completo, e um frame `result` sintético com
     `deferred_tool_use` populado foi parseado de volta num
     `DeferredToolUse` real via `message_parser.parse_message`.
   - **Armadilha, achada pela revisão dentro do próprio isolamento que este
     brief manda usar:** `permission_mode="bypassPermissions"` desativa
     `can_use_tool` EM SILÊNCIO — o SDK emite
     `CanUseToolShadowedWarning("can_use_tool will not be invoked:
     permission_mode 'bypassPermissions' auto-approves every tool call ...
     before the callback is consulted. To gate every tool call, use a
     PreToolUse hook instead.")`. Ou seja: com o isolamento que a Task 10
     exige, só o caminho do hook `PreToolUse` + `"defer"` funciona — o
     caminho `can_use_tool` está fechado por uma opção que o próprio brief
     manda ligar.
2. Histórico montado pelo CHAMADOR, não pelo processo — `SessionStore`
   (`InMemorySessionStore` publicamente exportado), `ClaudeAgentOptions.
   session_store` + `resume`, e `import_session_to_store`/
   `materialize_resume_session`: um transcript INVENTADO na hora (três
   linhas JSONL fabricadas — user, assistant com `tool_use`, user com
   `tool_result` — nunca produzidas por uma sessão real) foi aceito e
   materializado com sucesso como histórico de uma sessão retomada
   (`resume_session_id` bateu com o id fabricado).

**O que continua faltando — e é por isso que a decisão é de CUSTO, não de
impossibilidade.** Não existe um `complete(system, messages, tools) ->
LLMResponse` pronto — um método que aceite a Messages API (`system`,
`messages`, `tools` como JSON Schema) por chamada e devolva um turno cru.
Construí-lo por cima do que existe exigiria:

- Serializar o histórico no formato de transcript INTERNO do CLI a cada
  chamada — não a Messages API que `AnthropicClient`/`FakeLLMClient` falam.
  `SessionStoreEntry` (`types.py`) documenta o próprio formato como "the
  CLI's on-disk transcript format (a large discriminated union) ... That
  union is internal" — acoplar `ClienteAssinatura` a isso é acoplar a algo
  que o próprio pacote se recusa a versionar como contrato público.
- Ou manter uma sessão `ClaudeSDKClient` viva (via `connect()`) pela
  entrevista inteira, com a interceptação de "Pergunta" vivendo dentro de um
  hook `PreToolUse` assíncrono — o que move o ponto de controle da
  entrevista para dentro do ciclo de vida do SDK (registro de hook, resposta
  ao `control_request`, resumo do turno) em vez do laço síncrono e trivial
  de inspecionar que `LLMClient.complete()` dá hoje a QUALQUER
  implementação, inclusive ao `FakeLLMClient` que prova o laço inteiro sem
  rede.
- Um subprocesso do Claude Code por entrevista (ou por turno, se a sessão
  não for mantida viva) — custo de latência e de operação que
  `AnthropicClient` não paga.

Nenhuma dessas três é "impossível" — as três são reescrever a costura do
protocolo em torno do ciclo de vida do SDK (subprocesso, hooks assíncronos,
formato de transcript interno), o que o brief da Task 10 proíbe para esta
tarefa (o entrevistador muda UMA classe, nenhum outro arquivo) e que carrega
risco de quebra silenciosa numa versão futura do SDK, por depender de um
formato que o próprio pacote declara não-público.

**Decisão:** `ClienteAssinatura` é um alias documentado do cliente de chave
de API já provado em `agent/anthropic_client.py` — ele já satisfaz
`LLMClient` exatamente, sobre um formato de fio estável e público (a
Messages API), sem subprocesso. Mesmo desfecho que `eval/assinatura.py`
registrou como aceitável para o Investigador (P2.27 em `DECISOES.md`, Plano
2 — "não farei a chamada real..."), agora estendido à entrevista, mas por um
motivo diferente e mais estreito: lá era dinheiro do dono; aqui é também
acoplamento a uma API interna não versionada. Ver
`docs/superpowers/DECISOES.md`, seção "Plano 5" (P5.1), para o registro
formal — incluindo a alternativa rejeitada e por que ela é reversível.

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
