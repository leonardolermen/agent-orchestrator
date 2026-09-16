"""O gerador de benchmark sintético, e o `Source` que o expõe.

Saiu de `cli.py` no PR #9. `build_benchmark` nunca foi código de CLI: é o
gerador do dataset com gabarito, e ele morava ali só porque a CLI foi o
primeiro chamador. A consequência era a inversão nº 3 do §2.1 — `api/app.py`
importava de `orchestrator.cli`, a camada HTTP dependendo do ponto de entrada
de linha de comando.

`SyntheticSource` é a primeira implementação de `Source`, e por enquanto a
única. Com a conciliação rebaixada a implementação de referência (§1.3), ler
OFX/CNAB saiu do escopo: quem tiver o dado escreve um `Source` de 40 linhas, e
é essa a promessa do framework.
"""

from dataclasses import dataclass
from random import Random

from orchestrator.kernel.work import WorkSet
from orchestrator.models import pool
from orchestrator.synth.dataset import Dataset, InjectionResult
from orchestrator.synth.generator import build_dataset, generate_clean_pairs
from orchestrator.synth.injectors import (
    DefasagemTemporal,
    DevolucaoFundos,
    PagamentoAgregado,
    RetencaoImposto,
)

_INJETORES_SIMPLES = [DefasagemTemporal(), RetencaoImposto(), DevolucaoFundos()]

# Fração das injeções que vira PAGAMENTO_AGREGADO — o único tipo injetado que
# L1-L3 conseguem resolver sozinhas. A taxa determinística reportada é uma
# função direta deste número, não só do dataset:
#
#   fração agregados | taxa média | mínimo  | máximo
#   0.00              | 78.1%      | 75.4%   | 80.2%
#   0.25 (valor atual)| 87.2%      | 83.0%   | 92.3%
#   0.50              | 93.2%      | 88.5%   | 96.7%
#   0.90              | 99.5%      | 98.9%   | 100.0%
# (medido em 12 sementes, n=300)
#
# Variação de 21 pontos por causa de um único literal, sem estar documentado
# em lugar nenhum antes desta nota. Qualquer taxa que este benchmark reportar
# é condicional a esta composição — não é uma propriedade do sistema medida
# no vácuo. O piso de regressão em test_cli.py (78%) coincide com a média do
# cenário 0.00: ele não pegaria a mistura de agregados cair a zero.
_FRACAO_AGREGADOS = 0.25


def build_benchmark(seed: int, n: int, taxa_divergencia: float) -> Dataset:
    """Monta um dataset com a proporção pedida de divergências."""
    # Fora de [0, 1] o alvo de injeções vira negativo ou maior que o dataset;
    # com alvo negativo o laço abaixo nunca roda e a CLI imprime "Taxa
    # determinística: 100.0%" com exit code 0 — degradação silenciosa no único
    # lugar onde um humano lê o número. Todo outro módulo deste projeto falha
    # alto em config inválida; a CLI não é exceção.
    if not 0.0 <= taxa_divergencia <= 1.0:
        raise ValueError(
            f"taxa_divergencia precisa estar entre 0.0 e 1.0: {taxa_divergencia}"
        )

    rng = Random(seed)
    pares = generate_clean_pairs(seed=seed, n=n)

    alvo = int(n * taxa_divergencia)
    injecoes: list[InjectionResult] = []
    indice = 0

    while indice < alvo and indice < len(pares):
        if rng.random() < _FRACAO_AGREGADOS and indice + 3 <= len(pares):
            lote = pares[indice : indice + 3]
            injecoes.append(PagamentoAgregado().apply_many(rng, lote))
            indice += 3
        else:
            injetor = rng.choice(_INJETORES_SIMPLES)
            injecoes.append(injetor.apply(rng, pares[indice]))
            indice += 1

    return build_dataset(pares, injecoes)


@dataclass(frozen=True)
class SyntheticSource:
    """O benchmark sintético como `Source`.

    `ref` é o que torna uma execução identificável e reproduzível. Antes do
    PR #9, a identidade de um run era a tupla `(seed, n, taxa)` — e era ela que
    escopava a fila de decisões humanas, via `dataset_id`. Um framework cujo id
    de execução é uma tupla de parâmetros de benchmark não consegue representar
    execução nenhuma que não seja um benchmark.

    O prefixo `synth:` é o que abre espaço para os outros: `file:extrato.ofx#sha256:...`,
    `erp:…`. O formato depois dos dois pontos é assunto de cada `Source`.
    """

    seed: int = 1
    n: int = 300
    taxa_divergencia: float = 0.15

    @property
    def ref(self) -> str:
        return f"synth:s{self.seed}-n{self.n}-t{self.taxa_divergencia}"

    def dataset(self) -> Dataset:
        """O dataset COM gabarito.

        Separado de `load()` de propósito: o gabarito é insumo de AVALIAÇÃO, e
        o motor não deve recebê-lo. Um `Source` de dado real não tem este
        método — e é justamente por isso que `metrics.evaluate` continua
        exigindo um `Dataset` em vez de um `Source`.
        """
        return build_benchmark(self.seed, self.n, self.taxa_divergencia)

    def load(self) -> WorkSet:
        """O que o motor recebe: só o trabalho, sem gabarito."""
        ds = self.dataset()
        return pool(ds.bank, ds.ledger)
