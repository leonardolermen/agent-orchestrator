"""O mapa de camadas e o extrator de imports.

Separado do arquivo de teste porque é DADO, não asserção: a tabela de camadas
permitidas é a arquitetura alvo escrita uma vez, e três testes diferentes a
consultam. Misturar os dois faria a tabela ser lida como detalhe de um teste
em vez de como o contrato que ela é.

Ver `docs/superpowers/specs/2026-09-16-runtime-de-orquestracao-design.md`, §4.2.
"""

import ast
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2] / "src" / "orchestrator"

# A tabela da §4.2. Cada camada lista o que PODE importar, além de si mesma.
#
# Duas ausências deliberadas, e são o ponto inteiro do desenho:
#   - `kernel` não importa nada. Nem domínio, nem agente, nem pydantic.
#   - NINGUÉM importa `domains`. Se uma camada precisar, o conceito está na
#     camada errada — foi exatamente o defeito que os PRs #3 e #5 fecharam.
_BORDA = frozenset(
    {
        "kernel", "runtime", "storage", "observability", "agent", "human",
        "crew", "evaluation", "domains", "authoring",
    }
)

PERMITIDO: dict[str, frozenset[str]] = {
    "kernel": frozenset(),
    "runtime": frozenset({"kernel"}),
    "storage": frozenset({"kernel"}),
    "observability": frozenset({"kernel", "storage"}),
    "agent": frozenset({"kernel", "runtime"}),
    "human": frozenset({"kernel", "storage"}),
    "crew": frozenset({"kernel", "agent"}),
    "evaluation": frozenset({"kernel", "storage", "observability"}),
    "domains": frozenset(
        {"kernel", "runtime", "agent", "human", "crew", "evaluation", "storage"}
    ),
    "authoring": frozenset({"kernel", "runtime", "domains", "agent", "human"}),
    # Bordas: podem importar tudo. São elas que compõem o produto final.
    "api": _BORDA,
    "cli": _BORDA,
    # A FACHADA pública (`orchestrator/__init__.py`): o que alguém importa sem
    # ler o código. Pode alcançar qualquer camada, e NINGUÉM interno pode
    # importá-la — código interno importa o módulo de verdade. Há teste.
    "public": _BORDA,
}

# Onde cada módulo de HOJE deveria morar na arquitetura alvo.
#
# Esta tabela existe porque a migração ainda não aconteceu: o diretório de hoje
# (`matching/`, `review/`, `grill/`) não é o diretório alvo (`domains/`,
# `human/`, `authoring/`). Ela ENCOLHE a cada PR — quando um módulo chega ao
# diretório certo, a entrada sai daqui e o nome do diretório passa a responder
# sozinho (ver `camada_de`).
#
# Uma entrada aqui é uma AFIRMAÇÃO de projeto, não uma observação. "Onde isto
# deveria estar", não "onde está".
DESTINO: dict[str, str] = {
    # --- núcleo ---
    # O pacote `workflow/` deixou de existir no PR #5: `cost_class` virou
    # `kernel/cost.py` (PR #2), `workset` virou `kernel/work.py` (PR #3), e
    # `resolver`/`definition` foram para `kernel/`. O diretório responde por
    # todos — não há mais entrada aqui.
    # `agent.proposal` sumiu no PR #6: `Proposal`, `Confidence`, `TraceEvent` e
    # `TraceKind` foram para `kernel/resolution.py`, e `Proposal.tipo` deixou de
    # ser `DivergenceType` para ser `str`. Foi a generalização que os domínios
    # esqueleto exigiram — e que nenhuma análise prévia tinha previsto.
    # --- runtime ---
    # `matching.engine` virou `runtime/engine.py` no PR #5. Diretório responde.
    # --- agente: o laço genérico e a costura do modelo ---
    # `agent.llm`, `agent.anthropic_client` e `agent.investigator` NÃO aparecem
    # aqui: o diretório `agent/` já é o nome da camada e responde sozinho. Só
    # entram nesta tabela os dois vizinhos deles que vão para OUTRA camada —
    # `agent.proposal` (kernel, acima) e `agent.tools` (domains, abaixo).
    # --- humano ---
    "review.decision": "human",
    "review.fila": "human",
    "review.revisor": "human",
    "review.serial": "human",
    # --- avaliação ---
    "metrics": "evaluation",
    # `replay.py` e `assinatura.py` moram em `eval/` por PROPÓSITO de uso, mas
    # são implementações de `LLMClient` e de `Resolver` — a camada é dada pelo
    # que a coisa É, não por quem a usa. Mapeá-las para `evaluation` produziria
    # violações falsas (`evaluation -> agent`) que nenhum PR deveria fechar,
    # porque não há nada errado ali.
    "eval.replay": "agent",
    "eval.assinatura": "agent",
    # --- domínios ---
    # `domains/procurement` e `domains/swe` NÃO aparecem aqui: o diretório
    # `domains/` já é o nome da camada. A conciliação ainda está espalhada pela
    # raiz do pacote e por isso precisa das entradas abaixo — ela se muda para
    # `domains/reconciliation/` num PR próprio, que é rename puro.
    #
    # --- conciliação (§1.3: implementação de referência) ---
    "models": "domains",
    "money": "domains",
    "dates": "domains",
    "tax": "domains",
    "taxonomy": "domains",
    # A cascata padrão e a porta do domínio. `conciliacao/workflow.py` é o que
    # quebrou a circularidade `engine <-> definition`: a definição padrão é
    # configuração de produto, e só a camada `domains` pode conhecer motor E
    # resolvers.
    #
    # Virou PACOTE no M2: `agent/tools.py` guardava as ferramentas DE
    # CONCILIAÇÃO dentro do pacote do agente genérico, e ocupava o nome que o
    # `ToolRegistry` precisava. As duas coisas se resolvem com o mesmo mover.
    "conciliacao": "domains",
    "conciliacao.workflow": "domains",
    "conciliacao.ferramentas": "domains",
    "conciliacao.politica": "domains",
    "matching.exact": "domains",
    "matching.tolerance": "domains",
    "matching.grouping": "domains",
    # `build_benchmark` saiu de `cli.py` no PR #9. Nunca foi codigo de CLI: e o
    # gerador do dataset com gabarito, e morava la so porque a CLI foi o
    # primeiro chamador. Era a inversao nº 3 do §2.1 — a camada HTTP importando
    # do ponto de entrada de linha de comando.
    "synth.benchmark": "domains",
    "synth.dataset": "domains",
    "synth.generator": "domains",
    "synth.injectors": "domains",
    # --- autoria de workflow (hoje `grill/`) ---
    # `workflows.py` é o REGISTRO: de um id para uma definição executável.
    # Fica em `authoring` porque precisa conhecer as duas fontes — o embutido
    # (`conciliacao`, domains) e os gerados pelo grill (authoring) —, e
    # `authoring` é a camada que pode importar as duas. Saiu de `api/app.py`
    # no PR #8: quais workflows existem não é assunto da camada HTTP, e a CLI
    # precisa da mesma resposta.
    # A fachada pública.
    "__init__": "public",
    "workflows": "authoring",
    "grill.catalogo": "authoring",
    "grill.receita": "authoring",
    "grill.registro": "authoring",
    "grill.ferramentas": "authoring",
    "grill.entrevistador": "authoring",
    "grill.prompt": "authoring",
    "grill.assinatura": "authoring",
    # --- bordas ---
    # `cli/` virou PACOTE no M5 (despachante de subcomandos), então o diretório
    # responde por ele. `api.app`/`api.schemas` também não aparecem — `api/` já
    # é o nome da camada.
    "grill.cli": "cli",
    "eval.agent_eval": "cli",
}


@dataclass(frozen=True)
class Dependencia:
    """Um import de um módulo do projeto para outro."""

    de: str
    de_camada: str
    para: str
    para_camada: str
    linha: int

    def __str__(self) -> str:
        return (
            f"{self.de} [{self.de_camada}] -> {self.para} [{self.para_camada}] "
            f"(linha {self.linha})"
        )


class CamadaDesconhecida(Exception):
    """Um módulo sem camada atribuída.

    Levanta em vez de escolher um default, e a razão é a mesma do
    `_construir_definicao` da API: um default silencioso aqui faria um arquivo
    novo entrar sem camada e sem violação, e a fronteira deixaria de valer para
    ele sem ninguém perceber. Arquivo novo tem que custar uma decisão.
    """


def modulos() -> list[str]:
    """Todo módulo de `src/orchestrator`, com o prefixo do pacote removido.

    `__init__.py` vazio não entra: ele não tem import nem lugar na arquitetura,
    e contá-lo só produziria entradas mortas no `DESTINO`.
    """
    achados = []
    for caminho in sorted(RAIZ.rglob("*.py")):
        relativo = caminho.relative_to(RAIZ)
        if relativo.name == "__init__.py":
            if not caminho.read_text(encoding="utf-8").strip():
                continue
            # O `__init__.py` da RAIZ do pacote não tem parte nenhuma antes
            # dele, e `".".join(())` daria nome vazio. Ele é a fachada pública,
            # e precisa de nome para poder ter camada.
            partes = relativo.parts[:-1] or ("__init__",)
        else:
            partes = (*relativo.parts[:-1], relativo.stem)
        achados.append(".".join(partes))
    return achados


def camada_de(modulo: str) -> str:
    """A camada alvo de um módulo.

    Duas fontes, nesta ordem:
      1. A tabela `DESTINO` — uma afirmação explícita de projeto.
      2. O DIRETÓRIO, quando ele já é o nome de uma camada. É o estado final:
         `kernel/work.py` responde sozinho, sem tabela.

    O explícito vence o implícito, e não é preferência estética: TRÊS diretórios
    de hoje têm o nome de uma camada alvo sem serem ela — `agent/` guarda
    `proposal.py` (kernel) e `tools.py` (domains) junto do laço; `api/` e `cli`
    coincidem. Com a ordem invertida, `agent.proposal` resolvia como camada
    `agent`, a violação `kernel -> agent` (a inversão nº 1 do §2.1) sumia do
    relatório, e o teste passava a atestar uma arquitetura que não existe.
    Medido: com a ordem errada, 36 violações e a mais importante entre as
    ausentes.

    Quando um módulo chega ao diretório certo, sua entrada em `DESTINO` vira
    redundante — e `test_destino_sem_entrada_redundante` obriga a removê-la, de
    modo que a tabela encolhe sozinha até desaparecer.
    """
    if modulo in DESTINO:
        return DESTINO[modulo]
    topo = modulo.split(".")[0]
    if topo in PERMITIDO:
        return topo
    raise CamadaDesconhecida(
        f"módulo sem camada: {modulo!r}. Atribua uma em `DESTINO` "
        f"(tests/arquitetura/camadas.py) ou mova o arquivo para o diretório "
        f"da camada. Camadas: {sorted(PERMITIDO)}"
    )


def _alvo(no: ast.AST, modulo_atual: str) -> list[tuple[str, int]]:
    """Os módulos de `orchestrator` que este nó de import referencia."""
    if isinstance(no, ast.Import):
        return [
            (a.name.removeprefix("orchestrator."), no.lineno)
            for a in no.names
            if a.name.startswith("orchestrator.")
        ]
    if isinstance(no, ast.ImportFrom):
        # `from . import x` / `from .fila import y`: o repo não usa imports
        # relativos hoje, mas se usar, resolvê-los errado produziria um mapa
        # falso — e mapa falso é pior que mapa ausente.
        if no.level:
            raise NotImplementedError(
                f"import relativo em {modulo_atual} (linha {no.lineno}); "
                f"este extrator só entende imports absolutos"
            )
        if no.module and no.module.startswith("orchestrator"):
            return [(no.module.removeprefix("orchestrator.").lstrip("."), no.lineno)]
    return []


def dependencias() -> list[Dependencia]:
    """Todos os imports internos do projeto, com a camada dos dois lados.

    Percorre a árvore INTEIRA (`ast.walk`), não só o topo do arquivo. É
    obrigatório: a circularidade `engine <-> definition` vive em imports
    DENTRO de função, colocados lá justamente para escondê-la do interpretador.
    Um extrator que olhasse só o topo não veria o acoplamento mais antigo do
    repositório.
    """
    achadas: list[Dependencia] = []
    for modulo in modulos():
        arquivo = RAIZ / (modulo.replace(".", "/") + ".py")
        if not arquivo.exists():
            arquivo = RAIZ / modulo.replace(".", "/") / "__init__.py"
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=str(arquivo))
        origem = camada_de(modulo)
        for no in ast.walk(arvore):
            for destino, linha in _alvo(no, modulo):
                if destino == modulo:
                    continue
                achadas.append(
                    Dependencia(
                        de=modulo,
                        de_camada=origem,
                        para=destino,
                        para_camada=camada_de(destino),
                        linha=linha,
                    )
                )
    return achadas


def violacoes() -> list[Dependencia]:
    """As dependências que a arquitetura alvo não permite."""
    return [
        d
        for d in dependencias()
        if d.para_camada != d.de_camada
        and d.para_camada not in PERMITIDO[d.de_camada]
    ]


def deslocados() -> list[tuple[str, str]]:
    """Módulos cujo diretório ainda não é o da camada alvo: `(módulo, camada)`.

    Não é violação de dependência — é trabalho de migração pendente. Os dois
    encolhem por PRs diferentes, e misturá-los faria um PR que só MOVE arquivo
    parecer que consertou acoplamento.
    """
    return [(m, camada_de(m)) for m in modulos() if m.split(".")[0] not in PERMITIDO]
