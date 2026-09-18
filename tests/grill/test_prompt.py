"""O system prompt da entrevista é do quadro em branco, não da conciliação.

Um modelo de verdade revelou o que nenhum cliente falso poderia: com a chave
ligada, a entrevista recusou "triar issues de software" dizendo que o escopo
"desta esteira" era conciliação bancária — e apontou, na mesma resposta, que o
`triador` existia no catálogo. O modelo obedecia ao prompt: a fatia do quadro
em branco achatou o catálogo que o chat compõe, e deixou o prompt para trás.
"""

from orchestrator.grill.prompt import SYSTEM


def test_o_prompt_nao_nomeia_a_conciliacao_como_escopo():
    """Frágil de propósito: é exatamente a frase que fez um modelo recusar um
    caso que o catálogo resolvia. Se alguém precisar citar conciliação no
    prompt de novo, que seja como EXEMPLO, e este teste vai obrigar a dizer
    por quê."""
    assert "conciliação" not in SYSTEM.lower()
    assert "extrato" not in SYSTEM.lower()


def test_o_prompt_diz_que_o_CATALOGO_e_a_unica_verdade():
    """A regra que substitui o escopo fixo: se um bloco do catálogo serve, o
    domínio do parceiro não importa; se nenhum serve, `fora_do_catalogo`."""
    assert "catálogo" in SYSTEM.lower()
    assert "fora_do_catalogo" in SYSTEM


def test_o_custo_e_dito_por_CLASSE_e_nao_por_um_agente_nomeado():
    """'o agente investigador gasta' era verdade quando ele era o único agente.
    Com `triador` e `buscador` no catálogo, a frase certa é por classe."""
    assert "investigador" not in SYSTEM.lower()
    assert "AGENTE" in SYSTEM
