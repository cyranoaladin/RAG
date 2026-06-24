#!/usr/bin/env python3

# Script pour ajouter "collège" à la taxonomie d'éducation

def add_college_to_taxonomy():
    """Ajouter le groupe 'collège' à la taxonomie EDUCATION_TAXONOMY"""
    
    # Chemin du fichier UI
    ui_file = '/srv/nexusreussite/rag-ui/compose/ui/app_v2.py'
    
    # Lire le fichier
    with open(ui_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Définir la nouvelle taxonomie pour le collège
    college_taxonomy = '''    "Collège": [
        "Français",
        "Mathématiques",
        "Histoire-géographie",
        "Physique-chimie",
        "Sciences de la vie et de la Terre",
        "Technologie",
        "Langues vivantes (Anglais, Allemand, Espagnol, Italien, Portugais, Chinois, Arabe, Russe)",
        "Latin",
        "Grec",
        "Éducation physique et sportive",
        "Éducation musicale",
        "Arts plastiques",
        "Enseignement moral et civique",
        "Accompagnement personnalisé",
        "Parcours éducatifs (Avenir, Santé, Citoyenneté)",
    ],
'''
    
    # Trouver l'emplacement où insérer la taxonomie collège
    # Juste après la définition de EDUCATION_TAXONOMY
    import re
    
    # Pattern pour trouver la fin de la définition "Enseignements communs"
    pattern = r'("Enseignements communs": \[.*?\],)'
    
    # Remplacer pour ajouter le groupe "Collège" après "Enseignements communs"
    replacement = r'\1\n' + college_taxonomy
    
    # Appliquer la modification
    new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    
    # Vérifier si la modification a été appliquée
    if new_content != content:
        print("✅ Taxonomie 'Collège' ajoutée avec succès")
        
        # Écrire le fichier modifié
        with open(ui_file, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        print(f"✅ Fichier {ui_file} mis à jour")
        return True
    else:
        print("❌ La taxonomie n'a pas pu être ajoutée (pattern non trouvé)")
        
        # Alternative: ajouter après la première ligne de EDUCATION_TAXONOMY
        pattern_alt = r'(EDUCATION_TAXONOMY: dict\[str, list\[str\]\] = \{)'
        replacement_alt = r'\1\n' + college_taxonomy
        
        new_content_alt = re.sub(pattern_alt, replacement_alt, content)
        
        if new_content_alt != content:
            with open(ui_file, 'w', encoding='utf-8') as f:
                f.write(new_content_alt)
            print("✅ Taxonomie 'Collège' ajoutée avec succès (méthode alternative)")
            return True
        else:
            print("❌ Impossible d'ajouter la taxonomie")
            return False

def add_rag_maths_3e_dnb_to_collections():
    """Ajouter rag_maths_3e_dnb à la liste des collections"""
    
    ui_file = '/srv/nexusreussite/rag-ui/compose/ui/app_v2.py'
    
    with open(ui_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Pattern pour trouver la liste ALL_COLLECTIONS
    pattern = r'(ALL_COLLECTIONS = \[.*?\])'
    
    # Vérifier si rag_maths_3e_dnb est déjà dans la liste
    if 'rag_maths_3e_dnb' in content:
        print("✅ rag_maths_3e_dnb est déjà dans ALL_COLLECTIONS")
        return True
    
    # Ajouter rag_maths_3e_dnb à la liste
    replacement = 'ALL_COLLECTIONS = [\n    "rag_francais_premiere",\n    "rag_maths_premiere",\n    "rag_education",\n    "rag_web3",\n    "rag_divers",\n    "rag_maths_3e_dnb",\n]'
    
    new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    
    if new_content != content:
        with open(ui_file, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("✅ rag_maths_3e_dnb ajouté à ALL_COLLECTIONS")
        return True
    else:
        print("❌ Impossible d'ajouter rag_maths_3e_dnb à ALL_COLLECTIONS")
        return False

def add_college_levels():
    """Ajouter les niveaux de collège à NIVEAUX"""
    
    ui_file = '/srv/nexusreussite/rag-ui/compose/ui/app_v2.py'
    
    with open(ui_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Pattern pour trouver la liste NIVEAUX
    pattern = r'(NIVEAUX = \[.*?\])'
    
    # Nouvelle liste avec niveaux de collège
    replacement = '''NIVEAUX = [
    "Sixième",
    "Cinquième",
    "Quatrième",
    "Troisième",
    "Collège (tous niveaux)",
    "Seconde",
    "Première",
    "Terminale",
    "Première et Terminale",
    "Tous niveaux",
]'''
    
    new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    
    if new_content != content:
        with open(ui_file, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("✅ Niveaux de collège ajoutés à NIVEAUX")
        return True
    else:
        print("❌ Impossible d'ajouter les niveaux de collège")
        return False

def main():
    """Fonction principale pour appliquer toutes les modifications"""
    print("Ajout du groupe 'collège' à la taxonomie d'éducation...")
    
    success = True
    
    # 1. Ajouter la taxonomie collège
    if not add_college_to_taxonomy():
        success = False
    
    # 2. Ajouter rag_maths_3e_dnb aux collections
    if not add_rag_maths_3e_dnb_to_collections():
        success = False
    
    # 3. Ajouter les niveaux de collège
    if not add_college_levels():
        success = False
    
    if success:
        print("\n✅ Toutes les modifications ont été appliquées avec succès!")
        print("\nRésumé des changements:")
        print("- ✅ Groupe 'Collège' ajouté avec toutes les matières")
        print("- ✅ rag_maths_3e_dnb ajouté aux collections")
        print("- ✅ Niveaux de collège ajoutés (6ème à 3ème)")
        print("\nRedémarrez l'interface pour voir les changements.")
    else:
        print("\n❌ Certaines modifications ont échoué")

if __name__ == "__main__":
    import re
    main()
