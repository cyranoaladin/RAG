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

def search_by_title(collection_name, titles):
    """Chercher des documents par leurs titres"""
    search_url = f'{API_URL}/search'
    found_docs = []
    
    for title in titles:
        payload = {
            "q": title,
            "k": 10,
            "collection": collection_name,
            "include_documents": True
        }
        
        response = requests.post(search_url, headers=HEADERS, json=payload)
        if response.status_code == 200:
            data = response.json()
            hits = data.get('hits', [])
            
            for hit in hits:
                metadata = hit.get('metadata', {})
                doc_title = metadata.get('title', '')
                
                # Vérifier si le titre correspond
                if title.lower() in doc_title.lower() or doc_title.lower() in title.lower():
                    found_docs.append(hit)
                    print(f"  ✓ Trouvé: {hit['id'][:30]}... | {doc_title}")
    
    return found_docs

def main():
    # Liste des fichiers de la tâche Drive (d'après le statut de la tâche)
    task_files = [
        "16_Maths_4eme_attendus.pdf",
        "Commecritoralpourmontage.pdf",
        "Guide_resolution_de_problemes_mathematiques_au_college.pdf",
        "Geometrie_Espace.pdf",
        "Geometrie_Plane.pdf",
        "Ladifferentiationpedagogique.pdf",
        "Nombrescalculcalcullitteral.pdf",
        "Puissances.pdf",
        "Typesdetaches.pdf",
        "Raeevaluationsoclecycle.pdf",
        "Travaildeseleves.pdf",
        "C4mathmathmaitrlang.pdf",
        "Mathc4grandmesu.pdf",
        "Arithmetiquecomputiliser.pdf",
        "Chercher.pdf",
        "Comprendreetutiliserfonctions.pdf",
        "Grilles_de_positionnement_des_livres_de_mathematiques_au_college.pdf",
        "Algorithmiqueetprogrammation.pdf",
        "18_Maths_3eme_attendus.pdf",
        "MultiMathsmathematiquesmondeeconomiqueetprofessionnel.pdf",
        "Probabilites.pdf",
        "Compcalculer.pdf",
        "Ev16c4Mathssituationsevaluation.pdf",
        "C4mathmathetquotidien.pdf",
        "Modeliser.pdf",
        "Representer.pdf",
        "Annexe_2_Programme_de_mathématiques_pour_le_cycle_4.pdf",
        "14_Maths_5eme_attendus.pdf",
        "01_ra16c3c4mathmathjeu.pdf",
        "Nombresrelatifscomparercalculerresoudre.pdf",
        "Raisonner.pdf",
        "Resoupropo.pdf",
        "Fractionscomp_calresoudre.pdf",
        "Nombresdecimauxcomparercalculerresoudre.pdf",
        "26_Maths_c4_reperes.pdf"
    ]
    
    print(f"Recherche des {len(task_files)} documents de la tâche Drive")
    print(f"Dossier Drive cible: 1YMGGaLUafNjHdXi03JVpjzntPa310HeR")
    
    # Chercher dans rag_education
    print(f"\nRecherche dans rag_education...")
    found_docs = search_by_title('rag_education', task_files)
    
    if found_docs:
        print(f"\n✓ {len(found_docs)} documents trouvés dans rag_education")
        
        # Afficher les sources pour vérifier
        print(f"\nSources des documents trouvés:")
        for doc in found_docs:
            metadata = doc.get('metadata', {})
            source = metadata.get('source', '')
            title = metadata.get('title', '')
            print(f"  - {title[:50]}... | {source}")
        
        # Déplacer les documents
        return move_documents(found_docs, 'rag_maths_3e_dnb')
    else:
        print(f"\n✗ Aucun document trouvé dans rag_education")
        
        # Chercher dans d'autres collections
        collections = ['rag_francais_premiere', 'rag_maths_premiere', 'rag_divers', 'ressources_pedagogiques_terminale']
        
        for coll in collections:
            print(f"\nRecherche dans {coll}...")
            found_docs = search_by_title(coll, task_files)
            if found_docs:
                print(f"✓ {len(found_docs)} documents trouvés dans {coll}")
                return move_documents(found_docs, 'rag_maths_3e_dnb')
        
        print(f"\n✗ Aucun document trouvé dans aucune collection")
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
        print(f"Suppression des documents de la collection source...")
        
        # Identifier la collection source
        source_collection = None
        if docs:
            # Prendre la collection du premier document
            source_collection = docs[0].get('metadata', {}).get('collection', 'rag_education')
        
        if source_collection:
            delete_url = f'{API_URL}/collections/{source_collection}/delete'
            delete_payload = {
                'ids': ids_to_add
            }
            
            delete_response = requests.post(delete_url, headers=HEADERS, json=delete_payload)
            if delete_response.status_code == 200:
                print(f"Suppression réussie: {len(ids_to_add)} documents supprimés de {source_collection}")
                return True
            else:
                print(f"Erreur suppression: {delete_response.status_code} - {delete_response.text}")
                return False
    else:
        print(f"Erreur insertion: {response.status_code} - {response.text}")
        return False

if __name__ == "__main__":
    success = main()
    if success:
        print(f"\nOpération terminée avec succès!")
    else:
        print(f"\nÉchec de l'opération")
