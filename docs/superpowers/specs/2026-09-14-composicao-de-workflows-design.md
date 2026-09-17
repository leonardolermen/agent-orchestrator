# Composição de Workflows — Documento de Design

**Data:** 2026-09-14
**Estado:** ENTREGUE PARCIALMENTE. Existem `Composicao`, o canvas de composição
e o entrevistador. Falta a composição alcançar o GRAFO — etapas com
`consome`/`produz` e arestas derivadas —, que é o trabalho pendente do spec de
execução como grafo (X7–X8).
**Escopo:** V3 — a plataforma
**Spec pai:** [`2026-09-14-agent-orchestrator-design.md`](2026-09-14-agent-orchestrator-design.md)

---

## 0. Por que este documento existe, e por que não vira código ainda

Este é o design de como clientes montam workflows na plataforma. Ele foi feito
como **lente de design**, não como ordem de construção — o mesmo enquadramento
que o spec pai dá à Software Engineering Crew.

O anti-escopo do spec pai é explícito:

> | DSL de workflow em YAML | Desbloqueia quando houver **3 workflows reais e distintos em produção** |

Hoje existem **zero**. Não há cliente, não há receita, e o V1 ainda não é
produto — faltam o agente investigador e a revisão humana.

**O valor deste documento é o que ele mudou no trabalho próximo, não o que ele
autoriza a construir.** Ver seção 6: o exercício produziu duas correções
concretas no plano 2 e nenhuma antecipação de trabalho de plataforma.

**Gatilho de construção:** três workflows reais e distintos em produção, com
V1 e V2 pagos. Antes disso, este documento é referência, não roteiro.

---

## 1. A unidade de composição: cascata de resolução

### 1.1 A escolha errada

A escolha óbvia é "agentes são nós, o usuário liga eles". É o que o CrewAI faz,
e é errado para este produto: torna o caso caro o default e o caso barato uma
coisa que o usuário precisa lembrar de fazer.

Num canvas, toda caixa parece igual. Quem monta não tem como saber que um passo
deveria ser uma query e o outro precisa de LLM — e o caminho de menor
resistência numa tela de montar agentes é sempre montar mais um agente.

### 1.2 O primitivo

A unidade sai do que o núcleo determinístico já é:

```
Stage "conciliar lançamentos"
  ├── regra exata             ~R$ 0        resolve ~82%
  ├── regra com tolerância    ~R$ 0        resolve o que sobra e cabe
  ├── regra de agrupamento    ~R$ 0        resolve n:m
  └── agente investigador     R$ 0,30/item   ← último recurso
```

Isso não é uma sequência de passos. É uma **cascata de resolução**: tentativas
ordenadas da mais barata para a mais cara, cada uma recebendo apenas o que a
anterior não resolveu, com inteligência como último recurso.

**A cascata é o primitivo, não um padrão que o usuário lembra de aplicar.**

- Um `Stage` declara o que resolve.
- Dentro dele, uma lista ordenada de `Resolvers`, do barato para o caro.
- Um resolver recebe os itens não resolvidos e devolve resoluções.
- O último pode ser agente, humano, ou "deixa em aberto".

**O caso degenerado é um passo simples** — um stage com um resolver só. Não são
dois conceitos; é um.

A estrutura barata passa a ser a estrutura *default*. Não é possível montar o
encadeamento caro sem sair do caminho, porque o caminho já é a cascata.

### 1.3 Teste de generalidade

| Vertical | Stage | Cascata |
|---|---|---|
| Finance Ops | "conciliar lançamentos" | exato → tolerância → agrupamento → agente |
| Procurement | "quem fornece isto?" | lista de preferidos → compras anteriores → agente busca |
| Software Eng | "que mudança esta issue pede?" | *(sem regra barata)* → agente |

A terceira é o caso degenerado. O fato de caber sem forçar é o teste de
generalidade que o spec pai define para a Software Engineering Crew.

---

## 2. O gerador: prosa → rascunho

### 2.1 O gerador compõe, não escreve

Um gerador não consegue inventar regra barata do nada. Uma regra precisa
existir: alguém precisa ter escrito "casar por número de NF com tolerância de
5 centavos". Um gerador que produz código de regra a partir de prosa é um
gerador de código não testado decidindo como dinheiro é conciliado.

O trabalho real: **casar o processo descrito contra um catálogo de resolvers
conhecidos, e marcar os buracos.**

```
prosa do especialista
        ↓
   [gerador]  ──consulta──→  catálogo de resolvers
        ↓                     (o que resolve, custo, o que exige de entrada)
   rascunho de workflow
        ├── stages com cascatas montadas do catálogo
        └── LACUNAS explícitas onde não existe regra barata conhecida
```

### 2.2 Lacunas são saída, não falha

Quando o gerador não encontra resolver barato para um pedaço do processo, ele
**não improvisa**. Marca a lacuna e propõe um agente ali, dizendo textualmente
"não conheço regra para isto".

Uma lacuna deixa de ser erro e vira **roteiro**: cada uma é um resolver que
vale a pena construir.

É o mesmo mecanismo do `NAO_IDENTIFICADO` no spec pai, seção 4.5 — o acúmulo
de "não sei" é o canal por onde o sistema anuncia o que falta nele.

### 2.3 Consequência estratégica

Se o gerador só compõe, **o valor da plataforma cresce com o catálogo, não com
a esperteza do gerador.**

O catálogo é onde o fosso brasileiro do spec pai (seção 1.3) vira código:
casar por NF-e, tolerância de retenção na fonte, leitura de CNAB 240, dias
úteis com feriado municipal, agrupamento por fornecedor. Um concorrente de fora
pode ter gerador melhor e ainda assim não ter nenhum desses.

**Consequência desconfortável, registrada de propósito:** no começo os clientes
mal conseguem montar. O catálogo é raso, quase tudo vira lacuna, e quase tudo
vira agente caro. A plataforma melhora conforme o catálogo enche — o oposto da
curva que uma demonstração sugere.

---

## 3. O canvas

```
┌─ Stage: conciliar lançamentos ──────────────────────┐
│  entra: extrato + razão        sai: propostas       │
│                                                     │
│  ① casar por NF-e             regra   ~R$0   82% ●  │
│  ② tolerância valor/dias      regra   ~R$0    4% ●  │
│  ③ agrupamento por fornecedor regra   ~R$0    2% ●  │
│  ④ investigar divergência     AGENTE R$0,30  12% ◐  │
│                                                     │
│  projeção: 500 itens → R$ 18,00/execução            │
└─────────────────────────────────────────────────────┘
            ↓ propostas
┌─ Stage: aprovar ────────────────────────────────────┐
│  ⑤ revisão humana             HUMANO   —     12% ◐  │
└─────────────────────────────────────────────────────┘
```

### 3.1 O que o especialista edita livremente

Adicionar, remover e reordenar **stages**. Mudar o que entra e sai de cada um.
Dentro de uma cascata, ordenar resolvers **da mesma classe de custo** — se duas
regras servem, a ordem entre elas é conhecimento de domínio dele.

### 3.2 O que a estrutura decide por ele

**A ordem entre classes de custo é derivada, não escolhida.** Regras antes de
agentes, agentes antes de humanos. Não existe gesto de arrastar que coloque o
agente à frente da regra — a cascata se reordena sozinha.

A armadilha mais cara do produto deixa de ser um erro possível e passa a ser
uma coisa que a interface não sabe expressar.

### 3.3 O caminho de escape

Trocar uma regra por um agente é possível, mas é ato explícito que mostra o
delta — "isso leva a execução de R$ 18,00 para R$ 147,00" — e fica registrado
como decisão, com autor e motivo.

### 3.4 Lacunas são o ponto mais valioso da tela

Uma lacuna aparece marcada: "sem regra conhecida — usando agente". É onde o
conhecimento do especialista vale mais, porque ele pode dizer "tem regra sim: é
o código de retorno do CNAB".

Isso não é edição, é **captura de catálogo**. O canvas é a superfície onde os
clientes dizem o que construir a seguir.

### 3.5 Os números vêm de medição

As porcentagens e os custos nos selos saem do módulo de métricas do V1. **O
canvas só é honesto porque existe medição por trás dele.** Sem isso os selos
viram decoração — que é o modo de falha da abordagem rejeitada em 7.2.

---

## 4. O que o canvas produz, e como aquilo roda

### 4.1 A DSL existe, mas não é superfície de autoria

O canvas produz uma definição de workflow: **dado, não código**. Ninguém a
escreve à mão.

Isso muda os requisitos. Uma linguagem de autoria precisa ser agradável de
escrever, com boas mensagens de erro, documentação e tooling. Um **formato de
saída** precisa de três coisas: ser versionável, ser diffável, ser executável.
É uma fração do trabalho.

### 4.2 Versão imutável, execução fixa a versão

Editar o canvas cria versão nova. Execuções em voo continuam na versão em que
começaram. Um fechamento não muda de regra no meio porque alguém mexeu numa
tela.

É a capacidade "versionamento de workflow" do Tier 4 do spec pai, cujo gatilho
declarado — "execução em voo durante um deploy" — se cumpre aqui.

### 4.3 O diff é a peça que vende para auditoria

```
v7 → v8
  ~ stage "conciliar": tolerância de dias 3 → 5
  + resolver "código de retorno CNAB"  (regra, ~R$0)
  − resolver "investigar divergência"  agora recebe 4% em vez de 12%
  Δ custo projetado: R$ 18,00 → R$ 6,00 por execução
  autor: controller@cliente   motivo: "CNAB cobre devolução"
```

Um diff que mostra **consequência**, não apenas estrutura. Numa venda para área
de risco, vale mais que o canvas inteiro.

### 4.4 Aprovação humana não é feature especial

É o último resolver de uma cascata. Nenhum mecanismo novo, nenhum modo de
execução separado — uma das melhores propriedades do primitivo da seção 1.

### 4.5 A costura

A definição **não diz como é executada**. Declara o que resolve o quê, em que
ordem. Se roda em processo ou num workflow durável é assunto do executor.

É a costura `Executor` do spec pai 3.3, agora com contrato concreto em vez de
promessa.

---

## 5. Avaliação de um workflow gerado

### 5.1 O método do V1 não serve aqui

Na conciliação o gabarito é **fabricado**: injeta-se a divergência, então a
resposta é conhecida. Para "este workflow está correto?" não há injeção
possível — não há gabarito a fabricar.

### 5.2 O cliente já tem o gabarito

**O fechamento do mês passado dele está pronto, conferido e fechado.** É verdade
conhecida: conciliações que já aconteceram, com as respostas que humanos deram.

```
extrato + razão de julho (já fechado)
            ↓
   workflow gerado roda
            ↓
   compara com as conciliações reais de julho
            ↓
   concordou em X% | divergiu em Y casos | custaria R$ Z
```

### 5.3 A consequência comercial é maior que a técnica

Isso é **argumento de venda sem risco**: "me dá o fechamento do mês passado; eu
mostro o que o sistema teria feito, onde teria concordado com sua equipe, e
quanto teria custado".

O cliente não instala nada, não integra nada, não expõe processo em produção.
Usa dado que já tem, sobre um mês que já acabou, e confere linha a linha
porque viveu aquele mês.

Resolve o critério **F3** do spec pai com muito menos atrito que "três
profissionais avaliam saídas sintéticas".

### 5.4 Três camadas, porque uma não cobre

| Camada | Pega o quê | Quando |
|---|---|---|
| Validação estrutural | Workflow que nem roda: entrada faltando, stage órfão, ciclo | Na edição, instantânea |
| **Replay histórico** | Workflow que roda e faz a coisa errada | Antes de ir para produção |
| Decisões humanas acumuladas | Degradação: os dados mudaram e as regras pararam de pegar | Contínua, em produção |

A terceira é o loop de correção do spec pai 5.4, aplicado ao workflow em vez de
ao agente.

### 5.5 O que isso NÃO avalia

**Um workflow pode reproduzir julho perfeitamente e estar errado sobre um caso
que não aconteceu em julho** — retenção de INSS que não apareceu, fornecedor
novo, tipo de devolução inédito.

Pior: **o histórico só contém o que o processo antigo pegou.** Se a equipe
deixava passar um tipo de divergência, o gabarito erra na mesma direção, e o
workflow que concorda 100% com eles herda o ponto cego.

Não há solução barata. Há honestidade: o replay histórico mede **concordância
com o processo atual**, não **correção**. São coisas diferentes, e vender uma
como a outra repetiria o erro cometido com a estimativa de 85% no spec pai.

---

## 6. O retorno da lente: o que isto muda no trabalho próximo

O design foi conferido contra o código que existe hoje:

| O design exige | Estado |
|---|---|
| Cascata como dado, não hardcoded | ✅ `default_matchers()` devolve lista; `reconcile` recebe injetado |
| Execução não embutida na definição | ✅ `reconcile` é função pura sobre listas, sem I/O |
| Definição de workflow como dado | — não existe, e não precisa existir ainda |
| **Resolvers uniformes: regra e agente com a mesma forma** | ❌ lacuna — cai no plano 2 |
| **Custo e taxa por resolver, não só do sistema** | ❌ lacuna — cai no plano 2 |

**Duas lacunas, ambas no plano 2, ambas valiosas independentemente de a
plataforma existir:**

1. **O agente investigador deve satisfazer o mesmo protocolo das camadas
   determinísticas.** Ele entra na cascata como último resolver em vez de ser
   um estágio separado e especial — o que simplifica o plano 2, não complica.

2. **Métricas por resolver, não só do conjunto.** Responde "a camada L2 vale o
   que custa manter?", pergunta que aparece em dois meses com ou sem canvas.

**A lente mudou duas decisões do trabalho próximo e não antecipou nenhum
trabalho de plataforma.** É o que uma lente de design deve fazer.

---

## 7. Anti-escopo

### 7.1 Nada aqui é construído antes do gatilho

Três workflows reais e distintos em produção, com V1 e V2 pagos. O canvas, o
gerador e o catálogo somam meses a 10-15h/semana, e o spec pai nomeia a deriva
para plataforma antes de entregar valor como o risco de morte deste projeto.

### 7.2 Abordagens rejeitadas, com razão registrada

**Canvas edita tudo, com o custo exibido em tempo real.** Mais poder para o
especialista e mais honesto quanto à liberdade. Rejeitada: indicador de custo
não disciplina comportamento. As pessoas ignoram, e a falha é silenciosa — o
workflow caro *funciona*, apenas custa trinta vezes mais, e a descoberta vem na
fatura.

**Prosa como fonte única da verdade, canvas apenas como visualização.** Muito
mais barato de construir e mantém uma fonte de verdade só. Rejeitada por
remover a edição direta, que é requisito declarado.

**Agentes como nós, ligados livremente.** O modelo do CrewAI. Rejeitada na
seção 1.1: torna o caso caro o default.

---

## 8. Glossário

- **Stage** — uma unidade do processo que declara o que resolve
- **Resolver** — uma tentativa de resolução dentro de um stage: regra, agente ou humano
- **Cascata** — a lista ordenada de resolvers de um stage, do barato para o caro
- **Lacuna** — ponto do processo onde o gerador não conhece resolver barato
- **Catálogo** — o conjunto de resolvers disponíveis; o ativo que cresce
- **Replay histórico** — rodar um workflow contra um fechamento já concluído para comparar
