#!/usr/bin/env python3

import requests

# Configuration
API_URL = 'http://127.0.0.1:18001/collections'
TOKEN = '59e3c4746755272bd168b23d7abc2079821b9ec3ee89394dc783ca1ccf430cb0'
HEADERS = {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {TOKEN}'
}

def get_collections():
    """Récupérer la liste des collections"""
    response = requests.get(API_URL, headers=HEADERS)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Erreur API: {response.status_code} - {response.text}")
        return None

def search_in_collection(collection_name, drive_folder_id, limit=50):
    """Rechercher des documents dans une collection spécifique"""
    search_url = 'http://127.0.00.1:18001/search'
    payload = {
        "q": "",
        "k": limit,
        "collection": collection_name,
        "include_documents": True
    }
    
    response = requests.post(search_url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        data = response.json()
        hits = data.get('hits', [])
        
        # Filtrer les documents contenant l'ID du dossier Drive
        found_docs = []
        for hit in hits:
            metadata = hit.get('metadata', {})
            source = metadata.get('source', '')
            if drive_folder_id in source:
                found_docs.append(hit)
        
        return found_docs
    else:
        print(f"Erreur recherche dans {collection_name}: {response.status_code}")
        return []

# Récupérer les collections
print("Récupération des collections...")
collections_data = get_collections()

if collections_data:
    collections = collections_data.get('collections', [])
    print(f"Collections trouvées: {len(collections)}")
    
    # Afficher les collections
    for coll in collections:
        print(f"  - {coll.get('name', 'Sans nom')}: {coll.get('metadata', {})}")
    
    # Rechercher les documents du dossier Drive dans chaque collection
    drive_folder_id = '1YMGGaLUafNjHdXi03JVpjzntPa310HeR'
    print(f"\nRecherche des documents du dossier Drive {drive_folder_id} dans toutes les collections...")
    
    total_found = 0
    for coll in collections:
        coll_name = coll.get('name', '')
        print(f"\nRecherche dans {coll_name}...")
        
        found_docs = search_in_collection(coll_name, drive_folder_id)
        
        if found_docs:
            print(f"  {len(found_docs)} documents trouvés dans {coll_name}:")
            for i, doc in enumerate(found_docs):
                doc_id = doc.get('id', '')
                metadata = doc.get('metadata', {})
                title = metadata.get('title', 'Sans titre')
                source = metadata.get('source', '')
                print(f"    {i+1}. {doc_id}")
                print(f"       Titre: {title}")
                print(f"       Source: {source}")
            total_found += len(found_docs)
        else:
            print(f"  Aucun document trouvé dans {coll_name}")
    
    print(f"\nTotal trouvé: {total_found} documents")
    
    if total_found > 0:
        # Sauvegarder les informations
        with open('/tmp/found_docs_summary.txt', 'w') as f:
            f.write(f"Total documents trouvés: {total_found}\n")
            f.write(f"Dossier Drive: {drive_folder_id}\n\n")
            
            for coll in collections:
                coll_name = coll.get('name', '')
                found_docs = search_in_collection(coll_name, drive_folder_id)
                if found_docs:
                    f.write(f"Collection: {coll_name}\n")
                    for doc in found_docs:
                        f.write(f"  {doc.get('id', '')}\n")
                    f.write("\n")
        
        print("Informations sauvegardées dans /tmp/found_docs_summary.txt")
    else:
        print("\nAucun document trouvé. Vérification des documents les plus récents...")
        
        # Afficher les documents les plus récents de chaque collection
        for coll in collections[:5]:  # Limiter à 5 collections
            coll_name = coll.get('name', '')
            print(f"\nDocuments récents dans {coll_name}:")
            
            search_url = 'http://127.0.0.1:18001/search'
            payload = {
                "q": "",
                "k": 10,
                "collection": coll_name,
                "include_documents": True
            }
            
            response = requests.post(search_url, headers=HEADERS, json=payload)
            if response.status_code == 200:
                data = response.json()
                hits = data.get('hits', [])
                
                for i, hit in enumerate(hits[:5]):
                    metadata = hit.get('metadata', {})
                    source = metadata.get('source', '')
                    title = metadata.get('title', 'Sans titre')
                    print(f"  {i+1}. {title[:50]}... | {source[:60]}...")
else:
    print("Impossible de récupérer les collections")
