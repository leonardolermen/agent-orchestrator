"""`orchestrator.toml` e a precedência."""

import pytest

from orchestrator.cli.config import Config, carregar, procurar


def _escrever(pasta, conteudo: str):
    (pasta / "orchestrator.toml").write_text(conteudo, encoding="utf-8")
    return pasta / "orchestrator.toml"


def test_sem_arquivo_tudo_e_default(tmp_path):
    """O default mora no CÓDIGO, junto da guarda que o valida e da derivação
    que o justifica. Ver ADR-11."""
    cfg = carregar(None) if procurar(tmp_path) is None else carregar()

    assert isinstance(cfg, Config)
    assert cfg.model


def test_le_o_modelo_do_arquivo(tmp_path):
    caminho = _escrever(tmp_path, '[providers.anthropic]\ndefault_model = "claude-haiku-4-5"\n')

    assert carregar(caminho).model == "claude-haiku-4-5"


def test_ambiente_VENCE_o_arquivo(tmp_path, monkeypatch):
    """`ANTHROPIC_MODEL` existe para trocar o modelo numa execução sem editar o
    projeto — o caso de quem está comparando dois."""
    caminho = _escrever(tmp_path, '[providers.anthropic]\ndefault_model = "claude-opus-5"\n')
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-5")

    assert carregar(caminho).model == "claude-sonnet-5"


def test_caminho_relativo_e_relativo_ao_ARQUIVO_e_nao_ao_cwd(tmp_path, monkeypatch):
    """Rodar de uma subpasta não pode mudar onde os dados são gravados."""
    caminho = _escrever(tmp_path, '[storage]\nraiz = "dados"\n')
    sub = tmp_path / "workflows"
    sub.mkdir()
    monkeypatch.chdir(sub)

    assert carregar(caminho).raiz_dados == tmp_path / "dados"


def test_procurar_sobe_ate_achar(tmp_path, monkeypatch):
    """Subir é o que permite rodar a CLI de dentro de uma subpasta — que é onde
    alguém está na maior parte do tempo."""
    _escrever(tmp_path, "workflow = 'x'\n")
    fundo = tmp_path / "a" / "b" / "c"
    fundo.mkdir(parents=True)

    assert procurar(fundo) == tmp_path / "orchestrator.toml"


def test_arquivo_malformado_LEVANTA_com_o_caminho(tmp_path):
    """Não é a política de `listar_receitas`, que ignora receita ilegível e
    segue: uma receita ruim é um workflow a menos; um `orchestrator.toml` ruim é
    toda a execução rodando com defaults que ninguém pediu, em silêncio."""
    caminho = _escrever(tmp_path, "isto = não é [toml\n")

    with pytest.raises(ValueError, match="não é TOML válido"):
        carregar(caminho)


def test_secao_ausente_devolve_vazio_em_vez_de_levantar(tmp_path):
    cfg = carregar(_escrever(tmp_path, "workflow = 'x'\n"))

    assert cfg.secao("nao", "existe") == {}
    assert cfg.workflow_padrao == "x"


def test_TOML_e_nao_YAML_porque_tomllib_e_stdlib():
    """`tomllib` entrou no Python 3.11, que é exatamente o piso declarado em
    `requires-python`. YAML custaria `pyyaml` como dependência de RUNTIME num
    pacote que tem uma — e a superfície mínima de dependência está no §2.4 da
    auditoria como ativo, não como acaso."""
    import pathlib
    import tomllib  # noqa: F401

    py = pathlib.Path("pyproject.toml").read_text(encoding="utf-8")
    deps = py.split("dependencies = ")[1].split("\n")[0]

    assert "yaml" not in deps.lower()
    assert deps.count(",") == 0  # uma dependência de runtime, ainda
