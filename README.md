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

Próximo: revisão humana da fila de propostas.

### Avaliar o agente (gasta dinheiro)

Exige `ANTHROPIC_API_KEY` no ambiente ou `ant auth login`.

```bash
orchestrator-eval --n 100 --seed 1
```

Sem `--model`, compara `claude-opus-5`, `claude-sonnet-5` e `claude-haiku-4-5`
contra o mesmo gabarito. A suíte de testes não faz nenhuma chamada de API.
