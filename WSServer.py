from websocket_server import WebsocketServer
import threading
import base64
from datetime import datetime

from Context import Context
from Message import Message, MessageType


class WSServer:
    def __init__(self, ctx):
        self.host = ctx.host
        self.port = ctx.port
        self.server = WebsocketServer(host=self.host, port=self.port, loglevel=1)
        self.server.set_fn_new_client(self.on_new_client)
        self.server.set_fn_client_left(self.on_client_left)
        self.server.set_fn_message_received(self.on_message_received)

        self.clients = {}
        self.client_metadata = {}  # {username: {connected_at, last_activity}}
        self.admin_clients = []    # List of admin websockets
        self.running = False

    def on_new_client(self, client, server):
        print(f"\n[+] Client connecté: id={client['id']} addr={client['address']}")
        welcome_msg = Message(MessageType.RECEPTION.TEXT, emitter="SERVER", receiver="", value="Bienvenue !")
        server.send_message(client, welcome_msg.to_json())
        self.broadcast_clients_list()
        print("[SERVER] > ", end="", flush=True)

    def on_client_left(self, client, server):
        print(f"\n[-] Client déconnecté: id={client['id']}")
        disconnected_username = None

        for name, c in list(self.clients.items()):
            if c['id'] == client['id']:
                disconnected_username = name
                del self.clients[name]
                # Nettoie les métadonnées
                if name in self.client_metadata:
                    del self.client_metadata[name]
                break

        # Nettoie la liste des admins si c'était un admin
        self.admin_clients = [a for a in self.admin_clients if a.get('id') != client.get('id')]

        # Notifie les admins de la déconnexion
        if disconnected_username and not disconnected_username.startswith("ADMIN"):
            self.notify_admins_client_disconnected(disconnected_username)

        self.broadcast_clients_list()

        print("[SERVER] > ", end="", flush=True)

    def broadcast_clients_list(self):
        """Envoie la liste des clients à tous"""
        clients_ids = list(self.clients.keys())

        msg = Message(
            MessageType.RECEPTION.CLIENT_LIST,
            emitter="SERVER",
            receiver="ALL",
            value=clients_ids
        ).to_json()

        for client in self.clients.values():
            self.server.send_message(client, msg)

    def notify_admins_routing(self, emitter, receiver, msg_type):
        """Envoie une notification de routage à tous les admins (sans contenu)"""
        log_data = {
            'emitter': emitter,
            'receiver': receiver,
            'message_type': msg_type,
            'timestamp': datetime.now().isoformat()
        }
        msg = Message(MessageType.ADMIN.ROUTING_LOG, emitter="SERVER", receiver="ADMIN", value=log_data)
        for admin in self.admin_clients:
            try:
                self.server.send_message(admin, msg.to_json())
            except:
                pass

    def notify_admins_client_connected(self, username):
        """Notifie les admins d'une nouvelle connexion"""
        event_data = {
            'username': username,
            'connected_at': self.client_metadata[username]['connected_at'],
            'timestamp': datetime.now().isoformat()
        }
        msg = Message(MessageType.ADMIN.CLIENT_CONNECTED, emitter="SERVER", receiver="ADMIN", value=event_data)
        for admin in self.admin_clients:
            try:
                self.server.send_message(admin, msg.to_json())
            except:
                pass

    def notify_admins_client_disconnected(self, username):
        """Notifie les admins d'une déconnexion"""
        event_data = {
            'username': username,
            'timestamp': datetime.now().isoformat()
        }
        msg = Message(MessageType.ADMIN.CLIENT_DISCONNECTED, emitter="SERVER", receiver="ADMIN", value=event_data)
        for admin in self.admin_clients:
            try:
                self.server.send_message(admin, msg.to_json())
            except:
                pass

    def send_admin_client_list(self, admin_client):
        """Envoie la liste complète des clients avec métadonnées à un admin"""
        clients_data = []
        for username, metadata in self.client_metadata.items():
            clients_data.append({
                'username': username,
                'connected_at': metadata['connected_at'],
                'last_activity': metadata['last_activity'],
                'status': 'active'
            })
        msg = Message(MessageType.ADMIN.CLIENT_LIST_FULL, emitter="SERVER", receiver="ADMIN", value=clients_data)
        self.server.send_message(admin_client, msg.to_json())

    def on_message_received(self, client, server, message):
        print(f"\n[message reçu] {message}")
        received_msg = Message.from_json(message)
        if received_msg.message_type == MessageType.DECLARATION:
            username = received_msg.emitter

            # Détection des clients admin
            if username == "ADMIN" or username.startswith("ADMIN_"):
                self.admin_clients.append(client)
                print(f"[info] Admin '{username}' connecté")
                # Envoie la liste complète des clients à l'admin
                self.send_admin_client_list(client)
            else:
                # Client régulier - stocke les métadonnées
                self.client_metadata[username] = {
                    'connected_at': datetime.now().isoformat(),
                    'last_activity': datetime.now().isoformat()
                }
                # Notifie tous les admins de la nouvelle connexion
                self.notify_admins_client_connected(username)

            response = Message(MessageType.RECEPTION.TEXT, emitter="SERVER", receiver=username, value=f"Déclaration reçue de {username}")
            server.send_message(client, response.to_json())
            self.clients[username] = client
            print(f"[info] Client '{username}' enregistré")
            self.broadcast_clients_list()
        
        elif received_msg.message_type == MessageType.ENVOI.CLIENT_LIST:
            users_list = list(self.clients.keys())
            response = Message(MessageType.RECEPTION.CLIENT_LIST, emitter="SERVER", receiver=received_msg.receiver, value=users_list)
            server.send_message(client, response.to_json())
            print(f"CLIENTS = {users_list}")

        elif received_msg.message_type in [MessageType.ENVOI.TEXT, MessageType.ENVOI.IMAGE, MessageType.ENVOI.AUDIO, MessageType.ENVOI.VIDEO, MessageType.ENVOI.SENSOR]:
            # Met à jour last_activity pour l'émetteur
            if received_msg.emitter in self.client_metadata:
                self.client_metadata[received_msg.emitter]['last_activity'] = datetime.now().isoformat()

            # Détermine le type de message pour le log
            msg_type_simple = 'TEXT'
            if received_msg.message_type == MessageType.ENVOI.IMAGE:
                msg_type_simple = 'IMAGE'
            elif received_msg.message_type == MessageType.ENVOI.AUDIO:
                msg_type_simple = 'AUDIO'
            elif received_msg.message_type == MessageType.ENVOI.VIDEO:
                msg_type_simple = 'VIDEO'
            elif received_msg.message_type == MessageType.ENVOI.SENSOR:
                msg_type_simple = 'SENSOR'

            # Notifie les admins du routage (sans contenu)
            self.notify_admins_routing(received_msg.emitter, received_msg.receiver, msg_type_simple)

            if received_msg.receiver == "SERVER":
                print(f"[{received_msg.emitter}] {received_msg.value}")
            if received_msg.receiver == "SERVER" and received_msg.message_type == MessageType.SYS_MESSAGE:
                ack_msg = Message(MessageType.SYS_MESSAGE, emitter="SERVER", receiver="", value="VU")
                server.send_message(client, ack_msg.to_json())
            if received_msg.receiver == "ALL":
                reception_type = MessageType.RECEPTION.TEXT
                if received_msg.message_type == MessageType.ENVOI.IMAGE:
                    reception_type = MessageType.RECEPTION.IMAGE
                elif received_msg.message_type == MessageType.ENVOI.AUDIO:
                    reception_type = MessageType.RECEPTION.AUDIO
                elif received_msg.message_type == MessageType.ENVOI.VIDEO:
                    reception_type = MessageType.RECEPTION.VIDEO
                elif received_msg.message_type == MessageType.ENVOI.SENSOR:
                    reception_type = MessageType.RECEPTION.SENSOR

                for client in self.clients.values():
                    message = Message(reception_type, emitter=received_msg.emitter, receiver="ALL", value=received_msg.value, sensor_id=received_msg.sensor_id)
                    self.server.send_message(client, message.to_json())
            else:
                receiver_client = self.clients.get(received_msg.receiver, None)
                if receiver_client:
                    reception_type = MessageType.RECEPTION.TEXT
                    if received_msg.message_type == MessageType.ENVOI.IMAGE:
                        reception_type = MessageType.RECEPTION.IMAGE
                    elif received_msg.message_type == MessageType.ENVOI.AUDIO:
                        reception_type = MessageType.RECEPTION.AUDIO
                    elif received_msg.message_type == MessageType.ENVOI.VIDEO:
                        reception_type = MessageType.RECEPTION.VIDEO
                    elif received_msg.message_type == MessageType.ENVOI.SENSOR:
                        reception_type = MessageType.RECEPTION.SENSOR
                    forward_msg = Message(reception_type, emitter=received_msg.emitter, receiver=received_msg.receiver, value=received_msg.value, sensor_id=received_msg.sensor_id)
                    server.send_message(receiver_client, forward_msg.to_json())
                else:
                    error_msg = Message(MessageType.RECEPTION.TEXT, emitter="SERVER", receiver=received_msg.emitter, value=f"Erreur: destinataire {received_msg.receiver} non trouvé.")
                    server.send_message(client, error_msg.to_json())
        elif received_msg.message_type == MessageType.SYS_MESSAGE:
             # Forward SYS_MESSAGE (like VU) to the target receiver
             target = received_msg.receiver
             if target and target != "SERVER" and target != "ALL":
                 receiver_client = self.clients.get(target, None)
                 if receiver_client:
                     forward_msg = Message(MessageType.SYS_MESSAGE, emitter=received_msg.emitter, receiver=target, value=received_msg.value)
                     server.send_message(receiver_client, forward_msg.to_json())

        print("[SERVER] > ", end="", flush=True)

    def input_loop(self):
        print("\nChat serveur démarré. Tapez 'dest:message' pour envoyer (ex: Client:bonjour)")
        print("Tapez 'img:dest:chemin' pour envoyer une image (ex: img:Client:/path/image.png)")
        print("Tapez 'audio:dest:chemin' pour envoyer un audio (ex: audio:Client:/path/audio.mp3)")
        print("Tapez 'video:dest:chemin' pour envoyer une video (ex: video:Client:/path/video.mp4)")
        print("Tapez 'list' pour voir les clients connectés, 'disconnect' pour quitter.\n")
        while self.running:
            try:
                print("[SERVER] > ", end="", flush=True)
                user_input = input()
                if user_input.lower() == "disconnect":
                    self.running = False
                    self.server.shutdown_gracefully()
                    break
                elif user_input.lower() == "list":
                    print(f"Clients connectés: {list(self.clients.keys())}")
                elif user_input.lower().startswith("img:"):
                    parts = user_input[4:].split(":", 1)
                    if len(parts) == 2:
                        dest, filepath = parts[0].strip(), parts[1].strip()
                        self.send_image(filepath, dest)
                    else:
                        print("Format: img:dest:chemin")
                    continue
                elif user_input.lower().startswith("audio:"):
                    parts = user_input[6:].split(":", 1)
                    if len(parts) == 2:
                        dest, filepath = parts[0].strip(), parts[1].strip()
                        self.send_audio(filepath, dest)
                    else:
                        print("Format: audio:dest:chemin")
                    continue
                elif user_input.lower().startswith("video:"):
                    parts = user_input[6:].split(":", 1)
                    if len(parts) == 2:
                        dest, filepath = parts[0].strip(), parts[1].strip()
                        self.send_video(filepath, dest)
                    else:
                        print("Format: video:dest:chemin")
                    continue
                elif ":" in user_input:
                    dest, value = user_input.split(":", 1)
                    dest = dest.strip()
                    value = value.strip()
                    if dest.lower() == "ALL":
                        for name, client in self.clients.items():
                            msg = Message(MessageType.RECEPTION.TEXT, emitter="SERVER", receiver=name, value=value)
                            self.server.send_message(client, msg.to_json())
                        print(f"[envoyé à tous] {value}")
                    else:
                        receiver_client = self.clients.get(dest, None)
                        if receiver_client:
                            msg = Message(MessageType.RECEPTION.TEXT, emitter="SERVER", receiver=dest, value=value)
                            self.server.send_message(receiver_client, msg.to_json())
                            print(f"[envoyé à {dest}] {value}")
                        else:
                            print(f"[erreur] Client '{dest}' non trouvé")
                else:
                    print("Format: 'dest:message' ou 'ALL:message' pour broadcast")
            except EOFError:
                break

    def start(self):
        print(f"Serveur WS sur ws://{self.host}:{self.port}")
        self.running = True

        input_thread = threading.Thread(target=self.input_loop, daemon=True)
        input_thread.start()

        self.server.run_forever()

    def send_image(self, filepath, dest):
        with open(filepath, "rb") as f:
            img_base64 = base64.b64encode(f.read()).decode("utf-8")
        value = f"IMG:{img_base64}"
        if dest.lower() == "ALL":
            for name, client in self.clients.items():
                msg = Message(MessageType.RECEPTION.IMAGE, emitter="SERVER", receiver=name, value=value)
                self.server.send_message(client, msg.to_json())
            print(f"[image envoyée à tous]")
        else:
            receiver_client = self.clients.get(dest, None)
            if receiver_client:
                msg = Message(MessageType.RECEPTION.IMAGE, emitter="SERVER", receiver=dest, value=value)
                self.server.send_message(receiver_client, msg.to_json())
                print(f"[image envoyée à {dest}]")
            else:
                print(f"[erreur] Client '{dest}' non trouvé")

    def send_audio(self, filepath, dest):
        with open(filepath, "rb") as f:
            audio_base64 = base64.b64encode(f.read()).decode("utf-8")
        value = f"AUDIO:{audio_base64}"
        if dest.lower() == "ALL":
            for name, client in self.clients.items():
                msg = Message(MessageType.RECEPTION.AUDIO, emitter="SERVER", receiver=name, value=value)
                self.server.send_message(client, msg.to_json())
            print(f"[audio envoyé à tous]")
        else:
            receiver_client = self.clients.get(dest, None)
            if receiver_client:
                msg = Message(MessageType.RECEPTION.AUDIO, emitter="SERVER", receiver=dest, value=value)
                self.server.send_message(receiver_client, msg.to_json())
                print(f"[audio envoyé à {dest}]")
            else:
                print(f"[erreur] Client '{dest}' non trouvé")

    def send_video(self, filepath, dest):
        with open(filepath, "rb") as f:
            video_base64 = base64.b64encode(f.read()).decode("utf-8")
        value = f"VIDEO:{video_base64}"
        if dest.lower() == "ALL":
            for name, client in self.clients.items():
                msg = Message(MessageType.RECEPTION.VIDEO, emitter="SERVER", receiver=name, value=value)
                self.server.send_message(client, msg.to_json())
            print(f"[video envoyée à tous]")
        else:
            receiver_client = self.clients.get(dest, None)
            if receiver_client:
                msg = Message(MessageType.RECEPTION.VIDEO, emitter="SERVER", receiver=dest, value=value)
                self.server.send_message(receiver_client, msg.to_json())
                print(f"[video envoyée à {dest}]")
            else:
                print(f"[erreur] Client '{dest}' non trouvé")

    @staticmethod
    def dev():
        return WSServer(Context.dev())

    @staticmethod
    def prod():
        return WSServer(Context.prod())

if __name__ == "__main__":
    ws_server = WSServer.prod()
    ws_server.start()