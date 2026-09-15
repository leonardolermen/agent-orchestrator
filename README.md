# Agent Orchestrator

> **Nome de trabalho.** Marca a definir quando houver cliente.

Runtime para transformar processos reais de backoffice financeiro em execução
confiável e auditável: **workflow determinístico, com agente apenas onde
inteligência é necessária.**

## A tese

A camada de orquestração de agentes virou commodity. A camada de execução
confiável, não. E o erro mais caro em produção não é o agente falhar — é gastar
US$ 15 num encadeamento de LLMs para resolver algo que uma query resolve por
centavos.

Então a fronteira entre código e agente **é** o produto:

```
entrada estruturada
      ↓
  [código]   normalização
      ↓
  [código]   regra determinística  ──→ resolvido (83-92%) ──→ fim, centavos
      ↓ não resolvido
  [AGENTE]   investigação com ferramentas
      ↓
  proposta + evidência + confiança
      ↓
  [humano]   aprova / rejeita / corrige
      ↓
  correção vira caso de teste no benchmark
```

A última seta é o ativo de longo prazo. Em seis meses, o conjunto de avaliação
é a coisa que um concorrente não copia.

## Por que Brasil

Não é geografia — é que a stack documental e regulatória brasileira é
idiossincrática: NF-e, SPED, CNAB, retenção de ISS/IRRF, Pix, ERPs nacionais,
LGPD. Trabalho chato, local, que fornecedor de fora não faz direito. Em
"agentes genéricos" não haveria fosso nenhum; aqui há.

## Primeira fatia: investigação de divergência em conciliação

Matching determinístico em código resolve a maioria dos casos. O agente acorda
só no resto: busca contexto, cruza fontes, propõe explicação com evidência,
humano decide.

Escolhida por três motivos:

1. A tese fica visível no produto, não no slide — a conta no fim do mês é pequena
2. O output é auditável linha a linha por quem recebe
3. O dado de avaliação pode ser gerado sinteticamente **com gabarito**, sem
   depender de dado real de terceiros

## O que este projeto NÃO é (ainda)

Anti-escopo vale tanto quanto escopo:

- **Não** é workflow engine genérico com DSL
- **Não** reimplementa durable execution — se virar necessário, entra
  Temporal/Restate por baixo, e a fronteira de execução fica isolada pra isso
- **Não** tem marketplace de agentes
- **Não** é multi-tenant
- **Não** deixa o agente fazer o matching

A plataforma é o produto do ano 2, **extraída** de três casos reais — não
projetada a partir de zero instâncias.

## Decisões

| Data | Decisão | Razão |
|---|---|---|
| 2026-09-14 | Produto antes de plataforma | Abstração se extrai de instâncias, não se projeta |
| 2026-09-14 | Python | Ecossistema de avaliação; o benchmark é o ativo |
| 2026-09-14 | Sem engine durável no v1 | Conciliação leva minutos, não dias — Temporal resolve um problema que ainda não temos |
| 2026-09-14 | Zero dado de terceiros | Projeto pessoal; validação por dado sintético com gabarito |

## Status

Núcleo determinístico funcionando, e o agente de investigação (plano 2)
também — mas o agente nunca fez uma chamada real ao modelo, porque a conta
usada para desenvolver não tem crédito. Esta fatia (plano 3) uniu as três
camadas de regra e o agente atrás de um único protocolo `Resolver`, rodando
como cascata ordenada por custo; empacotou essa cascata numa
`WorkflowDefinition` que o motor executa e a API serializa sem cópia paralela;
mediu custo por resolver, não só por sistema; e acrescentou um canvas somente
leitura que desenha a cascata com números medidos, não inventados.

```bash
pip install -e ".[dev]"
pytest
orchestrator --seed 1 --n 500
```

Flags da CLI: `--seed` (semente do gerador), `--n` (tamanho do dataset) e
`--taxa-divergencia` (fração de pares que recebe divergência injetada — é o
flag que move a taxa determinística reportada acima).

### Ver a cascata no canvas

```bash
pip install -e ".[dev,api]"
uvicorn orchestrator.api.app:app --port 8000
```

Abra `http://localhost:8000`: a página mostra, para a definição servida, cada
resolver da cascata com classe de custo, taxa de resolução e custo — tudo
medido contra um benchmark sintético — e a lacuna que nenhum resolver cobre,
declarada em vez de escondida. Nenhum endpoint por trás da página tem caminho
de código até o modelo (ver `tests/api/test_execucao.py`), então nenhum F5
gasta dinheiro.

### Avaliar o agente (gasta dinheiro)

Exige `ANTHROPIC_API_KEY` no ambiente ou `ant auth login`.

```bash
orchestrator-eval --n 100 --seed 1
```

Sem `--model`, compara `claude-opus-5`, `claude-sonnet-5` e `claude-haiku-4-5`
contra o mesmo gabarito. A suíte de testes não faz nenhuma chamada de API.

### Fila de revisão humana

O agente propõe; ele nunca resolve. `--fila` grava as propostas de uma
avaliação na fila de revisão em vez de só imprimir o relatório:

```bash
orchestrator-eval --via assinatura --seed 1 --n 30 --fila
```

Isso escreve `data/fila/conciliacao/s1-n30-t0.15.jsonl` — um append-only por
`(workflow, dataset)`, escopado por `seed`/`n`/`taxa_divergencia` porque o
mesmo id de divergência aponta para lançamentos diferentes conforme o dataset
muda. Com o servidor no ar (`uvicorn orchestrator.api.app:app --port 8000`),
abra `http://localhost:8000/fila.html?seed=1&n=30&taxa_divergencia=0.15`: cada
proposta pendente aparece com o lançamento bancário e o contábil lado a lado,
e três botões — aceitar, rejeitar ou corrigir o tipo e os ids a conciliar.
Decidir grava uma `Decision` na mesma fila e invalida o cache do canvas, que
passa a mostrar o `revisor` — o resolver de classe `HUMANO` que fecha a
cascata — com o match aprovado.

`seed`, `n` e `taxa_divergencia` vêm da query string em `/` e em `/fila.html`
— as duas páginas usam os MESMOS padrões (`seed=1`, `n=300`,
`taxa_divergencia=0.15`, os mesmos de `RunRequest` na API) quando nenhum
parâmetro é passado, então basta abrir as duas sem query para as duas
apontarem para o mesmo dataset. Cada página tem um link para a outra que
carrega a query string atual, para navegar entre a cascata e a fila sem
perder de vista o dataset. Ao testar com um dataset menor (como `n=30` acima,
para manter uma avaliação real barata), abra as duas páginas com a MESMA
query string — a fila é escopada por dataset, então uma decisão tomada em
`/fila.html?n=30` só aparece em `/?n=30`, nunca em `/` sozinho (que usa o
padrão `n=300`).

A frase que resume a fatia inteira: **decisão é o que resolve; proposta nunca
resolve.** `reconcile()` continua puro — só lê a fila através do `revisor`, só
o CLI grava proposta e só a API grava decisão — e é disso que o golden e o
teste de "nenhum endpoint gasta dinheiro" dependem.
