from fastapi import FastAPI, Query, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
import requests
import os
import json
import time

import firebase_admin
from firebase_admin import credentials, firestore, auth as fb_auth

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
        db_fire.collection("clientes").add({**dados, "criadoEm": firestore.SERVER_TIMESTAMP})
        print("✅ Salvo no Firestore!")
        return True
    except Exception as e:
        print(f"❌ Erro ao salvar Firestore: {e}")
        return False

def cliente_base(nome="", cpf="", telefone="", email="", modalidade="", origem="", obs=""):
    return {
        "nome": nome or "Lead", "cpf": cpf, "whatsapp": telefone, "telefone": telefone,
        "email": email, "modalidade": modalidade, "status": "Lead", "origem": origem,
        "observacoes": obs,
        "rg": "", "dataNascimento": "", "cep": "", "endereco": "", "numero": "",
        "complemento": "", "bairro": "", "cidade": "", "estado": "",
        "banco": "", "agencia": "", "tipoConta": "", "numeroConta": "",
        "valorSolicitado": "", "bancoCrm": "", "dataContato": "",
        "senhaGov": "", "loginGov": "", "senhaSiape": "",
        "matriculaSiape": "", "senhaPrefeitura": "",
        "matriculaPrefeitura": "", "senhaAppBanco": "", "senhaInss": "",
    }

def _so_digitos(s):
    return "".join(ch for ch in str(s or "") if ch.isdigit())

def _chave_telefone(numero):
    d = _so_digitos(numero)
    return d[-8:] if len(d) >= 8 else d

def buscar_ou_criar_cliente(numero: str, nome: str = "", origem: str = "WhatsApp"):
    db_fire = firestore.client()
    chave = _chave_telefone(numero)
    if chave:
        for doc in db_fire.collection("clientes").stream():
            dados = doc.to_dict() or {}
            if (_chave_telefone(dados.get("telefone")) == chave or
                    _chave_telefone(dados.get("whatsapp")) == chave):
                return doc.id, False
    novo = cliente_base(nome=nome or f"WhatsApp {numero}", telefone=numero,
                        origem=origem, obs=f"Contato via {origem}")
    novo["ultimaMensagem"] = ""
    ref = db_fire.collection("clientes").add({
        **novo, "criadoEm": firestore.SERVER_TIMESTAMP,
        "ultimaAtualizacao": firestore.SERVER_TIMESTAMP,
    })
    print(f"🆕 Novo cliente criado: {numero}")
    return ref[1].id, True

def adicionar_mensagem(cliente_id: str, autor: str, texto: str):
    db_fire = firestore.client()
    db_fire.collection("clientes").document(cliente_id).collection("mensagens").add({
        "autor": autor, "texto": texto, "tipo": "texto", "data": firestore.SERVER_TIMESTAMP,
    })
    db_fire.collection("clientes").document(cliente_id).update({
        "ultimaMensagem": texto, "ultimaAtualizacao": firestore.SERVER_TIMESTAMP, "ultimoAutor": autor,
    })

def adicionar_mensagem_midia(cliente_id: str, autor: str, tipo: str, media_id: str, legenda: str = ""):
    db_fire = firestore.client()
    db_fire.collection("clientes").document(cliente_id).collection("mensagens").add({
        "autor": autor, "tipo": tipo, "midiaId": media_id, "texto": legenda, "data": firestore.SERVER_TIMESTAMP,
    })
    db_fire.collection("clientes").document(cliente_id).update({
        "ultimaMensagem": f"[{tipo}]", "ultimaAtualizacao": firestore.SERVER_TIMESTAMP, "ultimoAutor": autor,
    })

def atualizar_cliente_campos(cliente_id: str, campos: dict):
    firestore.client().collection("clientes").document(cliente_id).update(campos)

def fora_horario():
    from datetime import datetime, timezone, timedelta
    agora = datetime.now(timezone.utc) - timedelta(hours=3)
    dia = agora.weekday()
    minutos = agora.hour * 60 + agora.minute
    abre = 8 * 60
    if dia <= 4:
        fecha = 19 * 60
    elif dia == 5:
        fecha = 17 * 60 + 30
    else:
        fecha = 13 * 60
    if minutos < abre or minutos >= fecha:
        return True
    return False
def aviso_fora_horario(cliente_id, numero):
    db_fire = firestore.client()
    doc = db_fire.collection("clientes").document(cliente_id).get()
    d = doc.to_dict() or {}
    if d.get("responsavel"):
        return
    if d.get("avisoForaEnviado"):
        return
    msg = "Recebi os seus dados, obrigada! Sou a Letícia, da Recomece Cred. No momento estamos fora do horário de atendimento, mas já registrei tudo por aqui. Um consultor vai analisar e te retornar no próximo dia útil. Qualquer coisa é só me chamar!"
    enviar_texto_whatsapp(numero, msg)
    adicionar_mensagem(cliente_id, "atendente", msg)
    db_fire.collection("clientes").document(cliente_id).update({"avisoForaEnviado": True})
def deve_saudar(cliente_id, novo):
    try:
        d = firestore.client().collection("clientes").document(cliente_id).get().to_dict() or {}
    except Exception:
        d = {}
    if d.get("responsavel"):
        return False
    if novo:
        return True
    import time as _t
    ts = d.get("ultimaAtualizacao")
    try:
        sec = ts.timestamp() if ts else 0
    except Exception:
        sec = 0
    return (_t.time() - sec) > 6 * 3600

# =========================
# APP
# =========================
app = FastAPI(title="API Recomece Cred")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

CRM_URL    = os.getenv("CRM_URL")
CRM_TOKEN  = os.getenv("CRM_TOKEN")
WHATSAPP_TOKEN  = (os.getenv("WHATSAPP_TOKEN") or "").strip()
PHONE_NUMBER_ID = "1163031670226329"

def enviar_texto_whatsapp(numero: str, texto: str):
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    body = {"messaging_product": "whatsapp", "to": numero, "type": "text", "text": {"body": texto}}
    return requests.post(url, headers=headers, json=body)

def enviar_menu_modalidades(numero: str):
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    body = {
        "messaging_product": "whatsapp",
        "to": numero,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": "Recomece Cred"},
            "body": {"text": "Olá! Eu sou a Letícia, assistente virtual da Recomece Cred. Escolha a modalidade que você deseja e já te encaminho para um consultor:"},
            "footer": {"text": "Toque em Ver opções"},
            "action": {
                "button": "Ver opções",
                "sections": [{
                    "title": "Modalidades",
                    "rows": [
                        {"id": "mod_energia",    "title": "Conta de Energia"},
                        {"id": "mod_clt",        "title": "Crédito CLT"},
                        {"id": "mod_refi_casa",  "title": "Refinanciamento Casa"},
                        {"id": "mod_refi_carro", "title": "Refinanciamento Carro"},
                        {"id": "mod_fgts",       "title": "Saque FGTS"},
                        {"id": "mod_siape",      "title": "SIAPE"},
                        {"id": "mod_prefeitura", "title": "Servidor Prefeitura"},
                        {"id": "mod_bolsa",      "title": "Bolsa Família"},
                        {"id": "mod_solar",      "title": "Placa Solar"},
                    ],
                }],
            },
        },
    }
    return requests.post(url, headers=headers, json=body)

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

class EnvioWhatsApp(BaseModel):
    numero: str
    texto: str

class AlvoDisparo(BaseModel):
    numero: str
    nome: str = "cliente"

class DisparoRemarketing(BaseModel):
    alvos: list[AlvoDisparo]
    template: str = "remarketing_credito"
    idioma: str = "pt_BR"

@app.get("/")
def home():
    return {"mensagem": "API Recomece Cred funcionando 🚀"}

def processar_simulacao(cliente: ClienteModel, db: Session):
    bancos = definir_banco(cliente.produto)
    resultado = []
    for banco in bancos:
        valor = calcular_valor(cliente.cpf, banco)
        nova_simulacao = Simulacao(nome=cliente.nome, cpf=cliente.cpf, telefone=None,
                                   produto=cliente.produto, banco=banco,
                                   valor_aprovado=valor, score="PROCESSANDO")
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

@app.post("/captura")
def captura(dados: CapturaRequest):
    db: Session = SessionLocal()
    try:
        cliente = ClienteModel(nome=dados.nome, cpf=dados.cpf, produto=dados.produto)
        resultado, score, status = processar_simulacao(cliente, db)
        maior = max(resultado, key=lambda x: x["valor"])
        registro = cliente_base(nome=dados.nome, cpf=dados.cpf, telefone=dados.telefone or "",
                                email=dados.email or "", modalidade=dados.produto,
                                origem=dados.origem or "Landing Page",
                                obs=f"Score: {score} | Simulação: {status}")
        registro["banco"] = maior["banco"]
        registro["valorSolicitado"] = str(maior["valor"])
        salvar_no_firestore(registro)
        return {"ok": True, "resultado": {"valor": maior["valor"], "banco": maior["banco"], "status": status}}
    except Exception as e:
        print("❌ ERRO NA CAPTURA:", e)
        return {"erro": str(e)}
    finally:
        db.close()

@app.get("/leads")
def listar_leads():
    db: Session = SessionLocal()
    try:
        leads = db.query(Simulacao).order_by(Simulacao.id.desc()).all()
        return [{"id": l.id, "nome": l.nome, "cpf": l.cpf, "banco": l.banco,
                 "valor": l.valor_aprovado, "score": l.score} for l in leads]
    finally:
        db.close()

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

@app.get("/conversa/{numero}")
def ver_conversa(numero: str):
    db_fire = firestore.client()
    cliente_id, _ = buscar_ou_criar_cliente(numero)
    msgs = db_fire.collection("clientes").document(cliente_id).collection("mensagens").order_by("data").stream()
    return {"cliente_id": cliente_id,
            "mensagens": [{"autor": m.to_dict().get("autor"), "texto": m.to_dict().get("texto")} for m in msgs]}

@app.post("/enviar-whatsapp")
def enviar_whatsapp(dados: EnvioWhatsApp):
    if not WHATSAPP_TOKEN:
        return {"ok": False, "erro": "WHATSAPP_TOKEN não configurado no Render"}
    try:
        resp = enviar_texto_whatsapp(dados.numero, dados.texto)
        resultado = resp.json()
        if resp.ok:
            cliente_id, _ = buscar_ou_criar_cliente(dados.numero)
            adicionar_mensagem(cliente_id, "atendente", dados.texto)
        return {"ok": resp.ok, "resposta": resultado}
    except Exception as e:
        print("❌ ERRO AO ENVIAR WHATSAPP:", e)
        return {"ok": False, "erro": str(e)}

@app.post("/enviar-audio")
async def enviar_audio(numero: str = Form(...), arquivo: UploadFile = File(...)):
    return await _enviar_midia(numero, arquivo)

@app.post("/enviar-arquivo")
async def enviar_arquivo(numero: str = Form(...), arquivo: UploadFile = File(...)):
    return await _enviar_midia(numero, arquivo)

async def _enviar_midia(numero: str, arquivo: UploadFile):
    if not WHATSAPP_TOKEN:
        return {"ok": False, "erro": "WHATSAPP_TOKEN não configurado"}
    try:
        conteudo = await arquivo.read()
        mime = arquivo.content_type or "application/octet-stream"
        nome_arq = arquivo.filename or "arquivo"
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        files = {"file": (nome_arq, conteudo, mime)}
        data = {"messaging_product": "whatsapp"}
        up = requests.post(f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/media",
                           headers=headers, files=files, data=data)
        media_id = up.json().get("id")
        if not media_id:
            return {"ok": False, "erro": up.json()}

        if mime.startswith("image/"):
            tipo = "image"; corpo_midia = {"image": {"id": media_id}}
        elif mime.startswith("audio/"):
            tipo = "audio"; corpo_midia = {"audio": {"id": media_id}}
        elif mime.startswith("video/"):
            tipo = "video"; corpo_midia = {"video": {"id": media_id}}
        else:
            tipo = "document"; corpo_midia = {"document": {"id": media_id, "filename": nome_arq}}

        body = {"messaging_product": "whatsapp", "to": numero, "type": tipo, **corpo_midia}
        resp = requests.post(f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages",
                             headers={**headers, "Content-Type": "application/json"}, json=body)
        if resp.ok:
            cliente_id, _ = buscar_ou_criar_cliente(numero)
            adicionar_mensagem_midia(cliente_id, "atendente", tipo, media_id, nome_arq)
        return {"ok": resp.ok, "resposta": resp.json()}
    except Exception as e:
        print("❌ ERRO MÍDIA:", e)
        return {"ok": False, "erro": str(e)}

@app.get("/midia/{media_id}")
def obter_midia(media_id: str):
    if not WHATSAPP_TOKEN:
        return {"erro": "WHATSAPP_TOKEN não configurado"}
    try:
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        info = requests.get(f"https://graph.facebook.com/v21.0/{media_id}", headers=headers).json()
        media_url = info.get("url")
        mime = info.get("mime_type", "application/octet-stream")
        if not media_url:
            return {"erro": "mídia não encontrada", "info": info}
        r = requests.get(media_url, headers=headers)
        return Response(content=r.content, media_type=mime)
    except Exception as e:
        print("❌ ERRO MÍDIA GET:", e)
        return {"erro": str(e)}

@app.post("/disparar-remarketing")
def disparar_remarketing(dados: DisparoRemarketing):
    if not WHATSAPP_TOKEN:
        return {"ok": False, "erro": "WHATSAPP_TOKEN não configurado no Render"}
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    enviados = 0
    falhas = []
    for alvo in dados.alvos:
        num = _so_digitos(alvo.numero)
        if not num:
            continue
        if not num.startswith("55"):
            num = "55" + num
        body = {"messaging_product": "whatsapp", "to": num, "type": "template",
                "template": {"name": dados.template, "language": {"code": dados.idioma},
                             "components": [{"type": "body",
                                             "parameters": [{"type": "text", "text": alvo.nome or "cliente"}]}]}}
        try:
            resp = requests.post(url, headers=headers, json=body)
            if resp.ok:
                enviados += 1
                try:
                    cliente_id, _ = buscar_ou_criar_cliente(num, alvo.nome)
                    adicionar_mensagem(cliente_id, "atendente", f"📢 Remarketing enviado (modelo: {dados.template})")
                except Exception:
                    pass
            else:
                falhas.append({"numero": num, "erro": resp.json()})
        except Exception as e:
            falhas.append({"numero": num, "erro": str(e)})
        time.sleep(0.3)
    return {"ok": True, "enviados": enviados, "total": len(dados.alvos), "falhas": falhas}


@app.post("/robo-inatividade")
def robo_inatividade():
    import time as _t
    db_fire = firestore.client()
    agora = _t.time()
    LIMITE_FOLLOWUP = 20 * 60
    LIMITE_SEM_CONTATO = 60 * 60
    ativos = ["Lead", "Em Atendimento"]
    feito_followup = 0
    feito_sem_contato = 0
    for doc in db_fire.collection("clientes").stream():
        d = doc.to_dict() or {}
        if d.get("status", "") not in ativos:
            continue
        if d.get("responsavel"):
            continue
        numero = d.get("whatsapp") or d.get("telefone") or ""
        if not numero:
            continue
        autor = d.get("ultimoAutor", "")
        ts = d.get("ultimaAtualizacao")
        try:
            sec = ts.timestamp() if ts else 0
        except Exception:
            sec = 0
        inativo = agora - sec if sec else 0
        if (not d.get("followupEnviado")) and autor in ("atendente", "robo") and inativo > LIMITE_FOLLOWUP:
            msg = "Oi! Aqui é a Letícia da Recomece Cred. Vamos dar andamento ao seu atendimento ou prefere que a gente encerre por aqui? Se quiser continuar, é só me responder."
            enviar_texto_whatsapp(numero, msg)
            adicionar_mensagem(doc.id, "atendente", msg)
            db_fire.collection("clientes").document(doc.id).update({"followupEnviado": True, "followupEm": agora})
            feito_followup += 1
        elif d.get("followupEnviado") and autor in ("atendente", "robo"):
            fem = d.get("followupEm", 0) or 0
            if fem and (agora - fem) > LIMITE_SEM_CONTATO:
                db_fire.collection("clientes").document(doc.id).update({"status": "Sem Contato"})
                feito_sem_contato += 1
    return {"ok": True, "followup": feito_followup, "sem_contato": feito_sem_contato}


@app.post("/robo-inatividade")
def robo_inatividade():
    import time as _t
    db_fire = firestore.client()
    agora = _t.time()
    LIMITE_FOLLOWUP = 20 * 60
    LIMITE_SEM_CONTATO = 60 * 60
    ativos = ["Lead", "Em Atendimento"]
    feito_followup = 0
    feito_sem_contato = 0
    for doc in db_fire.collection("clientes").stream():
        d = doc.to_dict() or {}
        if d.get("status", "") not in ativos:
            continue
        numero = d.get("whatsapp") or d.get("telefone") or ""
        if not numero:
            continue
        autor = d.get("ultimoAutor", "")
        ts = d.get("ultimaAtualizacao")
        try:
            sec = ts.timestamp() if ts else 0
        except Exception:
            sec = 0
        inativo = agora - sec if sec else 0
        if (not d.get("followupEnviado")) and autor in ("atendente", "robo") and inativo > LIMITE_FOLLOWUP:
            msg = "Oi! Aqui é a Letícia da Recomece Cred. Vamos dar andamento ao seu atendimento ou prefere que a gente encerre por aqui? Se quiser continuar, é só me responder."
            enviar_texto_whatsapp(numero, msg)
            adicionar_mensagem(doc.id, "atendente", msg)
            db_fire.collection("clientes").document(doc.id).update({"followupEnviado": True, "followupEm": agora})
            feito_followup += 1
        elif d.get("followupEnviado") and autor in ("atendente", "robo"):
            fem = d.get("followupEm", 0) or 0
            if fem and (agora - fem) > LIMITE_SEM_CONTATO:
                db_fire.collection("clientes").document(doc.id).update({"status": "Sem Contato"})
                feito_sem_contato += 1
    return {"ok": True, "followup": feito_followup, "sem_contato": feito_sem_contato}


@app.post("/robo-inatividade")
def robo_inatividade():
    import time as _t
    db_fire = firestore.client()
    agora = _t.time()
    LIMITE_FOLLOWUP = 20 * 60
    LIMITE_SEM_CONTATO = 60 * 60
    ativos = ["Lead", "Em Atendimento"]
    feito_followup = 0
    feito_sem_contato = 0
    for doc in db_fire.collection("clientes").stream():
        d = doc.to_dict() or {}
        if d.get("status", "") not in ativos:
            continue
        numero = d.get("whatsapp") or d.get("telefone") or ""
        if not numero:
            continue
        autor = d.get("ultimoAutor", "")
        ts = d.get("ultimaAtualizacao")
        try:
            sec = ts.timestamp() if ts else 0
        except Exception:
            sec = 0
        inativo = agora - sec if sec else 0
        if (not d.get("followupEnviado")) and autor in ("atendente", "robo") and inativo > LIMITE_FOLLOWUP:
            msg = "Oi! Aqui é a Letícia da Recomece Cred. Vamos dar andamento ao seu atendimento ou prefere que a gente encerre por aqui? Se quiser continuar, é só me responder."
            enviar_texto_whatsapp(numero, msg)
            adicionar_mensagem(doc.id, "atendente", msg)
            db_fire.collection("clientes").document(doc.id).update({"followupEnviado": True, "followupEm": agora})
            feito_followup += 1
        elif d.get("followupEnviado") and autor in ("atendente", "robo"):
            fem = d.get("followupEm", 0) or 0
            if fem and (agora - fem) > LIMITE_SEM_CONTATO:
                db_fire.collection("clientes").document(doc.id).update({"status": "Sem Contato"})
                feito_sem_contato += 1
    return {"ok": True, "followup": feito_followup, "sem_contato": feito_sem_contato}


class CriarUsuario(BaseModel):
    idToken: str
    email: str
    senha: str
    empresaId: str
    nome: str = ""
    role: str = "funcionario"

@app.post("/criar-usuario")
def criar_usuario(dados: CriarUsuario):
    try:
        decoded = fb_auth.verify_id_token(dados.idToken)
        caller_uid = decoded.get("uid")
        db_fire = firestore.client()
        caller = db_fire.collection("usuarios").document(caller_uid).get()
        caller_data = caller.to_dict() if caller.exists else None
        is_super = (caller_data is None) or (caller_data.get("role") == "superadmin")
        if not is_super:
            return {"ok": False, "erro": "Sem permissao"}
    except Exception as e:
        return {"ok": False, "erro": "Token invalido: " + str(e)}
    try:
        novo_user = fb_auth.create_user(email=dados.email.strip(), password=dados.senha, display_name=(dados.nome or dados.email))
        firestore.client().collection("usuarios").document(novo_user.uid).set({
            "nome": dados.nome or dados.email,
            "email": dados.email.strip(),
            "empresaId": dados.empresaId,
            "role": dados.role,
            "criadoEm": firestore.SERVER_TIMESTAMP,
        })
        return {"ok": True, "uid": novo_user.uid}
    except Exception as e:
        return {"ok": False, "erro": str(e)}

# =========================
# WEBHOOK META
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
            for change in entry.get("changes", []):
                valor = change.get("value", {})

                if "leadgen_id" in valor:
                    lead_id = valor["leadgen_id"]
                    url = f"https://graph.facebook.com/v25.0/{lead_id}"
                    resp = requests.get(url, params={"access_token": CRM_TOKEN})
                    lead_data = resp.json()
                    nome = telefone = email = cpf = ""
                    for campo in lead_data.get("field_data", []):
                        n = campo.get("name", "").lower()
                        v = campo.get("values", [""])[0]
                        if "nome" in n or "name" in n: nome = v
                        elif "telefone" in n or "phone" in n or "whats" in n: telefone = v
                        elif "email" in n: email = v
                        elif "cpf" in n: cpf = v
                    salvar_no_firestore(cliente_base(nome=nome, cpf=cpf, telefone=telefone, email=email,
                                                     origem="Tráfego Pago", obs=f"Formulário Meta | Lead ID: {lead_id}"))

                if valor.get("messaging_product") == "whatsapp" and "messages" in valor:
                    contatos = valor.get("contacts", [])
                    nome_contato = ""
                    wa_numero = ""
                    if contatos:
                        nome_contato = contatos[0].get("profile", {}).get("name", "")
                        wa_numero = contatos[0].get("wa_id", "")
                    for msg in valor.get("messages", []):
                        numero = msg.get("from", "") or wa_numero
                        tipo = msg.get("type", "")
                        cliente_id, novo = buscar_ou_criar_cliente(numero, nome_contato)
                        saudar = deve_saudar(cliente_id, novo)

                        if tipo == "interactive":
                            interativo = msg.get("interactive", {})
                            escolha = ""
                            if interativo.get("type") == "list_reply":
                                escolha = interativo.get("list_reply", {}).get("title", "")
                            elif interativo.get("type") == "button_reply":
                                escolha = interativo.get("button_reply", {}).get("title", "")
                            if escolha and WHATSAPP_TOKEN:
                                adicionar_mensagem(cliente_id, "cliente", f"Modalidade escolhida: {escolha}")
                                try:
                                    atualizar_cliente_campos(cliente_id, {"modalidade": escolha, "status": "Em Atendimento"})
                                except Exception as e:
                                    print("erro modalidade:", e)
                                confirma = f"Perfeito! Você escolheu *{escolha}*.\n\nPara adiantar o seu atendimento, me envie por favor:\n\n- Nome completo\n- Data de nascimento\n- CEP\n- CPF\n\nEm instantes um de nossos consultores vai te atender.\n\nLetícia - Recomece Cred"
                                enviar_texto_whatsapp(numero, confirma)
                                adicionar_mensagem(cliente_id, "atendente", confirma)
                            continue

                        if tipo == "text":
                            texto = msg.get("text", {}).get("body", "")
                            adicionar_mensagem(cliente_id, "cliente", texto)
                            try:
                                atualizar_cliente_campos(cliente_id, {"followupEnviado": False})
                            except Exception:
                                pass
                            if (not novo) and WHATSAPP_TOKEN and fora_horario():
                                aviso_fora_horario(cliente_id, numero)
                        elif tipo in ("audio", "voice", "image", "video", "document", "sticker"):
                            media = msg.get(tipo, {}) or {}
                            media_id = media.get("id", "")
                            legenda = media.get("caption", "")
                            tipo_norm = "audio" if tipo in ("audio", "voice") else tipo
                            adicionar_mensagem_midia(cliente_id, "cliente", tipo_norm, media_id, legenda)
                        else:
                            adicionar_mensagem(cliente_id, "cliente", f"[mensagem do tipo {tipo}]")

                        if saudar and WHATSAPP_TOKEN:
                            try:
                                enviar_menu_modalidades(numero)
                                adicionar_mensagem(cliente_id, "atendente", "🤖 Menu de modalidades enviado")
                            except Exception as e:
                                print("❌ Erro menu:", e)

            for msg_event in entry.get("messaging", []):
                sender_id = msg_event.get("sender", {}).get("id", "")
                texto = msg_event.get("message", {}).get("text", "")
                if sender_id and texto:
                    origem = "Instagram" if objeto == "instagram" else "Facebook"
                    salvar_no_firestore(cliente_base(nome=f"Contato {origem}", origem=origem,
                                                     obs=f"DM {origem} | ID: {sender_id} | Msg: {texto}"))
        return {"status": "ok"}
    except Exception as erro:
        print("❌ ERRO WEBHOOK:", erro)
        return {"status": "erro", "mensagem": str(erro)}
