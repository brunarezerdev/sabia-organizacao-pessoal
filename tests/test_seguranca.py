"""Testes de segurança do próprio repositório.

Este repositório pode se tornar público. Estes testes falham se algum dado
sensível ou credencial entrar no versionamento — a varredura roda como parte
da suíte, não só como script manual.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]

IGNORAR_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".fila",
    "node_modules",
}
# Este arquivo e a varredura contêm os padrões por definição.
IGNORAR_ARQUIVOS = {"test_seguranca.py", "varredura_seguranca.sh"}

PADROES_PROIBIDOS = {
    "token de bot do Telegram": r"[0-9]{8,10}:[A-Za-z0-9_-]{30,}",
    "chave da Anthropic": r"sk-ant-[A-Za-z0-9_-]{10,}",
    "chave da OpenAI": r"sk-[A-Za-z0-9]{40,}",
    "token do Notion": r"\b(ntn|secret)_[A-Za-z0-9]{30,}",
    "token do GitHub": r"gh[pousr]_[A-Za-z0-9]{30,}",
    "chave privada": r"BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY",
    "CPF": r"\b[0-9]{3}\.[0-9]{3}\.[0-9]{3}-[0-9]{2}\b",
    "CNPJ": r"\b[0-9]{2}\.[0-9]{3}\.[0-9]{3}/[0-9]{4}-[0-9]{2}\b",
    "cartão de crédito": r"\b[0-9]{4}[ -][0-9]{4}[ -][0-9]{4}[ -][0-9]{4}\b",
    "telefone brasileiro": r"\(?[0-9]{2}\)?[ -]9[0-9]{4}[ -][0-9]{4}",
    "uid numérico longo": r"\b(uid|chat_id|user_id)\s*[:=]\s*[0-9]{9,}",
    # Caminho absoluto revela o usuário e a estrutura da máquina de origem.
    "caminho absoluto de host": r"(^|[^a-zA-Z0-9])/(opt|home|Users|srv)/[A-Za-z0-9_.-]+/",
    "e-mail pessoal": r"[A-Za-z0-9._%+-]+@(gmail|hotmail|outlook|yahoo|icloud|proton)\.[A-Za-z]{2,}",
    "URL de banco com senha": r"(postgres|postgresql|mysql|mongodb)://[^ \"']*:[^ \"']*@",
}


def arquivos_do_repo() -> list[Path]:
    """Os arquivos que entrariam no versionamento — nem mais, nem menos.

    A varredura em `scripts/varredura_seguranca.sh` já pergunta ao git; este
    teste passou a fazer o mesmo para não divergir dela. Percorrer a pasta
    inteira olhava também o que o .gitignore exclui: o `.env` da máquina, que
    o próprio README manda criar, e as dezenas de milhares de arquivos de
    `node_modules/`, que são código de terceiros e não passam por review aqui.

    `--others --exclude-standard` mantém no radar o arquivo novo ainda não
    adicionado: ele ainda não está versionado, mas está a um `git add` de
    entrar, que é exatamente o momento em que este teste precisa falhar.
    """
    resultado = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        capture_output=True,
        text=True,
        cwd=RAIZ,
        check=False,
    )
    if resultado.returncode != 0:  # fora de um repositório git
        return _varrer_pasta()

    caminhos = []
    for relativo in resultado.stdout.split("\0"):
        if not relativo or Path(relativo).name in IGNORAR_ARQUIVOS:
            continue
        caminho = RAIZ / relativo
        if caminho.is_file():
            caminhos.append(caminho)
    return caminhos


def _varrer_pasta() -> list[Path]:
    """Alternativa quando não há git: percorre a pasta ignorando o conhecido."""
    caminhos: list[Path] = []
    for caminho in RAIZ.rglob("*"):
        if not caminho.is_file():
            continue
        if any(parte in IGNORAR_DIRS for parte in caminho.parts):
            continue
        if caminho.name in IGNORAR_ARQUIVOS:
            continue
        caminhos.append(caminho)
    return caminhos


def ler(caminho: Path) -> str:
    try:
        return caminho.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


@pytest.mark.parametrize("rotulo,padrao", sorted(PADROES_PROIBIDOS.items()))
def test_nenhum_dado_sensivel_no_repo(rotulo, padrao):
    regex = re.compile(padrao)
    ocorrencias = [
        f"{caminho.relative_to(RAIZ)}: {regex.search(ler(caminho)).group(0)[:40]}"
        for caminho in arquivos_do_repo()
        if regex.search(ler(caminho))
    ]
    assert not ocorrencias, f"{rotulo} encontrado em: {ocorrencias}"


def test_env_example_tem_todas_as_variaveis_vazias():
    """O modelo de configuração não pode conter nenhum valor real."""
    texto = (RAIZ / ".env.example").read_text(encoding="utf-8")
    sensiveis = (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID_AUTORIZADO",
        "NOTION_TOKEN",
        "NOTION_DATABASE_ID",
        "ANTHROPIC_API_KEY",
        "GOOGLE_CREDENTIALS_PATH",
        "GOOGLE_TOKEN_PATH",
    )
    for variavel in sensiveis:
        achado = re.search(rf"^{variavel}=(.*)$", texto, re.MULTILINE)
        assert achado, f"{variavel} ausente do .env.example"
        assert achado.group(1).strip() == "", f"{variavel} tem valor preenchido"


def test_env_real_nao_esta_versionado():
    assert not (RAIZ / ".env").exists() or ".env" in (RAIZ / ".gitignore").read_text(
        encoding="utf-8"
    )


def test_gitignore_bloqueia_o_essencial():
    texto = (RAIZ / ".gitignore").read_text(encoding="utf-8")
    for padrao in (".env", "*.key", "*.pem", "token.json", "credentials.json"):
        assert padrao in texto, f"{padrao} não está no .gitignore"


def test_nenhum_arquivo_de_credencial_no_disco():
    proibidos = ("credentials.json", "token.json", "client_secret.json", ".env")
    encontrados = [
        str(c.relative_to(RAIZ)) for c in arquivos_do_repo() if c.name in proibidos
    ]
    assert not encontrados, f"arquivos de credencial presentes: {encontrados}"


def test_varredura_do_script_passa():
    """O script de varredura é a fonte de verdade — roda de verdade aqui."""
    script = RAIZ / "scripts" / "varredura_seguranca.sh"
    resultado = subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, cwd=RAIZ
    )
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr


def test_exemplos_nao_tem_dado_real():
    """Os exemplos precisam ser fictícios e genéricos."""
    texto = (RAIZ / "exemplos" / "mensagens.json").read_text(encoding="utf-8")
    assert "R$" in texto  # tem valores, mas...
    for padrao in PADROES_PROIBIDOS.values():
        assert not re.search(padrao, texto)
