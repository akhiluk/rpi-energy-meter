"""
ping.py
=======

    A Python script that sends the current timestamp to
    the Django app running on a remote server. This lets
    the users on the Django app know the last time this
    particular Raspberry Pi was active.
    
    Dependencies
    ============
        * request >= 2.28.1
"""

import time
import requests
import tomllib

def load_toml():
    """ Opens the TOML file containing vital configuration
    details and stores them in a dictionary that can be
    accessed as needed.
    
    Parameters:
    ===========
        None
    
    Returns:
    ========
        config: dict[str, str]
        A dictionary containing the configuration
        details as key-value pairs.
    """
    with open("config.toml", mode = "rb") as toml_config:
        config = tomllib.load(toml_config)
    return config

if __name__ == "__main__":
    # Load the configuration details from the `config.toml` file.
    # This file contains details about the URL of the Django server
    # and the modbus ID of the energy meter to which the Raspberry Pi
    # is connected.
    config = load_toml()

    METER_ID = int(config["meter_id"])
    SERVER_URL = config["server_url"]
    PING_URL = SERVER_URL + "/ping/"

    # Get the current time.
    time_now = time.strftime("%Y-%m-%d %H:%M:%S")
    
    # Package the required details (current timestamp, and the Modbus ID)
    # and send a POST request to the server.
    payload = {
        'timestamp': time_now,
        'meter_id': METER_ID
    }

    post_request = requests.post(PING_URL, data = payload)