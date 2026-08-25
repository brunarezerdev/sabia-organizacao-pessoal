"""Interface de linha de comando.

Comandos:

    python -m sop diagnostico          # o que está configurado e o que falta
    python -m sop agentes              # lista os agentes carregados
    python -m sop classificar "texto"  # classifica sem gravar nada
    python -m sop processar "texto"    # fluxo completo (grava de verdade)
    python -m sop escutar              # long polling do Telegram
    python -m sop worker               # consome a fila durável
    python -m sop demo                 # roda os exemplos fictícios, sem rede
    python -m sop regras               # lista as regras se-então carregadas
    python -m sop ritual               # monta o pacote do ritual de domingo
    python -m sop simular              # ritual de ponta a ponta, sem rede
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

from .agentes import carregar_registro
from .automacao import Automacao
from .config import Config, ConfiguracaoAusente
from .fila import Fila
from .integracoes.ia import criar_adaptador
from .modelos import Mensagem
from .orquestradora import Orquestradora
from .regras import (
    MotorDeRegras,
    estoque_de_lista,
    eventos_do_google,
    regras_de_lista,
    regras_do_notion,
)
from .ritual import Ritual, domingo_de

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


# -- ritual de domingo e motor de regras ------------------------------------


def _exemplos(nome: str) -> object:
    return json.loads((RAIZ / "exemplos" / nome).read_text(encoding="utf-8"))


def _carregar_motor(config: Config) -> tuple[MotorDeRegras, str]:
    """Monta o motor com as regras do Notion, ou com os exemplos fictícios.

    Sem a base de Regras configurada o sistema não trava: ele avisa e roda com
    os exemplos, para que dê para ver o motor funcionando antes de configurar.
    """
    if config.pronta("regras"):
        from .integracoes.notion import ClienteNotion

        cliente = ClienteNotion(config)
        return MotorDeRegras(regras_do_notion(cliente.regras())), "Notion"

    faltando = ", ".join(config.faltando("regras"))
    print(
        f"Aviso: base de Regras não configurada (falta {faltando}). "
        "Usando exemplos/regras.json.",
        file=sys.stderr,
    )
    return MotorDeRegras(regras_de_lista(_exemplos("regras.json"))), "exemplos"


def _domingo(args: argparse.Namespace) -> date:
    if getattr(args, "domingo", None):
        return date.fromisoformat(args.domingo)
    return domingo_de(date.today())


def cmd_regras(config: Config, _args: argparse.Namespace) -> int:
    motor, fonte = _carregar_motor(config)
    if not len(motor):
        print("Nenhuma regra cadastrada.")
        return 1

    print(f"{len(motor)} regra(s) carregada(s) de: {fonte}\n")
    for regra in motor.regras:
        marca = "ativa " if regra.ativa else "parada"
        print(f"[{marca}] {regra.nome}  ({regra.area or 'sem área'}, {regra.origem})")
        print(f"          se    {regra.se}")
        for texto, ordem in regra.acoes():
            grau = "então" if ordem == 1 else "  e aí"
            print(f"          {grau} {texto}")
        if regra.antecedencia_dias:
            print(f"          prazo {regra.antecedencia_dias} dia(s) antes")
        print(f"          pega  {', '.join(regra.palavras_chave) or '(sem palavra-chave)'}\n")
    return 0


def _publicar(config: Config, pacote, args: argparse.Namespace) -> None:
    """Manda o pacote para o Notion e para o Telegram, se pedirem."""
    if args.publicar:
        if not (config.pronta("notion") and config.notion_ritual_page_id):
            print(
                "Aviso: para publicar defina NOTION_TOKEN e NOTION_RITUAL_PAGE_ID.",
                file=sys.stderr,
            )
        else:
            from .integracoes.notion import ClienteNotion

            enviados = ClienteNotion(config).anexar_blocos(
                config.notion_ritual_page_id, pacote.para_blocos_notion()
            )
            print(f"\n{enviados} blocos acrescentados na página do ritual.")

    if args.telegram:
        if not config.pronta("telegram"):
            print("Aviso: Telegram não configurado, nada foi enviado.", file=sys.stderr)
        else:
            from .integracoes.telegram import ClienteTelegram

            ClienteTelegram(config).confirmar(pacote.para_telegram())
            print("\nPacote enviado pelo Telegram.")


def cmd_ritual(config: Config, args: argparse.Namespace) -> int:
    """Fecha a semana que terminou e abre a que começa."""
    motor, _ = _carregar_motor(config)

    agenda = None
    if config.pronta("google_calendar"):
        from .integracoes.google_calendar import ClienteGoogleCalendar

        agenda = ClienteGoogleCalendar(config)
    else:
        print(
            "Aviso: Google Agenda não configurada, o ritual sai sem compromissos.",
            file=sys.stderr,
        )

    pacote = Ritual(motor, agenda=agenda).pacote(_domingo(args))
    print(pacote.para_telegram())
    _publicar(config, pacote, args)
    return 0


def cmd_simular(config: Config, args: argparse.Namespace) -> int:
    """Ritual completo com a semana fictícia de exemplos/, sem tocar em rede."""
    dados = _exemplos("semana.json")
    motor = MotorDeRegras(regras_de_lista(_exemplos("regras.json")))
    domingo = date.fromisoformat(args.domingo or dados["domingo"])

    pacote = Ritual(motor).pacote(
        domingo,
        eventos_passados=eventos_do_google(dados["semana_que_terminou"]),
        eventos_futuros=eventos_do_google(dados["semana_que_comeca"]),
        estoque=estoque_de_lista(dados["estoque"]),
    )

    print("Simulação com dados fictícios. Nenhuma API é chamada aqui.\n")
    print(pacote.para_telegram())
    print("\n" + "-" * 70)
    print("Rastro de cada tarefa derivada, para conferência:")
    for tarefa in pacote.abertura.efeitos + pacote.abertura.alertas_estoque:
        grau = "efeito de 2a ordem" if tarefa.condicional else "efeito direto"
        print(f"  {tarefa.prazo or 'sem prazo'}  {grau:<18} {tarefa.titulo}")
        print(f"              regra: {tarefa.regra} | gatilho: {tarefa.gatilho}")
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

    sub.add_parser("regras", help="lista as regras se-então carregadas")

    p = sub.add_parser("ritual", help="monta o pacote do ritual de domingo")
    p.add_argument("--domingo", help="data do ritual (AAAA-MM-DD). Padrão: o próximo domingo")
    p.add_argument("--publicar", action="store_true", help="anexa o pacote na página do Notion")
    p.add_argument("--telegram", action="store_true", help="envia o pacote pelo Telegram")

    p = sub.add_parser("simular", help="ritual de ponta a ponta com dados fictícios")
    p.add_argument("--domingo", help="data do ritual (AAAA-MM-DD)")

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
        "regras": cmd_regras,
        "ritual": cmd_ritual,
        "simular": cmd_simular,
    }
    try:
        return comandos[args.comando](config, args)
    except ConfiguracaoAusente as erro:
        print(f"\n{erro}\n", file=sys.stderr)
        print("Rode `python -m sop diagnostico` para ver tudo que falta.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
