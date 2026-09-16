"""A definição de workflow: o objeto que o motor executa E que a API serializa.

**Zero conhecimento de domínio, desde o PR #5.** Este módulo trazia
`default_definition()` — a cascata de conciliação — e por causa dela importava
o motor (para `default_resolvers`) e o pacote `review` (para o revisor). Eram
quatro das arestas ilegais da CAUSA 2, e a circularidade `engine <-> definition`
que dois imports locais escondiam. A definição PADRÃO é configuração de
produto, não parte do kernel: ela mora em `conciliacao.py`.

Que seja o MESMO objeto nos dois lados é o ponto. Uma definição declarativa
paralela, que descrevesse o que o motor faz, permitiria drift entre o desenho
e a execução — e um desenho que não corresponde ao motor é a decoração que o
§3.5 do spec de composição nomeia como modo de falha.
"""

import hashlib
import json
from dataclasses import dataclass, field

from orchestrator.kernel.policy import ExecutionPolicy
from orchestrator.kernel.resolver import Resolver


@dataclass(frozen=True)
class Stage:
    name: str
    cascade: tuple[Resolver, ...]
    # A política deste stage. O default reproduz EXATAMENTE o comportamento
    # anterior ao M3: teto na classe mais cara, autonomia PROPOR, sem predicado
    # e sem razão de custo. É por isso que o motor de política entra sem mudar
    # um único número.
    policy: "ExecutionPolicy" = field(default_factory=lambda: ExecutionPolicy())

    def ordered(self) -> list[Resolver]:
        """A cascata na ordem em que roda.

        `sorted` é estável: a ordem entre classes de custo é derivada, a ordem
        dentro de uma classe é a que o autor da definição escreveu.
        """
        return sorted(self.cascade, key=lambda r: r.cost_class)


def Task(  # noqa: N802 — é um construtor, e o nome é o do conceito
    name: str,
    *,
    resolver: Resolver | None = None,
    cascade: tuple[Resolver, ...] | list[Resolver] | None = None,
    policy: ExecutionPolicy | None = None,
) -> Stage:
    """Açúcar: `Task(resolver=x)` é `Stage(cascade=(x,))`.

    NÃO é um conceito novo, e a ausência dele é deliberada. O spec de composição
    §1.2 diz textualmente que passo simples e cascata "não são dois conceitos; é
    um" — criar `Task` como entidade separada duplicaria estado, duplicaria
    serialização e criaria a pergunta "uma task tem stages ou um stage tem
    tasks?", que não tem resposta boa.

    Existe para que quem chega do CrewAI encontre a palavra que espera, sem que
    o kernel ganhe um segundo conceito para manter em sincronia.
    """
    if (resolver is None) == (cascade is None):
        raise ValueError("Task exige `resolver` OU `cascade`, exatamente um")
    return Stage(
        name=name,
        cascade=(resolver,) if resolver else tuple(cascade),
        policy=policy or ExecutionPolicy(),
    )


@dataclass(frozen=True)
class WorkflowDefinition:
    id: str
    name: str
    stages: tuple[Stage, ...]

    @property
    def version(self) -> str:
        """sha256 curto da FORMA da cascata. Derivado, nunca escrito à mão.

        O spec de composição §4.2 exige "versão imutável, execução fixa a
        versão", e `Run.workflow_version` é onde ela é fixada. Número escrito à
        mão é número que desatualiza em silêncio — a mesma razão de `_param()`
        ler o default do próprio dataclass no catálogo do grill.

        **Limite conhecido, e é real.** A forma é `(id, nome do stage, nome e
        classe de cada resolver, na ordem de execução)`. Trocar um PARÂMETRO —
        `L2(max_cents=5)` para `L2(max_cents=20)` — não muda a versão, porque o
        kernel não tem como introspectar parâmetro de resolver genericamente.
        Fechar isso exige `Resolver.version`, que é o PR #11 (a mesma peça que
        a chave de idempotência precisa). Até lá, esta versão responde "a
        cascata mudou de forma?", não "a cascata mudou?".
        """
        forma = [
            self.id,
            [
                [s.name, [[r.name, int(r.cost_class)] for r in s.ordered()]]
                for s in self.stages
            ],
        ]
        # A POLÍTICA não entra na versão, e é deliberado: ela é variável de
        # EXPERIMENTO (§14.4). Rodar o mesmo workflow com duas políticas tem de
        # produzir a mesma `workflow_version`, ou o benchmark compararia dois
        # workflows em vez de duas políticas. A política vai no `Run`, por
        # `PolicyDecision`, que é onde ela é observável.
        bruto = json.dumps(forma, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:12]
