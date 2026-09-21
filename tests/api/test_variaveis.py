"""As variáveis que um cliente configura para o workflow alcançar os sistemas dele.

O que estes testes protegem: a CERCA do prefixo (a rota não pode trocar a chave
do servidor nem o PATH), e o fato de o VALOR nunca sair — nem mascarado.
"""

import json
import os

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

import orchestrator.api.ambiente as variaveis  # noqa: E402
import orchestrator.api.app as api_app  # noqa: E402
from orchestrator.api.app import app  # noqa: E402

cliente = TestClient(app)


@pytest.fixture(autouse=True)
def _isolada(tmp_path, monkeypatch):
    """Raiz própria E ambiente próprio: sem isso um teste deixaria um segredo no
    `data/` de quem rodou a suíte e uma variável viva no processo."""
    monkeypatch.setattr(api_app, "_RAIZ_AMBIENTE", tmp_path / "ambiente")
    for k in [k for k in os.environ if k.startswith(variaveis.PREFIXO)]:
        monkeypatch.delenv(k, raising=False)


# --- a cerca ---------------------------------------------------------------


@pytest.mark.parametrize(
    "nome",
    [
        "ANTHROPIC_API_KEY",
        "PATH",
        "AWS_SECRET_ACCESS_KEY",
        "wf_minuscula",
        "WF-TRACO",
        "SEM_PREFIXO",
    ],
)
def test_nome_FORA_da_cerca_e_recusado(nome):
    """Sem a cerca, esta rota trocaria a chave do servidor por outra, apontaria
    o PATH para outro binário, ou vazaria que variáveis existem na máquina."""
    r = cliente.put(f"/api/ambiente/variaveis/{nome}", json={"valor": "x"})

    assert r.status_code == 422
    assert nome in r.json()["detail"]
    assert os.environ.get(nome) != "x"


def test_a_listagem_NAO_mostra_variavel_de_fora_da_cerca(monkeypatch):
    monkeypatch.setenv("SEGREDO_DO_HOSPEDEIRO", "nao-pode-aparecer")

    nomes = [v["nome"] for v in cliente.get("/api/ambiente/variaveis").json()]

    assert "SEGREDO_DO_HOSPEDEIRO" not in nomes


# --- o valor nunca sai -----------------------------------------------------


def test_definir_e_listar_NUNCA_devolve_o_valor():
    """Nem mascarado: um valor mascarado ainda vaza o COMPRIMENTO, e o
    comprimento de um token identifica o provedor."""
    cliente.put("/api/ambiente/variaveis/WF_TOKEN_ERP", json={"valor": "sk-segredo-123"})

    corpo = cliente.get("/api/ambiente/variaveis").text

    assert "sk-segredo-123" not in corpo
    assert '"nome":"WF_TOKEN_ERP"' in corpo.replace(" ", "")
    assert '"definida":true' in corpo.replace(" ", "")


# --- o efeito, que é o ponto -----------------------------------------------


def test_definir_faz_o_PROCESSO_enxergar():
    """É o que faz o próximo run funcionar: o bloco `entrada` lê `os.environ`."""
    cliente.put("/api/ambiente/variaveis/WF_TOKEN_ERP", json={"valor": "abc"})

    assert os.environ["WF_TOKEN_ERP"] == "abc"


def test_definir_PERSISTE_no_disco(tmp_path):
    """Um cliente não reconfigura o token a cada restart do servidor."""
    cliente.put("/api/ambiente/variaveis/WF_TOKEN_ERP", json={"valor": "abc"})

    gravado = json.loads(
        (tmp_path / "ambiente" / "variaveis.json").read_text(encoding="utf-8")
    )

    assert gravado == {"WF_TOKEN_ERP": "abc"}


def test_carregar_NAO_sobrescreve_o_ambiente_de_quem_hospeda(tmp_path, monkeypatch):
    """Um `export` antes de subir diz algo mais forte que um arquivo. Um arquivo
    antigo apagando isso em silêncio seria a pior surpresa possível."""
    raiz = tmp_path / "ambiente"
    raiz.mkdir(parents=True)
    (raiz / "variaveis.json").write_text(
        json.dumps({"WF_A": "do-disco", "WF_B": "do-disco"}), encoding="utf-8"
    )
    monkeypatch.setenv("WF_A", "do-shell")

    variaveis.carregar(raiz)

    assert os.environ["WF_A"] == "do-shell"
    assert os.environ["WF_B"] == "do-disco"


def test_um_arquivo_editado_a_mao_NAO_escapa_da_cerca(tmp_path):
    """Filtra na LEITURA também: `PATH` escrito à mão no arquivo não pode virar
    um `os.environ['PATH']` só porque ninguém validou o que já estava lá."""
    raiz = tmp_path / "ambiente"
    raiz.mkdir(parents=True)
    (raiz / "variaveis.json").write_text(
        json.dumps({"PATH": "/mal", "WF_OK": "bom"}), encoding="utf-8"
    )
    antes = os.environ.get("PATH")

    variaveis.carregar(raiz)

    assert os.environ.get("PATH") == antes
    assert os.environ["WF_OK"] == "bom"


# --- remover ---------------------------------------------------------------


def test_remover_tira_do_processo_e_do_disco(tmp_path):
    cliente.put("/api/ambiente/variaveis/WF_TOKEN_ERP", json={"valor": "abc"})

    assert cliente.delete("/api/ambiente/variaveis/WF_TOKEN_ERP").status_code == 204
    assert "WF_TOKEN_ERP" not in os.environ
    assert json.loads(
        (tmp_path / "ambiente" / "variaveis.json").read_text(encoding="utf-8")
    ) == {}


def test_remover_inexistente_e_404():
    assert cliente.delete("/api/ambiente/variaveis/WF_NAO_EXISTE").status_code == 404


def test_valor_vazio_e_recusado():
    """Vazio e ausente são a mesma coisa para quem lê, e guardar um vazio faria
    a tela dizer "definida" sobre nada."""
    r = cliente.put("/api/ambiente/variaveis/WF_X", json={"valor": ""})

    assert r.status_code == 422
