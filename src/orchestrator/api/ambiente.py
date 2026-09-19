"""As variáveis que um workflow usa para alcançar os sistemas do cliente.

Um bloco `Input` que lê um Postgres recebe `dsn_env` — o NOME de uma variável de
ambiente — e nunca a string de conexão. Um que lê uma API recebe `token_env`. A
indireção existe desde as fontes conectadas, e o motivo é o de sempre: o
workflow gravado em `data/` não pode carregar segredo, porque ele é lido,
versionado e mostrado na tela.

Faltava o outro lado: alguém precisa DEFINIR essas variáveis. Até aqui isso era
`export` no shell de quem sobe o servidor — o que serve para quem hospeda e não
serve para um cliente configurando o próprio workflow.

**Só nomes com o prefixo `WF_`, e a cerca é o ponto.** Sem ela, esta rota
escreveria `ANTHROPIC_API_KEY` (trocando a chave do servidor por outra),
`PATH` (executando outro binário) ou `AWS_SECRET_ACCESS_KEY`. E a LISTAGEM
revelaria que variáveis existem na máquina, que já é informação útil para quem
sonda. Com a cerca, o pior caso é o cliente estragar a própria configuração.

**O VALOR nunca sai daqui.** Nenhuma rota o devolve, nem mascarado: um valor
mascarado ainda vaza o comprimento, e o comprimento de um token identifica o
provedor. A tela mostra "definida" ou "ausente", que é o mesmo que a seção
Ambiente já fazia com a chave da Anthropic.

**O que este módulo NÃO resolve, e é maior do que ele.** O arquivo guarda
segredo em CLARO. Cifrar não ajudaria sozinho — a chave para decifrar teria de
ficar do lado, e um disco lido continua lido. O que protegeria de verdade é (a)
permissão de arquivo — pedida aqui, e que o Windows ignora (ver `_gravar_disco`)
— e (b) autenticação no servidor, que NÃO existe: hoje quem alcança a porta
pode escrever o segredo de qualquer cliente, e LER nenhum, mas escrever já
basta para apontar um workflow do cliente para o servidor de outra pessoa.
Enquanto for assim, este servidor é de uso próprio ou de rede confiável, e isso
está dito no README.
"""

import json
import os
import re
import stat
from pathlib import Path

_RAIZ_PADRAO = Path("data") / "ambiente"
_ARQUIVO = "variaveis.json"

# O prefixo é obrigatório e a forma é fechada: letras maiúsculas, dígitos e `_`.
# Fechada porque um nome é usado como chave de `os.environ` — e nomes esquisitos
# (espaço, `=`, minúscula) produzem variáveis que o processo enxerga de um jeito
# e o shell de outro.
PREFIXO = "WF_"
_FORMA = re.compile(r"^WF_[A-Z0-9_]+$")


class NomeRecusado(ValueError):
    """O nome não cabe na cerca. Mensagem própria porque ela é a explicação."""


def validar(nome: str) -> str:
    if not _FORMA.match(nome):
        raise NomeRecusado(
            f"{nome!r} não serve: a tela só define variáveis que começam com "
            f"{PREFIXO!r}, em maiúsculas (ex.: WF_TOKEN_ERP). A cerca existe "
            f"para que esta rota não possa trocar a chave do servidor nem o "
            f"PATH do processo"
        )
    return nome


def _arquivo(raiz: Path | None = None) -> Path:
    return (raiz or _RAIZ_PADRAO) / _ARQUIVO


def _ler_disco(raiz: Path | None = None) -> dict[str, str]:
    caminho = _arquivo(raiz)
    if not caminho.exists():
        return {}
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    # Filtra na LEITURA também, e não só na escrita: um arquivo editado à mão
    # com `PATH` dentro não pode virar um `os.environ["PATH"]` só porque
    # ninguém validou o que já estava lá.
    return {k: str(v) for k, v in dados.items() if _FORMA.match(k)}


def _gravar_disco(valores: dict[str, str], raiz: Path | None = None) -> None:
    caminho = _arquivo(raiz)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(valores, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    try:
        # Pede "só o dono lê e escreve". Vale no POSIX e é o caso comum e barato
        # de fechar: o outro usuário da mesma máquina.
        #
        # **No Windows isto NÃO protege**, e medi: o arquivo sai `644`, porque
        # quem manda lá é a ACL do NTFS e `chmod` só mexe no bit de
        # somente-leitura. Não levantar é deliberado — recusar a gravação
        # trocaria "segredo com permissão frouxa" por "workflow que não roda" —,
        # mas quem hospeda no Windows precisa fechar a pasta `data/` por fora.
        # Está dito no README, junto com o buraco maior (não há autenticação).
        caminho.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def carregar(raiz: Path | None = None) -> int:
    """Põe o que está no disco no ambiente do processo. Devolve quantas.

    Chamado no boot. Não SOBRESCREVE o que já veio do ambiente de quem hospeda:
    quem faz `export WF_TOKEN=...` antes de subir o servidor está dizendo algo
    mais forte que um arquivo, e um arquivo antigo apagando isso em silêncio
    seria a pior surpresa possível.
    """
    postas = 0
    for nome, valor in _ler_disco(raiz).items():
        if nome not in os.environ:
            os.environ[nome] = valor
            postas += 1
    return postas


def nomes(raiz: Path | None = None) -> list[str]:
    """Os nomes conhecidos, do disco e do ambiente. Nunca os valores."""
    do_ambiente = {k for k in os.environ if _FORMA.match(k)}
    return sorted(do_ambiente | set(_ler_disco(raiz)))


def definida(nome: str) -> bool:
    return bool(os.environ.get(nome, "").strip())


def definir(nome: str, valor: str, raiz: Path | None = None) -> None:
    """Define no processo E no disco, nesta ordem de importância.

    No processo porque é o que faz o próximo run enxergar; no disco porque um
    cliente não reconfigura o token a cada restart.
    """
    validar(nome)
    if not valor:
        raise ValueError(
            f"{nome}: valor vazio. Para remover, apague a variável — vazio e "
            f"ausente são a mesma coisa para quem lê, e guardar um vazio faria "
            f"a tela dizer 'definida' sobre nada"
        )
    os.environ[nome] = valor
    valores = _ler_disco(raiz)
    valores[nome] = valor
    _gravar_disco(valores, raiz)


def remover(nome: str, raiz: Path | None = None) -> bool:
    """Tira do processo e do disco. `True` se existia em algum dos dois."""
    validar(nome)
    valores = _ler_disco(raiz)
    tinha = valores.pop(nome, None) is not None
    tinha = os.environ.pop(nome, None) is not None or tinha
    _gravar_disco(valores, raiz)
    return tinha


__all__ = [
    "PREFIXO",
    "NomeRecusado",
    "carregar",
    "definida",
    "definir",
    "nomes",
    "remover",
    "validar",
]
