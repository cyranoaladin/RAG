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

def get_task_files():
    """Récupérer les fichiers de la tâche Drive"""
    task_url = f'{API_URL}/ingest/drive/status/70dda4ca5b25'
    
    response = requests.get(task_url, headers=HEADERS)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Erreur récupération tâche: {response.status_code}")
        return None

def search_documents_by_filename(filename):
    """Chercher un document par son nom de fichier"""
    search_url = f'{API_URL}/search'
    
    # Nettoyer le nom de fichier pour la recherche
    clean_name = filename.replace('.pdf', '').replace('_', ' ')
    
    payload = {
        "q": clean_name,
        "k": 20,
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
            source = metadata.get('source', '')
            
            # Vérifier si c'est le bon document
            if (clean_name.lower() in doc_title.lower() or 
                doc_title.lower() in clean_name.lower() or
                filename.lower() in doc_title.lower()):
                return hit
        
        return None
    else:
        print(f"Erreur recherche: {response.status_code}")
        return None

def main():
    print("Tentative finale de déplacement des documents...")
    
    # Récupérer les informations de la tâche
    task_data = get_task_files()
    if not task_data:
        return False
    
    file_results = task_data.get('file_results', [])
    print(f"Fichiers dans la tâche: {len(file_results)}")
    
    # Chercher chaque fichier
    found_docs = []
    for file_result in file_results:
        if file_result.get('status') == 'ok':
            filename = file_result.get('name', '')
            added = file_result.get('added', 0)
            
            if added > 0:  # Seulement les fichiers avec des chunks ajoutés
                print(f"Recherche: {filename} ({added} chunks)")
                
                doc = search_documents_by_filename(filename)
                if doc:
                    found_docs.append(doc)
                    print(f"  ✓ Trouvé: {doc.get('metadata', {}).get('title', 'Sans titre')}")
                else:
                    print(f"  ✗ Non trouvé")
    
    print(f"\nDocuments trouvés: {len(found_docs)}")
    
    if not found_docs:
        print("Aucun document trouvé")
        return False
    
    # Afficher les documents trouvés
    print("\nDocuments à déplacer:")
    for i, doc in enumerate(found_docs):
        metadata = doc.get('metadata', {})
        title = metadata.get('title', 'Sans titre')
        source = metadata.get('source', '')
        print(f"  {i+1}. {title[:50]}... | {source[:60]}...")
    
    # Confirmer le déplacement
    print(f"\nDéplacement de {len(found_docs)} documents vers rag_maths_3e_dnb...")
    
    # Préparer les documents
    documents_to_add = []
    ids_to_add = []
    metadatas_to_add = []
    
    for doc in found_docs:
        documents_to_add.append(doc.get('document', ''))
        ids_to_add.append(doc['id'])
        
        metadata = doc.get('metadata', {})
        metadata['collection'] = 'rag_maths_3e_dnb'
        metadata['moved_from'] = 'rag_education'
        metadata['move_date'] = '2025-05-05'
        metadatas_to_add.append(metadata)
    
    # Insérer dans la nouvelle collection
    insert_url = f'{API_URL}/ingest'
    
    # Diviser en lots plus petits
    batch_size = 5
    total_success = 0
    
    for i in range(0, len(found_docs), batch_size):
        batch_docs = documents_to_add[i:i+batch_size]
        batch_ids = ids_to_add[i:i+batch_size]
        batch_metas = metadatas_to_add[i:i+batch_size]
        
        payload = {
            'documents': batch_docs,
            'ids': batch_ids,
            'metadatas': batch_metas,
            'collection': 'rag_maths_3e_dnb'
        }
        
        print(f"  Lot {i//batch_size + 1}/{(len(found_docs)-1)//batch_size + 1}...")
        
        response = requests.post(insert_url, headers=HEADERS, json=payload)
        if response.status_code == 200:
            result = response.json()
            print(f"    Succès: {result}")
            total_success += len(batch_docs)
        else:
            print(f"    Erreur: {response.status_code} - {response.text}")
    
    print(f"\nTotal inséré: {total_success}/{len(found_docs)} documents")
    
    # Supprimer les documents de rag_education
    if total_success > 0:
        print("Suppression des documents de rag_education...")
        delete_url = f'{API_URL}/collections/rag_education/delete'
        delete_payload = {'ids': ids_to_add[:total_success]}
        
        response = requests.post(delete_url, headers=HEADERS, json=delete_payload)
        if response.status_code == 200:
            print(f"Suppression réussie: {total_success} documents supprimés")
            return True
        else:
            print(f"Erreur suppression: {response.status_code}")
    
    return total_success > 0

if __name__ == "__main__":
    success = main()
    if success:
        print("\n✅ Opération terminée avec succès!")
        print("Les documents ont été déplacés vers rag_maths_3e_dnb")
    else:
        print("\n❌ Échec de l'opération")
        print("Les documents n'ont pas pu être déplacés")
