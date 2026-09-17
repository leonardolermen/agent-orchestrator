# Quadro em branco: a plataforma sem domínio

**Data:** 2026-09-17
**Estado:** ENTREGUE (B1–B6). Duas lacunas continuam ABERTAS por decisão
explícita do dono, e nenhuma das duas é silêncio: (A) a lacuna de custo da §7 —
o quadro em branco entrou antes do G3, e enquanto o G3 não entrar, trabalho
novo começa 100% na classe AGENTE; (B) a guarda de `kind` que a §5 descreve
como "mais forte" não tem dono para composição feita pelo canvas —
`construir_composicao` emite um `Stage` só, com `consome`/`produz` nos
defaults, o que desliga a checagem de beco sem saída inteira antes de ela ter
algo para comparar. Fecha com o X7/X8 (`AgenteDeclarado.produz` + fiação em
`construir_composicao`), fora deste plano. Ambas registradas no README.
**Antecessor:** `2026-09-17-execucao-como-grafo-design.md` (X1–X6 entregues)

---

## 0. O pedido, e a evidência que o motivou

O dono compôs um workflow na tela, digitou `triagem-de-issues` no campo de
identidade, e recebeu uma paleta com `L1`, `L2`, `L3` e o agente `investigador`
— com vocabulário `DEFASAGEM_TEMPORAL`, `RETENCAO_IMPOSTO`, `PAGAMENTO_AGREGADO`.
Conciliação bancária inteira, para triar issues.

A pergunta que ele fez foi: *"ainda não tá muito fechado em conciliação?"* E a
resposta, medida, foi **sim — em três camadas diferentes**:

1. A paleta É por domínio, mas o default é `conciliacao` e o seletor fica no
   cabeçalho, longe da paleta e longe do campo de identidade. Quem digita
   "triagem-de-issues" não recebe sinal nenhum de que está no domínio errado.
2. O conteúdo é desigual: `conciliacao` tem 3 regras / 1 agente / 5 ferramentas;
   `swe` tem **0 regras**; `procurement` tem **0 ferramentas**.
3. **O chat ignora o domínio por completo.** `grill/catalogo.py` exporta
   `CATALOGO = ['L1','L2','L3','agente','revisor']` — cinco resolvers de
   conciliação, sempre. Nem `api/entrevista.py` nem `Chat.tsx` mencionam
   domínio em lugar nenhum.

O pedido que saiu daí: **quadro em branco, sem escolher domínio, o cliente monta
o workflow por prompt com todas as ferramentas disponíveis.**

### 0.1 O que "tirar domínio" significa, e o que NÃO significa

**Significa:** remover a partição de AUTORIA — o agrupamento que a tela usa para
filtrar a paleta, e que o `Dominio` existe para expressar.

**Não significa:** remover os workflows. `domains/procurement/workflow.py`,
`domains/swe`, `domains/redacao` e a conciliação são código Python que monta
`WorkflowDefinition`. Eles continuam existindo, rodando e sendo testados por
`tests/domains/test_generalidade.py`. O diretório `domains/` mantém o nome certo:
ele guarda domínios de TRABALHO, não uma taxonomia de autoria.

---

## 1. Há DOIS catálogos, e é por isso que o chat erra

O achado que mudou o desenho. Não havia um catálogo por domínio — havia dois
catálogos com escopos diferentes:

| Catálogo | Onde | Quem consome | Escopo |
|---|---|---|---|
| `DOMINIOS` | `domains/registro.py` | a paleta do canvas | por domínio |
| `CATALOGO` | `grill/catalogo.py` | o chat que compõe | **só conciliação** |

O segundo nunca soube o que é um domínio. Por isso a tela ficou por domínio numa
fatia anterior e o chat continuou propondo conciliação para tudo — os dois
caminhos de autoria divergiram sem ninguém notar, que é o mesmo modo de falha
que o P4.14 registra entre o canvas e a fila.

**Fundir os dois num catálogo plano fecha os dois problemas com uma peça.**

---

## 2. O catálogo único

**ONDE.** `domains/registro.py` deixa de exportar `DOMINIOS: dict[str, Dominio]`
e passa a exportar um `Catalogo` plano.

```python
@dataclass(frozen=True)
class Catalogo:
    ferramentas: ToolRegistry
    regras: tuple[RegraDisponivel, ...]
    agentes: tuple[AgenteDeclarado, ...]
```

Sem `kinds` e sem agrupamento. É o que existe, todo junto, disponível para
qualquer workflow.

**POR QUE no mesmo arquivo.** A tabela de camadas (`tests/arquitetura/`) diz que
NINGUÉM importa `domains`. O registro é a exceção que já existia, e ele importa
dos módulos de domínio para montar o que oferece. Mudar o CONTEÚDO do arquivo
não mexe na tabela; mover o arquivo mexeria, e por nada.

---

## 3. O que morre

| Peça | Onde |
|---|---|
| `Dominio` e seu `__post_init__` | `agent/declarado.py` |
| `DOMINIOS` | `domains/registro.py` |
| `DominioJSON`, rota `/api/dominios` | `api/schemas.py`, `api/app.py` |
| `Composicao.dominio` | `authoring/composicao.py` |
| o `<select>` de domínio | `web-app/src/App.tsx` |
| `CATALOGO` como coisa separada | `grill/catalogo.py` |

`AgenteDeclarado`, `RegraDisponivel` e `ParametroDeRegra` **ficam**: eles
descrevem blocos, não agrupamento.

---

## 4. Uma guarda MUDA DE LUGAR — não pode sumir

`Dominio.__post_init__` recusava regra e agente com o mesmo nome:

> *"a composição indexa blocos por nome, e dois iguais fariam a cascata depender
> de quem foi procurado primeiro"*

Isso continua verdade e fica **mais perigoso** num catálogo plano: antes o
conflito só podia acontecer dentro de um domínio, agora pode acontecer entre
quaisquer dois blocos do sistema. A guarda vira validação do `Catalogo` inteiro,
na importação — falha alto, como toda configuração inválida neste repositório.

`Dominio.__post_init__` também construía cada agente declarado com
`ClienteDeValidacao` — *"validar é construir"*. Essa guarda também migra: o
`Catalogo` valida construindo, na importação, pelo mesmo motivo.

---

## 5. O que substitui o `kinds`

Nada novo. O grafo.

`Dominio.kinds` existia porque *"uma cascata com um resolver de conciliação e um
de compras não é ruim — é vazia de sentido, porque o segundo roda sobre um pool
que o primeiro nem enxerga"*. Verdade — e resolvida pela fatia anterior:
`Stage.consome`/`Stage.produz` declara a fiação por degrau, e
`WorkflowDefinition.__post_init__` recusa um grafo cujos kinds não conectam.

Essa guarda é **mais forte** que a antiga: valida o grafo que vai rodar, em vez
de uma partição de catálogo. `Dominio.kinds` é resto do tempo em que o pool só
encolhia.

**Vale para o grafo — ainda não para todo caminho até ele.** A força depende
de os stages declararem `consome`/`produz`; para uma composição montada por
`construir_composicao` hoje, nenhum declara (ver o **Estado** no topo deste
arquivo e o docstring de `authoring/composicao.py` para o porquê). A guarda
certa ainda não alcançou esse caminho de autoria — o design desta seção está
certo, só falta chegar lá.

`AgenteDeclarado.kind` **fica**: um agente ainda declara sobre que tipo de item
trabalha. O que some é a conferência contra a lista de um domínio.

---

## 6. API e tela

**API.** `/api/catalogo` passa a servir o catálogo plano. Hoje essa rota serve o
cardápio do grill; ela deixa de ter escopo próprio e passa a ser a única fonte.
`/api/dominios` some.

```
GET /api/catalogo → { ferramentas: [...], regras: [...], agentes: [...] }
```

**Isto MUDA a forma da rota, e é deliberado.** Hoje `/api/catalogo` devolve uma
LISTA de entradas do grill (`EntradaCatalogoJSON[]`). A forma nova separa regra
de agente pela mesma razão que `DominioJSON` já separava: *"o que a tela edita em
cada um é diferente, e uma lista só obrigaria a inspecionar o tipo em cada linha
de render"*. Os consumidores são todos nossos — o canvas e os testes de
`test_compor.py` —, então a quebra é contida, mas ela é quebra e não pode entrar
em silêncio: `test_o_catalogo_e_DERIVADO_do_CATALOGO_do_grill` e os dois testes
de ordem e parâmetros mudam de alvo junto.

**Tela.** O seletor de domínio some do cabeçalho. A paleta é o catálogo inteiro.
O campo de identidade fica onde está — e passa a não ter mais como contradizer
um domínio, porque não há domínio.

**Chat.** O entrevistador compõe a partir do mesmo catálogo plano. É isto que
faz *"descreva uma triagem de issues"* parar de devolver `L1`/`L2`/`L3`.

---

## 7. A LACUNA, declarada

Esta seção existe porque o dono decidiu adiar o custo, e adiar em silêncio seria
outra coisa.

**Um quadro em branco com agente e ferramenta, sem regra genérica, começa 100%
na classe `AGENTE`** — o pior custo possível. Hoje as únicas regras são código
de conciliação (`ExactMatcher`, `ToleranceMatcher`) e de compras
(`FornecedorPreferido`, `ComprasAnteriores`). Elas continuam no catálogo e
continuam compondo, mas só servem a trabalho da forma delas. Para um trabalho
novo, não há piso barato.

O próprio README nomeia o modo de falha:

> *"Ampliar o mercado onde a tese se aplica não é o mesmo que aplicá-la, e
> confundir os dois é como um produto vira 'mais um framework de agentes' sem
> ninguém perceber."*

**Um quadro em branco só com agentes e ferramentas É mais um framework de
agentes.** O que fecha isso é o **G3** do spec da plataforma geral — tipos de
regra genéricos e declarativos (igualdade, tolerância, agrupamento, tabela de
decisão, padrão, limiar), que servem a qualquer trabalho porque têm os nomes dos
campos abertos. Os três primeiros são `L1`/`L2`/`L3` generalizados.

**Decisão registrada:** o quadro em branco entra ANTES do G3, por escolha
explícita do dono (2026-09-17). O custo de estar errado é o produto passar um
período indistinguível de um orquestrador de agentes comum. É reversível — o G3
entra depois e o piso aparece —, mas enquanto não entrar, a tese de custo não se
aplica a nenhum trabalho novo, e isso precisa estar escrito no README.

---

## 8. O que este plano deliberadamente NÃO faz

- **Não remove os workflows de exemplo.** §0.1.
- **Não inventa regras genéricas.** É o G3, e ele fica fora por decisão do dono.
- **Não acrescenta um conceito no lugar do domínio.** Nada de "preset",
  "workspace" ou "template" — renomear a partição não é removê-la.
- **Não mexe no grafo.** `consome`/`produz` e a recusa de beco sem saída já são
  a guarda, e não mudam.
- **Não deixa o catálogo aceitar bloco sem nome único.** §4.

---

## 9. Riscos

| Risco | Sintoma | Mitigação |
|---|---|---|
| Nome de bloco colidindo | a cascata depende de quem foi procurado primeiro | §4: validação do catálogo inteiro na importação |
| Quadro em branco 100% caro | todo workflow novo roda na classe AGENTE | §7, dito no README; G3 fecha |
| O chat continuar preso | fundir o catálogo mas o entrevistador manter a constante | o `CATALOGO` do grill é REMOVIDO, não ignorado |
| Perder os exemplos | alguém lê "tirar domínio" como "apagar `domains/`" | §0.1 e `test_generalidade.py` intocado |
| Agente sem validação | declaração inválida só falha ao executar | §4: o catálogo valida construindo, na importação |

---

## 10. Milestones

| M | O quê | Depende |
|---|---|---|
| **B1** | `Catalogo` plano em `registro.py`, com as duas guardas migradas | — |
| **B2** | `/api/catalogo` serve o catálogo plano; `/api/dominios` sai | B1 |
| **B3** | `Dominio` sai de `declarado.py`; `Composicao.dominio` sai | B2 |
| **B4** | O entrevistador compõe do catálogo plano; `grill.CATALOGO` sai | B2 |
| **B5** | Tela: seletor sai, paleta vira o catálogo inteiro | B2 |
| **B6** | README e spec registram a lacuna do §7 | B5 |

**B4 é o que o dono veria primeiro.** É a diferença entre "descreva uma triagem
de issues" devolver uma cascata bancária e devolver uma cascata de triagem.

---

## 11. A frase que resume

> O domínio era o jeito de dizer "estes blocos trabalham juntos" antes de o
> grafo saber dizer isso sozinho.
> O grafo sabe. O domínio é resto.
