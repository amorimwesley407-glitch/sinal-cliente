from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta


DB_PATH = os.getenv("DATABASE_PATH", "sinal_clientes.db")
STATUS_NAO_MONITORAVEIS = ("INATIVO", "DESATIVADO")


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
                status_contrato TEXT,
                status_acesso TEXT,
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
                upload_bytes INTEGER,
                download_bytes INTEGER,
                upload TEXT,
                download TEXT,
                motivo_desconexao TEXT,
                causa_ultima_queda TEXT,
                tipo_bloqueio TEXT,
                data_bloqueio TEXT,
                data_hora TEXT NOT NULL
            )
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(historico_sinal)").fetchall()}
        migrations = {
            "contato": "ALTER TABLE historico_sinal ADD COLUMN contato TEXT",
            "status_contrato": "ALTER TABLE historico_sinal ADD COLUMN status_contrato TEXT",
            "status_acesso": "ALTER TABLE historico_sinal ADD COLUMN status_acesso TEXT",
            "tempo_ligado": "ALTER TABLE historico_sinal ADD COLUMN tempo_ligado TEXT",
            "tempo_ligado_segundos": "ALTER TABLE historico_sinal ADD COLUMN tempo_ligado_segundos INTEGER",
            "pon": "ALTER TABLE historico_sinal ADD COLUMN pon TEXT",
            "caixa": "ALTER TABLE historico_sinal ADD COLUMN caixa TEXT",
            "porta_caixa": "ALTER TABLE historico_sinal ADD COLUMN porta_caixa TEXT",
            "ultima_desconexao": "ALTER TABLE historico_sinal ADD COLUMN ultima_desconexao TEXT",
            "tempo_desconectado": "ALTER TABLE historico_sinal ADD COLUMN tempo_desconectado TEXT",
            "upload_bytes": "ALTER TABLE historico_sinal ADD COLUMN upload_bytes INTEGER",
            "download_bytes": "ALTER TABLE historico_sinal ADD COLUMN download_bytes INTEGER",
            "upload": "ALTER TABLE historico_sinal ADD COLUMN upload TEXT",
            "download": "ALTER TABLE historico_sinal ADD COLUMN download TEXT",
            "motivo_desconexao": "ALTER TABLE historico_sinal ADD COLUMN motivo_desconexao TEXT",
            "causa_ultima_queda": "ALTER TABLE historico_sinal ADD COLUMN causa_ultima_queda TEXT",
            "tipo_bloqueio": "ALTER TABLE historico_sinal ADD COLUMN tipo_bloqueio TEXT",
            "data_bloqueio": "ALTER TABLE historico_sinal ADD COLUMN data_bloqueio TEXT",
        }
        for column, sql in migrations.items():
            if column not in columns:
                conn.execute(sql)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_hist_cliente_data ON historico_sinal(cliente_id, data_hora)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_hist_status ON historico_sinal(status)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS consumo_banda_cache (
                login TEXT PRIMARY KEY,
                cliente_id TEXT,
                nome TEXT NOT NULL,
                contato TEXT,
                upload_bytes INTEGER NOT NULL DEFAULT 0,
                download_bytes INTEGER NOT NULL DEFAULT 0,
                upload TEXT,
                download TEXT,
                periodo_dias INTEGER NOT NULL,
                atualizado_em TEXT NOT NULL
            )
            """
        )


def salvar_coleta(registro: dict) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO historico_sinal (
                cliente_id, nome, contato, login, rx, tx, score, status, status_onu,
                status_contrato, status_acesso, categoria, instavel, oscilacao_24h,
                tempo_ligado, tempo_ligado_segundos,
                pon, caixa, porta_caixa, ultima_desconexao, tempo_desconectado,
                upload_bytes, download_bytes, upload, download,
                motivo_desconexao, causa_ultima_queda, tipo_bloqueio, data_bloqueio, data_hora
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                registro.get("status_contrato", ""),
                registro.get("status_acesso", ""),
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
                registro.get("upload_bytes"),
                registro.get("download_bytes"),
                registro.get("upload", ""),
                registro.get("download", ""),
                registro.get("motivo_desconexao", ""),
                registro.get("causa_ultima_queda", ""),
                registro.get("tipo_bloqueio", ""),
                registro.get("data_bloqueio", ""),
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
        SELECT * FROM ultimos
        WHERE rn = 1
          AND {filtro_monitoraveis_sql()}
          {where}
        ORDER BY score ASC, rx ASC
    """
    with get_connection() as conn:
        return conn.execute(query, (*STATUS_NAO_MONITORAVEIS, *STATUS_NAO_MONITORAVEIS, *params)).fetchall()


def listar_offline_24h(limite: int | None = 30) -> list[dict]:
    inicio = (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds")
    inicio_queda = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    offline = ("offline", "off-line", "down", "desconectada", "desconectado", "sem sinal")
    placeholders = ", ".join("?" for _ in offline)
    query = f"""
        WITH ultimos AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY COALESCE(NULLIF(login, ''), NULLIF(cliente_id, ''), nome)
                ORDER BY data_hora DESC, id DESC
            ) AS rn
            FROM historico_sinal
            WHERE cliente_id IS NOT NULL
              AND cliente_id != ''
              AND data_hora >= ?
        )
        SELECT * FROM ultimos
        WHERE rn = 1
          AND {filtro_monitoraveis_sql()}
          AND LOWER(TRIM(COALESCE(status_onu, ''))) IN ({placeholders})
          AND datetime(REPLACE(NULLIF(ultima_desconexao, ''), 'T', ' ')) >= datetime(?)
        ORDER BY data_hora DESC, score ASC, rx ASC
        { "LIMIT ?" if limite else "" }
    """
    with get_connection() as conn:
        params = (
            inicio,
            *STATUS_NAO_MONITORAVEIS,
            *STATUS_NAO_MONITORAVEIS,
            *offline,
            inicio_queda,
            limite,
        ) if limite else (
            inicio,
            *STATUS_NAO_MONITORAVEIS,
            *STATUS_NAO_MONITORAVEIS,
            *offline,
            inicio_queda,
        )
        rows = [dict(row) for row in conn.execute(query, params).fetchall()]
        sinais_validos = _ultimos_sinais_validos(conn, rows)
        for row in rows:
            if _sinal_valido(row.get("rx")) and _sinal_valido(row.get("tx")):
                continue
            valido = _sinal_valido_do_cliente(sinais_validos, row)
            if not valido:
                if not _sinal_valido(row.get("rx")):
                    row["rx"] = None
                if not _sinal_valido(row.get("tx")):
                    row["tx"] = None
                row["categoria"] = "SEM DADOS"
                continue
            if not _sinal_valido(row.get("rx")):
                row["rx"] = valido["rx"]
            if not _sinal_valido(row.get("tx")):
                row["tx"] = valido["tx"]
            row["categoria"] = valido["categoria"] or row["categoria"]
            row["score"] = valido["score"] if valido["score"] is not None else row["score"]
        return rows


def listar_offline_mais_de_um_dia(limite: int | None = None) -> list[dict]:
    limite_data = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    offline = ("offline", "off-line", "down", "desconectada", "desconectado", "sem sinal")
    placeholders = ", ".join("?" for _ in offline)
    query = f"""
        WITH base AS (
            SELECT
                *,
                COALESCE(NULLIF(login, ''), NULLIF(cliente_id, ''), nome) AS chave
            FROM historico_sinal
            WHERE cliente_id IS NOT NULL
              AND cliente_id != ''
        ),
        ultimos AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY chave
                ORDER BY data_hora DESC, id DESC
            ) AS rn
            FROM base
        )
        SELECT atual.*
        FROM ultimos atual
        WHERE atual.rn = 1
          AND {filtro_monitoraveis_sql()}
          AND LOWER(TRIM(COALESCE(atual.status_onu, ''))) IN ({placeholders})
          AND datetime(REPLACE(NULLIF(atual.ultima_desconexao, ''), 'T', ' ')) <= datetime(?)
        ORDER BY datetime(REPLACE(atual.ultima_desconexao, 'T', ' ')) ASC, atual.score ASC, atual.rx ASC
        { "LIMIT ?" if limite else "" }
    """
    params = [
        *STATUS_NAO_MONITORAVEIS,
        *STATUS_NAO_MONITORAVEIS,
        *offline,
        limite_data,
    ]
    if limite:
        params.append(limite)
    with get_connection() as conn:
        rows = [dict(row) for row in conn.execute(query, tuple(params)).fetchall()]
        sinais_validos = _ultimos_sinais_validos(conn, rows)
        for row in rows:
            if _sinal_valido(row.get("rx")) and _sinal_valido(row.get("tx")):
                continue
            valido = _sinal_valido_do_cliente(sinais_validos, row)
            if not valido:
                if not _sinal_valido(row.get("rx")):
                    row["rx"] = None
                if not _sinal_valido(row.get("tx")):
                    row["tx"] = None
                row["categoria"] = "SEM DADOS"
                continue
            if not _sinal_valido(row.get("rx")):
                row["rx"] = valido["rx"]
            if not _sinal_valido(row.get("tx")):
                row["tx"] = valido["tx"]
            row["categoria"] = valido["categoria"] or row["categoria"]
            row["score"] = valido["score"] if valido["score"] is not None else row["score"]
        return rows


def _sinal_valido(valor) -> bool:
    return valor not in (None, 0, 0.0)


def filtro_monitoraveis_sql() -> str:
    return """
        UPPER(TRIM(COALESCE(status_contrato, ''))) NOT IN (?, ?)
        AND UPPER(TRIM(COALESCE(status_acesso, ''))) NOT IN (?, ?)
    """


def _chave_sinal(row: dict) -> str:
    return str(row.get("login") or row.get("cliente_id") or "")


def _sinal_valido_do_cliente(sinais_validos: dict[str, sqlite3.Row], row: dict) -> sqlite3.Row | None:
    for chave in (row.get("login"), row.get("cliente_id"), _chave_sinal(row)):
        chave = str(chave or "")
        if chave and chave in sinais_validos:
            return sinais_validos[chave]
    return None


def _ultimos_sinais_validos(conn: sqlite3.Connection, rows: list[dict]) -> dict[str, sqlite3.Row]:
    identificadores = sorted(
        {
            str(valor)
            for row in rows
            for valor in (row.get("login"), row.get("cliente_id"), _chave_sinal(row))
            if valor
        }
    )
    if not identificadores:
        return {}
    placeholders = ", ".join("?" for _ in identificadores)
    query = f"""
        WITH validos AS (
            SELECT
                login,
                cliente_id,
                rx,
                tx,
                categoria,
                score,
                ROW_NUMBER() OVER (
                    PARTITION BY COALESCE(NULLIF(login, ''), NULLIF(cliente_id, ''))
                    ORDER BY data_hora DESC, id DESC
                ) AS rn
            FROM historico_sinal
            WHERE (
                login IN ({placeholders})
                OR cliente_id IN ({placeholders})
            )
              AND (
                (rx IS NOT NULL AND rx != 0)
                OR (tx IS NOT NULL AND tx != 0)
              )
        )
        SELECT login, cliente_id, rx, tx, categoria, score
        FROM validos
        WHERE rn = 1
    """
    sinais = {}
    for row in conn.execute(query, (*identificadores, *identificadores)).fetchall():
        for chave in (row["login"], row["cliente_id"]):
            chave = str(chave or "")
            if chave and chave not in sinais:
                sinais[chave] = row
    return sinais



def obter_historico_cliente(
    cliente_id: str,
    limite: int | None = 50,
    dias: int | None = None,
    login: str = "",
) -> list[sqlite3.Row]:
    filtro_data = ""
    if login:
        filtro_cliente = "login = ?"
        params: list = [login]
    else:
        filtro_cliente = """
            (
                cliente_id = ?
                OR login = (
                    SELECT login
                    FROM historico_sinal
                    WHERE cliente_id = ?
                      AND login IS NOT NULL
                      AND login != ''
                    ORDER BY data_hora DESC, id DESC
                    LIMIT 1
                )
            )
        """
        params = [cliente_id, cliente_id]
    if dias:
        filtro_data = "AND data_hora >= ?"
        params.append((datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds"))
    filtro_limite = ""
    if limite:
        filtro_limite = "LIMIT ?"
        params.append(limite)
    with get_connection() as conn:
        return conn.execute(
            f"""
            SELECT * FROM historico_sinal
            WHERE {filtro_cliente}
            {filtro_data}
            ORDER BY data_hora DESC, id DESC
            {filtro_limite}
            """,
            tuple(params),
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


def salvar_consumo_banda_cache(ranking: dict[str, list[dict]], periodo_dias: int) -> None:
    registros = {}
    for grupo in ("download", "upload"):
        for row in ranking.get(grupo, []):
            login = str(row.get("login") or "").strip()
            if not login:
                continue
            registros[login] = row
    atualizado_em = datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        conn.execute("DELETE FROM consumo_banda_cache")
        conn.executemany(
            """
            INSERT INTO consumo_banda_cache (
                login, cliente_id, nome, contato, upload_bytes, download_bytes,
                upload, download, periodo_dias, atualizado_em
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    login,
                    row.get("cliente_id", ""),
                    row.get("nome", ""),
                    row.get("contato", ""),
                    int(row.get("upload_bytes") or 0),
                    int(row.get("download_bytes") or 0),
                    row.get("upload", "") or formatar_bytes(int(row.get("upload_bytes") or 0)),
                    row.get("download", "") or formatar_bytes(int(row.get("download_bytes") or 0)),
                    periodo_dias,
                    atualizado_em,
                )
                for login, row in registros.items()
            ],
        )


def top_consumo_banda(limite: int = 5) -> dict[str, list[dict]]:
    with get_connection() as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM consumo_banda_cache").fetchall()]
    com_download = [row for row in rows if row.get("download_bytes")]
    com_upload = [row for row in rows if row.get("upload_bytes")]
    return {
        "download": sorted(com_download, key=lambda row: row["download_bytes"], reverse=True)[:limite],
        "upload": sorted(com_upload, key=lambda row: row["upload_bytes"], reverse=True)[:limite],
    }


def formatar_bytes(total: int | None) -> str:
    if total is None or total < 0:
        return ""
    unidades = ["B", "KB", "MB", "GB", "TB", "PB"]
    valor = float(total)
    indice = 0
    while valor >= 1024 and indice < len(unidades) - 1:
        valor /= 1024
        indice += 1
    if indice == 0:
        return f"{int(valor)} {unidades[indice]}"
    if valor >= 100:
        return f"{valor:.0f} {unidades[indice]}"
    return f"{valor:.1f} {unidades[indice]}"


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
