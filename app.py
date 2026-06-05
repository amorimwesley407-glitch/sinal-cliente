from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from flask import Flask

from api_ixc import IXCClient
from classificador import classificar_rx, detectar_instabilidade, score_conexao
from dashboard import dashboard_bp
from database import init_db, salvar_coleta, ultimos_rx_24h


load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler("monitoramento.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev")
    init_db()
    app.register_blueprint(dashboard_bp)
    return app


def executar_coleta() -> list[dict]:
    init_db()
    client = IXCClient()
    registros = client.coletar_sinais()
    processados = []

    for registro in registros:
        rx_historico = ultimos_rx_24h(registro["cliente_id"], registro.get("login", ""))
        if registro.get("rx") is not None:
            rx_historico.append(registro["rx"])
        instavel, oscilacao = detectar_instabilidade(rx_historico)
        categoria = classificar_rx(registro.get("rx"))
        score = score_conexao(registro.get("rx"), registro.get("tx"), registro.get("status_onu"), oscilacao)
        status = "INSTÁVEL" if instavel else categoria

        item = {
            **registro,
            "categoria": categoria,
            "score": score,
            "status": status,
            "instavel": instavel,
            "oscilacao_24h": oscilacao,
        }
        salvar_coleta(item)
        processados.append(item)

    logger.info("Coleta concluída: %s clientes processados.", len(processados))
    return processados


def gerar_alertas(registros: list[dict]) -> list[str]:
    alertas = []
    for item in registros:
        if item["categoria"] == "CRÍTICO":
            alertas.append(
                f"Cliente: {item['nome']} | Login: {item['login']} | RX: {item['rx']} | "
                f"TX: {item['tx']} | Status: CRÍTICO"
            )
        if item["instavel"]:
            alertas.append(
                f"Cliente: {item['nome']} | Login: {item['login']} | RX: {item['rx']} | "
                f"Oscilação: {item['oscilacao_24h']} dBm | Status: INSTÁVEL"
            )
    return alertas


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Monitoramento preventivo de clientes IXC Soft")
    parser.add_argument("--coletar", action="store_true", help="Executa uma coleta na API IXC e salva no SQLite")
    parser.add_argument("--host", default="0.0.0.0", help="Host do servidor Flask")
    parser.add_argument("--port", default=5000, type=int, help="Porta do servidor Flask")
    args = parser.parse_args()

    if args.coletar:
        alertas = gerar_alertas(executar_coleta())
        for alerta in alertas:
            logger.warning(alerta)
    else:
        create_app().run(host=args.host, port=args.port, debug=True)
