import requests
from datetime import datetime, timedelta
import os
import sys
import re

# Configurações
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
CLIENTES_DB_ID = "2ef5027d49aa8023bd94f91238ae95d2"
PARCELAS_DB_ID = "2ef5027d49aa80ffb35fd4a655b776f7"
RESUMO_DB_ID = "2ef5027d49aa8019afbcdbba5f3cfa33"

headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

# Mapeamento de meses (português)
MESES_PT = {
    1: ["janeiro", "jan"],
    2: ["fevereiro", "fev"],
    3: ["março", "mar", "marco"],
    4: ["abril", "abr"],
    5: ["maio", "mai"],
    6: ["junho", "jun"],
    7: ["julho", "jul"],
    8: ["agosto", "ago"],
    9: ["setembro", "set"],
    10: ["outubro", "out"],
    11: ["novembro", "nov"],
    12: ["dezembro", "dez"]
}

def log(mensagem, tipo="info"):
    """Função de log colorido"""
    cores = {
        "info": "\033[94m",
        "success": "\033[92m",
        "warning": "\033[93m",
        "error": "\033[91m",
        "end": "\033[0m"
    }
    print(f"{cores.get(tipo, '')}[{datetime.now().strftime('%H:%M:%S')}] {mensagem}{cores['end']}")

def normalizar_nome_mes(data_pagamento):
    """Converte data para formato 'Mês/Ano' padronizado"""
    # Extrair mês e ano
    mes_numero = data_pagamento.month
    ano = data_pagamento.year
    
    # Pegar primeiro nome do mês (forma completa)
    nome_mes = MESES_PT[mes_numero][0].capitalize()
    
    # Formato padronizado: "Maio/2024"
    return f"{nome_mes}/{ano}"

def buscar_mes_no_resumo(mes_formatado):
    """Busca mês no BD Resumo Mensal (tenta vários formatos)"""
    # Tenta buscar exatamente como está
    query_exato = {
        "filter": {
            "property": "Mês",
            "title": {"equals": mes_formatado}
        }
    }
    
    try:
        response = requests.post(
            f"https://api.notion.com/v1/databases/{RESUMO_DB_ID}/query",
            headers=headers,
            json=query_exato
        )
        
        resultados = response.json().get("results", [])
        if resultados:
            return resultados[0]["id"]
    except Exception as e:
        log(f"Erro na busca exata: {e}", "error")
    
    # Se não encontrou, tenta buscar por partes
    query_contem = {
        "filter": {
            "property": "Mês",
            "title": {"contains": mes_formatado.split('/')[0]}
        }
    }
    
    try:
        response = requests.post(
            f"https://api.notion.com/v1/databases/{RESUMO_DB_ID}/query",
            headers=headers,
            json=query_contem
        )
        
        resultados = response.json().get("results", [])
        for resultado in resultados:
            titulo = resultado["properties"]["Mês"]["title"][0]["text"]["content"]
            if str(mes_formatado.split('/')[1]) in titulo:  # Verifica ano
                return resultado["id"]
    except Exception as e:
        log(f"Erro na busca parcial: {e}", "error")
    
    return None

def criar_mes_no_resumo(mes_formatado, data_pagamento):
    """Cria um novo mês no BD Resumo Mensal"""
    mes_numero = data_pagamento.month
    ano = data_pagamento.year
    
    dados_mes = {
        "parent": {"database_id": RESUMO_DB_ID},
        "properties": {
            "Mês": {
                "title": [{"type": "text", "text": {"content": mes_formatado}}]
            },
            "Mês número": {"number": mes_numero},
            "Ano": {"number": ano}
        }
    }
    
    try:
        response = requests.post(
            "https://api.notion.com/v1/pages",
            headers=headers,
            json=dados_mes
        )
        mes_id = response.json()["id"]
        log(f"Criado novo mês: {mes_formatado}", "success")
        return mes_id
    except Exception as e:
        log(f"Erro ao criar mês: {e}", "error")
        return None

def processar_pagamentos():
    """Processa parcelas pagas e relaciona com meses"""
    log("Processando pagamentos recentes...")
    
    # Buscar parcelas com Pagamento preenchido
    query = {
        "filter": {
            "property": "Pagamento",
            "date": {"is_not_empty": True}
        },
        "page_size": 100
    }
    
    try:
        response = requests.post(
            f"https://api.notion.com/v1/databases/{PARCELAS_DB_ID}/query",
            headers=headers,
            json=query
        )
        parcelas_pagas = response.json().get("results", [])
    except Exception as e:
        log(f"Erro ao buscar parcelas pagas: {e}", "error")
        return
    
    if not parcelas_pagas:
        log("Nenhuma parcela paga encontrada", "info")
        return
    
    log(f"Encontradas {len(parcelas_pagas)} parcela(s) paga(s)", "info")
    
    parcelas_processadas = 0
    
    for parcela in parcelas_pagas:
        props = parcela["properties"]
        parcela_id = parcela["id"]
        
        # Verificar se já tem mês relacionado
        meses_relacionados = props.get("Mês de pagamento", {}).get("relation", [])
        if meses_relacionados:
            continue  # Já tem mês, pula
        
        # Obter data de pagamento
        data_pagamento_str = props.get("Pagamento", {}).get("date", {}).get("start")
        if not data_pagamento_str:
            continue
        
        try:
            data_pagamento = datetime.fromisoformat(data_pagamento_str.replace('Z', '+00:00'))
        except:
            log(f"Data de pagamento inválida: {data_pagamento_str}", "warning")
            continue
        
        # Normalizar nome do mês
        mes_formatado = normalizar_nome_mes(data_pagamento)
        
        # Buscar mês existente
        mes_id = buscar_mes_no_resumo(mes_formatado)
        
        # Se não existe, criar
        if not mes_id:
            mes_id = criar_mes_no_resumo(mes_formatado, data_pagamento)
        
        if mes_id:
            # Atualizar relação
            update_data = {
                "properties": {
                    "Mês de pagamento": {
                        "relation": [{"id": mes_id}]
                    }
                }
            }
            
            try:
                requests.patch(
                    f"https://api.notion.com/v1/pages/{parcela_id}",
                    headers=headers,
                    json=update_data
                )
                log(f"✓ Parcela {parcela_id[:8]} → {mes_formatado}", "success")
                parcelas_processadas += 1
            except Exception as e:
                log(f"✗ Erro ao relacionar parcela: {e}", "error")
    
    log(f"Processados {parcelas_processadas} pagamento(s)", "success")

# ==============================================
# FUNÇÕES ORIGINAIS DE GERAÇÃO DE PARCELAS
# ==============================================

def buscar_clientes_nao_processados():
    """Busca clientes com checkbox 'Processado' = false"""
    log("Buscando clientes não processados...")
    
    query = {
        "filter": {
            "and": [
                {"property": "Qtd. Parcelas", "number": {"is_not_empty": True}},
                {"property": "Processado", "checkbox": {"equals": False}}
            ]
        }
    }
    
    try:
        response = requests.post(
            f"https://api.notion.com/v1/databases/{CLIENTES_DB_ID}/query",
            headers=headers,
            json=query
        )
        clientes = response.json().get("results", [])
        log(f"Encontrados {len(clientes)} cliente(s) não processado(s)", "success")
        return clientes
    except Exception as e:
        log(f"Erro ao buscar clientes: {e}", "error")
        return []

def verificar_parcelas_existentes(cliente_id, cliente_nome):
    """Verifica quantas parcelas já existem para o cliente"""
    query = {
        "filter": {
            "property": "Clientes",
            "relation": {"contains": cliente_id}
        }
    }
    
    try:
        response = requests.post(
            f"https://api.notion.com/v1/databases/{PARCELAS_DB_ID}/query",
            headers=headers,
            json=query
        )
        parcelas_existentes = len(response.json().get("results", []))
        
        if parcelas_existentes > 0:
            log(f"  ⚠️  {cliente_nome}: Já tem {parcelas_existentes} parcela(s)", "warning")
        
        return parcelas_existentes
    except Exception as e:
        log(f"  ✗ Erro ao verificar parcelas: {e}", "error")
        return 0

def criar_parcelas_para_cliente(cliente):
    """Cria parcelas para um cliente específico"""
    props = cliente["properties"]
    cliente_id = cliente["id"]
    
    try:
        nome_cliente = props["Nome"]["title"][0]["text"]["content"]
    except:
        nome_cliente = f"Cliente_{cliente_id[:8]}"
    
    qtd_parcelas = props.get("Qtd. Parcelas", {}).get("number")
    data_emprestimo_str = props.get("Data", {}).get("date", {}).get("start")
    
    if not qtd_parcelas or not data_emprestimo_str:
        log(f"✗ {nome_cliente}: Dados incompletos", "error")
        return False
    
    try:
        data_emprestimo = datetime.fromisoformat(data_emprestimo_str.replace('Z', '+00:00'))
    except:
        log(f"✗ {nome_cliente}: Data inválida", "error")
        return False
    
    # Verificar parcelas existentes
    parcelas_existentes = verificar_parcelas_existentes(cliente_id, nome_cliente)
    
    if parcelas_existentes >= qtd_parcelas:
        log(f"  ✅ {nome_cliente}: Todas as parcelas já existem", "success")
        marcar_como_processado(cliente_id)
        return True
    
    log(f"\n📋 {nome_cliente}: Criando {qtd_parcelas - parcelas_existentes} nova(s) parcela(s)...")
    
    # Criar parcelas faltantes
    for i in range(parcelas_existentes + 1, qtd_parcelas + 1):
        dias_para_vencimento = 30 * (i - 1)
        data_vencimento = data_emprestimo + timedelta(days=dias_para_vencimento)
        
        id_parcela = f"{nome_cliente[:3].upper()}-{cliente_id[-4:]}-{i}"
        
        dados_parcela = {
            "parent": {"database_id": PARCELAS_DB_ID},
            "properties": {
                "ID": {"title": [{"type": "text", "text": {"content": id_parcela}}]},
                "Parcela": {"number": i},
                "Clientes": {"relation": [{"id": cliente_id}]},
                "Vencimento": {"date": {"start": data_vencimento.strftime("%Y-%m-%d")}},
                "Diária": {"select": {"name": "15"}}
            }
        }
        
        try:
            requests.post("https://api.notion.com/v1/pages", headers=headers, json=dados_parcela)
            log(f"  ✓ Parcela {i}/{qtd_parcelas}: {data_vencimento.strftime('%d/%m/%Y')}", "success")
        except Exception as e:
            log(f"  ✗ Erro na parcela {i}: {e}", "error")
    
    marcar_como_processado(cliente_id)
    return True

def marcar_como_processado(cliente_id):
    """Marca o cliente como processado"""
    update_data = {
        "properties": {
            "Processado": {"checkbox": True}
        }
    }
    
    try:
        requests.patch(
            f"https://api.notion.com/v1/pages/{cliente_id}",
            headers=headers,
            json=update_data
        )
    except:
        pass

def main():
    """Função principal"""
    if not NOTION_TOKEN:
        log("❌ NOTION_TOKEN não configurado!", "error")
        sys.exit(1)
    
    print("\n" + "="*60)
    log("🚀 GERADOR DE PARCELAS + RELACIONADOR DE PAGAMENTOS", "info")
    print("="*60)
    
    # PARTE 1: Gerar novas parcelas
    clientes = buscar_clientes_nao_processados()
    
    if clientes:
        log(f"📊 {len(clientes)} cliente(s) para processar", "info")
        for cliente in clientes:
            criar_parcelas_para_cliente(cliente)
    else:
        log("✅ Nenhum cliente pendente", "success")
    
    # PARTE 2: Relacionar pagamentos com meses
    processar_pagamentos()
    
    print("\n" + "="*60)
    log("🎉 SISTEMA COMPLETO CONCLUÍDO!", "success")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()
