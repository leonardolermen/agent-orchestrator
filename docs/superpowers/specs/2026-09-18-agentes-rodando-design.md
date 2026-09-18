# Agentes rodando: a entrada, o motor e o teto

**Data:** 2026-09-18
**Estado:** proposta
**Antecessor:** `2026-09-17-quadro-em-branco-design.md` (B1–B6 entregues)

---

## 0. O pedido, e a evidência que o motivou

A fatia anterior abriu a autoria: o catálogo virou plano, o seletor de domínio
sumiu, e o chat passou a compor a partir de tudo que existe. Aí a revisão final
rodou o que a fatia tinha acabado de permitir:

```
POST /api/receitas  [preferido, anteriores]  → 201
POST /api/workflows/triagem-compras/runs     → 200
  {'bank_total': 56, 'deterministic_rate': 0.0, 'gap': {'items': 56, 'rate': 1.0}}
```

Um `200` com `0.0%` e lacuna de `100%`, sobre um dataset que aqueles resolvers
não enxergam. Nenhum erro. A tela desenha isso como medição.

O pedido do dono, depois de ver: **fazer os agentes funcionarem.** E, explícito:
a lacuna de custo fica por último.

### 0.1 Três bloqueios, e o do meio é o que ninguém vê

| # | O que impede | Onde |
|---|---|---|
| A | A API RECUSA qualquer cascata com agente: `409`, *"rode pela CLI"* | `api/app.py:413` |
| B | O `/runs` chama `reconcile(bank, ledger)`, **não** `execute()` | `api/app.py:422` |
| C | Só existe um `Source`: o sintético | `kernel/source.py` |

**B é o gargalo, e ele não aparece na tela.** O motor genérico existe e todo
mundo usa — a CLI, o scaffold, os três domínios. A API é a única que passa pela
função de domínio da conciliação. Enquanto isso for verdade, não existe teto que
ajude nem fonte que sirva: o pool continua sendo `bank`/`ledger`.

---

## 1. A decisão que o código já tinha tomado

`SyntheticSource` separa `load()` de `dataset()`, e o docstring diz por quê:

> *"O gabarito é insumo de AVALIAÇÃO, e o motor não deve recebê-lo. Um `Source`
> de dado real não tem este método — e é justamente por isso que
> `metrics.evaluate` continua exigindo um `Dataset` em vez de um `Source`."*

Daí sai a consequência que governa este spec inteiro:

> **Sem gabarito não existe taxa de acerto.**
> O que existe sem gabarito é o que o `Run` já carrega: quantos itens cada
> resolver resolveu, quanto custou, o que sobrou, e a lacuna.

Medição sem verdade é medição legítima — é a diferença entre *"resolvi 83% do
volume"* (contável) e *"acertei 83%"* (exige gabarito). O `RunJSON` de hoje
mistura as duas porque só existia uma fonte.

---

## 2. A fonte vem no PEDIDO, não no workflow

**POR QUE.** Um workflow não é casado com uma entrada: o mesmo workflow roda na
planilha de ontem e na de hoje. Declarar a fonte na `WorkflowDefinition` ligaria
os dois e obrigaria uma definição nova por arquivo novo.

**COMO.** `RunRequest` ganha um campo `fonte`, e os três campos de benchmark
(`seed`, `n`, `taxa_divergencia`) passam a ser o que sempre foram: os parâmetros
de UMA fonte, a sintética.

```python
class FonteSintetica(BaseModel):
    tipo: Literal["sintetica"] = "sintetica"
    seed: int = Field(default=1, ge=0)
    n: int = Field(default=300, ge=1, le=5000)
    taxa_divergencia: float = Field(default=0.15, ge=0.0, le=1.0)


class FonteArquivo(BaseModel):
    tipo: Literal["arquivo"]
    caminho: str
    kind: str
    campo_id: str
```

União discriminada por `tipo`, como `BlocoJSON` já é — um objeto com
`seed?` ao lado de `caminho?` aceitaria os cruzamentos que não significam nada.

E o teto, que a §6 exige estar no pedido:

```python
class RunRequest(BaseModel):
    fonte: FonteSintetica | FonteArquivo = FonteSintetica()
    # Teto da EXECUÇÃO inteira, em micro-centavos. `None` = o teto do próprio
    # agente (`AgentSpec.budget_total_microcents`). Nunca "sem teto": não há
    # valor que signifique isso, e é deliberado.
    teto_microcents: int | None = Field(default=None, ge=0)
```

**Compatibilidade.** `RunRequest` sem `fonte` continua valendo e cai na
sintética com os defaults de hoje. É o que mantém o canvas de execução, a CLI do
grill e os testes existentes funcionando sem edição.

---

## 3. Um mapeamento, vários leitores

**POR QUE.** CSV, JSON e HTTP diferem em como as linhas chegam. O que fazer com
uma linha é idêntico nos três, e desenhar isso três vezes produziria três
formatos de declaração que divergem na primeira mudança.

**O miolo:**

```
linha (dict)  →  WorkItem(id=linha[campo_id], kind=<declarado>, payload=linha)
```

Três decisões, e cada uma tem um motivo:

**`payload` é o dicionário da linha, cru.** O kernel nunca o inspeciona — é a
propriedade de `WorkItem.payload` desde o PR #3. E quem o consome já sabe lidar:
`AgenteDeclarado.prompt` é um template que formata a partir do payload
(`"{titulo}\n\n{corpo}"` no `swe`). O caminho inteiro — fonte declarada, agente
declarado, prompt declarado — fica sem código, que é o que "quadro em branco"
quer dizer.

**`kind` é declarado, não inferido.** Não existe coluna que diga o que um item
É. Inferir do nome do arquivo ou da primeira coluna seria adivinhação com cara
de conveniência, e o `kind` é o que liga um degrau ao outro no grafo.

**`campo_id` é declarado, e falha alto quando falta.** `WorkItem` recusa id
vazio (`work.py:__post_init__`), e `WorkSet` recusa id repetido. Uma coluna de
id ausente ou com valores repetidos é erro de configuração, não linha a pular:
pular em silêncio produziria um pool menor do que o arquivo, e ninguém saberia.

---

## 4. `ref` estável, e onde arquivo e HTTP divergem

O protocolo exige que duas execuções sobre a mesma entrada produzam o mesmo
`ref` — sem isso o replay não casa as decisões humanas já tomadas.

| Fonte | `ref` |
|---|---|
| sintética | `synth:s1-n300-t0.15` (existe) |
| arquivo | `file:<caminho>@<sha256 do conteúdo>` |
| http | `http:<url>@<etag ou hash do corpo>` — **plano 2** |

O hash do conteúdo, e não a data de modificação: um arquivo copiado ou tocado
muda `mtime` sem mudar o trabalho, e o replay quebraria por nada.

**Por que o HTTP fica para o segundo plano.** `ref` estável ali exige etag ou
hash do corpo, e o §8 do spec da plataforma geral já nomeia a armadilha que uma
implementação apressada comete primeiro: *"um `ref` com `datetime.now()`
dentro"*. Junto vêm auth, paginação e cursor. Nada disso bloqueia arquivo, e
tudo isso atrasaria.

---

## 5. O `/runs` passa pelo motor genérico

**ONDE.** `api/app.py`, a função `_executar`.

```python
# sai
resultado = reconcile(dataset.bank, dataset.ledger, definition=definicao, ...)

# entra
run = execute(definicao, fonte.load(), input_ref=fonte.ref, bus=bus)
```

**A conciliação não perde nada**, e é isso que torna a troca segura: ela vira
mais uma fonte — a sintética —, e o `reconcile()` continua existindo para a CLI
e para quem precisa do `ReconcileResult` com `divergences`. O que a API deixa de
fazer é supor que todo trabalho tem dois lados.

**A avaliação continua exigindo `Dataset`.** `evaluate(dataset, resultado)` só é
chamada quando a fonte tem gabarito, e é a fonte que diz se tem — não um `if`
sobre o id do workflow.

---

## 6. Rodar com agente, com teto

A regra deste módulo, como o chat a deixou:

> EXECUTAR um workflow pela web nunca gasta dinheiro.
> COMPOR por conversa gasta, com teto, e o teto é dito antes.

Ela ganha a segunda exceção, e fica mais precisa em vez de mais frouxa:

> EXECUTAR pela web gasta **quando a cascata tem agente**, com teto, e o teto é
> dito antes.

**As três guardas são as mesmas do chat, e nenhuma é opcional** — elas já
existem e já são testadas naquele caminho:

**Guarda 1 — teto por execução, dito antes.** `AgentSpec.budget_total_microcents`
já existe (400.000.000 µ¢, ≈ US$ 4) e já é aplicado por execução. O pedido
carrega o teto e a resposta o devolve; sem teto explícito, vale o do agente.

**Guarda 2 — o custo volta e aparece.** `Run.cost_by_resolver` já existe e já
acumula entre rondas (corrigido na fatia do grafo). A resposta o carrega por
resolver, como já carrega para as regras.

**Guarda 3 — sem chave, recusa explícita.** Sem `ANTHROPIC_API_KEY`, `409` com
motivo legível. `/api/ambiente` já publica `tem_chave`, e a tela já o mostra —
o botão desabilita antes, e o servidor recusa de qualquer jeito.

**O 409 muda de motivo, não some.** Hoje ele diz *"tem uma etapa paga"*. Passa a
dizer *"sem chave"* ou *"sem teto"*. Uma cascata com agente deixa de ser
recusada por ter agente.

**O que NÃO muda:** `ClienteAusente` continua sendo o default de `construir`.
Quem executa passa um cliente de verdade, de propósito — a tranca continua
armada, e desarmá-la continua sendo um ato explícito.

---

## 7. Duas formas de resposta

A §1 decidiu isto; aqui é a forma.

```python
class RunJSON(BaseModel):
    input_ref: str
    itens: int                       # o tamanho do pool que entrou
    resolvidos: int
    por_resolver: list[ResolverRunJSON]
    gap: GapJSON
    custo_microcents: int
    # Só quando a fonte tem gabarito. AUSENTE, não zero.
    contra_gabarito: MedidoJSON | None = None
```

```python
class MedidoJSON(BaseModel):
    """O que só existe quando a fonte carrega gabarito."""

    seed: int
    n: int
    bank_total: int
    deterministic_rate: float
```

`seed`, `n` e `bank_total` saem do topo e viram campos daqui, onde significam
alguma coisa. Num CSV de issues eles não têm valor certo nem valor neutro — têm
ausência, e ausência é o que a forma passa a expressar.

**`contra_gabarito: None` é a forma de dizer "não medido contra verdade".** Não
é `0.0`, e a tela não desenha uma barra vazia: ela diz que não há gabarito. Este
projeto já revogou duas conclusões por ler número pequeno como resultado
(P6.81 e P6.84); publicar `0.0%` sobre uma fonte sem verdade seria a mesma
falha com outra roupa.

**Isto quebra `RunJSON` para os consumidores atuais** — a vista de execução e os
testes de `test_execucao.py`. A quebra é contida (são todos nossos) e deliberada:
manter o formato antigo exigiria inventar `bank_total` para um CSV de issues.

---

## 7.1 A raiz, e por que ela não é detalhe

`FonteArquivo.caminho` é uma string que chega pela rede e vira uma leitura de
disco no servidor. Sem cerca, esse endpoint é um leitor de arquivos arbitrários
— `../../etc/passwd` é o exemplo de sempre, e `data/fila/**` é o exemplo que
importa aqui, porque ele devolveria decisões humanas de outro workflow.

**COMO.** Uma raiz configurada (`_RAIZ_ENTRADAS`, ao lado das que `api/app.py`
já tem para fila e receitas), e o caminho resolvido sob ela:

```python
alvo = (raiz / caminho).resolve()
if not alvo.is_relative_to(raiz.resolve()):
    raise HTTPException(422, "caminho fora da raiz de entradas")
```

`resolve()` ANTES da comparação, e `is_relative_to` em vez de `startswith`: um
prefixo de string diz que `/dados-secretos` está dentro de `/dados`, e um
symlink dentro da raiz apontando para fora passa por qualquer checagem feita
antes de resolver.

A raiz é isolada nos testes pela mesma fixture autouse que já isola a fila e o
run store (`tests/conftest.py`), pelo mesmo motivo: sem isso a suíte lê e
escreve onde o desenvolvedor guarda dado de verdade.

---

## 8. O que este plano deliberadamente NÃO faz

- **Não faz upload.** O `caminho` é lido do disco do servidor, como `data/` já
  é. Upload com id próprio, limite de tamanho e expiração é outra fatia.
- **Não faz HTTP.** Plano 2, pelas razões da §4.
- **Não fecha a lacuna de custo.** Decisão explícita do dono: um trabalho novo
  continua começando 100% na classe `AGENTE` até o G3 existir.
- **Não infere `kind` nem `campo_id`.** §3.
- **Não deixa a fonte morar na `WorkflowDefinition`.** §2.
- **Não pula linha inválida.** §3.

---

## 9. Riscos

| Risco | Sintoma | Mitigação |
|---|---|---|
| Executar pela web vira gasto sem freio | a conta aparece no fim do mês | §6, as três guardas, todas já existentes e testadas no caminho do chat |
| `ref` instável | replay não casa decisão humana já tomada | §4: hash do CONTEÚDO, nunca `mtime` nem `now()` |
| Leitura de caminho arbitrário do servidor | alguém lê `/etc/passwd` — ou pior, `data/fila/**`, a trilha de decisões humanas | §7.1: raiz configurada, `resolve()` antes de comparar, `is_relative_to` e não `startswith` |
| `RunJSON` quebrando a tela | a vista de execução quebra no F5 | quebra contida e deliberada (§7); a vista muda na mesma fatia |
| Pool grande demais | uma planilha de 200k linhas derruba o processo | teto de linhas no leitor, com recusa legível — o mesmo espírito do `n_max` que `RunRequest` já tem |
| Trocar `reconcile` por `execute` mudar número | o golden de 12 sementes muda | `reconcile` já chama `execute` por dentro; a diferença é só o que sai, não o que roda |

---

## 10. Milestones

| M | O quê | Plano |
|---|---|---|
| **R1** | `RunRequest.fonte` como união discriminada; a sintética como uma fonte entre outras | 1 |
| **R2** | `/runs` passa por `execute()`; `reconcile` fica para a CLI | 1 |
| **R3** | `RunJSON` em duas formas; `contra_gabarito` ausente sem gabarito | 1 |
| **R4** | `FonteArquivo` com CSV e JSON, `ref` por sha256, raiz configurada | 1 |
| **R5** | Executar com agente: teto, custo devolvido, recusa sem chave | 1 |
| **R6** | A tela: escolher a fonte, ver o custo, ver "sem gabarito" | 1 |
| **R7** | `FonteHttp`: auth, paginação, cursor, `ref` por etag | 2 |

**R2 primeiro, e não é ordem arbitrária.** Enquanto o `/runs` chamar
`reconcile`, R4 e R5 não têm onde encaixar: a fonte não tem quem a receba e o
agente não tem quem o execute.

---

## 11. A frase que resume

> O agente já sabia trabalhar. O que faltava era alguém entregar trabalho a ele
> — e deixar que ele gastasse para fazê-lo.
