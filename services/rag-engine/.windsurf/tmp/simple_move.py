#!/usr/bin/env python3

import requests

# Configuration
API_URL = 'http://127.0.0.1:18001'
TOKEN = '59e3c4746755272bd168b23d7abc2079821b9ec3ee89394dc783ca1ccf430cb0'
HEADERS = {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {TOKEN}'
}

def search_and_move():
    """Chercher les documents maths et les déplacer"""
    
    # Titres des documents maths à chercher
    math_titles = [
        "16_Maths_4eme_attendus.pdf",
        "Guide_resolution_de_problemes_mathematiques_au_college.pdf",
        "Geometrie_Espace.pdf",
        "Geometrie_Plane.pdf",
        "18_Maths_3eme_attendus.pdf",
        "Algorithmiqueetprogrammation.pdf",
        "Annexe_2_Programme_de_mathématiques_pour_le_cycle_4.pdf",
        "14_Maths_5eme_attendus.pdf",
        "01_ra16c3c4mathmathjeu.pdf",
        "26_Maths_c4_reperes.pdf"
    ]
    
    print("Recherche des documents maths dans rag_education...")
    
    # Chercher chaque document
    found_docs = []
    for title in math_titles:
        print(f"  Recherche: {title}")
        
        # Utiliser une recherche simple
        search_url = f'{API_URL}/search'
        payload = {
            "q": title.replace('.pdf', '').replace('_', ' '),
            "k": 5,
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
                if title.replace('.pdf', '').replace('_', ' ').lower() in doc_title.lower():
                    found_docs.append(hit)
                    print(f"    ✓ Trouvé: {doc_title}")
                    break
        else:
            print(f"    Erreur recherche: {response.status_code}")
    
    print(f"\nTotal documents trouvés: {len(found_docs)}")
    
    if not found_docs:
        print("Aucun document trouvé")
        return False
    
    # Créer la collection si nécessaire
    print("\nVérification/Création de la collection rag_maths_3e_dnb...")
    
    # Essayer d'insérer un document pour créer la collection
    test_doc = found_docs[0]
    insert_url = f'{API_URL}/ingest'
    payload = {
        'documents': [test_doc.get('document', '')],
        'ids': [test_doc['id'] + '_test'],
        'metadatas': [{'test': True, 'collection': 'rag_maths_3e_dnb'}],
        'collection': 'rag_maths_3e_dnb'
    }
    
    response = requests.post(insert_url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        print("Collection rag_maths_3e_dnb créée/prête")
        
        # Supprimer le document de test
        delete_url = f'{API_URL}/collections/rag_maths_3e_dnb/delete'
        delete_payload = {'ids': [test_doc['id'] + '_test']}
        requests.post(delete_url, headers=HEADERS, json=delete_payload)
    else:
        print(f"Erreur création collection: {response.status_code}")
    
    # Insérer tous les documents dans la nouvelle collection
    print(f"\nInsertion de {len(found_docs)} documents dans rag_maths_3e_dnb...")
    
    documents_to_add = []
    ids_to_add = []
    metadatas_to_add = []
    
    for doc in found_docs:
        documents_to_add.append(doc.get('document', ''))
        ids_to_add.append(doc['id'])
        
        # Mettre à jour les métadonnées
        metadata = doc.get('metadata', {})
        metadata['collection'] = 'rag_maths_3e_dnb'
        metadata['moved_from'] = 'rag_education'
        metadatas_to_add.append(metadata)
    
    # Insérer par lots pour éviter les limites
    batch_size = 10
    total_inserted = 0
    
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
        
        response = requests.post(insert_url, headers=HEADERS, json=payload)
        if response.status_code == 200:
            result = response.json()
            print(f"  Lot {i//batch_size + 1}: {result}")
            total_inserted += len(batch_docs)
        else:
            print(f"  Erreur lot {i//batch_size + 1}: {response.status_code} - {response.text}")
    
    print(f"\nTotal inséré: {total_inserted} documents")
    
    # Supprimer les documents de rag_education
    if total_inserted > 0:
        print("\nSuppression des documents de rag_education...")
        delete_url = f'{API_URL}/collections/rag_education/delete'
        delete_payload = {'ids': ids_to_add}
        
        response = requests.post(delete_url, headers=HEADERS, json=delete_payload)
        if response.status_code == 200:
            print(f"Suppression réussie: {len(ids_to_add)} documents supprimés")
            return True
        else:
            print(f"Erreur suppression: {response.status_code} - {response.text}")
    
    return False

if __name__ == "__main__":
    success = search_and_move()
    if success:
        print("\nOpération terminée avec succès!")
    else:
        print("\nÉchec de l'opération")
