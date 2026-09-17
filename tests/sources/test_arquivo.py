"""A fonte de arquivo: ler é fácil, a cerca é o trabalho."""

import json
from pathlib import Path

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


def test_linha_csv_truncada_e_recusada_nao_vira_id_none(tmp_path):
    """Uma linha mais curta que o cabeçalho preenche os campos que faltam com
    o `restval` do `DictReader` — a CHAVE fica presente, só o valor que falta.
    Sem um sentinela que não se confunda com um valor real, a linha truncada
    virava `WorkItem` com id `"None"`, fabricado, e ninguém era avisado."""
    raiz = _raiz(tmp_path)
    (raiz / "x.csv").write_text("x,id\num\n", encoding="utf-8")

    fonte = ArquivoSource(caminho=raiz / "x.csv", kind="k", campo_id="id", raiz=raiz)

    with pytest.raises(ValueError, match="truncada"):
        fonte.load()


def test_linha_csv_com_campos_extras_e_recusada_sem_TypeError(tmp_path):
    """Uma linha mais longa que o cabeçalho vai para o `restkey` do
    `DictReader` — e sem tratamento essa chave extra (um objeto, não uma
    string) faz `sorted()` da mensagem de erro explodir em `TypeError`, que
    esconde o problema real por trás de um traceback não relacionado."""
    raiz = _raiz(tmp_path)
    (raiz / "x.csv").write_text("id,x\n1,um,sobra\n", encoding="utf-8")

    fonte = ArquivoSource(caminho=raiz / "x.csv", kind="k", campo_id="id", raiz=raiz)

    with pytest.raises(ValueError, match="mais campos"):
        fonte.load()


def test_id_vazio_e_recusado(tmp_path):
    """String vazia não identifica nada — mesmo espírito do `WorkItem`, que já
    recusa id vazio, mas aqui com o número da linha."""
    raiz = _raiz(tmp_path)
    (raiz / "x.csv").write_text("id,x\n,um\n", encoding="utf-8")

    fonte = ArquivoSource(caminho=raiz / "x.csv", kind="k", campo_id="id", raiz=raiz)

    with pytest.raises(ValueError, match="vazio"):
        fonte.load()


def test_id_falsy_como_zero_e_aceito(tmp_path):
    """`0` é um id legítimo — a guarda testa `valor == ""`, nunca `not valor`,
    ou um id falsy qualquer (0, False) seria rejeitado à toa."""
    raiz = _raiz(tmp_path)
    (raiz / "x.json").write_text(
        json.dumps([{"id": 0, "x": "um"}]), encoding="utf-8"
    )

    pool = ArquivoSource(
        caminho=raiz / "x.json", kind="k", campo_id="id", raiz=raiz
    ).load()

    assert [i.id for i in pool.items] == ["0"]


def test_ref_usa_barra_mesmo_em_subdiretorio(tmp_path):
    """`Path` relativo imprime com `\\` no Windows e `/` no Linux — o MESMO
    arquivo produziria dois `ref` diferentes conforme o SO em que o processo
    roda. `.as_posix()` fixa o separador, e é isso que faz "estável" valer
    entre quem gerou o `ref` e o CI que faz o replay."""
    raiz = _raiz(tmp_path)
    (raiz / "sub").mkdir()
    (raiz / "sub" / "a.csv").write_text("id,x\n1,um\n", encoding="utf-8")

    fonte = ArquivoSource(
        caminho=raiz / "sub" / "a.csv", kind="k", campo_id="id", raiz=raiz
    )

    assert "/" in fonte.ref
    assert "\\" not in fonte.ref


def test_ref_e_load_leem_o_arquivo_uma_unica_vez(tmp_path, monkeypatch):
    """`ref` e `load()` liam o disco em chamadas separadas — nada garantia que
    os bytes hasheados por `ref` eram os mesmos que `load()` transformava em
    `WorkItem`. Memoizado, a leitura acontece uma vez só, não importa quantas
    vezes `ref`/`load()` sejam chamados."""
    raiz = _raiz(tmp_path)
    (raiz / "a.csv").write_text("id,x\n1,um\n", encoding="utf-8")
    fonte = ArquivoSource(caminho=raiz / "a.csv", kind="k", campo_id="id", raiz=raiz)

    chamadas = []
    original = Path.read_bytes

    def contando(self, *a, **kw):
        chamadas.append(self)
        return original(self, *a, **kw)

    monkeypatch.setattr(Path, "read_bytes", contando)

    _ = fonte.ref
    fonte.load()
    _ = fonte.ref

    assert len(chamadas) == 1


def test_teto_de_bytes_recusa_com_motivo(tmp_path):
    """Um arquivo de 4 GB não pode ser lido inteiro antes de ser recusado — o
    teto em bytes usa `stat()`, que roda ANTES de qualquer leitura, e por isso
    protege `ref` também, que não passa por `load()`."""
    raiz = _raiz(tmp_path)
    (raiz / "grande.csv").write_text("id,x\n1,umvalor\n", encoding="utf-8")

    fonte = ArquivoSource(
        caminho=raiz / "grande.csv", kind="k", campo_id="id", raiz=raiz, max_bytes=5
    )

    with pytest.raises(ValueError, match="bytes"):
        _ = fonte.ref
