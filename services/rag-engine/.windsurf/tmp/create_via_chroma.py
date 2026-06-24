#!/usr/bin/env python3
import requests
import json
import subprocess

# Configuration
API_URL = 'http://127.0.0.1:18001'
TOKEN = '59e3c4746755272bd168b23d7abc2079821b9ec3ee89394dc783ca1ccf430cb0'
HEADERS = {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {TOKEN}'
}

def create_collection_via_chroma(collection_name):
    """Créer une collection via ChromaDB direct"""
    try:
        # Utiliser curl pour créer la collection via l'API ChromaDB
        cmd = [
            'curl', '-s', '-X', 'POST',
            'http://localhost:8000/api/v1/collections',
            '-H', 'Content-Type: application/json',
            '-d', json.dumps({
                'name': collection_name,
                'metadata': {'hnsw:space': 'cosine'}
            })
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            print(f"Collection {collection_name} créée via ChromaDB")
            return True
        else:
            print(f"Erreur création ChromaDB: {result.stderr}")
            return False
    except Exception as e:
        print(f"Exception création collection: {e}")
        return False

def get_drive_documents(collection_name, drive_folder_id, limit=50):
    """Récupérer les documents d'une collection provenant d'un dossier Drive"""
    search_url = f'{API_URL}/search'
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
        print(f"Erreur recherche: {response.status_code} - {response.text}")
        return []

def move_documents(source_collection, target_collection, drive_folder_id):
    """Déplacer les documents d'une collection à une autre"""
    print(f"Déplacement des documents du dossier Drive {drive_folder_id}")
    print(f"De {source_collection} vers {target_collection}")
    
    # Récupérer tous les documents (plusieurs requêtes si nécessaire)
    all_docs = []
    processed_ids = set()
    
    for offset in range(0, 1000, 50):  # Limiter à 1000 documents pour éviter boucle infinie
        docs = get_drive_documents(source_collection, drive_folder_id, limit=50)
        if not docs:
            break
        
        # Éviter les doublons
        new_docs = [doc for doc in docs if doc['id'] not in processed_ids]
        if not new_docs:
            break
            
        all_docs.extend(new_docs)
        processed_ids.update(doc['id'] for doc in new_docs)
        
        if len(docs) < 50:  # Tous les documents ont été récupérés
            break
    
    print(f"Documents à déplacer: {len(all_docs)}")
    
    if not all_docs:
        print("Aucun document trouvé à déplacer")
        return False
    
    # Afficher les documents à déplacer
    print("\nDocuments à déplacer:")
    for i, doc in enumerate(all_docs):
        metadata = doc.get('metadata', {})
        title = metadata.get('title', 'Sans titre')
        print(f"  {i+1}. {doc['id'][:50]}... | {title[:50]}...")
    
    # Préparer les documents pour la nouvelle collection
    documents_to_add = []
    ids_to_add = []
    metadatas_to_add = []
    
    for doc in all_docs:
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
    
    print(f"\nInsertion de {len(documents_to_add)} documents dans {target_collection}...")
    
    response = requests.post(insert_url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        result = response.json()
        print(f"Insertion réussie: {result}")
        
        # Supprimer les documents de la collection source
        print(f"\nSuppression des documents de {source_collection}...")
        delete_url = f'{API_URL}/collections/{source_collection}/delete'
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

# Exécution principale
drive_folder_id = '1YMGGaLUafNjHdXi03JVpjzntPa310HeR'
source_collection = 'rag_education'
target_collection = 'rag_maths_3e_dnb'

print(f"Création de la collection {target_collection}...")
if create_collection_via_chroma(target_collection):
    print(f"Collection {target_collection} prête")
    
    print(f"\nDéplacement des documents...")
    success = move_documents(source_collection, target_collection, drive_folder_id)
    
    if success:
        print(f"\nOpération terminée avec succès!")
        print(f"Les documents ont été déplacés de {source_collection} vers {target_collection}")
    else:
        print(f"\nÉchec de l'opération")
else:
    print(f"Impossible de créer la collection {target_collection}")
