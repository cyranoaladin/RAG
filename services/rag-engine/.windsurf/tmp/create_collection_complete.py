#!/usr/bin/env python3

import requests

# Configuration
API_URL = 'http://127.0.0.1:18001'
TOKEN = '59e3c4746755272bd168b23d7abc2079821b9ec3ee89394dc783ca1ccf430cb0'
HEADERS = {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {TOKEN}'
}

def create_collection_with_complete_metadata():
    """Créer la collection avec tous les champs requis"""
    print("Création de la collection rag_maths_3e_dnb avec métadonnées complètes...")
    
    # Préparer le payload avec tous les champs requis
    payload = {
        'documents': ['Document test pour créer la collection rag_maths_3e_dnb'],
        'ids': ['test_doc_rag_maths_3e_dnb'],
        'metadatas': [{
            'test': True,
            'collection': 'rag_maths_3e_dnb',
            'source_type': 'test',
            'source': 'test_creation_rag_maths_3e_dnb',
            'section': 'education',
            'matiere': 'Mathématiques',
            'niveau': '3ème',
            'type_ressource': 'Test'
        }],
        'collection': 'rag_maths_3e_dnb'
    }
    
    try:
        response = requests.post(f'{API_URL}/ingest', headers=HEADERS, json=payload)
        
        if response.status_code == 200:
            result = response.json()
            print(f"✓ Collection créée avec succès: {result}")
            
            # Supprimer le document de test
            delete_payload = {'ids': ['test_doc_rag_maths_3e_dnb']}
            delete_response = requests.post(f'{API_URL}/collections/rag_maths_3e_dnb/delete', 
                                          headers=HEADERS, 
                                          json=delete_payload)
            
            if delete_response.status_code == 200:
                print("✓ Document de test supprimé")
            else:
                print(f"⚠️ Impossible de supprimer le document test: {delete_response.status_code}")
            
            return True
        else:
            print(f"❌ Erreur création collection: {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Exception: {e}")
        return False

def verify_collection():
    """Vérifier que la collection existe maintenant"""
    print("\nVérification de la collection...")
    
    response = requests.get(f'{API_URL}/collections', headers=HEADERS)
    
    if response.status_code == 200:
        data = response.json()
        collections = data.get('collections', [])
        
        print("Collections disponibles:")
        for coll in collections:
            print(f"  - {coll.get('name', 'Sans nom')}")
        
        rag_maths_exists = any(coll.get('name') == 'rag_maths_3e_dnb' for coll in collections)
        print(f"\nrag_maths_3e_dnb présente: {rag_maths_exists}")
        
        return rag_maths_exists
    else:
        print(f"Erreur vérification: {response.status_code}")
        return False

def main():
    print("Création de la collection rag_maths_3e_dnb")
    
    # Créer la collection
    success = create_collection_with_complete_metadata()
    
    if success:
        # Vérifier
        exists = verify_collection()
        
        if exists:
            print("\n✅ Collection rag_maths_3e_dnb créée et vérifiée avec succès!")
            print("Vous pouvez maintenant sélectionner 'rag_maths_3e_dnb' comme collection cible dans l'interface.")
        else:
            print("\n⚠️ Collection créée mais non visible dans la liste")
    else:
        print("\n❌ Échec de la création de la collection")

if __name__ == "__main__":
    main()
