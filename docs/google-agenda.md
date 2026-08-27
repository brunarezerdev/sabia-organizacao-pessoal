# Google Agenda — a API 2

A segunda API da arquitetura. O Telegram é por onde a mensagem entra, o Notion é
onde o registro fica, e a Google Agenda é onde o compromisso vira compromisso de
verdade: aquele que apita no celular da pessoa na hora certa.

Este documento cobre as três coisas que a integração precisa acertar e que não
aparecem quando tudo dá certo: **autenticação**, **tratamento de erro** e
**boas práticas de integração**.

---

## Onde cada peça mora

| Peça | Arquivo | Papel |
| ---- | ------- | ----- |
| Cliente HTTP | `src/sop/integracoes/google_calendar.py` | fala com a API: timeout, retry, conflito, log |
| Servidor MCP | `src/sop/integracoes/gcal_mcp.py` | expõe a agenda ao agente como quatro ferramentas |
| Wrapper do MCP | `scripts/openclaw/gcal_mcp.sh` | resolve a credencial e sobe o servidor em stdio |
| Prova da cadeia | `scripts/provar_cadeia.py` | roda Telegram → IA → Agenda → Notion de ponta a ponta |

### Por que servidor MCP e não uma skill de shell

O Notion já entra por MCP. A agenda pelo mesmo caminho dá ao agente **uma única
forma de falar com API externa**, e mantém timeout, retry, checagem de conflito e
log dentro de um cliente testado, em vez de espalhados em linhas de comando que o
modelo monta na hora. Uma skill de shell colocaria a lógica de integração no
prompt, que é o lugar onde ela não pode ser testada.

O utilitário operacional `gcal.py` já existente foi reaproveitado como referência e na
limpeza independente dos testes; ele não foi chamado pelo servidor porque sua
saída textual não distingue credencial inválida, 429 e 5xx e o cliente não
define timeout nem retry. Encapsulá-lo esconderia justamente os requisitos de
erro e resiliência que esta entrega precisa provar, então as chamadas REST
ficaram no cliente testável, usando a mesma conta de serviço e as mesmas agendas.

O cliente HTTP é reaproveitado pelos dois consumidores: o servidor MCP (para a
Sábia conversando no Telegram) e a CLI `sop` (para o fluxo automático). A regra
de conflito, o fuso e o retry são os mesmos nos dois caminhos porque são o mesmo
código.

---

## Autenticação

Duas rotas, a mesma interface (`Autenticacao`), escolhidas por
`escolher_autenticacao()`.

### Rota 1: conta de serviço (produção)

```
GOOGLE_SERVICE_ACCOUNT_PATH=<caminho do JSON da chave>
```

Uma chave de conta de serviço assina um JWT; o Google devolve um access token de
curta duração. **Ninguém precisa estar no navegador**, então o sistema sustenta
uma operação 24/7 sem intervenção — que é justamente o que a rota OAuth não faz,
porque o consentimento expira e alguém tem que reautorizar.

O acesso à agenda de uma pessoa não vem da chave: vem de a pessoa ter
compartilhado a agenda com o e-mail da conta de serviço. Sem esse
compartilhamento a API responde 403 mesmo com a chave perfeita — por isso o erro
de credencial deste cliente cita explicitamente as duas causas possíveis.

A assinatura RSA vem de `google.oauth2.service_account`. É o único pedaço da
biblioteca oficial que usamos: criptografia não se escreve à mão.

### Rota 2: OAuth com refresh token

```
GOOGLE_TOKEN_PATH=<caminho do JSON com refresh_token, client_id e client_secret>
```

O fluxo interativo roda **uma vez** em `scripts/autorizar_google.py`. Continua
suportada porque é a rota que um avaliador consegue reproduzir na própria conta,
sem ser admin de um workspace.

Basta uma das duas. Com as duas preenchidas, vence a conta de serviço.

### Como o segredo é guardado

Nenhuma credencial entra no repositório nem na configuração do OpenClaw. O que
circula é sempre o **caminho** de um arquivo em modo `0600`, fora da árvore do
projeto:

- `scripts/openclaw/gcal_mcp.sh` confere que a chave existe, é legível e está em
  `600` antes de subir o servidor, e avisa se estiver mais aberta que isso.
- O access token resultante vive **só em memória**, e é renovado um minuto antes
  de expirar (`MARGEM_EXPIRACAO`).
- Qualquer variável de segredo aceita a forma `<NOME>_PATH`
  (`NOTION_TOKEN_PATH`, `TELEGRAM_BOT_TOKEN_PATH`), então nem o `.env` precisa
  conter segredo em texto claro.
- O header `Authorization` nunca vai para o log, e as mensagens de erro citam só
  o que a API respondeu — nunca o que enviamos.

O teste `test_agenda_erro_nao_vaza_o_token` trava essa última regra.

---

## Tratamento de erro

Falha de integração não é uma coisa só, e tratar tudo como "deu erro" é o que faz
um sistema parecer quebrado quando ele só precisava esperar dois segundos. Cada
tipo tem uma classe e uma decisão:

| Situação | Classe | Decisão | Por quê |
| -------- | ------ | ------- | ------- |
| Arquivo de credencial ausente, ilegível ou incompleto | `ErroCredencialGoogle` | falha na hora, com a instrução do que rodar | repetir não cria o arquivo |
| 401 / 403 | `ErroCredencialGoogle` | falha na hora, citando compartilhamento e API habilitada | insistir só gasta cota |
| 429 (limite de requisição) | `ErroLimiteGoogle` | **repete** com recuo, respeitando `Retry-After` | é exatamente o caso que o recuo resolve |
| 500 / 502 / 503 / 504 | `ErroIndisponivelGoogle` | **repete** com recuo exponencial | indisponibilidade costuma ser passageira |
| Timeout, DNS, conexão recusada | `ErroIndisponivelGoogle` | **repete** com recuo | idem |
| 404 | `ErroGoogleCalendar` | falha na hora | o recurso não existe |
| Horário já ocupado | `ConflitoDeAgenda` | falha na hora, com as faixas ocupadas | não é falha técnica: é decisão da pessoa |

`ConflitoDeAgenda` merece nota. Ele é **erro** de propósito: o sistema nunca
sobrepõe um compromisso da pessoa por conta própria. Quando o agente recebe esse
retorno, ele não repete a chamada — ele conta o que já está lá e pergunta.
Sobrepor continua possível, com `permitir_conflito=True`, mas só de propósito.

E na automação (`src/sop/automacao.py`), uma falha da agenda **não derruba o
registro**: o item vai para o Notion do mesmo jeito e o erro aparece em
`ResultadoAutomacao.erros`. Perder o registro da pessoa é pior do que perder o
evento.

---

## Boas práticas de integração

**Timeout em toda chamada.** `TIMEOUT = 30`. Nenhuma requisição fica pendurada.
Travado por `test_agenda_toda_chamada_leva_timeout`.

**Retry com recuo exponencial e sorteio.** Três tentativas, esperando 1s, 2s, 4s,
com um sorteio de até 0,3s somado. O sorteio existe para que várias instâncias
reiniciadas juntas não voltem a bater na API no mesmo instante. Quando a resposta
traz `Retry-After`, ele vence o cálculo — o Google sabe melhor do que nós quando
quer ser chamado de novo.

**Log do que foi chamado.** Toda requisição registra método, caminho, status,
duração em milissegundos e número da tentativa:

```
INFO sop.google_calendar google_calendar POST /freeBusy -> 200 em 551ms (tentativa 1/3)
INFO sop.google_calendar google_calendar criou evento u8bbhep3... ('TESTE DA INTEGRAÇÃO' em 2026-08-30)
```

Criação e remoção de evento também são registradas, e uma recusa por conflito sai
como `WARNING` com a contagem. O log vai para `stderr` no servidor MCP: em
transporte stdio, um `print` em `stdout` corromperia o JSON-RPC.

**Consulta antes de escrita.** `criar_evento` chama `freeBusy` antes de criar,
sempre que houver hora definida. Evento de dia inteiro não é checado: não disputa
horário com ninguém.

**Fuso explícito, tirado do banco de fusos.** O payload leva o deslocamento no
próprio `dateTime` (`2026-08-30T06:00:00-03:00`) **e** o `timeZone`. O
deslocamento sai de `zoneinfo`, não de uma constante: hoje o Brasil é UTC-03:00 o
ano inteiro, e se o horário de verão voltar a janela continua certa sem ninguém
lembrar de mudar o código. `test_agenda_atravessa_a_meia_noite_sem_voltar_no_tempo`
trava o caso que o cálculo antigo errava: um evento das 23h30 termina no dia
seguinte, não às 00h30 do mesmo dia.

---

## Configurar

### 1. Compartilhar a agenda com a conta de serviço

Sem shell, direto no navegador:

1. Abra o Google Agenda.
2. Passe o mouse sobre a agenda na lista à esquerda, clique nos três pontinhos e
   escolha **Configurações e compartilhamento**.
3. Role até **Compartilhar com pessoas ou grupos específicos**.
4. **Adicionar pessoas** e cole o e-mail da conta de serviço (o campo
   `client_email` dentro do JSON da chave).
5. Em permissão, escolha **Fazer alterações nos eventos**. Só leitura não deixa
   criar nada.
6. **Enviar**.

### 2. Apontar o caminho da chave

```
GOOGLE_SERVICE_ACCOUNT_PATH=<caminho do JSON>
GOOGLE_CALENDAR_ID=<e-mail da agenda alvo>
```

Confira com `python -m sop diagnostico`.

### 3. Registrar o servidor MCP

```bash
openclaw mcp add agenda \
  --command scripts/openclaw/gcal_mcp.sh \
  --cwd . --connect-timeout 60 --timeout 120 \
  --env GOOGLE_SERVICE_ACCOUNT_PATH=<caminho do JSON> \
  --env 'SOP_AGENDAS=bruna=<e-mail>,wagner=<e-mail>'

openclaw mcp probe     # deve listar: agenda: 4 tools
openclaw mcp reload    # o gateway em execução passa a enxergar
```

`SOP_AGENDAS` mapeia **rótulo → agenda**. Os rótulos existem para que nem o
repositório nem o prompt do agente precisem carregar o e-mail de ninguém: a Sábia
pede "a agenda da bruna" e o mapeamento mora na configuração da máquina.

---

## As quatro ferramentas

| Ferramenta | Para quê |
| ---------- | -------- |
| `agenda_consultar(agenda, dias)` | compromissos dos próximos dias |
| `agenda_conflitos(data, hora, duracao_minutos, agenda)` | se o horário está livre, sem criar nada |
| `agenda_criar(titulo, data, hora, ...)` | cria, checa conflito e grava o espelho no Notion |
| `agenda_apagar(evento_id, agenda)` | apaga pelo id |

Toda ferramenta devolve `ok: true/false`. Falha vira `{"ok": false, "erro": "..."}`
em português, não traceback: o agente precisa conseguir contar para a pessoa o
que aconteceu, e um stack trace no meio de uma conversa no Telegram não serve
para nada.

`agenda_criar` concentra a escrita dupla para não depender de o modelo lembrar
uma segunda chamada: depois do Google, grava no Notion e devolve os dois ids. Se
o Notion falhar, apaga pelo id exato somente o evento recém-criado e informa a
falha, evitando tanto registro órfão quanto duplicidade numa nova tentativa.

---

## Provar que funciona

```bash
python scripts/provar_cadeia.py            # cadeia inteira, evento de teste apagado no fim
python scripts/provar_cadeia.py --verboso  # com o log de cada chamada
```

O script percorre Telegram → classificação → Google Agenda → Notion contra as
APIs de produção, lê de volta o que gravou em cada ponta, apaga o evento de teste
e escreve a evidência em `docs/evidencias/`. O relatório é higienizado antes de ir
para o disco: id de agenda, chat e credenciais são mascarados, porque `docs/` é
versionado.

Ele **não envia mensagem para ninguém** no Telegram: a etapa 1 valida a
credencial do bot com `getMe` e exercita o mesmo `para_mensagem` da captura,
incluindo a recusa de um chat não autorizado. Mandar mensagem para uma pessoa é
decisão dela, não de um script de verificação.
