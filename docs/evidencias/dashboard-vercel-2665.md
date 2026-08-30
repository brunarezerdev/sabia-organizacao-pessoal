# Deploy do dashboard DEMO na Vercel, tarefa 2665, 30/08/2026

Fecha o que a tarefa 2637 deixou em aberto: lá faltava credencial, aqui a Bruna
mandou o token e o deploy aconteceu.

**URL pública: <https://sabia-dashboard-demo.vercel.app>**

## Provado

### Credencial e escopo

- O token autentica na conta pessoal da Bruna na Vercel (usuário
  `brunarezerdev`), confirmado por `GET /v2/user`.
- Existe **um único escopo** disponível, `brunarezerdevs-projects`. Não houve
  escolha de time a fazer, então nada ficou parado esperando decisão.
- O projeto `sabia-app`, que já existia na conta (FastAPI, com `OPENAI_API_KEY`,
  `SABIA_DATABASE_URL` e outras variáveis reais), foi **apenas lido** para
  confirmar que era outra coisa. Nenhuma alteração nele.
- Projeto novo criado: `sabia-dashboard-demo`. Única variável em Production:
  `SABIA_DEMO=1`.

### Deploy

- Deploy de produção `READY` a partir do repositório local, respeitando o
  `vercel.json` já existente (`outputDirectory: dashboard`, função
  `api/dashboard.py`).
- Suíte completa verde **antes** do deploy: 301 testes.
- A primeira tentativa **falhou** e está registrada de propósito: o
  `.vercelignore` que escrevi como lista de permissão usava `*` + `!api/**`, e
  subiu 853 bytes (só o `vercel.json`), quebrando com
  `The pattern "api/dashboard.py" ... doesn't match any Serverless Functions`.
  Causa: não dá para reincluir arquivo cujo diretório-pai já foi excluído. A
  correção troca `*` por `/*`, que casa só a profundidade 1 — nada dentro de
  `api/` e `dashboard/` chega a ser excluído. Segunda tentativa subiu limpa.

### Segredos fora do bundle

A raiz do repositório tem `.env` com credenciais reais em uso (Telegram, Notion
das bases pessoais, OpenAI, Anthropic) e `backups/` com dumps do Notion da
Bruna. Não havia `.vercelignore`, então um deploy ingênuo levaria tudo isso para
a Vercel. O `.vercelignore` criado é lista de permissão: **só** `api/`,
`dashboard/` e `vercel.json` sobem. Arquivo sensível novo na raiz já nasce
excluído.

Efeito colateral desejado: sem `package.json` no bundle, a Vercel não roda build
de Node nem instala as 296 dependências do runtime dos agentes.

### Verificação por HTTP real, na URL pública

| Checagem | Resultado |
| --- | --- |
| `GET /` anônimo, sem cookies | `200`, 2152 bytes, sem tela de login |
| Selo `AMBIENTE DEMO · DADOS FICTÍCIOS` | presente |
| `style.css`, `app.js`, `data.json` | `200` |
| `content-security-policy` na raiz | contém `frame-ancestors https://www.notion.so https://notion.so` |
| `GET /api/dashboard` | `503` + `{"erro":"Dados temporariamente indisponíveis."}` |
| `POST /api/dashboard` | `405` com `Allow: GET` |

O `503` no endpoint é o **estado esperado hoje**: sem `NOTION_TOKEN` a função
recusa antes de ler qualquer fonte, e a página cai no snapshot fictício. A
mensagem é genérica, sem id de base nem erro cru do Notion.

### Verificação em navegador de verdade (Chromium/Playwright)

Contra a URL pública, com a CSP de produção valendo:

- Selo presente no desktop e no celular (iPhone 13).
- Cabeçalho mostra `Modo offline · snapshot`, confirmando o modo snapshot.
- **Barras com tamanhos diferentes entre si**, que era a regressão de CSP a
  vigiar. Larguras renderizadas, em px:
  - Despesas por categoria: `105.7` e `319.9`
  - Evolução mensal: `13`, `13` e `319.9` (os dois `13` são os dois meses de
    −R$ 32,00, corretamente iguais entre si)
- **Zero violações de CSP** no console.
- Cartões: Receitas R$ 1.000,00 · Despesas R$ 264,00 · Saldo R$ 736,00 ·
  Orçamento R$ 1.500,00. Tabela com 4 lançamentos, todos rotulados `DEMO —` e
  datados em 2035.
- Numa página servida na origem real `https://www.notion.so`, o iframe do
  dashboard **carrega**, com selo e barras corretas dentro do frame.
- Numa origem não autorizada, o mesmo iframe **não carrega**. O
  `frame-ancestors` está fazendo o trabalho nos dois sentidos.

Screenshots: `vercel-dashboard-desktop.png`, `vercel-dashboard-mobile.png`,
`vercel-embed-notion.png`.

### Embed no Celeiro › Finanças

Feito por `scripts/embutir_dashboard_notion.py`, não na mão.

- Backup da página gravado antes de qualquer alteração, em
  `backups/notion-financas-20260830-231724.json` (fora do versionamento:
  `backups/` é ignorado pelo git).
- Embed inserido logo abaixo do título; toggle de fallback
  "Abrir as bases direto no Notion" criado logo abaixo dele.
- Lista seca antiga **arquivada**, não apagada — recuperável na lixeira do
  Notion, e os mesmos links continuam na página dentro do toggle.
- Conferência automática relendo a página: OK. Ordem final
  `heading_2 › embed › toggle › paragraph › child_database × 3 › callout`,
  **3 bases DEMO preservadas**, ícone da página inalterado.
- Rodado de novo em modo `--conferir`: mesmo resultado, sem alteração.
- Nenhuma imagem, capa ou ícone tocado.

## Não provado

- **Screenshot do embed dentro do Notion logado.** O
  `vercel-embed-notion.png` é o dashboard num iframe servido na origem real
  `https://www.notion.so`, o que prova que a CSP permite o embed — mas não é uma
  foto da página do Notion da Bruna, porque isso exigiria a sessão autenticada
  dela num navegador daqui. O que está provado por API é a estrutura de blocos
  da página, acima.
- **Leitura ao vivo das bases DEMO.** Continua desligada de propósito: a
  integração Notion somente-leitura ainda não existe. O token do Notion da VPS
  **não** foi usado no projeto público, como mandado. O painel serve o snapshot
  fictício de `dashboard/data.json`.

## Depende da Bruna

1. **Integração Notion somente-leitura**, para ligar a leitura ao vivo. Passo a
   passo em `docs/deploy-vercel-demo.md`, seção "Ligar a leitura ao vivo",
   junto com os comandos exatos do lado de cá. Nada disso bloqueia o vídeo.
2. **Deploy automático no push**, se quiser. O projeto não está conectado ao
   GitHub porque conectar exige ela autorizar o app da Vercel. Hoje o deploy é
   manual. Também não bloqueia o vídeo.
