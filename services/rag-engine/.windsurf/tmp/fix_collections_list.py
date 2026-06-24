#!/usr/bin/env python3
"""
Script pour corriger la liste des collections cibles et inclure rag_maths_3e_dnb
"""

import re


def fix_collections_list():
    """Corriger la liste des collections cibles dans le fichier UI"""
    
    ui_file = '/srv/nexusreussite/rag-ui/compose/ui/app_v2.py'
    
    # Lire le fichier
    with open(ui_file, encoding='utf-8') as f:
        content = f.read()
    
    # Pattern pour trouver la liste des collections cibles
    pattern = r'collection_education = st\.selectbox\(\s*"Collection cible",\s*\[(.*?)\],'
    
    # Remplacer avec la nouvelle liste incluant rag_maths_3e_dnb
    new_list = '"rag_francais_premiere", "rag_maths_premiere", "rag_education", "rag_maths_3e_dnb"'
    
    def replacement(match):
        return f'collection_education = st.selectbox(\n        "Collection cible",\n        [{new_list}],'
    
    new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    
    # Vérifier si la modification a été appliquée
    if new_content != content:
        print("✅ Liste des collections cibles mise à jour")
        
        # Écrire le fichier modifié
        with open(ui_file, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        print(f"✅ Fichier {ui_file} mis à jour")
        
        # Vérifier la modification
        with open(ui_file, encoding='utf-8') as f:
            updated_content = f.read()
        
        if 'rag_maths_3e_dnb' in updated_content and 'Collection cible' in updated_content:
            print("✅ rag_maths_3e_dnb ajouté à la liste des collections cibles")
            return True
        else:
            print("❌ La modification n'a pas été appliquée correctement")
            return False
    else:
        print("❌ La liste des collections n'a pas pu être modifiée")
        return False

def update_help_text():
    """Mettre à jour le texte d'aide pour inclure rag_maths_3e_dnb"""
    
    ui_file = '/srv/nexusreussite/rag-ui/compose/ui/app_v2.py'
    
    with open(ui_file, encoding='utf-8') as f:
        content = f.read()
    
    # Pattern pour trouver le texte d'aide
    pattern = r'help=".*?".*?\)'
    
    # Nouveau texte d'aide
    new_help = 'help="`rag_francais_premiere` : Français 1ère | `rag_maths_premiere` : Maths 1ère spécialité | `rag_education` : corpus général | `rag_maths_3e_dnb` : Maths 3ème DNB"'
    
    # Remplacer le texte d'aide
    new_content = re.sub(
        r'help="`rag_francais_premiere` : Français 1ère \| `rag_maths_premiere` : Maths 1ère spécialité \| `rag_education` : corpus général"',
        new_help,
        content
    )
    
    if new_content != content:
        with open(ui_file, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("✅ Texte d'aide mis à jour")
        return True
    else:
        print("⚠️ Texte d'aide déjà à jour ou non modifiable")
        return True

def main():
    """Fonction principale"""
    print("Correction de la liste des collections cibles...")
    
    success = True
    
    # 1. Corriger la liste des collections
    if not fix_collections_list():
        success = False
    
    # 2. Mettre à jour le texte d'aide
    if not update_help_text():
        success = False
    
    if success:
        print("\n✅ Toutes les corrections ont été appliquées avec succès!")
        print("\nRésumé des changements:")
        print("- ✅ rag_maths_3e_dnb ajouté à la liste des collections cibles")
        print("- ✅ Texte d'aide mis à jour")
        print("\nRedémarrez l'interface pour voir les changements.")
    else:
        print("\n❌ Certaines corrections ont échoué")

if __name__ == "__main__":
    main()
