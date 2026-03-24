from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import engine, SessionLocal, Base
from models import Simulacao
from services import calcular_valor, definir_banco, calcular_score

# cria tabelas no banco
Base.metadata.create_all(bind=engine)

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# MODELOS
# =========================
class Cliente(BaseModel):
    nome: str
    cpf: str
    produto: str


class CapturaRequest(BaseModel):
    nome: str
    cpf: str
    telefone: str | None = None
    email: str | None = None
    produto: str = "FGTS"
    origem: str | None = None
    score: int | None = None
    data: str | None = None


# =========================
# ROTA INICIAL
# =========================
@app.get("/")
def home():
    return {"mensagem": "API Recomece Cred funcionando 🚀"}


# =========================
# SIMULAÇÃO
# =========================
@app.post("/simular")
def simular(cliente: Cliente):

    db: Session = SessionLocal()

    try:
        bancos = definir_banco(cliente.produto)

        resultado = []

        for banco in bancos:
            valor = calcular_valor(cliente.cpf, banco)

            resultado.append({
                "banco": banco,
                "valor": valor
            })

        banco_escolhido = resultado[0]["banco"]
        valor_simulado = resultado[0]["valor"]

        score = calcular_score(cliente.cpf)

        if score == "BAIXO":
            status = "EM ANÁLISE"
        elif score == "MÉDIO":
            status = "PRÉ-APROVADO"
        else:
            status = "APROVADO"

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

        return {
            "nome": cliente.nome,
            "cpf": cliente.cpf,
            "produto": cliente.produto,
            "score": score,
            "status": status,
            "simulacoes": resultado
        }

    finally:
        db.close()


# =========================
# LISTAR LEADS (CRM) ✅ AJUSTADO
# =========================
@app.get("/simulacoes")
def listar_simulacoes():
    db: Session = SessionLocal()
    try:
        dados = db.query(Simulacao).all()

        return [
            {
                "id": d.id,
                "nome": d.nome,
                "cpf": d.cpf,
                "produto": d.produto,
                "banco": d.banco,
                "valor_aprovado": d.valor_aprovado,
                "score": d.score
            }
            for d in dados
        ]

    finally:
        db.close()


# =========================
# CAPTURA
# =========================
@app.post("/captura")
def captura(dados: CapturaRequest):

    print("🔥 DADOS RECEBIDOS DO SITE:", dados)

    cliente = Cliente(
        nome=dados.nome,
        cpf=dados.cpf,
        produto=dados.produto
    )

    resultado = simular(cliente)

    print("✅ RESULTADO PROCESSADO:", resultado)

    return {
        "ok": True,
        "mensagem": "Lead capturado com sucesso",
        "cliente": {
            "nome": dados.nome,
            "cpf": dados.cpf,
            "telefone": dados.telefone,
            "email": dados.email
        },
        "resultado": resultado
    }