"""A fonte de arquivo: ler é fácil, a cerca é o trabalho."""

import json

import pytest

from orchestrator.sources.arquivo import ArquivoSource, RaizViolada


def _raiz(tmp_path):
    (tmp_path / "entradas").mkdir()
    return tmp_path / "entradas"


def test_csv_vira_pool_com_o_kind_declarado(tmp_path):
    raiz = _raiz(tmp_path)
    (raiz / "issues.csv").write_text(
        "numero,titulo\n7,trava ao salvar\n8,lento\n", encoding="utf-8"
    )

    fonte = ArquivoSource(
        caminho=raiz / "issues.csv", kind="issue", campo_id="numero", raiz=raiz
    )
    pool = fonte.load()

    assert [i.id for i in pool.items] == ["7", "8"]
    assert {i.kind for i in pool.items} == {"issue"}
    # O payload é a linha CRUA. O kernel nunca o inspeciona, e o `prompt` do
    # agente formata a partir dele.
    assert pool.items[0].payload == {"numero": "7", "titulo": "trava ao salvar"}


def test_json_com_lista_de_objetos_vira_o_mesmo_pool(tmp_path):
    raiz = _raiz(tmp_path)
    (raiz / "issues.json").write_text(
        json.dumps([{"numero": 7, "titulo": "trava"}]), encoding="utf-8"
    )

    pool = ArquivoSource(
        caminho=raiz / "issues.json", kind="issue", campo_id="numero", raiz=raiz
    ).load()

    # O id vira STRING mesmo quando o JSON traz número: `WorkItem.id` é `str`,
    # e deixar `7` e `"7"` coexistirem faria dois itens distintos para o mesmo
    # trabalho conforme o formato do arquivo.
    assert [i.id for i in pool.items] == ["7"]


def test_o_ref_e_o_SHA256_DO_CONTEUDO(tmp_path):
    """`ref` estável ou não há replay. Copiar o arquivo muda `mtime` e não muda
    o trabalho — por isso o hash é do conteúdo, nunca da data."""
    raiz = _raiz(tmp_path)
    (raiz / "a.csv").write_text("id,x\n1,um\n", encoding="utf-8")
    (raiz / "b.csv").write_text("id,x\n1,um\n", encoding="utf-8")

    a = ArquivoSource(caminho=raiz / "a.csv", kind="k", campo_id="id", raiz=raiz)
    b = ArquivoSource(caminho=raiz / "b.csv", kind="k", campo_id="id", raiz=raiz)

    assert a.ref.startswith("file:")
    # Mesmo conteúdo, arquivos diferentes: o hash bate, o caminho não.
    assert a.ref.split("@")[1] == b.ref.split("@")[1]
    assert a.ref != b.ref


def test_o_ref_MUDA_quando_o_conteudo_muda(tmp_path):
    raiz = _raiz(tmp_path)
    alvo = raiz / "a.csv"
    alvo.write_text("id,x\n1,um\n", encoding="utf-8")
    antes = ArquivoSource(caminho=alvo, kind="k", campo_id="id", raiz=raiz).ref

    alvo.write_text("id,x\n1,dois\n", encoding="utf-8")
    depois = ArquivoSource(caminho=alvo, kind="k", campo_id="id", raiz=raiz).ref

    assert antes != depois


def test_caminho_FORA_da_raiz_e_recusado(tmp_path):
    """O alvo que importa não é `/etc/passwd` — é `data/fila/**`, a trilha de
    decisões humanas de outro workflow."""
    raiz = _raiz(tmp_path)
    (tmp_path / "segredo.csv").write_text("id,x\n1,um\n", encoding="utf-8")

    with pytest.raises(RaizViolada):
        ArquivoSource(
            caminho=raiz / ".." / "segredo.csv", kind="k", campo_id="id", raiz=raiz
        )


def test_symlink_apontando_para_fora_e_recusado(tmp_path):
    """`resolve()` ANTES de comparar. Uma checagem feita sobre o caminho não
    resolvido é furada por um symlink que mora dentro da raiz."""
    raiz = _raiz(tmp_path)
    fora = tmp_path / "segredo.csv"
    fora.write_text("id,x\n1,um\n", encoding="utf-8")
    link = raiz / "atalho.csv"
    try:
        link.symlink_to(fora)
    except (OSError, NotImplementedError):
        pytest.skip("symlink exige privilégio neste sistema")

    with pytest.raises(RaizViolada):
        ArquivoSource(caminho=link, kind="k", campo_id="id", raiz=raiz)


def test_prefixo_de_string_NAO_conta_como_dentro(tmp_path):
    """`/dados-secretos` não está dentro de `/dados`, mas `startswith` diz que
    sim. É por isso que a comparação é `is_relative_to`."""
    raiz = _raiz(tmp_path)
    vizinho = tmp_path / "entradas-secretas"
    vizinho.mkdir()
    (vizinho / "x.csv").write_text("id,x\n1,um\n", encoding="utf-8")

    with pytest.raises(RaizViolada):
        ArquivoSource(
            caminho=vizinho / "x.csv", kind="k", campo_id="id", raiz=raiz
        )


def test_campo_id_ausente_e_erro_ALTO_nao_linha_pulada(tmp_path):
    """Pular em silêncio produziria um pool menor que o arquivo, e ninguém
    saberia. `WorkItem` já recusa id vazio; aqui a mensagem diz qual linha."""
    raiz = _raiz(tmp_path)
    (raiz / "x.csv").write_text("outro,x\n1,um\n", encoding="utf-8")

    fonte = ArquivoSource(caminho=raiz / "x.csv", kind="k", campo_id="id", raiz=raiz)

    with pytest.raises(ValueError, match="campo_id"):
        fonte.load()


def test_id_repetido_e_recusado_pelo_WorkSet(tmp_path):
    raiz = _raiz(tmp_path)
    (raiz / "x.csv").write_text("id,x\n1,um\n1,dois\n", encoding="utf-8")

    fonte = ArquivoSource(caminho=raiz / "x.csv", kind="k", campo_id="id", raiz=raiz)

    with pytest.raises(ValueError, match="id repetido"):
        fonte.load()


def test_teto_de_linhas_recusa_com_motivo(tmp_path):
    """Uma planilha de 200k linhas não pode derrubar o processo. Mesmo espírito
    do `n_max` que o pedido sintético já tem."""
    raiz = _raiz(tmp_path)
    linhas = "id,x\n" + "".join(f"{i},v\n" for i in range(12))
    (raiz / "grande.csv").write_text(linhas, encoding="utf-8")

    fonte = ArquivoSource(
        caminho=raiz / "grande.csv", kind="k", campo_id="id", raiz=raiz, max_linhas=10
    )

    with pytest.raises(ValueError, match="linhas"):
        fonte.load()
