import websocket
import threading
import base64
import os
import sys

_NL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nl_to_code")
sys.path.insert(0, _NL_DIR)
from nl_to_code import execute_code_from

import importlib.util as _ilu
_nl_main_spec = _ilu.spec_from_file_location("nl_main", os.path.join(_NL_DIR, "main.py"))
_nl_main = _ilu.module_from_spec(_nl_main_spec)
_nl_main_spec.loader.exec_module(_nl_main)

from Context import Context
from Message import Message, MessageType, SENSOR_ID


try:
    from PyQt5.QtCore import QObject, pyqtSignal
    HAS_PYQT = True
except ImportError:
    class QObject: pass
    def pyqtSignal(*args, **kwargs): return None
    HAS_PYQT = False

class WSClient(QObject):
    if HAS_PYQT:
        message_received = pyqtSignal(object)

    def __init__(self, ctx, username="Client", on_connect_callback=None, on_message_callback=None, on_users_list_callback=None):
        if HAS_PYQT:
            super().__init__()
        self.username = username
        self.connected = False
        self.on_connect_callback = on_connect_callback
        self.on_message_callback = on_message_callback
        self.on_users_list_callback = on_users_list_callback
        self.known_users = set()
        self.connected_users = []
        self.ws = websocket.WebSocketApp(
            ctx.url(),
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )

    def on_message(self, ws, message):
        received_msg = Message.from_json(message)

        # Message @IA → traitement nl_to_code
        if isinstance(received_msg.value, str) and received_msg.value.startswith("@IA"):
            nl = received_msg.value[len("@IA"):].strip()
            threading.Thread(target=self._handle_ia, args=(nl, received_msg.emitter), daemon=True).start()
            return

        # Sensor ESP_KILLIAN RFID/BUTTON/JOYSTICK → écriture en mémoire
        if (received_msg.message_type == MessageType.RECEPTION.SENSOR
                and received_msg.emitter == "ESP_KILLIAN"
                and received_msg.sensor_id in (SENSOR_ID.RFID, SENSOR_ID.BUTTON, SENSOR_ID.JOYSTICK)):
            threading.Thread(
                target=self._write_sensor_to_memory,
                args=(received_msg.sensor_id, received_msg.value),
                daemon=True
            ).start()
            return

        # Sensor BUTTON click → déclenche piper TTS
        if received_msg.message_type == MessageType.RECEPTION.SENSOR:
            print(f"[DEBUG SENSOR] sensor_id={repr(received_msg.sensor_id)} value={repr(received_msg.value)}")
            if received_msg.sensor_id == "BUTTON" and isinstance(received_msg.value, dict) and received_msg.value.get("isPressed") == True:
                import subprocess
                print("[DEBUG] Lancement piper...")
                try:
                    proc = subprocess.Popen(
                        ["python3", "-m", "piper", "-m", "fr_FR-tom-medium",
                         "--", "Attention, intrusion détectée dans la base secrète. Accès accordé au commandant Killian. Bonne journée, chef."]
                    )
                    print(f"[DEBUG] piper lancé pid={proc.pid}")
                except Exception as e:
                    print(f"[DEBUG] Erreur lancement piper: {e}")
                return

        # Répondre au ping du serveur
        if received_msg.message_type == MessageType.SYS_MESSAGE and received_msg.value == "ping":
            pong_msg = Message(MessageType.SYS_MESSAGE, emitter=self.username, receiver="", value="pong")
            ws.send(pong_msg.to_json())
            return

        # Gérer la liste des utilisateurs connectés
        if received_msg.message_type == MessageType.RECEPTION.CLIENT_LIST:
            self.connected_users = received_msg.value
            if self.on_users_list_callback:
                self.on_users_list_callback(self.connected_users)
            
            # Ne pas faire de return ici pour laisser le signal PyQt5
            # et le callback on_message être appelés à la fin

        # Ajouter l'émetteur aux utilisateurs connus
        if received_msg.emitter and received_msg.emitter != "SERVER":
            self.known_users.add(received_msg.emitter)

        # Signal pour l'UI PyQt5
        if HAS_PYQT:
            self.message_received.emit(received_msg)

        # Callback pour l'UI (standard ou Flask)
        if self.on_message_callback:
            self.on_message_callback(received_msg)
        else:
            # Affichage console par défaut (si pas de callback)
            print(f"\n[{received_msg.emitter}] {received_msg.value}")
            print(f"[{self.username}] > ", end="", flush=True)

        # Accusé de réception pour les messages RECEPTION
        if received_msg.message_type in [MessageType.RECEPTION.TEXT, MessageType.RECEPTION.IMAGE, MessageType.RECEPTION.AUDIO, MessageType.RECEPTION.VIDEO]:
            ack_msg = Message(MessageType.SYS_MESSAGE, emitter=self.username, receiver="", value="MESSAGE OK")
            ws.send(ack_msg.to_json())

    def _write_sensor_to_memory(self, sensor_id: str, value):
        if sensor_id == SENSOR_ID.JOYSTICK and isinstance(value, dict):
            content = value.get("direction", str(value))
        else:
            content = str(value)

        category = f"#{sensor_id}:"
        _nl_main.write_memory(category=category, content=content, replace=True)
        print(f"[MEMORY] {category} ← {content}")

    def _handle_ia(self, nl: str, sender: str):
        tools = {
            "compter":      _nl_main.compter,
            "gerer_led":    _nl_main.gerer_led,
            "read_memory":  _nl_main.read_memory,
            "write_memory": _nl_main.write_memory,
        }

        try:
            result = execute_code_from(nl=nl, filter_path="main", tools=tools)
            print(f"[IA] résultat: {result}")

            if isinstance(result, tuple) and len(result) == 3:
                action, couleur, led_number = result
                self.send_sensor(SENSOR_ID.LED, {
                    "action":     action,
                    "couleur":    couleur,
                    "led_number": led_number or 0,
                })
            elif result is not None:
                self.send(str(result), sender)
        except Exception as e:
            print(f"[IA] erreur: {e}")

    def on_error(self, ws, error):
        print(f"\n[error] {error}")

    def on_close(self, ws, close_status_code, close_msg):
        print(f"\n[close] code={close_status_code} msg={close_msg}")
        self.connected = False

    def on_open(self, ws):
        print("[open] connecté")
        self.connected = True
        message = Message(
            message_type=MessageType.DECLARATION,
            emitter=self.username,
            receiver="SERVER",
            value="hello je suis connecté"
        )
        ws.send(message.to_json())
        self.on_client_list()

        if self.on_connect_callback:
            self.on_connect_callback()
        else:
            input_thread = threading.Thread(target=self.input_loop, daemon=True)
            input_thread.start()

    def input_loop(self):
        print(f"Chat démarré. Tapez 'dest:message' pour envoyer (ex: SERVER:bonjour)")
        print(f"Tapez 'img:dest:chemin' pour envoyer une image (ex: img:Client2:/path/image.png)")
        print(f"Tapez 'audio:dest:chemin' pour envoyer un audio (ex: audio:Client2:/path/audio.mp3)")
        print(f"Tapez 'disconnect' pour quitter.\n")
        while self.connected:
            try:
                print(f"[{self.username}] > ", end="", flush=True)
                user_input = input()
                if user_input.lower() == "disconnect":
                    disconnect_msg = Message(MessageType.SYS_MESSAGE, emitter=self.username, receiver="", value="Disconnect")
                    self.ws.send(disconnect_msg.to_json())
                    self.ws.close()
                    break
                if user_input.lower().startswith("img:"):
                    parts = user_input[4:].split(":", 1)
                    if len(parts) == 2:
                        dest, filepath = parts[0].strip(), parts[1].strip()
                        self.send_image(filepath, dest)
                        print(f"Image envoyée à {dest}")
                    else:
                        print("Format: img:dest:chemin")
                    continue

                if user_input.lower().startswith("audio:"):
                    parts = user_input[6:].split(":", 1)
                    if len(parts) == 2:
                        dest, filepath = parts[0].strip(), parts[1].strip()
                        self.send_audio(filepath, dest)
                        print(f"Audio envoyé à {dest}")
                    else:
                        print("Format: audio:dest:chemin")
                    continue
                if user_input.lower().startswith("video:"):
                    parts = user_input[6:].split(":", 1)
                    if len(parts) == 2:
                        dest, filepath = parts[0].strip(), parts[1].strip()
                        self.send_video(filepath, dest)
                        print(f"Vidéo envoyée à {dest}")
                    else:
                        print("Format: video:dest:chemin")
                    continue
                if ":" in user_input:
                    dest, content = user_input.split(":", 1)
                    self.send(content.strip(), dest.strip())
                else:
                    self.send(user_input, "SERVER")
            except EOFError:
                break

    def connect(self):
        self.ws.run_forever()

    def on_client_list(self):
        message = Message(MessageType.ENVOI.CLIENT_LIST, emitter=self.username, receiver="SERVER", value="")
        self.ws.send(message.to_json())

    def send(self, value, dest):
        message = Message(MessageType.ENVOI.TEXT, emitter=self.username, receiver=dest, value=value)
        self.ws.send(message.to_json())

    def send_image(self, filepath, dest):
        with open(filepath, "rb") as f:
            img_base64 = base64.b64encode(f.read()).decode("utf-8")
        value = f"IMG:{img_base64}"
        message = Message(MessageType.ENVOI.IMAGE, emitter=self.username, receiver=dest, value=value)
        self.ws.send(message.to_json())

    def send_video(self, filepath, dest):
        with open(filepath, "rb") as f:
            video_base64 = base64.b64encode(f.read()).decode("utf-8")
        value = f"VIDEO:{video_base64}"
        message = Message(MessageType.ENVOI.VIDEO, emitter=self.username, receiver=dest, value=value)
        self.ws.send(message.to_json())

    def send_audio(self, filepath, dest):
        with open(filepath, "rb") as f:
            audio_base64 = base64.b64encode(f.read()).decode("utf-8")
        value = f"AUDIO:{audio_base64}"
        message = Message(MessageType.ENVOI.AUDIO, emitter=self.username, receiver=dest, value=value)
        self.ws.send(message.to_json())

    def send_sensor(self, sensor_id, value, dest="ALL"):
        message = Message(MessageType.ENVOI.SENSOR, emitter=self.username, receiver=dest, value=value, sensor_id=sensor_id)
        self.ws.send(message.to_json())

    @staticmethod
    def dev(username="Client"):
        return WSClient(Context.dev(), username)

    @staticmethod
    def prod(username="MAC_KILLIAN"):
        return WSClient(Context.prod(), username)

if __name__ == "__main__":
    import sys
    username = sys.argv[1] if len(sys.argv) > 1 else "MAC_KILLIAN"
    client = WSClient.prod(username)
    client.connect()
 