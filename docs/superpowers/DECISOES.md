# Decisões tomadas durante a execução do plano

**Data:** 2026-09-14
**Plano:** [`2026-09-14-nucleo-deterministico.md`](plans/2026-09-14-nucleo-deterministico.md)
**Spec:** [`2026-09-14-agent-orchestrator-design.md`](specs/2026-09-14-agent-orchestrator-design.md)

A execução deste plano foi delegada a subagentes, com revisão independente por
tarefa. Ao longo dela foram tomadas **26 decisões sem consulta prévia**: conflitos
entre o plano e o que a revisão encontrou, ambiguidades que teriam parado o
trabalho, e defeitos descobertos no próprio plano.

Cada uma traz a alternativa rejeitada e o custo de estar errada, para que possam
ser revistas individualmente. Nenhuma foi omitida.

---

## 1. Pre-flight (antes da Task 1)

usar branch `feat/nucleo-deterministico` em vez de worktree separado — repositório novo, sem trabalho paralelo, worktree seria cerimônia sem isolamento adicional. Custo se errado: nenhum; basta criar o worktree depois.

## 2. Pre-flight (antes da Task 1)

DEFEITO 1 — `Metrics.render` passa a formatar valores com `format_brl` em vez de imprimir centavos crus. Alternativa era remover `money.py` por YAGNI, mas o relatório é lido por humano e centavos crus são ilegíveis; isso torna a T1 load-bearing em vez de morta. Custo se errado: uma tarefa a menos de valor, removível em um commit.

## 3. Pre-flight (antes da Task 1)

DEFEITO 2 — `PagamentoAgregado` normaliza fornecedor E data de caixa de todos os lançamentos do lote para os do primeiro par. Justificativa de domínio: um pagamento em lote é a um único fornecedor e liquida tudo no mesmo dia. Alternativa era afrouxar o filtro de fornecedor em L3, rejeitada porque o filtro é o que mantém a camada barata. Custo se errado: o injetor gera um caso menos variado que a realidade.

## 4. Pre-flight (antes da Task 1)

DEFEITO 3 — `DevolucaoFundos` zera o `document` das três pernas. Justificativa de domínio: transferência devolvida aparece no extrato sem a referência do documento original. Isso bloqueia L1 e L2 (ambos exigem documento não nulo) e preserva a intenção do spec de que devolução é caso do agente. Alternativa era deslocar data ou valor, rejeitada por ser artificial. Custo se errado: L3 poderia casar uma perna por coincidência de soma; improvável e detectável pela métrica de falso positivo.

## 5. Pre-flight (antes da Task 1)

DEFEITO 4 — limite do teste relaxado para 5..25 injeções, que é a faixa que o laço realmente produz. Custo se errado: o teste deixa passar uma proporção de divergência mais variável que o pretendido; a métrica de taxa determinística continua sendo o sinal real.

## 6. Pre-flight (antes da Task 1)

os quatro defeitos são corrigidos NO PLANO antes da Task 1, não carregados como instrução em cada dispatch. O brief é a fonte única de requisitos do implementador; um plano errado com correção por fora produz brief errado. Custo se errado: nenhum — o plano é versionado e a correção é visível no diff.

## 7. Task 1

aceitar o achado contra o texto do plano. `parse_brl("10,999")` devolvendo 1099 é corrupção silenciosa de valor monetário num sistema cuja premissa é trilha auditável; o spec exige que dinheiro nunca esteja errado, e o plano apenas não previu o caso. Correção: validar o comprimento da parte decimal e levantar ValueError. Custo se errado: uma validação a mais que rejeita entrada que algum extrato real poderia trazer com 3 casas — detectável na ingestão, e preferível a truncar calado.

## 8. Task 1

Tasks 2 e 3 despachadas em um único brief. São dois módulos folha sem interface comum (dates.py: duas funções puras; taxonomy.py: uma enum), ambos com código completo no plano, ambos transcrição mais teste. Um dispatch por tarefa aqui seria overhead sem ganho de revisão. Custo se errado: o diff de review cobre dois módulos em vez de um; ambos pequenos o bastante para uma passada.

## 9. Task 2+3

aceitar o achado e corrigir levantando ValueError para n negativo. Nenhum chamador do plano passa negativo (T6, T7 e T10 só usam randrange positivo), então travessia reversa seria capacidade especulativa; mas no-op silencioso é armadilha e custa duas linhas para eliminar. Alternativa rejeitada: implementar retrocesso simétrico — YAGNI sem chamador. Custo se errado: se algum dia for preciso andar para trás, troca-se o raise pela travessia, com o teste já no lugar apontando o comportamento escolhido.

## 10. Task 2+3

passada dedicada no plano antes da Task 4, fora do loop de tarefa. Os dois achados plan-mandated até aqui (parse_brl truncando decimal, add_business_days no-op em n negativo) são a mesma classe de defeito: entrada malformada tratada em silêncio em vez de rejeitada. Varri as tarefas restantes procurando a mesma assinatura e encontrei três: generate_clean_pairs com n<1 devolve lista vazia; ToleranceMatcher com tolerância negativa nunca casa; GroupingMatcher com max_group_size<2 nunca agrupa — as três falham calado. Corrigir agora custa um commit; descobrir uma por uma custaria três fix rounds com dispatch, review e re-review cada. Custo se errado: três guardas a mais em construtores que ninguém chamaria errado; removíveis em um commit.

## 11. Task 4+5

o item ⚠️ do reviewer (BankEntry/LedgerEntry sem validação de campo) NÃO é lacuna. Neste plano essas entidades são construídas exclusivamente pelo gerador sintético, que controla as próprias entradas; validação de entrada externa pertence ao módulo de ingestão, que não faz parte deste plano — a CLI gera dados, não lê arquivo. Adicionar validação de campo agora seria especulativa. Custo se errado: quando a ingestão existir, a validação entra lá, que é onde a entrada não confiável chega.

## 12. Task 4+5

Tasks 7-10 não serão batched em bloco único apesar de todas tocarem injectors.py. As tarefas 9 e 10 carregam as duas correções de pre-flight mais delicadas (normalização de fornecedor e data no agregado; document=None nas pernas da devolução), e são exatamente as que produzem falha não óbvia se saírem erradas. Agrupamento por risco, não por arquivo: 7+8 juntas (injetores simples), 9+10 juntas (as que a camada de matching depende para funcionar). Custo se errado: um dispatch a mais que o estritamente necessário.

## 13. Task 6

defeito de desenho meu, não do implementador — build_dataset infere os ids consumidos a partir do que o injetor DEVOLVEU, o que só funciona se o injetor preservar todos os ids. DevolucaoFundos renomeia as três pernas; PagamentoAgregado funde N pares em um lançamento e dois ids somem por construção. Correção: InjectionResult passa a carregar `consumed: tuple[Pair, ...]`, os pares que ele substituiu, e build_dataset deriva os ids dali. Alternativa rejeitada: exigir que injetores preservem ids — impossível para o agregado. Alternativa rejeitada: filtrar os pares no chamador (build_benchmark) — deixaria build_dataset como armadilha para o próximo chamador. Custo se errado: um campo obrigatório a mais em cada injetor, verificável por teste.

## 14. Task 6

o teste de fan-out e fan-in com InjectionResult construído à mão entra na Task 6, não numa tarefa posterior. A ausência dele é a razão de o defeito ter passado, e ele não depende de nenhum injetor real existir.

## 15. Task 9+10

aceitar o achado. O risco mais caro medido neste plano estava sem guarda de regressão, e a guarda custa duas asserções. Custo se errado: duas linhas de teste a mais.

## 16. Task 9+10

Task 13 (GroupingMatcher) vai sozinha, sem batch com 11+12. É a única camada com busca combinatória e a única cujo erro produz falso positivo silencioso em vez de teste vermelho — merece superfície de review dedicada. Custo se errado: um dispatch a mais.

## 17. Task 11+12

aceitar. A taxa de resolução determinística é o número que este plano existe para produzir, e ela desloca silenciosamente se a inclusividade da fronteira mudar. Quatro asserções fixam isso. Custo se errado: quatro testes a mais numa camada que já está correta.

## 18. Task 13

o injetor está errado, não o matcher nem o gabarito. Modelagem correta do domínio: a empresa lança a nota pelo bruto, o banco paga o líquido, e a diferença é justamente o que o reconciliador vê e o agente precisa explicar. Se a contabilidade já registrasse o líquido, não haveria divergência nenhuma — o caso deixaria de ser interessante e o gabarito passaria a mentir. Correção: o injetor não toca o lançamento contábil; só o valor bancário vira líquido. Verificado antes de decidir: com o contábil intocado, L1 e L2 deixam de casar e sobra uma divergência de R$ 1.274,62. Alternativa rejeitada: marcar deterministic_expected=True — transformaria um caso de agente em caso determinístico e esvaziaria o tipo da taxonomia. Custo se errado: o injetor deixa de exercitar o cenário em que a contabilidade conhece a retenção; esse cenário não é divergência e não pertence ao gabarito.

## 19. Task 13

o teste test_retencao_mantem_bruto_e_ajusta_liquido codifica o comportamento errado e precisa mudar junto. Um teste que trava o defeito no lugar é pior que nenhum.

## 20. Task 13 — 1

teto de candidatos configurável, padrão 24. Estourou, o lançamento vai para divergência, que é o destino previsto de tudo que a camada barata não resolve. O teto serve a duas coisas ao mesmo tempo: limita o custo e reduz a chance de soma coincidente, porque pool maior significa mais oportunidade de coincidência. Alternativa rejeitada: aumentar max_group_size para cobrir lotes grandes — pioraria as duas. Custo se errado: lotes com mais de 24 faturas do mesmo fornecedor na janela viram divergência; com grupo máximo de 4, L3 não os resolveria de qualquer jeito.

## 21. Task 13 — 2a

L3 passa a considerar apenas débitos. A camada existe para casar PAGAMENTOS agregados; um crédito é recebimento e não deveria procurar faturas a pagar. Isso elimina a perna de crédito da devolução como vetor. Custo se errado: se algum dia houver conciliação de recebíveis, ela precisa de camada própria — o que é verdade de qualquer forma.

## 22. Task 13 — 2b

NÃO vou afirmar impossibilidade por teste. Se o valor de uma perna de devolução coincidir exatamente com a soma de faturas reais do mesmo fornecedor na janela, L3 casa, e nenhuma guarda barata evita isso sem quebrar o caso que L3 existe para resolver. O teste de regressão cobre o caso normal (mesmo fornecedor, janela próxima, valores não coincidentes, L3 não toca). A coincidência exata fica registrada como risco residual conhecido — e é exatamente para isso que a métrica de falso positivo existe no spec. Custo se errado: um falso positivo raro que a métrica mostra em vez de esconder.

## 23. Task 13

manter a validação e redesenhar o teste, não o contrário. A validação tem valor real — max_candidates abaixo de max_group_size faz o botão max_group_size mentir, porque grupos daquele tamanho nunca se formam. Além disso meu teste original não provaria nada mesmo se construísse: com pool de 3 e grupo máximo 2, o retorno vazio viria do tamanho do grupo, não do teto. Desenho novo: pool de 6 (o trio agregado mais três lançamentos de ruído do mesmo fornecedor na janela), teto 4 contra teto 6, ambos com max_group_size no padrão. Verificado por mim antes de despachar: teto 4 devolve zero, teto 6 casa o trio correto, e sem teto efetivo também casa — o que prova que é o teto, e não outra coisa, que causa o skip. Custo se errado: nenhum; o teste é mais caro de montar e prova mais.

## 24. Task 14+15 — crítico

contenção total no lado do falso negativo, sobreposição no lado do falso positivo. A assimetria é deliberada e o reviewer a identificou corretamente: para um caso que NÃO deve ser resolvido, qualquer toque já é erro; para um que DEVE, exige-se o caso inteiro. Alternativa rejeitada: exigir que os ids tenham sido casados dentro de um mesmo MatchResult — mais rigoroso, mas rejeitaria uma resolução legítima repartida entre camadas, e a contenção já mata o caso reproduzido. Custo se errado: a métrica fica levemente mais severa do que o necessário em cenários que nenhum matcher atual produz.

## 25. Task 14+15 — important

corrigir os rótulos para nomear as unidades e separar o gabarito entre casos que as camadas devem resolver e casos reservados ao agente. Alternativa rejeitada: agrupar as divergências por caso — exigiria que a engine conhecesse o gabarito, o que quebraria o isolamento que a Task 14 acabou de provar. Custo se errado: um relatório mais verboso.

## 26. Task 16

a asserção passa a ser sobre o MÍNIMO entre as sementes varridas, não sobre a média. Medido: sementes 1-5 a n=300 dão 86,8 / 83,0 / 85,3 / 89,7 / 90,1, mínimo 83,0%. Com piso sobre o mínimo, 0,85 de fato falha e a verificação de falsificação passa a significar alguma coisa. O mínimo também é a estatística certa para o propósito: um teste de regressão precisa pegar ALGUMA semente colapsar, não a média deslizar — a média esconde exatamente o caso que interessa. Piso fixado em 0,78, cinco pontos abaixo do mínimo medido de 83,0%, com folga para dispersão sem virar teste instável. Custo se errado: o teste tolera uma degradação de até cinco pontos numa semente antes de reclamar.

---

# Plano 2 — Agente investigador

Mais **27 decisões** tomadas sem consulta prévia durante a execução do
plano 2. Mesmo critério: cada uma traz a alternativa rejeitada e o custo de
estar errada.

---

## P2.1. Pre-flight (antes da Task 1)

usar branch `feat/agente-investigador`. A execução anterior teve a branch renomeada para main por processo externo; começar direto na main violaria a skill e perderia a separação. Custo se errado: nenhum.

## P2.2. Pre-flight (antes da Task 1)

DEFEITO 1 — `metrics.py` importa apenas `DivergenceType`. `Confidence` fica só no arquivo de teste, onde é de fato usado. Alternativa rejeitada: usar `Confidence` em metrics.py para justificar o import — seria inventar uso para salvar uma linha. Custo se errado: nenhum; o import volta se algum dia for preciso.

## P2.3. Pre-flight (antes da Task 1)

DEFEITO 2 — usar o `Counter` já importado no topo de metrics.py, sem alias local. Custo se errado: nenhum.

## P2.4. Pre-flight (antes da Task 1)

manter `_PRECOS` como fonte única importada por `anthropic_client`, apesar de ser nome privado atravessando módulo. Duplicar a tabela de preços em dois arquivos criaria a possibilidade de eles divergirem, e preço errado significa métrica de custo errada — que é a métrica central do produto. Custo se errado: acoplamento a um detalhe interno de `proposal.py`; visível e fácil de promover a público depois.

## P2.5. Pre-flight (antes da Task 1)

aceitar os dois `Investigator` homônimos (classe em `agent.investigator`, protocolo em `matching.engine`). Renomear o protocolo para algo como `InvestigatorProtocol` seria feio, e renomear a classe perderia o nome óbvio. Tipagem estrutural resolve. Custo se errado: confusão de leitura, resolvível com um comentário.

## P2.6. Task 1

corrigir coagindo `tipo` e `confianca` ao enum no `__post_init__`, não trocando `is` por `==`. Trocar o operador conserta UMA verificação e deixa o campo guardando string, o que quebraria as outras verificações por identidade que o projeto usa em toda parte (metrics faz `p.tipo is DivergenceType.NAO_IDENTIFICADO`). Coagir uma vez torna toda verificação por identidade segura e torna Proposal construível a partir de JSON — que é exatamente o que o plano 3 vai fazer. Custo se errado: duas linhas de object.__setattr__ num dataclass frozen, padrão conhecido e feio, removível se a coerção nunca for exercida.

## P2.7. Task 1

Tasks 2 e 3 despachadas num brief só. Dois módulos folha sem interface comum (llm.py: protocolo mais cliente falso; tools.py: cinco ferramentas e seus schemas), ambos com código completo no plano, ambos transcrição mais teste. Custo se errado: o diff de review cobre dois arquivos em vez de um.

## P2.8. Task 2+3

substituir o idioma `or` por checagem explícita de None e rejeitar limite < 1 com ValueError, mais `minimum: 1` no schema. Alternativa rejeitada: clampar em silêncio — seria a mesma classe de falha silenciosa que este projeto já corrigiu cinco vezes. Custo se errado: uma chamada do modelo com limite inválido vira erro que volta para ele em vez de resultado; é o comportamento desejado.

## P2.9. Task 2+3

corrigir a descrição do schema, que afirma "no máximo 10 resultados" mas só vale quando limite é omitido. A descrição É a interface do agente; descrição que promete garantia que o código não dá é defeito, não polimento.

## P2.10. Task 2+3

o reviewer marcou `ToolContext.bank` como estado morto. NÃO é — a Task 4 usa `self.context.bank` em `_descrever` para montar a divergência. O reviewer não tinha a Task 4 à vista. Registrado para o review final não reabrir. Custo se errado: nenhum.

## P2.11. Task 4 — #1 e #2 juntos

estreitar o try para envolver só `client.complete()`, e validar `client.model` contra a tabela de preços no `__post_init__`. Modelo sem preço não é abstenção, é erro de configuração: abster em toda divergência gastaria a execução inteira sem produzir nada, e o custo — métrica central do produto — ficaria incalculável. Validar na construção também elimina a necessidade do re-raise de AssertionError, que era a única coisa mantendo um caminho vivo de exceção saindo de investigate. Alternativa rejeitada: `except ValueError` estreito em volta do teto — conserta o sintoma e mantém o modelo sem preço rodando. Custo se errado: construir o investigador com modelo desconhecido falha na hora em vez de degradar; é o comportamento desejado.

## P2.12. Task 4 — #3

`evidencia` que não seja lista é rejeitada e vai para o caminho de retry, não embrulhada numa lista de um elemento. Embrulhar preservaria o conteúdo e economizaria um turno, mas seria adivinhar intenção — e este projeto já corrigiu seis defeitos da classe "aceita em silêncio o que deveria rejeitar". Consistência vale mais que um turno. Custo se errado: um turno a mais quando o modelo manda string onde pediu-se lista; medível na avaliação da Task 9.

## P2.13. Task 4 — #4

as três regressões ganham teste. Desvio de brief sem teste que o fixe é desvio que a próxima execução do plano desfaz em silêncio.

## P2.14. Task 4 — Minor 3 do reviewer, promovido

`_executar` passa a capturar largo. É a inversão exata do #1 — ali a captura larga esconde bug do investigador; aqui ela é o requisito literal do spec, porque erro de ferramenta tem que voltar ao modelo como texto sempre.

## P2.15. Task 5

corrigir agora, não adiar para o review final, apesar de exigir estender o Cost da Task 1 já fechada. A Task 9 vai reportar custo por divergência como o número comercial do produto, e um subcontagem sistemática conhecida nesse número é exatamente a classe de erro que eu já corrigi uma vez neste projeto com a taxa de 85%. Adiar significaria a avaliação reportar um número que eu sei ser baixo. Custo se errado: um campo a mais no Cost e um preço a mais na tabela; magnitude pequena em valor absoluto, porque só incide na primeira chamada de cada janela de cache.

## P2.16. Task 5

preço de escrita de cache fixado em 1,25x o preço de entrada, por modelo. É a razão documentada da API. Custo se errado: o custo reportado erra por uma fração de uma fração; corrigível numa linha da tabela.

## P2.17. Task 5

usuário perguntou se dava para fazer o front em paralelo num worktree. Respondi que o sistema de arquivos paraleliza mas eu não — sou um controlador só, e a verificação empírica entre rodadas, que pegou os defeitos mais caros de hoje, é a primeira coisa a degradar com atenção dividida. Somado a isso, Proposal mudou duas vezes só hoje, então front construído agora perseguiria contrato em movimento. Usuário escolheu terminar o plano 2 primeiro. Front vira plano 3, com a medição de precisão e abstenção na mão — que é o que decide qual das três telas o produto precisa ser.

## P2.18. Task 5

Tasks 6 e 7 despachadas juntas. Ambas modificam arquivo existente e a 7 consome diretamente o que a 6 produz (ReconcileResult.proposals e agent_cost); separá-las faria a 7 ser revisada contra uma engine que a própria 6 acabou de mudar. Custo se errado: diff de review maior.

## P2.19. Task 6+7

Tasks 8 e 9 despachadas juntas. Ambas criam arquivos novos em eval/, a 9 consome a 8 só conceitualmente (camadas de teste diferentes), e nenhuma toca código existente. Custo se errado: diff de review maior.

## P2.20. Task 8+9 — 1

asserção dura em avaliar de que cliente.model == model. Alternativa rejeitada: usar cliente.model para os dois — esconderia a discrepância em vez de gritar, e o ponto é que pedir um modelo e medir outro é erro de quem chamou. Custo se errado: uma fábrica legítima que troque de modelo deliberadamente passa a falhar; não existe caso assim hoje.

## P2.21. Task 8+9 — 2

pinar os três contadores brutos E o valor de precisão resultante, não só a faixa. Com os quatro fixos, trocar numerador por denominador quebra. Pinar só o valor final seria circular se a fórmula estivesse errada; pinar só os contadores não testaria a fórmula. Custo se errado: o teste precisa ser reajustado se o benchmark mudar de forma — que é exatamente quando alguém deveria olhar para ele.

## P2.22. Task 8+9

trocar a amostra do teste de precisão para n=100, semente 1 — medido por mim: 12 propostas, 0 abstenções, 6 corretas, precisão 0,5. Fórmula invertida daria 2,0, fora de [0,1], então a amostra discrimina. Alternativa rejeitada: manter n=40 e aceitar a degenerescência — pinar contadores numa amostra que não distingue a fórmula é teatro. Custo se errado: o teste roda sobre 100 pares em vez de 40, uns milissegundos a mais.

## P2.23. Task 8+9

acrescentar um segundo teste com falso que só abstém — medido: 12 propostas, 12 abstenções, 0 corretas, precisão 0,0, taxa de abstenção 1,0. Sem ele o denominador `total - abstidas` nunca é exercido com abstidas maior que zero, e o ramo de denominador zero também não. Custo se errado: um teste a mais.

## P2.24. Task 8+9

onda única de correção com os 30 itens, conforme a skill. Alternativa rejeitada: um corretor por achado — cada um reconstrói contexto e roda a suíte inteira.

## P2.25. Task 8+9

o novo orçamento padrão é derivado, não chutado: 4.000.000 micro-cents, com a derivação documentada no código e um teste que recalcula o turno realista a partir de len(SYSTEM) e len(TOOL_SCHEMAS) a cada execução. Assim crescimento de prompt ou mudança de preço quebram alto. Custo se errado: uma execução de 500 lançamentos com ~116 divergências custa até US$ 4,64 no opus em vez de falhar barato.

## P2.26. Task 8+9

calcular_retencao movido para tax.py neutro. O agente calculava retenção com a MESMA função que fabricou a divergência — a acurácia de RETENCAO_IMPOSTO na avaliação era parcialmente circular. Custo se errado: um módulo a mais.

## P2.27. Task 8+9

NÃO faço a chamada real que o reviewer pede como prova final. Gasta dinheiro e depende da chave do usuário; é decisão dele, não minha. Registrado como a única evidência que falta.
