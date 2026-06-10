from __future__ import annotations

import os
import sqlite3
import time
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timedelta


DB_PATH = os.getenv("DATABASE_PATH", "sinal_clientes.db")
STATUS_NAO_MONITORAVEIS = ("INATIVO", "DESATIVADO")
_DASHBOARD_CACHE: dict[str, object] = {"token": None, "value": None}
_SERIE_EVOLUCAO_CACHE: dict[str, object] = {"token": None, "limite": None, "value": None}

_COLUNAS_COLETA = (
    "id",
    "cliente_id",
    "nome",
    "contato",
    "login",
    "rx",
    "tx",
    "score",
    "status",
    "status_onu",
    "status_contrato",
    "status_acesso",
    "categoria",
    "instavel",
    "oscilacao_24h",
    "tempo_ligado",
    "tempo_ligado_segundos",
    "pon",
    "caixa",
    "porta_caixa",
    "ultima_desconexao",
    "tempo_desconectado",
    "upload_bytes",
    "download_bytes",
    "upload",
    "download",
    "motivo_desconexao",
    "causa_ultima_queda",
    "tipo_bloqueio",
    "data_bloqueio",
    "data_hora",
)


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _db_token() -> float:
    try:
        return os.path.getmtime(DB_PATH)
    except OSError:
        return time.time()


def _invalidate_caches() -> None:
    _DASHBOARD_CACHE.update({"token": None, "value": None})
    _SERIE_EVOLUCAO_CACHE.update({"token": None, "limite": None, "value": None})


def _cliente_chave(registro: dict | sqlite3.Row) -> str:
    try:
        login = registro["login"]
    except (KeyError, TypeError, IndexError):
        login = ""
    try:
        cliente_id = registro["cliente_id"]
    except (KeyError, TypeError, IndexError):
        cliente_id = ""
    try:
        nome = registro["nome"]
    except (KeyError, TypeError, IndexError):
        nome = ""
    return str(login or cliente_id or nome or "").strip()


def _valores_coleta(registro: dict, historico_id: int) -> tuple:
    return (
        historico_id,
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
    )


def _reconstruir_ultima_coleta(conn: sqlite3.Connection) -> None:
    total_historico = conn.execute("SELECT COUNT(*) FROM historico_sinal").fetchone()[0]
    total_ultima = conn.execute("SELECT COUNT(*) FROM ultima_coleta").fetchone()[0]
    if total_historico == 0 or total_ultima > 0:
        return

    colunas = ", ".join(_COLUNAS_COLETA)
    conn.execute(
        f"""
        INSERT INTO ultima_coleta (cliente_chave, {colunas})
        WITH ranqueados AS (
            SELECT
                COALESCE(NULLIF(login, ''), NULLIF(cliente_id, ''), nome) AS cliente_chave,
                {colunas},
                ROW_NUMBER() OVER (
                    PARTITION BY COALESCE(NULLIF(login, ''), NULLIF(cliente_id, ''), nome)
                    ORDER BY data_hora DESC, id DESC
                ) AS rn
            FROM historico_sinal
            WHERE cliente_id IS NOT NULL
              AND cliente_id != ''
        )
        SELECT cliente_chave, {colunas}
        FROM ranqueados
        WHERE rn = 1
        """
    )


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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_hist_login_data ON historico_sinal(login, data_hora)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_hist_status ON historico_sinal(status)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ultima_coleta (
                cliente_chave TEXT PRIMARY KEY,
                id INTEGER NOT NULL,
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ultima_score_rx ON ultima_coleta(score, rx)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ultima_categoria ON ultima_coleta(categoria)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ultima_status_onu ON ultima_coleta(status_onu)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ultima_queda ON ultima_coleta(ultima_desconexao)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ultima_data_hora ON ultima_coleta(data_hora)")
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
        _reconstruir_ultima_coleta(conn)


def salvar_coleta(registro: dict) -> None:
    with get_connection() as conn:
        cursor = conn.execute(
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
        historico_id = int(cursor.lastrowid)
        cliente_chave = _cliente_chave(registro)
        conn.execute(
            """
            DELETE FROM ultima_coleta
            WHERE cliente_chave != ?
              AND (
                (? != '' AND login = ?)
                OR (? != '' AND cliente_id = ?)
              )
            """,
            (
                cliente_chave,
                str(registro.get("login") or "").strip(),
                str(registro.get("login") or "").strip(),
                str(registro.get("cliente_id") or "").strip(),
                str(registro.get("cliente_id") or "").strip(),
            ),
        )
        colunas = ", ".join(_COLUNAS_COLETA)
        placeholders = ", ".join("?" for _ in _COLUNAS_COLETA)
        conn.execute(
            f"""
            INSERT INTO ultima_coleta (cliente_chave, {colunas})
            VALUES (?, {placeholders})
            ON CONFLICT(cliente_chave) DO UPDATE SET
                id = excluded.id,
                cliente_id = excluded.cliente_id,
                nome = excluded.nome,
                contato = excluded.contato,
                login = excluded.login,
                rx = excluded.rx,
                tx = excluded.tx,
                score = excluded.score,
                status = excluded.status,
                status_onu = excluded.status_onu,
                status_contrato = excluded.status_contrato,
                status_acesso = excluded.status_acesso,
                categoria = excluded.categoria,
                instavel = excluded.instavel,
                oscilacao_24h = excluded.oscilacao_24h,
                tempo_ligado = excluded.tempo_ligado,
                tempo_ligado_segundos = excluded.tempo_ligado_segundos,
                pon = excluded.pon,
                caixa = excluded.caixa,
                porta_caixa = excluded.porta_caixa,
                ultima_desconexao = excluded.ultima_desconexao,
                tempo_desconectado = excluded.tempo_desconectado,
                upload_bytes = excluded.upload_bytes,
                download_bytes = excluded.download_bytes,
                upload = excluded.upload,
                download = excluded.download,
                motivo_desconexao = excluded.motivo_desconexao,
                causa_ultima_queda = excluded.causa_ultima_queda,
                tipo_bloqueio = excluded.tipo_bloqueio,
                data_bloqueio = excluded.data_bloqueio,
                data_hora = excluded.data_hora
            """,
            (cliente_chave, *_valores_coleta(registro, historico_id)),
        )
    _invalidate_caches()


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
        SELECT {", ".join(_COLUNAS_COLETA)}
        FROM ultima_coleta
        WHERE cliente_id IS NOT NULL
          AND cliente_id != ''
          AND {filtro_monitoraveis_sql()}
          {where}
        ORDER BY score ASC, rx ASC
    """
    with get_connection() as conn:
        return conn.execute(query, (*STATUS_NAO_MONITORAVEIS, *STATUS_NAO_MONITORAVEIS, *params)).fetchall()


def _normalizar_categoria(valor: str) -> str:
    texto = unicodedata.normalize("NFKD", str(valor or "").strip().upper())
    return texto.encode("ascii", "ignore").decode("ascii")


def _snapshot_dashboard() -> dict[str, object]:
    token = _db_token()
    if _DASHBOARD_CACHE["value"] is not None and _DASHBOARD_CACHE["token"] == token:
        return _DASHBOARD_CACHE["value"]  # type: ignore[return-value]

    ultimos = listar_ultima_coleta()
    categorias: dict[str, int] = {}
    criticos: list[sqlite3.Row] = []
    instaveis = 0

    for row in ultimos:
        categoria = _normalizar_categoria(row["categoria"])
        categorias[categoria] = categorias.get(categoria, 0) + 1
        if categoria == "CRITICO" and len(criticos) < 20:
            criticos.append(row)
        if row["instavel"]:
            instaveis += 1

    snapshot = {
        "ultimos": ultimos,
        "stats": {
            "total": len(ultimos),
            "criticos": categorias.get("CRITICO", 0),
            "atencao": categorias.get("ATENCAO", 0),
            "bons": categorias.get("BOM", 0),
            "excelentes": categorias.get("EXCELENTE", 0),
            "instaveis": instaveis,
            "categorias": categorias,
        },
        "top_criticos": criticos,
    }
    _DASHBOARD_CACHE.update({"token": token, "value": snapshot})
    return snapshot


def listar_ultima_coleta_cached() -> list[sqlite3.Row]:
    return _snapshot_dashboard()["ultimos"]  # type: ignore[return-value]


def listar_clientes_por_categoria(*categorias: str) -> list[sqlite3.Row]:
    categorias_norm = {_normalizar_categoria(categoria) for categoria in categorias}
    return [
        row
        for row in listar_ultima_coleta_cached()
        if _normalizar_categoria(row["categoria"]) in categorias_norm
    ]


def listar_offline_24h(limite: int | None = 30) -> list[dict]:
    inicio_queda = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    offline = ("offline", "off-line", "down", "desconectada", "desconectado", "sem sinal")
    placeholders = ", ".join("?" for _ in offline)
    query = f"""
        SELECT {", ".join(_COLUNAS_COLETA)}
        FROM ultima_coleta
        WHERE cliente_id IS NOT NULL
          AND cliente_id != ''
          AND {filtro_monitoraveis_sql()}
          AND data_hora >= ?
          AND LOWER(TRIM(COALESCE(status_onu, ''))) IN ({placeholders})
          AND datetime(REPLACE(NULLIF(ultima_desconexao, ''), 'T', ' ')) >= datetime(?)
        ORDER BY data_hora DESC, score ASC, rx ASC
        { "LIMIT ?" if limite else "" }
    """
    with get_connection() as conn:
        params = (
            *STATUS_NAO_MONITORAVEIS,
            *STATUS_NAO_MONITORAVEIS,
            (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds"),
            *offline,
            inicio_queda,
            limite,
        ) if limite else (
            *STATUS_NAO_MONITORAVEIS,
            *STATUS_NAO_MONITORAVEIS,
            (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds"),
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
        SELECT {", ".join(_COLUNAS_COLETA)}
        FROM ultima_coleta
        WHERE cliente_id IS NOT NULL
          AND cliente_id != ''
          AND {filtro_monitoraveis_sql()}
          AND LOWER(TRIM(COALESCE(status_onu, ''))) IN ({placeholders})
          AND datetime(REPLACE(NULLIF(ultima_desconexao, ''), 'T', ' ')) <= datetime(?)
        ORDER BY datetime(REPLACE(ultima_desconexao, 'T', ' ')) ASC, score ASC, rx ASC
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
    return _snapshot_dashboard()["stats"]  # type: ignore[return-value]


def top_criticos(limite: int = 20) -> list[sqlite3.Row]:
    return listar_clientes_por_categoria("CRITICO")[:limite]


def top_instaveis(limite: int = 20) -> list[sqlite3.Row]:
    rows = [row for row in listar_ultima_coleta_cached() if row["instavel"]]
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
    _invalidate_caches()


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
    return listar_clientes_por_categoria("BOM", "EXCELENTE")


def resumo_ultima_coleta() -> dict[str, int | str | None]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT MAX(data_hora) AS ultima_data_hora, COUNT(*) AS total_clientes
            FROM ultima_coleta
            """
        ).fetchone()
    return {
        "ultima_data_hora": row["ultima_data_hora"] if row else None,
        "total_clientes": int(row["total_clientes"] or 0) if row else 0,
    }


def serie_evolucao(limite: int = 200) -> list[sqlite3.Row]:
    token = _db_token()
    if (
        _SERIE_EVOLUCAO_CACHE["value"] is not None
        and _SERIE_EVOLUCAO_CACHE["token"] == token
        and _SERIE_EVOLUCAO_CACHE["limite"] == limite
    ):
        return _SERIE_EVOLUCAO_CACHE["value"]  # type: ignore[return-value]

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT nome, login, rx, tx, data_hora
            FROM historico_sinal
            ORDER BY data_hora DESC, id DESC
            LIMIT ?
            """,
            (limite,),
        ).fetchall()
    _SERIE_EVOLUCAO_CACHE.update({"token": token, "limite": limite, "value": rows})
    return rows
