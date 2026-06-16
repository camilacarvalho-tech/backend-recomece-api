from sqlalchemy import Column, Integer, String, DateTime, Boolean
from datetime import datetime

from database import Base


class Simulacao(Base):
    __tablename__ = "simulacoes"

    id = Column(Integer, primary_key=True, index=True)

    nome = Column(String)
    cpf = Column(String, index=True)
    telefone = Column(String)

    produto = Column(String)
    banco = Column(String)

    valor_aprovado = Column(Integer)
    score = Column(String)

    origem = Column(String, default="SITE")
    status = Column(String, default="NOVO")

    is_deleted = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)


class Mensagem(Base):
    __tablename__ = "mensagens"

    id = Column(Integer, primary_key=True, index=True)

    cpf = Column(String, index=True)
    autor = Column(String)
    texto = Column(String)

    data = Column(DateTime, default=datetime.utcnow)