#!/usr/bin/env python3

import requests

# Configuration
API_URL = 'http://127.0.0.1:18001/search'
TOKEN = '59e3c4746755272bd168b23d7abc2079821b9ec3ee89394dc783ca1ccf430cb0'
HEADERS = {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {TOKEN}'
}

def search_collection(collection_name, limit=100):
    """Rechercher tous les documents d'une collection"""
    payload = {
        "q": "",
        "k": limit,
        "collection": collection_name,
        "include_documents": True
    }
    
    response = requests.post(API_URL, headers=HEADERS, json=payload)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Erreur API: {response.status_code} - {response.text}")
        return None

# Rechercher les documents dans rag_education
drive_folder_id = '1YMGGaLUafNjHdXi03JVpjzntPa310HeR'
print(f"Recherche des documents dans rag_education avec source contenant {drive_folder_id}")

data = search_collection('rag_education', limit=200)

if data and 'hits' in data:
    hits = data['hits']
    print(f"Total documents trouvés: {len(hits)}")
    
    # Filtrer les documents contenant l'ID du dossier Drive
    found_docs = []
    for hit in hits:
        metadata = hit.get('metadata', {})
        source = metadata.get('source', '')
        if drive_folder_id in source:
            found_docs.append(hit)
    
    print(f"Documents provenant du dossier Drive {drive_folder_id}: {len(found_docs)}")
    
    if found_docs:
        print("\nDétails des documents à déplacer:")
        for i, doc in enumerate(found_docs):
            doc_id = doc.get('id', '')
            metadata = doc.get('metadata', {})
            title = metadata.get('title', 'Sans titre')
            source = metadata.get('source', '')
            print(f"  {i+1}. ID: {doc_id}")
            print(f"     Titre: {title}")
            print(f"     Source: {source}")
            print()
        
        # Exporter les IDs pour le déplacement
        print("IDs à déplacer:")
        for i, doc in enumerate(found_docs):
            print(f"  {i+1}. {doc.get('id', '')}")
            
        # Sauvegarder les IDs dans un fichier
        with open('/tmp/docs_to_move.txt', 'w') as f:
            for doc in found_docs:
                f.write(f"{doc.get('id', '')}\n")
        print("\nIDs sauvegardés dans /tmp/docs_to_move.txt")
    else:
        print("Aucun document trouvé provenant de ce dossier Drive")
        
        # Afficher les premiers documents pour debug
        print("\nPremiers documents dans rag_education (pour debug):")
        for i, hit in enumerate(hits[:10]):
            metadata = hit.get('metadata', {})
            source = metadata.get('source', '')
            title = metadata.get('title', '')
            print(f"  {i+1}. {title[:50]}... | {source[:80]}...")
else:
    print("Impossible de récupérer les documents")
