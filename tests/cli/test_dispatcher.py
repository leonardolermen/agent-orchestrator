"""O despachante, e a invocação que o CI trava."""

import pytest

from orchestrator.cli.main import main


def test_a_invocacao_LEGADA_continua_valendo(capsys):
    """O job `conciliador` do CI roda `orchestrator --seed 1 --n 500` e faz
    `grep` da linha do percentual. Quebrar isso apagaria o único check que
    transforma regressão de qualidade em CI vermelho."""
    assert main(["--seed", "1", "--n", "60"]) == 0

    saida = capsys.readouterr().out
    assert "Taxa determinística (lado bancário):" in saida


def test_sem_argumento_nenhum_tambem_e_legado(capsys):
    """`orchestrator` sozinho sempre rodou o benchmark com os defaults, e há
    quem tenha isso num script."""
    assert main([]) == 0
    assert "Taxa determinística" in capsys.readouterr().out


def test_a_regra_do_despachante_e_UMA_linha(capsys):
    """Primeiro argumento começando com `-` é legado.

    Sem lista de nomes antigos para manter em sincronia, e sem colisão possível
    entre subcomando novo e flag antiga — que é o que uma lista produziria no
    dia em que alguém criasse um subcomando chamado `seed`.
    """
    assert main(["--taxa-divergencia", "0.1", "--n", "40"]) == 0
    assert "Taxa determinística" in capsys.readouterr().out


def test_bench_produz_a_MESMA_saida_da_invocacao_legada(capsys):
    main(["--seed", "3", "--n", "60"])
    legado = capsys.readouterr().out

    main(["bench", "--seed", "3", "--n", "60"])
    subcomando = capsys.readouterr().out

    # Duas formatações que precisassem concordar seriam o join frágil de
    # sempre; `bench` delega para o `main` antigo em vez de reimplementar.
    assert legado == subcomando


def test_version_nao_estoura_rodando_do_source(capsys):
    assert main(["version"]) == 0
    assert capsys.readouterr().out.strip()


def test_workflows_lista_com_versao_e_classes(capsys):
    assert main(["workflows"]) == 0

    saida = capsys.readouterr().out
    assert "conciliacao" in saida
    assert "REGRA" in saida and "HUMANO" in saida


def test_workflows_mostra_a_cascata_NA_ORDEM_QUE_RODA(capsys):
    """`ordered()`, não `cascade`. Mostrar a ordem autoral seria desenhar uma
    coisa e executar outra — a decoração que o §3.5 do spec de composição nomeia
    como modo de falha."""
    assert main(["workflows", "conciliacao"]) == 0

    linhas = [
        linha.strip()
        for linha in capsys.readouterr().out.splitlines()
        if linha.startswith("    ")
    ]
    classes = [linha.split()[0] for linha in linhas]
    assert classes == sorted(classes, key=["REGRA", "AGENTE", "CREW", "HUMANO"].index)


def test_workflow_desconhecido_lista_os_disponiveis(capsys):
    assert main(["workflows", "nao-existe"]) == 1
    assert "disponíveis" in capsys.readouterr().err


def test_help_mostra_os_subcomandos_em_vez_do_benchmark(capsys):
    """Melhoria, não quebra: quem roda `--help` está procurando o que existe."""
    with pytest.raises(SystemExit):
        main(["--help"])

    saida = capsys.readouterr().out
    assert "init" in saida and "trace" in saida
    # E a invocação antiga continua documentada, para quem a procurar.
    assert "Invocação antiga" in saida


def test_workflows_lista_tambem_as_COMPOSICOES_do_canvas(tmp_path, monkeypatch, capsys):
    """A CLI e a API respondem a MESMA pergunta.

    `descrever(cfg.raiz_receitas)` lia só receitas: uma composição salva pelo
    canvas — que a API lista e roda por `/runs` — fazia
    `orch workflows <id>` responder "workflow desconhecido". É exatamente a
    divergência contra a qual o docstring de `registry()` existe, e por isso a
    `Config` ganhou `raiz_composicoes` ao lado de `raiz_receitas`.
    """
    from datetime import UTC, datetime

    from orchestrator.authoring.composicao import BlocoRegra, Composicao, gravar
    from orchestrator.cli import comandos
    from orchestrator.cli.config import Config

    composicoes = tmp_path / "composicoes"
    composicoes.mkdir()
    gravar(
        Composicao(
            id="do-canvas", nome="Do canvas", gerado_em=datetime.now(UTC),
            blocos=(BlocoRegra(nome="L1", parametros={}),),
        ),
        composicoes,
    )
    cfg = Config(
        raiz_dados=tmp_path,
        raiz_receitas=tmp_path / "receitas",
        raiz_composicoes=composicoes,
    )
    monkeypatch.setattr(comandos, "_config", lambda: cfg)

    assert main(["workflows", "do-canvas"]) == 0
    assert "Do canvas" in capsys.readouterr().out

    # E uma config SÓ de receitas continua igual ao que era: a composição não
    # aparece, porque a raiz não foi dita.
    monkeypatch.setattr(
        comandos, "_config", lambda: Config(raiz_receitas=tmp_path / "receitas")
    )
    assert main(["workflows", "do-canvas"]) == 1
    assert "desconhecido" in capsys.readouterr().err
