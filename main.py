"""
main.py
=======

    A Python script for connecting to the Secure Elite 445
    energy meter using the Modbus protocol.
    
    * Once the connection has been made, the values for the parameters
    that are required are obtained. Each set of values is then
    sent to a psuedo-API endpoint running on a Django app
    on a webserver.

    * New in version 1.2
    ====================
        The readings are now stored locally in a CSV file if there
        is no network connection to the server present. When the
        connection is restored, all the backlogged data is sent
        in bulk to the server.
        Operation continues as usual from that point on. If the network
        connection persists, data is sent to the server as soon as it is
        collected. Otherwise, the data is stored in the CSV file locally.
    
    * New in version 1.1b
    =====================
        The script now detects the IP address of the host Raspberry Pi
        and includes it in the payload sent to the Django app. This IP
        address is then stored for aid in trouble-shooting sessions over SSH.

    Dependencies
    ============
        * minimalmodbus >= 2.0.1
        * pyserial >= 3.5
        * requests >= 2.28.1
"""

import os
import sys
import csv
import requests
import time
import logging
import minimalmodbus
import serial
import socket
from minimalmodbus import IllegalRequestError
from serial import SerialException
from requests import ConnectionError, Timeout

# DECLARE CONSTANTS HERE
# ======================

# Change `METER_ID` to the actual value of the Modbus ID set on the
# energy meter before deploying!
METER_ID = 101

REGISTER_LIST = [99, 101, 103, 113, 115, 117, 121, 123, 125, 127, 129, 131,
                133, 135, 137, 141, 143, 145, 149, 151, 153, 157, 159, 161,
                177, 179, 181, 183, 185, 187, 223, 223]

PARAMETER_NAME_LIST = ['timestamp', 'r_vtg', 'y_vtg', 'b_vtg', 'r_curr',
                        'y_curr', 'b_curr', 'r_active_curr', 'y_active_curr',
                        'b_active_curr', 'r_reactive_curr', 'y_reactive_curr',
                        'b_reactive_curr', 'r_pf', 'y_pf', 'b_pf',
                        'r_active_pwr', 'y_active_pwr', 'b_active_pwr',
                        'r_react_pwr', 'y_react_pwr', 'b_react_pwr',
                        'r_apparent_pwr', 'y_apparent_pwr', 'b_apparent_pwr',
                        'r_vtg_thd', 'y_vtg_thd', 'b_vtg_thd', 'r_curr_thd',
                        'y_curr_thd', 'b_curr_thd', 'abs_active_energy',
                        'total_energy_imp', 'phase_imbalance',
                        'meter_id', 'ip_address']

# Change `DJANGO_SERVER_URL` to the actual URL of the API endpoint
# before deploying!
DJANGO_SERVER_URL = ''

CSV_FILE_NAME = 'energy_meter_readings.csv'

LOG_FILE_NAME = 'rpi_energy_meter.log'

loop_counter = 0

def convert_mantissa(mantissa_str: str) -> int:
    """ Given a string consisting of binary digits,
    converts them into a proper decimal number.
    The positional power of 2 is calculated for each
    bit and then multipled with that bit.
    Similar to the manual method of converting
    binary numbers into decimal numbers.

    Paramters:
    ==========
        mantissa_str: str
        A string consisting of zeroes and ones
        representing a binary number.

    Returns:
    ========
        mantissa_int: int
        The decimal equivalent of the binary
        number represented by the argument string.
    """
    power_count = -1
    mantissa_int = 0
    for element in mantissa_str:
        mantissa_int += (int(element) * pow(2, power_count))
        power_count -= 1
    return mantissa_int + 1

def convert_to_decimal(register_value: list) -> float:
    """ Converts the 32-bit binary number obtained from a register
    into a floating-point decimal number. 
    This is done by using the conversion method specified by the
    IEEE Standard for Floating-Point Arithmetic (IEEE 754).
    Read more here: https://en.wikipedia.org/wiki/IEEE_754

    Parameters:
    ===========
        register_value: list
        A list containing two elements, each of which
        is a 16-character string representing
        one half of the total 32-bit binary number.

    Returns:
    ========
        decimal_number: float
        The value of the parameter present in the register
        in a decimal floating-point value.
    """
    parameter_value = []
    parameter_value.append('{0:016b}'.format(register_value[0]))
    parameter_value.append('{0:016b}'.format(register_value[1]))
    binary_string = parameter_value[1] + parameter_value[0]
    sign_bit = int(binary_string[0])
    exponent = int(binary_string[1:9], 2)
    exponent -= 127
    mantissa_binary = binary_string[9:]
    mantissa_decimal = convert_mantissa(mantissa_binary)
    decimal_number = pow(-1, sign_bit) * (mantissa_decimal) * pow(2, exponent)
    return decimal_number

def get_ip() -> str:
    """ A helper function that returns the IP address
    of the host machine this script is running on.
    
    Parameters:
    ===========
        None

    Returns:
    ========
        ip_address: str
        A string containing the IP address of the host Raspberry
        Pi. If the function failed, it returns `127.0.0.1` as a
        default failsafe.
    """
    ip_address = ''
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0)
    try:
        sock.connect(('10.254.254.254', 1))
        ip_address = sock.getsockname()[0]
    except Exception:
        ip_address = '127.0.0.1'
    finally:
        sock.close()
    return ip_address

def clear_csv(file_name: str):
    """ Given the name of a CSV file,
    truncates the contents and re-adds
    the column names to the now empty file.

    Parameters:
    ===========
        file_name: str
        The name of the CSV file, present in
        the same directory as this script.

    Returns:
    ========
        None
    """
    clear_file = open(file_name, 'w+')
    clear_file.close()
    with open(file_name, 'w', encoding = "utf-8") as csv_file:
        writer_object = csv.DictWriter(csv_file, fieldnames = PARAMETER_NAME_LIST)
        writer_object.writeheader()

def is_connected(hostname: str) -> bool:
    """ Returns True or False based on whether the host
    was able to create a socket connection to the URL of the
    Django app.
    Failure in creating a socket connection implies lack of
    a proper network connection, or an issue with the Django app
    server, so the script shifts to "offline" mode operation.

    Parameters:
    ===========
        hostname: str
        The URL of the host to connect to, which will mostly
        be the URL of the server the Django app is running on.
        If need be, the IP address of a DNS server can also be
        provided - 1.1.1.1 for example.

    Returns:
    ========
        connection_status: bool
        A Boolean object with either True or False, depending
        on the network status.
    """
    connection_status = False
    try:
        host = socket.gethostbyname(hostname)
        socket_object = socket.create_connection((host, 80), 2)
        socket_object.close()
        connection_status = True
        return connection_status
    except Exception:
        pass
    return connection_status

def get_and_send_readings(DJANGO_SERVER_URL: str):
    """ The main code snippet that gets the readings from
    the energy meter and sends it over to the Django server.
    A connection to the energy meter is created, then the register
    values are read. Each set of readings is stored as a row in the
    CSV file locally on the Raspberry Pi storage.

    Parameters:
    ===========
        DJANGO_SERVER_URL: str
        The URL of the endpoint to which the script has to
        send the collected set of readings.

    Returns:
    ========
        None
    """
    values_list = []
    values_dict = {}

    # Initialise the dictionary object
    # with None values.
    for parameter in PARAMETER_NAME_LIST:
        values_dict[parameter] = None

    time_now = time.strftime('%Y-%m-%d %H:%M:%S')
    values_list.append(time_now)

    try:
        # Let's specify the connection parameters to connect to the
        # energy meter and then configure it.
        instrument = minimalmodbus.Instrument('/dev/ttyUSB0', METER_ID, minimalmodbus.MODE_RTU)
        instrument.serial.baudrate = 9600
        instrument.serial.bytesize = 8
        instrument.serial.parity = serial.PARITY_NONE
        instrument.serial.stopbits = 2
        instrument.seial.timeout = 1

        for i in range(0, len(REGISTER_LIST)):
            # Read the value of each required register sequentially
            # and then store it in the list.
            register_value_binary = instrument.read_registers(REGISTER_LIST[i], 2, 3)
            actual_value = convert_to_decimal(register_value_binary)
            values_list.append(actual_value)

        # Phase imbalance needs to be calculated manually, so let's
        # do that now.
        r_current = values_list[5]
        y_current = values_list[6]
        b_current = values_list[7]

        avg_current = (r_current + y_current + b_current)/3
        max_phase_current = max(r_current, y_current, b_current)
        phase_imbalance = max_phase_current/avg_current

        ip_address = get_ip()

        values_list.append(phase_imbalance)
        values_list.append(METER_ID)
        values_list.append(ip_address)

        # Zip the parameter names (keys) and the register values (values)
        # into a different dictionary.
        final_dict = dict(zip(values_dict, values_list))

        if not is_connected(DJANGO_SERVER_URL):
            # Check if we are able to create a socket connection to the
            # Django app. If we aren't able to connect, we'll work
            # in "offline" mode - append the readings to the CSV file.
            with open(CSV_FILE_NAME, 'a+', encoding = "utf-8") as csv_file:
                writer_object = csv.DictWriter(csv_file, fieldnames = PARAMETER_NAME_LIST)
                writer_object.writerow(final_dict)
        else:
            # In this case, we `are` connected, and the current set of
            # readings (and any backlogged data in the CSV file) can
            # be sent to the server.
            #
            # So we'll add our current set of readings to the CSV
            # file first.
            with open(CSV_FILE_NAME, 'a+', encoding = "utf-8") as csv_file:
                writer_object = csv.DictWriter(csv_file, fieldnames = PARAMETER_NAME_LIST)
                writer_object.writerow(final_dict)
            # Then, we open the CSV file and send the data
            # within it to the server, row by row.
            with open(CSV_FILE_NAME, 'r') as csv_file:
                reader_object = csv.DictReader(csv_file)
                for row in reader_object:
                    final_dict['timestamp'] = row['timestamp']

                    final_dict['r_vtg'] = row['r_vtg']
                    final_dict['y_vtg'] = row['y_vtg']
                    final_dict['b_vtg'] = row['b_vtg']

                    final_dict['r_curr'] = row['r_curr']
                    final_dict['y_curr'] = row['y_curr']
                    final_dict['b_curr'] = row['b_curr']
                    
                    final_dict['r_active_curr'] = row['r_active_curr']
                    final_dict['y_active_curr'] = row['y_active_curr']
                    final_dict['b_active_curr'] = row['b_active_curr']

                    final_dict['r_reactive_curr'] = row['r_reactive_curr']
                    final_dict['y_reactive_curr'] = row['y_reactive_curr']
                    final_dict['b_reactive_curr'] = row['b_reactive_curr']

                    final_dict['r_pf'] = row['r_pf']
                    final_dict['y_pf'] = row['y_pf']
                    final_dict['b_pf'] = row['b_pf']

                    final_dict['r_active_pwr'] = row['r_active_pwr']
                    final_dict['y_active_pwr'] = row['y_active_pwr']
                    final_dict['b_active_pwr'] = row['b_active_pwr']

                    final_dict['r_react_pwr'] = row['r_react_pwr']
                    final_dict['y_react_pwr'] = row['y_react_pwr']
                    final_dict['b_react_pwr'] = row['b_react_pwr']

                    final_dict['r_apparent_pwr'] = row['r_apparent_pwr']
                    final_dict['y_apparent_pwr'] = row['y_apparent_pwr']
                    final_dict['b_apparent_pwr'] = row['b_apparent_pwr']

                    final_dict['r_vtg_thd'] = row['r_vtg_thd']
                    final_dict['y_vtg_thd'] = row['y_vtg_thd']
                    final_dict['b_vtg_thd'] = row['b_vtg_thd']

                    final_dict['r_curr_thd'] = row['r_curr_thd']
                    final_dict['y_curr_thd'] = row['y_curr_thd']
                    final_dict['b_curr_thd'] = row['b_curr_thd']

                    final_dict['abs_active_energy'] = row['abs_active_energy']
                    final_dict['total_energy_imp'] = row['total_energy_imp']
                    final_dict['phase_imbalance'] = row['phase_imbalance']

                    final_dict['meter_id'] = row['meter_id']
                    final_dict['rpi_ip_address'] = row['rpi_ip_address']

                    post_request = requests.POST(DJANGO_SERVER_URL, data = final_dict)
            # Once all the rows in the CSV file have been
            # sent over, we call `clear_csv()` to truncate
            # the CSV file without losing its column names/headers.
            clear_csv(CSV_FILE_NAME)
        logging.info(f"""Added row to the file at {time_now}.""")
    
    except IllegalRequestError as ire:
        logging.error("""READ_ERROR: Could not read values from
        device registers. More details: """, exc_info = 1)
    
    except SerialException as se:
        logging.error("""DEVICE_CONNECT_ERROR: Could not create a
        conncetion with the device. More details: """, exc_info = 1)
        time.sleep(10)
        sys.exit(1)
    
    except ConnectionError as ce:
        logging.error("""HTTP_CONNECT_ERROR: Could not connect to
        the Django application server. More details: """, exc_info = 1)
        time.sleep(10)
    
    except Timeout as te:
        logging.error("""TIMEOUT_ERROR: The request to the server
        timed out. More details: """, exc_info = 1)

if __name__ == '__main__':
    # A quick sanity check to see if the log file
    # exists. If not, we'll just create it.
    if not os.path.exists(LOG_FILE_NAME):
        create_log_file = open(LOG_FILE_NAME, 'w+')
        create_log_file.close()

    # Let's quickly set up the logging
    # as well while we're here.
    logger = logging.getLogger(__name__)
    logging.basicConfig(filename = LOG_FILE_NAME,
                        filemode = 'a',
                        format = """%(asctime)s - %(name)s -
                        %(levelname)s - %(message)s""",
                        datefmt = '%Y-%m-%d %H:%M:%S',
                        level = logging.DEBUG)

    # A quick sanity check to see if the CSV
    # file that will hold all the readings exists.
    # If not, we'll create it with the headers
    # in place.
    if not os.path.exists(CSV_FILE_NAME):
        with open(CSV_FILE_NAME, 'w', encoding = "utf-8") as csv_file:
            writer_object = csv.DictWriter(csv_file, fieldnames = PARAMETER_NAME_LIST)
            writer_object.writeheader()
    
    # With the initial configuration done,
    # let's call the main loop
    get_and_send_readings(DJANGO_SERVER_URL)