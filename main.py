from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime
import requests
import os
import json

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

# Salva mensagem do WhatsApp SEM duplicar o cliente (agrupa pelo número)
def salvar_ou_atualizar_whatsapp(numero, nome, texto):
    try:
        db_fire = firestore.client()
        col = db_fire.collection("clientes")
        existentes = col.where("whatsapp", "==", numero).limit(1).get()

        nova_msg = {
            "autor": "cliente",
            "texto": texto,
            "data": datetime.utcnow().isoformat(),
        }

        if existentes:
            doc = existentes[0]
            doc.reference.update({
                "mensagens": firestore.ArrayUnion([nova_msg]),
                "ultimaMensagem": texto,
                "atualizadoEm": firestore.SERVER_TIMESTAMP,
            })
            print(f"♻️ Conversa atualizada: {numero}")
            return False
        else:
            dados = cliente_base(
                nome=nome or f"WhatsApp {numero}",
                telefone=numero,
                origem="WhatsApp",
                obs=f"Lead via WhatsApp | Número: {numero}",
            )
            dados["mensagens"] = [nova_msg]
            dados["ultimaMensagem"] = texto
            dados["criadoEm"] = firestore.SERVER_TIMESTAMP
            dados["atualizadoEm"] = firestore.SERVER_TIMESTAMP
            col.add(dados)
            print(f"🆕 Novo cliente WhatsApp: {numero}")
            return True
    except Exception as e:
        print(f"❌ Erro salvar/atualizar WhatsApp: {e}")
        return False

# Modelo base de cliente vazio (todos os campos do CRM)
def cliente_base(nome="", cpf="", telefone="", email="", modalidade="", origem="", obs=""):
    return {
        "nome": nome or "Lead",
        "cpf": cpf,
        "whatsapp": telefone,
        "telefone": telefone,
        "email": email,
        "modalidade": modalidade,
        "status": "Lead",
        "origem": origem,
        "observacoes": obs,
        "rg": "", "cep": "", "endereco": "", "numero": "",
        "complemento": "", "bairro": "", "cidade": "", "estado": "",
        "banco": "", "agencia": "", "tipoConta": "", "numeroConta": "",
        "valorSolicitado": "", "bancoCrm": "", "dataContato": "",
        "senhaGov": "", "loginGov": "", "senhaSiape": "",
        "matriculaSiape": "", "senhaPrefeitura": "",
        "matriculaPrefeitura": "", "senhaAppBanco": "", "senhaInss": "",
    }

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
            nome=cliente.nome, cpf=cliente.cpf, telefone=None,
            produto=cliente.produto, banco=banco,
            valor_aprovado=valor, score="PROCESSANDO"
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
        cliente = ClienteModel(nome=dados.nome, cpf=dados.cpf, produto=dados.produto)
        resultado, score, status = processar_simulacao(cliente, db)
        maior = max(resultado, key=lambda x: x["valor"])
        registro = cliente_base(
            nome=dados.nome, cpf=dados.cpf, telefone=dados.telefone or "",
            email=dados.email or "", modalidade=dados.produto,
            origem=dados.origem or "Landing Page",
            obs=f"Score: {score} | Simulação: {status}"
        )
        registro["banco"] = maior["banco"]
        registro["valorSolicitado"] = str(maior["valor"])
        salvar_no_firestore(registro)
        return {"ok": True, "resultado": {"valor": maior["valor"], "banco": maior["banco"], "status": status}}
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
        return [{"id": l.id, "nome": l.nome, "cpf": l.cpf, "banco": l.banco,
                 "valor": l.valor_aprovado, "score": l.score} for l in leads]
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
        mensagens = db.query(Mensagem).filter(Mensagem.cpf == cpf).order_by(Mensagem.id.asc()).all()
        return [{"id": m.id, "autor": m.autor, "texto": m.texto} for m in mensagens]
    finally:
        db.close()

# =========================
# WEBHOOK META — Formulário + WhatsApp + Messenger + Instagram
# =========================
VERIFY_TOKEN = "recomece123"

@app.get("/webhook")
def verificar_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge")
):
    if hub_verify_token == VERIFY_TOKEN:
        return PlainTextResponse(content=hub_challenge)
    return {"erro": "Token invalido"}

@app.post("/webhook")
async def receber_webhook(payload: dict):
    print("🔥 WEBHOOK RECEBIDO")
    print(payload)
    try:
        objeto = payload.get("object", "")

        for entry in payload.get("entry", []):

            # ===== CHANGES: Formulário (Lead Ads) + WhatsApp =====
            for change in entry.get("changes", []):
                valor = change.get("value", {})

                # ----- FORMULÁRIO (Lead Ads) -----
                if "leadgen_id" in valor:
                    lead_id = valor["leadgen_id"]
                    url = f"https://graph.facebook.com/v25.0/{lead_id}"
                    resp = requests.get(url, params={"access_token": CRM_TOKEN})
                    lead_data = resp.json()
                    print("📦 FORM META:", lead_data)

                    nome = telefone = email = cpf = ""
                    for campo in lead_data.get("field_data", []):
                        n = campo.get("name", "").lower()
                        v = campo.get("values", [""])[0]
                        if "nome" in n or "name" in n: nome = v
                        elif "telefone" in n or "phone" in n or "whats" in n: telefone = v
                        elif "email" in n: email = v
                        elif "cpf" in n: cpf = v

                    salvar_no_firestore(cliente_base(
                        nome=nome, cpf=cpf, telefone=telefone, email=email,
                        origem="Tráfego Pago", obs=f"Formulário Meta | Lead ID: {lead_id}"
                    ))

                # ----- WHATSAPP (Cloud API) -----
                if valor.get("messaging_product") == "whatsapp" and "messages" in valor:
                    contatos = valor.get("contacts", [])
                    nome_contato = ""
                    wa_numero = ""
                    if contatos:
                        nome_contato = contatos[0].get("profile", {}).get("name", "")
                        wa_numero = contatos[0].get("wa_id", "")

                    for msg in valor.get("messages", []):
                        numero = msg.get("from", "") or wa_numero
                        tipo = ms
