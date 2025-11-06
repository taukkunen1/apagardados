import requests
from googlesearch import search
from bs4 import BeautifulSoup
import re

# Definindo as variáveis de busca
cpf = '41699024839'
cnpj = '56046597000160'
enderecos = ['r tamandare 1029', 'r tamandare 1029 ap 72']
nomes = ['pedro h dos santos lima', 'pedro henrique dos santos lima']

# Função para buscar informações no Google
def busca_google(termo):
    urls = []
    # Realiza uma busca no Google
    for url in search(termo, num_results=10):
        urls.append(url)
    return urls

# Função para verificar se os termos aparecem nas páginas
def verifica_termos(url, termos):
    try:
        # Faz uma requisição GET para a URL
        resposta = requests.get(url)
        # Analisa o conteúdo HTML com BeautifulSoup
        soup = BeautifulSoup(resposta.text, 'html.parser')
        conteudo = soup.get_text()
        resultados = {}
        # Verifica cada termo no conteúdo
        for termo in termos:
            # Usa regex para buscar o termo
            if re.search(re.escape(termo), conteudo):
                resultados[termo] = True
            else:
                resultados[termo] = False
        return resultados
    except Exception as e:
        print(f"Erro ao acessar a URL {url}: {e}")
        return None

# Executando as buscas
termos_busca = [cpf, cnpj] + enderecos + nomes
urls_encontradas = []
for termo in termos_busca:
    print(f"Buscando por: {termo}")
    urls = busca_google(termo)
    urls_encontradas.extend(urls)

# Analisando os URLs encontrados
for url in set(urls_encontradas):  # Usando set para evitar duplicatas
    resultados = verifica_termos(url, termos_busca)
    if resultados:
        print(f"Resultados para {url}:")
        for termo, encontrado in resultados.items():
            print(f" - {termo}: {'Encontrado' if encontrado else 'Não encontrado'}")
