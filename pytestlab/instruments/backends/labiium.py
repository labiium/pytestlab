import requests

class VisaInstrument:
    def __init__(self, vid, pid, url="http://localhost:8000"):
        self.url = url
        self.vid = vid
        self.pid = pid

    
    def write(self, command):
        response = requests.post(f"{self.url}/write", data={"vendor_id": self.vid, "product_id": self.pid, "command": command})
        if response.status_code != 200:
            raise Exception(f"Failed to send command: {response.text}")


    def query(self, command):
        response = requests.post(f"{self.url}/query", data={"vendor_id": self.vid, "product_id": self.pid, "command": command})
        if response.status_code != 200:
            raise Exception(f"Failed to send command: {response.text}")
        return response.text
    
    def query_raw(self, command):
        response = requests.post(f"{self.url}/query_raw", data={"vendor_id": self.vid, "product_id": self.pid, "command": command})
        if response.status_code != 200:
            raise Exception(f"Failed to send command: {response.text}")
        return response.content