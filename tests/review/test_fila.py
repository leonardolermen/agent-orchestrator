import json
from datetime import UTC, datetime

import pytest

from orchestrator.agent.proposal import Confidence, Proposal
from orchestrator.review.decision import Decision, Veredito
from orchestrator.review.fila import Fila, caminho_da_fila, dataset_id
from orchestrator.taxonomy import DivergenceType


def _proposta(divergence_id: str, tipo=DivergenceType.DEFASAGEM_TEMPORAL) -> Proposal:
    return Proposal(
        divergence_id=divergence_id,
        tipo=tipo,
        explicacao="x",
        evidencia=["e"],
        confianca=Confidence.MEDIA,
        acao_sugerida="conciliar_com(l1)",
    )


def _decisao(divergence_id: str, motivo: str = "") -> Decision:
    return Decision(
        divergence_id=divergence_id,
        veredito=Veredito.ACEITAR,
        tipo=DivergenceType.DEFASAGEM_TEMPORAL,
        conciliar_com=frozenset({"l1"}),
        autor="controller@cliente",
        quando=datetime(2026, 9, 15, tzinfo=UTC),
        motivo=motivo,
    )


def test_dataset_id_distingue_sementes():
    # O id `d-b-b00003` existe em TODA semente. Sem este escopo, uma decisão
    # tomada olhando a semente 1 se aplicaria ao b00003 da semente 7, que é
    # outro lançamento.
    assert dataset_id(1, 300, 0.15) != dataset_id(7, 300, 0.15)
    assert dataset_id(1, 300, 0.15) == "s1-n300-t0.15"


def test_caminho_separa_workflows(tmp_path):
    a = caminho_da_fila("conciliacao", "s1-n30-t0.15", raiz=tmp_path)
    b = caminho_da_fila("outro", "s1-n30-t0.15", raiz=tmp_path)

    assert a != b
    assert a.suffix == ".jsonl"


def test_grava_e_le_proposta(tmp_path):
    f = Fila(caminho_da_fila("w", "d", raiz=tmp_path))
    f.gravar_proposta(_proposta("d-1"))

    recarregada = Fila(caminho_da_fila("w", "d", raiz=tmp_path))

    assert recarregada.proposta("d-1") == _proposta("d-1")
    assert [p.divergence_id for p in recarregada.pendentes()] == ["d-1"]


def test_primeira_proposta_vence_e_a_segunda_nem_e_gravada(tmp_path):
    # O agente não se repete. Se uma segunda proposta chegasse, ela apagaria
    # o que o revisor já leu — e o custo de reinvestigar já teria sido pago.
    caminho = caminho_da_fila("w", "d", raiz=tmp_path)
    f = Fila(caminho)
    f.gravar_proposta(_proposta("d-1", DivergenceType.DEFASAGEM_TEMPORAL))
    f.gravar_proposta(_proposta("d-1", DivergenceType.RETENCAO_IMPOSTO))

    assert f.proposta("d-1").tipo is DivergenceType.DEFASAGEM_TEMPORAL
    assert len(caminho.read_text(encoding="utf-8").strip().splitlines()) == 1


def test_ultima_decisao_vence_mas_o_log_guarda_as_duas(tmp_path):
    # Um humano muda de ideia. O estado é a última decisão; a auditoria é
    # todas elas.
    caminho = caminho_da_fila("w", "d", raiz=tmp_path)
    f = Fila(caminho)
    f.gravar_proposta(_proposta("d-1"))
    f.gravar_decisao(_decisao("d-1", motivo="primeira"))
    f.gravar_decisao(_decisao("d-1", motivo="reconsiderei"))

    assert f.decisao("d-1").motivo == "reconsiderei"
    linhas = caminho.read_text(encoding="utf-8").strip().splitlines()
    assert sum(1 for x in linhas if '"decisao"' in x) == 2


def test_pendentes_exclui_o_que_ja_foi_decidido(tmp_path):
    f = Fila(caminho_da_fila("w", "d", raiz=tmp_path))
    f.gravar_proposta(_proposta("d-1"))
    f.gravar_proposta(_proposta("d-2"))
    f.gravar_decisao(_decisao("d-1"))

    assert [p.divergence_id for p in f.pendentes()] == ["d-2"]
    assert [p.divergence_id for p, _ in f.decididas()] == ["d-1"]


def test_fila_vazia_nao_escreve_nada(tmp_path, monkeypatch):
    # A definição padrão usa uma fila vazia. Se ela tocasse o disco, o golden
    # e a CLI passariam a depender de estado fora do processo.
    monkeypatch.chdir(tmp_path)
    f = Fila.vazia()

    assert f.pendentes() == []
    assert f.proposta("qualquer") is None
    assert list(tmp_path.iterdir()) == []


def test_registro_truncado_aponta_arquivo_e_linha(tmp_path):
    # A fila é a trilha de auditoria. Um registro incompleto — um schema mais
    # velho, um campo que só foi adicionado depois — não pode falhar com um
    # KeyError mudo: quem investiga precisa saber QUAL arquivo e QUAL linha.
    caminho = caminho_da_fila("w", "d", raiz=tmp_path)
    caminho.parent.mkdir(parents=True, exist_ok=True)

    decisao_incompleta = decisao_para_dict_sem_autor(_decisao("d-1"))
    linhas = [
        json.dumps({"kind": "proposta", "dados": _proposta_dict("d-1")}),
        json.dumps({"kind": "decisao", "dados": decisao_incompleta}),
    ]
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        Fila(caminho)

    mensagem = str(excinfo.value)
    assert str(caminho) in mensagem
    assert "2" in mensagem
    assert excinfo.value.__cause__ is not None


def _proposta_dict(divergence_id: str) -> dict:
    from orchestrator.review.serial import proposta_para_dict

    return proposta_para_dict(_proposta(divergence_id))


def decisao_para_dict_sem_autor(d: Decision) -> dict:
    from orchestrator.review.serial import decisao_para_dict

    dados = decisao_para_dict(d)
    del dados["autor"]
    return dados
