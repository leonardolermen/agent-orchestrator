import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web"

_DEFAULT_WORKFLOW = re.compile(r'QUERY\.get\("workflow"\)\s*\|\|\s*"([^"]+)"')

# Linhas de comentário são removidas antes de procurar rotas: `fila.js`
# menciona `/api/fila/{workflow_id}` em prosa, entre crases, para explicar que
# o id é segmento de PATH — texto que não é código e não pode contar como uso.
_COMENTARIO = re.compile(r"^\s*//.*$", re.MULTILINE)
_ROTA_DA_FILA = re.compile(r"`(/api/fila/[^`]*)`")


def test_o_canvas_le_o_workflow_da_url():
    # Constante local com default próprio foi o que fez canvas e fila
    # apontarem para datasets diferentes e quebrou o demo inteiro.
    js = (WEB / "canvas.js").read_text(encoding="utf-8")
    assert "location.search" in js
    assert "workflow" in js


def test_o_canvas_usa_o_mesmo_default_de_workflow_que_a_api():
    js = (WEB / "canvas.js").read_text(encoding="utf-8")
    assert "conciliacao" in js


def test_o_seletor_existe_no_html():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'id="workflow"' in html


def test_o_canvas_confere_a_resposta_antes_de_desenhar():
    # A CLI do grill imprime `?workflow=<id>` como último passo — se a
    # receita tiver classe AGENTE, é esse link que o parceiro clica, direto,
    # sem passar pelo <select>. `fetch` não rejeita sozinho em 409/404: sem
    # checar `.ok` explicitamente, a tela desenharia a cascata a partir do
    # corpo de um erro. Este teste só confere que a checagem existe no texto
    # do arquivo — não que ela é usada corretamente; isso é o Step 4 manual.
    js = (WEB / "canvas.js").read_text(encoding="utf-8")
    assert ".ok" in js


def test_canvas_e_fila_concordam_sobre_o_default_de_workflow():
    # Propositalmente NÃO trava o valor literal "conciliacao": trocar o
    # default nas DUAS páginas ao mesmo tempo é uma mudança legítima
    # (renomear o workflow embutido) que não deve quebrar este teste. O que
    # não pode acontecer é as duas páginas divergirem entre si — foi
    # exatamente essa classe de bug que já quebrou o demo duas vezes: uma
    # com `n=300` contra `n=30` entre canvas e fila numa fatia anterior, e
    # de novo agora com `fila.js` fixando `workflow` em "conciliacao" mesmo
    # quando o canvas apontava para outro id. Por isso este teste COMPARA os
    # dois arquivos em vez de duas asserções independentes: duas asserções
    # soltas (uma por arquivo) passariam cada uma isoladamente mesmo com os
    # defaults diferentes entre si, que é precisamente o defeito que causou
    # dano — não simplifique isto de volta a duas checagens separadas.
    canvas_js = (WEB / "canvas.js").read_text(encoding="utf-8")
    fila_js = (WEB / "fila.js").read_text(encoding="utf-8")
    m_canvas = _DEFAULT_WORKFLOW.search(canvas_js)
    m_fila = _DEFAULT_WORKFLOW.search(fila_js)
    assert m_canvas and m_fila, "os dois arquivos precisam declarar o default no mesmo formato"
    assert m_canvas.group(1) == m_fila.group(1)


def test_as_duas_urls_da_fila_interpolam_o_workflow():
    # O teste acima compara só a DECLARAÇÃO do default — e o defeito real que
    # ele foi escrito para constranger não estava na declaração: `fila.js`
    # declarava o default certo e mesmo assim chamava `/api/fila/conciliacao`
    # fixo. Com a declaração correta no lugar, fixar a URL de volta deixava a
    # suíte inteira verde — inclusive no POST de decisão, que é a metade que
    # grava decisão humana na trilha de auditoria de OUTRO workflow.
    #
    # Por isso a asserção é sobre o USO: as duas rotas — o GET da fila e o
    # POST da decisão — precisam interpolar a variável, não um literal.
    js = _COMENTARIO.sub("", (WEB / "fila.js").read_text(encoding="utf-8"))
    rotas = _ROTA_DA_FILA.findall(js)

    assert len(rotas) == 2, rotas
    for rota in rotas:
        assert rota.startswith("/api/fila/${"), rota
    # Uma das duas é o POST de decisão, a outra não: sem isto, fixar UMA delas
    # e duplicar a outra passaria pelas asserções acima.
    assert sorted("/decisao" in r for r in rotas) == [False, True], rotas
