"""O investigador movido a assinatura, usado só para avaliação.

Nada aqui chama o modelo: o laço real exige um processo local do Claude Code e
gasta os limites da assinatura. O que estes testes pinam são as costuras — que
o resolver entra na cascata como qualquer outro, que ele declara que o custo
dele NÃO é mensurável, e que importar o módulo não exige o SDK instalado.
"""

import subprocess
import sys
import textwrap

from orchestrator.domains.reconciliation.agent.ferramentas import ToolContext
from orchestrator.domains.reconciliation.synth.generator import generate_clean_pairs
from orchestrator.kernel.cost import CostClass


def _contexto() -> ToolContext:
    pares = generate_clean_pairs(seed=2, n=3)
    return ToolContext(bank=[p.bank for p in pares], ledger=[p.ledger for p in pares])


def test_importar_o_modulo_nao_exige_o_sdk_instalado():
    """Mesma regra do cliente da Anthropic: o import do SDK é preguiçoso.

    Sem isso, quem não instalar o extra `[assinatura]` não consegue nem
    coletar a suíte — e o extra existe justamente para o núcleo não depender
    do Claude Code.

    Roda em subprocesso com o pacote BLOQUEADO, porque `sys.modules` é estado
    do processo inteiro: um teste anterior que importe o SDK faria uma
    verificação in-process passar por engano.
    """
    codigo = textwrap.dedent(
        """
        import sys

        class Bloqueio:
            def find_spec(self, nome, caminho=None, alvo=None):
                if nome.split(".")[0] == "claude_agent_sdk":
                    raise ImportError("bloqueado de propósito")
                return None

        sys.meta_path.insert(0, Bloqueio())
        import orchestrator.eval.assinatura as m
        print(m.InvestigadorAssinatura.__name__)
        """
    )

    r = subprocess.run(
        [sys.executable, "-c", codigo], capture_output=True, text=True
    )

    assert r.returncode == 0, r.stderr
    assert "InvestigadorAssinatura" in r.stdout


def test_e_um_resolver_da_classe_agente():
    from orchestrator.eval.assinatura import InvestigadorAssinatura

    inv = InvestigadorAssinatura(context=_contexto())

    assert inv.name == "investigador"
    assert inv.cost_class is CostClass.AGENTE
    d = inv.describe()
    assert (d.name, d.cost_class) == (inv.name, inv.cost_class)
    assert d.summary


def test_declara_que_o_proprio_custo_nao_e_mensuravel():
    """A distinção que o resto do projeto depende de não perder.

    `cost_by_resolver` usa chave ausente para "não rodou" e `Cost.zero()` para
    "rodou e foi de graça". Uma execução por assinatura não é nenhuma das
    duas: ela custa, só não tem preço por chamada. Sem esta flag, o relatório
    imprimiria US$ 0,00 — que é exatamente o modo de falha que a avaliação já
    cometeu uma vez, relatando falha total como medição.
    """
    from orchestrator.eval.assinatura import InvestigadorAssinatura

    assert InvestigadorAssinatura(context=_contexto()).custo_mensuravel is False
