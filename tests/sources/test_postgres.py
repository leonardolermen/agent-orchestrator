"""A fonte Postgres: ler é fácil; não escrever, não vazar, e ter `ref` é o trabalho."""

import logging

import pytest

from orchestrator.sources.erros import ExtraAusente, FonteFalhou, VariavelAusente
from orchestrator.sources.postgres import PostgresSource

SENTINELA = "postgresql://usuario:SEGREDO-4F2A@db.interna:5432/erp"


class _Cursor:
    def __init__(self, linhas, erro=None):
        self.linhas, self.erro, self.executadas = linhas, erro, []

    def execute(self, query):
        self.executadas.append(query)
        if self.erro:
            raise self.erro

    def fetchall(self):
        return list(self.linhas)


class _Conexao:
    def __init__(self, linhas, erro=None):
        self.cursor_ = _Cursor(linhas, erro)
        self.fechada = False

    def cursor(self):
        return self.cursor_

    def close(self):
        self.fechada = True


def _fonte(monkeypatch, linhas, *, query="SELECT id, titulo FROM issues", erro=None, env=SENTINELA):
    """Conexão FALSA injetada; nenhum socket. A variável de ambiente recebe o
    sentinela para que qualquer vazamento apareça como texto reconhecível."""
    if env is not None:
        monkeypatch.setenv("ERP_DSN", env)
    else:
        monkeypatch.delenv("ERP_DSN", raising=False)
    conexoes = []

    def conectar(dsn):
        conexoes.append(dsn)
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


def test_o_ref_muda_quando_a_QUERY_muda(monkeypatch):
    a, _ = _fonte(monkeypatch, [{"id": 1}], query="SELECT id FROM a")
    b, _ = _fonte(monkeypatch, [{"id": 1}], query="SELECT id FROM b")
    assert a.ref != b.ref


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


def test_a_fonte_nao_IMPRIME_nada(monkeypatch, capsys):
    fonte, _ = _fonte(monkeypatch, [{"id": 1}])
    fonte.load()
    saida = capsys.readouterr()
    assert saida.out == "" and saida.err == ""


def test_campo_id_ausente_numa_linha_e_erro_ALTO_com_a_linha(monkeypatch):
    fonte, _ = _fonte(monkeypatch, [{"id": 1}, {"titulo": "sem id"}])
    with pytest.raises(FonteFalhou, match="linha 2"):
        fonte.load()


def test_teto_de_linhas_recusa_com_motivo(monkeypatch):
    linhas = [{"id": i} for i in range(6)]
    monkeypatch.setenv("ERP_DSN", SENTINELA)
    fonte = PostgresSource(
        dsn_env="ERP_DSN", query="SELECT id FROM t", kind="k", campo_id="id",
        max_linhas=5, conectar=lambda dsn: _Conexao(linhas),
    )
    with pytest.raises(FonteFalhou, match="teto"):
        fonte.load()


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
