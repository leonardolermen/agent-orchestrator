"""A fonte Postgres: ler é fácil; não escrever, não vazar, e ter `ref` é o trabalho."""

import logging

import pytest

from orchestrator.sources.erros import ExtraAusente, FonteFalhou, VariavelAusente
from orchestrator.sources.postgres import PostgresSource

SENTINELA = "postgresql://usuario:SEGREDO-4F2A@db.interna:5432/erp"


class _Cursor:
    """O cursor falso serve `fetchmany(n)` como o de verdade: no MÁXIMO `n`
    linhas. É por aí que o teto protege a memória — `fetchall()` traria tudo."""

    def __init__(self, linhas, erro=None):
        self.linhas, self.erro, self.executadas = linhas, erro, []
        self.pedidas = []

    def execute(self, query):
        self.executadas.append(query)
        if self.erro:
            raise self.erro

    def fetchmany(self, quantas):
        self.pedidas.append(quantas)
        return list(self.linhas)[:quantas]


class _Conexao:
    def __init__(self, linhas, erro=None):
        self.cursor_ = _Cursor(linhas, erro)
        self.fechada = False

    def cursor(self):
        return self.cursor_

    def close(self):
        self.fechada = True


def _fonte(
    monkeypatch, linhas, *, query="SELECT id, titulo FROM issues", erro=None, env=SENTINELA,
    erro_de_conexao=None,
):
    """Conexão FALSA injetada; nenhum socket. A variável de ambiente recebe o
    sentinela para que qualquer vazamento apareça como texto reconhecível."""
    if env is not None:
        monkeypatch.setenv("ERP_DSN", env)
    else:
        monkeypatch.delenv("ERP_DSN", raising=False)
    conexoes = []

    def conectar(dsn):
        conexoes.append(dsn)
        if erro_de_conexao is not None:
            raise erro_de_conexao
        return _Conexao(linhas, erro)

    fonte = PostgresSource(
        dsn_env="ERP_DSN", query=query, kind="issue", campo_id="id", conectar=conectar
    )
    return fonte, conexoes


def test_linhas_viram_pool_com_o_kind_e_o_payload_cru(monkeypatch):
    fonte, _ = _fonte(monkeypatch, [{"id": 7, "titulo": "trava"}, {"id": 8, "titulo": "lento"}])
    pool = fonte.load()
    assert [i.id for i in pool.items] == ["7", "8"]
    assert {i.kind for i in pool.items} == {"issue"}
    assert pool.items[0].payload == {"id": 7, "titulo": "trava"}


def test_o_DSN_e_lido_do_ambiente_NA_HORA_e_passado_ao_conectar(monkeypatch):
    fonte, conexoes = _fonte(monkeypatch, [{"id": 1}])
    fonte.load()
    assert conexoes == [SENTINELA]


def test_variavel_ausente_e_422_que_cita_o_NOME_e_nao_conecta(monkeypatch):
    fonte, conexoes = _fonte(monkeypatch, [{"id": 1}], env=None)
    with pytest.raises(VariavelAusente) as erro:
        fonte.load()
    assert "ERP_DSN" in str(erro.value)
    assert conexoes == []


@pytest.mark.parametrize(
    "query",
    [
        "SELECT id FROM issues",
        "select id from issues",
        "  -- comentário\nSELECT id FROM issues",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "SELECT id FROM issues;",
    ],
)
def test_leitura_PASSA_na_guarda(monkeypatch, query):
    fonte, conexoes = _fonte(monkeypatch, [{"id": 1}], query=query)
    fonte.load()
    assert len(conexoes) == 1


@pytest.mark.parametrize(
    "query",
    [
        "INSERT INTO issues VALUES (1)",
        "UPDATE issues SET x = 1",
        "DELETE FROM issues",
        "DROP TABLE issues",
        "CALL limpar()",
        "SELECT 1; DELETE FROM issues",
        "SELECT id INTO foo FROM t",
        "SELECT id\nINTO foo FROM t",
        "select * into novo from t",
    ],
)
def test_escrita_e_recusada_ANTES_de_conectar(monkeypatch, query):
    """A plataforma lê e nunca escreve. A guarda é conservadora de propósito, e
    o que ela prova é que `conectar` NÃO foi chamado."""
    fonte, conexoes = _fonte(monkeypatch, [{"id": 1}], query=query)
    with pytest.raises(FonteFalhou, match="SELECT"):
        fonte.load()
    assert conexoes == []


def test_o_ref_leva_o_NOME_da_variavel_o_hash_da_query_e_o_hash_das_linhas(monkeypatch):
    fonte, _ = _fonte(monkeypatch, [{"id": 1, "t": "a"}])
    ref = fonte.ref
    assert ref.startswith("pg:ERP_DSN/")
    assert "@" in ref
    assert "SEGREDO" not in ref and "db.interna" not in ref


def test_o_ref_e_ESTAVEL_para_as_mesmas_linhas_e_muda_quando_uma_muda(monkeypatch):
    a, _ = _fonte(monkeypatch, [{"id": 1, "t": "a"}, {"id": 2, "t": "b"}])
    b, _ = _fonte(monkeypatch, [{"id": 1, "t": "a"}, {"id": 2, "t": "b"}])
    c, _ = _fonte(monkeypatch, [{"id": 1, "t": "a"}, {"id": 2, "t": "MUDOU"}])
    assert a.ref == b.ref
    assert a.ref != c.ref


def test_o_ref_NAO_depende_da_ORDEM_em_que_as_linhas_chegaram(monkeypatch):
    """A mesma tabela, sem uma alteração sequer, devolvida em outra ordem.

    Um `SELECT` sem `ORDER BY` não promete ordem nenhuma, e ela muda na prática
    por troca de plano, por `VACUUM` movendo tuplas, por autovacuum entre duas
    execuções. Com o `ref` dependendo da ordem de chegada, a execução de terça
    produzia uma chave de `data/fila/**` nova e vazia, e toda decisão humana já
    tomada na segunda ficava invisível — as mesmas propostas voltando para
    revisão.
    """
    linhas = [{"id": 1, "t": "a"}, {"id": 2, "t": "b"}, {"id": 3, "t": "c"}]
    segunda, _ = _fonte(monkeypatch, linhas)
    terca, _ = _fonte(monkeypatch, list(reversed(linhas)))
    assert segunda.ref == terca.ref


def test_mas_linhas_DIFERENTES_continuam_dando_refs_diferentes(monkeypatch):
    """A outra metade de content-addressing, e a que o `sorted` poderia ter
    quebrado: ignorar a ordem não pode virar ignorar o conteúdo."""
    a, _ = _fonte(monkeypatch, [{"id": 1, "t": "a"}, {"id": 2, "t": "b"}])
    b, _ = _fonte(monkeypatch, [{"id": 1, "t": "a"}, {"id": 2, "t": "OUTRA"}])
    c, _ = _fonte(monkeypatch, [{"id": 1, "t": "a"}])
    d, _ = _fonte(monkeypatch, [{"id": 1, "t": "a"}, {"id": 1, "t": "a"}])
    assert len({a.ref, b.ref, c.ref, d.ref}) == 4


def test_a_ORDEM_do_POOL_continua_sendo_a_ordem_em_que_as_linhas_chegaram(monkeypatch):
    """O `sorted` é do DIGEST, não das linhas. Ordenar o pool mudaria o que a
    cascata processa primeiro — e o `ref` não tem nada a ver com isso."""
    fonte, _ = _fonte(monkeypatch, [{"id": 9}, {"id": 1}, {"id": 5}])
    assert [i.id for i in fonte.load().items] == ["9", "1", "5"]


def test_o_ref_muda_quando_a_QUERY_muda(monkeypatch):
    a, _ = _fonte(monkeypatch, [{"id": 1}], query="SELECT id FROM a")
    b, _ = _fonte(monkeypatch, [{"id": 1}], query="SELECT id FROM b")
    assert a.ref != b.ref


def test_o_ref_hasheia_a_query_GUARDADA_e_nao_a_crua(monkeypatch):
    """`;` final e comentário `--` são retirados por `_guarda_select`, então as
    três queries EXECUTAM o mesmo statement sobre as mesmas linhas. Hashear a
    query crua dava três `ref` — e três filas de revisão — para um statement
    só."""
    a, _ = _fonte(monkeypatch, [{"id": 1}], query="SELECT id FROM a")
    b, _ = _fonte(monkeypatch, [{"id": 1}], query="SELECT id FROM a;")
    c, _ = _fonte(monkeypatch, [{"id": 1}], query="-- um comentário\nSELECT id FROM a")
    assert a.ref == b.ref == c.ref


def test_ref_e_load_sao_UMA_consulta(monkeypatch):
    """Como o `ArquivoSource` memoiza os bytes: o `ref` nomeia exatamente as
    linhas que viraram trabalho, e o banco não é consultado duas vezes."""
    fonte, conexoes = _fonte(monkeypatch, [{"id": 1}])
    _ = fonte.ref
    fonte.load()
    assert len(conexoes) == 1


def test_erro_do_driver_e_REDUZIDO_a_classe_e_a_mensagem_inteira_vai_ao_log(monkeypatch, caplog):
    """`OperationalError` ecoa host e usuário. A resposta ao cliente leva só a
    classe; o log do servidor leva tudo — é o lugar designado."""

    class OperationalError(Exception):
        pass

    fonte, _ = _fonte(monkeypatch, [], erro=OperationalError(f"could not connect to {SENTINELA}"))
    with caplog.at_level(logging.ERROR, logger="orchestrator.sources"):
        with pytest.raises(FonteFalhou) as erro:
            fonte.load()
    assert str(erro.value) == "consulta falhou: OperationalError"
    assert "SEGREDO-4F2A" not in str(erro.value)
    assert any("SEGREDO-4F2A" in r.getMessage() for r in caplog.records)


def test_erro_de_CONEXAO_e_reduzido_a_classe_e_o_DSN_nao_vaza(monkeypatch, caplog):
    """O ramo que faltava, e é justamente o que ecoa host e usuário.

    O gêmeo acima falha dentro do `cursor.execute` — ramo "consulta falhou". A
    `OperationalError` de CONEXÃO (`could not connect to host … user …`) nasce
    no `connect`, e o ramo que a reduz não tinha teste nenhum: a redução estava
    escrita certa e não estava pinada.
    """

    class OperationalError(Exception):
        pass

    fonte, conexoes = _fonte(
        monkeypatch,
        [],
        erro_de_conexao=OperationalError(
            f'connection failed: could not translate host name to address, dsn="{SENTINELA}"'
        ),
    )
    with caplog.at_level(logging.ERROR, logger="orchestrator.sources"):
        with pytest.raises(FonteFalhou) as erro:
            fonte.load()
    assert str(erro.value) == "conexão falhou: OperationalError"
    # Nem a senha, nem o host, nem o usuário, nem o DSN inteiro.
    assert "SEGREDO-4F2A" not in str(erro.value)
    assert "db.interna" not in str(erro.value) and "usuario" not in str(erro.value)
    assert SENTINELA not in str(erro.value)
    # E o texto inteiro CHEGOU ao log do servidor — o lugar designado. Sem esta
    # linha, "reduzir" seria indistinguível de "perder".
    assert any(
        SENTINELA in r.getMessage() and r.name == "orchestrator.sources"
        for r in caplog.records
    )
    assert conexoes == [SENTINELA]


def test_a_fonte_nao_IMPRIME_nada(monkeypatch, capsys):
    fonte, _ = _fonte(monkeypatch, [{"id": 1}])
    fonte.load()
    saida = capsys.readouterr()
    assert saida.out == "" and saida.err == ""


def test_campo_id_ausente_numa_linha_e_erro_ALTO_com_a_linha(monkeypatch):
    fonte, _ = _fonte(monkeypatch, [{"id": 1}, {"titulo": "sem id"}])
    with pytest.raises(FonteFalhou, match="linha 2"):
        fonte.load()


def _com_teto(monkeypatch, linhas, teto=5):
    monkeypatch.setenv("ERP_DSN", SENTINELA)
    conexao = _Conexao(linhas)
    fonte = PostgresSource(
        dsn_env="ERP_DSN", query="SELECT id FROM t", kind="k", campo_id="id",
        max_linhas=teto, conectar=lambda dsn: conexao,
    )
    return fonte, conexao


def test_teto_de_linhas_recusa_com_motivo(monkeypatch):
    fonte, _ = _com_teto(monkeypatch, [{"id": i} for i in range(6)])
    with pytest.raises(FonteFalhou, match="teto"):
        fonte.load()


def test_o_teto_protege_o_REF_tambem_e_nao_so_o_load(monkeypatch):
    """`ref` não passa por `load()` — é a razão escrita em
    `ArquivoSource._bytes()`. Com o teto só no `load()`, `fonte.ref` devolvia um
    `ref` com SUCESSO sobre 20.000 linhas já trazidas para a memória."""
    fonte, _ = _com_teto(monkeypatch, [{"id": i} for i in range(6)])
    with pytest.raises(FonteFalhou, match="teto"):
        _ = fonte.ref


def test_o_cursor_nunca_e_pedido_por_mais_do_que_o_teto_mais_UM(monkeypatch):
    """`fetchall()` é bufferizado no cliente: uma tabela de 50 M de linhas vira
    50 M de dicts antes de o teto ter voz. O `+ 1` é o mínimo para distinguir
    "encheu" de "estourou"."""
    fonte, conexao = _com_teto(monkeypatch, [{"id": i} for i in range(20_000)], teto=5)
    with pytest.raises(FonteFalhou, match="teto"):
        fonte.load()
    assert conexao.cursor_.pedidas == [6]


def test_um_resultado_EXATAMENTE_no_teto_passa(monkeypatch):
    """Guarda contra over-refusal, e contra um erro de um a mais no `+ 1`."""
    fonte, _ = _com_teto(monkeypatch, [{"id": i} for i in range(5)])
    assert len(fonte.load().items) == 5


def test_sem_o_extra_a_falha_e_ALTA_e_nomeia_o_extra(monkeypatch):
    """Sem `conectar` injetado, o default importa `psycopg` dentro do `load()`.
    Fingir que o módulo não existe é `sys.modules[nome] = None`: o import
    levanta ImportError, e a fonte tem que virar isso em algo legível."""
    monkeypatch.setenv("ERP_DSN", SENTINELA)
    monkeypatch.setitem(__import__("sys").modules, "psycopg", None)
    fonte = PostgresSource(dsn_env="ERP_DSN", query="SELECT 1", kind="k", campo_id="id")
    with pytest.raises(ExtraAusente, match=r"\[fontes\]"):
        fonte.load()


@pytest.mark.skipif(
    not __import__("os").environ.get("TESTE_PG_DSN"),
    reason="integração opcional: defina TESTE_PG_DSN com um Postgres de teste",
)
def test_integracao_OPCIONAL_com_um_postgres_de_verdade(monkeypatch):
    """Nunca exigido pelo CI. Para quem tiver um banco: prova que o default
    `_conectar_padrao` (psycopg em `dict_row`) devolve linhas-dict e que o
    `ref` sai. Um `SELECT` constante não precisa de tabela nenhuma."""
    monkeypatch.setenv("ERP_DSN", __import__("os").environ["TESTE_PG_DSN"])
    fonte = PostgresSource(
        dsn_env="ERP_DSN", query="SELECT 1 AS id, 'a' AS t", kind="k", campo_id="id"
    )
    pool = fonte.load()
    assert [i.id for i in pool.items] == ["1"]
    assert fonte.ref.startswith("pg:ERP_DSN/")
