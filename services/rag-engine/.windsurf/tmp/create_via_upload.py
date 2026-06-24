#!/usr/bin/env python3
import json

import requests

# Configuration
API_URL = 'http://127.0.0.1:18001'
TOKEN = '59e3c4746755272bd168b23d7abc2079821b9ec3ee89394dc783ca1ccf430cb0'
HEADERS = {
    'Authorization': f'Bearer {TOKEN}'
}

def create_collection_via_upload():
    """Créer la collection via un upload simulé"""
    print("Création de la collection rag_maths_3e_dnb via upload simulé...")
    
    # Créer un fichier temporaire pour le test
    test_content = "Document test pour créer la collection rag_maths_3e_dnb"
    
    # Préparer les métadonnées complètes
    metadata = {
        'section': 'education',
        'collection': 'rag_maths_3e_dnb',
        'matiere': 'Mathématiques',
        'niveau': '3ème',
        'groupe': 'Enseignements communs',
        'type_ressource': 'Test'
    }
    
    # Simuler un upload pour créer la collection
    files = {
        'files': ('test_rag_maths_3e_dnb.txt', test_content, 'text/plain')
    }
    
    params = {
        'metadata': json.dumps(metadata)
    }
    
    try:
        response = requests.post(f'{API_URL}/ingest/upload-files', 
                                headers=HEADERS, 
                                files=files, 
                                params=params)
        
        if response.status_code == 200:
            result = response.json()
            print(f"✓ Collection créée via upload: {result}")
            
            # Récupérer l'ID du document pour le supprimer
            if result.get('results') and len(result['results']) > 0:
                doc_id = result['results'][0].get('id')
                if doc_id:
                    # Supprimer le document de test
                    delete_payload = {'ids': [doc_id]}
                    delete_response = requests.post(f'{API_URL}/collections/rag_maths_3e_dnb/delete', 
                                                  headers=HEADERS, 
                                                  json=delete_payload)
                    
                    if delete_response.status_code == 200:
                        print("✓ Document de test supprimé")
                    else:
                        print(f"⚠️ Impossible de supprimer le document test: {delete_response.status_code}")
            
            return True
        else:
            print(f"❌ Erreur création via upload: {response.status_code}")
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
    print("Création de la collection rag_maths_3e_dnb via upload")
    
    # Créer la collection
    success = create_collection_via_upload()
    
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
