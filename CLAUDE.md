# CLAUDE.md

Runtime de orquestração: workflow determinístico, agente só onde inteligência é
necessária, e um número dizendo quanto cada degrau custou. O `README.md` tem a
tese; este arquivo tem o que quebra se você não souber.

## Comandos

```bash
.venv/Scripts/python.exe -m pytest -q        # suíte inteira (~25s)
.venv/Scripts/python.exe -m ruff check src tests
orchestrator --seed 1 --n 500                # o número que o produto reporta
```

O CI roda mais quatro coisas, e as três primeiras pegam erro que a suíte local
não pega:

- `pytest` em **duas** instalações: `[dev]` e `[dev,api]`. Teste que importa
  extra opcional (`fastapi`, `claude_agent_sdk`, …) precisa de
  `pytest.importorskip` no topo — sem ele o arquivo não pula, ele derruba a
  COLETA da suíte inteira. Foi assim que três arquivos passaram por dez
  revisões sem ninguém ver: todo mundo rodava no venv completo.
- `npx tsc --noEmit` em `web-app/` — o Vite não checa tipos.
- o bundle de `web/` é **commitado** e comparado com a fonte. Mexeu em
  `web-app/src`? `npm --prefix web-app run build && git add web`.
- `orchestrator --seed 1 --n 500` tem de dizer `85.3%`, zero falso positivo,
  zero falso negativo. É a alegação que o README repete.

`ruff format` **não** roda e não deve rodar: o repositório nunca foi formatado
com ele, e adotá-lo é uma decisão própria num commit só.

Nenhum teste fala com a rede — `tests/conftest.py::_rede_proibida` é autouse e
cobre a suíte inteira. Avaliação ao vivo gasta dinheiro de verdade e é sempre
uma decisão explícita, nunca um efeito colateral de rodar testes.

## A fronteira de camadas é cobrada por teste

`tests/arquitetura/camadas.py` tem a arquitetura alvo como tabela, e
`test_camadas.py` a cobra. Duas consequências práticas:

**Arquivo novo custa uma decisão.** Um módulo cujo diretório ainda não é o nome
da camada precisa de entrada em `DESTINO`. Sem ela, `test_todo_modulo_tem_camada`
falha — de propósito: default silencioso faria a fronteira deixar de valer para
o arquivo novo sem ninguém perceber.

**A baseline é catraca de dois lados.** `VIOLACOES_CONHECIDAS` lista o
acoplamento que existe hoje. Violação nova falha; violação corrigida **também**
falha, até você apagar a linha no mesmo commit que a corrigiu. Não contorne
nenhum dos dois lados mexendo na tabela — `PERMITIDO` é decisão de arquitetura,
não ajuste de teste.

Regra nº 1, com teste próprio: **`kernel` não importa nada.** E ninguém importa
`domains` — se uma camada precisar, o conceito está na camada errada.

## Uma ferramenta por arquivo

`domains/reconciliation/agent/ferramentas/` é o formato. Cada arquivo tem a
função e o `ToolSpec`
que o modelo vê **lado a lado**:

```python
def buscar_lancamentos(ctx: ToolContext, ...) -> list[dict[str, Any]]: ...

SPEC = ToolSpec(name="buscar_lancamentos", description=..., input_schema=...,
                fn=buscar_lancamentos, permission=ToolPermission.READ_ONLY)
```

O `__init__.py` só enfileira, e a **ordem** da lista é a ordem dos schemas —
estável de propósito, porque prompt e schemas vão marcados para cache.

O que não fazer, porque já custou caro:

- **Não separe a forma da lógica.** Schema numa lista e função em outro lugar,
  ligados por `getattr(contexto, nome)`, é o join frágil que o `ToolRegistry`
  existe para matar: uma ferramenta passa a existir num lado e não no outro, e
  só uma chamada do modelo descobre.
- **Não ligue a função ao contexto na construção.** A assinatura é
  `fn(contexto, **args)` — sempre, inclusive nas que ignoram o contexto —, e o
  `ToolRegistry` injeta o contexto na EXECUÇÃO. Um registro sem contexto é
  CATÁLOGO: lista e monta schema, recusa executar. Isso é o que permite listar o
  que um domínio sabe fazer sem ter dados em mãos.
- **Não invente palavra de JSON Schema.** `_PALAVRAS_DE_SCHEMA` é lista branca
  medida contra a API. Um `"minimum"` fez a Messages API recusar a requisição
  inteira, e a primeira notícia foi uma avaliação falhando com dinheiro na mesa.
- Ferramenta `WRITE` tem de declarar a compensadora. Hoje são todas
  `READ_ONLY`, e é por isso que este plano não tem rollback.

## Estilo

**Português**, no código e na prosa: `ferramentas`, `conciliacao`, `receita`,
`catalogo`. Commits recentes escrevem o assunto sem acento.

**Comentário registra POR QUÊ, com evidência — nunca O QUÊ.** É a convenção mais
visível do repositório e é deliberada: quase todo comentário aqui traz a
alternativa rejeitada, o defeito que a decisão evita, ou um número medido
("limite=-3 devolveu 197 de 200 lançamentos"). Comentário que parafraseia o
código é ruído; comentário que preserva uma medição é o que impede a próxima
pessoa de refazer o erro. Docstring de módulo costuma contar a história do que
estava errado antes.

**Commits** seguem `tipo(escopo): frase em minúscula`, com corpo explicando o
porquê e a evidência.

## Onde mora o resto do porquê

- `docs/superpowers/specs/` — os designs, por data e tema.
- `docs/superpowers/DECISOES.md` — append-only, cada decisão com a alternativa
  rejeitada e **o custo de estar errada**. Os planos de implementação foram
  apagados depois de executados; isto é o que sobreviveu.
