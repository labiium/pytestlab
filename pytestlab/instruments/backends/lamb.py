import requests

class VisaInstrument:
    def __init__(self, manufacturer, model_name, url="http://lamb-server:8000"):
        self.url = url
        self.manufacturer = manufacturer
        self.model_name = model_name
        self.add()


    def add(self):
        response = requests.post(
            f"{self.url}/add", 
            json={"manufacturer": self.manufacturer, "model_name": self.model_name},  # Use the json parameter to ensure the payload is properly encoded as JSON
            headers={"Accept": "application/json", 'Accept-Charset': 'utf-8'}
            )
        if response.status_code != 200:
            raise Exception(f"{response.text}")
    
    def write(self, command):
        response = requests.post(
            f"{self.url}/instrument/write", 
            json={"model_name": self.model_name, "command": command},  # Use the json parameter to ensure the payload is properly encoded as JSON
            headers={"Accept": "application/json", 'Accept-Charset': 'utf-8'}
            )
        if response.status_code != 200:
            raise Exception(f"{response.text}")

    def query(self, command):
        response = requests.post(
            f"{self.url}/instrument/query", 
            json={"model_name": self.model_name, "command": command},  # Use the json parameter to ensure the payload is properly encoded as JSON
            headers={"Accept": "application/json", 'Accept-Charset': 'utf-8'}
            )
        if response.status_code != 200:
            raise Exception(f"{response.text}")
        content = response.content.decode('utf-8')
        if content.endswith("\n"):
            return content[:-1]
    
    def query_raw(self, command):
        response = requests.post(
            f"{self.url}/instrument/query_raw", 
            json={"model_name": self.model_name, "command": command},  # Use the json parameter to ensure the payload is properly encoded as JSON
            headers={"Accept": "application/json"}
            )
        if response.status_code != 200:
            raise Exception(f"{response.text}")
        return response.content
    
    def close(self):
        pass