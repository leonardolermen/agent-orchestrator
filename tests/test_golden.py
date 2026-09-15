"""O refactor da cascata não pode mudar um dígito.

Os outros testes de taxa afirmam PISOS. Piso não pega refactor que mexe nos
números para cima — e mudança silenciosa para cima é tão errada quanto para
baixo, porque significa que o motor passou a casar coisa que não casava.
"""

import json
from pathlib import Path

from golden.gerar import CAMINHO, medir

MENSAGEM = (
    "A medição mudou. Se você NÃO mexeu na lógica de matching, o refactor está "
    "errado — conserte o código, não o golden. Se você mexeu DE PROPÓSITO, "
    "regenere com `python tests/golden/gerar.py` e explique a mudança no corpo "
    "do commit, número por número."
)


def test_golden_existe():
    assert Path(CAMINHO).exists(), (
        f"golden não encontrado em {CAMINHO}; gere com "
        f"`python tests/golden/gerar.py` ANTES de qualquer refactor"
    )


def test_medicao_reproduz_o_golden_digito_a_digito():
    esperado = json.loads(Path(CAMINHO).read_text(encoding="utf-8"))
    obtido = medir()
    assert obtido == esperado, MENSAGEM
