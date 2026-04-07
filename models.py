from sqlalchemy import Column, Integer, String
from database import Base

class Simulacao(Base):
    __tablename__ = "simulacoes"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String)
    cpf = Column(String)
    telefone = Column(String)  # 🔥 ADICIONEI
    produto = Column(String)
    banco = Column(String)
    valor_aprovado = Column(Integer)
    score = Column(String)