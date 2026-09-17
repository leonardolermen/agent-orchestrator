# Quadro em branco — Plano de implementação (B1–B6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remover o conceito de DOMÍNIO da autoria, substituindo os dois catálogos de hoje por um só, plano, do qual tanto a tela quanto o chat compõem.

**Architecture:** `domains/registro.py` deixa de exportar `DOMINIOS: dict[str, Dominio]` e passa a exportar um `Catalogo` plano — ferramentas, regras e agentes, todos juntos, sem `kinds` e sem agrupamento. As duas guardas que viviam em `Dominio.__post_init__` (nome único entre blocos; validar construindo) migram para ele. O que substitui o `kinds` já existe: `Stage.consome`/`produz` e a recusa de beco sem saída, entregues na fatia do grafo.

**Tech Stack:** Python 3.13, dataclasses congelados, pytest, ruff. React 18 + Vite + Tailwind no front. Zero dependências novas.

**Spec:** `docs/superpowers/specs/2026-09-17-quadro-em-branco-design.md`

## Global Constraints

- **Ordem segura: nada é removido antes de o substituto existir e ter consumidor.** O `Catalogo` nasce AO LADO de `DOMINIOS` na Task 1; `Dominio` só morre na Task 5, quando ninguém mais o usa. Nenhuma task deixa o repositório sem tela ou sem chat.
- **Os workflows de exemplo NÃO são tocados.** `domains/procurement/workflow.py`, `domains/swe/`, `domains/redacao/` e a conciliação continuam existindo e rodando. `tests/domains/test_generalidade.py` e `tests/domains/test_redacao.py` não mudam uma linha — se mudarem, alguém leu "tirar domínio" como "apagar `domains/`".
- Layering: `tests/arquitetura/test_camadas.py` impõe a tabela. NINGUÉM importa `domains` — `registro.py` está DENTRO de `domains` e essa é a razão de o catálogo continuar morando lá.
- Código, comentários e docstrings em **português**, seguindo o repositório. Docstring explica POR QUE, não O QUE.
- Configuração inválida falha alto, na importação — nunca vira fallback silencioso.
- Nenhum teste chama API paga. `FakeLLMClient`/`ClienteDeValidacao` são as costuras.
- Rodar a suíte: `./.venv/Scripts/python.exe -m pytest -q`. Lint: `./.venv/Scripts/python.exe -m ruff check src tests`.
- Front: `npm --prefix web-app run build` antes de commitar mudança de tela; `npx tsc --noEmit` precisa passar (o CI roda os dois, e exige `git diff` vazio sobre `web/`).

## Estrutura de arquivos

| Arquivo | Responsabilidade | Tasks |
|---|---|---|
| `src/orchestrator/domains/registro.py` | o `Catalogo` plano e suas duas guardas | 1, 5 |
| `src/orchestrator/api/schemas.py` | `CatalogoJSON`; remoção de `DominioJSON` | 2, 5 |
| `src/orchestrator/api/app.py` | `/api/catalogo` novo; remoção de `/api/dominios` | 2, 5 |
| `src/orchestrator/grill/ferramentas.py` | os nomes de bloco que o MODELO recebe no schema | 3 |
| `src/orchestrator/grill/receita.py` | resolver nome de bloco ao construir | 3 |
| `src/orchestrator/grill/catalogo.py` | remoção do `CATALOGO` de conciliação | 3 |
| `src/orchestrator/authoring/composicao.py` | remoção de `Composicao.dominio` | 5 |
| `src/orchestrator/agent/declarado.py` | remoção de `Dominio` | 5 |
| `web-app/src/api.ts`, `App.tsx`, `Painel.tsx` | seletor sai, paleta vira o catálogo | 4 |
| `README.md` + o spec | a lacuna do §7, escrita | 6 |

---

### Task 1: O `Catalogo` plano, com as duas guardas migradas

**Files:**
- Modify: `src/orchestrator/domains/registro.py`
- Test: `tests/domains/test_registro.py`

**Interfaces:**
- Consumes: nada (primeira task)
- Produces:
  - `Catalogo` (dataclass congelado) com `ferramentas: ToolRegistry`, `regras: tuple[RegraDisponivel, ...]`, `agentes: tuple[AgenteDeclarado, ...]`
  - `CATALOGO: Catalogo` — a instância única
  - `Catalogo.bloco(nome: str) -> RegraDisponivel | AgenteDeclarado | None`

**Nota de escopo — `DOMINIOS` continua existindo nesta task.** O catálogo nasce ao lado. Quem remove é a Task 5, quando os consumidores já migraram.

**O achado que esta task precisa resolver.** O `CATALOGO` do grill tem um bloco que NENHUM `Dominio` tem: `revisor`, de classe `HUMANO`. `App.tsx:308` já registra isso como lacuna conhecida — *"`revisor` é classe HUMANO, e o modelo de domínio de hoje só tem regras e agentes"*. Fundir os dois catálogos sem incluí-lo perderia o degrau humano da composição, que é o degrau que fecha a cascata. O `Catalogo` plano carrega `revisor` como `RegraDisponivel` de classe `HUMANO` — o nome do tipo fica impreciso (não é regra), e isso é dito no código em vez de escondido.

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar ao fim de `tests/domains/test_registro.py`:

```python
from orchestrator.domains.registro import CATALOGO, Catalogo
from orchestrator.kernel.cost import CostClass


def test_o_catalogo_e_PLANO_e_traz_tudo_junto():
    """Um catálogo só, sem agrupamento. É o quadro em branco do §0.1.

    As contagens vêm das três origens somadas: 3 regras de conciliação + 2 de
    compras + o `revisor`, e 1 agente de cada domínio.
    """
    nomes_de_regra = {r.nome for r in CATALOGO.regras}

    assert {"L1", "L2", "L3", "preferido", "anteriores"} <= nomes_de_regra
    assert {a.name for a in CATALOGO.agentes} == {"investigador", "triador", "buscador"}


def test_o_catalogo_carrega_o_degrau_HUMANO():
    """O `revisor` existia só no catálogo do grill e em `Dominio` nenhum.

    Fundir os dois sem ele perderia o degrau que FECHA a cascata — e a
    invariante "proposta não resolve" depende de existir alguém que resolva.
    """
    revisor = next(r for r in CATALOGO.regras if r.nome == "revisor")

    assert revisor.cost_class is CostClass.HUMANO


def test_as_ferramentas_dos_TRES_dominios_estao_no_MESMO_registro():
    """"Todas as nossas tools disponíveis pra ele" — o pedido, virado teste."""
    nomes = CATALOGO.ferramentas.names()

    assert "contar_palavras" in nomes  # veio do swe
    assert len(nomes) >= 6  # as 5 da conciliação mais a do swe


def test_o_catalogo_RECUSA_bloco_com_nome_repetido():
    """A guarda que migrou de `Dominio.__post_init__`, e que fica MAIS
    perigosa aqui.

    Antes a colisão só podia acontecer dentro de um domínio; num catálogo
    plano ela pode acontecer entre quaisquer dois blocos do sistema. A
    composição indexa bloco por nome, e dois iguais fariam a cascata depender
    de quem foi procurado primeiro.
    """
    from orchestrator.agent.declarado import AgenteDeclarado, RegraDisponivel

    regra = RegraDisponivel(
        nome="colide", cost_class=CostClass.REGRA, resumo="x",
        construir=lambda p: None,
    )
    agente = AgenteDeclarado(
        name="colide", system="s", kind="k", prompt="{x}",
        tipos=("A",), abstem_com="NAO_SEI",
    )

    with pytest.raises(ValueError, match="nome repetido"):
        Catalogo(
            ferramentas=ToolRegistry([], contexto=None),
            regras=(regra,),
            agentes=(agente,),
        )


def test_o_catalogo_VALIDA_CONSTRUINDO_cada_agente():
    """"Validar é construir" — a outra guarda que migrou.

    Sem ela, uma declaração inválida só falharia ao EXECUTAR, que é depois de
    a pessoa ter montado a cascata inteira e clicado em rodar.
    """
    from orchestrator.agent.declarado import AgenteDeclarado

    # `max_turns=0` NÃO serve de fixture: `AgenteDeclarado.__post_init__` já
    # recusa isso ao DECLARAR, antes de `Catalogo` entrar em cena — o teste
    # passaria provando a guarda errada. Ferramenta inexistente é o caso que
    # `AgenteDeclarado` não tem como ver sozinho (ele não conhece registro
    # nenhum), e que só `construir_agente` descobre.
    quebrado = AgenteDeclarado(
        name="ferramenta_fantasma", system="s", kind="k", prompt="{x}",
        tipos=("A",), abstem_com="NAO_SEI", ferramentas=("nao_existe",),
    )

    with pytest.raises(ValueError):
        Catalogo(
            ferramentas=ToolRegistry([], contexto=None),
            regras=(),
            agentes=(quebrado,),
        )


def test_bloco_acha_por_nome_em_qualquer_das_duas_listas():
    assert CATALOGO.bloco("L1") is not None
    assert CATALOGO.bloco("triador") is not None
    assert CATALOGO.bloco("nao_existe") is None
```

Acrescentar ao topo do arquivo, junto dos imports existentes:

```python
from orchestrator.agent.tools.registry import ToolRegistry
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/domains/test_registro.py -q
```

Esperado: `ImportError: cannot import name 'CATALOGO'`.

- [ ] **Step 3: Implementar o `Catalogo`**

Em `src/orchestrator/domains/registro.py`, acrescentar ANTES das definições de domínio:

```python
@dataclass(frozen=True)
class Catalogo:
    """Tudo que dá para compor, junto, sem agrupamento.

    **Por que sem `kinds`.** O `Dominio` agrupava por `kind` porque "uma
    cascata com um resolver de conciliação e um de compras não é ruim — é
    vazia de sentido, porque o segundo roda sobre um pool que o primeiro nem
    enxerga". Continua verdade, e a fatia do grafo passou a dizer isso melhor:
    `Stage.consome`/`Stage.produz` declara a fiação POR DEGRAU e
    `WorkflowDefinition.__post_init__` recusa um grafo cujos kinds não
    conectam. Aquilo valida o grafo que vai rodar; isto validava uma partição
    de catálogo. O agrupamento é resto.

    **O `revisor` mora aqui, e o nome do tipo mente um pouco.** Ele é classe
    `HUMANO`, não regra. `RegraDisponivel` descreve "bloco determinístico com
    parâmetros ajustáveis", o que serve de forma, não de nome. Ele vivia só no
    catálogo do grill, e `Dominio` nenhum o carregava — a lacuna estava
    registrada em `App.tsx`. Fundir sem ele perderia o degrau que FECHA a
    cascata.
    """

    ferramentas: ToolRegistry
    regras: tuple[RegraDisponivel, ...] = ()
    agentes: tuple[AgenteDeclarado, ...] = ()

    def __post_init__(self) -> None:
        # Guarda 1, migrada de `Dominio.__post_init__` e mais perigosa aqui: a
        # composição indexa bloco por NOME, e dois iguais fariam a cascata
        # depender de quem foi procurado primeiro. Num catálogo plano a colisão
        # deixa de ser possível só dentro de um domínio.
        nomes = [r.nome for r in self.regras] + [a.name for a in self.agentes]
        repetidos = sorted({n for n in nomes if nomes.count(n) > 1})
        if repetidos:
            raise ValueError(f"catálogo com nome repetido entre blocos: {repetidos}")
        # Guarda 2, também migrada: VALIDAR É CONSTRUIR. Sem isto, uma
        # declaração inválida só falha ao EXECUTAR — depois de a pessoa ter
        # montado a cascata inteira e clicado em rodar.
        for a in self.agentes:
            construir_agente(a, ClienteDeValidacao(), self.ferramentas)

    def bloco(self, nome: str) -> "RegraDisponivel | AgenteDeclarado | None":
        """O bloco com este nome, venha ele de qual lista vier.

        Existe porque quem compõe conhece o NOME, não a natureza: o
        entrevistador recebe "L2" do modelo e a tela recebe "L2" de um clique,
        e nenhum dos dois deveria precisar saber em que lista procurar.
        """
        for r in self.regras:
            if r.nome == nome:
                return r
        for a in self.agentes:
            if a.name == nome:
                return a
        return None
```

E, no FIM do arquivo, a instância — montada do que já está declarado, nunca digitada de novo:

```python
def _todas_as_ferramentas() -> ToolRegistry:
    """Um registro com as ferramentas de todas as origens.

    `register` já recusa nome repetido, então uma colisão entre origens falha
    na importação em vez de uma das duas ganhar em silêncio. `contexto=None`
    porque catálogo NÃO executa: quem executa chama `com_contexto`.
    """
    junto = ToolRegistry(contexto=None)
    for origem in (catalogo_de_ferramentas(), ferramentas_swe()):
        for nome in origem.names():
            junto.register(origem.spec(nome))
    return junto


# O revisor: o degrau HUMANO que fecha a cascata. Ver o docstring de `Catalogo`.
_REVISOR = RegraDisponivel(
    nome="revisor",
    cost_class=CostClass.HUMANO,
    resumo="a decisão humana que fecha a cascata",
    construir=lambda p: RevisorHumano(fila=Fila.vazia()),
)

CATALOGO = Catalogo(
    ferramentas=_todas_as_ferramentas(),
    regras=(*CONCILIACAO.regras, *PROCUREMENT.regras, _REVISOR),
    agentes=(*CONCILIACAO.agentes, *SWE.agentes, *PROCUREMENT.agentes),
)
```

Acrescentar os imports que isso exige, no topo:

```python
from dataclasses import dataclass

from orchestrator.agent.declarado import ClienteDeValidacao, construir_agente
from orchestrator.review.fila import Fila
from orchestrator.review.revisor import RevisorHumano
```

- [ ] **Step 4: Rodar os testes novos**

```bash
./.venv/Scripts/python.exe -m pytest tests/domains/test_registro.py -q
```

Esperado: PASS, e os testes antigos de `DOMINIOS` continuam passando — `DOMINIOS` não foi tocado.

- [ ] **Step 5: Conferir a camada**

```bash
./.venv/Scripts/python.exe -m pytest tests/arquitetura -q
```

Esperado: PASS. `domains` pode importar `review` (está na tabela). Se falhar, PARE e reporte: significa que o `revisor` não pode morar aqui e a decisão precisa ser revista.

- [ ] **Step 6: Suíte inteira e lint**

```bash
./.venv/Scripts/python.exe -m pytest -q && ./.venv/Scripts/python.exe -m ruff check src tests
```

- [ ] **Step 7: Commit**

```bash
git add src/orchestrator/domains/registro.py tests/domains/test_registro.py
git commit -m "feat(catalogo): o catalogo plano, com as duas guardas migradas"
```

---

### Task 2: `/api/catalogo` serve o catálogo plano

**Files:**
- Modify: `src/orchestrator/api/schemas.py`
- Modify: `src/orchestrator/api/app.py`
- Test: `tests/api/test_compor.py`

**Interfaces:**
- Consumes: `CATALOGO` da Task 1
- Produces: `GET /api/catalogo → CatalogoJSON` com a forma `{ferramentas, regras, agentes}`

**Esta task MUDA a forma de uma rota existente.** Hoje `/api/catalogo` devolve `list[EntradaCatalogoJSON]` — o cardápio do grill. A forma nova separa regra de agente pela mesma razão que `DominioJSON` já separava: *"o que a tela edita em cada um é diferente, e uma lista só obrigaria a inspecionar o tipo em cada linha de render"*. `/api/dominios` continua existindo até a Task 5.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/api/test_compor.py`, SUBSTITUIR os três testes de catálogo existentes (`test_o_catalogo_e_DERIVADO_do_CATALOGO_do_grill`, `test_o_catalogo_vem_na_ordem_em_que_a_CASCATA_RODA`, `test_o_catalogo_traz_os_parametros_com_DEFAULT_do_proprio_resolver`) por:

```python
def test_o_catalogo_e_DERIVADO_do_CATALOGO_plano():
    """Uma lista escrita à mão na camada HTTP divergiria na primeira mudança,
    e o sintoma seria uma tela oferecendo um bloco que `construir` recusa."""
    from orchestrator.domains.registro import CATALOGO

    dados = cliente.get("/api/catalogo").json()

    assert {r["nome"] for r in dados["regras"]} == {r.nome for r in CATALOGO.regras}
    assert {a["name"] for a in dados["agentes"]} == {a.name for a in CATALOGO.agentes}


def test_as_regras_vem_na_ordem_em_que_a_CASCATA_RODA():
    """Ordem alfabética sugeriria que o autor escolhe a sequência. Ele não
    escolhe: a paleta é oferecida do mais barato ao mais caro porque é essa a
    ordem de execução."""
    classes = [r["cost_class"] for r in cliente.get("/api/catalogo").json()["regras"]]
    ordem = ["REGRA", "AGENTE", "CREW", "HUMANO"]

    assert classes == sorted(classes, key=ordem.index)


def test_o_catalogo_traz_os_parametros_com_DEFAULT_do_proprio_resolver():
    """`_param` lê o default do dataclass do resolver. A tela preenche com ele,
    então renomear o campo no resolver explode no import e não na tela."""
    dados = cliente.get("/api/catalogo").json()
    l2 = next(r for r in dados["regras"] if r["nome"] == "L2")

    assert {p["nome"] for p in l2["parametros"]} == {"max_cents", "max_business_days"}
    assert all(isinstance(p["default"], int) for p in l2["parametros"])


def test_o_catalogo_expoe_as_ferramentas_de_TODAS_as_origens():
    """"Todas as nossas tools disponíveis" — o pedido, na borda HTTP."""
    nomes = {f["nome"] for f in cliente.get("/api/catalogo").json()["ferramentas"]}

    assert "contar_palavras" in nomes
    assert len(nomes) >= 6
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/api/test_compor.py -q
```

Esperado: `TypeError: list indices must be str` ou `KeyError: 'regras'` — a rota ainda devolve lista.

- [ ] **Step 3: Implementar o schema**

Em `src/orchestrator/api/schemas.py`, acrescentar (mantendo `DominioJSON` por ora):

```python
class CatalogoJSON(BaseModel):
    """Tudo que dá para compor, sem agrupamento.

    Regra e agente NÃO vão na mesma lista: o que a tela edita em cada um é
    diferente, e uma lista só obrigaria a inspecionar o tipo em cada linha de
    render. É a mesma separação que `DominioJSON` fazia, agora sem a partição.
    """

    ferramentas: list[FerramentaJSON]
    regras: list[RegraJSON]
    agentes: list[AgenteDeclaradoJSON]
```

- [ ] **Step 4: Implementar a rota**

Em `src/orchestrator/api/app.py`, substituir o corpo de `catalogo()` por uma versão que serve o plano. Reaproveitar as funções de conversão que `dominios()` já usa — elas montam `FerramentaJSON`, `RegraJSON` e `AgenteDeclaradoJSON` a partir dos objetos do registro, e duplicá-las aqui criaria duas fontes que divergem.

```python
@app.get("/api/catalogo", response_model=CatalogoJSON)
def catalogo() -> CatalogoJSON:
    """Tudo que dá para compor. Derivado do `CATALOGO`, nunca escrito à mão.

    As regras saem ordenadas por classe de custo e depois por nome: é a ordem
    em que a cascata VAI RODAR, então é a ordem em que a tela deve oferecer.
    Uma paleta em ordem alfabética sugeriria que o autor escolhe a sequência —
    e ele não escolhe.

    Esta rota SUBSTITUIU o cardápio do grill, que era só de conciliação. Foi
    ele que fez o chat propor `L1`/`L2`/`L3` para triagem de issues.
    """
    return CatalogoJSON(
        ferramentas=[_ferramenta_json(CATALOGO.ferramentas, n) for n in CATALOGO.ferramentas.names()],
        regras=[_regra_json(r) for r in sorted(CATALOGO.regras, key=lambda r: (r.cost_class, r.nome))],
        agentes=[_agente_json(a) for a in CATALOGO.agentes],
    )
```

Se as conversões estiverem inline dentro de `dominios()`, EXTRAIA-as para `_ferramenta_json`, `_regra_json` e `_agente_json` antes de usá-las aqui, e faça `dominios()` passar a chamá-las. Extrair é o que impede as duas rotas de divergirem enquanto as duas existem.

- [ ] **Step 5: Rodar os testes**

```bash
./.venv/Scripts/python.exe -m pytest tests/api -q
```

Esperado: PASS. **Atenção:** a tela ainda consome a forma antiga e vai quebrar no navegador até a Task 4 — isso é esperado e é por isso que a Task 4 existe. Nenhum teste de Python depende da forma antiga depois do Step 1.

- [ ] **Step 6: Suíte e lint**

```bash
./.venv/Scripts/python.exe -m pytest -q && ./.venv/Scripts/python.exe -m ruff check src tests
```

- [ ] **Step 7: Commit**

```bash
git add src/orchestrator/api/schemas.py src/orchestrator/api/app.py tests/api/test_compor.py
git commit -m "feat(api): /api/catalogo serve o catalogo plano"
```

---

### Task 3: O chat compõe do catálogo plano

**É a task que o dono vê primeiro.** É a diferença entre *"descreva uma triagem de issues"* devolver uma cascata bancária e devolver uma cascata de triagem.

**Files:**
- Modify: `src/orchestrator/grill/ferramentas.py:42-43,91`
- Modify: `src/orchestrator/grill/receita.py:114-117`
- Modify: `src/orchestrator/grill/catalogo.py` (remoção do `CATALOGO`)
- Test: `tests/grill/test_catalogo.py`, `tests/grill/test_ferramentas.py`, `tests/grill/test_receita.py`

**Os dois call sites, encontrados lendo — o entrevistador NÃO usa o catálogo
direto.** `grill/ferramentas.py:91` monta `{"enum": sorted(CATALOGO)}`, que é a
lista de nomes válidos que o MODELO recebe no schema da ferramenta; é literalmente
onde o chat aprende que só existem cinco blocos. E `grill/receita.py:114` faz
`CATALOGO.get(item.nome)` para resolver nome em resolver na hora de construir.

**Interfaces:**
- Consumes: `CATALOGO` da Task 1
- Produces: o entrevistador oferece ao modelo os blocos do catálogo plano

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar a `tests/grill/test_catalogo.py`:

```python
def test_o_entrevistador_oferece_blocos_de_TODAS_as_origens():
    """O defeito que esta fatia existe para fechar.

    `grill/catalogo.py` exportava `CATALOGO = ['L1','L2','L3','agente',
    'revisor']` — conciliação pura, sem noção de domínio. Descrever uma
    triagem de issues devolvia uma cascata bancária, e nem `api/entrevista.py`
    nem `Chat.tsx` mencionavam domínio em lugar nenhum.
    """
    from orchestrator.domains.registro import CATALOGO

    oferecidos = {r.nome for r in CATALOGO.regras} | {a.name for a in CATALOGO.agentes}

    assert "triador" in oferecidos, "o chat continua sem oferecer o agente de issues"
    assert "L1" in oferecidos, "o chat perdeu os blocos de conciliação"
    assert "revisor" in oferecidos, "o chat perdeu o degrau humano"
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/grill/test_catalogo.py -q
```

Esperado: falha em `"triador" in oferecidos` se o teste ainda apontar para o `CATALOGO` do grill; se já apontar para o plano, ele passa e o trabalho é migrar o ENTREVISTADOR (Step 3).

- [ ] **Step 3: Apontar os dois call sites para o catálogo plano**

**Uma diferença de forma que precisa ser tratada, não contornada.** As entradas
antigas eram todas `EntradaCatalogo` (`.nome`, `.cost_class`, `.resumo`,
`.parametros`, `.construir`). No catálogo plano há DUAS formas: `RegraDisponivel`
tem a mesma, mas `AgenteDeclarado` tem `.name` em vez de `.nome` e não tem
`.construir` — quem o constrói é `construir_agente`. Quem consome precisa
ramificar. `authoring/composicao.py` já ramifica assim entre `BlocoRegra` e
`BlocoAgente`; siga aquele padrão, não invente um segundo.

Em `grill/ferramentas.py`:

```python
from orchestrator.domains.registro import CATALOGO

def _nomes_disponiveis() -> list[str]:
    """Os nomes que o MODELO pode escolher.

    Era `sorted(CATALOGO)` sobre o cardápio da conciliação — cinco nomes
    fixos —, e é literalmente aqui que o chat aprendia que só existia
    conciliação. Derivar do catálogo é o que faz "descreva uma triagem de
    issues" parar de devolver uma cascata bancária.
    """
    return sorted([r.nome for r in CATALOGO.regras] + [a.name for a in CATALOGO.agentes])
```

e usar `_nomes_disponiveis()` nos dois pontos (a descrição em `:42-43` e o
`enum` em `:91`).

Em `grill/receita.py`, trocar `CATALOGO.get(item.nome)` por
`CATALOGO.bloco(item.nome)` e a mensagem de erro por
`f"bloco desconhecido: {item.nome!r}. disponíveis: {_nomes_disponiveis()}"`,
ramificando entre regra e agente na construção.

- [ ] **Step 4: Remover o `CATALOGO` do grill**

Em `src/orchestrator/grill/catalogo.py`, remover o dicionário `CATALOGO` e as funções `_l1`/`_l2`/`_l3`/`_agente`/`_revisor` que só ele usava. O que sobrar (`EntradaCatalogo`, `ParametroSpec`, `_param`) fica se ainda tiver consumidor; se não tiver, o arquivo inteiro sai.

**Não deixe o `CATALOGO` do grill existir ignorado.** Um catálogo morto que ninguém lê é o próximo a ser lido por engano.

- [ ] **Step 5: Rodar os testes de grill**

```bash
./.venv/Scripts/python.exe -m pytest tests/grill tests/api -q
```

Esperado: PASS. Testes que importavam `grill.catalogo.CATALOGO` mudam de alvo — eles NÃO estão entre os protegidos, porque são desta fatia.

- [ ] **Step 6: Suíte e lint**

```bash
./.venv/Scripts/python.exe -m pytest -q && ./.venv/Scripts/python.exe -m ruff check src tests
```

- [ ] **Step 7: Commit**

```bash
git add src/orchestrator/grill tests/grill
git commit -m "feat(grill): o chat compoe do catalogo plano, nao do cardapio da conciliacao"
```

---

### Task 4: A tela sem seletor

**Files:**
- Modify: `web-app/src/api.ts`, `web-app/src/App.tsx`, `web-app/src/Painel.tsx`
- Test: `tests/api/test_compor.py` (as asserções sobre o bundle)

**Interfaces:**
- Consumes: `GET /api/catalogo → {ferramentas, regras, agentes}` da Task 2
- Produces: a tela sem `<select>` de domínio

**O que muda de comportamento, e precisa de decisão consciente.** `agenteEmBranco(nome, dominio.kinds[0] ?? "")` pegava o `kind` do domínio. Sem domínio, **o `kind` vira um campo que a pessoa preenche** — e isso é o certo para um quadro em branco: o grafo precisa do `kind` para ligar os degraus, então quem monta precisa dizer qual é. O campo já existe no painel do agente; o que muda é que ele passa a nascer vazio em vez de pré-preenchido.

- [ ] **Step 1: Trocar o tipo e a chamada em `api.ts`**

```ts
export interface Catalogo {
  ferramentas: Ferramenta[];
  regras: Regra[];
  agentes: AgenteDeclarado[];
}
```

Substituir `dominios: () => pedir<DominioInfo[]>("/api/dominios")` por:

```ts
  catalogo: () => pedir<Catalogo>("/api/catalogo"),
```

Remover `DominioInfo` e o campo `dominio: string` do corpo de `criarComposicao`.

- [ ] **Step 2: Tirar o seletor do `App.tsx`**

- Remover os estados `dominios`, `dominioId` e o `useEffect` que chamava `api.dominios()`; no lugar, um estado `catalogo: Catalogo | null` alimentado por `api.catalogo()`.
- `nosPorDominio` vira `nos: NoDoCanvas[]` — sem domínio não há por que separar os nós por chave. O `useCallback` que indexava por `dominioId` simplifica junto.
- Remover o `<label>` com o `<select>` de domínio do cabeçalho.
- Em `aceitarProposta`, remover `dominios.find((d) => d.id === "conciliacao")` — a proposta do chat pousa no canvas único.
- Em `criarComposicao`, parar de enviar `dominio`.

- [ ] **Step 3: Apontar o `Painel.tsx` para o catálogo**

Trocar a prop `dominio: DominioInfo | null` por `catalogo: Catalogo | null` e as leituras `p.dominio?.regras` / `p.dominio?.agentes` por `p.catalogo?.regras` / `p.catalogo?.agentes`.

O bloco que hoje diz "domínio sem regra é uma cascata que começa 100% no agente" continua valendo e continua útil — ele passa a falar do catálogo.

- [ ] **Step 4: Typecheck e build**

```bash
cd web-app && npx tsc --noEmit
npm --prefix web-app run build
```

Esperado: os dois limpos. `tsc` é o que pega referência sobrando a `DominioInfo` — o Vite não checa tipo.

- [ ] **Step 5: Verificar no navegador, não só nos testes**

```bash
./.venv/Scripts/python.exe -m uvicorn orchestrator.api.app:app --port 8111
```

Abrir `http://localhost:8111/?vista=compor` e confirmar, com os próprios olhos:
- não há `<select>` de domínio no cabeçalho;
- a paleta mostra blocos das TRÊS origens juntos (`L1`, `preferido`, `triador`, `revisor`);
- criar um agente em branco pede o `kind` em vez de assumir um;
- compor e validar ainda funciona.

- [ ] **Step 6: Suíte, lint e commit**

```bash
./.venv/Scripts/python.exe -m pytest -q && ./.venv/Scripts/python.exe -m ruff check src tests
git add web-app web tests/api/test_compor.py
git commit -m "feat(web): a tela sem seletor de dominio — a paleta e o catalogo inteiro"
```

---

### Task 5: `Dominio` morre

Agora que ninguém mais o usa.

**Files:**
- Modify: `src/orchestrator/agent/declarado.py` (remover `Dominio`)
- Modify: `src/orchestrator/domains/registro.py` (remover `DOMINIOS`, `CONCILIACAO`, `SWE`, `PROCUREMENT` como `Dominio`)
- Modify: `src/orchestrator/api/app.py`, `schemas.py` (remover `/api/dominios`, `DominioJSON`)
- Modify: `src/orchestrator/authoring/composicao.py` (remover `Composicao.dominio`)
- Test: `tests/domains/test_registro.py`, `tests/agent/test_declarado.py`, `tests/authoring/test_composicao.py`, `tests/api/test_composicoes.py`

**Interfaces:**
- Consumes: tudo das Tasks 1–4
- Produces: a ausência de `Dominio` no repositório

**Cuidado com `registro.py`.** As declarações `CONCILIACAO = Dominio(...)`, `SWE = ...` e `PROCUREMENT = ...` são de onde o `CATALOGO` da Task 1 se alimenta. Elas não podem simplesmente sumir: as REGRAS e os AGENTES dentro delas passam a ser declarados direto nas tuplas do `CATALOGO`, sem o embrulho `Dominio`. É movimentação de dado, não reescrita — cada `RegraDisponivel` e cada `AgenteDeclarado` viaja verbatim.

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar a `tests/domains/test_registro.py`:

```python
def test_o_conceito_de_DOMINIO_nao_existe_mais():
    """A metade "remover" da fatia, ancorada.

    Sem isto, um `Dominio` esquecido continuaria importável, e o próximo
    leitor não saberia se ele decide alguma coisa. Um conceito morto que
    ainda compila é o próximo a ser usado por engano.
    """
    import orchestrator.agent.declarado as declarado
    import orchestrator.domains.registro as registro

    assert not hasattr(declarado, "Dominio")
    assert not hasattr(registro, "DOMINIOS")
```

E a `tests/api/test_compor.py`:

```python
def test_a_rota_de_dominios_nao_existe_mais():
    assert cliente.get("/api/dominios").status_code == 404
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/domains/test_registro.py::test_o_conceito_de_DOMINIO_nao_existe_mais tests/api/test_compor.py::test_a_rota_de_dominios_nao_existe_mais -q
```

Esperado: as duas falham — `Dominio` ainda existe e a rota ainda responde 200.

- [ ] **Step 3: Remover**

Nesta ordem, para o interpretador apontar o que falta a cada passo:

1. `api/app.py`: apagar o handler `dominios()`.
2. `api/schemas.py`: apagar `DominioJSON` **e o campo `dominio` de `ComposicaoRequest`**. O segundo nao estava neste plano e foi achado pela Task 4: com o front parando de enviar `dominio` e o schema ainda exigindo, todo "Compor e validar" morreria num `422 Field required`. A Task 4 deu ao campo um default `"conciliacao"` como andaime de UMA fatia, marcado no codigo — e este e o passo que remove o andaime junto com o campo.
3. `authoring/composicao.py`: apagar o campo `dominio` de `Composicao`, o `buscar_dominio`, e as duas validações que dependiam dele (`regra desconhecida no domínio` e `não é do domínio`). A primeira vira "bloco desconhecido no catálogo"; a segunda **some**, porque é a checagem de `kind` contra a lista do domínio que o grafo substituiu. Ajustar `para_json`/`de_json` para não escrever nem ler `dominio`.
4. `domains/registro.py`: mover as `RegraDisponivel`/`AgenteDeclarado` de dentro de `CONCILIACAO`/`SWE`/`PROCUREMENT` para as tuplas do `CATALOGO`, verbatim, e apagar as três instâncias de `Dominio` e o `DOMINIOS`.
5. `agent/declarado.py`: apagar a classe `Dominio` e seu `__post_init__`. **Manter** `AgenteDeclarado`, `RegraDisponivel`, `ParametroDeRegra`, `ClienteDeValidacao` e `construir_agente`.

- [ ] **Step 4: Atualizar os testes que exercitavam `Dominio`**

`tests/agent/test_declarado.py` e `tests/domains/test_registro.py` têm testes de `Dominio` (incluindo `test_os_TRES_dominios_se_declaram` e `test_cada_dominio_tem_KIND_proprio_e_e_por_isso_que_nao_se_misturam`).

Para CADA um, decidir e registrar no relatório:
- a garantia **migrou** para o `Catalogo` (nome repetido, validar construindo) → o teste já existe desde a Task 1; apagar o antigo;
- a garantia **virou estrutural** (kinds não se misturam) → apagar, e dizer no commit que o grafo a substituiu;
- a garantia **continua viva e sem dono** → é um defeito desta fatia. PARE e reporte.

Não apague nenhum sem encaixá-lo numa das três.

- [ ] **Step 5: Suíte e lint**

```bash
./.venv/Scripts/python.exe -m pytest -q && ./.venv/Scripts/python.exe -m ruff check src tests
```

Esperado: verde. `tests/domains/test_generalidade.py` e `test_redacao.py` **não podem ter sido tocados** — confirme com `git status`.

- [ ] **Step 6: Build do front e commit**

```bash
cd web-app && npx tsc --noEmit && npm --prefix web-app run build
git add -A
git commit -m "refactor: Dominio morre — o grafo ja fazia a guarda que ele fazia"
```

---

### Task 6: A lacuna, escrita onde alguém lê

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-09-17-quadro-em-branco-design.md` (marcador de estado)

**Interfaces:**
- Consumes: tudo
- Produces: nenhuma API — é documentação, e é a parte que o dono pediu explicitamente para não ficar em silêncio

- [ ] **Step 1: Registrar a lacuna no README**

Na seção "O que este projeto NÃO é", acrescentar, na voz do arquivo:

```markdown
- **Não tem piso barato para trabalho novo, ainda.** A paleta é um catálogo
  plano de tudo que existe, e o que existe hoje é regra de conciliação e de
  compras — código, com a forma do trabalho delas. Um workflow de um trabalho
  NOVO começa 100% na classe `AGENTE`, que é o pior custo possível. Enquanto
  isso for verdade, a tese de custo não se aplica a ele: o que fecha é a regra
  genérica declarativa (igualdade, tolerância, agrupamento, tabela, padrão,
  limiar), e ela ainda não existe.
```

E, na seção "Os dois eixos" ou logo após a tabela de domínios, trocar qualquer texto que ainda fale em escolher domínio.

- [ ] **Step 2: Marcar o spec como entregue**

No cabeçalho de `2026-09-17-quadro-em-branco-design.md`, trocar `**Estado:** proposta` por:

```markdown
**Estado:** ENTREGUE (B1–B6). A lacuna da §7 continua ABERTA por decisão
explícita do dono: o quadro em branco entrou antes do G3, e enquanto o G3 não
entrar, trabalho novo começa 100% na classe AGENTE. Registrado no README.
```

- [ ] **Step 3: Conferir que o README não promete o que não existe**

Ler o README inteiro procurando qualquer frase que tenha virado mentira com esta fatia — menção a domínio, a escolher domínio, ou à paleta ser por domínio. Este repositório trata comentário que afirma mais do que o código faz como defeito; o README é o comentário mais lido de todos.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/superpowers/specs/2026-09-17-quadro-em-branco-design.md
git commit -m "docs: o quadro em branco entregue, e a lacuna de custo dita em voz alta"
```

---

## Fora deste plano

- **G3 — regras genéricas declarativas.** É o que fecha a lacuna da §7 e tem plano próprio. Entra depois, por decisão do dono.
- **A UX do campo de identidade.** Sem domínio, o defeito que gerou esta fatia (digitar "triagem-de-issues" e receber blocos bancários) some pela raiz — não há mais domínio errado para se estar. Não há o que consertar.
- **`review/serial.py:20`** chama `p.tipo.value`, mas `Proposal.tipo` é `str` desde o PR #6. Um domínio não-conciliação que grave proposta na fila quebra ali. É defeito real, pré-existente e independente desta fatia.
