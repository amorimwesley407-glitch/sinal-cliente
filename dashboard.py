from __future__ import annotations

import io
import logging
import re
import unicodedata
from datetime import datetime

import pandas as pd
from flask import Blueprint, Response, render_template, request, send_file

from api_ixc import IXCClient
from database import (
    listar_bons_excelentes,
    listar_offline_24h,
    listar_ultima_coleta,
    obter_historico_cliente,
    serie_evolucao,
    estatisticas_dashboard,
    top_criticos,
)


dashboard_bp = Blueprint("dashboard", __name__)
logger = logging.getLogger(__name__)
REGISTROS_POR_PAGINA = 50


@dashboard_bp.route("/")
@dashboard_bp.route("/dashboard")
def dashboard():
    stats = estatisticas_dashboard()
    clientes, paginacao = paginar_registros(listar_offline_24h(limite=None))
    return render_template(
        "dashboard.html",
        stats=stats,
        clientes=clientes,
        paginacao=paginacao,
        top_criticos=top_criticos(),
        evolucao=serie_evolucao(),
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


@dashboard_bp.route("/clientes-criticos")
def clientes_criticos():
    return renderizar_lista("Clientes Críticos", listar_ultima_coleta("AND categoria = 'CRÍTICO'"))


@dashboard_bp.route("/clientes-atencao")
def clientes_atencao():
    return renderizar_lista("Clientes em Atenção", listar_ultima_coleta("AND categoria = 'ATENÇÃO'"))


@dashboard_bp.route("/clientes-bons-excelentes")
def clientes_bons_excelentes():
    return renderizar_lista("Clientes Bons e Excelentes", listar_bons_excelentes())


@dashboard_bp.route("/clientes-bons")
def clientes_bons():
    return renderizar_lista("Clientes Bons", listar_ultima_coleta("AND categoria = 'BOM'"))


@dashboard_bp.route("/clientes-excelentes")
def clientes_excelentes():
    return renderizar_lista("Clientes Excelentes", listar_ultima_coleta("AND categoria = 'EXCELENTE'"))


@dashboard_bp.route("/cliente/<cliente_id>")
def detalhe_cliente(cliente_id: str):
    coletas = obter_historico_cliente(cliente_id, limite=None, dias=7)
    cliente_atual = coletas[0] if coletas else None
    coletas_meta = resumo_coletas(coletas)
    historico_conexao = []
    if cliente_atual and cliente_atual["login"]:
        try:
            historico_conexao = IXCClient().buscar_historico_conexao(cliente_atual["login"], dias=7)
        except Exception:
            logger.exception("Falha ao buscar historico Radacct do cliente %s", cliente_id)
    return render_template(
        "cliente.html",
        historico=historico_conexao,
        coletas=coletas,
        coletas_meta=coletas_meta,
        cliente=cliente_atual,
        cliente_id=cliente_id,
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
    if not termo:
        return clientes
    return [
        cliente
        for cliente in clientes
        if termo in str(cliente["nome"]).lower()
        or termo in str(cliente["login"]).lower()
        or termo in str(cliente["contato"] or "").lower()
    ]


def renderizar_lista(titulo: str, clientes):
    clientes_filtrados = filtrar_clientes(clientes)
    clientes_pagina, paginacao = paginar_registros(clientes_filtrados)
    return render_template(
        "lista.html",
        titulo=titulo,
        clientes=clientes_pagina,
        paginacao=paginacao,
    )


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


def resumo_coletas(coletas) -> dict:
    datas = [parse_data_coleta(row["data_hora"]) for row in coletas if row["data_hora"]]
    datas = [data for data in datas if data]
    if not datas:
        return {"total": 0, "inicio": "", "fim": ""}
    return {
        "total": len(coletas),
        "inicio": min(datas).strftime("%d/%m/%Y %H:%M"),
        "fim": max(datas).strftime("%d/%m/%Y %H:%M"),
    }


def parse_data_coleta(valor: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(valor))
    except ValueError:
        return None
