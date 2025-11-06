"""#!/usr/bin/env python3
"""

import re
import time
import json
import logging
import argparse
import concurrent.futures
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# CONFIG
MAX_WORKERS = 8
REQUEST_TIMEOUT = 10
MAX_SEARCH_RESULTS = 20
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

# Personal data (default values filled from user input)
CPF = '41699024839'
CNPJ = '56046597000160'
ADDRESSES = ['r tamandare 1029', 'r tamandare 1029 ap 72']
NAMES = ['pedro h dos santos lima', 'pedro henrique dos santos lima']

# OUTPUT PATHS
OUT_DIR = Path('apagardados_output')
OUT_DIR.mkdir(exist_ok=True)
RESULTS_FILE = OUT_DIR / 'results.json'
TEMPLATES_DIR = OUT_DIR / 'templates'
TEMPLATES_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger('webscraper_aprimorado')

# Utility: compile regexes for CPF/CNPJ (with/without formatting)
def build_patterns(cpf, cnpj, names, addresses):
    patterns = []
    # CPF pattern variants
    cpf_plain = re.sub(r'\D', '', cpf)
    cpf_fmt = r"\b" + re.sub(r'\.', r'\\.', re.sub(r'-', r'\\-', cpf)) + r"\b" if '.' in cpf or '-' in cpf else None
    if cpf_plain:
        patterns.append(re.compile(re.escape(cpf_plain)))
        # formatted variations: 000.000.000-00
        patterns.append(re.compile(r"\b" + r"{}".format(cpf_plain[:3]) + r"[\.\-\s]?" + r"{}".format(cpf_plain[3:6]) + r"[\.\-\s]?" + r"{}".format(cpf_plain[6:9]) + r"[\.\-\s]?" + r"{}".format(cpf_plain[9:]) + r"\b"))
    if cnpj:
        cnpj_plain = re.sub(r'\D', '', cnpj)
        patterns.append(re.compile(re.escape(cnpj_plain)))
        # formatted CNPJ: 00.000.000/0000-00
        patterns.append(re.compile(r"\b" + r"{}".format(cnpj_plain[:2]) + r"[\.\-\/]?" + r"{}".format(cnpj_plain[2:5]) + r"[\.\-\/]?" + r"{}".format(cnpj_plain[5:8]) + r"[\.\-\/]?" + r"{}".format(cnpj_plain[8:12]) + r"[\.\-\s]?" + r"{}".format(cnpj_plain[12:]) + r"\b"))
    # names and addresses (case-insensitive)
    for n in names:
        if n.strip():
            patterns.append(re.compile(re.escape(n.strip()), re.IGNORECASE))
    for a in addresses:
        if a.strip():
            patterns.append(re.compile(re.escape(a.strip()), re.IGNORECASE))
    return patterns

# Build combined search queries to reduce false positives
def build_queries(cpf, cnpj, names, addresses):
    queries = set()
    # single-term queries
    queries.add(cpf)
    queries.add(cnpj)
    for n in names:
        queries.add(f'"{n}"')
    for a in addresses:
        queries.add(f'"{a}"')
    # combined queries: name + cpf/cnpj/address
    for n in names:
        queries.add(f'"{n}" "{cpf}"')
        queries.add(f'"{n}" "{cnpj}"')
        for a in addresses:
            queries.add(f'"{n}" "{a}"')
    # address + cpf/cnpj
    for a in addresses:
        queries.add(f'"{a}" "{cpf}"')
        queries.add(f'"{a}" "{cnpj}"')
    return list(queries)

# Google search using the 'googlesearch' library if available, else fallback to simple Bing scrape (no API key)
try:
    from googlesearch import search as google_search
    def search_engine(query, num_results=MAX_SEARCH_RESULTS):
        results = []
        try:
            for url in google_search(query, num_results=num_results, lang='pt'):
                results.append(url)
        except Exception as e:
            logger.warning(f'googlesearch failed for "{query}": {e}')
        return results
except Exception:
    # Fallback naive Bing scraping via 'https://www.bing.com/search?q=' (may be blocked)
    def search_engine(query, num_results=MAX_SEARCH_RESULTS):
        logger.info('googlesearch not installed, using Bing fallback (may be unreliable)')
        qs = requests.utils.requote_uri(query)
        url = f'https://www.bing.com/search?q={qs}'
        headers = {'User-Agent': USER_AGENT}
        try:
            r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            soup = BeautifulSoup(r.text, 'html.parser')
            links = []
            for a in soup.select('li.b_algo h2 a'):
                href = a.get('href')
                if href:
                    links.append(href)
            return links[:num_results]
        except Exception as e:
            logger.warning(f'Bing fallback search failed: {e}')
            return []

# Fetch a URL with sensible headers and timeout
def fetch_url(url):
    headers = {'User-Agent': USER_AGENT}
    try:
        r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.text
    except Exception as e:
        logger.debug(f'Fetch failed for {url}: {e}')
        return None

# Analyze page content for patterns and try to find contact info
def analyze_page(url, html, patterns):
    soup = BeautifulSoup(html, 'html.parser')
    text = soup.get_text(separator=' ')
    found = []
    for p in patterns:
        if p.search(text):
            found.append(p.pattern)
    contact_emails = set()
    # find mailto links
    for a in soup.select('a[href^=mailto]'):
        href = a.get('href')
        try:
            email = href.split(':', 1)[1].split('?')[0]
            contact_emails.add(email)
        except Exception:
            pass
    # search for obvious email patterns in page
    email_regex = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
    for m in email_regex.findall(text):
        contact_emails.add(m)
    # try to find contact page links
    contact_urls = set()
    for a in soup.find_all('a', href=True):
        href = a['href']
        if re.search(r'contato|contact|fale[-_ ]?conosco|support|suporte', href, re.IGNORECASE):
            contact_urls.add(urljoin(url, href))
    return {'found_patterns': list(set(found)), 'emails': list(contact_emails), 'contact_pages': list(contact_urls)}

# Safe filename
def safe_filename(url):
    p = urlparse(url)
    name = p.netloc + p.path
    name = re.sub(r'[^a-zA-Z0-9\-_.]', '_', name)
    if not name:
        name = 'site'
    return name[:200]

# Generate removal template (LGPD / polite request)
def generate_template(url, found_items, contact_emails=None):
    subject = f'Requisição de remoção de dados pessoais - LGPD'
    body = (
        f'Prezado(a),\n\n'
        f'Estou entrando em contato para solicitar a remoção imediata dos meus dados pessoais que estão publicados na página: {url}\n\n'
        f'Os dados expostos identificados são:\n'
    )
    for item in found_items:
        body += f' - {item}\n'
    body += (
        '\nDe acordo com a Lei Geral de Proteção de Dados (Lei nº 13.709/2018), solicito que os dados sejam removidos e que me confirmem a remoção por escrito. '
        'Caso não seja possível a remoção por alguma razão legal, peço que informem o fundamento jurídico e as medidas tomadas para minimizar o problema.\n\n'
        'Atenciosamente,\n'
        'Pedro Henrique dos Santos Lima\n'
    )
    return {'subject': subject, 'body': body, 'emails': contact_emails or []}

# Main run function
def run(auto_submit=False, max_workers=MAX_WORKERS, max_results=MAX_SEARCH_RESULTS):
    logger.info('Preparando padrões de busca...')
    patterns = build_patterns(CPF, CNPJ, NAMES, ADDRESSES)
    queries = build_queries(CPF, CNPJ, NAMES, ADDRESSES)
    logger.info(f'Total de queries geradas: {len(queries)}')

    # collect URLs (avoid duplicates)
    urls = set()
    for q in queries:
        logger.info(f'Buscando: {q}')
        try:
            results = search_engine(q, num_results=max_results)
            for u in results:
                urls.add(u)
        except Exception as e:
            logger.warning(f'Busca falhou para "{q}": {e}')
        time.sleep(1)  # politeness

    logger.info(f'URLs coletadas: {len(urls)}')

    findings = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as exc:
        future_to_url = {exc.submit(fetch_url, url): url for url in urls}
        for fut in concurrent.futures.as_completed(future_to_url):
            url = future_to_url[fut]
            html = fut.result()
            if not html:
                continue
            analysis = analyze_page(url, html, patterns)
            if analysis['found_patterns']:
                logger.info(f'DADOS ENCONTRADOS em {url}: {analysis['found_patterns']}')
                # generate template
                template = generate_template(url, analysis['found_patterns'], contact_emails=analysis['emails'])
                fname = safe_filename(url) + '.txt'
                path = TEMPLATES_DIR / fname
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(f"Subject: {template['subject']}\n\n")
                    f.write(template['body'])
                    if template['emails']:
                        f.write('\n--\nEmails encontrados: ' + ', '.join(template['emails']))
                findings.append({'url': url, 'patterns': analysis['found_patterns'], 'emails': analysis['emails'], 'contact_pages': analysis['contact_pages'], 'template_file': str(path)})

    # save results
    with open(RESULTS_FILE, 'w', encoding='utf-8') as f:
        json.dump({'generated_at': time.time(), 'findings': findings}, f, indent=2, ensure_ascii=False)

    logger.info(f'Execução finalizada. {len(findings)} páginas com dados encontrados.')
    logger.info(f'Resultados salvos em: {RESULTS_FILE}')
    logger.info(f'Modelos de solicitação salvos em: {TEMPLATES_DIR}')
    if findings:
        logger.info('Para solicitar remoção no Google, use a ferramenta: https://support.google.com/websearch/troubleshooter/9685456')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Webscraper aprimorado para buscar e ajudar a remover dados pessoais')
    parser.add_argument('--auto-submit', action='store_true', help='(NÃO RECOMENDADO) tenta submeter formulários de contato automaticamente quando encontrados')
    parser.add_argument('--workers', type=int, default=MAX_WORKERS, help='Número de threads para fetch')
    parser.add_argument('--results', type=int, default=MAX_SEARCH_RESULTS, help='Resultados por query')
    args = parser.parse_args()
    run(auto_submit=args.auto_submit, max_workers=args.workers, max_results=args.results)