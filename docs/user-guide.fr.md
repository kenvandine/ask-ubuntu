# Ask Ubuntu — Guide de l'utilisateur

Ask Ubuntu est un assistant IA pour Ubuntu Linux. Il répond aux questions sur votre système, les paquets installés, les services en cours d'exécution, le matériel, la configuration et l'utilisation générale d'Ubuntu. Il fonctionne entièrement en local — pas de cloud, pas d'internet requis pour le chat.

---

## Ce qu'Ask Ubuntu peut répondre

- « Comment installer VLC ? » — vous indique la commande snap ou apt avec les informations de version
- « Quelle version de Firefox ai-je ? » — vérifie votre version snap installée réelle
- « Pourquoi le ventilateur de mon ordinateur portable tourne-t-il fort ? » — lit vos capteurs thermiques et le CPU governor
- « Combien d'espace disque est libre ? » — lit les statistiques de montage en direct
- « Est-ce que nginx est en cours d'exécution ? » — vérifie l'état du service systemd en temps réel
- « De quels snap interfaces l'application caméra a-t-elle besoin ? » — le recherche dans le snap store
- « Comment activer un pare-feu ? » — récupère la page man de UFW et vous donne les commandes exactes
- « Quels processus utilisent ma RAM ? » — obtient un instantané de processus en direct et l'explique

Ask Ubuntu connaît parfaitement votre machine spécifique. Quand vous demandez « combien de RAM ai-je ? », il répond avec votre mémoire réelle, pas une explication générique.

---

## Démarrer Ask Ubuntu

### Terminal CLI

```bash
./ask-ubuntu
```

Ou s'il est installé comme snap :
```bash
ask-ubuntu
```

Ask Ubuntu démarrera, affichera un en-tête d'informations système et vous amènera à l'invite de chat.

### Desktop GUI

Lancez depuis votre lanceur d'applications, ou depuis le terminal :
```bash
cd electron && npm start
```

L'application ouvre une fenêtre divisée : panneau d'informations système à gauche, chat à droite.

### Configuration initiale

Au tout premier lancement, Ask Ubuntu va :
1. Télécharger le modèle IA depuis Lemonade Server (~2–5 Go selon le modèle)
2. Télécharger le modèle d'embedding pour la recherche de documents (~500 Mo)
3. Construire l'index de documentation — lit les pages man et les fichiers d'aide Ubuntu (~2–3 minutes)

Tout est mis en cache dans `~/.cache/ask-ubuntu/`. Les démarrages suivants chargent instantanément.

---

## Utiliser la CLI

### Poser des questions

Tapez n'importe quelle question à l'invite `●` et appuyez sur Entrée :

```
● How do I check if a service is enabled?
```

Pour les **questions multiligne** (p. ex. coller un message d'erreur), appuyez sur `Esc` puis `Enter` pour insérer un saut de ligne. Appuyez sur `Enter` seul pour envoyer.

Utilisez `↑` et `↓` pour naviguer dans l'historique de vos questions.

### Commandes spéciales

| Commande | Ce qu'elle fait |
|----------|----------------|
| `/model` | Ouvre le sélecteur de modèle interactif — changer le modèle IA |
| `/help` | Afficher le tableau d'aide |
| `/clear` | Effacer l'écran |
| `/exit` ou `/quit` | Quitter Ask Ubuntu |
| `Ctrl+D` | Quitter |

### Changer le modèle dans la CLI

Tapez `/model` pour ouvrir un sélecteur interactif en plein écran :

- **Taper pour rechercher** — filtre instantanément la liste des modèles au fur et à mesure de la saisie
- `↑` / `↓` — naviguer dans la liste
- `PgUp` / `PgDn` — défiler plus rapidement
- `Enter` — sélectionner le modèle mis en surbrillance
- `Esc` — annuler et conserver le modèle actuel

Les modèles sont triés avec le meilleur choix pour votre matériel en haut. Les badges indiquent :

- **★ Recommended** — meilleure correspondance pour votre matériel
- **NPU** — conçu pour fonctionner sur l'AMD NPU (le plus rapide sur matériel compatible)
- **✓ Downloaded** — déjà sur le disque, se charge immédiatement
- *(aucun badge)* — sera téléchargé automatiquement lors de la sélection (~2–5 Go)

Quand vous sélectionnez un modèle qui n'est pas encore téléchargé, Ask Ubuntu le télécharge et affiche la progression avant de basculer.

### Lire les réponses

Les réponses apparaissent sous forme de texte en streaming. Les blocs de code sont mis en surbrillance. Si l'assistant a consulté des données système en direct avant de répondre (p. ex. utilisation de la mémoire, versions de paquets), ces appels d'outils sont affichés dans des lignes de détails repliées avant la réponse :

```
  ↳ check_snap(firefox)
  ↳ get_system_stats()
```

---

## Utiliser la Desktop GUI

### Disposition de la fenêtre

La fenêtre comporte deux panneaux :

**Barre latérale gauche** — instantané des informations système :
- Système d'exploitation, noyau, nom d'hôte, facteur de forme (ordinateur portable/bureau)
- CPU, GPU, mémoire, disque par montage, batterie
- Alertes thermiques actives
- Nombre de paquets installés (snap et deb)
- En haut : **bouton de sélection de modèle** et **bouton nouveau chat**

**Panneau droit** — la zone de chat :
- Vos messages apparaissent à droite en orange
- Les réponses de l'assistant apparaissent à gauche
- Un point clignotant indique quand le modèle réfléchit
- Les appels d'outils (recherches de paquets, statistiques en direct) apparaissent comme des détails dépliables

### Changer le modèle dans la GUI

Cliquez sur l'icône **⊙** (modèle/sunburst) en haut de la barre latérale gauche. Cela ouvre le panneau de sélection de modèle :

- **Zone de recherche** — tapez pour filtrer la liste des modèles instantanément
- Chaque ligne affiche le nom du modèle, la taille et les badges de statut
- Cliquez sur une ligne pour la sélectionner
- Si le modèle n'est pas encore téléchargé, une barre de progression apparaît — attendez que le téléchargement soit terminé avant de chatter

Badges :
- **Recommended** (orange) — le meilleur pour votre matériel
- **NPU** (bleu) — fonctionne sur l'AMD NPU
- **Downloaded** (vert) — déjà disponible

### Démarrer une nouvelle conversation

Cliquez sur le bouton **+** (nouveau chat) dans la barre latérale pour effacer la conversation et repartir de zéro. Vos messages précédents ne sont pas sauvegardés.

### Blocs de code

Chaque bloc de code dans une réponse dispose d'un bouton **Copy**. Cliquez dessus pour copier la commande dans votre presse-papiers. Le bouton clignote pour confirmer la copie.

---

## Comment Ask Ubuntu choisit le modèle IA

Au démarrage, Ask Ubuntu sélectionne automatiquement le meilleur modèle disponible pour votre matériel :

### 1. NPU + FLM (priorité maximale)

Si vous disposez d'un AMD NPU (XDNA ou XDNA2 — présent dans les processeurs Ryzen AI et Strix Point) et que le backend FastFlowLM (FLM) est installé, Ask Ubuntu utilise un modèle FLM dédié qui s'exécute nativement sur le NPU. C'est l'option la plus rapide et la plus économe en énergie.

Ordre de préférence des modèles FLM :
1. Qwen3-8b-FLM (8 milliards de paramètres, meilleure qualité)
2. Phi-4-Mini-Instruct-FLM (4B, plus rapide)
3. Llama-3.2-3B-FLM (3B, le plus petit)

Seuls les modèles FLM déjà téléchargés sont sélectionnés automatiquement. Si aucun n'est téléchargé, il bascule sur le niveau matériel.

### 2. Niveau matériel (solution de repli)

| Niveau | Matériel | Modèle |
|--------|----------|--------|
| High-End | AMD Strix / Ryzen AI (GPU) | Qwen3-4B-Instruct-2507-GGUF |
| Mid-Intel | Intel Core / Ultra | Phi-4-mini-instruct-GGUF |
| Balanced AMD | AMD CPU, ≥ 16 Go de RAM | Llama-3.2-3B-Instruct-GGUF |
| Legacy | Autre / peu de RAM | Llama-3.2-1B-Instruct-GGUF |

### Fixer un modèle spécifique

```bash
# CLI — passer en ligne de commande
./ask-ubuntu --model Llama-3.2-3B-Instruct-GGUF

# GUI — définir une variable d'environnement avant de démarrer
ASK_UBUNTU_MODEL=Llama-3.2-1B-Instruct-GGUF npm start
```

---

## Comment fonctionne le contexte système

Avant votre premier message, Ask Ubuntu collecte un instantané de votre machine :

- Identification complète du système d'exploitation (version Ubuntu, nom de code, noyau)
- Modèle de CPU, nombre de cœurs, hyperthreading, cache L3, CPU frequency governor actif
- Nom du GPU, utilisation de la mémoire VRAM et GTT, température, vitesse d'horloge (AMD)
- RAM : utilisée, disponible, mise en cache ; utilisation du swap ; pression mémoire (PSI)
- Disque : type de lecteur (NVMe SSD / HDD), détection LVM/LUKS/RAID, utilisation par montage
- Interfaces réseau : type, état, vitesse
- Charge et état de la batterie (ordinateurs portables)
- Zones thermiques — vous avertit si une zone est chaude
- Tous les snaps et paquets deb installés
- Services systemd en cours d'exécution

Ce contexte est inclus avec chaque question, de sorte que les réponses sont toujours spécifiques à votre machine.

Le LLM peut également appeler des **outils en direct** en cours de conversation pour obtenir des données fraîches :

| Outil | Ce qu'il récupère |
|-------|------------------|
| `check_snap(name)` | Version installée + version dans la boutique pour un snap |
| `check_apt(name)` | Si un paquet deb est installé ou disponible |
| `list_installed_snaps()` | Tous les snaps installés avec leurs versions |
| `check_service(name)` | Si un service systemd est actif et activé |
| `list_running_services()` | Tous les démons en cours d'exécution |
| `list_failed_services()` | Toutes les unités systemd en échec |
| `get_system_stats()` | Utilisation en direct de la mémoire, GPU, CPU, processus principaux, disque |

---

## Comment fonctionne la récupération de documents (RAG)

Ask Ubuntu dispose d'un index vectoriel local de la documentation Ubuntu. Avant de répondre à votre question, il recherche dans cet index les 3 documents les plus pertinents et les inclut comme contexte pour le modèle IA.

L'index contient :
- ~500 pages man Ubuntu (apt, snap, systemctl, ufw, etc.)
- ~200 articles d'aide Ubuntu de help.ubuntu.com
- Le guide de l'utilisateur et la FAQ d'Ask Ubuntu (ce document)

Les pages man sont chargées depuis :
1. `/usr/share/man/` si le snap interface `system-packages-doc` est connecté
2. Le cache local sur le disque dans `~/.cache/ask-ubuntu/manpages/`
3. Récupérées depuis manpages.ubuntu.com à la première utilisation (puis mises en cache)

L'index est stocké dans `~/.cache/ask-ubuntu/`. Supprimez-le pour forcer une reconstruction :
```bash
rm ~/.cache/ask-ubuntu/faiss_index_* ~/.cache/ask-ubuntu/documents_*.pkl
```

---

## Conseils pour de bonnes questions

- **Soyez précis** — « pourquoi apt est-il lent ? » donne une meilleure réponse que « répare mes paquets »
- **Incluez l'erreur** — collez le message d'erreur exact, Ask Ubuntu l'expliquera
- **Posez des questions de suivi** — Ask Ubuntu se souvient du contexte de la conversation
- **Demandez des commandes** — « donne-moi la commande pour vérifier la température de mon GPU » retourne une commande prête à exécuter
- **Posez des questions sur votre système** — « est-ce que Wayland ou X11 est en cours d'exécution ? », « quel est mon CPU governor ? »

---

## Versions Ubuntu prises en charge

Ask Ubuntu fonctionne sur Ubuntu 22.04 LTS (Jammy) et 24.04 LTS (Noble). Il nécessite Python 3.10+ et Lemonade Server fonctionnant localement sur le port 8000.
