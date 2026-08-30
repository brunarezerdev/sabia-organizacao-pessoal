# Dashboard financeiro DEMO, tarefa 2628

Matriz de paridade: resumo de receitas/despesas/saldo/orçamento, filtros por mês/tipo/categoria/status, barras por categoria, evolução mensal e tabelas de lançamentos/custos/orçamento estão implementados. Parcelas, veículos, eventos e categorias pessoais do painel VPS ficaram fora porque dependem de dados reais específicos.

O gerador `scripts/gerar_dashboard_demo.py` lê exclusivamente as três bases configuradas e recusa qualquer linha sem `Dados de demonstração=true`. O navegador recebe somente `dashboard/data.json`, nunca o token do Notion. Escrita ficou deliberadamente fora do embed: sem autenticação web já autorizada, CRUD público seria inseguro; a administração continua pelos links das próprias bases no Notion.

Prova local: `http://127.0.0.1:8765/`, screenshots `dashboard-demo-desktop.png` (1400×1000) e `dashboard-demo-mobile.png` (390×844). A interface é responsiva e tecnicamente embeddable, mas localhost não carrega no Notion. Não foi criado domínio/túnel público sem autorização, portanto o embed no Celeiro não foi instalado e a tarefa permanece parcialmente bloqueada nessa etapa externa.

Validação: suíte completa e varredura de segurança passaram. Zero dados reais foram lidos pelo gerador ou copiados para o dashboard; os exemplos são os registros fictícios das bases DEMO.
