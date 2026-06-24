import requests
import json

# Configuration
CHROMA_URL = 'http://localhost:8000'
HEADERS = {'Content-Type': 'application/json'}

def get_collection_documents(collection_name, where_clause=None, limit=100):
    """Récupérer les documents d'une collection avec filtre optionnel"""
    url = f'{CHROMA_URL}/api/v1/collections/{collection_name}/get'
    
    payload = {
        'limit': limit,
        'include': ['metadatas', 'documents']
    }
    
    if where_clause:
        payload['where'] = where_clause
    
    response = requests.post(url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        return response.json()
    else:
        print(f'Erreur {response.status_code}: {response.text}')
        return None

def list_collections():
    """Lister toutes les collections"""
    url = f'{CHROMA_URL}/api/v1/collections'
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        return response.json()
    else:
        print(f'Erreur {response.status_code}: {response.text}')
        return None

# Lister les collections
collections = list_collections()
if collections:
    print('Collections disponibles:')
    for coll in collections:
        print(f'  - {coll["name"]}: {coll.get("metadata", {}).get("hnsw:space", "unknown")} space')
else:
    print('Impossible de lister les collections')
    exit(1)

# Rechercher les documents dans rag_education avec le source Drive spécifique
drive_folder_id = '1YMGGaLUafNjHdXi03JVpjzntPa310HeR'
print(f'\nRecherche des documents dans rag_education avec source contenant {drive_folder_id}')

# Essayer avec une recherche par contains
where_clause = {'source': {'$contains': drive_folder_id}}
results = get_collection_documents('rag_education', where_clause)

if results and results.get('ids'):
    print(f'Nombre de documents trouvés: {len(results["ids"])}')
    print('\nPremiers résultats:')
    for i, doc_id in enumerate(results['ids'][:5]):
        metadata = results['metadatas'][i] if i < len(results['metadatas']) else {}
        source = metadata.get('source', 'N/A')
        title = metadata.get('title', 'N/A')
        print(f'  {i+1}. ID: {doc_id} | Titre: {title} | Source: {source}')
    
    if len(results['ids']) > 5:
        print(f'  ... et {len(results["ids"]) - 5} autres documents')
    
    # Afficher tous les IDs pour le déplacement
    print(f'\nIDs des documents à déplacer:')
    for i, doc_id in enumerate(results['ids']):
        print(f'  {i+1}. {doc_id}')
else:
    print('Aucun document trouvé avec ce filtre')
    
    # Alternative: chercher tous les documents récents et filtrer manuellement
    print('\nRecherche alternative: derniers documents dans rag_education')
    all_results = get_collection_documents('rag_education', limit=100)
    
    if all_results and all_results.get('ids'):
        found_count = 0
        found_ids = []
        found_titles = []
        
        for i, doc_id in enumerate(all_results['ids']):
            metadata = all_results['metadatas'][i] if i < len(all_results['metadatas']) else {}
            source = metadata.get('source', 'N/A')
            title = metadata.get('title', 'N/A')
            
            if drive_folder_id in source:
                found_count += 1
                found_ids.append(doc_id)
                found_titles.append(title)
                print(f'  {found_count}. ID: {doc_id} | Titre: {title}')
        
        print(f'\nTotal trouvé: {found_count}')
        
        if found_ids:
            print(f'\nIDs des documents à déplacer:')
            for i, (doc_id, title) in enumerate(zip(found_ids, found_titles)):
                print(f'  {i+1}. {doc_id} | {title}')
    else:
        print('Impossible de récupérer les documents')
