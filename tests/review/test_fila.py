import json
from datetime import UTC, datetime

import pytest

from orchestrator.kernel.resolution import Confidence, Proposal
from orchestrator.review.decision import Decision, Veredito
from orchestrator.review.fila import Fila, caminho_da_fila, dataset_id
from orchestrator.review.serial import decisao_para_dict, proposta_para_dict
from orchestrator.taxonomy import DivergenceType


def _proposta(divergence_id: str, tipo=DivergenceType.DEFASAGEM_TEMPORAL) -> Proposal:
    return Proposal(
        item_id=divergence_id,
        tipo=tipo,
        explicacao="x",
        evidencia=["e"],
        confianca=Confidence.MEDIA,
        acao_sugerida="conciliar_com(l1)",
    )


def _decisao(divergence_id: str, motivo: str = "") -> Decision:
    return Decision(
        divergence_id=divergence_id,
        veredito=Veredito.ACEITAR,
        tipo=DivergenceType.DEFASAGEM_TEMPORAL,
        conciliar_com=frozenset({"l1"}),
        autor="controller@cliente",
        quando=datetime(2026, 9, 15, tzinfo=UTC),
        motivo=motivo,
    )


def test_dataset_id_distingue_sementes():
    # O id `d-b-b00003` existe em TODA semente. Sem este escopo, uma decisão
    # tomada olhando a semente 1 se aplicaria ao b00003 da semente 7, que é
    # outro lançamento.
    assert dataset_id(1, 300, 0.15) != dataset_id(7, 300, 0.15)
    assert dataset_id(1, 300, 0.15) == "s1-n300-t0.15"


def test_caminho_separa_workflows(tmp_path):
    a = caminho_da_fila("conciliacao", "s1-n30-t0.15", raiz=tmp_path)
    b = caminho_da_fila("outro", "s1-n30-t0.15", raiz=tmp_path)

    assert a != b
    assert a.suffix == ".jsonl"
    assert a == tmp_path / "fila" / "conciliacao" / "s1-n30-t0.15.jsonl"


def test_grava_e_le_proposta(tmp_path):
    f = Fila(caminho_da_fila("w", "d", raiz=tmp_path))
    f.gravar_proposta(_proposta("d-1"))

    recarregada = Fila(caminho_da_fila("w", "d", raiz=tmp_path))

    assert recarregada.proposta("d-1") == _proposta("d-1")
    assert [p.item_id for p in recarregada.pendentes()] == ["d-1"]


def test_primeira_proposta_vence_e_a_segunda_nem_e_gravada(tmp_path):
    # O agente não se repete. Se uma segunda proposta chegasse, ela apagaria
    # o que o revisor já leu — e o custo de reinvestigar já teria sido pago.
    caminho = caminho_da_fila("w", "d", raiz=tmp_path)
    f = Fila(caminho)
    f.gravar_proposta(_proposta("d-1", DivergenceType.DEFASAGEM_TEMPORAL))
    f.gravar_proposta(_proposta("d-1", DivergenceType.RETENCAO_IMPOSTO))

    assert f.proposta("d-1").tipo is DivergenceType.DEFASAGEM_TEMPORAL
    assert len(caminho.read_text(encoding="utf-8").strip().splitlines()) == 1


def test_ultima_decisao_vence_mas_o_log_guarda_as_duas(tmp_path):
    # Um humano muda de ideia. O estado é a última decisão; a auditoria é
    # todas elas.
    caminho = caminho_da_fila("w", "d", raiz=tmp_path)
    f = Fila(caminho)
    f.gravar_proposta(_proposta("d-1"))
    f.gravar_decisao(_decisao("d-1", motivo="primeira"))
    f.gravar_decisao(_decisao("d-1", motivo="reconsiderei"))

    assert f.decisao("d-1").motivo == "reconsiderei"
    linhas = caminho.read_text(encoding="utf-8").strip().splitlines()
    assert sum(1 for x in linhas if '"decisao"' in x) == 2


def test_primeira_proposta_vence_tambem_ao_recarregar_do_arquivo(tmp_path):
    # `gravar_proposta` já bloqueia a segunda escrita em memória, o que nunca
    # chega a exercitar o dedup de `_aplicar`. Um arquivo pré-existente,
    # migrado ou produzido por outro processo pode conter as duas linhas de
    # `proposta` direto — é aí que o dedup de leitura precisa valer.
    caminho = caminho_da_fila("w", "d", raiz=tmp_path)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    linhas = [
        json.dumps(
            {
                "kind": "proposta",
                "dados": proposta_para_dict(
                    _proposta("d-1", DivergenceType.DEFASAGEM_TEMPORAL)
                ),
            }
        ),
        json.dumps(
            {
                "kind": "proposta",
                "dados": proposta_para_dict(_proposta("d-1", DivergenceType.RETENCAO_IMPOSTO)),
            }
        ),
    ]
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")

    f = Fila(caminho)

    assert f.proposta("d-1").tipo is DivergenceType.DEFASAGEM_TEMPORAL


def test_ultima_decisao_vence_tambem_ao_recarregar_do_arquivo(tmp_path):
    # `test_ultima_decisao_vence_mas_o_log_guarda_as_duas` só inspeciona a
    # `Fila` viva que escreveu — nunca reconstrói a partir do arquivo. Um
    # copy-paste acidental do ramo de proposta (primeira vence) para o ramo de
    # decisão passaria por aquele teste sem ser notado.
    caminho = caminho_da_fila("w", "d", raiz=tmp_path)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    linhas = [
        json.dumps({"kind": "decisao", "dados": decisao_para_dict(_decisao("d-1", "primeira"))}),
        json.dumps(
            {"kind": "decisao", "dados": decisao_para_dict(_decisao("d-1", "reconsiderei"))}
        ),
    ]
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")

    f = Fila(caminho)

    assert f.decisao("d-1").motivo == "reconsiderei"
    assert sum(1 for x in linhas if '"decisao"' in x) == 2


def test_pendentes_exclui_o_que_ja_foi_decidido(tmp_path):
    f = Fila(caminho_da_fila("w", "d", raiz=tmp_path))
    f.gravar_proposta(_proposta("d-1"))
    f.gravar_proposta(_proposta("d-2"))
    f.gravar_decisao(_decisao("d-1"))

    assert [p.item_id for p in f.pendentes()] == ["d-2"]
    assert [p.item_id for p, _ in f.decididas()] == ["d-1"]


def test_fila_vazia_nao_escreve_nada(tmp_path, monkeypatch):
    # A definição padrão usa uma fila vazia. Se ela tocasse o disco, o golden
    # e a CLI passariam a depender de estado fora do processo. Uma tarefa
    # futura chama `gravar_*` numa `Fila.vazia()` dentro dessa definição
    # padrão — o teste precisa exercitar exatamente essas chamadas, não só
    # as leituras (que são puras e não provariam nada sobre escrita).
    monkeypatch.chdir(tmp_path)
    f = Fila.vazia()

    f.gravar_proposta(_proposta("d-1"))
    f.gravar_decisao(_decisao("d-1"))

    assert f.pendentes() == []
    assert f.proposta("qualquer") is None
    assert list(tmp_path.iterdir()) == []


def test_registro_truncado_aponta_arquivo_e_linha(tmp_path):
    # A fila é a trilha de auditoria. Um registro incompleto — um schema mais
    # velho, um campo que só foi adicionado depois — não pode falhar com um
    # KeyError mudo: quem investiga precisa saber QUAL arquivo e QUAL linha.
    caminho = caminho_da_fila("w", "d", raiz=tmp_path)
    caminho.parent.mkdir(parents=True, exist_ok=True)

    dados_da_decisao_sem_autor = decisao_para_dict(_decisao("d-1"))
    del dados_da_decisao_sem_autor["autor"]
    linhas = [
        json.dumps({"kind": "proposta", "dados": proposta_para_dict(_proposta("d-1"))}),
        json.dumps({"kind": "decisao", "dados": dados_da_decisao_sem_autor}),
    ]
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        Fila(caminho)

    mensagem = str(excinfo.value)
    assert str(caminho) in mensagem
    # Não "2" solto: `tmp_path` real do pytest embute um contador de execução
    # (`pytest-of-<user>\pytest-<N>\...`) que pode conter o dígito por
    # coincidência mesmo se o número de linha estiver errado.
    assert "linha 2" in mensagem
    assert excinfo.value.__cause__ is not None


def test_a_chave_da_fila_sintetica_nao_mudou():
    """Se esta quebrar, toda fila em `data/fila/**` virou invisível.

    A chave da fila passou a sair do `ref` da fonte — uniformemente, para toda
    fonte — porque com um arquivo não existe `(seed, n, taxa)`. Isso só é
    seguro porque `SyntheticSource.ref` sempre foi `dataset_id` com o esquema
    na frente: a mesma string. Esta igualdade é o que garante que nenhuma
    decisão humana já gravada em disco deixa de ser encontrada.
    """
    from orchestrator.review.fila import dataset_de_ref
    from orchestrator.synth.benchmark import SyntheticSource

    assert dataset_de_ref("synth:s1-n300-t0.15") == dataset_id(1, 300, 0.15)
    # E o `ref` de verdade, não só a string escrita à mão aqui: sem isto, um
    # dia em que `SyntheticSource.ref` mudasse de formato o teste acima
    # continuaria verde comparando duas coisas que ninguém produz.
    for seed, n, taxa in ((1, 300, 0.15), (7, 50, 0.0), (0, 1, 1.0)):
        fonte = SyntheticSource(seed=seed, n=n, taxa_divergencia=taxa)
        assert dataset_de_ref(fonte.ref) == dataset_id(seed, n, taxa)


def test_a_chave_de_um_ref_de_arquivo_e_um_NOME_DE_ARQUIVO_valido(tmp_path):
    """`caminho_da_fila` interpola a chave em `{dataset}.jsonl`.

    Um ref `file:` carrega `/`, `@` e o `:` do esquema — diretório acidental no
    Linux, nome ilegal no Windows. Por isso vira hash. O teste escreve DE FATO
    no caminho produzido: uma chave ilegal falha aqui, não em produção.
    """
    from orchestrator.review.fila import dataset_de_ref

    ref = "file:sub/itens.csv@" + "a" * 64
    chave = dataset_de_ref(ref)

    assert not (set(chave) & set(r'/\:@*?"<>|'))
    caminho = caminho_da_fila("w", chave, raiz=tmp_path)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text("", encoding="utf-8")
    assert caminho.is_file()
    # O caminho relativo entra na identidade: dois arquivos diferentes com o
    # MESMO conteúdo não compartilham fila.
    assert chave != dataset_de_ref("file:outro.csv@" + "a" * 64)


def test_conteudo_diferente_no_mesmo_caminho_troca_a_fila():
    """O `ref` de arquivo carrega o sha256 do CONTEÚDO, então editar o arquivo
    troca a chave. É o mesmo argumento do docstring de `dataset_id`: uma
    decisão tomada olhando um conjunto não vale para outro."""
    from orchestrator.review.fila import dataset_de_ref

    assert dataset_de_ref("file:x.csv@" + "a" * 64) != dataset_de_ref(
        "file:x.csv@" + "b" * 64
    )


def test_a_forma_legada_descreve_o_que_dataset_id_produz():
    """O par que impede o join frágil.

    `_FORMA_LEGADA` é uma segunda expressão sobre o mesmo formato de
    `dataset_id`. Se elas divergirem, o ramo de compatibilidade para de
    reconhecer a chave antiga e toda fila em `data/fila/**` fica invisível —
    em silêncio, porque nada mais compara as duas.
    """
    from orchestrator.review.fila import _FORMA_LEGADA

    for seed in (0, 1, 7, 12345):
        for n in (1, 30, 300, 5000):
            for taxa in (0.0, 0.15, 1.0):
                assert _FORMA_LEGADA.fullmatch(dataset_id(seed, n, taxa)), (seed, n, taxa)


def test_o_ESQUEMA_faz_parte_da_chave_fora_do_caso_legado():
    """`synth:X` e `db:X` não podem cair na mesma fila.

    Descartar o esquema sempre que o resto fosse seguro colidiria dois
    conjuntos diferentes numa trilha de decisões só. Inalcançável hoje — há um
    `Source` com esquema `synth:` e outro com `file:` — e uma armadilha
    armada para o terceiro.
    """
    from orchestrator.review.fila import dataset_de_ref

    assert dataset_de_ref("synth:abc") != dataset_de_ref("db:abc")
    assert dataset_de_ref("db:abc") == "db-abc"
    # E o caso legado continua sendo o único que perde o esquema.
    assert dataset_de_ref("synth:s1-n300-t0.15") == "s1-n300-t0.15"
    assert dataset_de_ref("outro:s1-n300-t0.15") == "outro-s1-n300-t0.15"


def test_um_esquema_INSEGURO_nao_vira_prefixo():
    """A peneira do prefixo, que o caso do hash usa.

    `partition(':')` num ref SEM `:` devolve o ref inteiro como esquema. Sem a
    peneira, um ref `a/b` produziria a chave `a/b-<hash>` e
    `caminho_da_fila` criaria um DIRETÓRIO `a/` — a fila escrita num lugar que
    ninguém procura, sem erro nenhum.
    """
    from orchestrator.review.fila import dataset_de_ref

    for ref in ("a/b", "..", "c:\\temp\\x", "sem-dois-pontos/../fuga"):
        chave = dataset_de_ref(ref)
        assert not (set(chave) & set(r'/\:@*?"<>|')), ref
        assert chave not in (".", "..")
