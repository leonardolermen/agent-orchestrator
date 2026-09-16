"""Os 50 casos curados de triagem de issue.

**Por que 50 e não 5.** Com cinco casos, um acerto vale vinte pontos — e entre
duas execuções do MESMO braço a precisão variou de 75% a 100%. Não dava para
distinguir sinal de ruído, e os vereditos do M6/M8 diziam isso na cara. Com
cinquenta, um acerto vale dois pontos.

**O viés que 50 casos NÃO removem, e vale declarar.** Fui eu quem escreveu os
cinquenta, na mesma sessão em que escrevi o prompt que os classifica. Eles
codificam o meu entendimento do que é BUG, FEATURE e DÚVIDA — inclusive onde
esse entendimento está errado. Mais casos reduzem ruído estatístico; não
reduzem viés de autor. O que reduz viés de autor é `Provenance.HUMANO`: casos
colhidos de revisão real, pelo `harvest`. Estes são `ESPECIALISTA`, e a
procedência está gravada em cada um justamente para que ninguém os confunda.

**A estrutura, e por que ela importa mais que o número.** Cada caso tem uma
marca de dificuldade:

  `facil`        — o rótulo está na superfície (stack trace, "precisamos de").
                   Servem para detectar REGRESSÃO: o que hoje acerta e não pode
                   parar de acertar.
  `adversarial`  — a superfície aponta para o rótulo ERRADO. Um bug relatado
                   como pergunta educada, um pedido de funcionalidade escrito
                   como reclamação, uma dúvida que parece defeito.

Um conjunto só de fáceis mede quase nada e sobe sozinho. Um conjunto só de
adversariais não detecta regressão no caso fácil — que é onde ela aparece
primeiro, porque é onde ninguém olha. A proporção aqui é ~60/40.

**Balanceamento.** 17 BUG, 17 FEATURE, 16 DUVIDA. Desbalancear faria um
classificador constante pontuar bem: chutar sempre BUG num conjunto 70% BUG dá
70% de precisão sem nenhuma inteligência.
"""

# (id, título, corpo, esperado, dificuldade)
CASOS: tuple[tuple[str, str, str, str, str], ...] = (
    # ---------------------------------------------------------------- BUG
    # Fáceis: o defeito está na superfície.
    (
        "I-01",
        "App crasha ao abrir relatório mensal",
        "Stack trace: NullPointerException em ReportBuilder.build(), linha 84. "
        "Acontece toda vez desde a versão 2.3.1.",
        "BUG",
        "facil",
    ),
    (
        "I-02",
        "500 ao salvar pedido com mais de 200 itens",
        "O endpoint POST /pedidos devolve 500. No log: "
        "psycopg2.errors.StringDataRightTruncation na coluna observacao.",
        "BUG",
        "facil",
    ),
    (
        "I-03",
        "Botão de exportar não faz nada no Firefox",
        "Console: Uncaught TypeError: e.target.closest is not a function. "
        "No Chrome funciona.",
        "BUG",
        "facil",
    ),
    (
        "I-04",
        "Aplicação trava ao importar CSV de 40 MB",
        "A aba congela e o navegador sugere fechar a página. Reproduzi três "
        "vezes com o mesmo arquivo.",
        "BUG",
        "facil",
    ),
    (
        "I-05",
        "Login falha com senha correta após trocar de senha",
        "Troquei a senha nas configurações, fiz logout, e a senha nova é "
        "recusada. A antiga também. Tive que pedir reset.",
        "BUG",
        "facil",
    ),
    (
        "I-06",
        "Data aparece um dia antes na listagem",
        "Pedido criado em 01/10 aparece como 30/09 na grade. No detalhe do "
        "pedido aparece certo.",
        "BUG",
        "facil",
    ),
    (
        "I-07",
        "Upload de anexo perde o nome do arquivo",
        "Envio 'nota fiscal setembro.pdf' e fica salvo como 'undefined.pdf'. "
        "O conteúdo está certo.",
        "BUG",
        "facil",
    ),
    (
        "I-08",
        "Filtro de status some ao paginar",
        "Filtro por 'cancelado', vou para a página 2 e volta tudo. A URL "
        "mantém o parâmetro.",
        "BUG",
        "facil",
    ),
    (
        "I-09",
        "E-mail de confirmação chega sem o corpo",
        "O cliente recebe o e-mail com assunto correto e corpo em branco. "
        "Começou depois do deploy de terça.",
        "BUG",
        "facil",
    ),
    (
        "I-10",
        "Sessão expira em 2 minutos em vez de 30",
        "Configurado para 30 minutos. Na prática desloga em ~2. Voltou a "
        "acontecer depois da atualização.",
        "BUG",
        "facil",
    ),
    # Adversariais: erro de RESULTADO — nada estoura, nada aparece em log.
    (
        "I-11",
        "Total do relatório vem 3 centavos menor",
        "O somatório da coluna Valor fecha em R$ 1.204,97 mas a soma manual dá "
        "R$ 1.205,00. Reproduzível com o dataset de setembro.",
        "BUG",
        "adversarial",
    ),
    (
        "I-12",
        "Ordenação por fornecedor parece aleatória",
        "Clico no cabeçalho e a lista muda, mas não fica em ordem alfabética. "
        "Acentos parecem ir para o fim.",
        "BUG",
        "adversarial",
    ),
    (
        "I-13",
        "A busca não acha um pedido que existe",
        "Busco por '2024-0891' e não retorna nada. O pedido está na listagem "
        "da página 3 com esse número exato.",
        "BUG",
        "adversarial",
    ),
    # Adversarial: bug relatado como pergunta educada.
    (
        "I-14",
        "É normal o saldo mudar ao trocar de aba?",
        "Estou no painel, vou para Relatórios e volto, e o saldo total está "
        "diferente sem eu ter feito nada. Fecho e abro e volta ao valor "
        "antigo.",
        "BUG",
        "adversarial",
    ),
    (
        "I-15",
        "Alguém mais vê duas vezes o mesmo lançamento?",
        "Na conciliação de outubro o lançamento 4471 aparece duplicado na "
        "tela, mas só existe um no banco. O total soma ele duas vezes.",
        "BUG",
        "adversarial",
    ),
    # Adversarial: performance relatada como característica.
    (
        "I-16",
        "O fechamento mensal está demorando 40 minutos",
        "Até agosto levava 2 minutos com o mesmo volume. Ninguém mudou "
        "configuração. Começou depois da versão 3.1.",
        "BUG",
        "adversarial",
    ),
    (
        "I-17",
        "Contador reclamou que o imposto retido veio dobrado",
        "Nota com retenção de R$ 150,00 aparece com R$ 300,00 no resumo. Só "
        "nas notas que têm dois itens.",
        "BUG",
        "adversarial",
    ),
    # ------------------------------------------------------------ FEATURE
    # Fáceis: pedido explícito.
    (
        "I-18",
        "Exportar relatório em CSV",
        "Hoje só dá para exportar em PDF. Precisamos de CSV para abrir no "
        "Excel e cruzar com a planilha da controladoria.",
        "FEATURE",
        "facil",
    ),
    (
        "I-19",
        "Permitir anexar mais de um arquivo por lançamento",
        "Hoje é um anexo só. Precisamos de pelo menos três (nota, boleto e "
        "comprovante).",
        "FEATURE",
        "facil",
    ),
    (
        "I-20",
        "Adicionar autenticação em dois fatores",
        "Requisito do time de segurança para a certificação. TOTP resolve.",
        "FEATURE",
        "facil",
    ),
    (
        "I-21",
        "Integração com o ERP Omie",
        "Queremos puxar os lançamentos do Omie em vez de importar CSV toda "
        "semana. Eles têm API REST.",
        "FEATURE",
        "facil",
    ),
    (
        "I-22",
        "Modo escuro",
        "O time usa o sistema à noite no fechamento e pediu tema escuro.",
        "FEATURE",
        "facil",
    ),
    (
        "I-23",
        "Webhook quando uma conciliação termina",
        "Precisamos disparar nosso pipeline interno. Um POST com o id do run "
        "já resolve.",
        "FEATURE",
        "facil",
    ),
    (
        "I-24",
        "Histórico de alterações por lançamento",
        "Auditoria pediu para saber quem mudou o quê e quando. Hoje não dá "
        "para saber.",
        "FEATURE",
        "facil",
    ),
    (
        "I-25",
        "Permitir desfazer uma conciliação",
        "Se o revisor aprovar errado, hoje não tem volta. Precisamos de um "
        "desfazer com registro.",
        "FEATURE",
        "facil",
    ),
    (
        "I-26",
        "Agendar o fechamento para rodar de madrugada",
        "Rodar manualmente às 8h trava a máquina de quem chega cedo.",
        "FEATURE",
        "facil",
    ),
    (
        "I-27",
        "Suporte a múltiplas moedas",
        "Passamos a ter fornecedor em USD e hoje o sistema assume BRL em tudo.",
        "FEATURE",
        "facil",
    ),
    # Adversariais: reclamação que é pedido de funcionalidade.
    (
        "I-28",
        "A busca é inutilizável com muitos registros",
        "Com 50 mil linhas não dá para achar nada. Não tem filtro por data nem "
        "por fornecedor, só a caixa de texto.",
        "FEATURE",
        "adversarial",
    ),
    (
        "I-29",
        "Perdi meia hora procurando onde muda o CNPJ da empresa",
        "Não está em Configurações nem no Perfil. Tive que perguntar no "
        "suporte. Devia ter um lugar óbvio.",
        "FEATURE",
        "adversarial",
    ),
    (
        "I-30",
        "Ter que reimportar tudo por causa de uma linha errada é absurdo",
        "Se uma linha do CSV tem erro, o import inteiro falha e preciso "
        "corrigir e subir de novo o arquivo com 8 mil linhas.",
        "FEATURE",
        "adversarial",
    ),
    (
        "I-31",
        "O relatório não serve para o que a diretoria pede",
        "Eles querem por centro de custo e o relatório só agrupa por "
        "fornecedor. Todo mês eu refaço na mão no Excel.",
        "FEATURE",
        "adversarial",
    ),
    # Adversarial: "por que não tem" — parece dúvida, é pedido.
    (
        "I-32",
        "Por que não dá para copiar um lançamento?",
        "Lanço 30 aluguéis idênticos por mês e digito tudo de novo cada vez. "
        "Um botão duplicar resolveria.",
        "FEATURE",
        "adversarial",
    ),
    (
        "I-33",
        "Não existe jeito de exportar só o que está filtrado?",
        "Filtro os 200 pendentes e a exportação traz os 8 mil. Preciso do "
        "recorte que está na tela.",
        "FEATURE",
        "adversarial",
    ),
    (
        "I-34",
        "Seria possível avisar antes de estourar o limite do plano?",
        "Descobrimos que estourou quando parou de processar. Um aviso em 80% "
        "evitaria a parada.",
        "FEATURE",
        "adversarial",
    ),
    # ------------------------------------------------------------- DUVIDA
    # Fáceis: pergunta clara.
    (
        "I-35",
        "Dúvida sobre o campo 'status'",
        "Alguém sabe se o campo status considera pedidos cancelados? Não achei "
        "na documentação.",
        "DUVIDA",
        "facil",
    ),
    (
        "I-36",
        "Qual o formato de data aceito no import?",
        "A planilha do cliente vem em DD/MM/AAAA. O importador aceita ou "
        "precisa converter antes?",
        "DUVIDA",
        "facil",
    ),
    (
        "I-37",
        "Onde ficam os logs em produção?",
        "Preciso investigar um caso de ontem e não sei onde procurar.",
        "DUVIDA",
        "facil",
    ),
    (
        "I-38",
        "O plano gratuito tem limite de usuários?",
        "A página de preços não diz e o comercial me mandou perguntar aqui.",
        "DUVIDA",
        "facil",
    ),
    (
        "I-39",
        "Como faço para rodar os testes localmente?",
        "Clonei o repositório e o README não fala de dependências de "
        "desenvolvimento.",
        "DUVIDA",
        "facil",
    ),
    (
        "I-40",
        "A API tem paginação?",
        "GET /lancamentos devolveu 1000 itens. Existe cursor ou offset?",
        "DUVIDA",
        "facil",
    ),
    (
        "I-41",
        "Qual timezone o sistema usa para gravar as datas?",
        "Estou comparando com nosso banco e quero ter certeza antes de "
        "concluir que há diferença.",
        "DUVIDA",
        "facil",
    ),
    (
        "I-42",
        "Existe ambiente de homologação?",
        "Queremos testar a integração sem mexer em dados reais.",
        "DUVIDA",
        "facil",
    ),
    (
        "I-43",
        "Qual a diferença entre 'conciliado' e 'fechado'?",
        "Os dois aparecem no painel e para mim parecem a mesma coisa.",
        "DUVIDA",
        "facil",
    ),
    (
        "I-44",
        "O webhook reenvia em caso de falha?",
        "Nosso endpoint ficou fora 10 minutos e quero saber se perdemos "
        "eventos.",
        "DUVIDA",
        "facil",
    ),
    # Adversariais: parecem defeito, mas o autor não afirma que está errado.
    (
        "I-45",
        "Comportamento estranho no arredondamento",
        "Valores com três casas aparecem arredondados na tela. Isso é "
        "esperado? Não sei se é regra fiscal ou se está errado.",
        "DUVIDA",
        "adversarial",
    ),
    (
        "I-46",
        "Lançamento sumiu da listagem",
        "Não encontro mais o lançamento 88120. Pode ser que alguém tenha "
        "arquivado? Como confirmo quem fez o quê?",
        "DUVIDA",
        "adversarial",
    ),
    (
        "I-47",
        "É esperado que a importação ignore linhas em branco?",
        "Meu arquivo tem 1200 linhas e importou 1180. As 20 eram vazias. Isso "
        "é intencional?",
        "DUVIDA",
        "adversarial",
    ),
    # Adversarial: parece pedido de funcionalidade, mas é pergunta sobre o que
    # já existe.
    (
        "I-48",
        "Precisamos de relatório por centro de custo — já tem?",
        "Antes de abrir pedido: procurei e não achei, mas pode ser que exista "
        "com outro nome. Alguém sabe?",
        "DUVIDA",
        "adversarial",
    ),
    (
        "I-49",
        "Isso é limitação do plano ou do produto?",
        "Não consigo criar mais de 5 workspaces. Não sei se é o plano ou se o "
        "produto não suporta mais que isso.",
        "DUVIDA",
        "adversarial",
    ),
    (
        "I-50",
        "Dá para usar a API sem criar um usuário administrador?",
        "Segurança aqui não aprova conta admin para integração. Queria saber "
        "se existe outro caminho antes de propor mudança.",
        "DUVIDA",
        "adversarial",
    ),
)
