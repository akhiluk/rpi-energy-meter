# Raspberry Pi Energy Meter

## About The Python Script

A Python script for connecting to the Secure Elite 445 energy meter using the Modbus protocol.

Once the connection has been made, the values for the parameters that are required are obtained. Each set of values is then sent to a psuedo-API endpoint running on a Django app on a webserver.

### New in version 1.2c

* Integrated a TOML configuration file, so vital details, such as the energy meter Modbus ID and the server URL do not need to be hardcoded within the scripts.

* Better documentation for the `ping.py` script.

### New in version 1.2b

* Improved the logging facilities of the script so that the log file no longer grows uncontrollably. Upon reaching a maximum size of 5 MB it rolls over to the next log file, with there being upto 5 log files for analysis.

#### Added in version 1.2b patch 1

* Made the script agnostic to the server URL provided. The domain name of the server is enough, with the API endpoint URL being added to it within the script.

### New in version 1.2

* The readings are now stored locally in a CSV file if there is no network connection to the server present. When the connection is restored, all the backlogged data is sent in bulk to the server.

* Operation continues as usual from that point on. If the network connection persists, data is sent to the server as soon as it is collected. Otherwise, the data is stored in the CSV file locally.

### New in version 1.1b

* The script now detects the IP address of the host Raspberry Pi and includes it in the payload sent to the Django app. This IP address is then stored for aid in trouble-shooting sessions over SSH.

### Dependencies

* `minimalmodbus` >= 2.0.1

* `pyserial` >= 3.5

* `requests` >= 2.28.1
