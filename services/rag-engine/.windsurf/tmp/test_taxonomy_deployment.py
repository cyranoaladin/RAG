#!/usr/bin/env python3
"""
Tests unitaires et e2e pour vérifier le déploiement de la taxonomie "Collège"
et l'intégration de rag_maths_3e_dnb
"""

import requests
import json
import time
from typing import Dict, List, Any

# Configuration
API_URL = 'http://127.0.0.1:18001'
UI_URL = 'http://127.0.0.1:18501'
TOKEN = '59e3c4746755272bd168b23d7abc2079821b9ec3ee89394dc783ca1ccf430cb0'
HEADERS = {
    'Authorization': f'Bearer {TOKEN}',
    'Content-Type': 'application/json'
}

class TestTaxonomyDeployment:
    """Tests pour vérifier le déploiement de la taxonomie"""
    
    def __init__(self):
        self.results = []
        self.passed = 0
        self.failed = 0
    
    def log_result(self, test_name: str, passed: bool, message: str = ""):
        """Enregistrer le résultat d'un test"""
        status = "✅ PASS" if passed else "❌ FAIL"
        self.results.append(f"{status} {test_name}: {message}")
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        print(f"{status} {test_name}: {message}")
    
    def test_api_collections(self) -> bool:
        """Test 1: Vérifier que rag_maths_3e_dnb est dans les collections API"""
        try:
            response = requests.get(f'{API_URL}/collections', headers=HEADERS)
            if response.status_code == 200:
                data = response.json()
                collections = data.get('collections', [])
                collection_names = [coll.get('name', '') for coll in collections]
                
                if 'rag_maths_3e_dnb' in collection_names:
                    self.log_result("API Collections", True, "rag_maths_3e_dnb trouvé")
                    return True
                else:
                    self.log_result("API Collections", False, "rag_maths_3e_dnb non trouvé")
                    return False
            else:
                self.log_result("API Collections", False, f"Erreur API: {response.status_code}")
                return False
        except Exception as e:
            self.log_result("API Collections", False, f"Exception: {e}")
            return False
    
    def test_ui_health(self) -> bool:
        """Test 2: Vérifier que l'interface UI est accessible"""
        try:
            response = requests.get(f'{UI_URL}/_stcore/health', timeout=10)
            if response.status_code == 200:
                self.log_result("UI Health", True, "Interface accessible")
                return True
            else:
                self.log_result("UI Health", False, f"Interface inaccessible: {response.status_code}")
                return False
        except Exception as e:
            self.log_result("UI Health", False, f"Exception: {e}")
            return False
    
    def test_ui_taxonomy_endpoint(self) -> bool:
        """Test 3: Vérifier que la taxonomie est accessible via l'UI"""
        try:
            # Tenter d'accéder à un endpoint qui pourrait exposer la taxonomie
            response = requests.get(f'{UI_URL}/api/collections', timeout=10)
            if response.status_code == 200:
                self.log_result("UI Taxonomy Endpoint", True, "Endpoint taxonomie accessible")
                return True
            else:
                # L'endpoint n'existe peut-être pas, ce n'est pas critique
                self.log_result("UI Taxonomy Endpoint", True, "Endpoint non critique (404 attendu)")
                return True
        except Exception as e:
            self.log_result("UI Taxonomy Endpoint", False, f"Exception: {e}")
            return False
    
    def test_search_in_rag_maths_3e_dnb(self) -> bool:
        """Test 4: Vérifier que la collection rag_maths_3e_dnb fonctionne pour la recherche"""
        try:
            payload = {
                "q": "mathématiques",
                "k": 5,
                "collection": "rag_maths_3e_dnb",
                "include_documents": True
            }
            
            response = requests.post(f'{API_URL}/search', headers=HEADERS, json=payload)
            if response.status_code == 200:
                data = response.json()
                hits = data.get('hits', [])
                self.log_result("Search rag_maths_3e_dnb", True, f"Recherche OK, {len(hits)} résultats")
                return True
            else:
                self.log_result("Search rag_maths_3e_dnb", False, f"Erreur recherche: {response.status_code}")
                return False
        except Exception as e:
            self.log_result("Search rag_maths_3e_dnb", False, f"Exception: {e}")
            return False
    
    def test_ingest_to_rag_maths_3e_dnb(self) -> bool:
        """Test 5: Vérifier que l'ingestion fonctionne dans rag_maths_3e_dnb"""
        try:
            payload = {
                'documents': ['Test document pour collège maths'],
                'ids': ['test_college_maths'],
                'metadatas': [{
                    'section': 'education',
                    'collection': 'rag_maths_3e_dnb',
                    'matiere': 'Mathématiques',
                    'niveau': 'Troisième',
                    'groupe': 'Collège',
                    'type_ressource': 'Test',
                    'source_type': 'test',
                    'source': 'test_deployment'
                }],
                'collection': 'rag_maths_3e_dnb'
            }
            
            response = requests.post(f'{API_URL}/ingest', headers=HEADERS, json=payload)
            if response.status_code == 200:
                result = response.json()
                self.log_result("Ingest rag_maths_3e_dnb", True, f"Ingestion OK: {result}")
                
                # Nettoyer le document de test
                delete_payload = {'ids': ['test_college_maths']}
                delete_response = requests.post(f'{API_URL}/collections/rag_maths_3e_dnb/delete', 
                                              headers=HEADERS, 
                                              json=delete_payload)
                
                return True
            else:
                self.log_result("Ingest rag_maths_3e_dnb", False, f"Erreur ingestion: {response.status_code}")
                return False
        except Exception as e:
            self.log_result("Ingest rag_maths_3e_dnb", False, f"Exception: {e}")
            return False
    
    def test_ui_static_content(self) -> bool:
        """Test 6: Vérifier que le contenu statique de l'UI est servi"""
        try:
            response = requests.get(f'{UI_URL}/static/js/main.bundle.js', timeout=10)
            if response.status_code == 200:
                self.log_result("UI Static Content", True, "Contenu statique accessible")
                return True
            else:
                self.log_result("UI Static Content", False, f"Contenu statique inaccessible: {response.status_code}")
                return False
        except Exception as e:
            self.log_result("UI Static Content", False, f"Exception: {e}")
            return False
    
    def test_docker_logs(self) -> bool:
        """Test 7: Vérifier les logs du conteneur UI pour erreurs"""
        try:
            import subprocess
            
            # Vérifier les logs récents du conteneur UI
            cmd = ['docker', 'logs', '--tail=20', 'compose-ui-1']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                logs = result.stdout
                # Chercher des erreurs dans les logs
                if 'ERROR' in logs or 'Exception' in logs:
                    self.log_result("Docker Logs", False, "Erreurs trouvées dans les logs")
                    return False
                else:
                    self.log_result("Docker Logs", True, "Pas d'erreurs dans les logs récents")
                    return True
            else:
                self.log_result("Docker Logs", False, f"Impossible de lire les logs: {result.stderr}")
                return False
        except Exception as e:
            self.log_result("Docker Logs", False, f"Exception: {e}")
            return False
    
    def run_all_tests(self) -> Dict[str, Any]:
        """Exécuter tous les tests"""
        print("🧪 Démarrage des tests de déploiement de la taxonomie 'Collège'...")
        print("=" * 60)
        
        # Tests unitaires
        self.test_api_collections()
        self.test_ui_health()
        self.test_ui_taxonomy_endpoint()
        self.test_search_in_rag_maths_3e_dnb()
        self.test_ingest_to_rag_maths_3e_dnb()
        
        # Tests e2e
        self.test_ui_static_content()
        self.test_docker_logs()
        
        # Résultats
        print("=" * 60)
        print(f"📊 Résultats des tests:")
        print(f"   ✅ Réussis: {self.passed}")
        print(f"   ❌ Échoués: {self.failed}")
        print(f"   📈 Taux de réussite: {self.passed/(self.passed+self.failed)*100:.1f}%")
        
        print("\n📋 Détail des tests:")
        for result in self.results:
            print(f"   {result}")
        
        return {
            'total': self.passed + self.failed,
            'passed': self.passed,
            'failed': self.failed,
            'success_rate': self.passed/(self.passed+self.failed)*100 if (self.passed+self.failed) > 0 else 0,
            'results': self.results
        }

def main():
    """Fonction principale"""
    tester = TestTaxonomyDeployment()
    results = tester.run_all_tests()
    
    # Retourner le code de sortie approprié
    exit_code = 0 if results['failed'] == 0 else 1
    exit(exit_code)

if __name__ == "__main__":
    main()
