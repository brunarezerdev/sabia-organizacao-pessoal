"""Interface de linha de comando.

Comandos:

    python -m sop diagnostico          # o que está configurado e o que falta
    python -m sop agentes              # lista os agentes carregados
    python -m sop classificar "texto"  # classifica sem gravar nada
    python -m sop processar "texto"    # fluxo completo (grava de verdade)
    python -m sop escutar              # long polling do Telegram
    python -m sop worker               # consome a fila durável
    python -m sop demo                 # roda os exemplos fictícios, sem rede
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .agentes import carregar_registro
from .automacao import Automacao
from .config import Config, ConfiguracaoAusente
from .fila import Fila
from .integracoes.ia import criar_adaptador
from .modelos import Mensagem
from .orquestradora import Orquestradora

RAIZ = Path(__file__).resolve().parents[2]


def _montar(config: Config, com_fila: bool = False) -> Automacao:
    """Monta o grafo de objetos, ligando só as integrações configuradas."""
    registro = carregar_registro()
    fila = Fila(config.fila_dir) if com_fila else None
    orquestradora = Orquestradora(criar_adaptador(config), registro, fila)

    banco = None
    if config.pronta("notion"):
        from .integracoes.notion import ClienteNotion

        banco = ClienteNotion(config)

    agenda = None
    if config.pronta("google_calendar"):
        from .integracoes.google_calendar import ClienteGoogleCalendar

        agenda = ClienteGoogleCalendar(config)

    notificar = None
    if config.pronta("telegram"):
        from .integracoes.telegram import ClienteTelegram

        notificar = ClienteTelegram(config).confirmar

    return Automacao(orquestradora, banco=banco, agenda=agenda, notificar=notificar)


# -- comandos ---------------------------------------------------------------


def cmd_diagnostico(config: Config, _args: argparse.Namespace) -> int:
    print("Sistema Operacional Pessoal — diagnóstico de configuração\n")
    diagnostico = config.diagnostico()
    for integracao, faltantes in diagnostico.items():
        if faltantes:
            print(f"  [ ] {integracao:<16} falta: {', '.join(faltantes)}")
        else:
            print(f"  [x] {integracao:<16} pronta")

    registro = carregar_registro()
    print(f"\n  agentes carregados: {len(registro)} ({', '.join(registro.nomes())})")

    if any(diagnostico.values()):
        print(
            "\nO sistema roda mesmo assim: sem chave de IA usa o classificador\n"
            "heurístico local, e sem Notion/Agenda só deixa de gravar.\n"
            "Para configurar: cp .env.example .env e preencha as variáveis."
        )
    else:
        print("\nTudo configurado.")
    return 0


def cmd_agentes(_config: Config, _args: argparse.Namespace) -> int:
    registro = carregar_registro()
    if not len(registro):
        print("Nenhum agente encontrado em agentes/.")
        return 1
    for agente in registro:
        agenda = "cria evento" if agente.cria_evento else "sem agenda"
        print(f"{agente.nome:<14} {agente.titulo:<22} [{agenda}]")
        print(f"{'':<14} domínio: {agente.dominio}")
        print(f"{'':<14} categorias: {', '.join(agente.categorias)}\n")
    return 0


def cmd_classificar(config: Config, args: argparse.Namespace) -> int:
    orquestradora = Orquestradora(criar_adaptador(config), carregar_registro())
    mensagem = Mensagem(id="cli", texto=args.texto, canal="cli")
    classificacao, item = orquestradora.processar(mensagem)
    print(json.dumps(classificacao.para_dict(), ensure_ascii=False, indent=2))
    if orquestradora.deve_criar_evento(classificacao):
        print(f"\n-> viraria evento na agenda em {item.data} {item.hora or ''}".rstrip())
    return 0


def cmd_processar(config: Config, args: argparse.Namespace) -> int:
    automacao = _montar(config)
    resultado = automacao.executar(Mensagem(id="cli", texto=args.texto, canal="cli"))
    print(Automacao.montar_resposta(resultado))
    return 0 if resultado.sucesso else 1


def cmd_escutar(config: Config, args: argparse.Namespace) -> int:
    from .integracoes.telegram import ClienteTelegram

    telegram = ClienteTelegram(config)
    automacao = _montar(config, com_fila=True)
    fila = automacao.orquestradora.fila
    assert fila is not None

    print("Escutando o Telegram. Ctrl+C para parar.")
    offset: int | None = None
    while True:
        try:
            mensagens, offset = telegram.mensagens(offset)
            for mensagem in mensagens:
                tarefa_id = automacao.orquestradora.despachar(mensagem)
                print(f"  recebida {mensagem.id} -> fila {tarefa_id}")
            if args.processar:
                for resultado in automacao.processar_fila():
                    print(f"  processada: {resultado.resumo()}")
        except KeyboardInterrupt:
            print("\nEncerrado.")
            return 0
        except Exception as erro:  # noqa: BLE001 — o loop não pode morrer
            print(f"  erro no ciclo: {erro}", file=sys.stderr)
            time.sleep(5)


def cmd_worker(config: Config, args: argparse.Namespace) -> int:
    automacao = _montar(config, com_fila=True)
    fila = automacao.orquestradora.fila
    assert fila is not None

    orfas = fila.recuperar_orfas()
    if orfas:
        print(f"Recuperadas {len(orfas)} tarefas órfãs.")

    print(f"Worker ativo. Fila: {fila.estatisticas()}. Ctrl+C para parar.")
    while True:
        try:
            resultados = automacao.processar_fila(limite=args.limite)
            for resultado in resultados:
                print(f"  {resultado.resumo()}")
            if not resultados:
                time.sleep(2)
        except KeyboardInterrupt:
            print("\nEncerrado.")
            return 0


def cmd_demo(config: Config, _args: argparse.Namespace) -> int:
    """Roda os exemplos fictícios sem tocar em nenhuma API externa."""
    caminho = RAIZ / "exemplos" / "mensagens.json"
    exemplos = json.loads(caminho.read_text(encoding="utf-8"))
    orquestradora = Orquestradora(criar_adaptador(config), carregar_registro())

    print(f"Rodando {len(exemplos)} mensagens de exemplo (nada é gravado).\n")
    for exemplo in exemplos:
        mensagem = Mensagem(id=exemplo["id"], texto=exemplo["texto"], canal="demo")
        classificacao, item = orquestradora.processar(mensagem)
        marca = "!" if classificacao.precisa_confirmacao else " "
        quando = f" [{item.data}{' ' + item.hora if item.hora else ''}]" if item.data else ""
        print(f'{marca} "{exemplo["texto"]}"')
        print(f"    -> {classificacao.agente}/{classificacao.categoria}: {item.titulo}{quando}")
        if classificacao.agente == exemplo.get("agente_esperado"):
            print("    -> confere com o esperado\n")
        else:
            print(f"    -> esperado: {exemplo.get('agente_esperado')}\n")
    return 0


# -- entrada ----------------------------------------------------------------


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sop", description="Sistema Operacional Pessoal"
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    sub.add_parser("diagnostico", help="mostra o que está configurado")
    sub.add_parser("agentes", help="lista os agentes carregados")
    sub.add_parser("demo", help="roda os exemplos fictícios, sem rede")

    p = sub.add_parser("classificar", help="classifica um texto sem gravar")
    p.add_argument("texto")

    p = sub.add_parser("processar", help="fluxo completo: classifica e grava")
    p.add_argument("texto")

    p = sub.add_parser("escutar", help="long polling do Telegram")
    p.add_argument(
        "--processar",
        action="store_true",
        help="processa a fila no mesmo loop (sem worker separado)",
    )

    p = sub.add_parser("worker", help="consome a fila durável")
    p.add_argument("--limite", type=int, default=10)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    config = Config.do_ambiente()

    comandos = {
        "diagnostico": cmd_diagnostico,
        "agentes": cmd_agentes,
        "classificar": cmd_classificar,
        "processar": cmd_processar,
        "escutar": cmd_escutar,
        "worker": cmd_worker,
        "demo": cmd_demo,
    }
    try:
        return comandos[args.comando](config, args)
    except ConfiguracaoAusente as erro:
        print(f"\n{erro}\n", file=sys.stderr)
        print("Rode `python -m sop diagnostico` para ver tudo que falta.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
