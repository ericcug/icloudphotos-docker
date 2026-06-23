import socket\nold_getaddrinfo = socket.getaddrinfo\ndef new_getaddrinfo(*args, **kwargs):\n    return old_getaddrinfo(*args, **kwargs)\n
