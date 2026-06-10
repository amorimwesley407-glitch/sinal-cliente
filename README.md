# Monitoramento Preventivo IXC Soft

Aplicação Flask em Python para coletar sinais de fibra pela API IXC Soft, classificar a qualidade da conexão, detectar instabilidade por histórico de 24 horas e exibir dashboard com exportação CSV/Excel.

## Instalação

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Edite o arquivo `.env`:

```env
IXC_BASE_URL=https://seu-dominio.com.br/webservice/v1
IXC_TOKEN=seu_token_ixc
DATABASE_PATH=sinal_clientes.db
FLASK_SECRET_KEY=uma-chave-segura
```

## Uso

Executar uma coleta:

```bash
python app.py --coletar
```

Abrir o dashboard:

```bash
python app.py
```

Acesse `http://localhost:5000/dashboard`.

## Coleta Automática

Ao subir `python app.py`, a aplicação pode executar coletas automáticas em segundo plano para manter o dashboard atualizado sem rodar `--coletar` manualmente.

Variáveis disponíveis no `.env`:

```env
AUTO_COLETA_ENABLED=1
AUTO_COLETA_INTERVALO_SEGUNDOS=900
AUTO_COLETA_STARTUP=1
```

- `AUTO_COLETA_ENABLED=1`: liga a coleta automática
- `AUTO_COLETA_INTERVALO_SEGUNDOS=900`: executa uma nova coleta a cada 15 minutos
- `AUTO_COLETA_STARTUP=1`: faz uma coleta logo ao iniciar a aplicação

## Rotas

- `/dashboard`
- `/clientes-criticos`
- `/clientes-atencao`
- `/clientes-bons`
- `/clientes-excelentes`
- `/exportar/csv`
- `/exportar/xlsx`

## Agendamento

Se preferir manter a coleta fora da aplicação web, ainda é possível usar `python app.py --coletar` no Agendador de Tarefas do Windows ou cron.

## Classificação

- EXCELENTE: RX entre -17 e -22 dBm
- BOM: RX entre -22 e -26 dBm
- ATENÇÃO: RX entre -26 e -28 dBm
- CRÍTICO: RX menor que -28 dBm

TX normal fica entre 0 e 5 dBm. TX fora do padrão, ONU offline e oscilação de RX reduzem o score.
