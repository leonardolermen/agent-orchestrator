"""A fronteira entre as camadas, imposta por teste.

Sem este arquivo, a arquitetura alvo do §4.2 é um desenho num documento, e
"não quebre as camadas" é um pedido. Com ele, é uma coisa que o CI cobra.

**Por que uma baseline e não `xfail`.** O plano original pedia um teste vermelho
listando as violações conhecidas. Vermelho desde o primeiro dia é exatamente o
que o CI deste repositório já recusou uma vez, e pelo motivo certo — ver o
comentário sobre `ruff format` em `.github/workflows/ci.yml`: "um check de
formato vermelho desde o primeiro dia é um check que as pessoas aprendem a
ignorar". A mesma frase vale aqui.

Em vez disso, a baseline é uma catraca:

  - violação NOVA          -> `test_sem_violacao_nova` falha  (regressão)
  - violação CORRIGIDA     -> `test_baseline_honesta` falha    (registre o ganho)

Os dois lados falham alto. O teste está verde hoje, e cada PR da migração o
deixa vermelho de propósito por um instante — até a baseline encolher no mesmo
commit que encolheu o acoplamento. O progresso vira diff revisável em vez de
alegação.
"""

import pytest

# Import RELATIVO, não `from tests.arquitetura.camadas import ...`.
#
# Não é estilo: o absoluto QUEBRA no CI. `tests/` não tem `__init__.py`, então
# o pytest importa este arquivo como `arquitetura.test_camadas` e coloca
# `tests/` no `sys.path` — não a raiz do repositório. Com `python -m pytest` o
# absoluto funciona por acidente (o `-m` põe o CWD no path); com `pytest tests/
# -q`, que é como o CI invoca, ele levanta ModuleNotFoundError na COLETA e
# derruba a suíte INTEIRA, não só este arquivo.
#
# Medido, não suposto: `pytest tests/ -q` saiu com "Interrupted: 1 error during
# collection" e zero testes rodados. É a mesma classe de defeito que o primeiro
# commit deste CI pegou (ver `.github/workflows/ci.yml`) — e a segunda vez que
# ela aparece neste repositório.
from .camadas import (
    DESTINO,
    PERMITIDO,
    CamadaDesconhecida,
    camada_de,
    dependencias,
    deslocados,
    modulos,
    violacoes,
)

# As 13 arestas ilegais que existem hoje, agrupadas pela CAUSA, não pelo arquivo.
#
# Uma entrada sai daqui no mesmo PR que a elimina — nunca antes, nunca depois.
# O PR anotado ao lado de cada grupo é o de `§27` do spec desta migração.
VIOLACOES_CONHECIDAS: frozenset[tuple[str, str]] = frozenset(
    {
        # ---------------------------------------------------------------
        # CAUSA 1 — tipos de domínio fora do domínio. 10 das 13 arestas, e a
        # maior das cinco. É a lacuna nº 1 do §1.2.
        #
        # O KERNEL já saiu dela: `WorkSet` e `Resolution` viraram genéricos no
        # PR #3, e `Proposal.tipo` virou `str` no PR #6. O que resta é `agent` e
        # `human` conhecendo conciliação — fecha no PR #12, com `AgentSpec` e o
        # `ToolRegistry`.
        # ---------------------------------------------------------------
        ("agent.investigator", "models"),
        ("agent.investigator", "taxonomy"),
        ("agent.investigator", "agent.tools"),
        ("eval.assinatura", "agent.tools"),
        # ENTROU no PR #3, e não é regressão — é um acoplamento que já existia
        # e estava ESCONDIDO. `eval/assinatura.py` chamava
        # `work.as_divergences()`, e como `as_divergences` morava dentro do
        # próprio `WorkSet`, a dependência de conciliação não aparecia como
        # import nenhum. Mover o método para o domínio (`models.divergencias`)
        # revelou a seta que sempre esteve lá.
        #
        # É o caso mais forte a favor da catraca: ela não só barra acoplamento
        # novo, ela acha o que o desenho antigo camuflava.
        ("eval.assinatura", "models"),
        ("review.revisor", "models"),
        ("review.decision", "taxonomy"),
        ("review.serial", "taxonomy"),
        ("metrics", "taxonomy"),
        ("metrics", "money"),
        # Esta é a mais consequente das dez: a avaliação importa o GERADOR
        # sintético, e por isso só sabe medir contra gabarito fabricado. É a
        # lacuna nº 4 do §1.2 na forma de uma seta. Fecha no PR que introduz
        # `ExpectedOutcome` com duas procedências (M6).
        ("metrics", "synth.dataset"),
        # ---------------------------------------------------------------
        # CAUSA 2 — FECHADA no PR #5. Eram 6 arestas: o motor conhecia os três
        # resolvers do domínio, e a definição conhecia o motor — a
        # circularidade do §2.1, que dois imports locais escondiam do
        # interpretador. `default_resolvers()` e `default_definition()` foram
        # para `conciliacao.py`, e `execute()` passou a EXIGIR a definição. É a
        # obrigatoriedade que quebra o ciclo: quem tem um padrão é quem conhece
        # o domínio.
        # ---------------------------------------------------------------
        # ---------------------------------------------------------------
        # CAUSA 3 — FECHADA no PR #9. `api/app.py` importava
        # `build_benchmark` de `orchestrator.cli`: a camada HTTP dependendo do
        # ponto de entrada de linha de comando. O gerador foi para
        # `synth/benchmark.py`, onde sempre deveria ter estado, e ganhou um
        # `Source` por cima — que é o que dá identidade reproduzível a uma
        # execução.
        # ---------------------------------------------------------------
        # ---------------------------------------------------------------
        # CAUSA 4 — a avaliação lê o resultado da execução em vez de um `Run`
        # do store. Fecha no PR #7 (`Run`), consumido em M6.
        #
        # Era `metrics -> matching.engine` (evaluation -> runtime). Virou
        # `metrics -> conciliacao` (evaluation -> domains) quando
        # `ReconcileResult` desceu para o domínio no PR #5. A seta mudou de
        # nome, o acoplamento é o mesmo: a avaliação depende do formato de
        # saída de quem executou, em vez de ler um `Run` persistido.
        # ---------------------------------------------------------------
        ("metrics", "conciliacao"),
        # ---------------------------------------------------------------
        # CAUSA 5 — o agente usa a fila humana como cache de idempotência.
        # É o bug latente do §6.4, não só uma seta errada: o cache é permanente
        # e sem invalidação. Fecha no PR #11, com `IdempotencyKey`.
        # ---------------------------------------------------------------
        ("agent.investigator", "review.fila"),
    }
)

# Módulos que ainda não moraram para o diretório da camada alvo.
#
# NÃO é violação de dependência — é trabalho de migração pendente, e os dois
# encolhem por PRs diferentes. Separá-los evita que um PR que só MOVE arquivo
# pareça ter consertado acoplamento, e vice-versa.
DESLOCADOS_CONHECIDOS: frozenset[str] = frozenset(DESTINO)


def _formatar(pares) -> str:
    return "\n".join(f"  {de} -> {para}" for de, para in sorted(pares))


def test_todo_modulo_tem_camada():
    """Nenhum módulo sem camada atribuída.

    Um arquivo novo precisa custar uma decisão explícita. Sem este teste, ele
    entraria sem camada, sem violação e sem fronteira — e o contrato deixaria
    de valer para ele sem ninguém perceber.
    """
    sem_camada = []
    for modulo in modulos():
        try:
            camada_de(modulo)
        except CamadaDesconhecida:
            sem_camada.append(modulo)
    assert not sem_camada, (
        "módulos sem camada atribuída:\n  "
        + "\n  ".join(sem_camada)
        + "\n\nAtribua uma em `DESTINO` (tests/arquitetura/camadas.py) ou mova "
        "o arquivo para o diretório da camada."
    )


def test_extrator_enxerga_import_local_e_type_checking():
    """O extrator não pode olhar só o topo do arquivo.

    Dois acoplamentos reais deste repositório existem SOMENTE em formas que um
    extrator ingênuo não veria, e os dois são usados aqui como fixture porque
    são fatos verificáveis do código de hoje:

      - `conciliacao -> review.revisor` existe só DENTRO de
        `default_definition()`. Depois do PR #5 o import local não esconde mais
        circularidade nenhuma (`domains` pode importar `human`), mas continua
        sendo um import que só um extrator que percorre a árvore inteira vê.
      - `agent.investigator -> review.fila` existe só sob `TYPE_CHECKING`. Não
        há acoplamento em tempo de execução — mas há acoplamento de
        CONHECIMENTO, e é isso que uma fronteira de arquitetura mede.

    Se este teste falhar porque um dos dois imports mudou de forma, ótimo: o
    que ele protege é a capacidade de ver, e a fixture pode ser trocada. O que
    não pode é o extrator voltar a ler só o cabeçalho.
    """
    arestas = {(d.de, d.para) for d in dependencias()}
    assert ("conciliacao", "review.revisor") in arestas, (
        "o extrator perdeu um import DENTRO de função — foi exatamente onde a "
        "circularidade `engine <-> definition` se escondia até o PR #5"
    )
    assert ("agent.investigator", "review.fila") in arestas, (
        "o extrator perdeu um import sob TYPE_CHECKING — acoplamento de "
        "conhecimento também é acoplamento"
    )


def test_sem_violacao_nova():
    """Nenhuma dependência ilegal além das que já conhecíamos.

    Este é o lado da catraca que impede a arquitetura de piorar enquanto é
    reescrita — que é exatamente a janela em que ela pioraria.
    """
    atuais = {(d.de, d.para) for d in violacoes()}
    novas = atuais - VIOLACOES_CONHECIDAS
    assert not novas, (
        f"{len(novas)} dependência(s) ilegal(is) nova(s):\n"
        + _formatar(novas)
        + "\n\nA arquitetura alvo está no §4.2 do spec de migração. Se a "
        "dependência for legítima, o que está errado é a tabela `PERMITIDO` — "
        "e mudá-la é uma decisão de arquitetura, não um ajuste de teste."
    )


def test_baseline_honesta():
    """A baseline não lista violação que já foi corrigida.

    Falha quando um PR conserta um acoplamento sem apagar a linha
    correspondente. É proposital: obriga o ganho a aparecer no diff, em vez de
    ficar escondido atrás de uma lista que só cresce. Sem este lado, a baseline
    viraria uma lista de desculpas permanentes.
    """
    atuais = {(d.de, d.para) for d in violacoes()}
    resolvidas = VIOLACOES_CONHECIDAS - atuais
    assert not resolvidas, (
        f"{len(resolvidas)} violação(ões) da baseline não existe(m) mais:\n"
        + _formatar(resolvidas)
        + "\n\nApague-a(s) de `VIOLACOES_CONHECIDAS`, no MESMO commit que a(s) "
        "corrigiu. Faltam "
        f"{len(atuais)} para o alvo."
    )


def test_kernel_nao_importa_nada_fora_do_kernel():
    """A regra nº 1 do §4.2, com teste próprio e nome próprio.

    Ela já está coberta por `test_sem_violacao_nova`, mas ali falharia com uma
    mensagem genérica sobre camadas. Esta é a invariante da qual tudo o mais
    depende — `kernel` sem dependência é o que torna a extração barata — e
    quando ela quebrar, a falha precisa dizer isso pelo nome.
    """
    fora = [d for d in violacoes() if d.de_camada == "kernel"]
    conhecidas = {(d.de, d.para) for d in fora} & VIOLACOES_CONHECIDAS
    inesperadas = [d for d in fora if (d.de, d.para) not in conhecidas]
    assert not inesperadas, (
        "o kernel passou a importar de fora do kernel:\n"
        + "\n".join(f"  {d}" for d in inesperadas)
    )


def test_deslocados_apenas_os_conhecidos():
    """Nenhum módulo novo nasce fora do diretório da sua camada.

    A migração move os antigos; ela não autoriza os novos a nascerem no lugar
    errado.
    """
    atuais = {m for m, _ in deslocados()}
    novos = atuais - DESLOCADOS_CONHECIDOS
    assert not novos, (
        "módulos novos fora do diretório da camada alvo:\n  "
        + "\n  ".join(sorted(novos))
        + "\n\nCrie o arquivo já no diretório da camada."
    )


def test_destino_sem_entrada_redundante():
    """Higiene: `DESTINO` não guarda módulo que já está no lugar certo.

    Quando um módulo é movido para o diretório da sua camada, a entrada em
    `DESTINO` passa a ser ruído — e ruído numa tabela que é o contrato da
    migração é como a tabela para de ser lida. A tabela precisa encolher até
    sumir; este teste é o que garante que ela encolha.
    """
    redundantes = [m for m in DESTINO if m.split(".")[0] in PERMITIDO and "." in m]
    redundantes = [
        m for m in redundantes if m.split(".")[0] == DESTINO[m]
    ]
    assert not redundantes, (
        "entradas redundantes em `DESTINO` (o diretório já responde):\n  "
        + "\n  ".join(sorted(redundantes))
    )


def test_destino_sem_entrada_orfa():
    """Higiene: `DESTINO` não guarda módulo que não existe mais.

    Escrito DEPOIS de o PR #2 deixar `workflow.cost_class` órfão na tabela sem
    que nenhum dos 19 testes reclamasse. Entrada órfã é pior que ruído: ela
    infla `DESLOCADOS_CONHECIDOS`, e um módulo novo criado no lugar errado com
    um nome que por acaso já esteve ali entraria sem ninguém ver.
    """
    existentes = set(modulos())
    orfas = sorted(set(DESTINO) - existentes)
    assert not orfas, (
        "entradas em `DESTINO` para módulos que não existem:\n  "
        + "\n  ".join(orfas)
        + "\n\nApague-a(s) no mesmo commit que removeu o módulo."
    )


@pytest.mark.parametrize("camada", sorted(PERMITIDO))
def test_permitido_nao_referencia_camada_inexistente(camada: str):
    """A tabela não pode citar uma camada que não existe.

    Um erro de digitação em `PERMITIDO` — `"kernell"` — afrouxaria a regra em
    silêncio, porque nada importaria de uma camada inexistente e nenhuma
    violação apareceria.
    """
    desconhecidas = PERMITIDO[camada] - set(PERMITIDO)
    assert not desconhecidas, (
        f"camada {camada!r} permite importar de camada inexistente: "
        f"{sorted(desconhecidas)}"
    )
