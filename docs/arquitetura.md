# Arquitetura

Este documento registra as decisões de arquitetura e o porquê de cada uma. Os
diagramas estão em [`fluxo.md`](fluxo.md); o modelo de segurança em
[`seguranca.md`](seguranca.md).

---

## O problema

Quem tenta se organizar não sofre por falta de ferramenta — sofre por excesso.
A informação chega o dia inteiro em formatos diferentes e cada tipo mora em um
app diferente. O custo de **decidir onde registrar** acaba maior que o de
registrar, então nada é registrado.

A hipótese do projeto: se a captura for uma frase em um canal só, e a triagem
for automática, o sistema passa a ser usado.

---

## As quatro camadas

```
captura   →  recebe do mundo externo            integracoes/telegram.py
decisão   →  entende e roteia                   orquestradora.py + integracoes/ia.py
execução  →  regras de domínio e durabilidade   agentes/*.md + fila.py + automacao.py
registro  →  persiste                           integracoes/notion.py + google_calendar.py
```

A regra que sustenta o desenho: **cada camada só conhece a de baixo**. A captura
não sabe que o Notion existe; o Notion não sabe de onde a mensagem veio. Isso
tem consequência prática — trocar o canal de captura ou o banco de destino é
escrever uma classe nova, não refatorar o sistema.

---

## Decisão 1 — a orquestradora não executa nada

**Decisão:** a orquestradora entende, decide e despacha. Não grava, não formata,
não chama API de domínio.

**Alternativa descartada:** uma orquestradora que também executasse o trabalho.
É o caminho natural e mais curto no começo.

**Por quê:** porque a orquestradora é o único ponto por onde toda mensagem passa.
Se ela acumular lógica de domínio, cresce a cada agente novo e vira o gargalo de
manutenção do sistema — o clássico god object. Mantendo-a burra de propósito,
ela fica estável enquanto o resto cresce.

**Efeito colateral desejado:** adicionar um agente é criar um arquivo em
`agentes/`. O registro carrega o que encontrar no diretório e o roteamento passa
a considerar as categorias novas. Nenhuma linha de código muda.

---

## Decisão 2 — agentes em arquivo, não em código

**Decisão:** cada agente é um `.md` com cabeçalho de metadados e o prompt no
corpo.

**Alternativa descartada:** classes Python com o prompt em constante.

**Por quê:** três razões.

1. **O prompt é o produto.** Ajustar o comportamento de um agente é editar
   prose, não código. Quem edita não precisa saber Python.
2. **Regras de domínio não se generalizam.** O agente Financeiro tem uma regra
   que nenhum outro tem — nunca inventar um valor. O de Lifestyle tem outra —
   uma lista falada vira vários registros. Espremer isso num prompt único
   produziria algo impossível de manter.
3. **O prompt vira documentação.** Ler `agentes/financeira.md` é entender o que
   o agente faz, sem ler implementação.

**Restrição que isso impõe:** as categorias não podem se sobrepor entre agentes,
senão o roteamento fica ambíguo. Há um teste que falha se duas definições
declararem a mesma categoria.

---

## Decisão 3 — fila durável em disco

**Decisão:** a mensagem é enfileirada em arquivos JSON antes de ser processada.
Mudança de estado é `os.rename`.

**Alternativas descartadas:**

| Alternativa | Por que não |
|---|---|
| Processar na hora, em memória | Processo morre no meio → mensagem some sem rastro |
| Redis / RabbitMQ | Mais um serviço para instalar e manter, num sistema de uso pessoal |
| SQLite com tabela de fila | Funciona, mas exige lidar com lock de escrita concorrente |

**Por quê:** `rename` dentro do mesmo sistema de arquivos é atômico e é a trava.
Se dois workers tentarem reservar a mesma tarefa, só um consegue mover o
arquivo; o outro segue para a próxima. Durabilidade e exclusão mútua sem
dependência externa.

**O que isso habilita:** captura e processamento viram processos separados. Quem
escreveu recebe confirmação imediata, sem esperar três APIs responderem.

**Cuidado que exigiu:** o nome do arquivo é a chave de ordenação, então precisa
ser monotônico. Timestamp em microssegundos resolve entre processos; um contador
resolve empates dentro do mesmo processo — dois enfileiramentos no mesmo
microssegundo acontecem em rajada de mensagens e em teste.

---

## Decisão 4 — dois backends de classificação

**Decisão:** `ClassificadorAnthropic` e `ClassificadorHeuristico` implementam a
mesma interface. `criar_adaptador()` escolhe o disponível.

**Por quê:**

- **Demonstrabilidade.** Quem clona o repositório roda `python -m sop demo` e vê
  o sistema funcionando, sem criar conta em lugar nenhum.
- **Testabilidade.** A suíte inteira roda sem rede e sem custo.
- **Resiliência.** Sem chave, sem crédito ou com a API fora do ar, o sistema
  degrada em vez de parar.

**Preço:** duas implementações para manter, e a heurística é claramente pior.
Aceitável — ela existe para o sistema nunca ficar de pé sem funcionar.

**Detalhe de implementação:** a heurística também é o fallback quando o modelo
recusa a requisição (`stop_reason: "refusal"`). Uma recusa não pode virar
exceção nem resposta vazia.

---

## Decisão 5 — structured output em vez de parsing

**Decisão:** a chamada à Messages API usa `output_config.format` com um JSON
Schema. A validação acontece na API.

**Alternativa descartada:** pedir JSON no prompt e fazer `json.loads` na
resposta.

**Por quê:** pedir JSON no prompt funciona na maior parte das vezes, e é
exatamente esse "maior parte" que gera bug intermitente — o modelo embrulha em
bloco de código, adiciona um comentário, ou muda um nome de campo. Com o schema
declarado, a API garante o formato e o código não precisa de parsing defensivo.

**O que ainda foi preciso validar no código:** o schema garante o *formato*, não
a *semântica*. O modelo pode devolver um agente que não existe. A orquestradora
confere se o agente está no registro e, se não estiver, tenta resgatar o
roteamento pela categoria antes de cair no padrão.

---

## Decisão 6 — Notion como banco, não Postgres

**Decisão:** o banco é uma database do Notion.

**Por quê:** requisito da disciplina pedia banco no-code, mas a escolha se
sustenta sozinha. O dono deste sistema não escreve SQL. Num Postgres, corrigir
um registro classificado errado exigiria uma interface administrativa —
mais código para manter. No Notion, a pessoa abre, filtra, edita e arrasta. A
database também **é** o painel de acompanhamento: uma view agrupada por agente
resolve o requisito de painel sem construir front-end.

**O que se perde:** performance e consultas complexas. Irrelevante na escala de
uma pessoa registrando algumas dezenas de itens por semana.

---

## Decisão 7 — falha parcial não derruba o fluxo

**Decisão:** cada destino é tentado isoladamente. Erro entra em
`ResultadoAutomacao.erros` e o fluxo continua.

**Por quê:** os destinos não têm o mesmo valor. **Perder o registro é pior que
perder o evento** — o registro é a memória do sistema; o evento é conveniência
que a pessoa consegue recriar. Se a Google Agenda cair, o item ainda vai para o
Notion e a resposta diz o que falhou.

**Consequência:** um resultado pode ser parcialmente bem-sucedido.
`ResultadoAutomacao.sucesso` é `False` se houve qualquer erro, mas
`id_no_banco` pode estar preenchido. Quem consome precisa olhar os dois.

---

## Decisão 8 — configuração ausente não é exceção

**Decisão:** `Config` nunca levanta erro por falta de credencial. Só
`exigir(config, integracao)` levanta, e apenas quando alguém tenta usar aquela
integração.

**Por quê:** um projeto que quebra no import sem `.env` é hostil com quem acabou
de clonar. Aqui, `python -m sop diagnostico` roda em um repositório recém-clonado
e explica exatamente o que falta e onde configurar.

**A mensagem de erro é parte da decisão.** Ela diz a integração, as variáveis
faltantes e o comando para começar (`cp .env.example .env`). Um teste verifica
que `.env.example` aparece no texto — erro que não diz o próximo passo é erro
pela metade.

---

## Decisão 9 — só `requests` como dependência obrigatória

**Decisão:** `requests` é a única dependência obrigatória. `anthropic` e
`google-auth-oauthlib` são opcionais.

**Por quê:** o Google Calendar precisa de três chamadas REST. Trazer
`google-api-python-client` (que arrasta `httplib2`, `google-auth`, `protobuf`)
para isso não se paga. O que é realmente chato de implementar — o fluxo
interativo de consentimento — fica isolado em `scripts/autorizar_google.py`, que
roda uma vez e é o único lugar que precisa da biblioteca do Google.

**Resultado:** `pip install -r requirements.txt` instala `requests` e `pytest`.
O projeto roda em qualquer ambiente com Python 3.10.

---

## O que ficou de fora, e por quê

| Não implementado | Motivo |
|---|---|
| Webhook do Telegram | Long polling não exige HTTPS público nem domínio. Trocar depois é mudar um método. |
| Múltiplos usuários | O sistema é de uso pessoal. Multiusuário exigiria isolar credenciais por pessoa — outro projeto. |
| Front-end próprio | A database do Notion já é o painel. Construir um seria duplicar o que existe. |
| Edição por conversa | Corrigir um item se faz no Notion, que já é bom nisso. |
| Cache de classificação | Volume de uma pessoa não justifica. |

---

## Como estender

**Agente novo:** crie `agentes/<nome>.md` com `nome`, `titulo`, `dominio`,
`categorias`, `integracoes` e `cria_evento` no cabeçalho, e o prompt no corpo.
As categorias não podem colidir com as existentes. Nenhum código muda.

**Canal de captura novo:** escreva um cliente que produza `Mensagem` e chame
`orquestradora.despachar()`. A orquestradora não sabe nem se importa com a
origem.

**Banco de destino novo:** escreva uma classe com `criar_item(item) -> str` e
passe em `Automacao(orquestradora, banco=...)`. O protocolo `DestinoBanco` em
`automacao.py` documenta o contrato.

**Backend de IA novo:** implemente `classificar(texto, registro, hoje) ->
Classificacao` com um atributo `origem`. Passe para a orquestradora.
