#!/usr/bin/env python3

import requests

# Configuration
CHROMA_URL = 'http://localhost:8000'
HEADERS = {'Content-Type': 'application/json'}

def get_collection_documents(collection_name, limit=1000):
    """Récupérer les documents d'une collection"""
    url = f'{CHROMA_URL}/api/v1/collections/{collection_name}/get'
    
    payload = {
        'limit': limit,
        'include': ['metadatas', 'documents']
    }
    
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

# Rechercher les documents dans rag_education
drive_folder_id = '1YMGGaLUafNjHdXi03JVpjzntPa310HeR'
print(f'\nRecherche des documents dans rag_education avec source contenant {drive_folder_id}')

# Obtenir tous les documents de rag_education
results = get_collection_documents('rag_education', limit=1000)

if results and results.get('ids'):
    print(f'Total documents dans rag_education: {len(results["ids"])}')
    
    # Filtrer les documents contenant l'ID du dossier Drive
    found_docs = []
    found_ids = []
    found_titles = []
    
    for i, doc_id in enumerate(results['ids']):
        metadata = results['metadatas'][i] if i < len(results['metadatas']) else {}
        source = metadata.get('source', '')
        title = metadata.get('title', 'Sans titre')
        
        if drive_folder_id in source:
            found_docs.append({
                'id': doc_id,
                'title': title,
                'source': source,
                'metadata': metadata
            })
            found_ids.append(doc_id)
            found_titles.append(title)
    
    print(f'Documents provenant du dossier Drive {drive_folder_id}: {len(found_docs)}')
    
    if found_docs:
        print('\nDétails des documents à déplacer:')
        for i, doc in enumerate(found_docs):
            print(f"  {i+1}. ID: {doc['id']}")
            print(f"     Titre: {doc['title']}")
            print(f"     Source: {doc['source']}")
            print()
        
        # Exporter les IDs pour le déplacement
        print("IDs à déplacer:")
        for i, doc_id in enumerate(found_ids):
            print(f"  {i+1}. {doc_id}")
            
        # Sauvegarder les IDs dans un fichier
        with open('/tmp/docs_to_move.txt', 'w') as f:
            for doc_id in found_ids:
                f.write(f"{doc_id}\n")
        print("\nIDs sauvegardés dans /tmp/docs_to_move.txt")
    else:
        print("Aucun document trouvé provenant de ce dossier Drive")
        
        # Afficher quelques sources pour debug
        print("\nQuelques sources dans la collection (pour debug):")
        count = 0
        for i, doc_id in enumerate(results['ids']):
            if count >= 10:
                break
            metadata = results['metadatas'][i] if i < len(results['metadatas']) else {}
            source = metadata.get('source', '')
            title = metadata.get('title', '')
            print(f"  {count+1}. {title[:50]}... | {source[:80]}...")
            count += 1
else:
    print("Impossible de récupérer les documents de rag_education")
