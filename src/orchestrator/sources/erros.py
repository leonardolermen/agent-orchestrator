"""Os erros que uma fonte conectada levanta — e que a borda vira em 422.

Uma hierarquia própria, e não `ValueError` solto, por dois motivos. O primeiro
é a borda: `api/app.py::_ler` precisa distinguir "a fonte recusou, e a mensagem
é para o cliente" de "o servidor quebrou" — a primeira é 422 com o texto
inteiro, a segunda é 500. O segundo é o segredo: toda mensagem destas classes é
escrita para ser DEVOLVIDA ao cliente, então nenhuma delas pode carregar DSN,
token ou o que o driver ecoou. Quem constrói uma, reduz antes.
"""


class ErroDeFonte(ValueError):
    """Base. A mensagem é segura para devolver ao cliente."""


class VariavelAusente(ErroDeFonte):
    """A variável de ambiente que guardaria o segredo não existe no servidor.

    A mensagem cita o NOME — é a única coisa que o cliente pediu e a única que
    ele precisa para consertar.
    """

    def __init__(self, nome: str) -> None:
        self.nome = nome
        super().__init__(f"a variável de ambiente {nome!r} não existe no servidor")


class ExtraAusente(ErroDeFonte):
    """O driver do extra `[fontes]` não está instalado. Alto, não 500."""

    def __init__(self, pacote: str) -> None:
        super().__init__(
            f"a fonte precisa de {pacote!r}, que não está instalado: "
            f"instale o extra [fontes] (pip install '.[fontes]')"
        )


class FonteFalhou(ErroDeFonte):
    """A fonte recusou ou falhou, com mensagem já reduzida para o cliente."""
