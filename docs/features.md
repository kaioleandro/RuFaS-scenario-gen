# Funcionalidades adicionadas ao gerador

O gerador prepara arquivos de entrada para o RuFaS. Gerar um cenário não executa a simulação: os cenários ficam em `scenarios/`, enquanto os resultados das simulações ficam em `output/`.

Execute os comandos abaixo no terminal PowerShell do VSCode, na pasta principal do repositório, com o ambiente `.venv` instalado.

## 1. Geração em lote

Cria vários cenários com um único comando. A semente (`seed`) controla o sorteio; cada cenário usa a próxima semente da sequência.

```powershell
.\.venv\Scripts\python.exe executar_cenario.py --seed 800 --quantidade 10 --saida scenarios/lote800
```

Esse exemplo gera cenários com sementes de 800 a 809. Com o mesmo código e arquivos base, a mesma semente reproduz o sorteio. Use uma pasta de saída nova para evitar sobrescrever cenários existentes.

## 2. Escolha do que será sorteado

O argumento `--variar` seleciona os grupos que podem mudar. Os demais mantêm os valores da fazenda base.

```powershell
.\.venv\Scripts\python.exe executar_cenario.py --seed 900 --quantidade 2 --variar alimentacao --dias 30 --saida scenarios/dietas900
```

Nesse exemplo, apenas a alimentação é sorteada. As opções são `rebanho`, `genetica`, `ordenhas`, `localizacao`, `alimentacao` e `tolerancia`. É possível combinar grupos, como `--variar alimentacao ordenhas`. Use `todos` (padrão) ou `nenhum` isoladamente.

O grupo `rebanho` altera distribuição de paridade e fração em lactação, não o tamanho do rebanho. `localizacao` altera apenas o código FIPS, sem trocar os arquivos climáticos.

## 3. Resumo legível

Cada cenário recebe um arquivo `resumo.md` com informações de manejo e rações, incluindo nomes dos alimentos e porcentagens de matéria seca. Abra o arquivo no VSCode e pressione `Ctrl+Shift+V` para visualizar.

O lote também recebe arquivos CSV e JSON com as configurações geradas. Eles descrevem as entradas, não os resultados da simulação.

## 4. Verificação antes da simulação

A validação ocorre automaticamente ao gerar e antes de simular. Ela verifica arquivos referenciados, datas, cobertura climática, frações do rebanho e composição das rações. Erros bloqueiam a execução; o diagnóstico fica em `validation.json`.

Também é possível verificar um cenário existente:

```powershell
.\.venv\Scripts\python.exe executar_cenario.py --validar scenarios/dietas900/seed900/teste_30_dias
```

Essa verificação complementa as validações do RuFaS e não certifica a adequação nutricional da dieta.

## 5. Comparação de resultados

Adicione `--simular` para gerar, validar e simular os cenários. Se todas as execuções do lote terminarem com sucesso, a comparação é criada automaticamente.

```powershell
.\.venv\Scripts\python.exe executar_cenario.py --seed 1000 --quantidade 2 --variar alimentacao --dias 30 --simular --saida scenarios/comparacao1000
```

Os arquivos `comparison.csv` e `comparison.md`, em `output/comparisons/`, mostram produção total e média diária de leite, metano entérico total e médio diário e metano por kg de leite. O metano entérico não representa todas as emissões da fazenda.

Também é possível comparar execuções concluídas usando `--comparar` seguido dos caminhos dos arquivos `run.json`. Elas precisam ter o mesmo período e tipo de simulação.

## Observações rápidas

- `--seed` controla o sorteio do cenário; `--seed-simulacao` controla a aleatoriedade interna do RuFaS e tem padrão 42.
- Sem `--dias`, o cenário usa o período original de 2013 a 2019. Este comando exige pelo menos 30 dias para simular; esse mínimo não garante estabilidade nem define a duração adequada para pesquisa.
- Cada execução guarda resultados e registros em uma pasta exclusiva, preservando execuções anteriores.

Para instalação e detalhes dos comandos, consulte o [guia completo](scenario_workflow.md).
