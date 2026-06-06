from __future__ import annotations

import logging
import os
from base64 import b64encode
from datetime import datetime, timedelta
from typing import Any

import requests

from classificador import normalizar_float


logger = logging.getLogger(__name__)
STATUS_NAO_MONITORAVEIS = {"INATIVO", "DESATIVADO"}


class IXCClient:
    def __init__(self, base_url: str | None = None, token: str | None = None, timeout: int | None = None):
        self.base_url = (base_url or os.getenv("IXC_BASE_URL", "")).rstrip("/")
        self.token = token or os.getenv("IXC_TOKEN", "")
        self.timeout = timeout or int(os.getenv("IXC_TIMEOUT", "30"))
        if not self.base_url:
            raise ValueError("IXC_BASE_URL não configurado.")
        if not self.token:
            raise ValueError("IXC_TOKEN não configurado.")

    @property
    def headers(self) -> dict[str, str]:
        token = self.token.strip()
        if not token.lower().startswith("basic "):
            token = "Basic " + b64encode(token.encode("utf-8")).decode("ascii")
        return {
            "Authorization": token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "ixcsoft": "listar",
        }

    def listar(self, endpoint: str, filtros: dict[str, Any] | None = None, page: int = 1, rp: int = 1000) -> dict:
        url = f"{self.base_url}/{endpoint.strip('/')}"
        payload = {
            "qtype": filtros.get("qtype", "") if filtros else "",
            "query": filtros.get("query", "") if filtros else "",
            "oper": filtros.get("oper", "=") if filtros else "=",
            "page": str(page),
            "rp": str(rp),
            "sortname": filtros.get("sortname", "id") if filtros else "id",
            "sortorder": filtros.get("sortorder", "asc") if filtros else "asc",
        }
        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            logger.exception("Erro ao consultar endpoint IXC %s", endpoint)
            raise RuntimeError(f"Falha ao consultar IXC em {endpoint}: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError(f"Resposta inválida do IXC em {endpoint}.") from exc

    def listar_todos(self, endpoint: str, filtros: dict[str, Any] | None = None, rp: int = 1000) -> list[dict]:
        page = 1
        registros: list[dict] = []
        while True:
            dados = self.listar(endpoint, filtros=filtros, page=page, rp=rp)
            rows = dados.get("registros") or dados.get("rows") or []
            if isinstance(rows, dict):
                rows = list(rows.values())
            registros.extend(rows)
            total = int(dados.get("total", len(registros)) or 0)
            if not rows or len(registros) >= total:
                break
            page += 1
        return registros

    def buscar_cliente(self, cliente_id: str) -> dict | None:
        if not cliente_id:
            return None
        rows = self.listar_todos("cliente", {"qtype": "cliente.id", "query": cliente_id, "oper": "="}, rp=1)
        return rows[0] if rows else None

    def buscar_usuario_radius(self, login: str | None = None, id_radusuario: str | None = None) -> dict | None:
        if id_radusuario:
            filtros = {"qtype": "radusuarios.id", "query": id_radusuario, "oper": "="}
        elif login:
            filtros = {"qtype": "radusuarios.login", "query": login, "oper": "="}
        else:
            return None
        rows = self.listar_todos("radusuarios", filtros, rp=1)
        return rows[0] if rows else None

    def buscar_cliente_fibra(self, login: str | None = None, cliente_id: str | None = None) -> dict | None:
        filtros_tentativas = []
        usuario = self.buscar_usuario_radius(login=login) if login else None
        id_login = str(primeiro_valor(usuario or {}, ["id"]) or "")
        if id_login:
            filtros_tentativas.append(
                {"qtype": "radpop_radio_cliente_fibra.id_login", "query": id_login, "oper": "="}
            )
        if cliente_id:
            filtros_tentativas.append(
                {"qtype": "radpop_radio_cliente_fibra.id_cliente", "query": cliente_id, "oper": "="}
            )

        for filtros in filtros_tentativas:
            rows = self.listar_todos("radpop_radio_cliente_fibra", filtros, rp=1)
            if rows:
                return rows[0]
        return None

    def buscar_historico_potenciacao(self, id_cliente_fibra: str, limite: int = 15) -> list[dict]:
        if not id_cliente_fibra:
            return []
        filtros = {
            "qtype": "radpop_radio_cliente_fibra_historico.id_cliente_fibra",
            "query": id_cliente_fibra,
            "oper": "=",
            "sortname": "radpop_radio_cliente_fibra_historico.data_sinal",
            "sortorder": "desc",
        }
        dados = self.listar("radpop_radio_cliente_fibra_historico", filtros=filtros, page=1, rp=limite)
        rows = dados.get("registros") or dados.get("rows") or []
        if isinstance(rows, dict):
            rows = list(rows.values())
        return [normalizar_historico_potenciacao(row) for row in rows]

    def buscar_dados_bloqueio(self, cliente_id: str, status_acesso: str) -> dict:
        if not cliente_id:
            return {"tipo_bloqueio": "", "data_bloqueio": ""}
        rows = self.listar_todos(
            "cliente_contrato",
            {"qtype": "cliente_contrato.id_cliente", "query": cliente_id, "oper": "="},
            rp=20,
        )
        for contrato in rows:
            if status_contrato(contrato) != "ATIVO":
                continue
            status = status_acesso_contrato(contrato, {})
            if status == status_acesso:
                return dados_bloqueio_contrato(contrato, status)
        return {"tipo_bloqueio": "", "data_bloqueio": ""}

    def buscar_historico_conexao(self, login: str, dias: int = 7, limite: int = 100) -> list[dict]:
        if not login:
            return []
        filtros = {
            "qtype": "radacct.username",
            "query": login,
            "oper": "=",
            "sortname": "acctstarttime",
            "sortorder": "desc",
        }
        dados = self.listar("radacct", filtros=filtros, page=1, rp=limite)
        rows = dados.get("registros") or dados.get("rows") or []
        if isinstance(rows, dict):
            rows = list(rows.values())
        inicio_periodo = datetime.now() - timedelta(days=dias)
        sessoes = [normalizar_sessao_radius(row) for row in rows]
        sessoes = [row for row in sessoes if row["inicio_dt"] and row["inicio_dt"] >= inicio_periodo]
        return calcular_intervalos_desconectado(sessoes)

    def coletar_sinais(self) -> list[dict]:
        fibras = self.listar_todos("radpop_radio_cliente_fibra")
        logger.info("IXC: %s registros de fibra carregados.", len(fibras))

        radusuarios = self.listar_todos("radusuarios")
        rad_por_id = {str(row.get("id")): row for row in radusuarios if row.get("id")}
        logger.info("IXC: %s radusuarios carregados.", len(rad_por_id))

        clientes = self.listar_todos("cliente")
        cliente_por_id = {str(row.get("id")): row for row in clientes if row.get("id")}
        logger.info("IXC: %s clientes carregados.", len(cliente_por_id))

        contratos = self.listar_todos(
            "cliente_contrato",
            {"qtype": "cliente_contrato.status", "query": "A", "oper": "="},
        )
        contrato_por_id = {
            str(row.get("id")): row
            for row in contratos
            if row.get("id") and contrato_monitoravel(row)
        }
        logger.info("IXC: %s contratos ativos/monitoraveis carregados.", len(contrato_por_id))

        caixas = self.listar_todos("rad_caixa_ftth")
        caixa_por_id = {str(row.get("id")): row for row in caixas if row.get("id")}
        logger.info("IXC: %s caixas FTTH carregadas.", len(caixa_por_id))

        coleta = []
        ignorados = 0
        for fibra in fibras:
            registro = self._normalizar_fibra(fibra)
            if registro.get("contrato_id") and registro["contrato_id"] not in contrato_por_id:
                ignorados += 1
                continue

            radius = rad_por_id.get(registro.get("radusuario_id", ""))
            cliente_id = str(primeiro_valor(radius or {}, ["id_cliente"]) or registro["cliente_id"])
            cliente = cliente_por_id.get(cliente_id)
            contrato = contrato_por_id.get(registro.get("contrato_id", ""))
            caixa = caixa_por_id.get(registro.get("caixa_id", ""))

            registro["cliente_id"] = cliente_id or registro["cliente_id"]
            registro["nome"] = primeiro_valor(cliente or {}, ["razao", "nome", "fantasia"]) or registro["nome"]
            registro["contato"] = contato_cliente(cliente or {})
            registro["login"] = primeiro_valor(radius or {}, ["login", "usuario"]) or registro["login"]
            registro["status_onu"] = status_online(primeiro_valor(radius or {}, ["online"])) or registro["status_onu"]
            registro["status_contrato"] = status_contrato(contrato or {})
            registro["status_acesso"] = status_acesso_contrato(contrato or {}, radius or {})
            registro.update(dados_bloqueio_contrato(contrato or {}, registro["status_acesso"]))
            if not cliente_monitoravel(registro["status_contrato"], registro["status_acesso"]):
                ignorados += 1
                continue

            registro["caixa"] = primeiro_valor(caixa or {}, ["descricao", "nome"]) or registro["caixa"]
            registro.update(dados_conexao(radius or {}))
            coleta.append(registro)
        logger.info("IXC: %s registros ignorados por status inativo/desativado.", ignorados)
        return coleta

    def _normalizar_fibra(self, fibra: dict) -> dict:
        return {
            "cliente_id": str(primeiro_valor(fibra, ["id_cliente", "cliente_id", "idcliente", "id_contrato", "id"]) or ""),
            "nome": str(primeiro_valor(fibra, ["cliente", "nome", "razao"]) or "Cliente sem nome"),
            "contato": "",
            "contrato_id": str(primeiro_valor(fibra, ["id_contrato", "contrato_id"]) or ""),
            "login": str(primeiro_valor(fibra, ["login", "login_pppoe", "pppoe"]) or ""),
            "radusuario_id": str(primeiro_valor(fibra, ["id_radusuario", "radusuario_id", "id_login"]) or ""),
            "rx": normalizar_float(primeiro_valor(fibra, ["sinal_rx", "rx", "potencia_rx", "onu_rx"])),
            "tx": normalizar_float(primeiro_valor(fibra, ["sinal_tx", "tx", "potencia_tx", "onu_tx"])),
            "status_onu": status_online(primeiro_valor(fibra, ["status_onu", "status", "online"])) or "DESCONHECIDO",
            "status_acesso": "DESCONHECIDO",
            "status_contrato": "DESCONHECIDO",
            "pon": str(primeiro_valor(fibra, ["ponid", "pon", "ponno"]) or ""),
            "caixa_id": str(primeiro_valor(fibra, ["id_caixa_ftth", "caixa", "caixa_ftth"]) or ""),
            "caixa": str(primeiro_valor(fibra, ["id_caixa_ftth", "caixa", "caixa_ftth"]) or ""),
            "porta_caixa": str(primeiro_valor(fibra, ["porta_ftth", "porta_caixa"]) or ""),
            "causa_ultima_queda": str(primeiro_valor(fibra, ["causa_ultima_queda"]) or ""),
            "tempo_ligado": "",
            "tempo_ligado_segundos": None,
            "ultima_desconexao": "",
            "tempo_desconectado": "",
            "tipo_bloqueio": "",
            "data_bloqueio": "",
            "data_hora": datetime.now().isoformat(timespec="seconds"),
        }


def primeiro_valor(dados: dict, chaves: list[str]) -> Any:
    normalizado = {str(k).lower(): v for k, v in dados.items()}
    for chave in chaves:
        valor = normalizado.get(chave.lower())
        if valor not in (None, ""):
            return valor
    return None


def normalizar_historico_potenciacao(row: dict) -> dict:
    return {
        "data_sinal": str(primeiro_valor(row, ["data_sinal"]) or ""),
        "sinal_rx": normalizar_float(primeiro_valor(row, ["sinal_rx", "rx"])),
        "sinal_tx": normalizar_float(primeiro_valor(row, ["sinal_tx", "tx"])),
        "temperatura": normalizar_float(primeiro_valor(row, ["temperatura"])),
        "voltagem": normalizar_float(primeiro_valor(row, ["voltagem"])),
    }


def contato_cliente(cliente: dict) -> str:
    valores = []
    for campo in ["whatsapp", "telefone_celular", "fone", "telefone_comercial", "contato"]:
        valor = primeiro_valor(cliente, [campo])
        if valor and str(valor).strip() not in valores:
            valores.append(str(valor).strip())
    return " / ".join(valores)


def contrato_monitoravel(contrato: dict) -> bool:
    return cliente_monitoravel(status_contrato(contrato), status_acesso_contrato(contrato, {}))


def cliente_monitoravel(status_do_contrato: str, status_do_acesso: str) -> bool:
    contrato = str(status_do_contrato or "").strip().upper()
    acesso = str(status_do_acesso or "").strip().upper()
    return contrato not in STATUS_NAO_MONITORAVEIS and acesso not in STATUS_NAO_MONITORAVEIS


def dados_conexao(radius: dict) -> dict:
    agora = datetime.now()
    online = str(primeiro_valor(radius, ["online"]) or "").strip().lower() in {"s", "sim", "online", "on", "1", "true"}
    tempo_segundos = inteiro(primeiro_valor(radius, ["tempo_conectado", "tempo_conexao"]))
    ultima_desconexao = str(primeiro_valor(radius, ["ultima_conexao_final"]) or "")
    ultima_conexao = str(primeiro_valor(radius, ["ultima_conexao_inicial"]) or "")

    if online and (tempo_segundos is None or tempo_segundos <= 0):
        inicio = parse_ixc_datetime(ultima_conexao)
        if inicio:
            tempo_segundos = int((agora - inicio).total_seconds())

    tempo_ligado = formatar_duracao(tempo_segundos) if online or (tempo_segundos and tempo_segundos > 0) else ""

    return {
        "tempo_ligado": tempo_ligado,
        "tempo_ligado_segundos": tempo_segundos,
        "ultima_desconexao": ultima_desconexao,
        "tempo_desconectado": calcular_tempo_desconectado(ultima_desconexao, ultima_conexao, online=online, agora=agora),
        "motivo_desconexao": str(primeiro_valor(radius, ["motivo_desconexao"]) or ""),
    }


def status_contrato(contrato: dict) -> str:
    status = str(primeiro_valor(contrato, ["status"]) or "").strip().upper()
    mapa = {
        "A": "ATIVO",
        "I": "INATIVO",
        "P": "PRÉ-CONTRATO",
        "D": "DESISTIU",
        "N": "NEGATIVADO",
        "C": "CANCELADO",
    }
    return mapa.get(status, status or "DESCONHECIDO")


def status_acesso_contrato(contrato: dict, radius: dict) -> str:
    status = str(primeiro_valor(contrato, ["status_internet"]) or "").strip().upper()
    mapa = {
        "A": "ATIVO",
        "AA": "AVISO DE ATRASO",
        "CA": "BLOQUEIO AUTOMÁTICO",
        "CM": "BLOQUEIO MANUAL",
        "D": "DESATIVADO",
        "FA": "FINANCEIRO EM ATRASO",
    }
    if status:
        return mapa.get(status, status)
    ativo = str(primeiro_valor(radius, ["ativo"]) or "").strip().upper()
    if ativo == "N":
        return "INATIVO"
    return status_online(primeiro_valor(radius, ["online"])) or "DESCONHECIDO"


def dados_bloqueio_contrato(contrato: dict, status_acesso: str) -> dict:
    status = str(status_acesso or "").strip().upper()
    if status == "BLOQUEIO AUTOMÁTICO":
        data_bloqueio = str(primeiro_valor(contrato, ["dt_ult_bloq_auto"]) or "")
    elif status == "BLOQUEIO MANUAL":
        data_bloqueio = str(primeiro_valor(contrato, ["dt_ult_bloq_manual"]) or "")
    else:
        return {"tipo_bloqueio": "", "data_bloqueio": ""}

    if data_bloqueio in {"0000-00-00", "0000-00-00 00:00:00"}:
        data_bloqueio = ""
    return {
        "tipo_bloqueio": status,
        "data_bloqueio": data_bloqueio,
    }


def inteiro(valor: Any) -> int | None:
    if valor in (None, ""):
        return None
    try:
        return int(float(str(valor).strip()))
    except ValueError:
        return None


def formatar_duracao(segundos: int | None) -> str:
    if segundos is None or segundos < 0:
        return ""
    if segundos < 60:
        return f"{segundos}s"
    dias, resto = divmod(segundos, 86400)
    horas, resto = divmod(resto, 3600)
    minutos, _ = divmod(resto, 60)
    partes = []
    if dias:
        partes.append(f"{dias}d")
    if horas:
        partes.append(f"{horas}h")
    if minutos or not partes:
        partes.append(f"{minutos}min")
    return " ".join(partes[:3])


def parse_ixc_datetime(valor: str) -> datetime | None:
    if not valor:
        return None
    texto = str(valor).strip()
    formatos = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
    ]
    for formato in formatos:
        try:
            return datetime.strptime(texto[:19], formato)
        except ValueError:
            continue
    return None


def calcular_tempo_desconectado(
    inicio_queda: str,
    reconexao: str,
    online: bool = False,
    agora: datetime | None = None,
) -> str:
    if not inicio_queda:
        return ""
    queda = parse_ixc_datetime(inicio_queda)
    if not queda:
        return ""
    volta = parse_ixc_datetime(reconexao)

    if not online:
        segundos = int(((agora or datetime.now()) - queda).total_seconds())
        return formatar_duracao(segundos) if segundos >= 0 else ""

    if not volta:
        return ""
    segundos = int((volta - queda).total_seconds())
    if segundos < 0:
        return ""
    return formatar_duracao(segundos)


def normalizar_sessao_radius(row: dict) -> dict:
    inicio = parse_ixc_datetime(str(primeiro_valor(row, ["acctstarttime"]) or ""))
    fim = parse_ixc_datetime(str(primeiro_valor(row, ["acctstoptime"]) or ""))
    tempo_segundos = inteiro(primeiro_valor(row, ["acctsessiontime"]))
    return {
        "inicio_dt": inicio,
        "fim_dt": fim,
        "inicio": formatar_data_br(inicio),
        "fim": formatar_data_br(fim),
        "tempo_ligado": formatar_duracao(tempo_segundos),
        "tempo_desconectado": "",
        "motivo": str(primeiro_valor(row, ["acctterminatecause"]) or ""),
        "ip": str(primeiro_valor(row, ["framedipaddress"]) or ""),
        "mac": str(primeiro_valor(row, ["callingstationid"]) or ""),
        "concentrador": str(primeiro_valor(row, ["nasipaddress"]) or ""),
    }


def calcular_intervalos_desconectado(sessoes_desc: list[dict]) -> list[dict]:
    sessoes_asc = sorted(sessoes_desc, key=lambda row: row["inicio_dt"] or datetime.min)
    agora = datetime.now()
    for indice, sessao in enumerate(sessoes_asc):
        fim = sessao.get("fim_dt")
        if not fim:
            continue
        proxima = sessoes_asc[indice + 1] if indice + 1 < len(sessoes_asc) else None
        volta = proxima.get("inicio_dt") if proxima else agora
        if volta and volta >= fim:
            sessao["tempo_desconectado"] = formatar_duracao(int((volta - fim).total_seconds()))
    return sorted(sessoes_asc, key=lambda row: row["inicio_dt"] or datetime.min, reverse=True)


def formatar_data_br(valor: datetime | None) -> str:
    if not valor:
        return ""
    return valor.strftime("%d/%m/%Y %H:%M:%S")


def status_online(valor: Any) -> str | None:
    if valor in (None, ""):
        return None
    texto = str(valor).strip().lower()
    if texto in {"s", "sim", "online", "on", "1", "true"}:
        return "ONLINE"
    if texto in {"n", "nao", "não", "offline", "off", "0", "false"}:
        return "OFFLINE"
    return str(valor).strip().upper()
