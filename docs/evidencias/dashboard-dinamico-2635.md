# Prova do dashboard dinâmico DEMO, 30/08/2026

- Estado A, confirmado na leitura anterior à fixture: 4 lançamentos e R$ 264,00 em despesas DEMO.
- Replay controlado pelo agente `main`: uma chamada a `nota-demo.nota_demo_processar`, zero falhas, nota sintética de R$ 14,00 registrada.
- Estado B pelo endpoint HTTP `/api/dashboard`: 5 lançamentos, R$ 278,00 em despesas e uma linha de 10/06/2035 no valor de R$ 14,00.
- Reentrega em nova sessão: uma chamada da tool, zero falhas, resposta “já foi processada”; nova leitura permaneceu em 5 lançamentos/R$ 278,00.
- Atualização: cache server-side de 15 s; navegador consulta ao abrir e a cada 20 s, além do botão “Atualizar agora”. Latência declarada: até 35 s no pior alinhamento natural, imediata após expirar o cache.
- Falha Notion: o frontend preserva o último estado válido e sinaliza indisponibilidade; se nunca carregou, usa `data.json` como snapshot offline identificado.
- Segurança: endpoint GET-only, bind local, CORS não liberado, CSP com `frame-ancestors` restrito ao Notion, token apenas no processo e linhas não DEMO omitidas.
- Screenshots visuais desktop/mobile permanecem em `docs/evidencias/dashboard-demo-*.png`; esta etapa foi provada por HTTP e sessões do OpenClaw, sem deploy público.
