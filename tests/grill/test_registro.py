import json
from datetime import UTC, datetime

import pytest

from orchestrator.grill.receita import Receita, ResolverReceita
from orchestrator.grill.registro import (
    caminho_da_receita,
    gravar_receita,
    gravar_recusa,
    ler_receita,
    listar_receitas,
)


def _r(id: str = "acme") -> Receita:
    return Receita(
        id=id,
        nome="Acme",
        justificativa="j",
        gerado_em=datetime(2026, 9, 15, tzinfo=UTC),
        resolvers=(ResolverReceita("L1", {}),),
    )


def test_gravar_cria_o_diretorio_e_o_arquivo(tmp_path):
    # `data/` não existe num clone novo depois do .gitignore virar allowlist.
    caminho = gravar_receita(_r(), raiz=tmp_path)

    assert caminho == tmp_path / "workflows" / "acme.json"
    assert json.loads(caminho.read_text(encoding="utf-8"))["id"] == "acme"


def test_ler_devolve_a_mesma_receita(tmp_path):
    gravar_receita(_r(), raiz=tmp_path)
    assert ler_receita("acme", raiz=tmp_path) == _r()


def test_gravar_recusa_sobrescrever(tmp_path):
    # Sobrescrever mudaria, por baixo, o significado das decisões humanas já
    # gravadas sob esse workflow na fila.
    gravar_receita(_r(), raiz=tmp_path)
    with pytest.raises(ValueError, match="já existe"):
        gravar_receita(_r(), raiz=tmp_path)


def test_gravar_recusa_id_reservado(tmp_path):
    with pytest.raises(ValueError, match="reservado"):
        gravar_receita(_r("conciliacao"), raiz=tmp_path)


def test_gravar_recusa_id_fora_do_padrao(tmp_path):
    with pytest.raises(ValueError, match="id inválido"):
        gravar_receita(_r("Acme!"), raiz=tmp_path)


def test_id_com_travessia_de_caminho_e_recusado(tmp_path):
    # `PADRAO_ID` já barra, mas o teste existe porque a consequência de falhar
    # aqui é escrita fora de `data/`. Precisa de DOIS níveis de `..`: o
    # primeiro cancela só o segmento `workflows/` que `caminho_da_receita`
    # insere, e é o segundo que de fato sairia de `tmp_path`. Um único `..`
    # pousa de volta dentro de `tmp_path` — não prova nada sobre travessia.
    with pytest.raises(ValueError, match="id inválido"):
        gravar_receita(_r("../../fora"), raiz=tmp_path)
    # Não adivinha nome nem profundidade exata de onde a escrita indevida
    # pousaria: cobre qualquer travessia, recursivamente sob `tmp_path` e no
    # diretório acima dele.
    assert not any(tmp_path.rglob("*.json"))
    assert not any(tmp_path.parent.glob("*.json"))


def test_listar_devolve_ordenado_por_id(tmp_path):
    gravar_receita(_r("zeta"), raiz=tmp_path)
    gravar_receita(_r("alfa"), raiz=tmp_path)

    assert [x.id for x in listar_receitas(raiz=tmp_path)] == ["alfa", "zeta"]


def test_listar_em_raiz_inexistente_devolve_vazio(tmp_path):
    assert listar_receitas(raiz=tmp_path / "nao-existe") == []


def test_listar_ignora_arquivo_corrompido(tmp_path, capsys):
    gravar_receita(_r("bom"), raiz=tmp_path)
    (tmp_path / "workflows" / "ruim.json").write_text("{isto não é json", encoding="utf-8")

    achadas = listar_receitas(raiz=tmp_path)

    assert [x.id for x in achadas] == ["bom"]
    assert "ruim" in capsys.readouterr().err


def test_gravar_recusa_escreve_motivo_e_lacuna(tmp_path):
    from orchestrator.agent.proposal import Cost
    from orchestrator.grill.entrevistador import RecusaFinal

    caminho = gravar_recusa(
        "acme",
        RecusaFinal(
            motivo="é cartão", o_que_faltaria="adquirente", cost=Cost.zero(), transcricao=()
        ),
        raiz=tmp_path,
    )

    dados = json.loads(caminho.read_text(encoding="utf-8"))
    assert dados["motivo"] == "é cartão"
    assert dados["o_que_faltaria"] == "adquirente"


def test_caminho_da_receita_nao_cria_nada(tmp_path):
    # Montar caminho e criar diretório são responsabilidades diferentes: quem
    # cria é quem escreve. Mesma divisão de `caminho_da_fila` e `Fila._append`.
    caminho_da_receita("acme", raiz=tmp_path)
    assert not (tmp_path / "workflows").exists()
