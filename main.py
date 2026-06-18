from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
import requests
import os

from database import engine, SessionLocal, Base
from models import Simulacao, Mensagem
Base.metadata.create_all(bind=engine)
from services import calcular_valor, definir_banco, calcular_score

# =========================
# APP
# =========================
app = FastAPI()

# =========================
# CORS (LIBERA SEU SITE)
# =========================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# =========================
# CONFIG CRM (ENV)
# =========================
CRM_URL = os.getenv("CRM_URL")
CRM_TOKEN = os.getenv("CRM_TOKEN")


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
    origem: str | None = "site"

# =========================
# TESTE
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
# CONSULTA
# =========================
@app.post("/consulta")
def consulta(dados: dict):

    db: Session = SessionLocal()

    try:
        cpf = dados.get("cpf")

        if not cpf:
            return {"erro": "CPF não informado"}

        cliente = Cliente(cpf=cpf)

        resultado, score, status = processar_simulacao(cliente, db)

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
# CAPTURA + ENVIO CRM 🔥
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

        maior = max(resultado, key=lambda x: x["valor"])

        if CRM_URL:

            headers = {
                "Content-Type": "application/json"
            }

            if CRM_TOKEN:
                headers["Authorization"] = f"Bearer {CRM_TOKEN}"

            payload = {
                "nome": dados.nome,
                "cpf": dados.cpf,
                "telefone": dados.telefone,
                "email": dados.email,
                "produto": dados.produto,
                "banco": maior["banco"],
                "valor": maior["valor"],
                "status": status,
                "origem": dados.origem
            }

            try:
                requests.post(
                    CRM_URL,
                    json=payload,
                    headers=headers,
                    timeout=10
                )

            except Exception as crm_error:
                print("❌ ERRO CRM:", crm_error)

        return {
            "ok": True,
            "resultado": {
                "valor": maior["valor"],
                "banco": maior["banco"],
                "status": status
            }
        }

    except Exception as e:
        print("❌ ERRO NA CAPTURA:", e)
        return {"erro": str(e)}

    finally:
        db.close()

# =========================
# 🔥 LISTAR LEADS
# =========================
@app.get("/leads")
def listar_leads():

    db: Session = SessionLocal()

    try:

        leads = (
            db.query(Simulacao)
            .order_by(Simulacao.id.desc())
            .all()
        )

        return [
            {
                "id": l.id,
                "nome": l.nome,
                "cpf": l.cpf,
                "banco": l.banco,
                "valor": l.valor_aprovado,
                "score": l.score
            }
            for l in leads
        ]

    finally:
        db.close()


# =========================
# MODELO MENSAGEM
# =========================
class MensagemRequest(BaseModel):
    cpf: str
    autor: str
    texto: str


# =========================
# SALVAR MENSAGEM
# =========================
@app.post("/mensagens")
def salvar_mensagem(dados: MensagemRequest):

    db: Session = SessionLocal()

    try:

        nova = Mensagem(
            cpf=dados.cpf,
            autor=dados.autor,
            texto=dados.texto
        )

        db.add(nova)
        db.commit()

        return {"ok": True}

    finally:
        db.close()


# =========================
# LISTAR MENSAGENS
# =========================
@app.get("/mensagens/{cpf}")
def listar_mensagens(cpf: str):

    db: Session = SessionLocal()

    try:

        mensagens = (
            db.query(Mensagem)
            .filter(Mensagem.cpf == cpf)
            .order_by(Mensagem.id.asc())
            .all()
        )

        return [
            {
                "id": m.id,
                "autor": m.autor,
                "texto": m.texto
            }
            for m in mensagens
        ]

    finally:
        db.close()
        # =========================
# WEBHOOK META
# =========================

VERIFY_TOKEN = "recomececred123"


@app.get("/webhook")
def verificar_webhook(
    hub_mode: str = None,
    hub_verify_token: str = None,
    hub_challenge: str = None
):

    if hub_verify_token == VERIFY_TOKEN:
        return int(hub_challenge)

    return {"erro": "Token inválido"}


@app.post("/webhook")
async def receber_webhook(payload: dict):

    print("🔥 WEBHOOK RECEBIDO")
    print(payload)

    try:
        lead_id = payload["entry"][0]["changes"][0]["value"]["leadgen_id"]

        print("✅ LEAD ID:", lead_id)

        return {
            "status": "ok",
            "lead_id": lead_id
        }

    except Exception as erro:
        print("❌ ERRO:", erro)

        return {
            "status": "erro",
            "mensagem": str(erro)
        }