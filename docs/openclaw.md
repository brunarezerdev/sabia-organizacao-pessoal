# OpenClaw: como os agentes são declarados e executados

Este documento cobre a camada de execução dos agentes. A arquitetura do
sistema está em [`arquitetura.md`](arquitetura.md); a instalação passo a passo,
no [`README.md`](../README.md).

---

## O modelo mental

O OpenClaw é o runtime dos agentes. Ele resolve três coisas que o projeto teria
de resolver sozinho: onde o provedor de IA se autentica, como cada agente fica
isolado do outro, e quais ferramentas cada um pode usar.

A divisão de responsabilidade é esta:

| Camada | Onde vive | Do que cuida |
|---|---|---|
| Definição do agente | `agentes/*.md` | Identidade, domínio, prompt, tools |
| Declaração do projeto | `openclaw/agentes.json` | Lista o que registrar no OpenClaw |
| Alma de cada agente | `openclaw/workspaces/<id>/SOUL.md` | O prompt que o agente lê ao subir |
| Configuração real | `~/.openclaw/openclaw.json` | Escrita **pelo CLI**, nunca à mão |

A fonte de verdade é `agentes/*.md`. As outras duas linhas são geradas:

```bash
python -m sop openclaw              # gera
python -m sop openclaw --verificar  # confere se está em dia (sai 1 se não)
```

Há um teste (`test_declaracao_versionada_esta_em_dia`) que falha se alguém
editar um agente e esquecer de regerar. A inconsistência quebra o build em vez
de aparecer só quando o agente já estiver rodando errado.

### Por que a config real não é escrita à mão

Na versão 2026.6.5 o schema do `openclaw.json` valida na escrita. Um bloco
escrito manualmente falha com `OpenClaw config is invalid: <root>: Invalid
input`. Pior: os subagentes vivem em `agents.list[]`, e um `openclaw config
patch` nesse array é recusado com `Refusing to replace agents.list; it would
remove existing entries`, porque patch substitui array em vez de fazer merge.

O caminho que funciona é o subcomando dedicado `openclaw agents add`, que faz
append não destrutivo, valida na escrita e cria o workspace. É o que
`scripts/openclaw/registrar_agentes.sh` faz, um agente por vez.

---

## Os agentes

Cinco agentes constam na declaração: a Sábia e quatro especialistas de domínio.
`beija-flor`, `abelha` e `cervo` continuam no roteamento Python, mas têm
`openclaw_ativo: false` e não são registrados no OpenClaw; agenda e rotina
doméstica seguem com a `juliana-ops`. A Borboleta nasceu depois da instalação
e só entra na configuração ativa quando `registrar_agentes.sh` rodar.

Os ids `financeira`, `projetos` e `educacional` foram renomeados para `esquilo`,
`raposa` e `elefante` em 29/08/2026, junto com a adoção da identidade da Sábia.
A declaração do projeto já usa os nomes novos; o registro vivo do OpenClaw ainda
tem os antigos, e só passa a valer depois de rodar
`scripts/openclaw/registrar_agentes.sh`.

| id | Nome | Papel | Modelo | Tools |
|---|---|---|---|---|
| `main` | Sábia 🦉 | Compreender, decidir e despachar | `openai/gpt-5.5` | `fs.read`, `grep`, `agent.invoke` |
| `esquilo` | Esquilo 🐿️ | Guardar: finanças, compras, estoque | `openai/gpt-5.5` | `fs.read`, `fs.write` |
| `raposa` | Raposa 🦊 | Planejar: projetos, metas, prioridades | `openai/gpt-5.5` | `fs.read`, `fs.write` |
| `elefante` | Elefante 🐘 | Lembrar: memória, documentos, registros | `openai/gpt-5.5` | `fs.read`, `fs.write` |
| `borboleta` | Borboleta 🦋 | Crescer: educação, estudos, desenvolvimento pessoal | `openai/gpt-5.5` | `fs.read`, `fs.write`, `web.fetch` |

### Como as tools foram escolhidas

A regra é dar o menor conjunto que resolve o trabalho. Cada tool a mais é
superfície de erro e de custo.

- **`fs.read` + `fs.write`** para todo agente de domínio: ele lê o contexto e
  produz o registro. Nada além disso.
- **`web.fetch`** só na Borboleta, que precisa abrir o material de estudo
  referenciado na mensagem. Era do Elefante até 29/08/2026, quando o estudo
  saiu dele; a tool foi junto com o escopo.
- **`agent.invoke`** só na orquestradora. Dar delegação a um especialista abre
  caminho para loop infinito: A chama B, B chama A. Há um teste que garante
  que nenhum subagente tem essa tool.
- **`shell.exec`** em ninguém. Nenhum agente deste sistema precisa executar
  comando, e um agente com shell erra caro. Também tem teste.

Mudar as tools de um agente é editar o `tools:` do arquivo dele em `agentes/` e
rodar `python -m sop openclaw`.

### Modelo por agente

Todos usam o modelo do projeto (`OPENCLAW_MODELO`). Um agente que precise de
outro modelo declara `modelo: provider/nome` no próprio arquivo, e esse valor
vence — útil para mandar um agente barato cuidar de tarefa mecânica sem mexer
no resto.

---

## O provedor de IA

**Provider `openai`, rota Codex, autenticada por OAuth.**

No OpenClaw o provider se chama `openai` e a rota Codex roda pelo plugin codex
nativo. A autenticação é OAuth por device-code e consome a cota da assinatura
ChatGPT Plus.

> **Não existe API key para o Codex CLI.** Se você procurar por uma, não vai
> encontrar, e nenhum passo deste projeto pede uma. O `.env.example` tem uma
> variável `OPENAI_API_KEY`, mas ela serve a outra coisa: a rota alternativa
> por API, opcional e independente. Preencher ou não preencher aquela variável
> não muda nada na rota Codex.

O login é feito uma vez:

```bash
bash scripts/openclaw/configurar_provedor_openai.sh
```

O script imprime uma URL e um código. Abra a URL no navegador de um computador
já logado no ChatGPT Plus, digite o código e autorize. O CLI da máquina detecta
sozinho — nada é colado de volta no terminal. Foi desenhado assim para
funcionar em VPS sem navegador.

### O provedor continua trocável

A camada de IA (`src/sop/integracoes/ia.py`) expõe quatro backends atrás da
mesma interface:

| Backend | Como autentica | Quando usar |
|---|---|---|
| `openclaw` | Nenhuma credencial aqui; o OpenClaw resolve | Produção |
| `openai` | `OPENAI_API_KEY` | Se um dia preferir chamar a API direto |
| `anthropic` | `ANTHROPIC_API_KEY` | Rota alternativa |
| `heuristica` | Nada | Demonstração, testes, degradação |

`IA_BACKEND` força um; vazio deixa o sistema escolher pela ordem
`openclaw → openai → anthropic → heuristica`. Nenhum caminho levanta exceção
por falta de credencial: não conseguir usar IA custa precisão, não derruba o
sistema. Trocar de provedor não pede alteração na orquestradora, nos agentes
ou na automação.

---

## Pontos a confirmar

Coisas que **não foram verificadas na prática** porque o OpenClaw não está
instalado na máquina onde este código foi escrito. Estão marcadas aqui em vez
de documentadas como se fossem certeza.

### 1. Invocação não interativa para uma classificação

O backend `openclaw` precisa rodar o agente principal de forma não interativa,
mandando a instrução pela entrada padrão e lendo JSON da saída. O comando exato
não foi confirmado, então **não há um padrão chutado no código**: a variável
`OPENCLAW_COMANDO` começa vazia e, sem ela, o sistema usa o heurístico.

Para resolver, na máquina com o CLI instalado:

```bash
openclaw agents --help
openclaw --help | grep -iE "run|send|prompt|message"
```

Descoberto o comando, preencha no `.env`, com `{agente}` no lugar do id:

```bash
OPENCLAW_COMANDO=openclaw agents run {agente} --non-interactive
```

Depois confirme com `python -m sop diagnostico`, que mostra qual backend
responderia agora, e com `python -m sop classificar "reunião quinta às 14h"`.

### 2. Restrição de tools na registração

O roteiro de referência documenta `openclaw agents add <id> --non-interactive
--workspace <ws> --model <modelo>`. Uma flag `--tools` **não aparece lá**, e o
script de criação de subagente do curso resolve isso escrevendo o campo `tools`
direto no `openclaw.json` — o que o mesmo roteiro desaconselha para a 2026.6.5.

Como as duas fontes se contradizem, `registrar_agentes.sh` não escolhe por
conta própria: ele pergunta ao CLI (`openclaw agents add --help`), usa
`--tools` se a flag existir e, se não existir, avisa em voz alta que as tools
ficaram declaradas mas não aplicadas.

Em ambos os casos as tools continuam escritas no `SOUL.md` de cada agente, o
que restringe por instrução. A confirmar: se a versão instalada aceita a flag,
ou qual é o subcomando que aplica a restrição de verdade.

### 3. Versão do CLI

O bootstrap fixa `openclaw@2026.6.5`, seguindo o repositório de referência, que
registra que `@latest` quebra o polling do Telegram. Se a Bruna quiser uma
versão mais nova, vale conferir antes se o polling continua funcionando.

---

## Diagnóstico

| Sintoma | Causa provável |
|---|---|
| `Gateway start blocked ... missing gateway.mode` (exit 78) | Falta `openclaw config set gateway.mode local` |
| `OpenClaw config is invalid: <root>: Invalid input` | Alguém escreveu o `openclaw.json` à mão |
| `Refusing to replace agents.list` | Tentou registrar subagente com `config patch`; use `agents add` |
| Subagente não responde | Confira `openclaw agents list` e se o `SOUL.md` do workspace existe |
| Classificação caindo sempre no heurístico | `OPENCLAW_COMANDO` vazio; ver "Pontos a confirmar" |
| Bot não responde no Telegram | Seu id não está em `allowFrom`; rode `configurar_telegram.sh` de novo |

Para voltar a um estado bom:

```bash
cp ~/.openclaw/openclaw.json.last-good ~/.openclaw/openclaw.json
systemctl restart openclaw-gateway
```

Documentação oficial: <https://docs.openclaw.ai>
