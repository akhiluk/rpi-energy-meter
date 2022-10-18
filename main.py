"""
main.py
=======

    A Python script for connecting to the Secure Elite 445
    energy meter using the Modbus protocol.
    Once the connection has been made, the values for the parameters
    that are required are obtained. Each set of values is then
    sent to a psuedo-API endpoint running on a Django app
    on a webserver.

    Dependencies
    ============
        * minimalmodbus >= 2.0.1
        * pyserial >= 3.5
        * requests >= 2.28.1
"""

import os
import sys
import requests
import time
import logging
import minimalmodbus
import serial
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
                177, 179, 181, 183, 185, 187, 223, 733]

PARAMETER_NAME_LIST = ['timestamp', 'r_vtg', 'y_vtg', 'b_vtg', 'r_curr',
                        'y_curr', 'b_curr', 'r_active_curr', 'y_active_curr',
                        'b_active_curr', 'r_reactive_curr', 'y_reactive_curr',
                        'b_reactive_curr', 'r_pf', 'y_pf', 'b_pf',
                        'r_active_pwr', 'y_active_pwr', 'b_active_pwr',
                        'r_react_pwr', 'y_react_pwr', 'b_react_pwr',
                        'r_apparent_pwr', 'y_apparent_pwr', 'b_apparent_pwr',
                        'r_vtg_thd', 'y_vtg_thd', 'b_vtg_thd', 'r_curr_thd',
                        'y_curr_thd', 'b_curr_thd', 'abs_active_energy',
                        'total_energy_imp', 'phase_imbalance']

# Change `DJANGO_SERVER_URL` to the actual URL of the API endpoint
# before deploying!
DJANGO_SERVER_URL = ''

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

def execute_loop(DJANGO_SERVER_URL: str):
    """ The main code snippet that runs in an infinite loop.
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
    while(True):
        values_list = []
        values_dict = {}

        # Initialise the dictionary object
        # will None values.
        values_dict['timestamp'] = None
        for i in PARAMETER_NAME_LIST:
            values_dict[i] = None

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
            instrument.serial.timeout = 1

            for i in range(0, len(REGISTER_LIST)):
                # Read the value in each required register sequentially
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

            values_list.append(phase_imbalance)

            # Zip the parameter names (keys) and the register values (values)
            # into a different dictionary, then send the contents of that
            # dictionary as the POST-request payload to the Django app
            # on the server.
            final_dict = dict(zip(values_dict, values_list))
            post_request = requests.POST(DJANGO_SERVER_URL, data = final_dict)

            loop_counter += 1
            logging.info(
                f"""Added row {loop_counter} to the file 
                at {time_now}. Server response code: 
                {post_request.text}.""")
            time.sleep(3)

        except IllegalRequestError as ire:
            logging.error("""READ_ERROR: Could not read values from
             device registers. More details: """, exc_info = 1)

        except SerialException as se:
            logging.error("""DEVICE_CONNECT_ERROR: Could not create a 
            connection with the device. More details: """, exc_info = 1)
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

    # With the initial configuration done,
    # let's call the main loop
    execute_loop(DJANGO_SERVER_URL)