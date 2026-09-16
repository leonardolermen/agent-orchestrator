"""A fachada pública: o que alguém importa sem ler o código."""

import ast
import pathlib

import orchestrator


def test_todo_nome_de___all___existe():
    faltando = [n for n in orchestrator.__all__ if not hasattr(orchestrator, n)]
    assert faltando == []


def test_a_fachada_NAO_exporta_conciliacao():
    """Ela é a implementação de referência (§1.3), mora em
    `orchestrator.conciliacao`, e exportá-la daqui faria todo usuário do
    framework carregar a taxonomia de divergência fiscal brasileira."""
    proibidos = {"DivergenceType", "BankEntry", "LedgerEntry", "Divergence", "reconcile"}

    assert proibidos & set(orchestrator.__all__) == set()
    assert not any(hasattr(orchestrator, n) for n in proibidos)


def test_um_agente_cabe_numa_importacao_so():
    """Se declarar um agente exigisse importar de seis módulos internos, a
    fachada não estaria fazendo o trabalho dela."""
    from orchestrator import (  # noqa: F401
        Agent,
        AgentSpec,
        AgentTask,
        Task,
        Tool,
        ToolRegistry,
        Workflow,
        execute,
        tool_schema,
    )


def test_Tool_e_Workflow_sao_APELIDOS_e_nao_tipos_novos():
    """Os nomes longos dizem o que a coisa É; os curtos são o que alguém
    escreve. Apelido não é conceito novo — mesma razão de `Task()` ser açúcar
    sobre `Stage`."""
    assert orchestrator.Tool is orchestrator.ToolSpec
    assert orchestrator.Workflow is orchestrator.WorkflowDefinition


def test_NENHUM_modulo_interno_importa_a_fachada():
    """Código interno importa o módulo de verdade.

    Importar `orchestrator` de dentro criaria um ciclo em tempo de import (a
    fachada importa quase tudo) e tornaria a ordem de import significativa —
    exatamente o tipo de acoplamento que a catraca de camadas existe para
    barrar, e que ela sozinha não pegaria, porque `orchestrator` não é uma
    camada.
    """
    raiz = pathlib.Path(orchestrator.__file__).parent
    culpados = []
    for arquivo in raiz.rglob("*.py"):
        if arquivo.name == "__init__.py" and arquivo.parent == raiz:
            continue
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            if isinstance(no, ast.ImportFrom) and no.module == "orchestrator":
                culpados.append(f"{arquivo.relative_to(raiz)}:{no.lineno}")
            if isinstance(no, ast.Import) and any(
                a.name == "orchestrator" for a in no.names
            ):
                culpados.append(f"{arquivo.relative_to(raiz)}:{no.lineno}")

    assert culpados == [], (
        "módulos internos importando a fachada:\n  " + "\n  ".join(culpados)
    )


def test_a_fachada_nao_puxa_o_SDK_da_anthropic_no_import():
    """Importar o framework não pode exigir credencial.

    `AnthropicClient` constrói o cliente real na PRIMEIRA CHAMADA, e é por isso
    que ele não está na fachada: quem quer o provider importa
    `orchestrator.agent.anthropic_client`, e quem só quer declarar um workflow
    não paga por isso.

    O caminho é verificado, não afirmado: um docstring meu citava
    `orchestrator.agent.providers`, que NÃO EXISTE — achado ao rodar o agente
    de verdade, não por leitura. Documentação que nomeia um módulo é
    documentação que pode mentir.
    """
    import importlib

    assert not hasattr(orchestrator, "AnthropicClient")
    assert importlib.import_module("orchestrator.agent.anthropic_client")
