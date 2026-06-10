from __future__ import annotations

import io
import logging
import re
import unicodedata
from datetime import datetime

import pandas as pd
from flask import Blueprint, Response, render_template, request, send_file

from api_ixc import IXCClient
from coleta_status import snapshot as coleta_snapshot
from database import (
    listar_clientes_por_categoria,
    listar_bons_excelentes,
    listar_offline_24h,
    listar_offline_mais_de_um_dia,
    listar_ultima_coleta,
    obter_historico_cliente,
    resumo_ultima_coleta,
    serie_evolucao,
    estatisticas_dashboard,
    top_consumo_banda,
    top_criticos,
)


dashboard_bp = Blueprint("dashboard", __name__)
logger = logging.getLogger(__name__)
REGISTROS_POR_PAGINA = 50
DIAS_HISTORICO_CONEXAO = 30


@dashboard_bp.route("/")
@dashboard_bp.route("/dashboard")
def dashboard():
    stats = estatisticas_dashboard()
    clientes_base = listar_offline_24h(limite=None)
    clientes_filtrados = filtrar_clientes(clientes_base)
    clientes, paginacao = paginar_registros(clientes_filtrados)
    coleta_info = status_coleta_dashboard()
    return render_template(
        "dashboard.html",
        stats=stats,
        clientes=clientes,
        paginacao=paginacao,
        filtros=opcoes_filtros(clientes_base),
        pagination_args=argumentos_paginacao(),
        top_criticos=top_criticos(),
        top_consumo=top_consumo_banda(limite=20),
        historico_dias=DIAS_HISTORICO_CONEXAO,
        evolucao=serie_evolucao(),
        coleta_info=coleta_info,
    )


@dashboard_bp.app_template_filter("status_class")
def status_class(value) -> str:
    texto = unicodedata.normalize("NFKD", str(value or "").lower())
    texto = texto.encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"[^a-z0-9]+", "-", texto).strip("-")
    return texto or "sem-status"


def _cliente_online(value) -> bool:
    texto = str(value or "").strip().lower()
    return texto not in {"offline", "off-line", "down", "desconectada", "desconectado", "sem sinal"}


@dashboard_bp.app_template_filter("online_label")
def online_label(value) -> str:
    return "Sim" if _cliente_online(value) else "Não"


@dashboard_bp.app_template_filter("online_status")
def online_status(value) -> str:
    return "online" if _cliente_online(value) else "offline"


@dashboard_bp.app_template_filter("sinal_optico")
def sinal_optico(value) -> str:
    if value in (None, 0, 0.0):
        return "-"
    return f"{float(value):.2f}"


@dashboard_bp.route("/clientes-criticos")
def clientes_criticos():
    return renderizar_lista("Clientes Críticos", listar_clientes_por_categoria("CRITICO"))


@dashboard_bp.route("/clientes-atencao")
def clientes_atencao():
    return renderizar_lista("Clientes em Atenção", listar_clientes_por_categoria("ATENCAO"))


@dashboard_bp.route("/clientes-bons-excelentes")
def clientes_bons_excelentes():
    return renderizar_lista("Clientes Bons e Excelentes", listar_bons_excelentes())


@dashboard_bp.route("/clientes-bons")
def clientes_bons():
    return renderizar_lista("Clientes Bons", listar_clientes_por_categoria("BOM"))


@dashboard_bp.route("/clientes-excelentes")
def clientes_excelentes():
    return renderizar_lista("Clientes Excelentes", listar_clientes_por_categoria("EXCELENTE"))


@dashboard_bp.route("/offiline")
def offiline():
    return renderizar_lista("Offiline", listar_offline_mais_de_um_dia(), mostrar_ultima_queda=True)


@dashboard_bp.route("/cliente/<cliente_id>")
def detalhe_cliente(cliente_id: str):
    login = request.args.get("login", "").strip()
    coletas = obter_historico_cliente(cliente_id, limite=None, dias=7, login=login)
    cliente_atual = dict(coletas[0]) if coletas else None
    historico_conexao = []
    ultimas_os = []
    sinal_grafico = dados_grafico_sinal(coletas)
    if cliente_atual:
        try:
            client = IXCClient()
        except Exception:
            logger.exception("Falha ao iniciar cliente IXC para %s", cliente_id)
        else:
            if cliente_atual["login"]:
                try:
                    historico_conexao = client.buscar_historico_conexao(
                        cliente_atual["login"], dias=DIAS_HISTORICO_CONEXAO
                    )
                except Exception:
                    logger.exception("Falha ao buscar historico Radacct do cliente %s", cliente_id)
            try:
                ultimas_os = client.buscar_ultimas_os_cliente(cliente_atual["cliente_id"], limite=10)
            except Exception:
                logger.exception("Falha ao buscar ultimas OSs do cliente %s", cliente_id)
            try:
                historico_potenciacao = buscar_historico_potenciacao_ixc(client, cliente_atual)
                if historico_potenciacao:
                    sinal_grafico = dados_grafico_potenciacao(historico_potenciacao)
            except Exception:
                logger.exception("Falha ao buscar historico de potenciacao do cliente %s", cliente_id)
            try:
                if cliente_com_bloqueio(cliente_atual) and not cliente_atual.get("data_bloqueio"):
                    cliente_atual.update(
                        client.buscar_dados_bloqueio(cliente_atual["cliente_id"], cliente_atual["status_acesso"])
                    )
            except Exception:
                logger.exception("Falha ao buscar dados de bloqueio do cliente %s", cliente_id)
    return render_template(
        "cliente.html",
        historico=historico_conexao,
        coletas=coletas,
        sinal_grafico=sinal_grafico,
        historico_dias=DIAS_HISTORICO_CONEXAO,
        cliente=cliente_atual,
        cliente_id=cliente_id,
        ultimas_os=ultimas_os,
    )


@dashboard_bp.route("/exportar/<formato>")
def exportar(formato: str):
    rows = [dict(row) for row in listar_ultima_coleta()]
    df = pd.DataFrame(rows)
    if formato == "csv":
        csv_data = df.to_csv(index=False, sep=";")
        return Response(
            csv_data,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=clientes_sinal.csv"},
        )
    if formato in {"xlsx", "excel"}:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Clientes")
        output.seek(0)
        return send_file(
            output,
            as_attachment=True,
            download_name="clientes_sinal.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    return "Formato inválido", 400


@dashboard_bp.route("/api/cliente/<cliente_id>/historico")
def api_historico_cliente(cliente_id: str):
    rows = obter_historico_cliente(cliente_id, int(request.args.get("limite", 500)), dias=7)[::-1]
    return {
        "labels": [row["data_hora"] for row in rows],
        "rx": [row["rx"] for row in rows],
        "tx": [row["tx"] for row in rows],
    }


def filtrar_clientes(clientes):
    termo = request.args.get("q", "").strip().lower()
    online = request.args.get("online", "").strip().lower()
    contrato = request.args.get("contrato", "").strip()
    acesso = request.args.get("acesso", "").strip()
    motivo = request.args.get("motivo", "").strip()
    queda_inicio = data_filtro("queda_inicio")
    queda_fim = data_filtro("queda_fim", fim_do_dia=True)
    coleta_inicio = data_filtro("coleta_inicio")
    coleta_fim = data_filtro("coleta_fim", fim_do_dia=True)
    if not any((termo, online, contrato, acesso, motivo, queda_inicio, queda_fim, coleta_inicio, coleta_fim)):
        return clientes
    return [
        cliente
        for cliente in clientes
        if (
            not termo
            or termo in texto_campo(cliente, "nome").lower()
            or termo in texto_campo(cliente, "login").lower()
            or termo in texto_campo(cliente, "contato").lower()
        )
        and (not online or online_status(valor_campo(cliente, "status_onu")) == online)
        and (not contrato or texto_campo(cliente, "status_contrato") == contrato)
        and (not acesso or texto_campo(cliente, "status_acesso") == acesso)
        and (not motivo or motivo_cliente(cliente) == motivo)
        and data_no_intervalo(valor_campo(cliente, "ultima_desconexao"), queda_inicio, queda_fim)
        and data_no_intervalo(valor_campo(cliente, "data_hora"), coleta_inicio, coleta_fim)
    ]


def renderizar_lista(titulo: str, clientes, mostrar_ultima_queda: bool = False):
    clientes_base = list(clientes)
    clientes_filtrados = filtrar_clientes(clientes_base)
    clientes_pagina, paginacao = paginar_registros(clientes_filtrados)
    return render_template(
        "lista.html",
        titulo=titulo,
        clientes=clientes_pagina,
        paginacao=paginacao,
        filtros=opcoes_filtros(clientes_base),
        pagination_args=argumentos_paginacao(),
        mostrar_ultima_queda=mostrar_ultima_queda,
    )


def opcoes_filtros(clientes) -> dict[str, list[dict[str, str]]]:
    opcoes = {
        "online": {},
        "contrato": {},
        "acesso": {},
        "motivo": {},
    }
    for cliente in clientes:
        online_value = online_status(valor_campo(cliente, "status_onu"))
        opcoes["online"][online_value] = "Online" if online_value == "online" else "Offline"
        adicionar_opcao(opcoes["contrato"], texto_campo(cliente, "status_contrato"))
        adicionar_opcao(opcoes["acesso"], texto_campo(cliente, "status_acesso"))
        adicionar_opcao(opcoes["motivo"], motivo_cliente(cliente))
    return {chave: ordenar_opcoes(valores) for chave, valores in opcoes.items()}


def adicionar_opcao(opcoes: dict[str, str], valor: str) -> None:
    valor = valor.strip()
    if valor:
        opcoes[valor] = valor


def ordenar_opcoes(opcoes: dict[str, str]) -> list[dict[str, str]]:
    return [
        {"value": value, "label": label}
        for value, label in sorted(opcoes.items(), key=lambda item: item[1].lower())
    ]


def argumentos_paginacao() -> dict[str, str]:
    args = request.args.to_dict()
    args.pop("page", None)
    return {chave: valor for chave, valor in args.items() if valor}


def motivo_cliente(cliente) -> str:
    return texto_campo(cliente, "motivo_desconexao") or texto_campo(cliente, "causa_ultima_queda")


def data_filtro(nome: str, fim_do_dia: bool = False) -> datetime | None:
    valor = request.args.get(nome, "").strip()
    if not valor:
        return None
    try:
        data = datetime.strptime(valor, "%Y-%m-%d")
    except ValueError:
        return None
    if fim_do_dia:
        return data.replace(hour=23, minute=59, second=59, microsecond=999999)
    return data


def data_no_intervalo(valor, inicio: datetime | None, fim: datetime | None) -> bool:
    if not inicio and not fim:
        return True
    data = parse_data_coleta(str(valor or ""))
    if not data:
        return False
    return (not inicio or data >= inicio) and (not fim or data <= fim)


def texto_campo(cliente, chave: str) -> str:
    valor = valor_campo(cliente, chave)
    return str(valor or "").strip()


def valor_campo(cliente, chave: str):
    try:
        return cliente[chave]
    except (KeyError, IndexError):
        return ""


def cliente_com_bloqueio(cliente: dict) -> bool:
    return str(cliente.get("status_acesso") or "").strip().upper() in {
        "BLOQUEIO AUTOMÁTICO",
        "BLOQUEIO MANUAL",
    }


def paginar_registros(registros):
    total = len(registros)
    total_paginas = max(1, (total + REGISTROS_POR_PAGINA - 1) // REGISTROS_POR_PAGINA)
    pagina = pagina_atual(total_paginas)
    inicio = (pagina - 1) * REGISTROS_POR_PAGINA
    fim = inicio + REGISTROS_POR_PAGINA
    return registros[inicio:fim], {
        "pagina": pagina,
        "por_pagina": REGISTROS_POR_PAGINA,
        "total": total,
        "total_paginas": total_paginas,
        "inicio": inicio + 1 if total else 0,
        "fim": min(fim, total),
    }


def pagina_atual(total_paginas: int) -> int:
    try:
        pagina = int(request.args.get("page", "1"))
    except ValueError:
        pagina = 1
    return min(max(pagina, 1), total_paginas)


def dados_grafico_sinal(coletas, limite: int = 15) -> dict:
    ultimas = list(coletas[:limite])
    ultimas.reverse()
    return {
        "labels": [rotulo_data_grafico(row["data_hora"]) for row in ultimas],
        "rx": [valor_grafico(row["rx"]) for row in ultimas],
        "tx": [valor_grafico(row["tx"]) for row in ultimas],
        "fonte": "Coletas locais",
    }


def buscar_historico_potenciacao_ixc(client: IXCClient, cliente: dict) -> list[dict]:
    cliente_fibra = client.buscar_cliente_fibra(
        login=texto_campo(cliente, "login"),
        cliente_id=texto_campo(cliente, "cliente_id"),
    )
    id_cliente_fibra = str(cliente_fibra.get("id") or "") if cliente_fibra else ""
    if not id_cliente_fibra:
        return []
    return client.buscar_historico_potenciacao(id_cliente_fibra, limite=15)


def dados_grafico_potenciacao(historico: list[dict]) -> dict:
    registros = list(historico[:15])
    registros.reverse()
    return {
        "labels": [rotulo_data_grafico(row.get("data_sinal", "")) for row in registros],
        "rx": [valor_grafico(row.get("sinal_rx")) for row in registros],
        "tx": [valor_grafico(row.get("sinal_tx")) for row in registros],
        "fonte": "IXC Histórico de potenciação",
    }


def rotulo_data_grafico(valor: str) -> str:
    data = parse_data_coleta(valor)
    if not data:
        return str(valor or "-")
    return data.strftime("%d/%m %H:%M")


def valor_grafico(valor):
    if valor in (None, ""):
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def parse_data_coleta(valor: str) -> datetime | None:
    valor = str(valor or "").strip()
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor)
    except ValueError:
        pass
    for formato in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(valor, formato)
        except ValueError:
            continue
    return None


def status_coleta_dashboard() -> dict[str, str | int | None | bool]:
    estado = coleta_snapshot()
    resumo = resumo_ultima_coleta()
    agora = datetime.now()
    intervalo = int(estado.get("interval_seconds") or 0)
    ultima_sucesso = estado.get("last_success_at")
    proxima = estado.get("next_run_at")
    executando = bool(estado.get("running"))
    erro = str(estado.get("last_error") or "").strip()
    habilitada = bool(estado.get("enabled"))

    situacao = "desabilitada"
    situacao_texto = "Automação desabilitada"
    if executando:
        situacao = "executando"
        situacao_texto = "Coleta em andamento"
    elif erro:
        situacao = "erro"
        situacao_texto = "Última coleta falhou"
    elif not habilitada:
        situacao = "desabilitada"
        situacao_texto = "Automação desabilitada"
    elif proxima and proxima < agora:
        situacao = "atrasada"
        situacao_texto = "Coleta atrasada"
    else:
        situacao = "saudavel"
        situacao_texto = "Coleta automática saudável"

    return {
        "enabled": habilitada,
        "running": executando,
        "status": situacao,
        "status_text": situacao_texto,
        "interval_seconds": intervalo,
        "interval_text": formatar_intervalo(intervalo),
        "last_started_at": formatar_data_hora_relativa(estado.get("last_started_at")),
        "last_finished_at": formatar_data_hora_relativa(estado.get("last_finished_at")),
        "last_success_at": formatar_data_hora_relativa(ultima_sucesso),
        "next_run_at": formatar_data_hora_relativa(proxima),
        "last_error": erro,
        "last_result_count": estado.get("last_result_count"),
        "last_origin": estado.get("last_origin"),
        "db_last_data_hora": formatar_data_hora_relativa(parse_data_coleta(str(resumo.get("ultima_data_hora") or ""))),
        "db_total_clientes": resumo.get("total_clientes"),
    }


def formatar_data_hora_relativa(valor: datetime | None) -> str:
    if not valor:
        return "-"
    agora = datetime.now()
    diferenca = int((agora - valor).total_seconds())
    if diferenca < 0:
        diferenca = 0
    if diferenca < 60:
        relativo = "agora mesmo"
    elif diferenca < 3600:
        relativo = f"há {diferenca // 60} min"
    else:
        relativo = f"há {diferenca // 3600} h"
    return f"{valor.strftime('%d/%m/%Y %H:%M:%S')} ({relativo})"


def formatar_intervalo(segundos: int) -> str:
    if segundos <= 0:
        return "-"
    minutos, resto = divmod(segundos, 60)
    horas, minutos = divmod(minutos, 60)
    partes = []
    if horas:
        partes.append(f"{horas}h")
    if minutos:
        partes.append(f"{minutos}min")
    if resto and not horas:
        partes.append(f"{resto}s")
    return " ".join(partes) or f"{segundos}s"
