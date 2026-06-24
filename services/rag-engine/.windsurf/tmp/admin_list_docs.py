#!/usr/bin/env python3
from datetime import datetime

import requests

# Configuration
API_URL = 'http://127.0.0.1:18001'
TOKEN = '59e3c4746755272bd168b23d7abc2079821b9ec3ee89394dc783ca1ccf430cb0'
HEADERS = {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {TOKEN}'
}

def list_recent_documents():
    """Lister les documents récents via l'API admin"""
    
    # Utiliser l'API admin pour lister les documents
    admin_url = f'{API_URL}/admin/documents'
    
    # Essayer de récupérer les documents récents
    params = {
        'limit': 100,
        'collection': 'rag_education'
    }
    
    try:
        response = requests.get(admin_url, headers=HEADERS, params=params)
        
        if response.status_code == 200:
            data = response.json()
            docs = data.get('documents', [])
            print(f"Documents récupérés via API admin: {len(docs)}")
            
            # Filtrer les documents récents (dernières 24h)
            recent_docs = []
            now = datetime.now()
            
            for doc in docs:
                # Vérifier si le document est récent
                metadata = doc.get('metadata', {})
                source = metadata.get('source', '')
                title = metadata.get('title', '')
                
                # Chercher des documents qui pourraient être les documents maths
                if any(keyword in title.lower() for keyword in ['maths', 'math', 'géométrie', 'algorithmique', 'programme']):
                    recent_docs.append(doc)
                    print(f"  - {title} | {source}")
            
            print(f"\nDocuments maths potentiels trouvés: {len(recent_docs)}")
            
            if recent_docs:
                return move_documents(recent_docs, 'rag_maths_3e_dnb')
            else:
                # Si aucun document trouvé, essayer une approche différente
                print("Aucun document maths trouvé via API admin")
                return try_direct_approach()
                
        else:
            print(f"Erreur API admin: {response.status_code} - {response.text}")
            return try_direct_approach()
            
    except Exception as e:
        print(f"Exception API admin: {e}")
        return try_direct_approach()

def try_direct_approach():
    """Essayer une approche directe avec la tâche Drive"""
    
    print("\nEssai avec l'approche directe basée sur la tâche Drive...")
    
    # Récupérer le statut de la tâche Drive
    task_url = f'{API_URL}/ingest/drive/status/70dda4ca5b25'
    
    response = requests.get(task_url, headers=HEADERS)
    if response.status_code == 200:
        task_data = response.json()
        file_results = task_data.get('file_results', [])
        
        print(f"Fichiers de la tâche: {len(file_results)}")
        
        # Chercher ces documents dans la collection
        found_docs = []
        
        for file_result in file_results:
            if file_result.get('status') == 'ok':
                filename = file_result.get('name', '')
                print(f"  Recherche: {filename}")
                
                # Chercher ce document dans la collection
                search_url = f'{API_URL}/search'
                payload = {
                    "q": filename.replace('.pdf', ''),
                    "k": 10,
                    "collection": "rag_education",
                    "include_documents": True
                }
                
                response = requests.post(search_url, headers=HEADERS, json=payload)
                if response.status_code == 200:
                    data = response.json()
                    hits = data.get('hits', [])
                    
                    for hit in hits:
                        metadata = hit.get('metadata', {})
                        doc_title = metadata.get('title', '')
                        
                        # Vérifier si c'est le bon document
                        if filename.replace('.pdf', '').lower() in doc_title.lower() or doc_title.lower() in filename.replace('.pdf', '').lower():
                            found_docs.append(hit)
                            print(f"    ✓ Trouvé: {doc_title}")
                            break
        
        print(f"\nDocuments trouvés: {len(found_docs)}")
        
        if found_docs:
            return move_documents(found_docs, 'rag_maths_3e_dnb')
        else:
            print("Aucun document trouvé avec cette approche")
            return False
    else:
        print(f"Erreur récupération tâche: {response.status_code}")
        return False

def move_documents(docs, target_collection):
    """Déplacer les documents vers la nouvelle collection"""
    if not docs:
        return False
    
    print(f"\nDéplacement de {len(docs)} documents vers {target_collection}")
    
    # Préparer les documents pour la nouvelle collection
    documents_to_add = []
    ids_to_add = []
    metadatas_to_add = []
    
    for doc in docs:
        documents_to_add.append(doc.get('document', ''))
        ids_to_add.append(doc['id'])
        
        # Mettre à jour les métadonnées
        metadata = doc.get('metadata', {})
        metadata['collection'] = target_collection
        metadata['moved_from'] = 'rag_education'
        metadata['move_date'] = datetime.now().isoformat()
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
        
        # Supprimer les documents de rag_education
        print("Suppression des documents de rag_education...")
        delete_url = f'{API_URL}/collections/rag_education/delete'
        delete_payload = {'ids': ids_to_add}
        
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

if __name__ == "__main__":
    success = list_recent_documents()
    if success:
        print("\nOpération terminée avec succès!")
    else:
        print("\nÉchec de l'opération")
