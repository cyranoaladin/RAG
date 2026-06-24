#!/usr/bin/env python3
"""
Test final de validation pour confirmer que les changements sont bien déployés
"""

import subprocess
import json

def test_code_deployment():
    """Test 1: Vérifier que le code contient les changements"""
    print("🧪 Test 1: Validation du code déployé")
    
    # Vérifier la taxonomie Collège dans le code
    cmd = ['docker', 'exec', 'compose-ui-1', 'grep', '-n', 'Collège', '/app/app_v2.py']
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0 and 'Collège' in result.stdout:
        print("✅ Taxonomie 'Collège' trouvée dans le code")
        print(f"   Détail: {result.stdout.strip()}")
        return True
    else:
        print("❌ Taxonomie 'Collège' non trouvée dans le code")
        return False

def test_rag_maths_3e_dnb_in_code():
    """Test 2: Vérifier que rag_maths_3e_dnb est dans le code"""
    print("\n🧪 Test 2: Validation de rag_maths_3e_dnb dans le code")
    
    cmd = ['docker', 'exec', 'compose-ui-1', 'grep', '-n', 'rag_maths_3e_dnb', '/app/app_v2.py']
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0 and 'rag_maths_3e_dnb' in result.stdout:
        print("✅ rag_maths_3e_dnb trouvé dans le code")
        print(f"   Détail: {result.stdout.strip()}")
        return True
    else:
        print("❌ rag_maths_3e_dnb non trouvé dans le code")
        return False

def test_college_levels_in_code():
    """Test 3: Vérifier les niveaux de collège dans le code"""
    print("\n🧪 Test 3: Validation des niveaux de collège dans le code")
    
    cmd = ['docker', 'exec', 'compose-ui-1', 'grep', '-A', '10', 'NIVEAUX', '/app/app_v2.py']
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    college_levels = ['Sixième', 'Cinquième', 'Quatrième', 'Troisième']
    found_levels = [level for level in college_levels if level in result.stdout]
    
    if len(found_levels) >= 3:
        print(f"✅ Niveaux de collège trouvés: {found_levels}")
        return True
    else:
        print(f"❌ Niveaux de collège insuffisants: {found_levels}")
        return False

def test_college_subjects_in_code():
    """Test 4: Vérifier les matières de collège dans le code"""
    print("\n🧪 Test 4: Validation des matières de collège dans le code")
    
    cmd = ['docker', 'exec', 'compose-ui-1', 'grep', '-A', '20', '"Collège":', '/app/app_v2.py']
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    college_subjects = ['Mathématiques', 'Français', 'Histoire-géographie', 'Physique-chimie']
    found_subjects = [subject for subject in college_subjects if subject in result.stdout]
    
    if len(found_subjects) >= 3:
        print(f"✅ Matières de collège trouvées: {found_subjects}")
        return True
    else:
        print(f"❌ Matières de collège insuffisantes: {found_subjects}")
        return False

def test_api_collections():
    """Test 5: Vérifier que rag_maths_3e_dnb est dans les collections API"""
    print("\n🧪 Test 5: Validation des collections API")
    
    cmd = ['curl', '-s', '-X', 'GET', 'http://127.0.0.1:18001/collections', 
            '-H', 'Authorization: Bearer 59e3c4746755272bd168b23d7abc2079821b9ec3ee89394dc783ca1ccf430cb0']
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0 and 'rag_maths_3e_dnb' in result.stdout:
        print("✅ rag_maths_3e_dnb trouvé dans les collections API")
        return True
    else:
        print("❌ rag_maths_3e_dnb non trouvé dans les collections API")
        return False

def test_ui_container_status():
    """Test 6: Vérifier que le conteneur UI est en cours d'exécution"""
    print("\n🧪 Test 6: Validation du conteneur UI")
    
    cmd = ['docker', 'ps', '--filter', 'name=compose-ui-1', '--format', '{{.Status}}']
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0 and 'Up' in result.stdout:
        print("✅ Conteneur UI en cours d'exécution")
        print(f"   Status: {result.stdout.strip()}")
        return True
    else:
        print("❌ Conteneur UI non en cours d'exécution")
        return False

def main():
    """Fonction principale"""
    print("🔍 Validation finale du déploiement de la taxonomie 'Collège'")
    print("=" * 60)
    
    tests = [
        test_code_deployment,
        test_rag_maths_3e_dnb_in_code,
        test_college_levels_in_code,
        test_college_subjects_in_code,
        test_api_collections,
        test_ui_container_status
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ Erreur dans le test: {e}")
            failed += 1
    
    print("=" * 60)
    print(f"📊 Résultats de la validation finale:")
    print(f"   ✅ Réussis: {passed}")
    print(f"   ❌ Échoués: {failed}")
    print(f"   📈 Taux de réussite: {passed/(passed+failed)*100:.1f}%")
    
    if failed == 0:
        print("\n🎉 Tous les tests ont réussi!")
        print("✅ Le déploiement de la taxonomie 'Collège' est confirmé")
        print("✅ rag_maths_3e_dnb est bien intégré")
        print("✅ L'interface devrait maintenant afficher le groupe 'Collège'")
    else:
        print(f"\n⚠️ {failed} test(s) ont échoué")
        print("Veuillez vérifier les logs et le déploiement")
    
    return failed == 0

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
