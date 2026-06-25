from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import Flask

from api_ixc import IXCClient
from classificador import classificar_rx, detectar_instabilidade, score_conexao
from coleta_status import configure, mark_failure, mark_started, mark_success, set_next_run
from dashboard import dashboard_bp
from database import (
    init_db,
    listar_ultima_coleta,
    resumo_ultima_coleta,
    salvar_coleta,
    salvar_consumo_banda_cache,
    ultimos_rx_24h,
)


load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler("monitoramento.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)
_AUTO_COLETA_LOCK = threading.Lock()
_AUTO_COLETA_STOP = threading.Event()
_AUTO_COLETA_THREAD: threading.Thread | None = None


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev")
    init_db()
    configure(
        enabled=coleta_automatica_habilitada(),
        interval_seconds=intervalo_coleta_automatica(),
        startup_enabled=coleta_automatica_inicio_habilitada(),
    )
    app.register_blueprint(dashboard_bp)
    iniciar_coleta_automatica()
    return app


def coleta_automatica_habilitada() -> bool:
    return os.getenv("AUTO_COLETA_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}


def intervalo_coleta_automatica() -> int:
    valor = os.getenv("AUTO_COLETA_INTERVALO_SEGUNDOS", "300").strip()
    try:
        return max(60, int(valor))
    except ValueError:
        logger.warning("AUTO_COLETA_INTERVALO_SEGUNDOS inválido: %s. Usando 300 segundos.", valor)
        return 300


def coleta_automatica_inicio_habilitada() -> bool:
    return os.getenv("AUTO_COLETA_STARTUP", "1").strip().lower() not in {"0", "false", "no", "off"}


def executar_coleta_segura(origem: str) -> None:
    if not _AUTO_COLETA_LOCK.acquire(blocking=False):
        logger.info("Coleta automática ignorada (%s): já existe uma coleta em andamento.", origem)
        return
    try:
        logger.info("Iniciando coleta automática (%s).", origem)
        mark_started(origem)
        registros = executar_coleta()
        alertas = gerar_alertas(registros)
        mark_success(len(registros))
        for alerta in alertas:
            logger.warning(alerta)
    except Exception as exc:
        mark_failure(str(exc))
        logger.exception("Falha durante a coleta automática (%s).", origem)
    finally:
        _AUTO_COLETA_LOCK.release()


def ultima_coleta_banco() -> datetime | None:
    resumo = resumo_ultima_coleta()
    valor = str(resumo.get("ultima_data_hora") or "").strip()
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor)
    except ValueError:
        for formato in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
            try:
                return datetime.strptime(valor, formato)
            except ValueError:
                continue
    return None


def proxima_execucao_planejada(intervalo: int) -> datetime:
    ultima = ultima_coleta_banco()
    agora = datetime.now()
    if not ultima:
        return agora
    proxima = ultima + timedelta(seconds=intervalo)
    return proxima if proxima > agora else agora


def loop_coleta_automatica() -> None:
    intervalo = intervalo_coleta_automatica()
    executar_inicio = coleta_automatica_inicio_habilitada()
    logger.info("Coleta automática habilitada. Intervalo configurado: %s segundos.", intervalo)

    proxima_execucao = proxima_execucao_planejada(intervalo)
    if executar_inicio and proxima_execucao <= datetime.now():
        executar_coleta_segura("startup")
        proxima_execucao = datetime.now() + timedelta(seconds=intervalo)
    elif executar_inicio:
        logger.info(
            "Coleta automática de startup adiada. Próxima execução em %s.",
            proxima_execucao.strftime("%d/%m/%Y %H:%M:%S"),
        )

    set_next_run(proxima_execucao)
    while True:
        espera = max(1, int((proxima_execucao - datetime.now()).total_seconds()))
        if _AUTO_COLETA_STOP.wait(espera):
            break
        executar_coleta_segura("agendada")
        proxima_execucao = datetime.now() + timedelta(seconds=intervalo)
        set_next_run(proxima_execucao)


def iniciar_coleta_automatica() -> None:
    global _AUTO_COLETA_THREAD

    if not coleta_automatica_habilitada():
        logger.info("Coleta automática desabilitada por configuração.")
        configure(enabled=False, interval_seconds=intervalo_coleta_automatica(), startup_enabled=coleta_automatica_inicio_habilitada())
        return

    # Evita duplicar a thread quando o recarregador do Flask inicia o processo "pai".
    if os.getenv("FLASK_DEBUG") == "1" and os.getenv("WERKZEUG_RUN_MAIN") != "true":
        return

    if _AUTO_COLETA_THREAD and _AUTO_COLETA_THREAD.is_alive():
        return

    _AUTO_COLETA_STOP.clear()
    _AUTO_COLETA_THREAD = threading.Thread(
        target=loop_coleta_automatica,
        name="auto-coleta-ixc",
        daemon=True,
    )
    _AUTO_COLETA_THREAD.start()


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
    atualizar_cache_consumo_banda(client, processados)
    return processados


def atualizar_cache_consumo_banda(client: IXCClient, clientes: list[dict]) -> None:
    if not clientes:
        return
    periodo_dias = int(os.getenv("IXC_CONSUMO_PERIODO_DIAS", "30"))
    limite = int(os.getenv("IXC_CONSUMO_RANK_LIMITE", "50"))
    try:
        ranking = client.buscar_top_consumo_banda(clientes, dias=periodo_dias, limite=limite)
        salvar_consumo_banda_cache(ranking, periodo_dias)
        logger.info(
            "Cache de consumo atualizado: %s download / %s upload.",
            len(ranking.get("download", [])),
            len(ranking.get("upload", [])),
        )
    except Exception:
        logger.exception("Falha ao atualizar cache de consumo de banda.")


def atualizar_consumo_por_radacct() -> dict[str, list[dict]]:
    init_db()
    client = IXCClient()
    clientes = [dict(row) for row in listar_ultima_coleta()]
    periodo_dias = int(os.getenv("IXC_CONSUMO_PERIODO_DIAS", "30"))
    limite = int(os.getenv("IXC_CONSUMO_RANK_LIMITE", "50"))
    ranking = client.buscar_top_consumo_banda(clientes, dias=periodo_dias, limite=limite)
    salvar_consumo_banda_cache(ranking, periodo_dias)
    logger.info(
        "Cache de consumo acumulado atualizado: %s download / %s upload.",
        len(ranking.get("download", [])),
        len(ranking.get("upload", [])),
    )
    return ranking


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
    parser.add_argument("--atualizar-consumo", action="store_true", help="Atualiza apenas o cache de consumo acumulado")
    parser.add_argument("--host", default="0.0.0.0", help="Host do servidor Flask")
    parser.add_argument("--port", default=5000, type=int, help="Porta do servidor Flask")
    args = parser.parse_args()

    if args.coletar:
        alertas = gerar_alertas(executar_coleta())
        for alerta in alertas:
            logger.warning(alerta)
    elif args.atualizar_consumo:
        atualizar_consumo_por_radacct()
    else:
        create_app().run(host=args.host, port=args.port, debug=True)
