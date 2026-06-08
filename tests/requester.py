import requests


class Requester():
    def __init__(self, port=8000):
        self.__default_url = f"http://localhost:{port}"
        self.__url = ''
        self.__data = {}
        self.__use_get_method = True
        self.__method = "GET"
        self.__headers = {}
        self.__use_json_body = False
        self.last_response = None
    
    @property
    def url(self):
        return self.__url

    @url.setter
    def url(self, sub):
        self.__url = self.__default_url + sub
    def headers(self, **kwargs):
        self.__headers = {k:v for k,v in kwargs.items()}
    def data(self, **kwargs):
        self.__data = {k:v for k,v in kwargs.items()}

    def query(self):
        query_method = getattr(requests, self.__method.lower())
        request_kwargs = {"headers": self.__headers}
        if self.__method == "GET" or not self.__use_json_body:
            request_kwargs["params"] = self.__data
        else:
            request_kwargs["json"] = self.__data
        res = query_method(self.__url, **request_kwargs)
        self.last_response = res
        res.raise_for_status()

        return res.json()

    def toggle_get_method(self):
        self.__use_get_method = not self.__use_get_method
        self.__method = "GET" if self.__use_get_method else "POST"
        return {"use_get_method":self.__use_get_method}

    def use_json_body(self, enabled=True):
        self.__use_json_body = bool(enabled)
        return {"use_json_body": self.__use_json_body}

    def method(self, value):
        value = str(value).upper()
        if value not in {"GET", "POST", "DELETE"}:
            raise ValueError(f"unsupported method: {value}")
        self.__method = value
        self.__use_get_method = value == "GET"
        return {"method": self.__method}

