# Segurança

Este repositório é entregue como trabalho acadêmico e pode se tornar público.
O modelo de segurança tem duas frentes: proteger o sistema em execução e
garantir que nenhum dado real entre no versionamento.

---

## 1. Credenciais

### Onde ficam

**Em lugar nenhum do repositório.** Tudo vem de variáveis de ambiente, lidas de
um `.env` que está no `.gitignore` desde o primeiro commit. O `.env.example`
documenta cada variável, com todos os valores vazios — há um teste que falha se
alguma aparecer preenchida.

### Bloqueio por padrão

O `.gitignore` bloqueia famílias inteiras de arquivo, não casos específicos:

```
.env*                 exceto .env.example
*.key *.pem *.p12     chaves privadas
credentials.json      OAuth do Google
token*.json           tokens de acesso
*session*.txt         sessões
secrets/ .secrets/    diretórios de segredo
dados/ data/ vault/   dados reais
```

A lógica é que um arquivo novo de credencial provavelmente cai em um padrão
existente. Bloquear por exceção depende de lembrar de cada caso.

### Ciclo de vida por API

| API | Credencial | Onde vive | Rotação |
|---|---|---|---|
| Telegram | Token de bot | `.env` | `/revoke` no @BotFather |
| Notion | Token de integração | `.env` | Regerar em my-integrations |
| Anthropic | Chave de API | `.env` | Regerar no console |
| Google | Refresh token | arquivo separado, `chmod 600` | Revogar em myaccount.google.com/permissions |

O Google é o único que não guarda a credencial de longo prazo no `.env` — o
refresh token fica em arquivo próprio, fora do repositório, com permissão 600. O
access token, que é o que efetivamente autentica as chamadas, existe apenas em
memória e é renovado a cada sessão.

---

## 2. Controle de acesso na captura

Um bot do Telegram é endereçável por **qualquer pessoa** que descubra seu nome.
Sem controle, qualquer um poderia inserir dados no sistema.

O cliente resolve isso em `ClienteTelegram.autorizada()`: só converte em
mensagem processável o que vier do `chat_id` configurado em
`TELEGRAM_CHAT_ID_AUTORIZADO`. Qualquer outra origem é descartada **em
silêncio** — sem resposta que confirmasse ao remetente que o bot existe e está
ativo.

```python
def autorizada(self, update):
    chat_id = str(update.get("message", {}).get("chat", {}).get("id", ""))
    return bool(chat_id) and chat_id == str(self.config.telegram_chat_autorizado)
```

Testes: `test_telegram_aceita_apenas_o_chat_autorizado`.

---

## 3. Vazamento por log e por exceção

O token do Telegram viaja **no caminho da URL**, não em header. Isso significa
que qualquer exceção de rede que inclua a URL vaza a credencial para o log.

Dois controles:

1. `_url()` é a única função que toca o token. Nada mais o concatena.
2. Erros da API propagam apenas o campo `description` devolvido pelo Telegram,
   que não contém a URL.

```python
if not corpo.get("ok"):
    # A descrição do Telegram não contém o token; é seguro propagar.
    raise RuntimeError(f"Telegram recusou {metodo}: {corpo.get('description')}")
```

Teste: `test_token_nao_vaza_no_erro` verifica que o token não aparece na
mensagem da exceção.

---

## 4. Escopo mínimo

O fluxo OAuth do Google pede **apenas** `https://www.googleapis.com/auth/calendar`.
Não pede Drive, Gmail nem perfil. Se o token vazar, o dano fica contido ao
calendário.

A integração do Notion enxerga **apenas** as páginas explicitamente
compartilhadas com ela dentro do Notion. Um token vazado não dá acesso ao
workspace inteiro — só à database que foi conectada.

---

## 5. Dados sensíveis no repositório

### Varredura automática

```bash
bash scripts/varredura_seguranca.sh
```

Verifica todos os arquivos versionados contra três grupos de padrão:

**Credenciais** — token de bot do Telegram, chave da Anthropic, chave da OpenAI,
token do Notion, token do GitHub, chave privada PEM, `client_secret` e
`refresh_token` preenchidos, senha em texto claro, arquivo de sessão.

**Identificadores pessoais** — telefone brasileiro, CPF, CNPJ, RG, uid numérico
longo, agência e conta, cartão de crédito.

**Contexto privado** — menções a operações privadas, caminhos internos de host,
diretórios de dados reais, e-mail pessoal.

Sai com código 1 se encontrar qualquer ocorrência.

### A varredura roda nos testes

`tests/test_seguranca.py` executa o mesmo script como parte da suíte, além de
checar cada padrão diretamente em Python. Um dado sensível **quebra o build**,
não apenas o script manual — que alguém poderia esquecer de rodar.

### Dois arquivos ficam fora da varredura

O script de varredura e o teste de segurança contêm os padrões sensíveis por
definição — são as regras. Se fossem escaneados, a varredura encontraria as
próprias regras e falharia sempre. Ambos estão explicitamente excluídos.

---

## 6. Dados de exemplo

Todos os exemplos em `exemplos/mensagens.json` são fictícios e genéricos:
"Reunião com a equipe de produto", "Acabou o café", "Gastei R$ 45,90 no almoço".

Nenhum contém nome de pessoa real, empresa real, endereço, telefone ou valor de
transação real. `test_exemplos_nao_tem_dado_real` verifica isso contra todos os
padrões proibidos.

---

## 7. O que a IA recebe

A camada de classificação envia para a API da Anthropic:

- o texto da mensagem;
- o catálogo de agentes (nomes, domínios e categorias);
- a data de hoje.

**Não envia** credenciais, histórico de outras mensagens, dados já gravados no
Notion, ou identificadores da pessoa. Cada classificação é independente.

Quem processar dados pessoais de terceiros deve considerar as políticas de
retenção do provedor de IA antes de colocar em produção.

---

## 8. Riscos conhecidos

| Risco | Estado | Mitigação |
|---|---|---|
| `.env` commitado por engano | Mitigado | `.gitignore` + teste + varredura |
| Token vazando em log | Mitigado | Isolamento em `_url`, teste dedicado |
| Bot recebendo mensagem de estranho | Mitigado | Allowlist de `chat_id` |
| Refresh token do Google em disco | Aceito | `chmod 600`, fora do repositório, escopo mínimo |
| Dados da mensagem enviados à API de IA | Aceito | Documentado; sem chave, usa o classificador local |
| Ausência de criptografia em repouso | Aceito | Uso pessoal, máquina única |
| Sem rate limiting na captura | Aceito | Allowlist de um único chat limita o volume |

---

## 9. Checklist antes de tornar público

- [ ] `bash scripts/varredura_seguranca.sh` sai com código 0
- [ ] `python -m pytest` passa inteiro
- [ ] `git log -p | grep -iE 'sk-ant|ntn_|BEGIN.*PRIVATE'` não retorna nada
      (a varredura olha o estado atual, não o histórico)
- [ ] `git ls-files | grep -E '\.env$|token.*\.json|credentials'` vazio
- [ ] Prints em `docs/prints/` sem token, e-mail ou dado pessoal visível na tela
- [ ] `.env.example` com todos os valores vazios

O item dos prints é o que costuma passar: uma captura de tela do Notion ou do
terminal pode mostrar um token na barra de endereço ou um dado pessoal em um
registro. Confira imagem por imagem antes de publicar.
