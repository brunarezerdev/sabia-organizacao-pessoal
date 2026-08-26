# Estrutura Sábia

A estrutura de agentes da Bruna rodando sobre o OpenClaw, com o Codex como modelo, atendendo no
bot `@SabiaAquiBot`. É a estrutura usada na entrega de 30/08/2026 e na do mês seguinte.

Montada em 26/08/2026.

## O que é, e o que não é

**É** a estrutura de agentes separada e sanitizada em 24/08/2026, que vive em
`brunarezerdev/aria-infra`, em `.claude/agents/`: nove agentes que a Bruna usa de fato, mais uma
orquestradora.

**Não é** a wiki de receitas do Notion, e **não é** a estrutura pessoal antiga (educacional,
financeira, lifestyle, projetos, secretaria). Aquela continua registrada e preservada, declarada
em `openclaw/agentes.json`. As duas convivem no mesmo OpenClaw sem se misturar.

## A orquestradora

A orquestradora chama-se **Sábia** 🐦 e é o agente `main` do OpenClaw. É ela que atende no
`@SabiaAquiBot`: recebe a mensagem, entende, escolhe o agente e devolve o resultado.

A Sábia não é a Ária. A Ária é outra assistente, de outra operação, em outro bot, com outro
token. O bot `@SabiaAquiBot` nunca foi da Ária.

A alma da Sábia é escrita à mão em `sabia/orquestradora.md`. Ela é a única fonte: o arquivo em
`sabia/almas/sabia.md` e o `SOUL.md` do workspace são gerados.

## Os nove agentes

| id | nome | função | raciocínio |
| --- | --- | --- | --- |
| `neo-dev` | Neo 💻 | desenvolvedor full-stack | high |
| `juliana-ops` | Juliana 🎨 | sub-gerente operacional, executora padrão | high |
| `jonathan-copy` | Jonathan ✍️ | copywriter e pesquisador | medium |
| `ethan-projetos` | Ethan 📋 | gestor de projetos | medium |
| `monica-projetos` | Mônica 🗂️ | registro de decisões de produto | medium |
| `jane-academica` | Jane 🎓 | ghostwriter acadêmica | medium |
| `jordan-sdr` | Jordan 🤝 | SDR | medium |
| `denderson-clone` | Denderson 🎯 | tráfego pago | medium |
| `amanda-crm` | Amanda 💬 | atendimento e relacionamento | medium |

## Como a conversão funciona

```
aria-infra/.claude/agents/*.md        (formato Claude Code, fonte)
        |
        | cópia fiel, vendorizada com o commit de origem anotado
        v
sabia/agentes-fonte/*.md
        |
        | python3 sabia/converter.py
        v
sabia/almas/*.md  +  sabia/agentes-sabia.json
        |
        | bash sabia/registrar.sh   (openclaw agents add / set-identity / config set)
        v
OpenClaw: agents.list[] + ~/.openclaw/workspace-<id>/SOUL.md
```

Para ressincronizar quando a Bruna mudar um agente no `aria-infra`:

```bash
cd /opt/aria/projetos/sop-pessoal
gh repo clone brunarezerdev/aria-infra /tmp/aria-infra -- --depth 1
cp /tmp/aria-infra/.claude/agents/*.md sabia/agentes-fonte/
python3 sabia/converter.py
bash sabia/registrar.sh
bash sabia/reiniciar_gateway.sh
```

### Tradução de ferramentas

O Claude Code e o OpenClaw nomeiam as ferramentas de forma diferente. O mapa está em
`sabia/converter.py`, em `TOOLS`. Dois casos não são simétricos e ficam registrados aqui:

- `Grep` e `Glob` não existem no OpenClaw. Busca lá é `read` e, quando precisa varrer, `exec`.
  Quem tinha Grep/Glob recebeu `read`; quem tinha `Bash` já recebeu `exec` e segue conseguindo
  varrer.
- `Agent` (invocar outro subagente) virou o trio `sessions_spawn`, `subagents`, `agents_list`.
  Só a Juliana tem, igual ao original.

O `jordan-sdr` tinha `disallowedTools: [Bash, Edit]`. Isso virou `tools.deny` com os aliases que
dariam o mesmo poder por outro nome: `exec`, `process`, `code_execution`, `edit`, `apply_patch`.

### Tradução de modelo

Os nove nasceram com `model: opus | sonnet`. Aqui todos rodam no mesmo provedor, o Codex
(`openai/gpt-5.5`), porque é o único que a Bruna escolheu e ligou. O que preserva a diferença de
peso entre eles é o `thinkingDefault`: quem era opus pensa em `high`, quem era sonnet pensa em
`medium`.

### Por que não usamos o `criar-subagente-openclaw.py` do próprio repo

O script existe em `.claude/skills/criar-subagente/scripts/` do `aria-infra` e serve pra criar
**um** subagente novo do zero, noutro ambiente. Nesta VPS ele não roda, por quatro motivos:

1. Escreve direto no `openclaw.json` com um esquema que a 2026.6.5 não aceita
   (`system_prompt_file`, `channels`, `max_tokens`, `isolation`). O esquema real de
   `agents.list[]` usa `agentDir`, `identity`, `model`, `tools`, `subagents`.
2. `MODELOS_VALIDOS` só aceita modelo Claude. Com `openai/gpt-5.5` ele aborta antes de escrever.
3. Assume base em `/root/.openclaw` e reinicia via `systemctl restart openclaw-gateway` no escopo
   do sistema. Aqui a base é `/home/aria/.openclaw` e o gateway é serviço **do usuário**.
4. A alma que ele gera fixa "equipe Naia" e "reporta pra Naia". A equipe daqui reporta pra Sábia.

O script não foi alterado: ele continua válido pro caso de uso dele.

## Onde as políticas por agente são aplicadas

`openclaw agents add` cria o agente, mas não tem flag pra tools, raciocínio ou delegação. Esses
campos ficam dentro de cada item de `agents.list[]`:

```
agents.list[N].tools            { allow, deny }
agents.list[N].thinkingDefault  off|minimal|low|medium|high|xhigh|adaptive|max
agents.list[N].subagents        { delegationMode, allowAgents }
```

Editar o `openclaw.json` na mão não serve: o CLI recusa `config patch` que substitua
`agents.list` inteiro, e a escrita crua pula a validação e o `last-good`. O caminho suportado é
`openclaw config set` por caminho indexado, em lote validado. É o que
`sabia/bin/aplicar_politicas.py` faz, resolvendo o índice pelo `id` na hora (o índice muda
conforme agentes entram e saem, então nunca é fixado).

A Sábia recebe `subagents.delegationMode: "prefer"` e `allowAgents` com os nove. É o mecanismo do
próprio OpenClaw pra um agente coordenador empurrar trabalho pros subagentes em vez de fazer.

Ela **não** recebe `tools.allow` restrito, de propósito: o perfil global `coding` é o que dá a ela
as ferramentas do MCP do Notion, que a rotina diária de 11h já usa. Fechar a lista derrubaria
aquela rotina em silêncio. O limite da Sábia está na alma dela e no `delegationMode`.

## Modelo: o Codex

O provedor é o Codex, pelo plugin nativo do OpenClaw, usando a **mesma** credencial que a
juliana-ops já usa: a CLI do Codex autenticada em `/home/aria/.codex` (`auth.json`,
`config.toml`). Não há segunda credencial, não houve login novo e não existe chave de API no meio.

O plugin sobe o `codex app-server` como filho do gateway, dentro do mesmo cgroup do serviço.

```
plugins.allow            ["codex", "telegram"]
agents.defaults.model    openai/gpt-5.5
```

Confirmação de que responde de verdade:

```bash
node node_modules/openclaw/dist/index.js agent --agent main \
  --session-key teste --message "Quanto é 17 vezes 23?" --json
```

O envelope traz `executionTrace.winnerProvider: "openai"`, `winnerModel: "gpt-5.5"` e
`requestShaping.authMode: "auth-profile"`, que é a prova de que passou pela credencial do Codex e
não por API key.

## Telegram

```
channels.telegram.enabled      true
channels.telegram.name         "Sábia"
channels.telegram.tokenFile    /opt/aria/.secrets/sop-telegram-bot.token
channels.telegram.dmPolicy     allowlist
channels.telegram.allowFrom    ["5052079460", "8188614125"]
channels.telegram.groupPolicy  allowlist
```

O token **não** está no repositório: fica em `/opt/aria/.secrets/`, e a config guarda só o
caminho.

Quem busca as mensagens é o próprio gateway do OpenClaw, em modo polling. Isso é decisão de
projeto, não acidente: a API do Telegram entrega cada update uma única vez, para um único
consumidor. Um segundo poller com o mesmo token receberia `409 Conflict` e os dois brigariam
pelo mesmo update.

### Separação da Ária

| | Ária | Sábia |
| --- | --- | --- |
| bot | outro | `@SabiaAquiBot` |
| token | `/opt/aria-bot/.env` | `/opt/aria/.secrets/sop-telegram-bot.token` |
| fila | `/opt/aria-bot/{inbox,outbox,sent}` | `sabia/fila/` |
| quem processa | sessão tmux da Ária | gateway do OpenClaw |

Dois bots, dois tokens, duas filas, zero interseção. A Sábia **não** lê nem escreve em
`/opt/aria-bot/`, e a Ária não conhece o caminho da Sábia. Não há como uma responder pela outra.

### As três travas contra eco

Já houve incidente nesta operação em que a saída do próprio bot voltou como entrada e virou spam
(msg 724). Aqui isso é barrado em quatro lugares:

1. **Estrutural.** A API do Telegram não entrega ao bot as mensagens que o próprio bot enviou.
   No caminho do Telegram o eco é impossível por construção. O incidente da Ária não veio do
   Telegram, veio de um hook local que realimentava o texto na sessão. Aqui não existe hook
   desses: a saída da Sábia vai direto do gateway pra API do Telegram.
2. **Origem.** `dmPolicy: allowlist` com os dois uids no canal, e a mesma lista repetida em
   `AUTORIZADOS`, na fila. `sabia` nunca é origem válida de entrada.
3. **Impressão digital.** Todo texto que a Sábia produz entra no ledger como `saida` com o
   sha256. Entrada cujo sha256 já apareça como saída é recusada: é eco, não é pedido.
4. **Idempotência.** Cada item tem uma chave `ref`. Chave já vista no ledger não roda de novo.

## A fila própria da Sábia

```
sabia/fila/
├── entrada/       pedidos aguardando
├── saida/         respostas produzidas
├── processadas/   entradas já consumidas
└── ledger.jsonl   registro append-only de tudo, com sha256 e ref
```

O caminho do Telegram **não** passa pela fila (ver acima: um poller só). A fila serve pra disparar
trabalho pra Sábia a partir de cron, script ou de outra parte do sistema, sem Telegram no meio, e
pra manter o registro auditável.

```bash
python3 sabia/bin/fila_sabia.py enfileirar --de 5052079460 --texto "..."
python3 sabia/bin/fila_sabia.py processar
python3 sabia/bin/fila_sabia.py status
```

## Operação

O gateway é serviço **do usuário** `aria`, não do sistema:

```
~/.config/systemd/user/openclaw-gateway.service   (enabled, Restart=always)
```

Não precisa de root. `sudo systemctl restart openclaw-gateway` não acha a unit. Uma sessão não
interativa chega sem `XDG_RUNTIME_DIR` e falha com "Failed to connect to bus";
`sabia/reiniciar_gateway.sh` cuida disso e espera o gateway voltar a atender.

> `systemd/openclaw-gateway.service`, na raiz do repositório, é outro arquivo: um modelo de unit
> de **sistema**, apontando pra `/root`, que nunca foi instalado nesta VPS. Quem manda é a unit de
> usuário acima. O modelo ficou desatualizado e não deve ser usado como referência.

Reiniciar é necessário depois de trocar `SOUL.md` ou identidade: o gateway lê a alma no início da
sessão e mantém em memória.

## Pontos abertos

- **Rotina de 11h.** O cron `0 11 * * *` chama `scripts/openclaw/rotina_sabia.sh`, que roda um
  turno do agente `main` pedindo o resumo de receitas e lista de compras do Notion. Isso vem da
  interpretação antiga de "Sábia", a que a Bruna corrigiu em 26/08. Com o `main` sendo agora a
  orquestradora, esse prompt não tem dono entre os nove agentes. A rotina **não** entrega no
  Telegram (roda sem `--deliver`, só escreve em `/opt/aria/logs/sabia-rotina.log`), então não gera
  mensagem indevida. Ficou como está porque desativar cron de outra pessoa é decisão dela.
- **Triagem do sop.** `src/sop/config.py` usa `OPENCLAW_AGENTE` (default `main`) esperando que o
  agente devolva um JSON de classificação. Com o `main` virando a Sábia, esse contrato mudou: a
  Sábia conversa e delega, não devolve JSON cru.

  Isso **não** quebrou nada hoje, porque `IA_BACKEND` está vazio no `.env` e o sop usa o
  classificador heurístico local. O caminho do OpenClaw está desligado.

  Fica como armadilha para o futuro: se alguém setar `IA_BACKEND=openclaw` com
  `OPENCLAW_AGENTE=main`, a classificação vai chegar na Sábia e falhar. A alma antiga de
  classificação continua preservada em `openclaw/workspaces/main/SOUL.md` e é gerada de
  `agentes/_orquestradora.md`. Antes de ligar aquele caminho, registre um agente dedicado com
  aquela alma e aponte `OPENCLAW_AGENTE` pra ele.

  Nenhum agente extra foi criado agora, de propósito: seria estrutura que a Bruna não pediu, para
  um caminho que está desligado.
