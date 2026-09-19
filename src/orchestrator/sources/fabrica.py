"""Uma fonte a partir de parâmetros planos — o que o bloco de entrada recebe.

`api/app.py::_fonte_de` já monta fonte, mas a partir de um `RunRequest`: um
objeto tipado, com uma união discriminada que o Pydantic já validou. O bloco de
entrada não tem isso — ele recebe o que a tela digitou, no mesmo formato plano
de todo parâmetro de regra.

**`sintetica` também não está.** Ela é a fonte de BENCHMARK, e mora em
`domains/reconciliation/synth/` — um domínio. `sources` importa só o kernel, e
ninguém importa `domains`: uma entrada que dependesse de um domínio faria a
camada genérica conhecer um específico, que é o defeito que a arquitetura
inteira existe para impedir. Benchmark continua sendo escolha de quem roda.

**`arquivo` NÃO está aqui, e a razão é concreta.** `ArquivoSource` precisa de uma
RAIZ — o diretório sob o qual o caminho é resolvido, e a cerca que impede um
`../../etc` de sair dele. Essa raiz é configuração do SERVIDOR, não da
composição: um workflow que a carregasse poderia ser gravado apontando para
qualquer lugar do disco de quem o executa. Enquanto a raiz não tiver como chegar
aqui sem vir do arquivo gravado, entrada por arquivo continua sendo escolha de
quem aperta rodar.
"""

from typing import Any

from orchestrator.kernel.source import Source

_TIPOS = ("postgres", "http")


def fonte_de_parametros(p: dict[str, Any]) -> Source:
    """A fonte que estes parâmetros descrevem, ou levanta dizendo o que falta."""
    tipo = str(p.get("tipo", "")).strip()
    if tipo not in _TIPOS:
        raise ValueError(
            f"fonte de tipo {tipo!r}: use um de {list(_TIPOS)}. `arquivo` não "
            f"entra num workflow gravado — a raiz sob a qual o caminho é "
            f"resolvido é configuração do servidor, e um workflow que a "
            f"carregasse apontaria para o disco de quem o executa"
        )

    exigidos = ("kind", "campo_id")
    faltam = [c for c in exigidos if not str(p.get(c, "")).strip()]
    if tipo == "postgres":
        faltam += [c for c in ("dsn_env", "query") if not str(p.get(c, "")).strip()]
    else:
        faltam += [c for c in ("url",) if not str(p.get(c, "")).strip()]
    if faltam:
        raise ValueError(
            f"fonte {tipo!r} precisa de {faltam} preenchido(s). sem eles ela não "
            f"tem como buscar, nem como dizer que tipo de item entregou"
        )

    if tipo == "postgres":
        from orchestrator.sources.postgres import PostgresSource

        return PostgresSource(
            dsn_env=str(p["dsn_env"]),
            query=str(p["query"]),
            kind=str(p["kind"]),
            campo_id=str(p["campo_id"]),
        )

    from orchestrator.sources.http import HttpSource

    # `token_env` é o NOME da variável de ambiente, nunca o token. Vazio vira
    # `None`, que é "API sem autenticação" — e é diferente de string vazia, que
    # o `HttpSource` leria como uma variável chamada "".
    token = str(p.get("token_env", "")).strip() or None
    return HttpSource(
        url=str(p["url"]),
        token_env=token,
        kind=str(p["kind"]),
        campo_id=str(p["campo_id"]),
        caminho=str(p.get("caminho", "")),
    )


__all__ = ["fonte_de_parametros"]
