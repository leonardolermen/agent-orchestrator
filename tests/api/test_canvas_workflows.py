from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web"


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
