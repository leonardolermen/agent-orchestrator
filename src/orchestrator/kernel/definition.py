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
from dataclasses import dataclass

from orchestrator.kernel.resolver import Resolver


@dataclass(frozen=True)
class Stage:
    name: str
    cascade: tuple[Resolver, ...]

    def ordered(self) -> list[Resolver]:
        """A cascata na ordem em que roda.

        `sorted` é estável: a ordem entre classes de custo é derivada, a ordem
        dentro de uma classe é a que o autor da definição escreveu.
        """
        return sorted(self.cascade, key=lambda r: r.cost_class)


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
        bruto = json.dumps(forma, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:12]
