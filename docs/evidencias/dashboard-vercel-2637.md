# Porte do dashboard DEMO para a Vercel, tarefa 2637, 30/08/2026

## Provado

- Tarefa 2635 fechada: suíte completa verde (275 testes) e
  `scripts/varredura_seguranca.sh` limpo antes do commit `e7ce5d7`, empurrado
  para `origin/main` sem `--force`.
- `api/dashboard.py` lê as três bases DEMO reais pelo próprio caminho de código
  (urllib, sem passar por `sop.dashboard_server`): 5 lançamentos, R$ 278,00 em
  despesas, 2 custos fixos, 2 orçamentos. Bate exatamente com o estado B da
  prova A/B registrada em `dashboard-dinamico-2635.md`.
- Payload serializado com 1019 bytes, sem nenhum id de página.
- `tests/test_api_dashboard.py`, 20 casos: filtro DEMO (inclusive checkbox
  ausente, nulo e string), paridade de saída com `sop.dashboard_server.carregar`
  na mesma fixture, recusa sem `SABIA_DEMO=1`, sem token e com fonte faltando,
  cabeçalhos de segurança, 304 por ETag, 503 sem vazar detalhe do Notion e 405
  em todo método de escrita.
- Suíte completa após o porte: 295 testes verdes.

## Não provado, porque o deploy não aconteceu

Não existe credencial Vercel nesta VPS. `VERCEL_TOKEN` e `VERCEL_SCOPE` estão
definidos e **vazios** no ambiente e nos dois arquivos `.env` da operação; a CLI
não está instalada; não há `auth.json` de login; a API devolve
`403 forbidden / missing authentication token`. O conector MCP da Vercel exige
OAuth interativo, indisponível nesta sessão.

Consequência, sem rodeio: **estas etapas não foram feitas nem simuladas.**

- Deploy do projeto DEMO na Vercel.
- Confirmação por HTTP real da URL pública, do selo permanente e do
  `frame-ancestors` na resposta pública.
- Embed no Celeiro/Finanças do Notion. O Notion **não foi tocado**: sem URL
  pública não há o que incorporar, e trocar a lista por um embed quebrado seria
  pior que deixar como está. Nenhum backup foi feito porque nada foi alterado.
- Prova final nota sintética → URL pública refletindo o novo total.
- Screenshots do dashboard público (desktop e celular) e do embed carregando
  dentro do Notion.

Os screenshots existentes, `dashboard-demo-desktop.png` e
`dashboard-demo-mobile.png`, são da renderização local de 30/08 e continuam
válidos como prova visual do layout. Não são prova de deploy público.

O passo a passo do que destrava está em `docs/deploy-vercel-demo.md`, incluindo
o alerta para criar uma integração Notion separada, somente leitura e conectada
só às três bases DEMO, em vez de reaproveitar o token da VPS, que enxerga as
bases pessoais reais.
