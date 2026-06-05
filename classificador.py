from __future__ import annotations


def normalizar_float(valor) -> float | None:
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip().lower()
    if not texto or texto in {"null", "none", "nan", "-"}:
        return None
    texto = (
        texto.replace("dbm", "")
        .replace("db", "")
        .replace(",", ".")
        .strip()
    )
    try:
        return float(texto)
    except ValueError:
        return None


def classificar_rx(rx: float | None) -> str:
    if rx is None:
        return "SEM DADOS"
    if -22 <= rx <= -17:
        return "EXCELENTE"
    if -26 <= rx < -22:
        return "BOM"
    if -28 <= rx < -26:
        return "ATENÇÃO"
    if rx < -28:
        return "CRÍTICO"
    return "FORA DO PADRÃO"


def tx_normal(tx: float | None) -> bool:
    return tx is not None and 0 <= tx <= 5


def onu_online(status_onu: str | None) -> bool:
    texto = (status_onu or "").strip().lower()
    offline = {"offline", "off-line", "down", "desconectada", "desconectado", "sem sinal"}
    return texto not in offline


def score_conexao(
    rx: float | None,
    tx: float | None,
    status_onu: str | None,
    oscilacao_24h: float = 0,
) -> int:
    categoria = classificar_rx(rx)
    base = {
        "EXCELENTE": 100,
        "BOM": 80,
        "ATENÇÃO": 50,
        "CRÍTICO": 20,
    }.get(categoria, 30)

    penalidade = 0
    if not tx_normal(tx):
        penalidade += 10
    if not onu_online(status_onu):
        penalidade += 30
    if oscilacao_24h > 5:
        penalidade += 20
    elif oscilacao_24h > 3:
        penalidade += 10

    return max(0, min(100, base - penalidade))


def detectar_instabilidade(rx_values: list[float]) -> tuple[bool, float]:
    valores = [v for v in rx_values if v is not None]
    if len(valores) < 2:
        return False, 0.0
    oscilacao = round(max(valores) - min(valores), 2)
    return oscilacao > 3 or oscilacao > 5, oscilacao
