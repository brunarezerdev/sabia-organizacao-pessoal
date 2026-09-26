# Wiki Sábia sanitizada: template público para a banca

Investigação e plano. **Nada foi criado, duplicado, publicado ou alterado no Notion.**
Auditoria feita em 01/09/2026, somente leitura, pela integração do projeto.

---

## 1. A pergunta das credenciais, respondida com prova

A pergunta da Bruna foi "como mandar um template sem minhas credenciais". A resposta
honesta tem duas partes, e a segunda é a que importa.

### 1.1 As credenciais nunca estiveram no Notion

Os segredos do projeto vivem **fora** do Notion, no servidor:

- `.env`, na raiz privada do projeto, com permissão `-rw-------` (só o dono lê).
- `.gitignore` bloqueia `.env` e `.env.*` (linhas 4 e 5), então não vão para o git.
- O token do Notion é lido em runtime de `NOTION_TOKEN` / `NOTION_TOKEN_PATH` e vai
  no header `Authorization: Bearer` de cada chamada
  (`src/sop/integracoes/notion.py`, linhas 59 a 63). Nunca é escrito em página.

Varredura de confirmação sobre os 1554 objetos que a integração enxerga no Notion,
procurando padrões de segredo no conteúdo:

| padrão | ocorrências |
| --- | --- |
| `ntn_...` / `secret_...` (token Notion) | 0 |
| `sk-...` (OpenAI) | 0 |
| `sk-ant-...` (Anthropic) | 0 |
| `<id>:<hash>` (bot Telegram) | 0 |
| cabeçalho de chave privada PEM (service account Google) | 0 |
| `Bearer ...` | 0 |

Ou seja: **nenhuma página do Notion carrega credencial**. Publicar uma página não
vaza token, porque token não mora lá. Duplicar como template também não: a cópia
leva blocos e registros, não variáveis de ambiente do servidor.

### 1.2 O risco real não é credencial, é conteúdo pessoal

O que vaza numa página compartilhada é o que está escrito nela e em tudo abaixo dela.
Encontrado de fato na árvore atual:

- **E-mail pessoal da Bruna em texto puro**, na propriedade `Agenda` (rich_text) de
  11 registros da base `Agenda (Google)`, dentro do JARDIM.
- **Nome e foto da Bruna** na propriedade `Proprietário` (tipo `people`) da base-wiki
  `Ecossistema Sábia` e das páginas Biblioteca e Series tracker.
- **Finanças reais**: páginas Finanças, Patrimônio, Assinaturas, Recursos no CELEIRO;
  bases `expenses` (18 linhas), `income`, `budget`, `balance calculator`.
- **Família e saúde**: NINHO com página Família e Manutenção; base `Regras` com itens
  como "Atividade na escola do Don pede item" e "Consulta médica pede dinheiro em mãos".
- **Rotina e corpo**: CULTIVO com `Hábitos` e `Hábitos diários` (29 linhas: acordar às 7,
  gua sha, exercícios, leitura), base `Journal`.
- **Documentos e histórico**: ARQUIVO com Documentos, Histórico, Registros.
- **Escolha musical e horário**: dois embeds de playlist do Spotify (NINHO e HERBÁRIO).
- **IDs internos e URLs**: toda página duplicada carrega os IDs do Notion, e o link
  `https://sabia-dashboard-demo.vercel.app` embutido no CELEIRO.

Sobre comentários e histórico de edição em página publicada: a documentação do Notion
consultada **não afirma** o que o visitante anônimo vê. Não dá para tranquilizar sobre
isso com fonte. Tratar como não verificado e simplesmente não ter comentário nem
histórico relevante na página nova.

---

## 2. O que a documentação oficial do Notion diz hoje

Fontes consultadas em 01/09/2026:

- [Publish a website with Notion Sites](https://www.notion.com/help/public-pages-and-web-publishing)
- [Duplicate public Notion pages](https://www.notion.com/help/duplicate-public-pages)
- [Sharing & permissions settings in Notion](https://www.notion.com/help/sharing-and-permissions)
- [The ultimate guide to Notion templates](https://www.notion.com/help/guides/the-ultimate-guide-to-notion-templates)
- [Database relations & rollups in Notion](https://www.notion.com/help/relations-and-rollups)
- [Notion API reference](https://developers.notion.com/reference/intro) e o índice
  [llms.txt](https://developers.notion.com/llms.txt)

### 2.1 Publicar em leitura

Caminho na interface atual: abrir a página, `Share` no topo, aba `Publish`, botão
`Publish`. Isso é o Notion Sites, e é diferente de marcar
`"Anyone on the web with link"` no menu `Share`.

Por padrão o visitante só lê. Para comentar ou editar ele precisaria estar logado no
Notion e ter permissão explícita. Os níveis são `Full access`, `Can edit`,
`Can comment`, `Can view`.

### 2.2 Duplicação como template

A opção chama-se literalmente **`Duplicate as template`**, no cabeçalho de configurações
da página publicada. Ligada, ela permite que "your site visitors to duplicate your
Notion Site as a Notion page in their own workspace". Desligada, ninguém duplica.

O que a duplicação leva: a página e **"all the sub-pages contained in the original
page"**, incluindo bases e o conteúdo das bases, para a seção Private do workspace de
quem duplicou, que passa a poder editar como qualquer página dele.

### 2.3 Subpáginas: o ponto crítico

Publicar uma página publica **todas as subpáginas dela, e as subpáginas das
subpáginas**, automaticamente. É preciso conferir tudo antes de publicar. Dá para
restringir a permissão de uma subpágina para escondê-la, mas isso vira uma lista de
exceções que precisa estar 100% certa, e é o que torna a rota "duplicar e limpar"
perigosa (seção 4).

### 2.4 Relação que aponta para fora do escopo duplicado

Quando uma base com relação é duplicada, o Notion **converte a relação de 2-way sync
para 1-way sync**, e a base duplicada não aparece de volta como relação na base
original. Na prática, relação que aponta para base que ficou fora do que foi duplicado
chega quebrada ou vazia no workspace do avaliador. A doc também avisa que blocos sem
permissão aparecem como `No access` na cópia e podem ser apagados.

Isso é decisivo para o POMAR: `Receitas`, `Ingredientes` e `Planejamento de Refeições`
se relacionam entre si. Ou as três entram no template juntas, ou a relação morre.

### 2.5 O que a API faz e o que não faz

A API do Notion (versão atual `2026-03-11`) tem endpoints para criar página, criar
database, criar data source, e **criar view** (`POST /views`, `GET /views`,
`PATCH /views`). O projeto já usa isso no módulo privado de integração da agenda,
função `criar_views_padrao`, que cria as views Hoje / Esta semana / Mês.

A API **não tem** endpoint para publicar página na web nem para duplicar página. Essas
duas ações só existem no aplicativo. Publicar é clique da Bruna, sempre.

---

## 3. Auditoria da árvore atual (somente leitura)

A integração enxerga **1554 objetos: 1464 páginas e 90 databases**.

A raiz da wiki é **`Ecossistema Sábia`**, e é uma **base-wiki no topo do workspace**
(id `3c7ef9c8-0d22-8069-a484-dbec6f7919a7`), não uma página comum. Ela tem **33 linhas**.
Os 9 territórios são 9 dessas 33 linhas. As outras 24 são páginas pessoais soltas no
mesmo nível: Finanças, Patrimônio, Assinaturas, Documentos, Histórico, Registros,
Família, Manutenção, Semana, Mês, Trimestre, Ano, Biblioteca, Ritual de Domingo,
Registro do Sistema, e as três bases DEMO.

Isso já responde a pergunta 3 da tarefa: **publicar ou duplicar a raiz arrasta as 33
linhas, não só os 9 territórios.**

### 3.1 O que cada território arrasta

| Território | Filhos diretos | Pessoal? |
| --- | --- | --- |
| NINHO · Família & Lar | embed Spotify, view de `Planejamento de Refeições`, páginas Família e Manutenção | **sim, tudo** |
| JARDIM · Visão Geral | bases `Registro do Sistema` (13 linhas) e `Agenda (Google)` | **sim**: a Agenda tem o e-mail dela em 11 linhas |
| FLORESTA · Projetos | base `Projetos em Andamento` (5 linhas) | parcial |
| POMAR · Alimentação | 6 bases, entre elas `Receitas` (85), `Ingredientes` (213/220), `Planejamento de Refeições` (35) | **sim**, e com relações cruzadas |
| CULTIVO · Pessoal | `Hábitos`, `Hábitos diários` (29 linhas), página Biblioteca | **sim, rotina e corpo** |
| HERBÁRIO · Conhecimento | embed Spotify, `Parts of My Life (2)` | parcial |
| CELEIRO · Recursos | 3 bases DEMO, páginas Finanças / Patrimônio / Assinaturas / Recursos, embed do dashboard | **misto: DEMO limpo ao lado de real** |
| ARQUIVO · Memória | páginas Documentos, Histórico, Registros | **sim** |
| OBSERVATÓRIO · Planejamento | link para Ritual de Domingo, páginas Semana / Mês / Trimestre / Ano, base `Prazos e tarefas` (14 linhas) | parcial |

### 3.2 Detalhe que quebra o atalho

As três bases DEMO (`DEMO — Lançamentos financeiros` 20 linhas, `DEMO — Custos fixos e
assinaturas` 9, `DEMO — Orçamento por categoria` 8) têm como pai a **página `Finanças`**,
que é pessoal. Não dá para publicar o CELEIRO DEMO sem levar a Finanças junto, a não ser
mexendo na árvore real da Bruna. O conteúdo delas está limpo: auditei os 20 lançamentos,
todos começam com `DEMO —` e a observação diz "DADO FICTÍCIO. Não representa pessoa,
operação ou transação real". Serve de material de partida para o template novo.

---

## 4. Caminho recomendado, e por que o outro é pior

### Recomendado: construir uma página-template NOVA, isolada

Uma página nova, fora da base-wiki `Ecossistema Sábia`, sem nenhuma subpágina pessoal
embaixo, replicando só a **estrutura**: 9 territórios, as bases, as propriedades, as
views, com 2 a 3 registros fictícios por base e selo de ambiente DEMO.

Por que é o caminho certo:

1. **Segurança por construção, não por exceção.** Nada pessoal entra, então nada pessoal
   pode escapar. Não depende de lembrar de esconder subpágina nenhuma.
2. **Publicar é seguro por padrão.** Como publicar arrasta toda a subárvore, a única
   garantia forte é a subárvore não ter nada.
3. **A duplicação funciona de verdade.** Relação só sobrevive se as duas pontas estiverem
   dentro do escopo duplicado. Numa página construída para isso, ficam.
4. **A banca vê a arquitetura, que é o que está sendo avaliado.** Integração de APIs se
   demonstra com esquema, propriedades, relações e views, não com o extrato da Bruna.
5. **Zero risco para a operação real.** A árvore da Bruna não é tocada.

### Alternativa: duplicar a raiz e limpar. É pior.

- Duplicar a raiz traz **33 páginas de topo mais toda a subárvore**, incluindo 1464
  páginas visíveis. Limpar isso à mão é um trabalho grande com chance alta de sobrar coisa.
- A limpeza é uma **lista de exceções**. Uma subpágina esquecida vai ao ar publicada, e
  publicada com atualização automática.
- **O e-mail dela está em campo rich_text** dentro de 11 registros. Isso não se resolve
  apagando página, tem que editar registro por registro.
- Propriedade `people` carrega nome e foto de quem é dono. Sobrevive à duplicação.
- Ao duplicar bases com relação, o Notion **converte 2-way em 1-way**. Se depois a Bruna
  apagar bases da cópia, o que sobra fica com relação quebrada e views vazias, e o
  template chega na banca com aparência de coisa mal feita.
- Custo de tempo parecido, risco muito maior.

Só vale duplicar se a intenção fosse entregar o conteúdo real, o que não é o caso.

---

## 5. Plano de execução

### 5.1 Divisão de trabalho

| Etapa | Quem | Como |
| --- | --- | --- |
| Criar página-raiz vazia do template | **Bruna, no app** | a API não cria página no topo do workspace sem um pai já compartilhado |
| Compartilhar essa página com a integração | **Bruna, no app** | sem isso a API responde 404 |
| Criar os 9 territórios, as bases, as propriedades | Ária, via API | `POST /pages`, `POST /databases`, `POST /data_sources` |
| Criar as views (tabela, calendário, board) | Ária, via API | `POST /views`, padrão já usado em `criar_views_padrao` |
| Popular 2 a 3 registros fictícios por base | Ária, via API | `POST /pages` com parent data source |
| Selo DEMO em cada território e cada base | Ária, via API | callout no topo + propriedade `Dados de demonstração` |
| Conferir se sobrou algo pessoal | Ária, via API | releitura da subárvore inteira |
| **Publicar e ligar `Duplicate as template`** | **Bruna, no app** | não existe endpoint de publicação |
| Validação em janela anônima | Bruna, e Ária pelo link público | seção 6 |

### 5.2 Passo a passo da Bruna, com os cliques

**Antes de a Ária começar:**

1. Abrir o Notion no computador.
2. Na barra lateral esquerda, passar o mouse sobre `Private` e clicar no `+` que aparece.
   Isso cria uma página nova no topo, fora da base-wiki `Ecossistema Sábia`.
3. Dar o nome: `Sábia — Template público (DEMO)`.
4. Com a página aberta, clicar em `Share`, no canto superior direito.
5. Clicar no campo de busca do menu que abriu, digitar o nome da integração do projeto e
   selecioná-la. Deixar em `Full access`.
6. Ainda no menu `Share`, copiar o link da página e mandar para a Ária. É por esse link
   que a Ária descobre o id e começa a construir.

**Depois que a Ária avisar que a estrutura está pronta:**

7. Abrir `Sábia — Template público (DEMO)` e ler de cima a baixo, entrando em cada um dos
   9 territórios. Conferir se todo registro tem cara de fictício.
8. Clicar em `Share`, ir na aba `Publish`, clicar em `Publish`.
9. Ainda na aba `Publish`, ligar o toggle **`Duplicate as template`**.
10. Decidir o toggle de indexação. Em `Search engine indexing`, deixar
    `Discoverable on the web` **desligado**, porque a banca recebe o link direto e não há
    motivo para o template aparecer no Google.
11. Copiar o link público e mandar para a Ária, para a validação da seção 6.
12. Depois da entrega, voltar em `Share`, aba `Publish`, e clicar em `Unpublish` quando o
    trabalho já tiver sido avaliado.

**Nunca:** arrastar uma página existente para dentro do template, nem usar
`Duplicate` numa página da árvore real. É assim que dado pessoal entra sem ninguém ver.

---

## 6. Protocolo de validação, obrigatório antes de mandar

Sem esses seis passos, o link não vai para a banca.

1. **Janela anônima.** Abrir o link público numa janela anônima do navegador, sem estar
   logada no Notion. Se pedir login, a publicação não está valendo.
2. **Percorrer os 9 territórios.** Entrar em cada um. Nenhum deve levar a página fora do
   template.
3. **Abrir todas as bases e todas as views.** Conferir aba por aba: tabela, calendário,
   board. View filtrada pode esconder linha na tela e mostrar na duplicação.
4. **Caçar nome e e-mail.** `Ctrl+F` na janela anônima procurando `gmail`, `bruna`,
   `rezer` e o nome dos filhos. Zero resultado. Conferir também se alguma base tem
   propriedade do tipo `people` preenchida.
5. **Testar a duplicação como terceiro.** Numa conta de Notion que **não seja** a da Bruna
   (uma conta gratuita nova serve), abrir o link, clicar em `Duplicate` no topo, e abrir a
   cópia em Private. Conferir: os 9 territórios vieram, as bases vieram com registros, as
   relações do POMAR funcionam, e não aparece nenhum bloco `No access`.
6. **Conferir o embed.** O dashboard `sabia-dashboard-demo.vercel.app`, se for embutido,
   tem que abrir na anônima e mostrar só dado DEMO.

Bloco `No access` na cópia é sinal de que sobrou referência para fora do template.
Nesse caso, corrigir antes de entregar.

---

## 7. Esforço

Contagem do que precisa ser construído, a partir do mapa da seção 3:

- 1 página-raiz (Bruna cria)
- 9 páginas de território
- 14 subpáginas de estrutura (Família, Manutenção, Finanças, Patrimônio, Assinaturas,
  Recursos, Documentos, Histórico, Registros, Biblioteca, Semana, Mês, Trimestre, Ano)
- 13 bases: Registro do Sistema, Agenda (Google), Projetos em Andamento, Receitas,
  Ingredientes, Planejamento de Refeições, Hábitos, Hábitos diários, Parts of My Life,
  Prazos e tarefas, e as 3 DEMO financeiras
- 4 relações a recriar: Receitas ↔ Ingredientes, Receitas ↔ Planejamento de Refeições,
  Hábitos ↔ Hábitos diários
- cerca de 30 registros fictícios, 2 a 3 por base
- 20 a 25 views

Total: **em torno de 37 objetos e 30 registros.** Tudo pela API, sem clique manual, fora
os dois momentos da Bruna (criar e compartilhar a raiz no começo, publicar no fim).

**Dá para fazer hoje**, desde que a Bruna faça os passos 1 a 6 da seção 5.2 primeiro. A
construção via API é da ordem de uma a duas horas de execução, dominada pelo limite de
requisições do Notion, que o projeto já respeita em `scripts/backup_notion.py`. A
validação da seção 6 depende do tempo dela e da conta de teste do passo 5.

**Precisa da autorização dela para:** criar a página-raiz, compartilhar com a integração,
e liberar a Ária para escrever dentro dessa página. Nada da árvore real é tocado em
momento nenhum.
