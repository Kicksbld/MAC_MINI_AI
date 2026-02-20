# WebSocket Server Python

## Installation
Il est fortement recommandé d'utiliser un environnement virtuel (venv) :

```bash
# Créer l'environnement (si pas déjà fait)
python3 -m venv venv

# Activer l'environnement
source venv/bin/activate

# Installer les dépendances
pip install -r requirements.txt
```

## Configuration du Contexte
Pour changer d'environnement (Dev ou Prod) :

1.  **Context.py** : Modifiez la classe `Context` dans `Context.py` si nécessaire pour ajuster les IPs et ports.
2.  **WSServer.py** : Dans le bloc `if __name__ == "__main__":` à la fin du fichier, changez le mode d'initialisation :
    - Pour le développement local : `ws_server = WSServer.dev()`
    - Pour la production : `ws_server = WSServer.prod()`
3.  **dashboard_flask.py** : Dans le bloc `if __name__ == "__main__":` à la fin du fichier, changez le mode d'initialisation :
    - Pour le développement local : `ws_server = WSServer.dev()`
    - Pour la production : `ws_server = WSServer.prod()`

## Lancement du Système
Il est recommandé de lancer chaque composant dans un terminal séparé :

1.  **Lancer le serveur WebSocket** :
    ```bash
    python3 WSServer.py
    ```

2.  **Lancer l'interface de Login (Client PyQt5)** :
    ```bash
    python3 login.py
    ```

3.  **Lancer le Dashboard (Flask)** :
    ```bash
    python3 dashboard_flask.py
    ```
    Le dashboard sera accessible à l'adresse suivante : [http://127.0.0.1:5005](http://127.0.0.1:5005)


    kyutai

    