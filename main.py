from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import engine, SessionLocal, Base
from models import Simulacao
from services import calcular_valor, definir_banco, calcular_score

# =========================
# CRIAR TABELAS
# =========================
Base.metadata.create_all(bind=engine)

app = FastAPI()

# =========================
# CORS
# =========================
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


# =========================
# TESTE API
# =========================
@app.get("/")
def home():
    return {"mensagem": "API Recomece Cred funcionando 🚀"}


# =========================
# FUNÇÃO INTERNA DE SIMULAÇÃO
# =========================
def processar_simulacao(cliente: Cliente, db: Session):
    bancos = definir_banco(cliente.produto)
    resultado = []

    for banco in bancos:
        valor = calcular_valor(cliente.cpf, banco)

        nova_simulacao = Simulacao(
            nome=cliente.nome,
            cpf=cliente.cpf,
            telefone=None,
            produto=cliente.produto,
            banco=banco,
            valor_aprovado=valor,
            score="PROCESSANDO"
        )

        db.add(nova_simulacao)

        resultado.append({
            "banco": banco,
            "valor": valor
        })

    score = calcular_score(cliente.cpf)

    if score == "BAIXO":
        status = "EM ANÁLISE"
    elif score == "MÉDIO":
        status = "PRÉ-APROVADO"
    else:
        status = "APROVADO"

    # 🔥 ATUALIZA SCORE DEPOIS
    db.flush()  # garante que os dados existem

    simulacoes = db.query(Simulacao).filter(Simulacao.cpf == cliente.cpf).all()
    for s in simulacoes:
        s.score = score

    db.commit()

    return resultado, score, status


# =========================
# SIMULAÇÃO
# =========================
@app.post("/simular")
def simular(cliente: Cliente):
    db: Session = SessionLocal()

    try:
        resultado, score, status = processar_simulacao(cliente, db)

        return {
            "nome": cliente.nome,
            "cpf": cliente.cpf,
            "produto": cliente.produto,
            "score": score,
            "status": status,
            "simulacoes": resultado
        }

    except Exception as e:
        print("❌ ERRO NA SIMULAÇÃO:", e)
        return {"erro": str(e)}

    finally:
        db.close()


# =========================
# 🔥 LISTAR LEADS (ARRUMADO)
# =========================
@app.get("/simulacoes")
def listar_simulacoes():
    db: Session = SessionLocal()

    try:
        dados = db.query(Simulacao).all()

        if not dados:
            return {"mensagem": "Nenhuma simulação encontrada"}

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

    except Exception as e:
        print("❌ ERRO AO LISTAR:", e)
        return {"erro": str(e)}

    finally:
        db.close()


# =========================
# CAPTURA DO SITE
# =========================
@app.post("/captura")
def captura(dados: CapturaRequest):

    db: Session = SessionLocal()

    try:
        cliente = Cliente(
            nome=dados.nome,
            cpf=dados.cpf,
            produto=dados.produto
        )

        resultado, score, status = processar_simulacao(cliente, db)

        return {
            "ok": True,
            "mensagem": "Lead capturado com sucesso",
            "cliente": {
                "nome": dados.nome,
                "cpf": dados.cpf,
                "telefone": dados.telefone,
                "email": dados.email
            },
            "score": score,
            "status": status,
            "simulacoes": resultado
        }

    except Exception as e:
        print("❌ ERRO NA CAPTURA:", e)
        return {"erro": str(e)}

    finally:
        db.close()