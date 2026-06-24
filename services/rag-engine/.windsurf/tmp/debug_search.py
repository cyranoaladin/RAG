#!/usr/bin/env python3

import requests

# Configuration
API_URL = 'http://127.0.0.1:18001'
TOKEN = '59e3c4746755272bd168b23d7abc2079821b9ec3ee89394dc783ca1ccf430cb0'
HEADERS = {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {TOKEN}'
}

def debug_search(collection_name, drive_folder_id):
    """Analyser la recherche pour comprendre pourquoi les documents ne sont pas trouvés"""
    print(f"Analyse de la recherche dans {collection_name}")
    print(f"Dossier Drive cible: {drive_folder_id}")
    
    # Récupérer les documents de la collection
    search_url = f'{API_URL}/search'
    payload = {
        "q": "",
        "k": 100,
        "collection": collection_name,
        "include_documents": True
    }
    
    response = requests.post(search_url, headers=HEADERS, json=payload)
    if response.status_code != 200:
        print(f"Erreur recherche: {response.status_code} - {response.text}")
        return
    
    data = response.json()
    hits = data.get('hits', [])
    print(f"\nTotal documents trouvés dans {collection_name}: {len(hits)}")
    
    # Analyser les sources
    sources = {}
    drive_found = False
    
    for i, hit in enumerate(hits[:20]):  # Limiter à 20 pour l'analyse
        metadata = hit.get('metadata', {})
        source = metadata.get('source', '')
        
        # Compter les types de sources
        source_type = 'unknown'
        if 'drive.google.com' in source:
            source_type = 'drive'
            if drive_folder_id in source:
                drive_found = True
                print(f"  ✓ TROUVÉ - Doc {i+1}: {hit['id'][:30]}... | {metadata.get('title', 'Sans titre')[:50]}...")
                print(f"    Source: {source}")
        elif '/data/uploads/' in source:
            source_type = 'upload'
        elif 'http' in source:
            source_type = 'url'
        else:
            source_type = 'other'
        
        sources[source_type] = sources.get(source_type, 0) + 1
        
        if not drive_found and i < 10:  # Afficher les 10 premiers si pas encore trouvé
            print(f"  {i+1}. {hit['id'][:30]}... | {metadata.get('title', 'Sans titre')[:50]}...")
            print(f"     Source: {source}")
    
    print("\nTypes de sources trouvés:")
    for source_type, count in sources.items():
        print(f"  - {source_type}: {count}")
    
    if drive_found:
        print(f"\n✓ Documents du dossier Drive {drive_folder_id} trouvés!")
    else:
        print(f"\n✗ Aucun document du dossier Drive {drive_folder_id} trouvé")
        
        # Chercher des documents avec des IDs de dossier similaires
        print("\nRecherche d'IDs de dossier similaires...")
        for hit in hits[:50]:
            metadata = hit.get('metadata', {})
            source = metadata.get('source', '')
            if 'drive.google.com' in source and 'folder' in source.lower():
                print(f"  ID de dossier trouvé: {source}")
            elif 'drive.google.com' in source and len(source) > 50:
                print(f"  Source Drive longue: {source}")

# Exécuter l'analyse
drive_folder_id = '1YMGGaLUafNjHdXi03JVpjzntPa310HeR'
collection_name = 'rag_education'

debug_search(collection_name, drive_folder_id)
