from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
import requests
import os
import json

# Firebase Admin
import firebase_admin
from firebase_admin import credentials, firestore

from database import engine, SessionLocal, Base
from models import Simulacao, Mensagem
Base.metadata.create_all(bind=engine)
from services import calcular_valor, definir_banco, calcular_score

# =========================
# FIREBASE INIT
# =========================
FIREBASE_KEY_JSON = os.getenv("FIREBASE_KEY_JSON")

if FIREBASE_KEY_JSON and not firebase_admin._apps:
    try:
        cred_dict = json.loads(FIREBASE_KEY_JSON)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        print("✅ Firebase conectado!")
    except Exception as e:
        print(f"❌ Erro Firebase: {e}")

def salvar_no_firestore(dados: dict):
    """Salva um lead/cliente na coleção 'clientes' do Firestore."""
    try:
        db_fire = firestore.client()
        db_fire.collection("clientes").add({
            **dados,
            "criadoEm": firestore.SERVER_TIMESTAMP,
        })
        print("✅ Salvo no Firestore!")
        return True
    except Exception as e:
        print(f"❌ Erro ao salvar Firestore: {e}")
        return False

# =========================
# APP
# =========================
app = FastAPI(title="API Recomece Cred")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# CONFIG (ENV)
# =========================
CRM_URL    = os.getenv("CRM_URL")
CRM_TOKEN  = os.getenv("CRM_TOKEN")

# =========================
# MODELOS
# =========================
class ClienteModel(BaseModel):
    nome: str = "Cliente"
    cpf: str
    produto: str = "FGTS"

class CapturaRequest(BaseModel):
    nome: str
    cpf: str
    telefone: str | None = None
    email: str | None = None
    produto: str = "FGTS"
    origem: str | None = "Landing Page"

# =========================
# TESTE
# =========================
@app.get("/")
def home():
    return {"mensagem": "API Recomece Cred funcionando 🚀"}

# =========================
# FUNÇÃO INTERNA
# =========================
def processar_simulacao(cliente: ClienteModel, db: Session):
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
        resultado.append({"banco": banco, "valor": valor})

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
        cliente = ClienteModel(cpf=cpf)
        resultado, score, status = processar_simulacao(cliente, db)
        maior = max(resultado, key=lambda x: x["valor"])
        return {"valor": maior["valor"], "banco": maior["banco"], "status": status}
    except Exception as e:
        print("❌ ERRO NA CONSULTA:", e)
        return {"erro": str(e)}
    finally:
        db.close()

# =========================
# CAPTURA — Landing Page
# =========================
@app.post("/captura")
def captura(dados: CapturaRequest):
    db: Session = SessionLocal()
    try:
        cliente = ClienteModel(
            nome=dados.nome,
            cpf=dados.cpf,
            produto=dados.produto
        )
        resultado, score, status = processar_simulacao(cliente, db)
        maior = max(resultado, key=lambda x: x["valor"])

        # Salva no Firestore
        salvar_no_firestore({
            "nome":      dados.nome,
            "cpf":       dados.cpf,
            "whatsapp":  dados.telefone or "",
            "telefone":  dados.telefone or "",
            "email":     dados.email or "",
            "modalidade":dados.produto,
            "status":    "Lead",
            "origem":    dados.origem or "Landing Page",
            "banco":     maior["banco"],
            "valorSolicitado": str(maior["valor"]),
            "rg": "", "cep": "", "endereco": "", "numero": "",
            "complemento": "", "bairro": "", "cidade": "", "estado": "",
            "agencia": "", "tipoConta": "", "numeroConta": "",
            "senhaGov": "", "loginGov": "", "senhaSiape": "",
            "matriculaSiape": "", "senhaPrefeitura": "",
            "matriculaPrefeitura": "", "senhaAppBanco": "", "senhaInss": "",
            "observacoes": f"Score: {score} | Status simulação: {status}",
            "dataContato": "",
            "bancoCrm": "",
        })

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
# LISTAR LEADS (SQLite)
# =========================
@app.get("/leads")
def listar_leads():
    db: Session = SessionLocal()
    try:
        leads = db.query(Simulacao).order_by(Simulacao.id.desc()).all()
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
# MENSAGENS
# =========================
class MensagemRequest(BaseModel):
    cpf: str
    autor: str
    texto: str

@app.post("/mensagens")
def salvar_mensagem(dados: MensagemRequest):
    db: Session = SessionLocal()
    try:
        nova = Mensagem(cpf=dados.cpf, autor=dados.autor, texto=dados.texto)
        db.add(nova)
        db.commit()
        return {"ok": True}
    finally:
        db.close()

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
        return [{"id": m.id, "autor": m.autor, "texto": m.texto} for m in mensagens]
    finally:
        db.close()

# =========================
# WEBHOOK META 🔥
# =========================
VERIFY_TOKEN = "recomece123"

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

        # Busca dados do lead no Meta
        facebook_token = CRM_TOKEN
        url = f"https://graph.facebook.com/v25.0/{lead_id}"
        response = requests.get(url, params={"access_token": facebook_token})
        lead_data = response.json()
        print("📦 DADOS META:", lead_data)

        # Extrai campos do formulário
        nome     = ""
        telefone = ""
        email    = ""
        cpf      = ""

        field_data = lead_data.get("field_data", [])
        for campo in field_data:
            nome_campo = campo.get("name", "").lower()
            valor      = campo.get("values", [""])[0]
            if "nome" in nome_campo or "name" in nome_campo:
                nome = valor
            elif "telefone" in nome_campo or "phone" in nome_campo or "whatsapp" in nome_campo:
                telefone = valor
            elif "email" in nome_campo:
                email = valor
            elif "cpf" in nome_campo:
                cpf = valor

        # Define origem pelo ad
        origem = "Facebook"
        ad_name = lead_data.get("ad_name", "").lower()
        if "instagram" in ad_name:
            origem = "Instagram"
        elif "google" in ad_name:
            origem = "Google ADS"

        # Salva no Firestore
        salvar_no_firestore({
            "nome":      nome or "Lead Meta",
            "cpf":       cpf,
            "whatsapp":  telefone,
            "telefone":  telefone,
            "email":     email,
            "modalidade":"",
            "status":    "Lead",
            "origem":    origem,
            "observacoes": f"Lead ID Meta: {lead_id}",
            "rg": "", "cep": "", "endereco": "", "numero": "",
            "complemento": "", "bairro": "", "cidade": "", "estado": "",
            "banco": "", "agencia": "", "tipoConta": "", "numeroConta": "",
            "valorSolicitado": "", "bancoCrm": "", "dataContato": "",
            "senhaGov": "", "loginGov": "", "senhaSiape": "",
            "matriculaSiape": "", "senhaPrefeitura": "",
            "matriculaPrefeitura": "", "senhaAppBanco": "", "senhaInss": "",
        })

        return {"status": "ok", "lead_id": lead_id, "nome": nome}

    except Exception as erro:
        print("❌ ERRO WEBHOOK:", erro)
        return {"status": "erro", "mensagem": str(erro)}
