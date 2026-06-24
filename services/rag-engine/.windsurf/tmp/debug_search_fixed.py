#!/usr/bin/env python3
import requests
import json

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
        "k": 50,
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
    drive_docs = []
    
    for i, hit in enumerate(hits):
        metadata = hit.get('metadata', {})
        source = metadata.get('source', '')
        
        # Compter les types de sources
        source_type = 'unknown'
        if 'drive.google.com' in source:
            source_type = 'drive'
            if drive_folder_id in source:
                drive_found = True
                drive_docs.append(hit)
                print(f"  ✓ TROUVÉ - Doc {len(drive_docs)}: {hit['id'][:30]}... | {metadata.get('title', 'Sans titre')[:50]}...")
                print(f"    Source: {source}")
        elif '/data/uploads/' in source:
            source_type = 'upload'
        elif 'http' in source:
            source_type = 'url'
        else:
            source_type = 'other'
        
        sources[source_type] = sources.get(source_type, 0) + 1
        
        if i < 10:  # Afficher les 10 premiers
            print(f"  {i+1}. {hit['id'][:30]}... | {metadata.get('title', 'Sans titre')[:50]}...")
            print(f"     Source: {source}")
    
    print(f"\nTypes de sources trouvés:")
    for source_type, count in sources.items():
        print(f"  - {source_type}: {count}")
    
    if drive_found:
        print(f"\n✓ {len(drive_docs)} documents du dossier Drive {drive_folder_id} trouvés!")
        return drive_docs
    else:
        print(f"\n✗ Aucun document du dossier Drive {drive_folder_id} trouvé")
        
        # Chercher des documents avec des IDs de dossier similaires
        print(f"\nRecherche d'IDs de dossier similaires...")
        for hit in hits:
            metadata = hit.get('metadata', {})
            source = metadata.get('source', '')
            if 'drive.google.com' in source:
                # Extraire l'ID du fichier Drive
                if '/d/' in source:
                    file_id = source.split('/d/')[1].split('/')[0]
                    print(f"  ID de fichier Drive: {file_id}")
                else:
                    print(f"  Source Drive: {source}")
        return []

def move_found_documents(docs, target_collection):
    """Déplacer les documents trouvés vers la nouvelle collection"""
    if not docs:
        print("Aucun document à déplacer")
        return False
    
    print(f"\nDéplacement de {len(docs)} documents vers {target_collection}")
    
    # Préparer les documents pour la nouvelle collection
    documents_to_add = []
    ids_to_add = []
    metadatas_to_add = []
    
    for doc in docs:
        documents_to_add.append(doc.get('document', ''))
        ids_to_add.append(doc['id'])
        
        # Mettre à jour les métadonnées pour la nouvelle collection
        metadata = doc.get('metadata', {})
        metadata['collection'] = target_collection
        metadatas_to_add.append(metadata)
    
    # Insérer dans la nouvelle collection
    insert_url = f'{API_URL}/ingest'
    payload = {
        'documents': documents_to_add,
        'ids': ids_to_add,
        'metadatas': metadatas_to_add,
        'collection': target_collection
    }
    
    print(f"Insertion de {len(documents_to_add)} documents dans {target_collection}...")
    
    response = requests.post(insert_url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        result = response.json()
        print(f"Insertion réussie: {result}")
        
        # Supprimer les documents de la collection source
        print(f"Suppression des documents de rag_education...")
        delete_url = f'{API_URL}/collections/rag_education/delete'
        delete_payload = {
            'ids': ids_to_add
        }
        
        delete_response = requests.post(delete_url, headers=HEADERS, json=delete_payload)
        if delete_response.status_code == 200:
            print(f"Suppression réussie: {len(ids_to_add)} documents supprimés")
            return True
        else:
            print(f"Erreur suppression: {delete_response.status_code} - {delete_response.text}")
            return False
    else:
        print(f"Erreur insertion: {response.status_code} - {response.text}")
        return False

# Exécuter l'analyse
drive_folder_id = '1YMGGaLUafNjHdXi03JVpjzntPa310HeR'
source_collection = 'rag_education'
target_collection = 'rag_maths_3e_dnb'

found_docs = debug_search(source_collection, drive_folder_id)

if found_docs:
    success = move_found_documents(found_docs, target_collection)
    if success:
        print(f"\nOpération terminée avec succès!")
        print(f"Les {len(found_docs)} documents ont été déplacés de {source_collection} vers {target_collection}")
    else:
        print(f"\nÉchec du déplacement")
else:
    print(f"\nAucun document trouvé à déplacer")
