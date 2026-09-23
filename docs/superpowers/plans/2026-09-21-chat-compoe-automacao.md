# O Chat Compõe a Automação — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O entrevistador passa a propor uma `Composicao` — etapas, agente declarado na hora, tarefa, tripulação, `entrega` e `max_rondas` — em vez de uma `Receita` de um degrau só com nomes prontos do catálogo.

**Architecture:** A ferramenta `propor_workflow` troca `resolvers[]` por `etapas[]`, com o bloco expresso como `tipo` (enum) mais um objeto por tipo — porque `oneOf`/`anyOf` estão fora da lista branca de JSON Schema medida contra a Messages API. O laço do entrevistador não muda: ele continua validando por construção e devolvendo `ValueError` ao modelo como `is_error`, só que agora chamando `construir_composicao`. A borda (WS, gravação, CLI do grill) e a tela passam a falar composição.

**Tech Stack:** Python 3.11+, dataclasses, pytest, FastAPI/WebSocket, React + TypeScript (Vite) no canvas.

**Spec:** `docs/superpowers/specs/2026-09-21-chat-compoe-automacao-design.md`

## Pré-requisito

**A fatia do nó de `tarefa` no canvas precisa estar feita antes da Task 5.** `NoResolver.tsx` hoje tem `DadosDoNo = DadosRegra | DadosAgente | DadosCrew`; a Task 5 pousa blocos de tipo `tarefa`, e sem `DadosTarefa` o `tsc` do CI reprova. As Tasks 1 a 4 não dependem dela.

## Global Constraints

- **Português** no código e na prosa. Commits: `tipo(escopo): frase em minúscula`, assunto sem acento, corpo com o porquê e a evidência.
- **Comentário registra POR QUÊ, com evidência** — alternativa rejeitada, defeito evitado ou número medido.
- **TDD**: nenhum código de produção sem um teste que falhou antes.
- Suíte: `.venv/Scripts/python.exe -m pytest -q`. Lint: `.venv/Scripts/python.exe -m ruff check src tests`. **`ruff format` não roda.**
- Teste que importa `fastapi` precisa de `pytest.importorskip("fastapi")` no topo, antes do import.
- Nenhum teste fala com a rede; modelo só via `FakeLLMClient`.
- **Palavra de JSON Schema só da lista branca**: `{type, description, properties, required, additionalProperties, items, enum}` — mais `minItems`, que os esquemas de hoje já usam em produção. **Nada de `oneOf`/`anyOf`**: a Messages API recusa a requisição inteira por ferramenta malformada, e o erro só aparece gastando dinheiro (precedente: `"minimum": 1`, 2026-09-16).
- Ao final de cada tarefa: suíte verde + `ruff check` limpo.
- Critério do produto: `.venv/Scripts/orchestrator.exe --seed 1 --n 500` diz `85.3%`, zero falso positivo, zero falso negativo.

---

### Task 1: A ferramenta fala etapas

**Files:**
- Modify: `src/orchestrator/grill/ferramentas.py` (`PropostaBruta`, `_catalogo_em_texto`, `esquemas`, `interpretar`)
- Test: `tests/grill/test_ferramentas.py`

**Interfaces:**
- Consumes: `CATALOGO` (regras e agentes), `authoring.composicao.{BlocoRegra, BlocoAgente, BlocoTarefa, BlocoCrew, Etapa}`, `agent.declarado.{AgenteDeclarado, TarefaDeclarada}`.
- Produces: `PropostaBruta(nome: str, justificativa: str, etapas: tuple[Etapa, ...], entrega: tuple[str, ...], max_rondas: int)` — o campo `resolvers` deixa de existir.

- [x] **Step 1: Write the failing tests**

Acrescentar a `tests/grill/test_ferramentas.py`:

```python
def test_a_proposta_aceita_DUAS_etapas_com_blocos_de_tipos_diferentes():
    """A forma que o chat não sabia propor: um degrau que transforma e outro
    que consome o que ele produziu."""
    from orchestrator.agent.llm import ToolCall
    from orchestrator.authoring.composicao import BlocoRegra, BlocoTarefa
    from orchestrator.grill.ferramentas import interpretar

    bruta = interpretar(
        ToolCall(
            id="t",
            name="propor_workflow",
            arguments={
                "nome": "Redação",
                "justificativa": "porque sim",
                "etapas": [
                    {
                        "nome": "escrever",
                        "blocos": [
                            {"tipo": "regra", "regra": {"nome": "filtro", "parametros": {"kind": "issue"}}},
                            {
                                "tipo": "tarefa",
                                "tarefa": {
                                    "name": "escritor",
                                    "system": "escreva",
                                    "kind": "issue",
                                    "produz": "rascunho",
                                    "prompt": "Escreva sobre {titulo}",
                                },
                            },
                        ],
                    },
                    {
                        "nome": "revisar",
                        "blocos": [
                            {
                                "tipo": "agente",
                                "agente": {
                                    "name": "revisor",
                                    "system": "revise",
                                    "kind": "rascunho",
                                    "prompt": "Revise {rascunho}",
                                    "tipos": ["APROVADO", "REPROVADO"],
                                    "abstem_com": "NAO_SEI",
                                },
                            }
                        ],
                    },
                ],
                "entrega": ["rascunho"],
            },
        )
    )

    assert [e.nome for e in bruta.etapas] == ["escrever", "revisar"]
    primeira, segunda = bruta.etapas
    assert isinstance(primeira.blocos[0], BlocoRegra)
    assert isinstance(primeira.blocos[1], BlocoTarefa)
    assert primeira.blocos[1].declaracao.produz == "rascunho"
    assert segunda.blocos[0].declaracao.tipos == ("APROVADO", "REPROVADO")
    assert bruta.entrega == ("rascunho",)


def test_bloco_cujo_tipo_nao_traz_o_objeto_correspondente_e_RECUSADO():
    """A conferência que substitui a união discriminada — que não cabe no
    schema porque `oneOf` está fora da lista branca da Messages API. A recusa
    volta ao modelo como `is_error` e ele corrige no turno seguinte."""
    from orchestrator.agent.llm import ToolCall
    from orchestrator.grill.ferramentas import interpretar

    with pytest.raises(ValueError, match="tarefa"):
        interpretar(
            ToolCall(
                id="t",
                name="propor_workflow",
                arguments={
                    "nome": "x",
                    "justificativa": "y",
                    "etapas": [
                        {
                            "nome": "e1",
                            "blocos": [{"tipo": "tarefa", "agente": {"name": "z"}}],
                        }
                    ],
                },
            )
        )


def test_o_parametro_de_regra_aceita_TEXTO_e_LISTA():
    """`ValorDeParametro` é `int | str | tuple[str, ...]` desde que as regras
    genéricas passaram a receber NOME DE CAMPO. A versão antiga recusava tudo
    que não fosse inteiro, e com isso o modelo não conseguia propor `filtro`,
    `condicao`, `tabela` nem `entrada` — os blocos genéricos inteiros."""
    from orchestrator.agent.llm import ToolCall
    from orchestrator.grill.ferramentas import interpretar

    bruta = interpretar(
        ToolCall(
            id="t",
            name="propor_workflow",
            arguments={
                "nome": "x",
                "justificativa": "y",
                "etapas": [
                    {
                        "nome": "e1",
                        "blocos": [
                            {
                                "tipo": "regra",
                                "regra": {
                                    "nome": "igualdade",
                                    "parametros": {"campos": ["documento", "valor"], "kind": "banco"},
                                },
                            }
                        ],
                    }
                ],
            },
        )
    )

    (bloco,) = bruta.etapas[0].blocos
    assert bloco.parametros == {"campos": ("documento", "valor"), "kind": "banco"}


def test_parametro_BOOLEANO_continua_recusado():
    """`isinstance(True, int)` é True em Python: sem exclusão explícita,
    `max_cents=true` viraria 1."""
    from orchestrator.agent.llm import ToolCall
    from orchestrator.grill.ferramentas import interpretar

    with pytest.raises(ValueError, match="booleano"):
        interpretar(
            ToolCall(
                id="t",
                name="propor_workflow",
                arguments={
                    "nome": "x",
                    "justificativa": "y",
                    "etapas": [
                        {
                            "nome": "e1",
                            "blocos": [
                                {"tipo": "regra", "regra": {"nome": "L2", "parametros": {"max_cents": True}}}
                            ],
                        }
                    ],
                },
            )
        )


def test_o_schema_NAO_usa_palavra_fora_da_lista_branca():
    """A lista branca é medida contra a Messages API (`_PALAVRAS_DE_SCHEMA`).
    `oneOf` derrubaria a requisição INTEIRA, e a primeira notícia seria uma
    entrevista falhando com dinheiro na mesa. `minItems` entra porque os
    esquemas de hoje já o usam em produção."""
    import json

    from orchestrator.agent.tools.registry import _PALAVRAS_DE_SCHEMA
    from orchestrator.grill.ferramentas import esquemas

    permitidas = set(_PALAVRAS_DE_SCHEMA) | {"minItems"}

    def conferir(no, onde):
        if isinstance(no, dict):
            for chave, valor in no.items():
                if onde.endswith(".properties"):
                    conferir(valor, f"{onde}.{chave}")
                    continue
                assert chave in permitidas, f"{onde}.{chave} fora da lista branca"
                conferir(valor, f"{onde}.{chave}")
        elif isinstance(no, list):
            for i, item in enumerate(no):
                conferir(item, f"{onde}[{i}]")

    for e in esquemas():
        conferir(e["input_schema"], e["name"])
    # E continua serializável, que é o que o SDK exige.
    json.dumps(esquemas())
```

Ajustar os testes existentes que falam de `resolvers` (`test_interpretar_proposta`, `test_interpretar_rejeita_parametro_nao_inteiro`, `test_descricao_da_proposta_lista_os_parametros_de_cada_resolver`) para a forma nova — eles medem a MESMA garantia, e reescrevê-los é o preço declarado da mudança de contrato.

- [x] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/grill/test_ferramentas.py -q`
Expected: FAIL — `interpretar` levanta `ValueError: argumento 'resolvers' ausente ou vazio`.

- [x] **Step 3: Reescrever `PropostaBruta` e `interpretar`**

Em `src/orchestrator/grill/ferramentas.py`:

```python
@dataclass(frozen=True)
class PropostaBruta:
    """Ainda não é `Composicao`: falta o id (que vem da CLI ou do WS) e o
    relógio. Os blocos JÁ são os do `authoring`, construídos aqui — e é essa
    construção que recusa declaração inválida ANTES de a composição existir."""

    nome: str
    justificativa: str
    etapas: tuple[Etapa, ...]
    entrega: tuple[str, ...] = ()
    max_rondas: int = 1


def _valor_de_parametro(nome_do_bloco: str, chave: str, v: Any) -> ValorDeParametro:
    """Um parâmetro como `ValorDeParametro`: inteiro, texto ou lista de textos.

    A versão anterior exigia INTEIRO, e isso foi escrito quando o catálogo era
    o cardápio da conciliação (folga em centavos, dias). As regras genéricas
    recebem NOME DE CAMPO — `campos`, `kind`, `teste` —, então a exigência
    antiga impedia o modelo de propor `filtro`, `condicao`, `tabela` e
    `entrada`: os blocos que fazem a plataforma ser geral.
    """
    # `isinstance(True, int)` é True em Python: sem esta linha, `max_cents=true`
    # viraria 1 em silêncio.
    if isinstance(v, bool):
        raise ValueError(
            f"parâmetro {chave!r} de {nome_do_bloco!r} veio booleano ({v!r}); "
            f"use inteiro, texto ou lista de textos"
        )
    if isinstance(v, int) or isinstance(v, str):
        return v
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        return tuple(v)
    raise ValueError(
        f"parâmetro {chave!r} de {nome_do_bloco!r} precisa ser inteiro, texto "
        f"ou lista de textos, veio {v!r}"
    )


def _objeto(bloco: dict[str, Any], chave: str) -> dict[str, Any]:
    """O objeto que o `tipo` promete. A conferência que a união discriminada
    faria no schema, e que aqui precisa ser código: `oneOf` está fora da lista
    branca de JSON Schema, e usá-lo derrubaria a requisição inteira."""
    valor = bloco.get(chave)
    if not isinstance(valor, dict):
        raise ValueError(
            f"bloco de tipo {chave!r} sem o objeto {chave!r}: mande "
            f"{{\"tipo\": {chave!r}, {chave!r}: {{...}}}}"
        )
    return valor


def _agente_de(d: dict[str, Any]) -> AgenteDeclarado:
    return AgenteDeclarado(
        name=_texto(d, "name"),
        system=_texto(d, "system"),
        kind=_texto(d, "kind"),
        prompt=_texto(d, "prompt"),
        tipos=tuple(d.get("tipos") or ()),
        abstem_com=_texto(d, "abstem_com"),
        ferramentas=tuple(d.get("ferramentas") or ()),
    )


def _tarefa_de(d: dict[str, Any]) -> TarefaDeclarada:
    return TarefaDeclarada(
        name=_texto(d, "name"),
        system=_texto(d, "system"),
        kind=_texto(d, "kind"),
        produz=_texto(d, "produz"),
        prompt=_texto(d, "prompt"),
        ferramentas=tuple(d.get("ferramentas") or ()),
    )


def _bloco_de(bloco: Any) -> Bloco:
    if not isinstance(bloco, dict):
        raise ValueError(f"bloco malformado: {bloco!r}")
    tipo = bloco.get("tipo")
    if tipo == "regra":
        r = _objeto(bloco, "regra")
        nome = _texto(r, "nome")
        params = r.get("parametros") or {}
        if not isinstance(params, dict):
            raise ValueError(f"'parametros' de {nome!r} não é objeto")
        return BlocoRegra(
            nome=nome,
            parametros={k: _valor_de_parametro(nome, k, v) for k, v in params.items()},
        )
    if tipo == "agente":
        return BlocoAgente(declaracao=_agente_de(_objeto(bloco, "agente")))
    if tipo == "tarefa":
        return BlocoTarefa(declaracao=_tarefa_de(_objeto(bloco, "tarefa")))
    if tipo == "crew":
        c = _objeto(bloco, "crew")
        agentes = c.get("agentes")
        if not isinstance(agentes, list) or not agentes:
            raise ValueError("tripulação sem agentes")
        return BlocoCrew(
            nome=_texto(c, "nome"),
            agentes=tuple(_agente_de(a) for a in agentes),
            process=c.get("process") or "sequential",
            conflito=c.get("conflito") or "abster",
        )
    raise ValueError(
        f"tipo de bloco desconhecido: {tipo!r}. use 'regra', 'agente', "
        f"'tarefa' ou 'crew'"
    )
```

e o ramo de `propor_workflow` em `interpretar`:

```python
    if chamada.name == "propor_workflow":
        etapas_cruas = args.get("etapas")
        if not isinstance(etapas_cruas, list) or not etapas_cruas:
            raise ValueError("argumento 'etapas' ausente ou vazio")
        etapas = []
        for e in etapas_cruas:
            if not isinstance(e, dict):
                raise ValueError(f"etapa malformada: {e!r}")
            blocos = e.get("blocos")
            if not isinstance(blocos, list) or not blocos:
                raise ValueError(f"etapa {e.get('nome')!r} sem bloco")
            # `Etapa.__post_init__` recusa etapa sem nome e sem bloco, com o
            # texto de lá. Construir aqui é o que faz a recusa chegar ao modelo
            # em vez de esperar a composição.
            etapas.append(Etapa(nome=_texto(e, "nome"), blocos=tuple(_bloco_de(b) for b in blocos)))
        entrega = args.get("entrega") or []
        if not isinstance(entrega, list) or not all(isinstance(x, str) for x in entrega):
            raise ValueError("'entrega' precisa ser uma lista de kinds")
        rondas = args.get("max_rondas", 1)
        if isinstance(rondas, bool) or not isinstance(rondas, int):
            raise ValueError(f"'max_rondas' precisa ser inteiro, veio {rondas!r}")
        return PropostaBruta(
            nome=_texto(args, "nome"),
            justificativa=_texto(args, "justificativa"),
            etapas=tuple(etapas),
            entrega=tuple(entrega),
            max_rondas=rondas,
        )
```

Imports novos no topo: `from orchestrator.agent.declarado import AgenteDeclarado, TarefaDeclarada, ValorDeParametro` e `from orchestrator.authoring.composicao import Bloco, BlocoAgente, BlocoCrew, BlocoRegra, BlocoTarefa, Etapa`. `ResolverReceita` sai dos imports.

- [x] **Step 4: Reescrever `esquemas()`**

Substituir o schema de `propor_workflow` por:

```python
_DECL_AGENTE = {
    "type": "object",
    "description": "um agente que JULGA o item e propõe um tipo. Nunca resolve.",
    "properties": {
        "name": {"type": "string"},
        "system": {"type": "string", "description": "o papel, em uma ou duas frases"},
        "kind": {"type": "string", "description": "o kind de item que ele lê"},
        "prompt": {
            "type": "string",
            "description": (
                "template sobre os CAMPOS do item, ex.: 'Classifique: {titulo}'. "
                "Só cite campo que o parceiro disse existir — campo inventado "
                "não falha aqui, falha na execução, com a conta paga."
            ),
        },
        "tipos": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": "o vocabulário fechado de saída",
        },
        "abstem_com": {
            "type": "string",
            "description": "o rótulo de 'não sei'. NUNCA um dos `tipos`",
        },
        "ferramentas": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name", "system", "kind", "prompt", "tipos", "abstem_com"],
}

_DECL_TAREFA = {
    "type": "object",
    "description": (
        "um agente que TRANSFORMA: consome um kind e produz outro, e o texto "
        "dele vira o item do degrau seguinte."
    ),
    "properties": {
        "name": {"type": "string"},
        "system": {"type": "string"},
        "kind": {"type": "string", "description": "o kind que ele consome"},
        "produz": {
            "type": "string",
            "description": (
                "o kind que ele produz, diferente de `kind`. O degrau seguinte "
                "lê o texto no campo com ESTE nome: produz 'rascunho' → o "
                "próximo interpola '{rascunho}'"
            ),
        },
        "prompt": {"type": "string", "description": "template sobre os campos do item"},
        "ferramentas": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name", "system", "kind", "produz", "prompt"],
}

_BLOCO = {
    "type": "object",
    "description": (
        "UM bloco. `tipo` manda, e você preenche o objeto com o mesmo nome: "
        "tipo 'regra' → objeto `regra`; tipo 'agente' → objeto `agente`; e "
        "assim por diante. Os outros ficam de fora."
    ),
    "properties": {
        "tipo": {"type": "string", "enum": ["regra", "agente", "tarefa", "crew"]},
        "regra": {
            "type": "object",
            "properties": {
                "nome": {"type": "string", "enum": _nomes_de_regra()},
                "parametros": {"type": "object"},
            },
            "required": ["nome"],
        },
        "agente": _DECL_AGENTE,
        "tarefa": _DECL_TAREFA,
        "crew": {
            "type": "object",
            "description": "vários agentes sobre o MESMO item, com política de conflito",
            "properties": {
                "nome": {"type": "string"},
                "agentes": {"type": "array", "items": _DECL_AGENTE, "minItems": 2},
                "process": {"type": "string", "enum": ["sequential", "hierarchical"]},
                "conflito": {"type": "string", "enum": ["abster", "maioria", "sintetizar"]},
            },
            "required": ["nome", "agentes"],
        },
    },
    "required": ["tipo"],
}
```

e o schema da ferramenta:

```python
        {
            "name": "propor_workflow",
            "description": (
                "Encerra a entrevista propondo a automação. Regras disponíveis "
                "para blocos de tipo 'regra':\n"
                + _catalogo_em_texto()
                + "\n\nAgente e tarefa NÃO saem de lista: você os declara. "
                "Omita um parâmetro de regra para usar o default. Não repita "
                "um bloco na mesma automação."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "nome": {"type": "string", "description": "rótulo legível"},
                    "justificativa": {
                        "type": "string",
                        "description": "por que esta automação resolve o caso descrito",
                    },
                    "etapas": {
                        "type": "array",
                        "minItems": 1,
                        "description": (
                            "os degraus, em ordem. Dentro de um degrau a ordem é "
                            "por CUSTO (o motor ordena: regra, depois agente, "
                            "depois humano); ENTRE degraus é por DADO — o "
                            "degrau seguinte só vê o que o anterior produziu."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "nome": {"type": "string"},
                                "blocos": {"type": "array", "minItems": 1, "items": _BLOCO},
                            },
                            "required": ["nome", "blocos"],
                        },
                    },
                    "entrega": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "os kinds que SÃO a saída: o que ninguém consome de "
                            "propósito. Sem isso, um kind produzido e não "
                            "consumido é recusado como beco sem saída."
                        ),
                    },
                    "max_rondas": {
                        "type": "integer",
                        "description": (
                            "quantas vezes a sequência pode rodar. 1 é uma "
                            "passada; mais de 1 só para aresta de volta (o "
                            "revisor reprova e o rascunho volta ao escritor)."
                        ),
                    },
                },
                "required": ["nome", "justificativa", "etapas"],
            },
        },
```

`_nomes_disponiveis` vira `_nomes_de_regra` — só as regras, porque agente deixou de ser escolhido de lista:

```python
def _nomes_de_regra() -> list[str]:
    """Os nomes que o modelo pode escolher para um bloco de REGRA.

    Os agentes saíram: eles deixaram de ser escolhidos de um cardápio e passaram
    a ser declarados. Os três prontos do catálogo continuam existindo para quem
    monta pela tela; o chat, que agora sabe declarar, não precisa deles.
    """
    return sorted(r.nome for r in CATALOGO.regras)
```

E `_catalogo_em_texto` perde a mentira do `int`:

```python
    for r in CATALOGO.regras:
        if r.parametros:
            params = "; ".join(
                f"{p.nome} (default {p.default!r}) — {p.descricao}" for p in r.parametros
            )
        else:
            params = "sem parâmetros"
```

O laço `for a in CATALOGO.agentes` sai de `_catalogo_em_texto`: agente não é mais item de cardápio.

- [x] **Step 5: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/grill/test_ferramentas.py -q`
Expected: PASS.

- [x] **Step 6: Commit**

```bash
.venv/Scripts/python.exe -m ruff check src tests
git add src/orchestrator/grill/ferramentas.py tests/grill/test_ferramentas.py
git commit -m "feat(grill): a ferramenta da entrevista fala etapas e blocos"
```

Corpo: por que o bloco não é união discriminada (a lista branca medida), e por que o parâmetro deixou de exigir inteiro (os blocos genéricos recebem nome de campo).

---

### Task 2: O entrevistador produz `Composicao`

**Files:**
- Modify: `src/orchestrator/grill/entrevistador.py` (`Proposta`, `_receita` → `_composicao`, a validação)
- Modify: `src/orchestrator/grill/prompt.py`
- Test: `tests/grill/test_entrevistador.py`, `tests/grill/test_prompt.py`

**Interfaces:**
- Consumes: `PropostaBruta` da Task 1.
- Produces: `Proposta(composicao: Composicao, cost: Cost, transcricao: tuple[str, ...])` — o campo `receita` deixa de existir.

- [x] **Step 1: Write the failing tests**

Em `tests/grill/test_entrevistador.py` (usar os helpers de cliente falso que o arquivo já tem; se ele monta `ToolCall` de proposta, atualizar aqueles para a forma nova):

```python
def test_a_entrevista_propoe_uma_COMPOSICAO_de_duas_etapas():
    """O desfecho que o chat não alcançava: dois degraus ligados por kind."""
    from orchestrator.authoring.composicao import Composicao

    cliente = _cliente_que_propoe(
        {
            "nome": "Triagem",
            "justificativa": "regra barata antes do modelo",
            "etapas": [
                {
                    "nome": "escrever",
                    "blocos": [
                        {
                            "tipo": "tarefa",
                            "tarefa": {
                                "name": "escritor",
                                "system": "escreva",
                                "kind": "issue",
                                "produz": "rascunho",
                                "prompt": "Escreva sobre {titulo}",
                            },
                        }
                    ],
                },
                {
                    "nome": "revisar",
                    "blocos": [
                        {
                            "tipo": "agente",
                            "agente": {
                                "name": "revisor",
                                "system": "revise",
                                "kind": "rascunho",
                                "prompt": "Revise {rascunho}",
                                "tipos": ["APROVADO", "REPROVADO"],
                                "abstem_com": "NAO_SEI",
                            },
                        }
                    ],
                },
            ],
            "entrega": ["rascunho"],
        }
    )

    resultado = Entrevistador(client=cliente).entrevistar(
        "triagem", "classifique minhas issues", responder=lambda _: "sim"
    )

    assert isinstance(resultado, Proposta)
    assert isinstance(resultado.composicao, Composicao)
    assert [e.nome for e in resultado.composicao.etapas] == ["escrever", "revisar"]


def test_proposta_INVALIDA_volta_ao_modelo_em_vez_de_derrubar_a_entrevista():
    """VALIDAR É CONSTRUIR, e o erro é do DOMÍNIO — texto escrito para ser
    lido. Um prompt que não interpola campo nenhum faria todo item receber o
    mesmo texto; `AgenteDeclarado` recusa, e a recusa precisa chegar ao modelo
    como `is_error` para ele corrigir no turno seguinte."""
    cliente = _cliente_que_propoe_e_depois_corrige(
        invalida={
            "nome": "x",
            "justificativa": "y",
            "etapas": [
                {
                    "nome": "e1",
                    "blocos": [
                        {
                            "tipo": "agente",
                            "agente": {
                                "name": "cego",
                                "system": "s",
                                "kind": "issue",
                                "prompt": "classifique isto",
                                "tipos": ["A"],
                                "abstem_com": "NAO_SEI",
                            },
                        }
                    ],
                }
            ],
        },
        valida={
            "nome": "x",
            "justificativa": "y",
            "etapas": [
                {
                    "nome": "e1",
                    "blocos": [
                        {
                            "tipo": "agente",
                            "agente": {
                                "name": "cego",
                                "system": "s",
                                "kind": "issue",
                                "prompt": "classifique {titulo}",
                                "tipos": ["A"],
                                "abstem_com": "NAO_SEI",
                            },
                        }
                    ],
                }
            ],
        },
    )

    resultado = Entrevistador(client=cliente).entrevistar(
        "w", "desc", responder=lambda _: "sim"
    )

    assert isinstance(resultado, Proposta)
    # O erro do domínio chegou ao modelo, verbatim.
    erro = cliente.chamadas[-1]["messages"][-1]["content"][0]["content"]
    assert "interpola" in erro
```

Os dois helpers (`_cliente_que_propoe`, `_cliente_que_propoe_e_depois_corrige`) montam um `FakeLLMClient` cujas respostas trazem `ToolCall(name="propor_workflow", arguments=...)`; se o arquivo já tiver um equivalente para a forma antiga, adaptá-lo em vez de criar um segundo.

Em `tests/grill/test_prompt.py`:

```python
def test_o_prompt_NAO_promete_um_degrau_so():
    """A frase "A cascata tem um estágio" era verdade quando o entrevistador
    produzia `Receita`. Com etapas, ela passa a ensinar o modelo a não usar o
    que existe."""
    assert "um estágio" not in SYSTEM


def test_o_prompt_manda_PERGUNTAR_os_campos_do_item():
    """Campo inventado não falha na composição — falha na execução, com a conta
    paga. É a mesma disciplina que o prompt já impõe a parâmetro ("NUNCA invente
    um valor que não ouviu"), estendida a campo."""
    assert "campos" in SYSTEM.lower()
```

- [x] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/grill -q`
Expected: FAIL — `Proposta` não tem `composicao`; `SYSTEM` ainda contém "um estágio".

- [x] **Step 3: Implementar no entrevistador**

```python
@dataclass(frozen=True)
class Proposta:
    composicao: Composicao
    cost: Cost
    transcricao: tuple[str, ...]
```

O ramo da proposta:

```python
                    composicao = self._composicao(workflow_id, interpretada)
                    try:
                        # VALIDAR É CONSTRUIR. Se constrói, roda.
                        construir_composicao(composicao)
                    except ValueError as e:
                        mensagens.append(
                            self._mensagem_resultado(
                                resposta.tool_calls, self._bloco_erro(chamada.id, str(e))
                            )
                        )
                        tentativas += 1
                    else:
                        return Proposta(
                            composicao=composicao, cost=total, transcricao=tuple(transcricao)
                        )
```

e o construtor:

```python
    @staticmethod
    def _composicao(workflow_id: str, bruta: PropostaBruta) -> Composicao:
        return Composicao(
            id=workflow_id,
            nome=bruta.nome,
            justificativa=bruta.justificativa,
            gerado_em=datetime.now(UTC),
            etapas=bruta.etapas,
            entrega=bruta.entrega,
            max_rondas=bruta.max_rondas,
        )
```

Imports: `from orchestrator.authoring.composicao import Composicao, construir_composicao`; `receita.construir` e `Receita` saem, `validar_id` fica (o id continua sendo validado pela MESMA função que o disco usa).

- [x] **Step 4: Reescrever o system prompt**

Em `src/orchestrator/grill/prompt.py`, trocar a linha da cascata de um estágio por:

```
- A automação tem ETAPAS, em ordem. Dentro de uma etapa a ordem é por CUSTO e
  quem ordena é o motor — regra, depois agente, depois humano; não tente
  contorná-la. ENTRE etapas a ordem é por DADO: a etapa seguinte só enxerga o
  que a anterior produziu.
- Agente e tarefa você DECLARA, não escolhe de lista: nome, papel, kind,
  prompt e vocabulário são seus.
- ANTES de declarar um agente ou uma tarefa, PERGUNTE quais campos cada item
  tem, e interpole só esses no prompt. Campo inventado não falha na composição:
  falha na execução, depois de a conta ser paga.
- Um kind produzido e não consumido é recusado como beco sem saída. Se a saída
  de uma etapa é o fim do trabalho, declare esse kind em `entrega`.
```

- [x] **Step 5: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/grill -q`
Expected: PASS.

- [x] **Step 6: Commit**

```bash
.venv/Scripts/python.exe -m ruff check src tests
git add src/orchestrator/grill tests/grill
git commit -m "feat(grill): a entrevista propoe composicao, nao receita"
```

---

### Task 3: A borda — WebSocket e gravação

**Files:**
- Modify: `src/orchestrator/api/entrevista.py` (payload de `proposta`)
- Modify: `src/orchestrator/api/app.py` (`_gravar_receita_do_chat` → `_gravar_composicao_do_chat`)
- Test: `tests/api/test_entrevista.py`

**Interfaces:**
- Consumes: `Proposta.composicao` (Task 2).
- Produces: mensagem WS `{"tipo": "proposta", "composicao": {...}, "custo_usd": float, "transcricao": [...]}`.

- [x] **Step 1: Write the failing test**

Em `tests/api/test_entrevista.py`:

O helper `_propor` do arquivo monta `{"nome", "justificativa", "resolvers"}`. Ele passa a montar etapas:

```python
def _propor(etapas, entrega=()):
    return _resposta(
        "propor_workflow",
        {
            "nome": "Do chat",
            "justificativa": "porque o parceiro descreveu assim",
            "etapas": etapas,
            "entrega": list(entrega),
        },
    )


_ESCRITOR = {
    "tipo": "tarefa",
    "tarefa": {
        "name": "escritor",
        "system": "escreva",
        "kind": "issue",
        "produz": "rascunho",
        "prompt": "Escreva sobre {titulo}",
    },
}

_REVISOR = {
    "tipo": "agente",
    "agente": {
        "name": "revisor",
        "system": "revise",
        "kind": "rascunho",
        "prompt": "Revise {rascunho}",
        "tipos": ["APROVADO", "REPROVADO"],
        "abstem_com": "NAO_SEI",
    },
}
```

E os dois testes novos, na forma que `test_o_chat_PROPOE_uma_cascata_e_ela_vira_workflow` já usa:

```python
def test_a_mensagem_de_proposta_carrega_a_COMPOSICAO(com_entrevistador):
    """A tela precisa das ETAPAS para pousar por etapa. `receita` no payload
    deixaria o canvas empilhando tudo no primeiro degrau."""
    raiz = com_entrevistador(
        [
            _propor(
                [
                    {"nome": "escrever", "blocos": [_ESCRITOR]},
                    {"nome": "revisar", "blocos": [_REVISOR]},
                ],
                entrega=["rascunho"],
            )
        ]
    )

    with cliente.websocket_connect("/api/entrevista") as ws:
        ws.send_json({"workflow_id": "do-chat", "descricao": "triar minhas issues"})
        msg = ws.receive_json()

    assert msg["tipo"] == "proposta", msg
    assert [e["nome"] for e in msg["composicao"]["etapas"]] == ["escrever", "revisar"]
    # O formato ANTIGO não sobrevive ao lado do novo: dois campos para a mesma
    # proposta é o join frágil de sempre, e qual deles a tela lê viraria
    # escolha dela.
    assert "receita" not in msg
    assert (raiz / "composicoes" / "do-chat.json").exists()


def test_o_chat_RECUSA_id_que_ja_existe_no_registry(com_entrevistador):
    """A terceira porta de escrita, com a mesma tranca das outras duas: o id é
    um espaço só para embutido, receita e composição. Sem esta recusa, o chat
    gravava por cima e o workflow antigo sumia no pulo-com-aviso de
    `registry()` — um `stderr` do servidor, invisível para quem usa a tela."""
    from orchestrator.agent.declarado import TarefaDeclarada
    from orchestrator.authoring.composicao import (
        BlocoTarefa,
        Composicao,
        Etapa,
        agora,
        gravar,
    )

    raiz = com_entrevistador(
        [_propor([{"nome": "escrever", "blocos": [_ESCRITOR]}], entrega=["rascunho"])]
    )
    gravar(
        Composicao(
            id="do-chat",
            nome="ja existia",
            gerado_em=agora(),
            etapas=(
                Etapa(
                    nome="e1",
                    blocos=(
                        BlocoTarefa(
                            declaracao=TarefaDeclarada(
                                name="t",
                                system="s",
                                kind="issue",
                                produz="rascunho",
                                prompt="{titulo}",
                            )
                        ),
                    ),
                ),
            ),
            entrega=("rascunho",),
        ),
        raiz / "composicoes",
    )

    with cliente.websocket_connect("/api/entrevista") as ws:
        ws.send_json({"workflow_id": "do-chat", "descricao": "triar minhas issues"})
        msg = ws.receive_json()

    assert msg["tipo"] == "recusa", msg
    assert "já existe" in msg["motivo"]
```

A fixture `com_entrevistador` já isola a raiz e devolve o `tmp_path` usado. Se ela ainda apontar só para `workflows/`, estendê-la para servir às duas pastas — é uma linha, e sem ela o primeiro `assert` de arquivo falha por caminho, não por comportamento.

- [x] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_entrevista.py -q`
Expected: FAIL — a mensagem ainda traz `receita`.

- [x] **Step 3: Implementar**

Em `api/entrevista.py`:

```python
                await ws.send_json(
                    {
                        "tipo": "proposta",
                        "composicao": para_json(carga.composicao),
                        "custo_usd": _usd(carga.cost, modelo),
                        "transcricao": list(carga.transcricao),
                    }
                )
```

com `from orchestrator.authoring.composicao import para_json` no lugar do `para_json` de `receita` (o `validar_id` continua vindo de `grill.receita`, que é onde ele mora).

Em `api/app.py`:

```python
def _gravar_composicao_do_chat(composicao: Composicao) -> None:
    """A TERCEIRA porta de escrita, com a mesma tranca das outras duas.

    `gravar` só sabe se o ARQUIVO existe — não consulta o `registry()`. Sem
    esta checagem, o chat gravava com o id de outro workflow e o antigo sumia
    no pulo-com-aviso de `registry()`: um `stderr` do servidor, invisível para
    quem usa a tela.
    """
    if composicao.id in registry(_RAIZ_RECEITAS, _RAIZ_COMPOSICOES):
        raise ValueError(f"já existe um workflow com id {composicao.id!r}; escolha outro")
    gravar(composicao, _RAIZ_COMPOSICOES)
```

e `conduzir(ws, gravar=_gravar_composicao_do_chat)`.

- [x] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
.venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m ruff check src tests
git add src/orchestrator/api tests/api/test_entrevista.py
git commit -m "feat(api): o chat entrega composicao pelo websocket"
```

---

### Task 4: O `grill` CLI grava composição

**Files:**
- Modify: `src/orchestrator/grill/cli.py`
- Test: `tests/grill/test_cli.py`

**Interfaces:**
- Consumes: `Proposta.composicao` (Task 2).
- Produces: nenhum símbolo novo; o CLI passa a escrever em `data/composicoes/`.

- [x] **Step 1: Write the failing test**

O helper `_propor()` do arquivo monta a forma antiga. Ele passa a montar etapas:

```python
def _propor() -> LLMResponse:
    return _chamada(
        "propor_workflow",
        nome="Triagem",
        justificativa="uma regra barata antes de qualquer modelo",
        etapas=[{"nome": "casar", "blocos": [{"tipo": "regra", "regra": {"nome": "L1"}}]}],
    )
```

E o teste:

```python
def test_a_cli_grava_COMPOSICAO(capsys, tmp_path):
    """Um entrevistador com duas SAÍDAS seria o join frágil de sempre. A
    `Receita` continua carregando do disco por `_de_receita`; o que muda é que
    quem PRODUZ passa a produzir um formato só."""
    from orchestrator.authoring.composicao import ler

    ent = Entrevistador(client=FakeLLMClient([_chamada("perguntar", texto="p?"), _propor()]))

    codigo = _rodar(["--id", "triagem", "--descricao", "conciliamos NF"], ["r"], ent)

    assert codigo == 0
    assert ler("triagem", tmp_path / "composicoes").nome == "Triagem"
    # E NÃO grava no formato antigo: dois arquivos para a mesma entrevista
    # fariam `registry()` ver dois workflows com o mesmo id, e o segundo sumir
    # com um aviso em `stderr`.
    assert not (tmp_path / "workflows" / "triagem.json").exists()
```

Os outros testes do arquivo que afirmam `(tmp_path / "workflows" / "<id>.json").exists()` passam a afirmar `composicoes` — medem a mesma garantia, e atualizá-los é o preço declarado da mudança de saída.

- [x] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/grill/test_cli.py -q`
Expected: FAIL — o arquivo foi para `data/receitas/`.

- [x] **Step 3: Implementar**

Trocar `caminho_da_receita`/`gravar_receita` por `caminho`/`gravar` de `authoring.composicao`, `construir` por `construir_composicao` em `_medir`, e `resultado.receita` por `resultado.composicao` nas três linhas que imprimem o desfecho.

- [x] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/grill -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/orchestrator/grill/cli.py tests/grill/test_cli.py
git commit -m "feat(grill): a cli grava composicao — uma saida so"
```

---

### Task 5: A tela pousa por etapa

**Files:**
- Modify: `web-app/src/api.ts` (tipo `ComposicaoProposta`)
- Modify: `web-app/src/Chat.tsx` (payload e resumo)
- Modify: `web-app/src/App.tsx` (`aceitarProposta`)
- Modify: `web/` (bundle commitado)

**Interfaces:**
- Consumes: a mensagem WS da Task 3.
- Produces: nós no canvas com `etapa` correta e `tipo` em `{regra, agente, tarefa, crew}`.

**Pré-requisito:** `DadosTarefa` precisa existir em `NoResolver.tsx` (a fatia do nó de tarefa no canvas). Sem ela o `tsc` reprova.

- [x] **Step 1: Tipo novo em `api.ts`**

```ts
// O que o chat propõe hoje. `Receita` continua existindo para os arquivos em
// disco; o que mudou é o que o ENTREVISTADOR produz.
export interface ComposicaoProposta {
  id: string;
  nome: string;
  justificativa: string;
  etapas: { nome: string; blocos: BlocoPedido[] }[];
  entrega: string[];
  max_rondas: number;
}
```

`BlocoPedido` ganha o caso da tarefa:

```ts
  | { tipo: "tarefa"; declaracao: TarefaDeclarada }
```

com

```ts
// Uma TAREFA como dado. Sem `tipos` e sem `abstem_com`: transformar não tem
// vocabulário de julgamento a rotular.
export interface TarefaDeclarada {
  name: string;
  system: string;
  kind: string;
  produz: string;
  prompt: string;
  ferramentas: string[];
  max_turns: number;
  budget_microcents: number;
}
```

- [x] **Step 2: `Chat.tsx` fala composição**

`Props.aoPropor` passa a receber `ComposicaoProposta`; o `case "proposta"` lê `m.composicao`, e o resumo passa a ser por etapa:

```ts
          dizer(
            "entrevistador",
            `Proponho: ${m.composicao.etapas
              .map((e: { nome: string; blocos: { tipo: string }[] }) =>
                `${e.nome} (${e.blocos.length})`)
              .join(" → ")}. ${m.composicao.justificativa}`,
          );
```

- [x] **Step 3: `aceitarProposta` pousa por etapa**

```ts
  const aceitarProposta = (composicao: ComposicaoProposta) => {
    if (!catalogo) {
      setAviso("o catálogo ainda não carregou; a proposta do chat não pôde pousar");
      return;
    }
    const novos: NoDoCanvas[] = [];
    const naoColocados: string[] = [];
    composicao.etapas.forEach((etapa, indice) => {
      for (const bloco of etapa.blocos) {
        let dados: DadosDoNo | null = null;
        if (bloco.tipo === "regra") {
          const regra = catalogo.regras.find((x) => x.nome === bloco.nome);
          // O `push` do não-colocado mora AQUI DENTRO, e não num `if (!dados)`
          // lá embaixo: só regra pode não pousar — o nome dela vem do catálogo,
          // e um nome que não está lá é o chat propondo o que a tela não tem.
          // Agente, tarefa e crew são DECLARADOS, não há o que procurar. Fora
          // deste ramo `bloco.nome` nem existe no tipo, e o `tsc` recusa.
          if (!regra) naoColocados.push(bloco.nome);
          if (regra) {
            const parametros: Record<string, ValorParametro> = {};
            for (const p of regra.parametros) parametros[p.nome] = p.default;
            dados = {
              tipo: "regra",
              regra,
              parametros: { ...parametros, ...bloco.parametros },
              etapa: indice,
            };
          }
        } else if (bloco.tipo === "agente") {
          dados = { tipo: "agente", declaracao: { ...bloco.declaracao }, etapa: indice };
        } else if (bloco.tipo === "tarefa") {
          dados = { tipo: "tarefa", declaracao: { ...bloco.declaracao }, etapa: indice };
        } else {
          dados = {
            tipo: "crew",
            nome: bloco.nome,
            agentes: bloco.agentes.map((a) => ({ ...a })),
            process: bloco.process,
            conflito: bloco.conflito,
            etapa: indice,
          };
        }
        if (!dados) continue;
        novos.push({
          id: `n${proximoId.current++}`,
          type: "resolver",
          position: { x: 0, y: 0 },
          data: dados,
        });
      }
    });
    setNos(novos);
    setAviso(
      naoColocados.length
        ? `o chat propôs ${naoColocados.join(", ")}, que o canvas não sabe ` +
          `desenhar: não há bloco com esse nome no catálogo`
        : null,
    );
    invalidar();
  };
```

- [x] **Step 4: Typecheck, build, bundle**

```bash
npx --prefix web-app tsc --noEmit -p web-app/tsconfig.json
npm --prefix web-app run build
git diff --stat web
```
Expected: `tsc` exit 0; o diff de `web/` traz os assets novos.

- [x] **Step 5: Ver funcionando**

Subir o preview (`preview_start`), abrir o canvas, e conferir que uma proposta de duas etapas pousa em DUAS colunas. Sem chave configurada o chat recusa com motivo — nesse caso, exercitar `aceitarProposta` pelo console com um objeto de composição é prova suficiente para esta fatia.

- [x] **Step 6: Commit**

```bash
git add web-app/src web
git commit -m "feat(canvas): a proposta do chat pousa por etapa"
```

---

## Fora deste plano, de propósito

- **Sugerir 2 ou 3 automações para comparar por custo.** A entrevista propõe UMA; alternativas lado a lado é outro produto.
- **Ler os campos do item de uma fonte conectada.** Decidido: o chat pergunta.
- **Decisão humana genérica.** Continua sendo o degrau HUMANO que não existe.

---

## Executado em 2026-09-21 — e o que o plano errou

Commits: `a8df032` (Tasks 1–4, juntas) e `42d3511` (Task 5).

**A fronteira da Task 1 estava errada.** O plano exigia suíte verde ao fim de
cada tarefa, e a Task 1 muda um CONTRATO: assim que a ferramenta passou a falar
etapas, os três consumidores — entrevistador, CLI e WebSocket — ficaram
vermelhos por construção (23 testes). Não há como fatiar isso em commits verdes
sem duplicar o formato por um tempo, que é a coisa que este repositório recusa.
As Tasks 1–4 viraram um commit só.

**Renomear `_nomes_disponiveis` foi erro meu.** `receita.construir` a importa
para dizer o que HÁ quando uma receita cita um resolver inexistente, e `Receita`
compõe por nome — agente inclusive. As duas funções ficaram, com a diferença
escrita no docstring. Descoberto quebrando quatro testes de receita.

**O orçamento da entrevista dobrou, e isso é do desenho.** O schema saiu de
2430 para 10485 chars porque agora carrega as declarações inteiras; o turno
passou de 981.000 para 2.082.000 µ¢. `ORCAMENTO_PADRAO` foi para 40.000.000
(US$ 0,40 de teto por entrevista de até 12 turnos). Quem cobrou a reconta foi
`test_orcamento_padrao_cobre_uma_entrevista_realista`, que existe exatamente
para isso.

**O que não foi verificado:** a chegada da proposta na TELA. O servidor local
não tem `ANTHROPIC_API_KEY` e o chat recusa começar sem ela — corretamente. A
prova de ponta a ponta exige uma entrevista real contra o modelo.
