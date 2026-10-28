# Scenario generation workflow / Guia do gerador de cenários

This contribution adds batch generation, selective randomization, readable feed
reports, read-only preflight validation and comparison of completed RuFaS runs.
The original `RUFAS/scenarios_generator.py` remains available unchanged.
The workflow calls its existing sampling functions and restores unselected groups
from the base farm, preserving the original draws for a given seed.

## Instalação

Use Python 3.12 ou 3.13. Na raiz do repositório:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

As features usam a biblioteca padrão do Python; a simulação usa as dependências
do RuFaS. Os exemplos abaixo usam PowerShell. Em Linux/macOS, use
`.venv/bin/python` no lugar de `.\.venv\Scripts\python.exe`.
Também é possível executar `python -m RUFAS.scenario_workflow`.

## 1. Gerar um ou vários cenários

```powershell
# Sementes 200 a 209, em uma pasta própria
.\.venv\Scripts\python.exe executar_cenario.py --seed 200 --quantidade 10 --saida scenarios/lote01

# Dois cenários limitados a 30 dias para experimentar a integração
.\.venv\Scripts\python.exe executar_cenario.py --seed 300 --quantidade 2 --dias 30 --saida scenarios/lote02
```

Cada cenário recebe JSONs compatíveis com RuFaS, `scenario.json`, `resumo.md` e
`validation.json`. O lote recebe `batch_*.csv` e `batch_*.json`, com sementes,
valores finais, grupos sorteados e resultado da validação.

Um cenário sem `--dias` usa o período original do exemplo, de 2013 a 2019.
O gerador se recusa a sobrescrever pastas existentes; escolha outra semente ou
outra `--saida`. Nenhum cenário novo é escrito se houver colisão com uma pasta
do lote. Destinos de entrada devem ficar dentro de `scenarios/`.

## 2. Escolher o que será sorteado

```powershell
# Só a alimentação varia; o restante vem da fazenda base
.\.venv\Scripts\python.exe executar_cenario.py --seed 400 --quantidade 5 --variar alimentacao --saida scenarios/dietas

# Variar dois grupos
.\.venv\Scripts\python.exe executar_cenario.py --seed 500 --variar alimentacao ordenhas --saida scenarios/experimento

# Controle: preservar todos os valores da fazenda base
.\.venv\Scripts\python.exe executar_cenario.py --seed 600 --variar nenhum --saida scenarios/controle
```

| Grupo | Campos que podem mudar |
|---|---|
| `rebanho` | Distribuição de paridade e fração de vacas em lactação |
| `genetica` | Ativação da simulação de genética |
| `ordenhas` | Frequência diária de ordenha |
| `localizacao` | Código FIPS; clima e demais arquivos regionais não são trocados |
| `alimentacao` | Ração de vacas em lactação e cadastro dos ingredientes necessários |
| `tolerancia` | Tolerância usada na formulação da ração |
| `todos` | Todos os grupos; padrão |
| `nenhum` | Preserva a configuração base |

`todos` e `nenhum` devem ser usados sozinhos. O tamanho do rebanho e outros campos
que o gerador original não sorteia permanecem iguais. Uma semente não garante
que todas as características sejam diferentes de outro cenário; opções discretas
podem repetir. Reproduzir o sorteio pressupõe o mesmo código e arquivos base.

## 3. Ler o cenário

Abra `resumo.md` no VS Code e pressione `Ctrl+Shift+V` para visualizar o relatório.
Ele contém manejo, distribuição de partos e as rações com IDs, nomes da biblioteca
NASEM e porcentagens de matéria seca. Os nomes da biblioteca permanecem em inglês.
O CSV do lote facilita a comparação das entradas; ele não contém resultados de simulação.

## 4. Validar antes de executar

```powershell
.\.venv\Scripts\python.exe executar_cenario.py --validar scenarios/lote02/seed300/teste_30_dias
```

A validação é automática na geração e antes de cada execução. Verifica arquivos
referenciados, datas inicial/final, cobertura de cada data na série climática,
frações do rebanho, tolerância e composição das rações (soma, valores finitos,
ingredientes duplicados, disponíveis e existentes na biblioteca).

O relatório separa erros e avisos. Erros bloqueiam a simulação. Os arquivos de um
cenário inválido ficam disponíveis para diagnóstico em `validation.json`.
Essa etapa não certifica adequação nutricional; o InputManager do RuFaS continua
aplicando suas validações completas na execução.

Períodos inferiores a um ano produzem um aviso sobre o ajuste climático sazonal.
Este comando exige pelo menos 30 dias para simular, pois um teste de três dias
produziu um ajuste instável. Trinta dias não são uma garantia de estabilidade nem
uma recomendação de duração para estudos científicos.

## 5. Simular e comparar

```powershell
# Gerar, validar, executar dois cenários e comparar automaticamente
.\.venv\Scripts\python.exe executar_cenario.py --seed 700 --quantidade 2 --variar alimentacao --dias 30 --simular --saida scenarios/lote03

# Executar novamente um cenário existente, sem regenerar suas entradas
.\.venv\Scripts\python.exe executar_cenario.py --executar scenarios/lote02/seed300/teste_30_dias
```

Há duas sementes distintas: `--seed` controla a geração do cenário;
`--seed-simulacao` controla a aleatoriedade interna do RuFaS (padrão 42).
O mesmo valor de simulação é usado para os cenários do lote. Use valores de
1 a 4294967295; zero é recusado, pois o RuFaS interpreta zero como uma semente aleatória.

Cada execução recebe uma pasta exclusiva em
`output/scenarios/<lote>/seedN/teste_D_dias/<identificador>/`, contendo:

- `inputs/`: cópia dos três JSONs gerados e metadados usados na execução;
- `tasks.json` e `task_manager_metadata.json`: tarefa e caminhos da execução;
- `console.log` e `logs/`: diagnósticos, incluindo avisos do RuFaS;
- `CSVs/`: série diária de produção de leite e metano entérico;
- `run.json`: estado `running`, `completed` ou `failed`, sementes, datas, hashes
  dos JSONs copiados e métricas quando a execução foi concluída.

Os demais arquivos da fazenda continuam referenciando `input/`; guarde a versão
do repositório para reproduzir o experimento. A execução é sequencial e para
na primeira falha. Os cenários e resultados já produzidos são preservados.
Só há comparação automática se todas as execuções do lote forem concluídas.

Para comparar execuções existentes, copie os caminhos de `run.json` mostrados
ao final de cada simulação. Exemplo com caminhos ilustrativos:

```powershell
.\.venv\Scripts\python.exe executar_cenario.py --comparar output/caminho1/run.json output/caminho2/run.json --comparacao-saida output/minha_comparacao
```

A comparação cria `comparison.csv` e `comparison.md`. O destino deve ser novo.
As métricas são leite total (kg), leite médio diário (kg/dia), metano entérico
total (kg), metano entérico médio diário (kg/dia) e metano entérico por kg de leite.
A intensidade fica vazia quando a produção total de leite é zero.

O metano é somado entre os lotes de animais reportados e convertido de gramas
para quilogramas. **Não é a emissão total da fazenda nem CO₂ equivalente.**
São recusadas execuções que falharam, períodos/tipos de simulação diferentes,
colunas ausentes, valores inválidos e séries com dias ausentes ou duplicados.
Uma comparação descritiva não comprova causalidade nem significância estatística.

## Development and verification

```powershell
.\.venv\Scripts\python.exe -m pip install pytest pytest-mock black flake8 mypy
.\.venv\Scripts\python.exe -m pytest tests/test_scenario_workflow.py
```

Tests cover reproducibility, frozen groups, collision protection, preflight errors,
date coverage, aggregation and units, incomplete outputs and RuFaS failures hidden
behind a zero process exit code. No generated scenarios, installed runtimes or
simulation results belong in the contribution commit.
