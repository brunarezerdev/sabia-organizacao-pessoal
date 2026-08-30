# Demonstração: nota de mercado

Use somente a fixture sintética ou uma nota sem CPF/dados pessoais. Envie a foto/PDF ao
`@SabiaAquiBot`; o canal já autenticado coloca o anexo em `media/inbound` e a Sábia chama a
ferramenta MCP `nota_demo_processar`. A resposta deve mostrar o total, os itens que entraram na Despensa e
que correspondências exatas saíram da Lista de Compras. Reenvie a mesma nota para provar que
nada duplica. O fluxo exige `SABIA_DEMO=1`, os ids explícitos das fontes DEMO e não persiste
texto OCR, chave fiscal, CPF/CNPJ, cartão, endereço ou arquivo recebido.

QR/NFC-e é a primeira pista quando `zbarimg` estiver instalado. Nesta VPS ele não está; PDF
textual usa `pdftotext` e imagem usa o Tesseract local, sem serviço pago. PDF escaneado deve
ser enviado como imagem enquanto não houver conversor de páginas instalado.
