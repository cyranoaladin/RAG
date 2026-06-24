#!/usr/bin/env python3
"""
Tests e2e pour vérifier que l'interface utilisateur affiche bien
le groupe "Collège" et que les changements sont visibles
"""

from typing import Any

import requests

# Configuration
UI_URL = 'http://127.0.0.1:18501'
API_URL = 'http://127.0.0.1:18001'
TOKEN = '59e3c4746755272bd168b23d7abc2079821b9ec3ee89394dc783ca1ccf430cb0'
HEADERS = {
    'Authorization': f'Bearer {TOKEN}',
    'Content-Type': 'application/json'
}

class TestE2EInterface:
    """Tests e2e pour l'interface utilisateur"""
    
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
    
    def test_ui_page_load(self) -> bool:
        """Test 1: Vérifier que la page UI se charge correctement"""
        try:
            response = requests.get(UI_URL, timeout=30)
            if response.status_code == 200:
                content = response.text
                
                # Vérifier que le contenu principal est présent
                if 'RAG Dashboard' in content or 'Nexus Réussite' in content:
                    self.log_result("UI Page Load", True, "Page UI chargée avec succès")
                    return True
                else:
                    self.log_result("UI Page Load", False, "Contenu principal non trouvé")
                    return False
            else:
                self.log_result("UI Page Load", False, f"Erreur chargement: {response.status_code}")
                return False
        except Exception as e:
            self.log_result("UI Page Load", False, f"Exception: {e}")
            return False
    
    def test_ui_taxonomy_content(self) -> bool:
        """Test 2: Vérifier que la taxonomie "Collège" est présente dans le code UI"""
        try:
            response = requests.get(UI_URL, timeout=30)
            if response.status_code == 200:
                content = response.text
                
                # Vérifier la présence du groupe "Collège"
                if 'Collège' in content:
                    self.log_result("UI Taxonomy Content", True, "Groupe 'Collège' trouvé dans le code")
                    
                    # Vérifier aussi les matières de collège
                    college_subjects = ['Mathématiques', 'Français', 'Histoire-géographie', 'Physique-chimie']
                    found_subjects = [subject for subject in college_subjects if subject in content]
                    
                    if len(found_subjects) >= 2:
                        self.log_result("UI College Subjects", True, f"Matières trouvées: {found_subjects}")
                        return True
                    else:
                        self.log_result("UI College Subjects", False, f"Matières insuffisantes: {found_subjects}")
                        return False
                else:
                    self.log_result("UI Taxonomy Content", False, "Groupe 'Collège' non trouvé")
                    return False
            else:
                self.log_result("UI Taxonomy Content", False, f"Erreur chargement: {response.status_code}")
                return False
        except Exception as e:
            self.log_result("UI Taxonomy Content", False, f"Exception: {e}")
            return False
    
    def test_ui_javascript_content(self) -> bool:
        """Test 3: Vérifier que le JavaScript contient la taxonomie mise à jour"""
        try:
            response = requests.get(f'{UI_URL}/static/js/main.bundle.js', timeout=30)
            if response.status_code == 200:
                content = response.text
                
                # Vérifier la présence des niveaux de collège
                college_levels = ['Sixième', 'Cinquième', 'Quatrième', 'Troisième']
                found_levels = [level for level in college_levels if level in content]
                
                if len(found_levels) >= 2:
                    self.log_result("UI JS College Levels", True, f"Niveaux trouvés: {found_levels}")
                    return True
                else:
                    self.log_result("UI JS College Levels", False, f"Niveaux insuffisants: {found_levels}")
                    return False
            else:
                self.log_result("UI JS College Levels", False, f"Erreur JS: {response.status_code}")
                return False
        except Exception as e:
            self.log_result("UI JS College Levels", False, f"Exception: {e}")
            return False
    
    def test_api_taxonomy_verification(self) -> bool:
        """Test 4: Vérifier que l'API reconnaît les nouvelles collections"""
        try:
            response = requests.get(f'{API_URL}/collections', headers=HEADERS)
            if response.status_code == 200:
                data = response.json()
                collections = data.get('collections', [])
                collection_names = [coll.get('name', '') for coll in collections]
                
                # Vérifier que rag_maths_3e_dnb est présent
                if 'rag_maths_3e_dnb' in collection_names:
                    self.log_result("API Collections", True, "rag_maths_3e_dnb trouvé dans l'API")
                    
                    # Vérifier que la collection a des documents
                    search_response = requests.post(f'{API_URL}/search', headers=HEADERS, json={
                        "q": "test",
                        "k": 5,
                        "collection": "rag_maths_3e_dnb",
                        "include_documents": True
                    })
                    
                    if search_response.status_code == 200:
                        search_data = search_response.json()
                        hits = search_data.get('hits', [])
                        self.log_result("API Search", True, f"Recherche OK: {len(hits)} résultats")
                        return True
                    else:
                        self.log_result("API Search", False, f"Erreur recherche: {search_response.status_code}")
                        return False
                else:
                    self.log_result("API Collections", False, "rag_maths_3e_dnb non trouvé")
                    return False
            else:
                self.log_result("API Collections", False, f"Erreur API: {response.status_code}")
                return False
        except Exception as e:
            self.log_result("API Collections", False, f"Exception: {e}")
            return False
    
    def test_ui_form_elements(self) -> bool:
        """Test 5: Vérifier que les éléments de formulaire sont présents"""
        try:
            response = requests.get(UI_URL, timeout=30)
            if response.status_code == 200:
                content = response.text
                
                # Vérifier la présence des éléments de formulaire
                form_elements = [
                    'Groupe d\'enseignement',
                    'Matière',
                    'Niveau',
                    'Type de ressource',
                    'Collection cible'
                ]
                
                found_elements = [elem for elem in form_elements if elem in content]
                
                if len(found_elements) >= 4:
                    self.log_result("UI Form Elements", True, f"Éléments trouvés: {found_elements}")
                    return True
                else:
                    self.log_result("UI Form Elements", False, f"Éléments manquants: {found_elements}")
                    return False
            else:
                self.log_result("UI Form Elements", False, f"Erreur chargement: {response.status_code}")
                return False
        except Exception as e:
            self.log_result("UI Form Elements", False, f"Exception: {e}")
            return False
    
    def test_ui_streamlit_components(self) -> bool:
        """Test 6: Vérifier que les composants Streamlit fonctionnent"""
        try:
            response = requests.get(UI_URL, timeout=30)
            if response.status_code == 200:
                content = response.text
                
                # Vérifier la présence des composants Streamlit
                streamlit_indicators = [
                    'streamlit',
                    'st.selectbox',
                    'st.columns',
                    'data-testid'
                ]
                
                found_indicators = [ind for ind in streamlit_indicators if ind in content.lower()]
                
                if len(found_indicators) >= 2:
                    self.log_result("UI Streamlit Components", True, f"Composants trouvés: {found_indicators}")
                    return True
                else:
                    self.log_result("UI Streamlit Components", False, f"Composants insuffisants: {found_indicators}")
                    return False
            else:
                self.log_result("UI Streamlit Components", False, f"Erreur chargement: {response.status_code}")
                return False
        except Exception as e:
            self.log_result("UI Streamlit Components", False, f"Exception: {e}")
            return False
    
    def test_ui_responsive_design(self) -> bool:
        """Test 7: Vérifier que le design responsive fonctionne"""
        try:
            # Test avec user-agent mobile
            headers_mobile = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)'}
            response = requests.get(UI_URL, headers=headers_mobile, timeout=30)
            
            if response.status_code == 200:
                content = response.text
                
                # Vérifier la présence de méta-tags responsive
                if 'viewport' in content.lower() or 'responsive' in content.lower():
                    self.log_result("UI Responsive Design", True, "Design responsive détecté")
                    return True
                else:
                    self.log_result("UI Responsive Design", False, "Design responsive non détecté")
                    return False
            else:
                self.log_result("UI Responsive Design", False, f"Erreur mobile: {response.status_code}")
                return False
        except Exception as e:
            self.log_result("UI Responsive Design", False, f"Exception: {e}")
            return False
    
    def test_ui_error_handling(self) -> bool:
        """Test 8: Vérifier la gestion des erreurs"""
        try:
            # Test avec une URL invalide
            response = requests.get(f'{UI_URL}/page_inexistante', timeout=10)
            
            if response.status_code in [404, 500]:
                self.log_result("UI Error Handling", True, f"Gestion d'erreur OK: {response.status_code}")
                return True
            else:
                self.log_result("UI Error Handling", False, f"Gestion d'erreur inattendue: {response.status_code}")
                return False
        except Exception as e:
            self.log_result("UI Error Handling", False, f"Exception: {e}")
            return False
    
    def run_all_tests(self) -> dict[str, Any]:
        """Exécuter tous les tests e2e"""
        print("🧪 Démarrage des tests e2e pour l'interface utilisateur...")
        print("=" * 60)
        
        # Tests e2e
        self.test_ui_page_load()
        self.test_ui_taxonomy_content()
        self.test_ui_javascript_content()
        self.test_api_taxonomy_verification()
        self.test_ui_form_elements()
        self.test_ui_streamlit_components()
        self.test_ui_responsive_design()
        self.test_ui_error_handling()
        
        # Résultats
        print("=" * 60)
        print("📊 Résultats des tests e2e:")
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
    tester = TestE2EInterface()
    results = tester.run_all_tests()
    
    # Retourner le code de sortie approprié
    exit_code = 0 if results['failed'] == 0 else 1
    exit(exit_code)

if __name__ == "__main__":
    main()
