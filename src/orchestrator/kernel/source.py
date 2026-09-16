"""De onde o trabalho vem, e como essa origem é nomeada.

Até o PR #9 não havia abstração de entrada: `build_benchmark(seed, n, taxa)`
era chamado direto pela CLI, pela API e pela avaliação. Duas consequências, e a
segunda é a que importa:

1. `api/app.py` importava de `orchestrator.cli` — a camada HTTP dependendo do
   ponto de entrada de linha de comando (inversão nº 3 do §2.1).
2. A **identidade** de uma execução era a tupla `(seed, n, taxa)`, e era ela
   que escopava a fila de decisões humanas (`dataset_id`). Um framework cujo id
   de execução é uma tupla de parâmetros de benchmark não consegue representar
   execução nenhuma que não seja um benchmark — e um domínio novo não tem de
   onde receber trabalho sem inventar um segundo `build_benchmark`.

Com a conciliação rebaixada a implementação de referência (§1.3), ler OFX/CNAB
saiu do escopo. O que entra é a costura: quem tiver o dado escreve um `Source`
de 40 linhas, e é essa a promessa do framework.
"""

from typing import Protocol

from orchestrator.kernel.work import WorkSet


class Source(Protocol):
    """Uma origem de trabalho, com identidade reproduzível.

    `ref` é o `input_ref` que vai para o `Run`. Ele precisa ser ESTÁVEL: duas
    execuções sobre a mesma entrada precisam produzir o mesmo `ref`, ou o
    `ReplayResume` (M7) não consegue casar as decisões humanas já tomadas com o
    trabalho de agora.

    Convenção do prefixo: `synth:`, `file:`, `erp:`. O que vem depois dos dois
    pontos é assunto de cada implementação — para um arquivo, o caminho mais um
    hash do conteúdo; para um benchmark, os parâmetros.

    `load()` devolve SÓ o trabalho. Gabarito, quando existe, não passa por aqui:
    ele é insumo de avaliação, e o motor não deve recebê-lo. Ver
    `SyntheticSource.dataset()`, que é o método que os `Source` de dado real
    não têm.
    """

    @property
    def ref(self) -> str: ...

    def load(self) -> WorkSet: ...
