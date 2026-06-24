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

def check_collections():
    """Vérifier les collections existantes"""
    response = requests.get(f'{API_URL}/collections', headers=HEADERS)
    
    if response.status_code == 200:
        data = response.json()
        collections = data.get('collections', [])
        
        print("Collections disponibles:")
        for coll in collections:
            print(f"  - {coll.get('name', 'Sans nom')}")
        
        rag_maths_exists = any(coll.get('name') == 'rag_maths_3e_dnb' for coll in collections)
        print(f"\nrag_maths_3e_dnb présente: {rag_maths_exists}")
        
        return collections, rag_maths_exists
    else:
        print(f"Erreur récupération collections: {response.status_code}")
        return [], False

def create_collection_direct():
    """Créer la collection directement via ChromaDB"""
    print("\nCréation de la collection rag_maths_3e_dnb...")
    
    # Utiliser curl pour créer la collection via ChromaDB
    import subprocess
    
    cmd = [
        'curl', '-s', '-X', 'POST',
        'http://localhost:8000/api/v1/collections',
        '-H', 'Content-Type: application/json',
        '-d', json.dumps({
            'name': 'rag_maths_3e_dnb',
            'metadata': {'hnsw:space': 'cosine'}
        })
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            print("✓ Collection rag_maths_3e_dnb créée avec succès")
            return True
        else:
            print(f"Erreur création collection: {result.stderr}")
            return False
    except Exception as e:
        print(f"Exception création collection: {e}")
        return False

def create_collection_via_api():
    """Essayer de créer la collection via l'API RAG"""
    print("\nTentative de création via API RAG...")
    
    # Essayer avec l'endpoint d'ingestion
    response = requests.post(f'{API_URL}/ingest', headers=HEADERS, json={
        'documents': ['Document test pour créer la collection'],
        'ids': ['test_doc'],
        'metadatas': [{'test': True, 'collection': 'rag_maths_3e_dnb'}],
        'collection': 'rag_maths_3e_dnb'
    })
    
    if response.status_code == 200:
        print("✓ Collection rag_maths_3e_dnb créée via API RAG")
        
        # Supprimer le document de test
        delete_response = requests.post(f'{API_URL}/collections/rag_maths_3e_dnb/delete', 
                                       headers=HEADERS, 
                                       json={'ids': ['test_doc']})
        if delete_response.status_code == 200:
            print("✓ Document de test supprimé")
        
        return True
    else:
        print(f"Erreur création via API RAG: {response.status_code} - {response.text}")
        return False

def main():
    print("Vérification et création de la collection rag_maths_3e_dnb")
    
    # Vérifier les collections existantes
    collections, exists = check_collections()
    
    if not exists:
        print("\nLa collection rag_maths_3e_dnb n'existe pas, tentative de création...")
        
        # Essayer différentes méthodes de création
        success = False
        
        # Méthode 1: Via ChromaDB direct
        if not success:
            success = create_collection_direct()
        
        # Méthode 2: Via API RAG
        if not success:
            success = create_collection_via_api()
        
        if success:
            print("\n✅ Collection rag_maths_3e_dnb créée avec succès")
            
            # Vérifier à nouveau
            print("\nVérification finale:")
            check_collections()
        else:
            print("\n❌ Impossible de créer la collection rag_maths_3e_dnb")
    else:
        print("\n✅ La collection rag_maths_3e_dnb existe déjà")

if __name__ == "__main__":
    main()
