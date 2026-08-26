#!/usr/bin/env python3
"""
fila_sabia.py — a fila própria da Sábia.

    python3 sabia/bin/fila_sabia.py enfileirar --de 5052079460 --texto "..."
    python3 sabia/bin/fila_sabia.py processar
    python3 sabia/bin/fila_sabia.py registrar-saida --de sabia --texto "..." --ref <id>
    python3 sabia/bin/fila_sabia.py status

POR QUE ESTA FILA EXISTE, E POR QUE ELA NÃO É UM SEGUNDO BOT
------------------------------------------------------------
A Ária tem a fila dela em /opt/aria-bot/{inbox,outbox,sent}, com o token dela. A Sábia é outro
bot (@SabiaAquiBot) e não encosta naquelas pastas. Esta aqui é a dela, e fica dentro do próprio
projeto: sabia/fila/.

O caminho do Telegram NÃO passa por aqui. Quem busca mensagem no Telegram é o próprio gateway do
OpenClaw, com o canal `telegram` em modo polling. Isso é de propósito: a API do Telegram entrega
cada update uma única vez, para um único consumidor. Se este script também chamasse getUpdates
com o mesmo token, os dois brigariam pelo mesmo update e a API responderia 409 Conflict. Um
poller só, e ele é o do OpenClaw.

Esta fila serve para o resto: disparar trabalho para a Sábia a partir de cron, script ou de
outra parte do sistema, sem Telegram no meio, e manter um registro auditável do que entrou e do
que saiu.

TRÊS TRAVAS CONTRA O ECO
------------------------
Já houve incidente nesta operação em que a saída do próprio bot voltou como entrada e virou spam.
Aqui isso é barrado em três lugares:

  1. Origem. Só `5052079460` (Bruna) e `8188614125` (Wagner) são aceitos. Qualquer outra origem é
     descartada em silêncio, sem resposta e sem erro visível. `sabia` nunca é origem válida de
     entrada, então uma resposta dela não pode virar pedido.
  2. Impressão digital. Todo texto que a Sábia produz entra no ledger como `saida` com o sha256
     dele. Uma entrada cujo sha256 já apareça como saída é recusada: ela é eco, não é pedido.
  3. Idempotência. Cada item tem uma chave (`ref`). Chave já vista no ledger não roda de novo,
     mesmo que o arquivo seja recriado.

No caminho do Telegram o eco também é impossível por construção: a API do Telegram não entrega
ao bot as mensagens que o próprio bot enviou. As travas acima cobrem o caminho local.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
FILA = RAIZ / "sabia" / "fila"
ENTRADA = FILA / "entrada"
SAIDA = FILA / "saida"
PROCESSADAS = FILA / "processadas"
LEDGER = FILA / "ledger.jsonl"
CLI = RAIZ / "node_modules" / "openclaw" / "dist" / "index.js"

# As duas únicas origens que existem nesta operação. A mesma lista está no canal do OpenClaw
# (channels.telegram.allowFrom) e na alma da Sábia. Três camadas, de propósito.
AUTORIZADOS = {"5052079460": "Bruna", "8188614125": "Wagner"}

TIMEOUT = int(os.environ.get("SABIA_TIMEOUT", "300"))


def agora() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def digital(texto: str) -> str:
    return hashlib.sha256(texto.strip().encode("utf-8")).hexdigest()


def ler_ledger() -> list[dict]:
    if not LEDGER.exists():
        return []
    linhas = []
    for linha in LEDGER.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        try:
            linhas.append(json.loads(linha))
        except json.JSONDecodeError:
            continue  # linha truncada por escrita interrompida: ignora, não derruba a fila
    return linhas


def anotar(evento: dict) -> None:
    FILA.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(evento, ensure_ascii=False) + "\n")


def cmd_enfileirar(args: argparse.Namespace) -> int:
    de = str(args.de)
    if de not in AUTORIZADOS:
        # Silêncio total: origem não autorizada não gera resposta nem erro visível.
        return 0

    texto = args.texto.strip()
    if not texto:
        print("ERRO: texto vazio.", file=sys.stderr)
        return 1

    ledger = ler_ledger()
    impressao = digital(texto)

    # Trava 2: isto é uma resposta da própria Sábia voltando como pedido?
    if any(e.get("tipo") == "saida" and e.get("sha256") == impressao for e in ledger):
        print("RECUSADO: este texto é uma resposta da própria Sábia. Eco não vira pedido.")
        return 0

    ref = args.ref or f"{int(time.time())}-{impressao[:8]}"

    # Trava 3: chave já processada.
    if any(e.get("ref") == ref and e.get("tipo") == "entrada" for e in ledger):
        print(f"JÁ EXISTE: ref {ref} já está na fila.")
        return 0

    ENTRADA.mkdir(parents=True, exist_ok=True)
    item = {"ref": ref, "de": de, "quem": AUTORIZADOS[de], "texto": texto, "em": agora()}
    (ENTRADA / f"{ref}.json").write_text(
        json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    anotar({"tipo": "entrada", "sha256": impressao, **item})
    print(f"ENFILEIRADO: {ref} ({AUTORIZADOS[de]})")
    return 0


def chamar_sabia(texto: str, ref: str) -> tuple[bool, str]:
    """Roda um turno da Sábia pelo gateway. Sessão própria por item: a fila não é conversa."""
    r = subprocess.run(
        [
            "node", str(CLI), "agent",
            "--agent", "main",
            "--session-key", f"fila-{ref}",
            "--message", texto,
            "--timeout", str(TIMEOUT),
            "--json",
        ],
        capture_output=True, text=True, timeout=TIMEOUT + 60, cwd=str(RAIZ),
    )
    bruto = r.stdout
    inicio = bruto.find("{")
    if inicio == -1:
        return False, (r.stderr or bruto).strip()[:2000]
    try:
        envelope = json.loads(bruto[inicio:])
    except json.JSONDecodeError as e:
        return False, f"envelope ilegível: {e}"

    # O envelope tem dois formatos: rota gateway e queda pro agente embutido.
    payloads = envelope.get("result", {}).get("payloads") or envelope.get("payloads") or []
    texto_saida = "\n".join(p["text"] for p in payloads if p.get("text"))
    if not texto_saida:
        return False, "a Sábia não devolveu texto."
    return True, texto_saida.strip()


def cmd_processar(args: argparse.Namespace) -> int:
    ENTRADA.mkdir(parents=True, exist_ok=True)
    SAIDA.mkdir(parents=True, exist_ok=True)
    PROCESSADAS.mkdir(parents=True, exist_ok=True)

    pendentes = sorted(ENTRADA.glob("*.json"))
    if not pendentes:
        print("nada na fila.")
        return 0

    ledger = ler_ledger()
    ja_respondidos = {e.get("ref") for e in ledger if e.get("tipo") == "saida"}

    for caminho in pendentes:
        item = json.loads(caminho.read_text(encoding="utf-8"))
        ref = item["ref"]

        if str(item.get("de")) not in AUTORIZADOS:
            caminho.unlink()
            continue  # silêncio

        if ref in ja_respondidos:
            print(f"{ref}: já respondido, apenas arquivando.")
            caminho.rename(PROCESSADAS / caminho.name)
            continue

        print(f"{ref}: processando ({item['quem']})...")
        ok, resposta = chamar_sabia(item["texto"], ref)

        if not ok:
            print(f"{ref}: FALHOU: {resposta}")
            anotar({"tipo": "falha", "ref": ref, "erro": resposta, "em": agora()})
            continue  # fica na entrada para nova tentativa

        (SAIDA / f"{ref}.json").write_text(
            json.dumps(
                {"ref": ref, "para": item["de"], "texto": resposta, "em": agora()},
                ensure_ascii=False, indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        # A saída entra no ledger com a impressão digital: é isso que impede o eco depois.
        anotar({
            "tipo": "saida", "ref": ref, "de": "sabia", "para": item["de"],
            "sha256": digital(resposta), "texto": resposta, "em": agora(),
        })
        caminho.rename(PROCESSADAS / caminho.name)
        print(f"{ref}: respondido ({len(resposta)} caracteres)")

    return 0


def cmd_registrar_saida(args: argparse.Namespace) -> int:
    """Registra no ledger um texto que a Sábia entregou por fora da fila (ex: Telegram).

    Serve para a impressão digital dele passar a valer como trava de eco também aqui."""
    texto = args.texto.strip()
    anotar({
        "tipo": "saida", "ref": args.ref or f"externo-{int(time.time())}",
        "de": args.de, "sha256": digital(texto), "texto": texto, "em": agora(),
    })
    print("registrado no ledger.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    ledger = ler_ledger()
    entradas = [e for e in ledger if e.get("tipo") == "entrada"]
    saidas = [e for e in ledger if e.get("tipo") == "saida"]
    falhas = [e for e in ledger if e.get("tipo") == "falha"]

    print(f"fila:        {FILA}")
    print(f"pendentes:   {len(list(ENTRADA.glob('*.json'))) if ENTRADA.exists() else 0}")
    print(f"processadas: {len(list(PROCESSADAS.glob('*.json'))) if PROCESSADAS.exists() else 0}")
    print(f"ledger:      {len(entradas)} entradas, {len(saidas)} saídas, {len(falhas)} falhas")
    if ledger:
        print(f"último:      {ledger[-1].get('em')} ({ledger[-1].get('tipo')})")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Fila própria da Sábia")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("enfileirar", help="põe um pedido na fila")
    e.add_argument("--de", required=True, help="uid de origem (só Bruna ou Wagner)")
    e.add_argument("--texto", required=True)
    e.add_argument("--ref", help="chave de idempotência (default: timestamp + hash)")
    e.set_defaults(func=cmd_enfileirar)

    pr = sub.add_parser("processar", help="roda a Sábia sobre o que está na fila")
    pr.set_defaults(func=cmd_processar)

    rs = sub.add_parser("registrar-saida", help="anota no ledger um texto já entregue")
    rs.add_argument("--de", default="sabia")
    rs.add_argument("--texto", required=True)
    rs.add_argument("--ref")
    rs.set_defaults(func=cmd_registrar_saida)

    st = sub.add_parser("status", help="mostra o estado da fila")
    st.set_defaults(func=cmd_status)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
