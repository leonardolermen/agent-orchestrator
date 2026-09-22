# `Enrich`: a regra que busca, e o caso Barrier que a prova

> Tese: **o item chega magro, e quem engorda não precisa ser o modelo.** Hoje o
> canvas sabe trazer uma lista de uma API e não sabe buscar o detalhe de cada
> item dela. O buraco entre `Input` e os blocos de decisão é preenchido, hoje,
> pagando um agente para fazer trabalho determinístico.

---

## 0. O pedido

"Vamos pensar em um fluxo complexo, podemos usar o barrier como api pra buscar
alguma informação, pra ter um case bem forte de automação e fazer ele
funcionar."

O Barrier é a plataforma de KYC/PLD-FT do mesmo autor: recebe o cadastro de um
cliente, roda verificação de identidade, screening de PEP/sanções e
classificação de risco, e devolve a decisão. O que interessa aqui é o que ele
expõe para quem opera:

| endpoint | o que dá |
|---|---|
| `GET /v1/mesa/queues/{queue}` | a fila de trabalho da mesa de análise, mais antigo primeiro |
| `GET /v1/assessments/{id}` | o detalhe da avaliação |
| `GET /v1/mesa/cases/{id}` | a linha do tempo do caso |
| `POST /v1/assessments/{id}/decision` | a decisão (EDD) — **fora desta fatia** |

Duas decisões tomadas antes do desenho, e elas o encurtam:

1. **O fluxo é de triagem, e quem decide é o humano.** Nada escreve no Barrier.
   Todas as ferramentas seguem `READ_ONLY`, como o `CLAUDE.md` exige enquanto
   não houver compensadora — e a compensadora de uma decisão de PLD-FT não é
   óbvia.
2. **Roda contra o Barrier de verdade**, não contra um stub.

---

## 1. O que já existe, e o que falta

**Existe:** `Input` (a fonte HTTP vira degrau e o workflow se basta), `condicao`
e `filtro` (roteiam e descartam de graça), `BlocoAgente` (julga) e `BlocoTarefa`
(transforma), a `Fila` append-only que recebe as propostas, e o `Trigger` que
dispara tudo por URL.

**Falta uma coisa, e ela é a mais comum em automação:** buscar, para CADA item,
o detalhe que a lista não trouxe. A fila da mesa devolve `CaseSummary` —
`assessmentId`, `queue`, `assignedTo`, `openedAt`, `slaSeconds` — e nada disso
permite classificar risco. O detalhe está em `/v1/assessments/{id}`, uma
chamada por item.

Sem o bloco, as duas saídas são ruins:

- **Um agente com ferramenta busca o detalhe.** Funciona, e paga um turno de
  modelo para executar um `GET` cujo resultado não depende de julgamento
  nenhum. É exatamente o que o §2 do README proíbe.
- **O agente adivinha** com id e SLA. Barato e sem valor.

---

## 2. Abordagens consideradas

### A. Bloco `Enrich` genérico (ESCOLHIDA)

Um resolver determinístico que consome um kind, chama uma URL montada com os
campos do próprio item, funde a resposta no payload e produz outro kind.

Serve para qualquer API — o Barrier é o primeiro usuário, não o dono.

### B. Ferramenta de domínio (`domains/kyc/agent/ferramentas/buscar_caso.py`)

Segue um padrão que o repositório já tem e é mais rápida de escrever. Rejeitada
porque **o modelo passa a pagar pela busca**: cada detalhe vira um turno, e o
turno não decide nada. Custo de estar errado: o caso "forte de automação" que
esta spec existe para provar viraria a demonstração de um anti-padrão —
inteligência cara fazendo trabalho de encanamento.

### C. A fonte HTTP traz tudo de uma vez

Se `/v1/mesa/queues/…` devolvesse o detalhe embutido, não haveria problema. Ela
não devolve, e mudar o Barrier para servir um payload gordo por causa do
orquestrador é acoplar dois produtos pelo lado errado.

---

## 3. O bloco `Enrich`

`regras/enriquecimento.py`, categoria `DATA` no catálogo, `CostClass.REGRA`.

| parâmetro | papel |
|---|---|
| `kind` | o que consome |
| `produz` | o kind que sai; **≠ `kind`**, pela mesma recusa de `condicao.py` |
| `url` | template com `{campo}` do payload do item |
| `token_env` | o **NOME** da variável de ambiente com o bearer |
| `caminho` | onde o objeto está no corpo (vazio = o corpo inteiro) |

**Consome e produz, como `condicao` e `Tarefa`** — o kernel não tem alteração
em lugar: resolução consome, produção cria. Isso não é cerimônia: é o que põe o
bloco no grafo (`consome`/`produz` declarados), desenha a aresta no canvas e
mantém a recusa de beco sem saída funcionando.

**Herda de `sources/http.py`, sem reescrever:** token por nome; userinfo
(`user:senha@`) recusado; query redigida no que a gente registra; a guarda de
host (loopback, link-local e formas numéricas não canônicas); teto de bytes;
transporte injetável para teste. Cada uma dessas decisões custou uma vez; a
segunda cópia divergiria.

### 3.1 O dado pousa no TOPO, e a colisão tem dono

Os campos da resposta são fundidos no **primeiro nível** do payload, não
aninhados sob um nome. Não é preferência: `_prompt_do_item` usa `format_map`,
que só alcança o primeiro nível — aninhar tornaria inalcançável, pelo prompt,
exatamente o dado que foi buscado para ele.

**Em colisão, o campo ORIGINAL do item vence**, e os descartados vão nomeados
para o trace. Uma resposta não pode reescrever o `assessmentId` que identifica
o item: se pudesse, o id do run, a chave da fila e a decisão humana passariam a
apontar para coisas diferentes.

É a regra OPOSTA à do `BlocoTarefa` (lá, o texto novo vence), e a assimetria é
deliberada: lá o campo novo é a saída do trabalho; aqui é informação de
terceiro chegando sobre um item que já tem identidade.

### 3.2 Falha por item não derruba o run

Timeout, 500 do parceiro, corpo que não é JSON, `caminho` que não existe,
template citando campo que o item não tem: o item **não é consumido**, fica no
pool sem enriquecimento, e o motivo entra no trace.

É a mesma forma da abstenção de um agente, e pela mesma razão: uma falha de
rede não pode derrubar um fechamento por causa de um item. O item aparecer na
lacuna é a notícia certa — muito melhor que um payload pela metade que o modelo
do degrau seguinte leria como fato.

**O que NÃO é abstenção:** `token_env` apontando para variável inexistente é
erro de CONFIGURAÇÃO e falha alto, uma vez, como `VariavelAusente` já faz na
fonte. Abster item a item por falta de credencial gastaria a fila inteira para
não fazer nada.

### 3.3 Uma `REGRA` que faz I/O

Até aqui toda regra era pura. Esta faz rede, e vale dizer o que muda:

- **A classe continua medindo DINHEIRO.** O bloco custa 0 µ¢ e isso é verdade;
  o que ele custa é latência e um modo de falha.
- **O golden não pode tocá-lo.** `--seed 1 --n 500` é determinístico porque a
  cascata de conciliação é pura. Este bloco nunca entra naquele caminho, e o
  teste que fixa os 85.3% é a catraca que avisa se alguém tentar.

---

## 4. O caso Barrier

```
entrada  HTTP   GET /v1/mesa/queues/ANALISE_PADRAO   →  caso            grátis
enrich          GET /v1/assessments/{assessmentId}   →  caso_completo   grátis
condicao        SLA estourado                        →  caso_urgente    grátis
agente          classifica com evidência             →  proposta        paga
→ fila de revisão: o analista decide no Barrier
```

**A semente é determinística.** O bureau simulado do Barrier escolhe o desfecho
pelo CPF: `999.300.000-03` (SUSPENSA → `IDENTITY_MISMATCH`) e `999.400.000-49`
(PENDENTE) caem em `EM_REVISAO`, e é de `EM_REVISAO` que nasce todo caso na
`ANALISE_PADRAO`. Semear a mesa é `POST /v1/assessments` com esses documentos —
cenário escolhido, sem inventar dado.

### 4.1 O `localhost` é recusado, e isso é a guarda funcionando

`sources/http.py` recusa loopback e link-local antes de qualquer requisição,
porque o servidor passou a fazer requisições para URLs que vêm da tela. O
Barrier local escuta em `localhost:8080`.

**Não se afrouxa a guarda para uma demo.** A saída já está escrita no docstring
dela: faixa privada (`192.168.x`, `10.x`) **não** é coberta, de propósito. O
Barrier sobe ouvindo no IP da máquina na LAN, ou num nome de serviço na rede do
compose, e o workflow aponta para lá — que é o endereço que qualquer outro
consumidor usaria. Mais realista que `localhost`, aliás.

**JDK:** o Barrier exige Java 25 e esta máquina tem 17. O `Dockerfile` dele
builda com `maven:3.9-eclipse-temurin-25`, então a Risk Engine sobe por
container sem instalar JDK nenhum — o `docker-compose.yml` de lá sobe só
Postgres, Kafka e Kafka UI, então o serviço entra como container na mesma rede.

### 4.2 O que atravessa a fronteira, e onde ele para

Enriquecer com uma avaliação de KYC traz **dado pessoal** para dentro do
orquestrador. Ele não some depois: o payload enriquecido vive no pool durante o
run, o que o agente propõe vai para `data/fila/**` (append-only, por desenho) e
o rastro da conversa entra no trace.

Duas consequências que a composição deve assumir em voz alta:

1. **`caminho` é a ferramenta de minimização.** Apontá-lo para o subobjeto que
   importa — o resultado do screening, não o cadastro inteiro — é o que mantém
   nome e documento fora da fila. A spec recomenda o `caminho` mais estreito
   que responda à pergunta do agente.
2. **O Barrier é operador e cuidadoso com isso** (ele nem guarda imagem de
   documento). Um orquestrador que copia o cadastro inteiro para um JSONL local
   desfaz essa disciplina do lado de fora. Se o caso for além de demonstração,
   cifragem em repouso da fila é decisão própria, e não desta fatia.

---

## 5. Testes

**Unidade, com `httpx.MockTransport`** — o mesmo padrão da fonte HTTP:

1. sucesso: os campos da resposta chegam no topo do payload e o kind muda;
2. colisão: o campo original do item vence, e o descartado é nomeado no trace;
3. 500 num item: aquele item fica no pool, os outros seguem, o run conclui;
4. template citando campo inexistente: mesma abstenção, com o nome do campo;
5. `token_env` ausente: falha ALTO, uma vez, sem tocar a rede;
6. host loopback: recusado pela guarda herdada.

**Ponta a ponta contra o Barrier real:** subir a Risk Engine por container,
semear dois casos com os CPFs do bureau simulado, compor o workflow e rodar —
com o modelo em Haiku ou gravado, não em Opus.

---

## 6. O que esta fatia NÃO faz

- **Escrita no Barrier.** Decidido: triagem, humano decide.
- **Paginação e cursor.** A fonte HTTP já os deixou de fora com o motivo escrito
  (o `ref` de várias páginas é desenho próprio); o `Enrich` não os reinventa.
- **Cache.** Um `If-None-Match` por item é a evolução óbvia e exige um store.
- **Domínio `kyc/` no orquestrador.** Não é preciso: o caso é composição, e a
  peça de framework é genérica.

---

## 7. Riscos

| risco | mitigação |
|---|---|
| Uma fila de 200 casos vira 200 requisições ao parceiro | O `limit` da própria fila é o teto natural; o bloco não pagina, então o pool é o que a fonte trouxe |
| Latência: 200 chamadas em série | Aceito nesta fatia e dito aqui; paralelismo é desenho próprio, e o motor ainda é sequencial |
| Dado pessoal na fila e no trace | `caminho` estreito; §4.2 |
| Alguém aponta o bloco para um host interno | A guarda herdada recusa loopback/link-local; faixa privada continua alcançável, e isso está declarado |

---

## 8. Critério de aceite

1. Um workflow composto com `entrada` + `enrich` + `condicao` + agente roda
   contra o Barrier de verdade e produz propostas na fila de revisão, com o
   detalhe da avaliação citado na evidência.
2. Um caso cujo enriquecimento falha aparece na LACUNA, com o motivo no trace,
   e não derruba o run.
3. `pytest` verde nas duas instalações; `ruff` limpo; bundle de `web/` batendo.
4. `orchestrator --seed 1 --n 500` continua em `85.3%`, zero falso positivo,
   zero falso negativo — o bloco novo não toca o caminho do golden.
