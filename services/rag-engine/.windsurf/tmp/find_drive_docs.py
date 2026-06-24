#!/usr/bin/env python3
import json
import subprocess


# Exécuter curl pour interroger l'API search
def search_documents(collection, limit=100):
    cmd = [
        'curl', '-s', '-X', 'POST',
        'http://127.0.0.1:18001/search',
        '-H', 'Content-Type: application/json',
        '-H', 'Authorization: Bearer 59e3c4746755272bd168b23d7abc2079821b9ec3ee89394dc783ca1ccf430cb0',
        '-d', json.dumps({
            "q": "",
            "k": limit,
            "collection": collection,
            "include_documents": True
        })
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return json.loads(result.stdout)
        else:
            print(f"Erreur curl: {result.stderr}")
            return None
    except Exception as e:
        print(f"Exception: {e}")
        return None

# Rechercher les documents dans rag_education
drive_folder_id = '1YMGGaLUafNjHdXi03JVpjzntPa310HeR'
print(f"Recherche des documents dans rag_education avec source contenant {drive_folder_id}")

data = search_documents('rag_education', limit=100)

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
    else:
        print("Aucun document trouvé provenant de ce dossier Drive")
        
        # Afficher les premiers documents pour debug
        print("\nPremiers documents dans rag_education (pour debug):")
        for i, hit in enumerate(hits[:5]):
            metadata = hit.get('metadata', {})
            source = metadata.get('source', '')
            title = metadata.get('title', '')
            print(f"  {i+1}. {title[:50]}... | {source[:50]}...")
else:
    print("Impossible de récupérer les documents")
