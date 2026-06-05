from dataclasses import dataclass
from datetime import datetime


@dataclass
class ClienteSinal:
    cliente_id: str
    nome: str
    login: str
    rx: float | None
    tx: float | None
    status_onu: str
    categoria: str
    score: int
    instavel: bool
    oscilacao_24h: float
    data_hora: datetime
