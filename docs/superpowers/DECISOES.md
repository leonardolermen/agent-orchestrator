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

---

# Plano 3 — cascata e canvas

**10 decisões** tomadas sem consulta prévia durante a execução do plano 3. Mesmo
critério: cada uma traz a alternativa rejeitada e o custo de estar errada.

---

## P3.1. Task 1

sem `tests/__init__.py`. O brief original especificava `from tests.golden.gerar import ...` e `python -m tests.golden.gerar`, o que exige `tests` ser pacote. Em vez disso, o golden importa `from golden.gerar import ...` (pytest insere `tests/` no `sys.path`, então o caminho relativo resolve) e o gerador roda como script de caminho: `./.venv/Scripts/python.exe tests/golden/gerar.py`. Alternativa rejeitada: criar `tests/__init__.py` — transformaria `tests` num pacote de verdade e renomearia o módulo de TODO arquivo de teste existente (de `test_x` para `tests.test_x`), quebrando qualquer import relativo ou configuração que dependa do nome atual, só para consertar um import de um gerador novo. Custo se errado: se algum dia `tests` precisar virar pacote por outro motivo, este import volta a `from tests.golden.gerar import ...` numa linha só.

## P3.2. Task 4

`MatchResult.layer` não foi renomeado quando os resolvers ganharam `name`. São conceitos diferentes por desenho: `layer` é proveniência — quem produziu aquele vínculo específico —, `name` é identidade do resolver que roda na cascata. Hoje os valores coincidem (`"L1"`, `"L2"`, `"L3"`) porque cada resolver produz exatamente os próprios matches, mas são campos com propósitos distintos, e `metrics.matches_by_layer` já consome `layer` como taxa por camada antes deste plano existir. Alternativa rejeitada: unificar em um campo só (`name`) e apagar `layer` — economizaria um campo hoje, mas prenderia "quem produziu o match" a "quem é o resolver atual" para sempre, o que quebra no dia em que um resolver processar matches de proveniências diferentes (ex.: um agente que reclassifica um match de regra). Custo se errado: dois campos que sempre carregam o mesmo valor, redundância visível mas inofensiva.

## P3.3. Task 5

`Investigator.investigate()` foi mantido intocado ao lado do novo `resolve()`. `resolve(work)` é o ponto de entrada uniforme que o protocolo `Resolver` exige — é o que a cascata chama. `investigate()` é onde o laço de turnos, orçamento, parsing e chamada ao modelo de fato vivem, e é o método que carrega a maioria dos testes existentes do agente (27 testes no arquivo, todos passando sem alteração). Alternativa rejeitada: inlinar o corpo de `investigate()` dentro de `resolve()` e apagar o nome antigo — economiza um método, mas reescreve (e força re-revisão de) o comportamento mais delicado do sistema por motivo puramente estético. Custo se errado: uma camada de indireção a mais (`resolve` chama `investigate` por baixo); zero risco comportamental, porque o corpo não muda.

## P3.4. Task 6

`reconcile` importa `default_definition` dentro do corpo da função, não no topo do módulo. `definition.py` importa `default_resolvers` de `engine.py` no nível de módulo; um import de topo no sentido inverso (`engine.py` → `definition.py`) seria circular. A assinatura de `reconcile` ainda precisa anotar o tipo `WorkflowDefinition`, então um import guardado por `TYPE_CHECKING` supre a anotação sem executar em tempo real (e sem reintroduzir a circularidade, porque o bloco `TYPE_CHECKING` nunca roda fora de type checkers estáticos). Alternativa rejeitada: mover `default_resolvers` para um terceiro módulo neutro que ambos importam — resolve o ciclo de verdade, mas reestrutura um módulo que os dez testes anteriores já exercitam, por causa de uma única função de fábrica. Custo se errado: um import dentro de função em vez de no topo — padrão comum em Python para quebrar ciclos, com uma linha de comentário explicando o motivo.

## P3.5. Task 6

`default_definition()` não contém agente algum — só as três regras (`L1`, `L2`, `L3`) num único stage. Consequência direta: o que as regras não resolvem vira LACUNA na tela, não uma linha AGENTE com um selo "não medido". Alternativa rejeitada: incluir um `Investigator` na definição padrão servida pela API — daria ao canvas algo para desenhar na quarta linha, mas ligaria a única definição servida hoje a um resolver que gasta dinheiro de verdade, exatamente a armadilha que o §5.2 do spec desta fatia existe para fechar. Custo se errado: a tela mostra uma lacuna honesta em vez de um selo de agente; corrigível servindo uma segunda definição (`conciliacao-com-agente`) quando existir gravação — ver a tabela de anti-escopo do §2 do spec e a nota adicionada ao §5.3.

## P3.6. Task 7

`metrics.py` passa a pular a chamada a `custo.microcents(model)` quando `custo == Cost.zero()`, em vez de chamar incondicionalmente como o brief especificava ao pé da letra. `Cost.microcents` valida o modelo contra a tabela de preços ANTES de olhar os valores, então o código verbatim do brief levantaria `ValueError` para qualquer cascata só-de-regras (`L1`/`L2`/`L3`, sempre `Cost.zero()`) rodando com um `model` sem preço cadastrado — regressão em relação ao comportamento anterior, que só convertia quando havia proposta. Rastreado antes de aceitar o atalho: nenhum chamador real perde a guarda de configuração, porque `Investigator.__post_init__` já rejeita um modelo sem preço na CONSTRUÇÃO (`Cost.zero().microcents(self.client.model)` dispara lá), então o único lugar que dependia de `Cost.microcents` validar incondicionalmente continua validando. Alternativa rejeitada: mudar `Cost.microcents` para tratar custo zero como caso especial de forma global — quebraria esse teste de construção do `Investigator`, que depende exatamente do comportamento atual. Custo se errado: uma cascata só-de-regras com `model` inválido reportaria zero em vez de estourar; nenhum teste hoje passa esse caso, e o `Investigator` continua barrando o modelo inválido onde já importa (na construção).

## P3.7. Task 9

`gap.items` é calculado como `bank_total - bank_matched`, não como o total menos a soma das contagens de match por resolver (`sum(r.matches for r in por_resolver)`), que era o código que o brief mostrava verbatim. A segunda fórmula assume implicitamente que todo `MatchResult` carrega exatamente um id bancário — verdade hoje (medida: zero matches com mais de um id bancário em três sementes, e `sum(matches_by_layer.values()) == bank_matched` exatamente), mas não garantida pelo tipo. `bank_matched` já é o conjunto de ids bancários casados intersectado com o dataset real, a mesma garantia de domínio que `evaluate` aplica contra resolver hostil ou com bug — não depende dessa suposição. Consequência pretendida: o teste que soma as taxas por resolver com `gap.rate` e espera 1.0 deixa de ASSUMIR essa invariante e passa a VERIFICÁ-LA. Alternativa rejeitada: o código verbatim do brief (soma das contagens) — mais direto de ler, mas silenciosamente errado no dia em que um resolver produzir um match multi-lançamento, e o teste de soma-para-1.0 não pegaria isso porque as duas fórmulas coincidem sempre que a invariante vale. Custo se errado: nenhum hoje — as duas fórmulas produzem o mesmo número em todo caso medido; a diferença só aparece se a invariante quebrar, e é exatamente aí que a fórmula escolhida continua correta e a rejeitada mentiria.

## P3.8. Task 9 — a mais consequente do plano

**A técnica do teste do dinheiro foi trocada depois de a original se provar vazia — demonstrado, não teorizado.** O plano especificava injetar um `LLMClient` que levanta uma exceção de dentro de `complete()` e exigir `status_code == 200` da rota de execução. Isso não prova nada contra o único agente que existe no projeto: `Investigator._uma()` envolve a chamada a `complete()` num `try/except Exception` largo e DELIBERADO — o próprio módulo comenta "nunca levanta por causa do modelo" — então qualquer exceção vinda de `complete()`, seja falha de rede real ou o `AssertionError` do canário, vira abstenção silenciosa (`Proposal.abstencao`, custo `Cost.zero()`) e a rota devolve 200 de qualquer jeito. A verificação: um `Investigator` real foi ligado a uma cópia de `default_definition()` e o teste antigo — do jeito que o brief especificava — CONTINUOU PASSANDO com o agente no caminho de execução. O design defensivo do `Investigator` (nunca propagar falha do modelo, para não derrubar um fechamento inteiro por causa de um item) neutraliza exatamente o mecanismo que o canário usa para detectar a chamada. Em produção real, sem monkeypatch, um `Investigator` ligado por engano chamaria a API de verdade — gastando dinheiro de verdade — e o endpoint devolveria 200 do mesmo jeito, tanto no caminho de sucesso quanto no de erro. O teste antigo não perceberia nenhum dos dois casos. Substituição: duas asserções independentes, sem depender de exceção nenhuma. Primeira, um espião que NUNCA levanta — grava cada chamada a `complete()` (`system`, `messages`, `tools`) numa lista e devolve uma resposta de mentira — com a asserção sobre o próprio estado do espião (`chamadas == []`). Segunda, uma asserção estrutural sobre a resposta do endpoint: todo resolver em `by_resolver` tem `cost_class == "REGRA"`. Reverifiquei com o mesmo `Investigator` real ligado: as duas asserções falham, cada uma por um motivo diferente e independente (o espião captura 36 chamadas reais; o `by_resolver` passa a incluir um resolver de classe `AGENTE`) — nenhum ajuste foi feito para "fazer passar". Alternativa rejeitada: manter a técnica de exceção do plano original, documentando a limitação em comentário — foi tentado primeiro (round 1) e sobreviveu à tarefa até a re-verificação pedida expor que o teste era vazio contra o único agente real do projeto; manter um teste vazio com aviso escrito é pior que trocar a técnica, porque quem lê `200 = sem gasto` confia no verde do teste, não no comentário ao lado. Custo se errado: esta é a garantia de mais alto risco desta fatia — "nenhum endpoint gasta dinheiro" (§5.2) — protegida antes só por uma exceção que o próprio design do agente absorve; com a técnica antiga em produção, um `Investigator` ligado por engano na definição servida chamaria a API real a cada request sem que teste algum acusasse, até a fatura aparecer.

## P3.9. Task 9

`lru_cache` no endpoint de execução, com a chave incluindo o id do workflow além dos parâmetros do benchmark (`seed`, `n`, `taxa`) — dois workflows com os mesmos parâmetros não colidem na mesma entrada de cache. O 404 de workflow desconhecido é levantado ANTES de qualquer memoização, na função que recebe o id, delegando para a função decorada só depois de validar. Alternativa rejeitada: cachear pela assinatura completa da request incluindo o id já validado dentro da função decorada — funcionaria, mas esconderia um 404 atrás de uma chamada de cache (`lru_cache` sempre executa a função na primeira chamada de uma chave nova, então o erro ainda sairia, mas só depois de a função decorada montar parte do estado) em vez de falhar cedo e de forma óbvia na borda da rota. Custo se errado: um id inválido custaria uma entrada de cache desperdiçada em vez de falhar antes de tocar a lógica de execução — sem risco de gasto, porque o cache é só para a execução determinística, que nunca chama o agente.

## P3.10. Task 11

o §7.2 do spec desta fatia (`docs/superpowers/specs/2026-09-15-cascata-e-canvas-design.md`) foi corrigido para descrever a técnica de teste do dinheiro que de fato ficou (espião + asserção estrutural), não a técnica por exceção que o documento ainda descrevia. Não estava na lista de arquivos do brief da Task 11 (que só cita §6), mas deixar §7.2 descrevendo uma técnica comprovadamente vazia — registrada em P3.8 como a decisão mais consequente do plano — contradiria o próprio propósito desta tarefa, que é corrigir o spec onde a realidade divergiu dele. Alternativa rejeitada: tocar só §6 como o brief lista literalmente, e deixar §7.2 para uma tarefa futura — deixaria o documento de design, que é a fonte consultável do plano, ensinando um teste que não existe mais. Custo se errado: uma seção do spec editada além do que o brief listou explicitamente; o conteúdo em si não é controverso — é a mesma história que P3.8 já registra em detalhe.

---

# Plano 4 — fila de revisão humana

**13 decisões** tomadas sem consulta prévia durante a execução do plano 4 —
o agente propõe, o humano decide, e é a decisão, nunca a proposta, que resolve
a divergência. Mesmo critério das seções anteriores: cada uma traz a
alternativa rejeitada e o custo de estar errada.

---

## P4.1. Task 1

`ids_de_conciliar_com` devolve `frozenset()` vazio para qualquer forma que não
seja exatamente `conciliar_com(a, b)` — inclusive `conciliar_com(l1))`, com
parênteses sobrando dentro do conteúdo extraído. Alternativa rejeitada:
aceitar o texto até o primeiro `)` e ignorar o resto — salvaria o caso de um
parêntese digitado a mais, mas transformaria uma ação malformada num id
plausível-porém-errado (`"l1)"` como id de lançamento), que só falharia
adiante, silenciosamente, quando `revisor.py` não encontrasse esse id em
nenhum dos dois lados do pool e descartasse a decisão inteira como obsoleta —
o reviewer veria 200, o item sumiria da fila, e nenhum vínculo seria criado.
Devolver vazio para qualquer forma quebrada faz o mesmo descarte acontecer
pela mesma rota, mas sem fabricar um id corrompido no meio do caminho. Custo
se errado: uma ação com parêntese sobrando que poderia ter um único id válido
extraído é tratada como "não concilia nada" em vez de tentar recuperar parte
dela.

## P4.2. Task 3

escopo da fila por `dataset_id(seed, n, taxa)`, não só pelo `workflow_id`.
`d-b-b00003` existe em toda semente do gerador sintético — é o mesmo id de
divergência apontando para lançamentos diferentes conforme seed/n/taxa
mudam. Alternativa rejeitada: uma fila só por `workflow_id`, mais simples de
navegar — uma decisão tomada olhando a semente 1 se aplicaria, sem aviso, a
um lançamento completamente diferente na semente 7. Custo se errado: uma
decisão de revisão apontaria para o lançamento errado sempre que alguém
trocasse de semente ou de `n` sem perceber que a fila também mudou de arquivo.

## P4.3. Task 3

dentro de uma mesma fila, PRIMEIRA proposta vence e ÚLTIMA decisão vence —
duas regras opostas no mesmo arquivo, de propósito. Uma proposta é o agente
falando uma vez sobre uma divergência; uma segunda proposta para o mesmo id
só apareceria por reprocessamento, e aceitá-la apagaria o que o revisor já
leu e talvez já tenha decidido em cima. Uma decisão é um humano que pode
mudar de ideia; a mais recente é o estado corrente, e o log guarda todas as
anteriores como auditoria. Alternativa rejeitada: última vence dos dois
lados, por uniformidade — deixaria uma reinvestigação acidental substituir
silenciosamente o texto que um revisor já tinha julgado. Custo se errado:
com a regra atual, uma correção de proposta feita por reprocessamento nunca
chega ao revisor; o único jeito de corrigir uma proposta é uma decisão nova,
não uma proposta nova.

## P4.4. Task 3

`Fila.vazia()` é uma fila em memória que nunca toca o disco (`Fila(None)`,
com `_acrescentar` virando no-op quando `caminho is None`). É o que
`default_definition()` usa quando ninguém passa fila explícita — o revisor
entra sempre na cascata, mas sem fila ele não emite nenhum match. Alternativa
rejeitada: `default_definition()` sem revisor nenhum quando não há fila, com
o revisor entrando só numa segunda definição — reintroduziria a bifurcação
"definição servida" vs "definição executada" que a Task 6 do plano 3 (P3.5)
fechou de propósito. Custo se errado: sem este caminho, toda chamada a
`reconcile()` sem fila explícita (golden, testes antigos, CLI sem `--fila`)
precisaria passar uma fila descartável na mão, ou o revisor teria que sumir
da cascata padrão — voltando à bifurcação que P3.5 evitou.

## P4.5. Task 4

o lado de cada id que uma decisão concilia vem do POOL (`work.bank`/
`work.ledger`, os dois lados ainda não casados no momento em que o revisor
roda), nunca do prefixo do próprio id (`b`/`l`) nem do tipo da divergência.
Um id que não aparece em nenhum dos dois lados do pool é obsoleto — regra já
resolveu antes, ou outra decisão já fechou o caso — e a decisão inteira é
descartada em silêncio, nunca em erro. Alternativa rejeitada: inferir o lado
pelo prefixo do id (`b00003` é banco, `l00003` é contábil) — mais direto de
ler, mas depende de uma convenção de nomenclatura do gerador sintético que
nada no domínio real garante, e não distingue "id nunca existiu" de "id já
foi consumido por outra camada". É esta classificação, e só ela, que faz o
passo 4 da prova de ponta a ponta da Task 10 funcionar sem nenhum código
especial: aceitar a proposta do lado bancário remove os dois ids do pool
juntos, e o meio-item fantasma do lado contábil deixa de existir como
consequência, não como feature. Custo se errado: um id do lado errado do
pool seria aceito como válido, criando um `MatchResult` que mistura dois
lançamentos do MESMO lado — o defeito que o §3.5 do spec deste plano existe
para impedir.

## P4.6. Task 5

`ReconcileResult` ganha `matches_by_class: dict[CostClass, list[MatchResult]]`,
e `metrics.py` usa isso — não `MatchResult.layer` — para decidir o que conta
como determinístico. `layer` é proveniência (P3.2 em DECISOES.md: quem
produziu aquele vínculo específico), não identidade de classe de custo; usar
`layer` para essa decisão prenderia "é regra ou é humano" a uma string que
cada resolver escolhe livremente. Alternativa rejeitada: comparar
`layer in {"L1", "L2", "L3"}` — funciona hoje porque cada resolver nomeia a
própria proveniência igual ao próprio nome, mas quebra no dia em que
`RevisorHumano` reclassificar um match de outra proveniência, ou um resolver
usar um `layer` que não seja o nome dele. Custo se errado: uma migração
futura de proveniência (ex.: revisor confirmando um match que L3 propôs)
contaria como determinístico ou como humano pela string errada, sem nenhum
teste acusando — porque hoje as duas fontes coincidem por coincidência, não
por garantia de tipo.

## P4.7. Task 5

dinheiro (`Valor conciliado`, `Valor em divergência`) conta TODAS as classes
de custo; a taxa determinística (`deterministic_rate`, falsos positivos e
negativos) conta só REGRA. São duas perguntas diferentes: quanto dinheiro
está resolvido de fato, contra quanto uma regra sozinha resolveu sem
intervenção. Alternativa rejeitada: as duas métricas na mesma população
(as duas REGRA-only, ou as duas todas-as-classes) — mais simples de explicar,
mas ou esconderia o valor que o revisor humano fechou (subestimando o
produto), ou contaria aprovação humana como se fosse determinismo de regra
(inflando a métrica que este projeto já corrigiu uma vez por contaminação
silenciosa, `e6b2b05`). Custo se errado: um revisor aprovando um caso do
agente moveria `deterministic_rate` para cima sem nenhuma regra nova ter
rodado — o mesmo defeito que a Task 5 deste plano existe para fechar,
reaberto por outra porta.

## P4.8. Task 6

o `POST` de decisão chama `_executar_memoizado.cache_clear()` depois de
gravar. `_executar_memoizado` deixou de ser função pura dos três parâmetros
do benchmark assim que passou a ler a fila em disco — ela também depende do
conteúdo do arquivo de decisões, que o `lru_cache` não vê. Alternativa
rejeitada: cache com TTL curto em vez de invalidação explícita — evitaria
acoplar a rota de escrita ao detalhe de cache da rota de leitura, mas faria
uma decisão recém-aprovada ficar invisível no canvas por um tempo arbitrário
depois do clique, o oposto do que "aceitar e ver o efeito" deveria ser numa
tela de revisão. Custo se errado: sem a limpeza, o canvas mostraria o estado
anterior à decisão até o processo reiniciar ou o cache estourar por
tamanho — o passo 3 da prova de ponta a ponta da Task 10 falharia sempre,
mesmo com o mecanismo de revisão correto por baixo.

## P4.9. Task 6

`_construir_definicao` decide se repassa `fila` a uma fábrica de workflow
introspectando a ASSINATURA dela por um parâmetro chamado literalmente
`fila` — sem checagem estrutural nem import de tipo entre `api/app.py` e
`workflow/definition.py`. Uma fábrica cuja assinatura não seja "aceita
`fila`" nem "não aceita nada" levanta `TypeError` em vez de cair
silenciosamente para `fabrica()` (o que aplicaria o argumento errado a um
parâmetro qualquer, ou ignoraria a fila sem avisar). Um teste em
`tests/workflow/test_definition.py` pina o nome literal `fila` do parâmetro
de `default_definition`, porque é o único contrato entre os dois módulos.
Alternativa rejeitada: um protocolo formal (`class WorkflowFactory(Protocol):
def __call__(self, fila: Fila) -> WorkflowDefinition`) — mais explícito, mas
exigiria toda fábrica de teste (que hoje registra função de zero argumentos
direto em `_WORKFLOWS`) migrar para a mesma assinatura, só para declarar um
contrato que uma introspecção de uma linha já cobre. Custo se errado: trocar
o nome do parâmetro em `default_definition` sem tocar `app.py` quebra o
teste que pina o nome, mas não quebra silenciosamente em produção — é
exatamente o ponto de pinar.

## P4.10. Task 6

o teste `test_ler_a_fila_nao_chama_o_modelo` mudou de propósito depois de a
revisão apontar que ele passava por acidente, não por prova. Com a fila
vazia (estado original do teste), `_item()` nunca roda — não existe proposta
pendente para montar — então o teste passaria mesmo que `_item` chamasse o
modelo por baixo; é a mesma classe de teste vazio que P3.8 já documentou
para a rota de execução, agora encontrada na rota de fila. Correção: o teste
agora semeia uma proposta de verdade antes de espiar `anthropic_client`, e
acrescenta `assert r.json()["itens"] != []` para garantir que o laço de
montagem de item de fato executou. Alternativa rejeitada: manter o teste
como estava, documentando em comentário que ele exige fila não-vazia para
valer algo — um teste que precisa de aviso ao lado para não enganar quem lê
o verde é pior que corrigi-lo. Custo se errado: nenhum — o teste antigo
nunca discriminava o defeito; o novo, sim, e a suíte confirma que ele
continua verde com o código real.

## P4.11. Task 6

a guarda de idempotência do agente (`Investigator`, que já existia deste
plano) fica em `investigate()`, no laço que soma custo total da passagem, e
não em `_uma()`, que é onde a proposta guardada é servida. `serial.py`
persiste os cinco campos de `Cost`, então uma proposta lida do disco carrega
o gasto REAL da investigação original — se `investigate()` somasse esse
custo ao total desta passagem, uma execução que só serviu propostas
guardadas (gasto real: zero) apareceria com o gasto da execução ANTERIOR, e
o teto por execução estouraria sobre dinheiro que não foi gasto agora.
Alternativa rejeitada: manter a guarda em `_uma()` e subtrair o custo
histórico de volta no chamador — funciona, mas exige que todo chamador de
`_uma()` saiba filtrar propostas servidas da fila para não contar o custo
delas, duplicando a regra em vez de ter um único ponto que nunca deixa o
custo histórico entrar no total. Custo se errado: uma segunda passagem sobre
o mesmo dataset, com a fila já populada pela primeira, reportaria custo e
consumiria teto de orçamento por trabalho que não fez.

## P4.12. Task 8

a API recusa com 422 em dois pontos que antes aceitavam em silêncio e
descartavam depois: aceitar uma proposta cuja `acao_sugerida` começa com
`conciliar_com` mas não extrai nenhum id (forma quebrada como
`"conciliar_com:l1"`, sem parênteses), e corrigir com um id que não existe
em nenhum dos dois lados do dataset. Nos dois casos, sem o guard, o pedido
chegava intacto até `revisor.py`, que marcava a decisão inteira "obsoleta" e
a descartava — o reviewer via 200, o item sumia de `pendentes()`,
`divergiu` acusava divergência do agente, e nenhum vínculo era criado.
Alternativa rejeitada: deixar `revisor.py` ser a única linha de defesa, já
que ele descarta o caso obsoleto de qualquer jeito — tecnicamente seguro
(nenhum vínculo fantasma é criado), mas transforma um erro de entrada em
silêncio operacional: ninguém percebe que a decisão não fez nada até
auditar o log. Custo se errado: um clique de "aceitar" ou "corrigir" que
parecia ter funcionado (200) não concilia nada, e só a trilha de auditoria
do jsonl revela isso depois.

## P4.13. Task 9

o formulário de correção em `/fila.html` é alternado por uma CLASSE
(`.aberta`, que carrega o `display` real), nunca pelo atributo `hidden`, e
"Corrigir" só alterna essa classe — nunca decide sozinho; um botão separado
("Confirmar correção") dentro da caixa é o único caminho até `decidir()`.
Descoberto tarde: o CSS do bloco de autor já declarava `display:flex` na
classe do container de correção, o que vence o `display:none` que o
`hidden` do user agent aplicaria — a caixa ficava visível desde o primeiro
paint, o primeiro clique em "Corrigir" parecia não fazer nada (já estava
"aberta" aos olhos), e o segundo clique caía direto em `decidir("corrigir",
...)` com o `<select>` ainda no primeiro tipo da lista e nenhum id — o
backend aceita isso como abstenção legítima, gravando uma correção
inventada no log de decisões. Alternativa rejeitada: continuar usando
`hidden` e corrigir só o CSS que o sobrepunha — trataria o sintoma (o
elemento errado ficando visível), não a causa (um único botão fazendo duas
coisas, abrir a caixa E submeter, dependendo de quantas vezes foi clicado).
Separar "abrir" de "confirmar" em dois controles elimina a ambiguidade de
contagem de cliques por construção. Custo se errado: sem a separação, todo
fluxo de correção fica um clique-fantasma de distância de gravar uma decisão
falsa no log de auditoria — exatamente o defeito que este item corrigiu
depois de já commitado uma vez sem ele.

## P4.14. Task 10 — resolvida na própria Task 10 (rodada de correção)

Achado original: `web/canvas.js` (`PEDIDO = { seed: 1, n: 300, ... }`, do
plano 3) e `web/fila.js` (`PARAMS = { seed: 1, n: 30, ... }`, da Task 9 deste
plano) apontavam para datasets DIFERENTES — a fila é escopada por
`dataset_id` (P4.2), e os dois arquivos nunca tinham sido alinhados ao mesmo
`n`. Na primeira passada da prova de ponta a ponta isso significava que
aceitar uma proposta em `/fila.html` (dataset `s1-n30-t0.15`) nunca aparecia
em `/` (dataset `s1-n300-t0.15`, sem fila gravada) — os dois liam arquivos de
fila diferentes, PARA SEMPRE, para qualquer usuário, porque os valores
estavam fixos em cada arquivo. O mecanismo por baixo (`revisor.py`,
`_executar_memoizado`) já estava correto — confirmado batendo a API
diretamente com os parâmetros da fila — mas a demonstração publicada
(abrir `/` depois de decidir em `/fila.html`) não fechava visualmente, o que
derrota o que esta fatia existe para provar: aprovar na fila e VER o canvas
mudar.

**Correção:** as duas páginas passaram a ler `seed`/`n`/`taxa_divergencia` da
própria URL (`location.search`), com o MESMO padrão nas duas quando o
parâmetro está ausente (`seed=1`, `n=300`, `taxa_divergencia=0.15` — os
mesmos de `RunRequest` em `api/schemas.py`). Cada página ganhou um link para
a outra carregando a query string atual (`Ver a fila de revisão →` no
canvas, `← Ver a cascata` na fila), para navegar entre as duas sem perder o
dataset de vista. Alternativa rejeitada: só igualar as duas constantes
(`n:300` nos dois arquivos) — resolveria o sintoma medido, mas é a MESMA
classe de defeito que criou o problema: um valor duplicado em dois arquivos
sem nenhum mecanismo que os mantenha iguais, que já drift uma vez (Task 9
escolheu 30, Plano 3 já tinha escolhido 300, e nada acusou a divergência até
esta tarefa testar as duas páginas juntas). Ler da URL faz as duas páginas
concordarem por CONSTRUÇÃO — não há um segundo lugar para o valor ficar
desatualizado. Custo se errado: se um dia as duas páginas precisarem de
padrões diferentes de propósito (por exemplo, a fila mostrando um dataset
menor por padrão para carregar mais rápido), a homogeneização atual exigiria
uma decisão explícita de produto para diferenciá-los de novo — o oposto do
custo do defeito original, que era diferenciação acidental por nunca terem
sido escritos juntos.

Reprovado com os próprios olhos depois da correção, no navegador, com
`n=30` na query string dos dois lados (dataset barato de avaliar de verdade
pela assinatura): canvas ANTES da decisão mostrava `revisor` HUMANO 0.0% e
lacuna 3.6%; depois de aceitar `d-b-b00003` em `/fila.html?...&n=30`, o
MESMO canvas (`/?...&n=30`, recarregado) mostrou `revisor` HUMANO 3.6% e
lacuna 0.0%. O passo 3 do roteiro da Task 10, que na primeira rodada só
tinha sido confirmado mecanicamente (via API), passou a se ver na tela.
