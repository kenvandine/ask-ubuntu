# Ask Ubuntu — Foire aux questions

## Premiers pas

### Comment démarrer Ask Ubuntu ?

**CLI :** Exécute `./ask-ubuntu` (ou `ask-ubuntu` s'il est installé en tant que snap) dans un terminal.

**GUI :** Lance-le depuis le lanceur d'applications ou exécute `cd electron && npm start` dans un terminal.

Lemonade Server doit être démarré en premier. Lance-le avec :
```bash
lemonade-server start
```

### Qu'est-ce que Lemonade Server ?

Lemonade Server est le moteur d'inférence d'IA local qu'Ask Ubuntu utilise pour exécuter le modèle de langage sur ta propre machine. Il doit être en cours d'exécution sur le port 8000 avant de démarrer Ask Ubuntu. Installe-le depuis le projet Lemonade sur GitHub.

### Ask Ubuntu envoie-t-il des données sur internet ?

Non. Toute l'inférence d'IA s'exécute localement via Lemonade Server. Tes questions et informations système ne quittent jamais ta machine. Les man pages peuvent être récupérées depuis manpages.ubuntu.com lors de la première utilisation (pour construire le cache local), mais cela est uniquement en lecture seule et sans authentification.

### Combien de temps dure le premier démarrage ?

Le premier démarrage télécharge le modèle d'IA (~2–5 Go) et construit un index de documentation (~2–3 minutes). Les démarrages suivants chargent tout depuis le cache et ne prennent que quelques secondes.

---

## Utiliser Ask Ubuntu

### Comment poser une question ?

Il suffit de taper à l'invite `●` et d'appuyer sur Entrée. Aucune syntaxe particulière n'est nécessaire.

### Puis-je coller du texte multiligne comme un message d'erreur ?

Oui. Appuie sur `Esc` puis `Enter` pour insérer un saut de ligne à l'invite CLI. Appuie sur `Enter` seul pour envoyer. Dans la GUI, utilise `Shift+Enter` pour les sauts de ligne.

### Comment démarrer une nouvelle conversation ?

**CLI :** La conversation se réinitialise lorsque tu redémarres `./ask-ubuntu`.

**GUI :** Clique sur le bouton **+** (nouveau chat) en haut de la barre latérale gauche.

### Comment effacer l'écran de la CLI ?

Tape `/clear` à l'invite.

### Comment quitter Ask Ubuntu ?

**CLI :** Tape `/exit`, `/quit` ou appuie sur `Ctrl+D`.

**GUI :** Ferme la fenêtre.

### Ask Ubuntu peut-il exécuter des commandes sur mon ordinateur ?

Non. Ask Ubuntu lit l'état du système (listes de paquets, état des services, statistiques en direct) mais n'exécute jamais de commandes ni n'apporte de modifications à ton système. Il te dira quelle commande exécuter ; c'est toi qui l'exécutes.

---

## Modèles

### Comment Ask Ubuntu choisit-il le modèle d'IA à utiliser ?

Il détecte ton matériel automatiquement :
1. Si tu as une AMD NPU (Ryzen AI, Strix Point) et que le backend FLM est installé, il utilise le meilleur modèle FLM téléchargé (Qwen3-8b-FLM, Phi-4-Mini-FLM ou Llama-3.2-3B-FLM).
2. Sinon, il sélectionne un modèle GGUF en fonction du niveau de ton matériel (AMD haut de gamme, Intel, AMD équilibré ou matériel ancien).

### Comment changer le modèle d'IA ?

**CLI :** Tape `/model` pour ouvrir le sélecteur de modèle interactif. Utilise les touches fléchées pour naviguer, tape pour rechercher, appuie sur Entrée pour sélectionner.

**GUI :** Clique sur le bouton d'icône de modèle **⊙** en haut de la barre latérale gauche.

### Que signifient les badges des modèles ?

- **Recommended** — le modèle qu'Ask Ubuntu considère comme le mieux adapté à ton matériel
- **NPU** — conçu pour s'exécuter sur l'AMD NPU via le backend FLM
- **Downloaded** — déjà sur le disque ; se charge immédiatement
- Aucun badge — sera téléchargé lors de la sélection (peut prendre quelques minutes)

### Comment télécharger un nouveau modèle ?

Dans le sélecteur de modèle (CLI `/model` ou bouton ⊙ de la GUI), sélectionne n'importe quel modèle qui n'est pas encore téléchargé. Ask Ubuntu le téléchargera automatiquement et basculera dessus.

### Puis-je fixer un modèle spécifique ?

Oui. Démarre Ask Ubuntu avec `--model <model-id>` en CLI, ou définis la variable d'environnement `ASK_UBUNTU_MODEL` pour la GUI.

### Qu'est-ce que le backend FLM ?

FastFlowLM (FLM) est un backend permettant d'exécuter nativement des modèles de langage quantifiés sur l'AMD NPU (Neural Processing Unit). Il est nettement plus rapide et économe en énergie que l'exécution sur le CPU. Le backend FLM s'installe séparément dans le cadre de la pile Lemonade NPU.

### Quels modèles sont disponibles ?

Il y a ~70 modèles de chat dans le catalogue de Lemonade, dont Llama, Qwen, Phi, Mistral et d'autres en différentes tailles et formats (FLM pour NPU, GGUF pour CPU/GPU). Utilise le sélecteur de modèle pour tous les parcourir.

---

## Informations système

### Quelles informations système Ask Ubuntu collecte-t-il ?

Au démarrage : détails du système d'exploitation, modèle/cœurs/governor du CPU, nom et mémoire du GPU, utilisation de la RAM, points de montage des disques, batterie, zones thermiques, snaps et paquets deb installés, services en cours d'exécution. Consulte la barre latérale gauche dans la GUI pour un résumé rapide.

### Ask Ubuntu peut-il voir mes fichiers ?

Non. Ask Ubuntu lit les métadonnées système (listes de paquets, état des services, informations matérielles) mais ne lit jamais tes fichiers personnels, le contenu de ton répertoire personnel ni aucun fichier que tu n'as pas explicitement collé dans le chat.

### Pourquoi les informations système dans la barre latérale affichent-elles un avertissement thermique ?

Une alerte thermique apparaît si une zone thermique CPU ou GPU signale 60 °C ou plus au démarrage. C'est informatif — Ask Ubuntu t'indique que ta machine chauffe. Demande-lui « is my laptop overheating? » pour une analyse détaillée.

### Comment actualiser les informations système ?

Les informations système sont collectées au démarrage. Redémarre Ask Ubuntu (ou ouvre une nouvelle session) pour obtenir un instantané actualisé. Les statistiques en direct (RAM, CPU, GPU pendant la conversation) sont récupérées à la demande via l'outil `get_system_stats` lorsque tu poses des questions sur l'utilisation actuelle des ressources.

---

## Documentation et RAG

### Quelle documentation Ask Ubuntu recherche-t-il ?

Il effectue des recherches dans un index vectoriel local de ~500 man pages Ubuntu et ~200 articles d'aide Ubuntu de help.ubuntu.com, ainsi que dans le guide de l'utilisateur d'Ask Ubuntu. Cet index est construit lors de la première exécution et mis en cache dans `~/.cache/ask-ubuntu/`.

### Pourquoi Ask Ubuntu ne connaît-il pas une man page spécifique ?

L'index couvre les commandes les plus fréquemment référencées. Si une man page est absente, Ask Ubuntu tentera quand même de répondre à partir de ses connaissances d'entraînement. Tu peux également lui demander de consulter une commande spécifique : « show me the man page for rsync ».

### Comment forcer une reconstruction de l'index de documentation ?

```bash
rm ~/.cache/ask-ubuntu/faiss_index_* ~/.cache/ask-ubuntu/documents_*.pkl
```

Redémarre ensuite Ask Ubuntu. L'index sera reconstruit depuis zéro (2–3 minutes).

### Comment obtenir des man pages locales plutôt que récupérées à distance ?

Connecte l'interface snap `system-packages-doc` (disponible sur Ubuntu 24.04+) :
```bash
sudo snap connect ask-ubuntu:system-packages-doc
```

Cela donne au snap un accès en lecture à `/usr/share/man/` pour une recherche locale rapide.

---

## Dépannage

### Ask Ubuntu affiche « Lemonade Server is not running »

Démarre Lemonade Server :
```bash
lemonade-server start
```

Puis relance Ask Ubuntu.

### La GUI est bloquée sur « Starting backend… »

1. Assure-toi que Lemonade Server est en cours d'exécution : `curl http://localhost:8000/api/v1/health`
2. Vérifie dans le terminal la présence de lignes d'erreur `[server]` — une erreur d'import Python ou un conflit de port s'y affichera.

### Le téléchargement d'un modèle a échoué ou est bloqué

Ouvre à nouveau le sélecteur de modèle et essaie de re-sélectionner le même modèle. Si cela échoue à plusieurs reprises, vérifie que Lemonade Server a accès à internet et dispose de suffisamment d'espace disque (~5 Go libres).

### Les touches fléchées du sélecteur de modèle CLI ne fonctionnent pas dans mon terminal

Certains terminaux (notamment de très anciennes variantes de xterm) ne transmettent pas correctement les séquences d'échappement. Essaie un terminal différent (GNOME Terminal, Alacritty, Kitty ou le terminal Ubuntu intégré). Le sélecteur requiert un terminal moderne avec prise en charge des codes d'échappement ANSI.

### Mon snap ne peut pas lire /var/lib/apt/lists ou /var/lib/dpkg

Les interfaces snap doivent être connectées :
```bash
sudo snap connect ask-ubuntu:var-lib-apt-lists
sudo snap connect ask-ubuntu:var-lib-dpkg
```

Après la connexion, redémarre Ask Ubuntu.

### Ask Ubuntu donne de mauvaises réponses sur mon système

Essaie de lui demander de revérifier avec un outil en direct : « run get_system_stats and tell me what it shows ». Essaie également de démarrer une nouvelle conversation — les informations système sont collectées au début de chaque session.

### Comment signaler un bug ?

Ouvre un issue dans le dépôt GitHub d'Ask Ubuntu en incluant :
- Ta version d'Ubuntu (`lsb_release -d`)
- La version d'Ask Ubuntu ou le commit git
- La question exacte que tu as posée et la réponse obtenue
- Toute sortie d'erreur du terminal

---

## Confidentialité et sécurité

### Mes données sont-elles privées ?

Oui. Toute l'inférence s'exécute localement sur ta machine via Lemonade Server. Rien n'est envoyé à un serveur distant, sauf :
- Les man pages récupérées depuis manpages.ubuntu.com lors de la première utilisation (sans authentification, lecture seule)
- Les pages d'aide récupérées depuis help.ubuntu.com lors de la première utilisation (sans authentification, lecture seule)

### Ask Ubuntu peut-il modifier mon système ?

Non. Il lit l'état du système mais n'exécute jamais de commandes ni n'écrit dans tes fichiers. Il te dit quoi exécuter ; c'est toi qui décides de le faire.
