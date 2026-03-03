def definir_banco(produto: str):
    produto = produto.upper()

    if produto == "FGTS":
        return "BANCO V8"

    elif produto == "INSS":
        return "BANCO FACTA"

    elif produto == "ICRED":
        return "ICRED"

    else:
        return "BANCO FACTA"


def calcular_valor(cpf: str, banco: str):

    if banco == "BANCO V8":
        return 10000

    elif banco == "BANCO FACTA":
        return 8000

    elif banco == "BANCO ITAU":
        return 20000

    elif banco == "ICRED":
        return 5000

    else:
        return 3000


def calcular_score(cpf: str):
    ultimo_digito = int(cpf[-1])

    if ultimo_digito <= 3:
        return "BAIXO"

    elif ultimo_digito <= 6:
        return "MÉDIO"

    else:
        return "ALTO"