def definir_banco(produto: str):

    produto = produto.upper()

    if produto == "FGTS":
        return ["BANCO V8", "BANCO FACTA"]

    elif produto == "INSS":
        return ["BANCO FACTA", "ICRED", "360CONSIG"]

    elif produto == "CLT":
        return ["C6 BANK", "BANCO FACTA", "BANCO V8"]

    elif produto == "ENERGIA":
        return ["CREFAZ"]

    else:
        return ["BANCO FACTA"]


def calcular_valor(cpf: str, banco: str):

    if banco == "BANCO V8":
        return 10000

    elif banco == "BANCO FACTA":
        return 8000

    elif banco == "C6 BANK":
        return 15000

    elif banco == "ICRED":
        return 5000

    elif banco == "360CONSIG":
        return 7000

    elif banco == "CREFAZ":
        return 3000

    else:
        return 2000


def calcular_score(cpf: str):

    ultimo = int(cpf[-1])

    if ultimo <= 3:
        return "BAIXO"

    elif ultimo <= 6:
        return "MÉDIO"

    else:
        return "ALTO"