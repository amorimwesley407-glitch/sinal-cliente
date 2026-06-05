from __future__ import annotations

import io

import pandas as pd
from flask import Blueprint, Response, render_template, request, send_file

from database import (
    listar_bons_excelentes,
    listar_ultima_coleta,
    obter_historico_cliente,
    serie_evolucao,
    estatisticas_dashboard,
    top_criticos,
)


dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@dashboard_bp.route("/dashboard")
def dashboard():
    stats = estatisticas_dashboard()
    clientes = listar_ultima_coleta()
    return render_template(
        "dashboard.html",
        stats=stats,
        clientes=clientes[:30],
        top_criticos=top_criticos(),
        evolucao=serie_evolucao(),
    )


@dashboard_bp.route("/clientes-criticos")
def clientes_criticos():
    return render_template("lista.html", titulo="Clientes Críticos", clientes=filtrar_clientes(listar_ultima_coleta("AND categoria = 'CRÍTICO'")))


@dashboard_bp.route("/clientes-atencao")
def clientes_atencao():
    return render_template("lista.html", titulo="Clientes em Atenção", clientes=filtrar_clientes(listar_ultima_coleta("AND categoria = 'ATENÇÃO'")))


@dashboard_bp.route("/clientes-bons-excelentes")
def clientes_bons_excelentes():
    return render_template("lista.html", titulo="Clientes Bons e Excelentes", clientes=filtrar_clientes(listar_bons_excelentes()))


@dashboard_bp.route("/clientes-bons")
def clientes_bons():
    return render_template("lista.html", titulo="Clientes Bons", clientes=filtrar_clientes(listar_ultima_coleta("AND categoria = 'BOM'")))


@dashboard_bp.route("/clientes-excelentes")
def clientes_excelentes():
    return render_template("lista.html", titulo="Clientes Excelentes", clientes=filtrar_clientes(listar_ultima_coleta("AND categoria = 'EXCELENTE'")))


@dashboard_bp.route("/cliente/<cliente_id>")
def detalhe_cliente(cliente_id: str):
    historico = obter_historico_cliente(cliente_id, 100)
    cliente_atual = historico[0] if historico else None
    return render_template(
        "cliente.html",
        historico=historico,
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
    rows = obter_historico_cliente(cliente_id, int(request.args.get("limite", 50)))[::-1]
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
