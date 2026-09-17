"""As guardas que impedem as telas de olharem para a fila errada.

**O que mudou, e por que metade destes testes encolheu.** Até a migração para
um frontend só havia três páginas — `index.html`+`canvas.js`, `fila.html`+
`fila.js` e o app React — e elas precisavam CONCORDAR sobre qual workflow e
qual dataset estavam olhando. A coordenação dependia de cada arquivo ler a
mesma query string com os mesmos defaults, e o `DECISOES.md` registra que essa
promessa quebrou DUAS vezes: uma com `n=300` contra `n=30`, outra com `fila.js`
fixando `workflow` em "conciliacao" enquanto o canvas apontava para outro id.

Havia um teste aqui que COMPARAVA os dois arquivos, porque duas asserções
independentes passariam mesmo com os defaults divergindo. Ele não existe mais:
com uma aplicação só, `parametrosDaUrl` é declarada UMA vez e as duas vistas a
importam. A divergência deixou de ser algo a testar e passou a ser algo que não
se consegue escrever — que é o desfecho melhor.

O que NÃO encolheu é a outra metade do defeito, e ela continua viva: declarar o
default certo e mesmo assim chamar `/api/fila/conciliacao` fixo. Isso ainda é
possível, então ainda é testado.
"""

import re
from pathlib import Path

FONTE = Path(__file__).resolve().parents[2] / "web-app" / "src"

# Linhas de comentário saem antes de procurar rotas: `api.ts` menciona
# `/api/fila/{workflow_id}` em prosa, entre crases, para explicar que o id é
# segmento de PATH e o dataset é query — texto que não é código e não pode
# contar como uso. A versão anterior deste arquivo já trazia esta guarda, pelo
# mesmo motivo; removê-la ao reescrever a fez falhar na primeira execução.
_COMENTARIO = re.compile(r"^\s*//.*$", re.MULTILINE)
_ROTA = re.compile(r"`(/api/(?:fila|workflows)/[^`]*)`")


def test_a_URL_e_a_unica_fonte_dos_parametros():
    """Uma constante local com default próprio foi o que fez as telas
    apontarem para datasets diferentes."""
    fila = (FONTE / "Fila.tsx").read_text(encoding="utf-8")

    assert "location.search" in fila
    assert "conciliacao" in fila


def test_os_defaults_sao_declarados_UMA_vez_so():
    """A prova de que a divergência virou impossível, e não só improvável.

    `parametrosDaUrl` é exportada de um módulo e importada pelas outras
    vistas. Se alguém reintroduzir uma cópia — outra função que leia
    `location.search` e invente os próprios defaults —, este teste fica
    vermelho antes de a cópia divergir, que é o único momento barato de pegar.
    """
    definicoes = [
        f.name
        for f in FONTE.glob("*.tsx")
        if "export function parametrosDaUrl" in f.read_text(encoding="utf-8")
    ]

    assert definicoes == ["Fila.tsx"], definicoes

    execucao = (FONTE / "Execucao.tsx").read_text(encoding="utf-8")
    assert "parametrosDaUrl" in execucao
    assert 'from "./Fila"' in execucao


def test_TODA_rota_de_workflow_interpola_o_id():
    """O defeito real que este arquivo existe para constranger.

    Ele não estava na declaração: `fila.js` declarava o default certo e mesmo
    assim chamava `/api/fila/conciliacao` fixo. Com a declaração correta no
    lugar, fixar a URL de volta deixava a suíte inteira verde — inclusive no
    POST de decisão, que é a metade que grava decisão humana na trilha de
    auditoria de OUTRO workflow.

    Por isso a asserção é sobre o USO: toda rota que carrega um id de workflow
    precisa interpolar a variável, nunca um literal.
    """
    api = _COMENTARIO.sub("", (FONTE / "api.ts").read_text(encoding="utf-8"))
    rotas = _ROTA.findall(api)

    assert len(rotas) >= 4, rotas
    for rota in rotas:
        assert "${" in rota, f"rota com id fixo: {rota}"
    # As duas metades da fila precisam existir: ler e DECIDIR. Sem esta
    # checagem, interpolar só o GET e fixar o POST passaria pelas asserções
    # acima — e é o POST que grava decisão humana.
    da_fila = [r for r in rotas if r.startswith("/api/fila/")]
    assert sorted("/decisao" in r for r in da_fila) == [False, True], da_fila


def test_o_seletor_de_workflow_existe():
    """A vista de execução navega entre workflows salvos — é o outro lado do
    link que a CLI do grill imprime (`grill/cli.py:122`)."""
    execucao = (FONTE / "Execucao.tsx").read_text(encoding="utf-8")

    # `.workflows()` sem o receptor: o prettier quebra `api` para a linha de
    # cima, e um teste que trava formatação fica vermelho por indentação.
    assert ".workflows()" in execucao
    assert "<select" in execucao
    # Opção desabilitada para cascata paga: a tela não deixa a pessoa colher
    # um 409 pelo dropdown. Quem garante continua sendo o servidor.
    assert "disabled={!w.executavel}" in execucao


def test_a_resposta_e_conferida_antes_de_desenhar():
    """`fetch` não rejeita sozinho em 409/404: sem checar `ok` explicitamente,
    a tela desenharia a cascata a partir do corpo de um erro.

    A checagem mora num lugar só — `pedir`, em `api.ts` — e é por isso que
    nenhuma vista precisa lembrar de fazê-la.
    """
    api = (FONTE / "api.ts").read_text(encoding="utf-8")

    assert "if (!r.ok) throw await erroDe(r);" in api
