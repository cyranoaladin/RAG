#!/usr/bin/env python3
import sys
import os

# Ajouter le chemin de l'API
sys.path.append('/app')

try:
    from ingestor.api import get_chroma_client
    import chromadb
    
    # Connexion à ChromaDB
    client = get_chroma_client()
    
    # Vérifier la collection rag_education
    try:
        collection = client.get_collection('rag_education')
        print(f'Collection rag_education trouvée, {collection.count()} documents')
        
        # Rechercher les documents avec le source Drive spécifique
        drive_folder_id = '1YMGGaLUafNjHdXi03JVpjzntPa310HeR'
        
        # Obtenir tous les documents de la collection
        results = collection.get(
            include=['metadatas', 'documents']
        )
        
        print(f'Total documents dans rag_education: {len(results.get("ids", []))}')
        
        # Filtrer les documents contenant l'ID du dossier Drive
        found_docs = []
        found_ids = []
        found_titles = []
        
        for i, doc_id in enumerate(results.get('ids', [])):
            metadata = results.get('metadatas', [])[i] if i < len(results.get('metadatas', [])) else {}
            source = metadata.get('source', '')
            title = metadata.get('title', 'Sans titre')
            
            if drive_folder_id in source:
                found_docs.append({
                    'id': doc_id,
                    'title': title,
                    'source': source,
                    'metadata': metadata
                })
                found_ids.append(doc_id)
                found_titles.append(title)
        
        print(f'Documents provenant du dossier Drive {drive_folder_id}: {len(found_docs)}')
        
        if found_docs:
            print('\nDétails des documents à déplacer:')
            for i, doc in enumerate(found_docs):
                print(f"  {i+1}. ID: {doc['id']}")
                print(f"     Titre: {doc['title']}")
                print(f"     Source: {doc['source']}")
                print()
            
            # Exporter les IDs pour le déplacement
            print("IDs à déplacer:")
            for i, doc_id in enumerate(found_ids):
                print(f"  {i+1}. {doc_id}")
                
            # Créer un fichier avec les IDs pour le déplacement
            with open('/tmp/docs_to_move.txt', 'w') as f:
                for doc_id in found_ids:
                    f.write(f"{doc_id}\n")
            print(f"\nIDs sauvegardés dans /tmp/docs_to_move.txt")
        else:
            print("Aucun document trouvé provenant de ce dossier Drive")
            
            # Afficher quelques sources pour debug
            print("\nQuelques sources dans la collection (pour debug):")
            for i, doc_id in enumerate(results.get('ids', [])[:10]):
                metadata = results.get('metadatas', [])[i] if i < len(results.get('metadatas', [])) else {}
                source = metadata.get('source', '')
                title = metadata.get('title', '')
                print(f"  {i+1}. {title[:50]}... | {source[:80]}...")
    
    except Exception as e:
        print(f'Erreur avec la collection rag_education: {e}')
        
        # Lister toutes les collections disponibles
        try:
            collections = client.list_collections()
            print(f'\nCollections disponibles:')
            for coll in collections:
                print(f'  - {coll.name}: {coll.count()} documents')
        except Exception as e2:
            print(f'Erreur lors de la liste des collections: {e2}')

except ImportError as e:
    print(f'Erreur d\'import: {e}')
    print('Modules disponibles:')
    import pkgutil
    for importer, modname, ispkg in pkgutil.iter_modules():
        if 'chroma' in modname.lower() or 'ingest' in modname.lower():
            print(f'  - {modname}')
except Exception as e:
    print(f'Erreur générale: {e}')
