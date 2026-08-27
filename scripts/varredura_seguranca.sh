#!/usr/bin/env bash
# Varredura de padrões sensíveis no repositório inteiro.
#
# Este repositório é entregue à faculdade e pode se tornar público. Nenhum dado
# real pode entrar. Rode antes de todo commit:
#
#     bash scripts/varredura_seguranca.sh
#
# Sai com código 1 se encontrar qualquer ocorrência.

set -uo pipefail
cd "$(dirname "$0")/.." || exit 2

ACHADOS=0
# Só arquivos versionados. Os dois arquivos que DEFINEM os padrões sensíveis
# (este script e o teste de segurança) ficam de fora — senão a varredura
# encontraria as próprias regras e falharia sempre.
#
# O package-lock.json também fica de fora, pela mesma razão que node_modules:
# é metadado gerado pelo npm, não código que passa por review aqui. Além
# disso, a versão semver de um pacote ("ip-address": "10.2.0") casa com o
# padrão de IP privado e produzia falso positivo em série.
EXCLUIR='^(scripts/varredura_seguranca\.sh|tests/test_seguranca\.py|package-lock\.json)$'
ARQUIVOS=$(git ls-files 2>/dev/null | grep -vE "$EXCLUIR" \
  || find . -type f \
       -not -path './.git/*' -not -path './.venv/*' -not -path './venv/*' \
       -not -path '*/__pycache__/*' -not -path './.pytest_cache/*' \
       -not -path './.fila/*' \
       -not -name 'varredura_seguranca.sh' -not -name 'test_seguranca.py')

# checar <rótulo> <padrão> [regex de caminhos dispensados deste padrão]
#
# A dispensa é do PADRÃO naquele caminho, não do arquivo: quem for dispensado de
# uma regra continua sendo varrido por todas as outras.
checar() {
  local rotulo="$1" padrao="$2" dispensa="${3:-}"
  local alvos="$ARQUIVOS" saida
  if [ -n "$dispensa" ]; then
    alvos=$(printf '%s\n' "$ARQUIVOS" | grep -vE "$dispensa")
  fi
  saida=$(printf '%s\n' "$alvos" | xargs -r grep -nEI "$padrao" 2>/dev/null)
  if [ -n "$saida" ]; then
    echo "  [FALHOU] $rotulo"
    printf '%s\n' "$saida" | sed 's/^/      /'
    ACHADOS=$((ACHADOS + 1))
  else
    echo "  [ok]     $rotulo"
  fi
}

echo "Varredura de segurança — $(pwd)"
echo

echo "1. Credenciais e chaves de API"
checar "token de bot do Telegram"    '[0-9]{8,10}:[A-Za-z0-9_-]{30,}'
checar "chave da Anthropic"          'sk-ant-[A-Za-z0-9_-]{10,}'
checar "chave da OpenAI"             'sk-[A-Za-z0-9]{40,}'
checar "token de integração Notion"  '\b(ntn|secret)_[A-Za-z0-9]{30,}'
checar "token do GitHub"             'gh[pousr]_[A-Za-z0-9]{30,}'
checar "chave privada PEM"           'BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY'
checar "client_secret preenchido"    'client_secret["'"'"']?\s*[:=]\s*["'"'"'][A-Za-z0-9_-]{10,}'
checar "refresh_token preenchido"    'refresh_token["'"'"']?\s*[:=]\s*["'"'"'][A-Za-z0-9_/-]{20,}'
checar "senha em texto claro"        '(senha|password|passwd)\s*[:=]\s*["'"'"'][^"'"'"' ]{6,}'
checar "arquivo de sessão"           '\bsession[._-][a-z]*\.(txt|json|dat)|cookies?\.txt'

echo
echo "2. Identificadores pessoais"
# Exige separador de formatação: um timestamp Unix não é telefone.
checar "telefone brasileiro"         '(\+55[ -]?)?\(?[0-9]{2}\)?[ -]9?[0-9]{4}[ -][0-9]{4}\b'
checar "CPF"                         '\b[0-9]{3}\.[0-9]{3}\.[0-9]{3}-[0-9]{2}\b'
checar "CNPJ"                        '\b[0-9]{2}\.[0-9]{3}\.[0-9]{3}/[0-9]{4}-[0-9]{2}\b'
checar "RG"                          '\bRG\s*[:nº]*\s*[0-9]{7,}'
checar "uid numérico longo"          '\b(uid|chat_id|user_id)\s*[:=]\s*[0-9]{9,}'
checar "IBAN / agência e conta"      '\b(ag[êe]ncia|conta corrente|iban)\b\s*[:=]?\s*[0-9]'
checar "cartão de crédito"           '\b[0-9]{4}[ -][0-9]{4}[ -][0-9]{4}[ -][0-9]{4}\b'

echo
echo "3. Contexto que não pertence a um repositório público"
# Caminho absoluto de máquina revela usuário e estrutura do host de origem.
#
# Dispensados só deste padrão: `sabia/` e `docs/estrutura-sabia.md`, que
# documentam a implantação real numa VPS. Ali os caminhos são o conteúdo — onde
# o gateway lê a fila, onde ficam as almas dos agentes. O código entregue
# (src/, scripts/, tests/, agentes/) continua sem nenhum caminho de máquina.
checar "caminho absoluto de host"    '(^|[^a-zA-Z0-9])/(opt|home|Users|srv)/[A-Za-z0-9_.-]+/' \
       '^(sabia/|docs/estrutura-sabia\.md$)'
checar "e-mail pessoal real"         '[A-Za-z0-9._%+-]+@(gmail|hotmail|outlook|yahoo|icloud|proton)\.[A-Za-z]{2,}'
checar "URL de banco de dados"       '(postgres|postgresql|mysql|mongodb)://[^ "'"'"']*:[^ "'"'"']*@'
checar "IP privado explícito"        '\b(10|192\.168|172\.(1[6-9]|2[0-9]|3[01]))\.[0-9]{1,3}\.[0-9]{1,3}\b'

echo
if [ "$ACHADOS" -eq 0 ]; then
  echo "RESULTADO: limpo. Nenhum padrão sensível encontrado."
  exit 0
fi
echo "RESULTADO: $ACHADOS categoria(s) com ocorrência. NÃO COMMITE antes de resolver."
exit 1
