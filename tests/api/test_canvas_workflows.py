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
