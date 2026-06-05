from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta


DB_PATH = os.getenv("DATABASE_PATH", "sinal_clientes.db")


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS historico_sinal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id TEXT NOT NULL,
                nome TEXT NOT NULL,
                contato TEXT,
                login TEXT NOT NULL,
                rx REAL,
                tx REAL,
                score INTEGER NOT NULL,
                status TEXT NOT NULL,
                status_onu TEXT,
                categoria TEXT NOT NULL,
                instavel INTEGER NOT NULL DEFAULT 0,
                oscilacao_24h REAL NOT NULL DEFAULT 0,
                tempo_ligado TEXT,
                tempo_ligado_segundos INTEGER,
                pon TEXT,
                caixa TEXT,
                porta_caixa TEXT,
                ultima_desconexao TEXT,
                tempo_desconectado TEXT,
                motivo_desconexao TEXT,
                causa_ultima_queda TEXT,
                data_hora TEXT NOT NULL
            )
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(historico_sinal)").fetchall()}
        migrations = {
            "contato": "ALTER TABLE historico_sinal ADD COLUMN contato TEXT",
            "tempo_ligado": "ALTER TABLE historico_sinal ADD COLUMN tempo_ligado TEXT",
            "tempo_ligado_segundos": "ALTER TABLE historico_sinal ADD COLUMN tempo_ligado_segundos INTEGER",
            "pon": "ALTER TABLE historico_sinal ADD COLUMN pon TEXT",
            "caixa": "ALTER TABLE historico_sinal ADD COLUMN caixa TEXT",
            "porta_caixa": "ALTER TABLE historico_sinal ADD COLUMN porta_caixa TEXT",
            "ultima_desconexao": "ALTER TABLE historico_sinal ADD COLUMN ultima_desconexao TEXT",
            "tempo_desconectado": "ALTER TABLE historico_sinal ADD COLUMN tempo_desconectado TEXT",
            "motivo_desconexao": "ALTER TABLE historico_sinal ADD COLUMN motivo_desconexao TEXT",
            "causa_ultima_queda": "ALTER TABLE historico_sinal ADD COLUMN causa_ultima_queda TEXT",
        }
        for column, sql in migrations.items():
            if column not in columns:
                conn.execute(sql)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_hist_cliente_data ON historico_sinal(cliente_id, data_hora)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_hist_status ON historico_sinal(status)")


def salvar_coleta(registro: dict) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO historico_sinal (
                cliente_id, nome, contato, login, rx, tx, score, status, status_onu,
                categoria, instavel, oscilacao_24h, tempo_ligado, tempo_ligado_segundos,
                pon, caixa, porta_caixa, ultima_desconexao, tempo_desconectado,
                motivo_desconexao, causa_ultima_queda, data_hora
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                registro["cliente_id"],
                registro["nome"],
                registro.get("contato", ""),
                registro["login"],
                registro.get("rx"),
                registro.get("tx"),
                registro["score"],
                registro["status"],
                registro.get("status_onu"),
                registro["categoria"],
                int(registro.get("instavel", False)),
                registro.get("oscilacao_24h", 0),
                registro.get("tempo_ligado", ""),
                registro.get("tempo_ligado_segundos"),
                registro.get("pon", ""),
                registro.get("caixa", ""),
                registro.get("porta_caixa", ""),
                registro.get("ultima_desconexao", ""),
                registro.get("tempo_desconectado", ""),
                registro.get("motivo_desconexao", ""),
                registro.get("causa_ultima_queda", ""),
                registro["data_hora"],
            ),
        )


def ultimos_rx_24h(cliente_id: str, login: str = "", agora: datetime | None = None) -> list[float]:
    agora = agora or datetime.now()
    inicio = (agora - timedelta(hours=24)).isoformat(timespec="seconds")
    if login:
        filtro = "login = ?"
        valor = login
    else:
        filtro = "cliente_id = ?"
        valor = cliente_id
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT rx FROM historico_sinal
            WHERE {filtro} AND data_hora >= ? AND rx IS NOT NULL
            ORDER BY data_hora ASC
            """,
            (valor, inicio),
        ).fetchall()
    return [row["rx"] for row in rows]


def listar_ultima_coleta(where: str = "", params: tuple = ()) -> list[sqlite3.Row]:
    query = f"""
        WITH ultimos AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY COALESCE(NULLIF(login, ''), NULLIF(cliente_id, ''), nome)
                ORDER BY data_hora DESC, id DESC
            ) AS rn
            FROM historico_sinal
            WHERE cliente_id IS NOT NULL AND cliente_id != ''
        )
        SELECT * FROM ultimos WHERE rn = 1 {where}
        ORDER BY score ASC, rx ASC
    """
    with get_connection() as conn:
        return conn.execute(query, params).fetchall()


def obter_historico_cliente(cliente_id: str, limite: int = 50) -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT * FROM historico_sinal
            WHERE cliente_id = ?
            ORDER BY data_hora DESC
            LIMIT ?
            """,
            (cliente_id, limite),
        ).fetchall()


def estatisticas_dashboard() -> dict:
    ultimos = listar_ultima_coleta()
    categorias = {}
    for row in ultimos:
        categorias[row["categoria"]] = categorias.get(row["categoria"], 0) + 1
    categorias_upper = {str(k).upper(): v for k, v in categorias.items()}
    return {
        "total": len(ultimos),
        "criticos": categorias_upper.get("CRÍTICO", 0),
        "atencao": categorias_upper.get("ATENÇÃO", 0),
        "bons": categorias_upper.get("BOM", 0),
        "excelentes": categorias_upper.get("EXCELENTE", 0),
        "instaveis": sum(1 for r in ultimos if r["instavel"]),
        "categorias": categorias,
    }


def top_criticos(limite: int = 20) -> list[sqlite3.Row]:
    return listar_ultima_coleta("AND categoria = 'CRÍTICO'", ())[:limite]


def top_instaveis(limite: int = 20) -> list[sqlite3.Row]:
    rows = listar_ultima_coleta("AND instavel = 1", ())
    return sorted(rows, key=lambda r: r["oscilacao_24h"], reverse=True)[:limite]


def listar_bons_excelentes() -> list[sqlite3.Row]:
    return listar_ultima_coleta("AND categoria IN (?, ?)", ("BOM", "EXCELENTE"))


def serie_evolucao(limite: int = 200) -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT nome, login, rx, tx, data_hora
            FROM historico_sinal
            ORDER BY data_hora DESC, id DESC
            LIMIT ?
            """,
            (limite,),
        ).fetchall()
