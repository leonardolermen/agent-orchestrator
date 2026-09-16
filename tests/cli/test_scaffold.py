"""`orchestrator init`: o projeto tem de RODAR, não de ser preenchido.

O primeiro feedback que alguém tem do framework é se ele executa. Um scaffold
com `raise NotImplementedError` transfere para a primeira hora do usuário o
trabalho de descobrir a forma — e, com a regra dos três usos suspensa (§1.3),
feedback de quem chega de fora é o substituto que sobrou para validar a
abstração.

Estes testes rodam o projeto gerado DE VERDADE, num subprocesso: um scaffold que
só é verificado por `assert arquivo.exists()` é um scaffold que quebra sem
ninguém ver.
"""

import subprocess
import sys

import pytest

from orchestrator.cli.scaffold import criar


@pytest.fixture
def projeto(tmp_path):
    return criar("demo", tmp_path)


def _rodar(projeto, *args: str) -> subprocess.CompletedProcess:
    import orchestrator

    src = str(__import__("pathlib").Path(orchestrator.__file__).parents[2])
    env = {
        "PYTHONPATH": f"{src}{';' if sys.platform == 'win32' else ':'}{projeto}",
        "PYTHONIOENCODING": "utf-8",
        "PATH": __import__("os").environ.get("PATH", ""),
        "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
    }
    return subprocess.run(
        [sys.executable, *args],
        cwd=projeto,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


def test_o_workflow_do_projeto_novo_RODA(projeto):
    """O critério do M5, e ele é um subprocesso, não uma asserção sobre
    arquivos."""
    r = _rodar(projeto, "-m", "workflows.triagem")

    assert r.returncode == 0, r.stderr
    assert "estado: concluido" in r.stdout


def test_a_cascata_do_projeto_novo_resolve_de_graca_antes_de_gastar(projeto):
    """A regra roda antes do agente porque é `CostClass.REGRA`, não porque o
    exemplo a escreveu primeiro."""
    r = _rodar(projeto, "-m", "workflows.triagem")

    assert "resolvido de graça: 1" in r.stdout
    assert "proposto pelo agente: 2" in r.stdout


def test_o_projeto_novo_imprime_a_arvore_de_trace(projeto):
    """Observabilidade sai de graça: o exemplo assina o barramento em três
    linhas e ganha a árvore inteira."""
    r = _rodar(projeto, "-m", "workflows.triagem")

    assert "resolver palavra-chave" in r.stdout
    assert "custo total: US$" in r.stdout


def test_os_testes_do_projeto_novo_PASSAM(projeto):
    """Um scaffold que vem com teste quebrado ensina que teste quebrado é
    normal."""
    r = _rodar(projeto, "-m", "pytest", "tests", "-q")

    assert r.returncode == 0, r.stdout + r.stderr
    assert "2 passed" in r.stdout


def test_o_projeto_novo_nao_gasta_dinheiro(projeto):
    """`FakeLLMClient` no exemplo, e trocar por `AnthropicClient` é UMA linha.

    Um scaffold que gasta ao rodar pela primeira vez é a pior surpresa possível
    — e é a mesma regra que a API já segue: não é flag, é ausência de caminho.
    """
    fonte = (projeto / "workflows" / "triagem.py").read_text(encoding="utf-8")

    assert "FakeLLMClient" in fonte
    assert "AnthropicClient" not in fonte.split('"""')[2]  # só no docstring


def test_o_scaffold_recusa_sobrescrever(tmp_path):
    """Mesmo cuidado de `gravar_receita`, que não deixa um id existente ser
    substituído — ali porque mudaria o significado de decisões já gravadas,
    aqui porque apagaria o trabalho de alguém."""
    criar("demo", tmp_path)

    with pytest.raises(FileExistsError, match="já existe"):
        criar("demo", tmp_path)


def test_data_nao_e_versionado_mas_avaliacoes_sao(projeto):
    """A decisão de ativo do projeto, visível na árvore.

    `data/` é saída (runs, traces, filas). `avaliacoes/casos/` é o conjunto de
    avaliação — o que o §1.1 do spec pai chama de "a coisa que um concorrente
    não copia", e por isso vai para o git.
    """
    gitignore = (projeto / ".gitignore").read_text(encoding="utf-8")

    assert "data/" in gitignore
    assert "avaliacoes" not in gitignore
    assert (projeto / "avaliacoes" / "casos").is_dir()


def test_existe_uma_pasta_de_dominio(projeto):
    """Diferença deliberada do scaffold do CrewAI, que é `agents.yaml` +
    `tasks.yaml` porque lá o domínio é o texto do prompt.

    Aqui o domínio é código tipado, e a pasta existe para dizer, na ESTRUTURA,
    que o que é determinístico não mora num YAML de prompt.
    """
    assert (projeto / "dominio" / "modelo.py").is_file()
    assert "@dataclass(frozen=True)" in (
        projeto / "dominio" / "modelo.py"
    ).read_text(encoding="utf-8")
