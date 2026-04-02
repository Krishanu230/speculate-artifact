import threading


class ThreadSafeComponents:
    def __init__(self):
        self.components = {"components": {"schemas": {}, "securitySchemes": {}}}
        self.lock = threading.Lock()

    def update_schemas(self, key, value):
        with self.lock:
            self.components["components"]["schemas"][key] = value

    def update_security(self, key, value):
        with self.lock:
            self.components["components"]["securitySchemes"][key] = value

    def get_schemas(self):
        with self.lock:
            return self.components["components"]["schemas"].copy()

    def check_security_scheme_exists(self, name):
        with self.lock:
            return name in self.components["components"]["securitySchemes"]

    def get_full_components(self):
        with self.lock:
            return self.components.copy()
    
    def get_schema_count(self):
        with self.lock:
            return len(self.components["components"]["schemas"])


class ThreadSafeVariable:
    def __init__(self):
        self.value = 0
        self.lock = threading.Lock()

    def increment(self, value=1):
        with self.lock:
            self.value += value

    def decrement(self, value=1):
        with self.lock:
            self.value -= value

    def get_value(self):
        with self.lock:
            return self.value


class ThreadSafeString:
    def __init__(self):
        self.value = ""
        self.lock = threading.Lock()

    def increment(self, value):
        with self.lock:
            self.value += value

    def get_value(self):
        with self.lock:
            return self.value

class ThreadSafeDualString:
    def __init__(self):
        self.value1 = ""
        self.value2 = ""
        self.lock = threading.Lock()

    def increment(self, value1, value2):
        with self.lock:
            self.value1 += value1
            self.value2 += value2

    def get_value(self):
        with self.lock:
            return self.value1, self.value2


class ThreadSafePaths:
    def __init__(self):
        self.paths = {"paths": {}}
        self.lock = threading.Lock()

    def update_paths(self, key, value):
        with self.lock:
            self.paths["paths"][key] = value

    def get_paths(self):
        with self.lock:
            return self.paths["paths"].copy()

    def get_full_paths(self):
        with self.lock:
            return self.paths.copy()

    def delete_key(self, key):
        with self.lock:
            del self.paths["paths"][key]
    
    def get_path_count(self):
        with self.lock:
            count=0
            for endpoint in self.paths["paths"].keys(): count+=len(self.paths["paths"][endpoint])
            return count


class ThreadSafeList:
    def __init__(self):
        self.lock = threading.Lock()
        self.arr = []

    def append(self, item):
        with self.lock:
            self.arr.append(item)

    def get(self):
        with self.lock:
            return self.arr
    
    def get_length(self):
        with self.lock:
            return len(self.arr)
