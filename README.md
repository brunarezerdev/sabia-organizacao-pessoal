# Sábia

**Inteligência para cultivar a vida.**

Sábia é um sistema de organização pessoal em que a pessoa escreve uma frase em
linguagem natural no Telegram e o sistema decide sozinho o que aquilo é, onde
guardar e se vira compromisso na agenda.

> "Reunião com o cliente na quinta às 14h"
> → classificado como **compromisso** → registrado no Notion → evento criado na Google Agenda

Sem formulário, sem categoria para escolher, sem app para abrir. A fricção de
registrar é o que faz as pessoas abandonarem sistemas de organização; a ideia
aqui é reduzir essa fricção a zero.

---

## Índice

- [Descrição da solução](#descrição-da-solução)
- [APIs utilizadas e justificativa](#apis-utilizadas-e-justificativa)
- [Arquitetura e fluxo de integração](#arquitetura-e-fluxo-de-integração)
- [Os agentes](#os-agentes)
- [Autenticação e segurança](#autenticação-e-segurança)
- [Instalar e rodar o OpenClaw](#instalar-e-rodar-o-openclaw)
- [Como executar](#como-executar)
- [Automação de ponta a ponta](#automação-de-ponta-a-ponta)
- [O ciclo semanal: regras se-então e ritual de domingo](#o-ciclo-semanal-regras-se-então-e-ritual-de-domingo)
- [Testes](#testes)
- [Prints](#prints)

---

## Descrição da solução

O problema que este projeto resolve não é falta de ferramenta de organização —
é excesso. A informação chega o dia todo em formatos diferentes (um gasto, uma
consulta marcada, um item que acabou na despensa, uma tarefa de projeto) e cada
uma dessas coisas mora em um app diferente. O custo de decidir *onde* registrar
é maior do que o de registrar, então nada é registrado.

A solução é inverter a responsabilidade: **a pessoa despeja o pensamento em um
canal só e o sistema faz a triagem.** Uma camada de IA lê a mensagem, decide
qual dos sete agentes especializados cuida daquilo, extrai os campos
estruturados (data, hora, valor, projeto, disciplina) e grava no lugar certo.

O que o sistema entrega:

- **Captura sem fricção** — Telegram, que a pessoa já tem aberto.
- **Classificação automática** — sete funções cognitivas, um agente cada.
- **Registro estruturado** — Notion, que a pessoa consegue abrir e editar.
- **Agendamento automático** — o que tem data vira evento na Google Agenda.
- **Painel de acompanhamento** — a própria database do Notion, com filtros por
  agente, categoria e data.

### Por que agentes especializados e não um classificador só

Cada domínio tem regras próprias que não se generalizam. Tino, o esquilo 🐿️,
tem uma regra que nenhum outro tem: **nunca inventar um valor**. Se a mensagem
diz "gastei no posto" sem número, ele pergunta o valor antes de criar o
registro, em vez de chutar. Tino tem outra: uma lista falada
("preciso de arroz, feijão e sabão") vira três registros, não um.

Essa política vale para os oito agentes: lacuna essencial gera uma pergunta
curta e específica e bloqueia o registro incompleto; lacuna secundária não
impede o registro, mas aparece claramente na resposta. Nenhum agente inventa
dados, fica calado sobre o que faltou ou faz mais de uma ou duas perguntas por
vez.

Codificar isso num prompt único produziria um monstro impossível de manter.
Cada agente vive em um arquivo próprio, com seu prompt e suas regras.

---

## APIs utilizadas e justificativa

O projeto integra **quatro APIs externas**, todas com autenticação.

| API | Papel | Autenticação | Por que esta |
|---|---|---|---|
| **Telegram Bot API** | Captura de mensagens | Token de bot | É onde a pessoa já está. Um app próprio exigiria instalação e login; o Telegram custa zero fricção e tem long polling gratuito. |
| **Notion API** | Banco de dados no-code | Token de integração (Bearer) | Requisito de banco no-code. Diferente de um Postgres, a pessoa consegue abrir, filtrar e corrigir os registros sem SQL — o que importa quando o dono do sistema não é programador. |
| **Google Calendar API v3** | Leitura e escrita de eventos | OAuth 2.0 com refresh token | A agenda que a pessoa realmente usa. Escrever num calendário próprio seria criar mais um lugar para conferir. |
| **OpenAI, rota Codex, via OpenClaw** | Classificação da mensagem e execução dos agentes | OAuth 2.0 por device-code, sobre a assinatura ChatGPT Plus | Faz a triagem e roda os agentes. A autenticação não usa chave: o login é feito uma vez pelo CLI e consome a cota da assinatura. |

### Modos de autenticação

As quatro APIs usam mecanismos diferentes de propósito — o projeto exercita o
espectro completo:

- **Token no caminho da URL** (Telegram)
- **Bearer token em header** (Notion)
- **OAuth 2.0 com fluxo de consentimento e renovação de token** (Google)
- **OAuth 2.0 por device-code, sem chave de API** (OpenAI, rota Codex)

O Google e o OpenAI são os mais interessantes, e por motivos diferentes.

No Google, o fluxo interativo roda uma única vez
(`scripts/autorizar_google.py`), grava um refresh token, e daí em diante o
cliente troca esse refresh por um access token de curta duração a cada sessão,
renovando sozinho quando expira.

No OpenAI, o fluxo é **device-code**: a máquina que precisa de acesso não tem
navegador, então ela imprime uma URL e um código curto, e a autorização
acontece em outro dispositivo já logado. A máquina fica consultando até o
consentimento chegar. É o desenho pensado para servidor sem interface, e é o
motivo de **não existir API key nessa rota** — a credencial é a assinatura da
pessoa, não um segredo copiável. Detalhes em [`docs/openclaw.md`](docs/openclaw.md).

---

## Arquitetura e fluxo de integração

```
   ┌─────────────┐
   │  Telegram   │  captura — a pessoa escreve uma frase
   └──────┬──────┘
          │  Mensagem (id, texto, autor)
          ▼
   ┌──────────────────┐        ┌────────────────────────────┐
   │  ORQUESTRADORA   │◄──────►│  OpenClaw                  │
   │                  │        │  provider openai (Codex)   │
   │  entende         │        │  main + 6 subagentes,      │
   │  decide          │        │  um workspace cada         │
   │  despacha        │        └────────────────────────────┘
   │                  │        ┌──────────────────┐
   │                  │◄──────►│  Fila durável    │
   └────────┬─────────┘        │  (em disco)      │
            │                  └──────────────────┘
            │  Item classificado
            ├──────────────────────────┐
            ▼                          ▼
   ┌──────────────────┐      ┌──────────────────┐
   │      Notion      │      │  Google Agenda   │
   │  (todos os itens)│      │  (só o que tem   │
   │                  │      │   data + agente  │
   │                  │      │   de agenda)     │
   └──────────────────┘      └──────────────────┘
```

Diagrama detalhado em Mermaid: [`docs/fluxo.md`](docs/fluxo.md).
Decisões de arquitetura: [`docs/arquitetura.md`](docs/arquitetura.md).

### O papel da orquestradora

A orquestradora (`src/sop/orquestradora.py`) é a peça central e faz
deliberadamente **muito pouco**: entende, decide e despacha. Ela não grava no
Notion, não cria evento, não formata texto. Toda lógica de domínio vive na
definição do agente.

Esse desenho é o que permite **acrescentar um agente novo sem tocar no código**:
basta criar um arquivo em `agentes/`. O registro carrega tudo o que encontrar no
diretório e o roteamento passa a considerar as categorias novas.

### A fila durável

Mensagem recebida é enfileirada em disco antes de ser processada. Se o processo
morrer no meio, a tarefa continua existindo e é retomada — `recuperar_orfas()`
devolve para a fila o que ficou travado. Cada mudança de estado é um
`os.rename`, que é atômico: dois workers nunca processam a mesma tarefa.

Isso separa a captura do processamento: quem escreveu recebe confirmação na
hora, sem esperar as três APIs responderem.

### Degradação em vez de falha

O sistema foi desenhado para funcionar parcialmente configurado:

- **Sem chave de IA** → cai no classificador heurístico local (palavras-chave e
  expressões regulares). Menos preciso, mas roda offline e sem custo.
- **Sem Notion** → classifica e responde, apenas não persiste.
- **Google Agenda fora do ar** → o item ainda é gravado no Notion e o erro
  aparece no resultado. Perder o evento é ruim; perder o registro seria pior.

---

## Os agentes

Cada agente é um arquivo Markdown em `agentes/`, com cabeçalho de metadados e o
prompt no corpo. As categorias não se sobrepõem: cada uma pertence a um único
agente, senão o roteamento seria ambíguo (há um teste que garante isso).

Os animais não representam páginas. Cada um representa uma **função cognitiva**
da arquitetura, e é isso que faz a metáfora sustentar o sistema em vez de só
decorá-lo.

| Agente | Função | Domínio | Categorias | Cria evento? |
|---|---|---|---|---|
| **Prumo, a raposa** 🦊 | planejar | estratégia, projetos, metas, prioridades | `tarefa`, `marco`, `metrica` | sim |
| **Lida, a abelha** 🐝 | fazer | rotinas, hábitos, limpeza, tarefas recorrentes | `limpeza`, `rotina` | não |
| **Tino, o esquilo** 🐿️ | guardar | finanças, compras, estoque, patrimônio | `gasto`, `receita`, `meta`, `compras`, `estoque` | não |
| **Elo, o cervo** 🦌 | cuidar | família, filhos, casa, alimentação, bem-estar | `cardapio`, `familia` | não |
| **Eco, o elefante** 🐘 | lembrar | memória, documentos, histórico, registros | `documento`, `registro` | não |
| **Nova, a borboleta** 🦋 | crescer | educação, estudos, hábitos de aprendizado, cursos, leituras, desenvolvimento pessoal | `estudo`, `material`, `flashcard`, `curso`, `aprendizado` | sim |
| **Psiu, o beija-flor** 🐦 | avisar | calendário, lembretes, avisos, mensagens | `compromisso`, `lembrete`, `mensagem` | sim |

A **Sábia, a coruja** 🦉 é a oitava e mora em `agentes/_orquestradora.md`. O prefixo `_` a
mantém fora do roteamento: ela compreende, consulta o contexto e decide para
quem vai a mensagem, sem receber categoria nenhuma. O `nome:` dela continua
`main`, que é o slot do agente principal no OpenClaw.

O **efeito borboleta** citado em `regras.py` e no ritual semanal é outra coisa:
é o encadeamento se-então entre compromissos, não Nova, a borboleta 🦋.

### Como a Sábia fala

Calma, observadora, prática e elegante. Sem urgência artificial e sem linguagem
motivacional. A regra de tom vale para todos os agentes e está escrita na alma
de cada um:

> Em vez de "Você está atrasado em 17 tarefas", diga "Há 17 tarefas abertas.
> Cinco merecem sua atenção esta semana."

```bash
python -m sop agentes    # lista os agentes de domínio e seus domínios
```

### Como eles rodam: OpenClaw

Os agentes são declarados e executados no [OpenClaw](https://docs.openclaw.ai),
com **um workspace por agente, tools restritas por agente e modelo por agente**.

O mesmo arquivo em `agentes/` alimenta as duas pontas: o roteamento em Python e
a alma (`SOUL.md`) que o agente lê ao subir dentro do OpenClaw. O prompt é
escrito uma vez.

```bash
python -m sop openclaw              # gera openclaw/agentes.json e as almas
python -m sop openclaw --verificar  # falha se alguém editou agentes/ sem regerar
```

| id | Papel | Tools |
|---|---|---|
| `main` | Sábia, a coruja 🦉, compreender e despachar | `fs.read`, `grep`, `agent.invoke` |
| `esquilo` | Tino, o esquilo 🐿️, guardar | `fs.read`, `fs.write` |
| `raposa` | Prumo, a raposa 🦊, planejar | `fs.read`, `fs.write` |
| `elefante` | Eco, o elefante 🐘, lembrar | `fs.read`, `fs.write` |
| `borboleta` | Nova, a borboleta 🦋, crescer | `fs.read`, `fs.write`, `web.fetch` |

`beija-flor`, `abelha` e `cervo` permanecem apenas no roteamento Python, com
`openclaw_ativo: false`; não são instalados no OpenClaw. Agenda e rotina
doméstica ficam com a `juliana-ops` na estrutura Sábia.

A regra das tools é dar o menor conjunto que resolve o trabalho. `agent.invoke`
existe só na orquestradora, porque delegação em especialista abre caminho para
loop infinito; `shell.exec` não existe em ninguém, porque nenhum agente deste
sistema precisa executar comando. As duas regras têm teste.

Detalhes, decisões e pontos em aberto: [`docs/openclaw.md`](docs/openclaw.md).

---

## Autenticação e segurança

### Estratégia de credenciais

**Nenhuma credencial vive no código ou no repositório.** Tudo vem de variáveis
de ambiente, carregadas de um `.env` que está no `.gitignore` desde o primeiro
commit. O `.env.example` documenta cada variável com todos os valores vazios.

O `.gitignore` bloqueia por padrão, não por exceção: `.env*`, `*.key`, `*.pem`,
`credentials.json`, `token*.json`, `*session*.txt`, `secrets/`, `dados/`.

### Controle de acesso na captura

Um bot do Telegram é endereçável por qualquer pessoa que descubra seu nome.
Por isso o cliente só converte em mensagem processável o que vier do `chat_id`
configurado em `TELEGRAM_CHAT_ID_AUTORIZADO` — qualquer outra origem é
descartada silenciosamente, sem resposta que confirme a existência do bot.

### Cuidados no tratamento de erro

O token do Telegram viaja no caminho da URL, então uma exceção de rede poderia
vazá-lo em log. O cliente isola isso: a única função que toca o token é `_url`,
e os erros propagam apenas a descrição devolvida pela API. Há um teste que
verifica que o token não aparece na mensagem de erro.

### Escopo mínimo no Google

O fluxo OAuth pede apenas `calendar`. O arquivo de token é gravado com
permissão `600` e fica fora do repositório.

### Varredura automática

```bash
bash scripts/varredura_seguranca.sh
```

Verifica o repositório inteiro contra padrões de token, chave privada, CPF,
CNPJ, telefone, cartão e outros dados sensíveis. Sai com código 1 se encontrar
qualquer ocorrência. **A mesma varredura roda dentro da suíte de testes**
(`tests/test_seguranca.py`), então um dado sensível quebra o build, não só o
script manual.

---

## Instalar e rodar o OpenClaw

Esta seção é o passo a passo completo para quem nunca viu o projeto. Se você só
quer ver o sistema funcionando sem instalar nada, pule para
[Como executar](#como-executar): o projeto sobe sem o OpenClaw e sem nenhuma
credencial.

### O que é preciso

- Ubuntu 22+ / Debian (root) ou macOS 13+ (usuário normal)
- Node 22.19 ou superior — o script instala se faltar
- Uma assinatura **ChatGPT Plus** ativa, para autorizar a rota Codex
- Um bot do Telegram criado no `@BotFather`

### Se o OpenClaw não estiver instalado

É o caso normal em máquina nova. Confira e instale:

```bash
openclaw --version || bash scripts/openclaw/instalar.sh
```

O script instala Node 22 via nvm (se preciso), instala `openclaw@2026.6.5` e
cria `~/.openclaw` com permissão `700`. No Ubuntu ele precisa de root, porque
instala pacotes de sistema e cria os symlinks que o systemd enxerga:

```bash
sudo bash scripts/openclaw/instalar.sh
```

> A versão é fixada de propósito. O repositório de referência registra que
> `openclaw@latest` quebra o polling do Telegram. Não troque sem testar.

**Se você não quiser ou não puder instalar o OpenClaw**, nada aqui é
bloqueante: sem ele, `IA_BACKEND` cai no classificador heurístico local e o
sistema continua classificando, gravando no Notion e criando evento na agenda.
O que muda é a precisão da triagem. `python -m sop diagnostico` mostra qual
backend está respondendo.

### 1. Autenticar o provedor de IA

```bash
bash scripts/openclaw/configurar_provedor_openai.sh
```

O script imprime uma URL (`https://auth.openai.com/codex/device`) e um código
curto. Abra a URL no navegador de um computador **já logado no ChatGPT Plus**,
digite o código e autorize. O terminal detecta sozinho e imprime
`OpenAI device code complete`. Você não cola nada de volta.

> **Não procure por uma API key do Codex.** Ela não existe. A rota Codex
> autentica só por OAuth, contra a sua assinatura. A variável `OPENAI_API_KEY`
> do `.env.example` serve a outra coisa: a rota alternativa por API, opcional.

Ao final, o script define `gateway.mode local` (sem isso o gateway nem sobe) e
`openai/gpt-5.5` como modelo primário.

### 2. Configurar o canal do Telegram

```bash
TG_BOT_TOKEN="cole-o-token-do-botfather" \
TG_USER_ID="seu-id-numerico" \
  bash scripts/openclaw/configurar_telegram.sh
```

Para descobrir o seu id: mande qualquer mensagem para o bot e abra
`https://api.telegram.org/bot<SEU_TOKEN>/getUpdates`; o número está em
`message.from.id`.

O script usa `openclaw config patch`, que valida na escrita, e configura
`dmPolicy: allowlist` com o seu id — só você fala com o bot. O arquivo
temporário que carrega o token é apagado logo depois.

### 3. Gerar e registrar os agentes

```bash
python -m sop openclaw                      # gera a declaração e as almas
bash scripts/openclaw/registrar_agentes.sh  # registra no OpenClaw
```

O segundo script lê `openclaw/agentes.json` e, para cada agente, chama
`openclaw agents add` (append não destrutivo e idempotente — pode rodar de
novo), define nome e emoji com `agents set-identity` e copia a alma para o
`SOUL.md` do workspace dele.

### 4. Subir o gateway como serviço

```bash
sudo cp systemd/openclaw-gateway.service /etc/systemd/system/
sudo sed -i "s|__OPENCLAW_BIN__|$(command -v openclaw)|" \
    /etc/systemd/system/openclaw-gateway.service
sudo systemctl daemon-reload
sudo systemctl enable --now openclaw-gateway
systemctl status openclaw-gateway
```

O caminho do binário é substituído porque o Node instalado via nvm não está no
`PATH` do systemd.

### 5. Conferir

```bash
openclaw config validate     # deve dizer "Config valid"
openclaw agents list         # main + os 5 subagentes
openclaw models status --probe
openclaw doctor
python -m sop diagnostico    # mostra qual backend de IA está ativo
```

E, no Telegram, mande `/start` para o seu bot.

### Ponto a confirmar antes de usar em produção

O backend `openclaw` da camada de IA precisa de `OPENCLAW_COMANDO` no `.env`:
a linha de comando que invoca o agente principal de forma não interativa. Essa
invocação **não foi verificada** e por isso não há um padrão chutado no código
— enquanto a variável estiver vazia, o sistema usa o heurístico.

Confira na sua máquina com `openclaw agents --help` e preencha:

```bash
OPENCLAW_COMANDO=openclaw agents run {agente} --non-interactive
```

Este e os outros pontos em aberto estão listados em
[`docs/openclaw.md`](docs/openclaw.md#pontos-a-confirmar).

---

## Como executar

### Requisitos

Python 3.10 ou superior. O OpenClaw é opcional para rodar e obrigatório só para
usar o provedor de IA de verdade — ver a seção acima.

### 1. Instalar

```bash
git clone https://github.com/brunarezerdev/sabia-organizacao-pessoal.git
cd sabia-organizacao-pessoal
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Rodar sem configurar nada

O projeto sobe sem credencial. Comece por aqui:

```bash
python -m sop diagnostico    # mostra o que está configurado e o que falta
python -m sop demo           # classifica 12 mensagens de exemplo, sem rede
```

O `demo` usa o classificador heurístico local — nenhuma API é chamada e nada é
gravado. Serve para ver o roteamento funcionando antes de configurar qualquer
coisa.

### 3. Configurar as credenciais

```bash
cp .env.example .env
```

Preencha o `.env` seguindo os passos abaixo.

<details>
<summary><b>Telegram</b> — TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID_AUTORIZADO</summary>

1. No Telegram, converse com **@BotFather** e mande `/newbot`.
2. Escolha nome e username. O BotFather devolve o token — cole em
   `TELEGRAM_BOT_TOKEN`.
3. Mande qualquer mensagem para o seu bot.
4. Abra `https://api.telegram.org/bot<SEU_TOKEN>/getUpdates` no navegador e
   copie o `message.chat.id` para `TELEGRAM_CHAT_ID_AUTORIZADO`.
</details>

<details>
<summary><b>Notion</b> — NOTION_TOKEN, NOTION_DATABASE_ID</summary>

1. Acesse <https://www.notion.so/my-integrations> e crie uma integração
   interna. Copie o token para `NOTION_TOKEN`.
2. No Notion, crie uma database com estas propriedades (nome e tipo exatos):

   | Propriedade | Tipo |
   |---|---|
   | `Titulo` | Title |
   | `Agente` | Select |
   | `Categoria` | Select |
   | `Data` | Date |
   | `Observacao` | Text |
   | `Detalhes` | Text |

3. Na database, menu `...` → **Conexões** → adicione a sua integração.
   **Sem esse passo a API devolve 404 mesmo com token válido.**
4. Copie o ID da database da URL (os 32 caracteres antes do `?`) para
   `NOTION_DATABASE_ID`.
</details>

<details>
<summary><b>Google Agenda</b> — GOOGLE_CREDENTIALS_PATH, GOOGLE_TOKEN_PATH</summary>

1. No <https://console.cloud.google.com>, crie um projeto e habilite a
   **Google Calendar API**.
2. Em Credenciais, crie um **ID do cliente OAuth 2.0** do tipo "Aplicativo para
   computador". Baixe o JSON.
3. Aponte `GOOGLE_CREDENTIALS_PATH` para o JSON baixado e `GOOGLE_TOKEN_PATH`
   para onde o token será salvo (fora do repositório).
4. Rode o fluxo de consentimento uma única vez:

   ```bash
   pip install google-auth-oauthlib
   python scripts/autorizar_google.py
   ```
</details>

<details>
<summary><b>Anthropic</b> — ANTHROPIC_API_KEY (opcional)</summary>

1. Crie uma chave em <https://console.anthropic.com/>.
2. Cole em `ANTHROPIC_API_KEY` e instale o SDK: `pip install anthropic`.

Sem essa chave o sistema usa o classificador heurístico local e continua
funcionando.
</details>

### 4. Verificar

```bash
python scripts/verificar_config.py
```

Diferente do `diagnostico`, este script bate nas APIs de verdade e confirma que
as credenciais funcionam.

### 5. Rodar

```bash
python -m sop escutar --processar   # tudo em um processo só
```

Ou separando captura de processamento (recomendado em produção):

```bash
python -m sop escutar    # terminal 1: captura e enfileira
python -m sop worker     # terminal 2: consome a fila
```

### Todos os comandos

| Comando | O que faz |
|---|---|
| `python -m sop diagnostico` | Mostra o que está configurado |
| `python -m sop agentes` | Lista os agentes carregados |
| `python -m sop demo` | Roda os exemplos fictícios, sem rede |
| `python -m sop classificar "texto"` | Classifica sem gravar nada |
| `python -m sop processar "texto"` | Fluxo completo (grava de verdade) |
| `python -m sop escutar` | Long polling do Telegram |
| `python -m sop worker` | Consome a fila durável |
| `python -m sop regras` | Lista as regras se-então carregadas |
| `python -m sop ritual` | Monta o pacote do ritual de domingo |
| `python -m sop simular` | Ritual de ponta a ponta com dados fictícios, sem rede |

---

## Automação de ponta a ponta

A automação demonstrável do projeto, em `src/sop/automacao.py`:

**Mensagem no Telegram → item classificado no Notion → evento na Google Agenda**

Passo a passo do que acontece quando alguém escreve
*"Reunião com o cliente na quinta às 14h"*:

1. **Captura** — o cliente do Telegram recebe o update, confere que o `chat_id`
   é o autorizado e converte em `Mensagem`.
2. **Enfileiramento** — a mensagem entra na fila durável em disco. A pessoa
   recebe confirmação sem esperar o resto.
3. **Classificação** — a camada de IA lê o texto e devolve, validado por JSON
   Schema: agente `beija-flor`, categoria `compromisso`, título
   "Reunião com o cliente", data `2026-09-03`, hora `14:00`.
4. **Validação de roteamento** — a orquestradora confirma que o agente existe e
   que a categoria pertence a ele. Se o modelo alucinar um agente inexistente,
   o roteamento é resgatado pela categoria.
5. **Registro** — o item é gravado no Notion com todas as propriedades.
6. **Agendamento** — como tem data e Psiu, o beija-flor, trabalha com agenda, um
   evento de 60 minutos é criado na Google Agenda.
7. **Confirmação** — o sistema responde no Telegram dizendo o que entendeu,
   onde guardou e se algo precisa de confirmação.

Ver funcionando sem configurar nada:

```bash
python -m sop demo
```

---

## O ciclo semanal: regras se-então e ritual de domingo

A automação da mensagem resolve o minuto. O ciclo semanal resolve a semana.

São duas peças, em `src/sop/regras.py` e `src/sop/ritual.py`:

**Agenda da semana + base de Regras → tarefas derivadas → ritual de domingo**

### O motor de regras

Todo compromisso gera efeito. Uma consulta médica não é só uma consulta: ela
exige que o dinheiro esteja separado antes. Se o dinheiro não estiver separado,
alguém precisa sacar, e isso vira outro compromisso. Uma coisa puxa a outra.

O motor lê os eventos da semana, cruza com uma base de regras editável e gera as
tarefas que nascem desse cruzamento. Uma regra tem esta forma:

| Campo | Para que serve |
|---|---|
| `Se` | O gatilho, escrito em uma frase |
| `Então` | A ação gerada, escrita em uma frase |
| `Área` | Casa, Escola, Saúde, Estudos, Projetos ou Finanças |
| `Origem` | `Agenda` cruza com os eventos, `Estoque` com a lista de essenciais |
| `Palavras-chave` | Termos separados por vírgula que reconhecem o gatilho |
| `Antecedência em dias` | Quantos dias antes a tarefa vence |
| `Ativa` | Desliga a regra sem apagá-la |
| `Observação` | Contexto para quem for executar |

Duas decisões que valem explicação:

- **Cada frase do `Então` vira uma tarefa.** Frases que começam com "Se" são
  efeitos de segunda ordem: dependem de uma checagem humana antes de existirem.
  É assim que a falta do dinheiro consegue gerar a tarefa de pedir para sacar,
  sem que o sistema precise adivinhar se o dinheiro está lá.
- **Os termos de `Palavras-chave` são alternativas, e um termo com mais de uma
  palavra é procurado como frase.** Isso permite escrever `escola da nina` sem
  que todo evento com a palavra `nina` dispare a regra. Na dúvida o motor gera a
  tarefa a mais, que se desmarca em um clique: esquecer o material da escola
  custa mais caro do que uma linha sobrando na lista.

A base de regras mora no Notion e é editada por quem usa, sem tocar em código.
Acrescentar uma regra nova não exige nenhum deploy. Sem a base configurada, o
motor cai em `exemplos/regras.json` e continua demonstrável.

```bash
python -m sop regras
```

### O ritual de domingo

Vinte minutos, uma vez por semana, em duas metades:

1. **Fechar a semana que terminou.** O sistema lista os compromissos que
   estiveram na agenda e devolve em checkbox. Ele não afirma o que foi feito,
   porque não tem como saber: quem marca é a pessoa. O que sobra é dividido
   entre o que volta para a semana seguinte e o que morre ali.
2. **Abrir a semana que começa.** Os compromissos da semana, os efeitos que eles
   geram pelo motor de regras, os essenciais que estão acabando, o checklist do
   que precisa estar pronto e as três prioridades.

O pacote sai pronto nos dois formatos: texto para o Telegram e blocos para o
Notion, com `to_do` de verdade, não parágrafo.

```bash
python -m sop ritual                        # imprime o pacote
python -m sop ritual --domingo 2026-03-08   # em outra data
python -m sop ritual --publicar --telegram  # cria o registro datado e envia
```

`--publicar` cria um registro próprio em `NOTION_RITUAIS_DATABASE_ID`, identificado
pela propriedade `Domingo`. A execução é idempotente: se aquela data já existe,
nada é duplicado. Os domingos anteriores recebem `Status = Fechado` e continuam
no mesmo banco; nada é apagado. Se `NOTION_TAREFAS_DATABASE_ID` estiver definido,
o registro relaciona as tarefas marcadas como feitas cujo prazo cai na semana,
sem copiar os dados da base `Prazos e tarefas`.

Nesta instalação, `scripts/ritual_domingo.sh` é a entrada segura para o cron:
usa a configuração do projeto, publica pela API gratuita e não envia Telegram.
Como a VPS roda em UTC, domingo às 19h de Brasília é:

```cron
0 22 * * 0 /bin/bash /caminho/do/projeto/scripts/ritual_domingo.sh >> /caminho/dos/logs/ritual-domingo.log 2>&1
```

### Ver funcionando sem configurar nada

```bash
python -m sop simular
```

Roda o ciclo inteiro com a semana fictícia de `exemplos/semana.json`, incluindo
uma consulta médica que gera as duas tarefas do efeito borboleta. Nenhuma API é
chamada.

---

## Testes

```bash
python -m pytest
```

**253 testes, nenhum toca em rede ou usa credencial real.** As APIs externas são
substituídas por sessões HTTP falsas e o cliente da Anthropic por um duplo que
registra os parâmetros recebidos.

| Arquivo | Cobre |
|---|---|
| `test_agentes.py` | Carga das definições, categorias sem sobreposição |
| `test_config.py` | Subir sem credencial, diagnóstico, mensagens de erro |
| `test_fila.py` | FIFO, retentativa, persistência entre processos, órfãs |
| `test_classificacao.py` | Datas relativas, extração de valor, roteamento, structured output |
| `test_automacao.py` | Fluxo ponta a ponta, falha parcial, fila |
| `test_integracoes.py` | Os três clientes de API, autorização, renovação de token |
| `test_seguranca.py` | Varredura de dados sensíveis no repositório |
| `test_regras.py` | Motor se-então: casamento de gatilho, efeito de segunda ordem, prazos |
| `test_ritual.py` | Limites das semanas, leitura da agenda, saída para Telegram e Notion |

Alguns testes que valem menção:

- `test_gasto_sem_valor_pede_confirmacao` — garante a regra de nunca inventar
  um número e fazer uma pergunta objetiva.
- `test_lacuna_essencial_pergunta_e_nao_grava` — impede que um item essencialmente
  incompleto seja salvo antes da resposta.
- `test_lacuna_secundaria_grava_e_avisa` — permite o registro útil, sem esconder
  o detalhe secundário que não foi informado.
- `test_falha_na_agenda_nao_perde_o_registro` — a agenda cai e o item ainda é
  gravado.
- `test_token_nao_vaza_no_erro` — o token do Telegram não aparece na exceção.
- `test_estado_persiste_entre_instancias` — a fila sobrevive ao processo.
- `test_recusa_do_modelo_cai_na_heuristica` — `stop_reason: refusal` não vira
  crash nem resposta vazia.
- `test_consulta_na_agenda_gera_as_duas_tarefas_do_efeito_borboleta` — o efeito
  de segunda ordem nasce junto com o direto.
- `test_fechamento_nao_inventa_o_que_foi_feito` — o sistema pergunta em vez de
  afirmar o que não tem como saber.
- `test_coluna_faltando_no_notion_nao_derruba_a_leitura` — a base de regras é
  editada à mão, e uma coluna renomeada não pode quebrar o domingo de ninguém.

---

## Prints

> Espaço reservado para as capturas de tela da entrega. Salve as imagens em
> `docs/prints/` e substitua cada bloco abaixo.

### 1. Bot no Telegram recebendo e confirmando

<!-- ![Conversa no Telegram](docs/prints/01-telegram.png) -->

_Print da conversa: a mensagem enviada e a confirmação do sistema._

### 2. Database do Notion com os itens classificados

<!-- ![Database do Notion](docs/prints/02-notion.png) -->

_Print da database com registros de agentes diferentes, mostrando as colunas
Agente, Categoria e Data._

### 3. Evento criado automaticamente na Google Agenda

<!-- ![Google Agenda](docs/prints/03-agenda.png) -->

_Print do evento na agenda, criado a partir da mensagem do Telegram._

### 4. Diagnóstico de configuração

<!-- ![Diagnóstico](docs/prints/04-diagnostico.png) -->

_Print do `python -m sop diagnostico` com as quatro integrações prontas._

### 5. Suíte de testes passando

<!-- ![Testes](docs/prints/05-testes.png) -->

_Print do `python -m pytest` com os 241 testes verdes._

### 6. Painel de acompanhamento

<!-- ![Painel](docs/prints/06-painel.png) -->

_Print de uma view do Notion agrupada por agente, servindo como painel de
acompanhamento da rotina._

---

## Estrutura do projeto

```
sop-pessoal/
├── agentes/                   definições dos agentes (um .md por agente)
├── docs/
│   ├── arquitetura.md         decisões de arquitetura
│   ├── fluxo.md               diagramas Mermaid
│   ├── seguranca.md           modelo de ameaças e controles
│   └── prints/                capturas de tela da entrega
├── exemplos/
│   ├── mensagens.json         12 mensagens fictícias para demonstração
│   ├── regras.json            regras se-então de exemplo
│   └── semana.json            semana fictícia para o `sop simular`
├── scripts/
│   ├── autorizar_google.py    fluxo OAuth, roda uma vez
│   ├── verificar_config.py    testa as credenciais contra as APIs
│   └── varredura_seguranca.sh varredura de dados sensíveis
├── src/sop/
│   ├── orquestradora.py       entende, decide, despacha
│   ├── automacao.py           fluxo de ponta a ponta
│   ├── regras.py              motor de regras se-então
│   ├── ritual.py              fechamento e abertura da semana
│   ├── fila.py                fila durável em disco
│   ├── agentes/               carga das definições
│   ├── integracoes/           telegram, notion, google_calendar, ia
│   ├── config.py              configuração e diagnóstico
│   ├── modelos.py             estruturas de dados
│   ├── datas.py               datas relativas em português
│   └── cli.py                 interface de linha de comando
└── tests/                     159 testes, sem rede
```

---

## Licença

MIT.
