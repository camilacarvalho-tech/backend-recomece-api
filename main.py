from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
import requests

from database import engine, SessionLocal, Base
from models import Simulacao
from services import calcular_valor, definir_banco, calcular_score

# =========================
# CRIAR TABELAS
# =========================
#Base.metadata.create_all(bind=engine)

app = FastAPI()

# =========================
# CORS (LIBERA SEU SITE)
# =========================
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://recomececredoficial.com.br",
        "https://www.recomececredoficial.com.br"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# MODELOS
# =========================
class Cliente(BaseModel):
    nome: str = "Cliente"
    cpf: str
    produto: str = "FGTS"


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
# FUNÇÃO INTERNA
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

    db.flush()

    simulacoes = db.query(Simulacao).filter(Simulacao.cpf == cliente.cpf).all()
    for s in simulacoes:
        s.score = score

    db.commit()

    return resultado, score, status


# =========================
# 🔥 NOVO ENDPOINT (IMPORTANTE)
# =========================
@app.post("/consulta")
def consulta(dados: dict):
    db: Session = SessionLocal()

    try:
        cpf = dados.get("cpf")

        cliente = Cliente(
            cpf=cpf
        )

        resultado, score, status = processar_simulacao(cliente, db)

        # pega o maior valor
        maior = max(resultado, key=lambda x: x["valor"])

        return {
            "valor": maior["valor"],
            "banco": maior["banco"],
            "status": status
        }

    except Exception as e:
        print("❌ ERRO NA CONSULTA:", e)
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

        # 🔥 ENVIA PARA CRM (trocar depois)
        try:
            requests.post("URL_DO_SEU_CRM", json={
                "nome": cliente.nome,
                "cpf": cliente.cpf,
                "produto": cliente.produto,
                "score": score,
                "status": status
            })
        except:
            pass

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