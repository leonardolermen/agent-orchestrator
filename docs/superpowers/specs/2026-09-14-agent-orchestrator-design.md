# Agent Orchestrator — Documento de Design

**Data:** 2026-09-14
**Status:** Design aprovado em partes; aguardando revisão integral
**Autor:** Leonardo Lermen
**Nome:** de trabalho. Marca a definir quando houver cliente.

---

## 0. Sumário executivo

Construir um **runtime para transformar processos de backoffice financeiro em execução confiável e auditável**, onde o workflow é determinístico e o agente de IA entra apenas onde inteligência é genuinamente necessária.

A plataforma genérica é o destino, não o ponto de partida. O caminho é: resolver um processo real de ponta a ponta, resolver um segundo para o mesmo comprador, e **extrair** a abstração de runtime a partir das instâncias — nunca projetá-la a partir de zero.

**V1:** investigação de divergência em conciliação financeira.
**V2:** procurement (mesmo comprador, mesma pilha documental).
**V3:** a plataforma, extraída.

**Restrições que moldam tudo:** um desenvolvedor, 10-15h/semana, sem acesso a dado real de terceiros, meta de cliente pagante em 12 meses.

---

## 1. Contexto e tese

### 1.1 O problema

Colocar agentes de IA em produção falha por três motivos, em ordem de frequência:

1. **Custo desproporcional.** Encadeamentos de agentes gastam dólares para resolver o que uma query resolve por centavos. A arquitetura multi-agente é aplicada uniformemente a um problema que é heterogêneo.
2. **Erro silencioso.** O agente não trava — ele responde errado, com confiança, e ninguém percebe até o dano aparecer a jusante.
3. **Ausência de trilha.** Quando alguém pergunta "por que o sistema decidiu isso?", não há resposta auditável.

Note que "o processo morreu no meio" — o problema que durable execution resolve — não está nessa lista. Ele é real, mas aparece depois, e só em processos longos.

### 1.2 Por que agora

A camada de **orquestração** de agentes virou commodity: CrewAI, LangGraph, AutoGen, Agents SDK e outros resolvem "faça N agentes conversarem". A camada de **execução confiável** não. Mas ela também já tem ocupantes sérios do lado genérico (Temporal, Restate, DBOS, Inngest, LangGraph Platform), o que significa que construir mais um runtime genérico é entrar na briga pelo lado errado.

O espaço aberto é a interseção: **execução confiável aplicada a um domínio onde a confiabilidade é exigência regulatória, não conforto.**

### 1.3 Por que Brasil

Não é geografia — é que a pilha documental e regulatória brasileira é idiossincrática e exige trabalho local que fornecedor de fora não faz:

- NF-e / NFS-e (XML estruturado, mas com regras municipais divergentes)
- SPED, ECD, EFD
- CNAB 240/400, extratos OFX de bancos nacionais
- Retenções na fonte: ISS, IRRF, PIS/COFINS/CSLL, INSS
- Pix e seus modos (agendado, automático, devolução)
- ERPs nacionais (TOTVS, Senior, Sankhya) e suas exportações
- LGPD

Um agente genérico não sabe o que é retenção de ISS na fonte nem lê um arquivo CNAB 240. Essa ignorância é o fosso. Em "agentes genéricos" não haveria fosso nenhum.

### 1.4 Posicionamento frente às alternativas

| Alternativa | Como se compara |
|---|---|
| CrewAI / LangGraph / AutoGen | Resolvem orquestração. Não resolvem domínio, avaliação nem auditoria. Podem ser usados por baixo se conveniente. |
| Temporal / Restate / DBOS | Resolvem durabilidade genérica muito melhor do que construiríamos. Adotar quando fizer falta, não competir. |
| Planilha + analista | O incumbente real. É contra isso que o valor é medido, não contra software. |
| ERP nativo | Faz matching determinístico. Não investiga o que não casou — devolve a exceção para o humano. É exatamente essa lacuna que atacamos. |
| Consultoria / BPO | Vende hora. Nosso argumento é custo marginal por divergência, não hora. |

---

## 2. Estratégia de produto

### 2.1 Produto antes de plataforma

**Princípio:** a abstração correta se extrai de instâncias; não se projeta a partir de zero.

Tentar desenhar o runtime primeiro produz um framework que resolve bem o caso imaginado e mal o caso real. O compromisso deste projeto é: **nenhuma abstração de plataforma é criada antes de existirem três usos concretos que a justifiquem.**

Isso não impede que o código seja bem estruturado. Impede que ele seja *genérico* cedo demais. As costuras (seção 3.3) existem para tornar a extração barata quando chegar a hora — não para antecipá-la.

### 2.2 Sequência de verticais

| Ordem | Vertical | Razão |
|---|---|---|
| 1 | **Finance Ops** — conciliação | Dor mensurável, output verificável, dado sintetizável com gabarito |
| 2 | **Procurement** | Mesmo comprador (CFO), mesma pilha documental (contrato, NF, fornecedor), mesma exigência de aprovação. Estende em vez de recomeçar. |
| 3 | **Plataforma** | Extraída das duas anteriores mais o terceiro processo que aparecer |

#### Verticais não-comerciais

Nem toda vertical precisa gerar receita para merecer lugar no projeto. **Software Engineering** entra por dois motivos que não são venda:

- **Dogfooding.** É o único domínio onde o autor é seu próprio usuário. O atrito da abstração é sentido na pele, imediatamente, sem ciclo de venda e sem intermediário. Nas outras verticais esse sinal é caro; nesta é gratuito.
- **Critério de aceitação da plataforma.** Se a abstração extraída no V3 não conseguir expressar um fluxo `issue → plano → código → teste → revisão → PR`, ela é estreita demais. Isso é um teste de generalidade que se pode rodar sem vender nada a ninguém.

Como vertical comercial ela permanece fraca — mercado saturado (Cursor, Devin, Copilot, Claude Code) e difícil sustentar preço. Mas essa avaliação só se aplica a vendê-la, e vendê-la não é o objetivo aqui.

**Gatilho:** usada como lente de design desde já; construída como produto apenas depois de V1 e V2 estarem pagos.

**Risco a vigiar, nomeado de propósito:** esta vertical é divertida e conciliação é chata. É exatamente assim que um projeto solo perde o foco da vertical que paga. A lente de design não pode virar desvio de escopo — se ela começar a consumir horas de construção antes de V1 entregar, o gatilho foi violado.

Adiada, sem papel definido:

- **E-commerce Ops** — fraude e estoque são latência-sensíveis, com incumbentes estabelecidos; a fatia onde IA agrega é mais fina do que aparenta.

### 2.3 Critérios de sucesso por fase

| Fase | Critério objetivo |
|---|---|
| F1 — Núcleo funcionando | Matching determinístico resolve ≥85% dos casos sintéticos; agente produz proposta com evidência nos demais |
| F2 — Qualidade medida | Precisão ≥90% nas propostas aceitas; taxa de abstenção explícita e estável; custo <R$0,50 por divergência investigada |
| F3 — Validação externa | 3 profissionais de backoffice avaliam saídas sobre dado sintético e concordam que economizaria tempo real |
| F4 — Primeiro cliente | Alguém assina contrato pago |

Validação sem alguém assinando cheque engana. F3 não substitui F4.

---

## 3. Norte arquitetural (onde isso chega)

Esta seção descreve o destino. **Nada aqui é construído no v1** — está registrado para que as decisões do v1 não fechem portas.

### 3.1 O runtime

```
                    APLICAÇÃO CLIENTE
                           │
                           ▼
                 ┌───────────────────┐
                 │   AGENT RUNTIME   │
                 └─────────┬─────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
    Workflow            Agents             Tools
        │                  │                  │
     Estado             Memória            APIs
     Retry              Contexto           Banco
     Resume             Modelo             Código
     Timeout            Skills             Browser
        │                  │                  │
        └──────────────────┼──────────────────┘
                           ▼
                   Aprovação humana
                           ▼
                       RESULTADO
```

### 3.2 Capacidades do runtime, priorizadas por gatilho

A lista original de capacidades desejadas, organizada por **o que precisa ser verdade para cada uma valer o custo**. Esta tabela é o coração do documento: ela transforma uma lista de desejos em um plano.

**Tier 1 — no v1, porque o valor existe desde o primeiro dia**

| Capacidade | Por que já |
|---|---|
| Trace por unidade de trabalho | Sem isso não há depuração nem auditoria |
| Contabilidade de custo | O argumento comercial central é custo por divergência |
| Limite de orçamento (hard cap) | Um loop de agente pode gastar muito, rápido |
| Retry com backoff | Falha de API de LLM é rotina, não exceção |
| Timeout | Idem |
| Idempotência de ingestão | Reprocessar o mesmo extrato não pode duplicar nada |
| Trilha de auditoria | Subproduto do matching em camadas; ver 4.3 |

**Tier 2 — quando o sistema passar a escrever em sistemas de terceiros**

| Capacidade | Gatilho |
|---|---|
| Aprovação humana formalizada | Já existe no v1 como fila; vira máquina de estado quando houver efeito colateral |
| Permissões por agente | Quando houver mais de um perfil de usuário |
| Gestão de segredos | Quando houver credencial de cliente, não só nossa |
| Compensação / rollback | Quando uma ação for irreversível. **No v1 não existe: ferramentas são somente-leitura.** |

**Tier 3 — quando houver processo longo (dias, não minutos)**

| Capacidade | Gatilho |
|---|---|
| Durable execution | Processo que atravessa dias e não pode reiniciar do zero |
| Checkpoint / resume | Idem |
| Replay | Idem |

> **Decisão:** ao atingir o Tier 3, adotar Temporal, Restate ou DBOS. Não construir. Reimplementar event sourcing é trabalho de muitos meses que não é nosso diferencial.

**Tier 4 — quando houver múltiplos clientes ou código de terceiros**

| Capacidade | Gatilho |
|---|---|
| Sandbox de execução | Quando executarmos código que não escrevemos |
| Rate limiting | Quando houver multi-tenant |
| Versionamento de workflow | Quando houver execução em voo durante um deploy |
| RBAC | Quando o cliente pedir |

**Descartado explicitamente:** marketplace de agentes. Marketplace exige demanda antes de oferta. Reavaliar apenas com 10+ clientes pedindo.

### 3.3 As costuras que preservam o caminho

Três interfaces no v1, definidas justamente nos pontos onde o projeto vai querer mudar de ideia:

| Interface | No v1 | Depois pode virar |
|---|---|---|
| `Executor` | Função in-process, síncrona | Workflow Temporal/Restate, sem tocar no domínio |
| `ToolRegistry` | Dicionário de funções com schema | Ferramentas remotas, MCP, sandbox |
| `LLMClient` | Cliente único | Roteamento por modelo, fallback, cache |

Regra: **o código de domínio (matching, taxonomia, avaliação) nunca importa nada dessas três interfaces diretamente.** Ele recebe por injeção. É isso que torna a extração barata.

---

## 4. V1 — Investigação de divergência em conciliação

### 4.1 Escopo

**Entra:** ingestão de extrato bancário e razão contábil; matching determinístico em camadas; investigação por agente do que não casou; proposta com evidência e confiança; fila de revisão humana; realimentação da correção no benchmark.

**Não entra:** escrita em qualquer sistema externo; multi-tenant; interface web elaborada; integração com ERP real; contas a pagar; qualquer DSL.

### 4.2 Arquitetura

```
ingest ──→ matching ──→ investigation ──→ review ──→ eval
              │              │              │          ▲
              │              │              └──────────┘
        (não sabe que    (não sabe que    correções realimentam
         agente existe)   humano existe)   o benchmark
```

Cada módulo é testável isoladamente e ignora a existência do seguinte. A dependência é sempre para trás, nunca para frente.

### 4.3 A fronteira código/agente

Esta é a decisão de produto mais importante do projeto.

| Camada | Regra | Custo |
|---|---|---|
| L1 | Exato: valor + data + identificador | ~0 |
| L2 | Tolerância configurável; padrão valor ± R$ 0,05 e data ± 3 dias úteis | ~0 |
| L3 | Agrupamento n:1 e 1:n (um TED cobrindo várias notas) | ~0 |
| L4 | Sobrou → acorda o agente | $$ |

Cada camada registra **por que** casou, com a regra e os valores que a satisfizeram. A trilha de auditoria sai como subproduto, não como funcionalidade construída depois.

**Regra inviolável:** o agente não faz matching. Se a taxa de casos que chegam ao L4 subir, a resposta é melhorar L1-L3, não dar mais trabalho ao agente.

### 4.4 Modelo de dados

Entidades centrais, em modelo canônico independente de fonte:

- **`BankEntry`** — lançamento de extrato: data, valor, descrição, documento, contraparte, identificador de origem, hash de idempotência
- **`LedgerEntry`** — lançamento contábil: data de competência, data de caixa, valor bruto, valor líquido, conta, centro de custo, documento fiscal, fornecedor
- **`MatchResult`** — vínculo entre conjuntos de `BankEntry` e `LedgerEntry`, com a camada que o produziu e a justificativa
- **`Divergence`** — o que não casou, com o contexto candidato
- **`Proposal`** — saída do agente: explicação, tipo de divergência sugerido, evidência citada, nível de confiança, custo incorrido
- **`Decision`** — ato humano: aceitar, rejeitar, corrigir; com o motivo
- **`EvalCase`** — caso sintético com gabarito, ou caso real promovido a partir de uma `Decision`

Valores monetários em inteiro de centavos. Nunca ponto flutuante.

### 4.5 Taxonomia de divergências

Esta taxonomia é conhecimento de domínio e constitui parte substancial da propriedade intelectual do projeto. Serve para três coisas: guiar o gerador sintético, estruturar a saída do agente, e medir cobertura.

| Tipo | Descrição |
|---|---|
| `RETENCAO_IMPOSTO` | Líquido difere do bruto por ISS, IRRF, PIS/COFINS/CSLL ou INSS |
| `PAGAMENTO_AGREGADO` | Um crédito/débito cobre N documentos |
| `PAGAMENTO_PARCIAL` | Valor menor que o documento, saldo em aberto |
| `TARIFA_BANCARIA` | Tarifa descontada na liquidação |
| `JUROS_MULTA` | Acréscimo por atraso |
| `DESCONTO_ANTECIPACAO` | Abatimento por pagamento antecipado |
| `DEFASAGEM_TEMPORAL` | Competência versus caixa; D+1, D+2, fim de semana, feriado |
| `DUPLICIDADE` | Mesmo documento lançado duas vezes |
| `ESTORNO` | Devolução total ou parcial |
| `DEVOLUCAO_FUNDOS` | TED, Pix ou cheque devolvido. **Alta frequência, confirmada em campo.** |
| `DIFERENCA_CAMBIAL` | Variação entre contratação e liquidação |
| `ERRO_DIGITACAO` | Transposição de dígitos, vírgula deslocada |
| `CONTA_INCORRETA` | Lançado em conta ou centro de custo errado |
| `NAO_IDENTIFICADO` | Nenhuma hipótese com confiança suficiente |

`NAO_IDENTIFICADO` é resposta legítima e deve ser barata.

#### Eventos de múltiplas pernas

`DEVOLUCAO_FUNDOS` não é um lançamento divergente isolado — é uma cadeia: o débito sai, o crédito volta, e frequentemente um reenvio corrigido ocorre dias depois. Três linhas do extrato compõem um evento só.

Isso impõe um requisito ao modelo de dados que os outros tipos não impõem: `MatchResult` precisa vincular **conjuntos** de `BankEntry` a conjuntos de `LedgerEntry`, nunca par a par. O mesmo vale para `PAGAMENTO_AGREGADO`. Tratar matching como relação 1:1 e depois generalizar seria reescrita, então a cardinalidade n:m é assumida desde o primeiro dia.

#### A taxonomia é aberta por design

Esta lista foi montada de conhecimento geral mais uma confirmação de campo (`DEVOLUCAO_FUNDOS`). **Ela está certamente incompleta**, e a resposta honesta a isso não é inventar mais tipos para parecer completa — é construir o mecanismo que encontra os que faltam.

Candidatos levantados mas não confirmados, deliberadamente fora da lista até que apareçam: transferência entre contas próprias, aplicação e resgate financeiro, antecipação de recebíveis com deságio, encontro de contas, pagamento por terceiro, split de adquirente, bloqueio judicial.

**Mecanismo de descoberta.** `NAO_IDENTIFICADO` não é só um fallback — é o canal por onde um tipo ausente se anuncia. Duas fontes de sinal:

1. **Agrupamento dos não identificados.** Se casos marcados `NAO_IDENTIFICADO` se repetem com estrutura parecida, há um tipo faltando. Revisão periódica desse conjunto é tarefa recorrente, não eventual.
2. **Correção humana para "nenhum destes".** Quando o revisor rejeita a proposta sem conseguir escolher um tipo existente, isso é evidência direta de lacuna.

**Requisito de extensibilidade:** adicionar um tipo deve custar uma entrada na taxonomia, um gerador de caso sintético e uma linha na métrica de cobertura — nunca mudança estrutural. Se adicionar um tipo exigir refatoração, o desenho está errado.

### 4.6 O agente

**Ferramentas — todas somente-leitura no v1:**

| Ferramenta | Retorna |
|---|---|
| `buscar_lancamentos` | Lançamentos contábeis por filtro (data, valor, fornecedor) |
| `buscar_documento_fiscal` | Dados de NF por número, fornecedor ou valor |
| `historico_fornecedor` | Padrão histórico de pagamento daquele fornecedor |
| `calcular_retencao` | Cálculo determinístico de retenções sobre um bruto |
| `calendario_bancario` | Dias úteis, feriados, previsão de liquidação |

`calcular_retencao` é deliberadamente uma ferramenta e não um raciocínio do modelo: cálculo fiscal precisa ser exato e testável.

**Contrato de saída — estruturado, nunca texto livre:**

```
Proposal {
  divergence_id
  tipo: <um valor da taxonomia>
  explicacao: texto curto para humano
  evidencia: [referências concretas a registros consultados]
  confianca: alta | media | baixa
  acao_sugerida: conciliar_com(ids) | ajustar(valor) | investigar_manual
  custo: { tokens, chamadas, reais }
}
```

**Abstenção é cidadã de primeira classe.** Uma proposta errada com confiança alta destrói a credibilidade mais rápido do que dez abstenções. Num produto que um contador vai auditar, essa é a diferença entre adoção e desligamento.

**O agente recebe apenas a divergência e o contexto que ele próprio solicitar via ferramenta** — nunca o conjunto inteiro. Isso é custo e qualidade simultaneamente.

### 4.7 Revisão humana

Fila simples. Para cada divergência: a proposta, a evidência citada de forma navegável, e três ações — aceitar, rejeitar, corrigir.

A corrigir é a mais importante das três: é ela que gera sinal de treino. Toda `Decision` que diverge da `Proposal` vira candidata a `EvalCase`.

---

## 5. Avaliação — o ativo de longo prazo

### 5.1 Geração sintética com gabarito

Sem dado de terceiros, o gerador é a única fonte de verdade — e por isso é componente de primeira classe, não utilitário de teste.

Ele produz pares de extrato e razão que **deveriam** conciliar, e então injeta divergências de tipo conhecido em proporção configurável. Cada injeção registra o gabarito: qual tipo, quais registros, qual explicação correta.

Propriedades exigidas: determinismo por semente, realismo nas distribuições (valores, fornecedores, sazonalidade), e cobertura de toda a taxonomia.

**Limitação reconhecida honestamente:** dado sintético mede se o sistema resolve os problemas que sabemos existir. Não descobre os que não sabemos. Por isso F3 (validação com profissionais reais) não é opcional.

### 5.2 Métricas

Medir o **sistema** e o **agente** separadamente — confundir os dois esconde regressões.

| Métrica | O que responde |
|---|---|
| Taxa de resolução determinística | O L1-L3 está fazendo seu trabalho? |
| Precisão das propostas | Das que o agente propôs, quantas estavam certas? |
| Cobertura por tipo | Há tipos da taxonomia em que falhamos sistematicamente? |
| Taxa de abstenção | Está abstendo de menos (arriscado) ou demais (inútil)? |
| Custo por divergência | O argumento comercial se sustenta? |
| Taxa de correção humana | Tendência ao longo do tempo |
| Volume e agrupamento de `NAO_IDENTIFICADO` | Há um tipo faltando na taxonomia? (ver 4.5) |

### 5.3 Suíte de regressão

Roda a cada mudança. Uma queda de precisão em qualquer tipo da taxonomia falha a suíte. Mudança de prompt, de modelo ou de ferramenta sem rodar a suíte é proibida — é a única defesa contra regressão silenciosa em sistema não determinístico.

### 5.4 O loop de correção

```
Decision humana diverge da Proposal
            ↓
     vira EvalCase candidato
            ↓
     revisão e promoção
            ↓
     entra na suíte de regressão
```

Em seis meses, esse conjunto é o ativo que um concorrente não copia — e é a resposta para "por que você e não o ChatGPT?".

---

## 6. Tratamento de erro, custo e limites

| Falha | Tratamento |
|---|---|
| Timeout de LLM | Retry com backoff; após 3 tentativas, marca `NAO_IDENTIFICADO` |
| Saída malformada | Retry com correção; após 3 tentativas, abstém |
| Ferramenta falha | Informa o agente; ele decide prosseguir com menos contexto ou abster |
| Alucinação de ferramenta | Registro rejeitado pelo schema; conta como erro na métrica |
| Orçamento estourado | Interrompe e marca a divergência como não investigada |

Limites em dois níveis: por divergência e por execução. Ambos configuráveis, ambos com valor padrão conservador. Estourar orçamento é evento observável, não exceção silenciosa.

**Não existe compensação no v1** porque não existe escrita. Essa é a simplificação mais valiosa do documento.

---

## 7. Observabilidade e auditoria

Um `trace` por divergência investigada, contendo: entrada, cada chamada de ferramenta com argumentos e retorno, cada chamada de LLM com custo, a proposta final, e a decisão humana.

Requisito de auditoria: dado um resultado conciliado, deve ser possível reconstruir integralmente por que o sistema chegou ali — seja por regra determinística (com a regra citada) ou por proposta de agente (com a evidência e o revisor que aprovou).

---

## 8. Segurança, dados e conformidade

- **Nenhum dado de terceiros neste repositório.** O projeto é pessoal, construído fora do horário e da infraestrutura do empregador. Dado sintético é versionado; dado real, nunca. O `.gitignore` reflete isso.
- Segredos por variável de ambiente; `.env` fora do versionamento.
- Dado sintético não contém pessoas reais; nomes de fornecedores são gerados.
- LGPD entra como requisito quando houver dado de cliente — não antes, mas o modelo de dados já separa identificadores para tornar anonimização viável.

---

## 9. Anti-escopo e gatilhos de desbloqueio

O principal risco deste projeto é derivar para construir um workflow engine genérico antes de entregar valor. Cada item abaixo tem gatilho explícito.

| Não construir | Desbloqueia quando |
|---|---|
| DSL de workflow em YAML | Houver 3 workflows reais e distintos em produção |
| Durable execution própria | Nunca. Adotar Temporal/Restate se o Tier 3 chegar. |
| Marketplace de agentes | 10+ clientes pedirem |
| Multi-tenant | Houver 2º cliente pagante |
| Sandbox de execução | Executarmos código de terceiros |
| Escrita em ERP | O loop de leitura estiver validado por usuários reais |
| Software Eng Crew como produto | V1 e V2 pagos. Antes disso vale só como lente de design (ver 2.2) — zero horas de construção. |
| E-commerce Ops | Sem gatilho definido; reavaliar se aparecer comprador |

---

## 10. Riscos

| Risco | Severidade | Mitigação |
|---|---|---|
| Deriva para plataforma cedo demais | Alta | Seção 9 com gatilhos; revisar a cada marco |
| Desvio para a vertical divertida (Software Eng) | Média | Gatilho em 2.2: lente de design sim, horas de construção não, até V1 e V2 pagos |
| Dado sintético não representa a realidade | Alta | F3 obrigatória antes de vender |
| Taxonomia incompleta | Alta | Assumida incompleta em 4.5; mecanismo de descoberta via `NAO_IDENTIFICADO` e extensibilidade sem refatoração |
| Empregador reivindicar propriedade | Alta | Zero dado, tempo e infraestrutura da empresa; registrado na seção 8 |
| Matching determinístico resolver menos que o esperado | Média | Se L4 receber demais, melhorar L1-L3 — nunca compensar com agente |
| Tempo disponível cair | Média | Marcos pequenos e independentes; nada exige bloco contínuo |
| Modelo de IA mudar sob os pés | Média | Suíte de regressão detecta; `LLMClient` isola |
| Nenhum comprador se materializar | Alta | F3 antes de investir em F4; abandonar cedo é resultado válido |

---

## 11. Glossário

- **Conciliação** — conferir que lançamentos internos correspondem a movimentações bancárias
- **Divergência** — lançamento que não encontrou correspondência
- **Competência vs. caixa** — data do fato gerador vs. data do dinheiro
- **Retenção na fonte** — imposto descontado pelo pagador antes do repasse
- **Gabarito** — a resposta correta conhecida de um caso sintético
- **Abstenção** — o agente declarar que não sabe, em vez de arriscar
