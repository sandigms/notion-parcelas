import requests
from datetime import datetime, timedelta
import os
import sys

# Configurações
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
CLIENTES_DB_ID = "2ef5027d49aa8023bd94f91238ae95d2"
PARCELAS_DB_ID = "2ef5027d49aa80ffb35fd4a655b776f7"

headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

def log(mensagem, tipo="info"):
    """Função de log colorido"""
    cores = {
        "info": "\033[94m",    # Azul
        "success": "\033[92m", # Verde
        "warning": "\033[93m", # Amarelo
        "error": "\033[91m",   # Vermelho
        "end": "\033[0m"       # Fim da cor
    }
    print(f"{cores.get(tipo, '')}[{datetime.now().strftime('%H:%M:%S')}] {mensagem}{cores['end']}")

def buscar_clientes_nao_processados():
    """Busca clientes com checkbox 'Processado' = false"""
    log("Buscando clientes não processados...")
    
    query = {
        "filter": {
            "and": [
                {
                    "property": "Qtd. Parcelas",
                    "number": {"is_not_empty": True}
                },
                {
                    "property": "Processado",
                    "checkbox": {"equals": False}
                }
            ]
        }
    }
    
    try:
        response = requests.post(
            f"https://api.notion.com/v1/databases/{CLIENTES_DB_ID}/query",
            headers=headers,
            json=query
        )
        response.raise_for_status()
        
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
            log(f"  ⚠️  {cliente_nome}: Já tem {parcelas_existentes} parcela(s) existente(s)", "warning")
        
        return parcelas_existentes
        
    except Exception as e:
        log(f"  ✗ Erro ao verificar parcelas existentes: {e}", "error")
        return 0

def criar_parcelas_para_cliente(cliente):
    """Cria parcelas para um cliente específico"""
    props = cliente["properties"]
    cliente_id = cliente["id"]
    
    # Extrair dados do cliente
    try:
        nome_cliente = props["Nome"]["title"][0]["text"]["content"]
    except (KeyError, IndexError):
        nome_cliente = f"Cliente_{cliente_id[:8]}"
    
    qtd_parcelas = props.get("Qtd. Parcelas", {}).get("number")
    data_emprestimo_str = props.get("Data", {}).get("date", {}).get("start")
    
    if not qtd_parcelas:
        log(f"✗ {nome_cliente}: Quantidade de parcelas não definida", "error")
        return False
    
    if not data_emprestimo_str:
        log(f"✗ {nome_cliente}: Data do empréstimo não definida", "error")
        return False
    
    # Verificar se já existem parcelas
    parcelas_existentes = verificar_parcelas_existentes(cliente_id, nome_cliente)
    
    if parcelas_existentes >= qtd_parcelas:
        log(f"  ✅ {nome_cliente}: Todas as {qtd_parcelas} parcelas já existem. Marcando como processado...", "success")
        marcar_como_processado(cliente_id)
        return True
    
    # Converter data
    try:
        data_emprestimo = datetime.fromisoformat(data_emprestimo_str.replace('Z', '+00:00'))
    except:
        log(f"✗ {nome_cliente}: Data inválida: {data_emprestimo_str}", "error")
        return False
    
    log(f"\n📋 {nome_cliente}: Criando {qtd_parcelas - parcelas_existentes} nova(s) parcela(s)...", "info")
    
    # Criar parcelas faltantes
    parcelas_criadas = 0
    for i in range(parcelas_existentes + 1, qtd_parcelas + 1):
        # Calcular data de vencimento (30 dias entre parcelas)
        dias_para_vencimento = 30 * (i - 1)
        data_vencimento = data_emprestimo + timedelta(days=dias_para_vencimento)
        
        # ID único para a parcela
        id_parcela = f"{nome_cliente[:3].upper()}-{cliente_id[-4:]}-{i}"
        
        # Criar página da parcela
        dados_parcela = {
            "parent": {"database_id": PARCELAS_DB_ID},
            "properties": {
                "ID": {
                    "title": [{"type": "text", "text": {"content": id_parcela}}]
                },
                "Parcela": {"number": i},
                "Clientes": {"relation": [{"id": cliente_id}]},
                "Vencimento": {"date": {"start": data_vencimento.strftime("%Y-%m-%d")}},
                "Diária": {"select": {"name": "15"}}  # Valor padrão
            }
        }
        
        try:
            response = requests.post(
                "https://api.notion.com/v1/pages",
                headers=headers,
                json=dados_parcela
            )
            response.raise_for_status()
            
            parcelas_criadas += 1
            log(f"  ✓ Parcela {i}/{qtd_parcelas}: {data_vencimento.strftime('%d/%m/%Y')} (ID: {id_parcela})", "success")
            
        except Exception as e:
            log(f"  ✗ Erro ao criar parcela {i}: {e}", "error")
    
    # Marcar cliente como processado se criou todas as parcelas
    if parcelas_criadas > 0:
        marcar_como_processado(cliente_id)
        log(f"  ✅ {nome_cliente}: {parcelas_criadas} parcela(s) criada(s) com sucesso!", "success")
    
    return True

def marcar_como_processado(cliente_id):
    """Marca o cliente como tendo parcelas geradas"""
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
    except Exception as e:
        log(f"  ⚠️  Não consegui marcar cliente como processado: {e}", "warning")

def main():
    """Função principal"""
    if not NOTION_TOKEN:
        log("❌ ERRO: NOTION_TOKEN não configurado!", "error")
        log("Configure com: export NOTION_TOKEN='seu_token_aqui'", "info")
        sys.exit(1)
    
    print("\n" + "="*50)
    log("🚀 GERADOR DE PARCELAS NOTION - INICIANDO", "info")
    print("="*50)
    
    clientes = buscar_clientes_nao_processados()
    
    if not clientes:
        log("✅ Nenhum cliente pendente encontrado.", "success")
        return
    
    total_parcelas_criadas = 0
    
    for cliente in clientes:
        if criar_parcelas_para_cliente(cliente):
            total_parcelas_criadas += 1
    
    print("\n" + "="*50)
    log(f"🎉 PROCESSAMENTO CONCLUÍDO!", "success")
    log(f"📊 Clientes processados: {total_parcelas_criadas}/{len(clientes)}", "info")
    print("="*50 + "\n")

if __name__ == "__main__":
    main()
  
