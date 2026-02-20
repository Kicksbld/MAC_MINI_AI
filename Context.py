# machine à etat qui suivant si prod ou dev on change l'url en ws ou wss
class Context:
    def __init__(self, host, port):
        self.host = host
        self.port = port

    def url(self):
        return f"ws://{self.host}:{self.port}"

    @staticmethod
    def dev():
        return Context("0.0.0.0", 8765)
    
    @staticmethod
    def prod():
        return Context("192.168.4.230", 9000)
    
