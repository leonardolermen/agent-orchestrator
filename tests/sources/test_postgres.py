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


def test_valores_de_TIPOS_diferentes_com_o_mesmo_TEXTO_nao_colapsam(monkeypatch):
    """`default=str` colapsava conteúdo genuinamente diferente no mesmo digest.

    Uma coluna `numeric` devolve `Decimal("1")`; uma `text`, a string `"1"`. Uma
    `date` devolve `date(2026, 9, 20)`; uma `text`, `"2026-09-20"`. Com `str` no
    meio, os quatro viravam dois textos e os dois pares compartilhavam o `ref` —
    o mesmo dano do ETag fraco na fonte HTTP, do outro lado do espelho: dois
    conjuntos distintos dividindo o `dataset` de `data/fila/**`, e uma decisão
    tomada sobre um casada com os itens do outro.
    """
    from datetime import date
    from decimal import Decimal

    numerico, _ = _fonte(monkeypatch, [{"id": 1, "v": Decimal("1")}])
    texto, _ = _fonte(monkeypatch, [{"id": 1, "v": "1"}])
    data, _ = _fonte(monkeypatch, [{"id": 1, "v": date(2026, 9, 20)}])
    data_em_texto, _ = _fonte(monkeypatch, [{"id": 1, "v": "2026-09-20"}])
    assert len({numerico.ref, texto.ref, data.ref, data_em_texto.ref}) == 4


def test_mas_o_MESMO_valor_nao_nativo_continua_dando_o_MESMO_ref(monkeypatch):
    """A outra metade: distinguir tipos não pode virar um `ref` que muda sozinho
    entre duas leituras iguais — seria trocar um órfão por outro."""
    from decimal import Decimal

    a, _ = _fonte(monkeypatch, [{"id": 1, "v": Decimal("1.50")}])
    b, _ = _fonte(monkeypatch, [{"id": 1, "v": Decimal("1.50")}])
    c, _ = _fonte(monkeypatch, [{"id": 1, "v": Decimal("1.5")}])
    assert a.ref == b.ref
    # E `Decimal("1.50")` != `Decimal("1.5")`: a escala É conteúdo numa coluna
    # `numeric`, e o texto de cada um a preserva.
    assert a.ref != c.ref


@pytest.mark.parametrize(
    "forjado",
    [
        {"Decimal": "1"},
        # A forja que REALMENTE funcionava. O tipo `json` (ao contrário do
        # `jsonb`) guarda o texto verbatim e aceita o escape de byte nulo; o
        # loader do psycopg roda `json.loads`, e o escape vira um byte nulo de
        # verdade dentro da chave. A marca prefixada por byte nulo fechava o
        # `jsonb` e não fechava este — `chr(0)` aqui é exatamente o que uma
        # coluna `json` entrega.
        {chr(0) + "Decimal": "1"},
    ],
    ids=["sem-prefixo", "com-o-prefixo-vindo-de-uma-coluna-json"],
)
def test_uma_coluna_json_nao_consegue_FORJAR_a_marca_de_tipo(monkeypatch, forjado):
    """Marca não pode ser uma FORMA que o dado consiga ter.

    Enquanto a marca era uma chave especial, bastava o dado conter aquela chave
    — e o tipo `json` deixa. A propriedade só vale porque hoje TODO valor é
    marcado: o objeto de uma coluna `json` sai como `["dict", …]` e a marca é a
    posição no par, que é nossa, não uma chave que alguém possa escrever.
    """
    from decimal import Decimal

    de_verdade, _ = _fonte(monkeypatch, [{"id": 1, "v": Decimal("1")}])
    imitacao, _ = _fonte(monkeypatch, [{"id": 1, "v": forjado}])
    assert de_verdade.ref != imitacao.ref


def test_tipos_NATIVOS_diferentes_tambem_nao_colapsam(monkeypatch):
    """O outro lado da mesma falha: `default=` nunca é chamado para tipo nativo,
    então nenhuma marca chegava a eles. Um composto `ROW(1,2)` vira `tuple` e um
    `int[]` vira `list`; `1` e `1.0` são `integer` e `double precision`; `"1"` e
    `1` são `text` e `integer`. Todos davam o mesmo texto JSON."""
    lista, _ = _fonte(monkeypatch, [{"id": 1, "v": [1, 2]}])
    tupla, _ = _fonte(monkeypatch, [{"id": 1, "v": (1, 2)}])
    inteiro, _ = _fonte(monkeypatch, [{"id": 1, "v": 1}])
    flutuante, _ = _fonte(monkeypatch, [{"id": 1, "v": 1.0}])
    booleano, _ = _fonte(monkeypatch, [{"id": 1, "v": True}])
    texto, _ = _fonte(monkeypatch, [{"id": 1, "v": "1"}])
    assert len({lista.ref, tupla.ref, inteiro.ref, flutuante.ref, booleano.ref, texto.ref}) == 6


def test_a_marca_sobrevive_a_PROFUNDIDADE(monkeypatch):
    """A recursão é o que estende a propriedade a um `json` aninhado — sem ela,
    a marca valeria no primeiro nível e o colapso voltaria no segundo."""
    from decimal import Decimal

    fundo_decimal, _ = _fonte(monkeypatch, [{"id": 1, "v": {"a": {"b": [Decimal("1")]}}}])
    fundo_texto, _ = _fonte(monkeypatch, [{"id": 1, "v": {"a": {"b": ["1"]}}}])
    assert fundo_decimal.ref != fundo_texto.ref


def test_bytea_nao_traz_ENDERECO_de_memoria_para_o_ref(monkeypatch):
    """`str(memoryview(b"ab"))` é `<memory at 0x…>`: o endereço mudaria o `ref`
    entre duas leituras idênticas. Bytes viram hex, que é conteúdo."""
    a, _ = _fonte(monkeypatch, [{"id": 1, "v": memoryview(b"ab")}])
    b, _ = _fonte(monkeypatch, [{"id": 1, "v": memoryview(b"ab")}])
    c, _ = _fonte(monkeypatch, [{"id": 1, "v": memoryview(b"ac")}])
    assert a.ref == b.ref and a.ref != c.ref
    assert "0x" not in a.ref.split("@")[1]


def test_chaves_de_TIPOS_diferentes_no_mesmo_dicionario_nao_quebram_o_ref(monkeypatch):
    """Guarda contra um `sorted` ingênuo: `1 < "a"` levanta `TypeError` em
    Python 3, e o digest não pode depender da ordem de iteração do dict."""
    fonte, _ = _fonte(monkeypatch, [{"id": 1, "v": {1: "a", "1": "b", None: "c"}}])
    assert fonte.ref.startswith("pg:ERP_DSN/")


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


def _psycopg_falso(monkeypatch):
    """Um `psycopg` de mentira em `sys.modules`, para que `_conectar_padrao` — o
    ÚNICO caminho que fala com o driver de verdade — possa ser exercitado sem
    driver e sem socket. É a mesma técnica de
    `test_sem_o_extra_a_falha_e_ALTA_e_nomeia_o_extra`, com um módulo no lugar
    de `None`. Devolve o dicionário com o que `connect` recebeu.
    """
    import sys
    import types

    capturado: dict = {}
    psycopg = types.ModuleType("psycopg")
    rows = types.ModuleType("psycopg.rows")
    rows.dict_row = object()
    psycopg.rows = rows

    def connect(dsn, **kwargs):
        capturado["dsn"] = dsn
        capturado.update(kwargs)
        return object()

    psycopg.connect = connect
    monkeypatch.setitem(sys.modules, "psycopg", psycopg)
    monkeypatch.setitem(sys.modules, "psycopg.rows", rows)
    return capturado


def test_a_conexao_de_verdade_leva_o_relogio_de_CONEXAO(monkeypatch):
    """Sem `connect_timeout`, um banco que não responde prende a requisição
    (e uma conexão do parceiro) por quanto o SO quiser."""
    from orchestrator.sources import postgres as mod

    capturado = _psycopg_falso(monkeypatch)
    mod._conectar_padrao("postgresql://u:s@h/db")
    assert capturado["connect_timeout"] == mod.CONEXAO_TIMEOUT_S


def test_a_conexao_de_verdade_leva_o_relogio_do_SERVIDOR(monkeypatch):
    """`statement_timeout` é o único dos dois que interrompe um `pg_sleep(60)`
    que já começou — quem o cancela é o Postgres. `_guarda_select` deixa
    `SELECT pg_sleep(60)` passar, e a query vem de um campo de texto na tela."""
    from orchestrator.sources import postgres as mod

    capturado = _psycopg_falso(monkeypatch)
    mod._conectar_padrao("postgresql://u:s@h/db")
    assert capturado["options"] == f"-c statement_timeout={mod.STATEMENT_TIMEOUT_MS}"
    # E o DSN continua chegando inteiro: o relógio não pode ter comido nada.
    assert capturado["dsn"] == "postgresql://u:s@h/db"


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
