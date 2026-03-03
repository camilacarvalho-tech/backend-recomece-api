from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import engine, SessionLocal, Base
from models import Simulacao
from services import calcular_valor, definir_banco, calcular_score

# cria as tabelas no banco
Base.metadata.create_all(bind=engine)

app = FastAPI()


class Cliente(BaseModel):
    nome: str
    cpf: str
    produto: str


@app.get("/")
def home():
    return {"mensagem": "API Recomece Cred funcionando 🚀"}


@app.post("/simular")
def simular(cliente: Cliente):
    db: Session = SessionLocal()

    # 1️⃣ define banco
    banco_escolhido = definir_banco(cliente.produto)

    # 2️⃣ calcula valor baseado no banco
    valor_simulado = calcular_valor(cliente.cpf, banco_escolhido)

    # 3️⃣ calcula score
    score = calcular_score(cliente.cpf)

    # 4️⃣ define status inteligente
    if score == "BAIXO":
        status = "EM ANÁLISE"
    elif score == "MÉDIO":
        status = "PRÉ-APROVADO"
    else:
        status = "APROVADO"

    # 5️⃣ salva no banco
    nova_simulacao = Simulacao(
        nome=cliente.nome,
        cpf=cliente.cpf,
        produto=cliente.produto,
        banco=banco_escolhido,
        valor_aprovado=valor_simulado,
        score=score
    )

    db.add(nova_simulacao)
    db.commit()
    db.refresh(nova_simulacao)
    db.close()

    return {
        "nome": cliente.nome,
        "cpf": cliente.cpf,
        "produto": cliente.produto,
        "banco": banco_escolhido,
        "valor_aprovado": valor_simulado,
        "score": score,
        "status": status
    }


@app.get("/simulacoes")
def listar_simulacoes():
    db: Session = SessionLocal()
    simulacoes = db.query(Simulacao).all()
    db.close()
    return simulacoes


@app.get("/simulacoes/{cpf}")
def buscar_por_cpf(cpf: str):
    db: Session = SessionLocal()
    simulacoes = db.query(Simulacao).filter(Simulacao.cpf == cpf).all()
    db.close()
    return simulacoes
@app.get("/dashboard")
def dashboard():
    db: Session = SessionLocal()

    total = db.query(Simulacao).count()
    baixo = db.query(Simulacao).filter(Simulacao.score == "BAIXO").count()
    medio = db.query(Simulacao).filter(Simulacao.score == "MÉDIO").count()
    alto = db.query(Simulacao).filter(Simulacao.score == "ALTO").count()

    db.close()

    return {
        "total_simulacoes": total,
        "score_baixo": baixo,
        "score_medio": medio,
        "score_alto": alto
    }