#!/usr/bin/env python
# -*- coding: ascii -*-
######################################################################################################
#
#               Communication module for EV-Box charging points via RS485 "Max" protocol
#
######################################################################################################
#                                     ________________
#                                     |              |
#                                     |     Back     |
#                                     |    Office    |
#                                     |              |
#                                     |______________|
#                                             ^
#                                             .
#                                             .
#                                        GPRS / UMTS
#                                             .
#                                             .
#                                             v
#                                     ________________                         _________________
#                                     |              |                         |               |
#                                     | ChargePoint  |        RS4845           |     EVPi      |
#                                     |    Module    |<------------------------|    Module     |
#                                     |    ```````   |                         | (Smart Home   |
#                                     |              |                         | Charging Ctrl)|
#                                     |______________|                         |_______________|
#                                             ^
#                                             |RS485
#             +--------------------+----------+----------+--------------------+
#             |                    |                     |                    |
#             v                    v                     v                    v
#     _________________    _________________     _________________    _________________
#     |               |    |               |     |               |    |               |
#     |   ChargeBox   |    |   ChargeBox   |     |   ChargeBox   |    |   ChargeBox   |
#     |    Module 1   |    |    Module 2   |     |    Module 3   |    |    Module x   |
#     |               |    |               |     |               |    |               |
#     |_______________|    |_______________|     |_______________|    |_______________|
#
######################################################################################################
import os
import sys
import serial
import time
import operator
from functools import reduce


# Main command : send phases' max power to the EV-Box charging point
# ------------------------------------------------------------------
# TRAME structure : START | ADDRESSES | COMMAND | DATA | CHECKSUM | STOP
# Beginning structure
#     Recipient address : Chargepoint = 0x80 | Broadcast = 0xBC
#     Sender address : 0xA0
#     Command : Only 0x69
# Data structure : All currents in dA
#     Courant max phase L1 */** 1 mot
#     Courant max phase L2 */** 1 mot
#     Courant max phase L3 */** 1 mot
#     Timeout en secondes 1 mot
#     Courant max phase L1 si timeout */** 1 mot
#     Courant max phase L2 si timeout */** 1 mot
#     Courant max phase L3 si timeout */** 1 mot
# Sending example : data = '00E6008C0154003C002800500046'
#
# Answer example : A080690001015E02007800000000000003E803E803E800000028007800000000000003E803E803E80000001EC47A
#   Here the answer has been converted from byte array to string with .convert("utf-8")
# Answer structure : Data
#     Intervalle minimum admissible an seconde 1 mot
#     Courant max par phase de la station 1 mot
#     Nombre de modules ChargeBox connect?s [n] 1 octet
#     Donnees des ChargeBox n*9 mots
#       Courant minimum requis par phase 1 mot
#       Courant utilise sur L1 1 mot
#       Courant utilise sur L2 1 mot
#       Courant utilise sur L3 1 mot
#       Cosinus phi L1 1 mot
#       Cosinus phi L1 1 mot
#       Cosinus phi L1 1 mot
#       Valeur totale compteur kWh en Wh 2 mot

class EVBox:

    def __init__(self):
        """Communication method for EV-Box charging points.
        Connexion type RS485 with a master that could have up to 20 connectors"""

        # bytes to begin and finish a command to the charging point
        self.start = 0x02
        self.stop = 0x03

        # Addresses
        self.modem_adr = "80" # address of the master modem to call to manage the charging power
        self.manager_adr = "A0" # address of the Energy manager that send the commands
        # Broadcast = "BC"
        self.cmd = "69" # The only existing command for EV-Box charging points
        self.adr = self.modem_adr + self.manager_adr
        self.rien = 0

    # Checksum calculation
    # --------------------
    def chksum(self, payload):
        # data = adr + cmd + payload
        crcl = '{:X}'.format(sum(bytearray(payload, 'ascii')) % 256).zfill(2)
        # if python 3 : crch = '{:X}'.format(reduce(operator.xor, bytes(payload, 'ascii'), 0)).zfill(2)
        crch = '{:X}'.format(reduce(operator.xor, bytearray(payload, 'ascii'), 0)).zfill(2)
        return crcl + crch

    # Main command : send phases' max power to the EV-Box charging point
    # ------------------------------------------------------------------
    def setmaxcurrent(self, data, RS485):
        # RS485 : serial instance that enable RS484 communication with th pole
        # data : part that contain the data in the TRAME structure
        # TRAME structure : START | ADDRESSES | COMMAND | DATA | CHECKSUM | STOP
        # Beginning structure
        #     Recipient address
        #     Sender address
        #     Command
        # Data structure :
        #     Courant max phase L1 */** 1 mot
        #     Courant max phase L2 */** 1 mot
        #     Courant max phase L3 */** 1 mot
        #     Timeout en secondes 1 mot
        #     Courant max phase L1 si timeout */** 1 mot
        #     Courant max phase L2 si timeout */** 1 mot
        #     Courant max phase L3 si timeout */** 1 mot
        # Sending example : data = '00E6008C0154003C002800500046'
        #
        # Answer example : A080690001015E02007800000000000003E803E803E800000028007800000000000003E803E803E80000001EC47A
        #   Here the answer has been converted from byte array to string with .convert("utf-8")
        # Answer structure : Data
        #     Intervalle minimum admissible an seconde 1 mot
        #     Courant max par phase de la station 1 mot
        #     Nombre de modules ChargeBox connect?s [n] 1 octet
        #     Donn?es des ChargeBox n*9 mots
        #       Courant minimum requis par phase 1 mot
        #       Courant utilise sur L1 1 mot
        #       Courant utilise sur L2 1 mot
        #       Courant utilise sur L3 1 mot
        #       Cosinus phi L1 1 mot
        #       Cosinus phi L1 1 mot
        #       Cosinus phi L1 1 mot
        #       Valeur totale compteur kWh en Wh 2 mot

        # check data validity
        if len(data) != 28:
            return "-1 The payload is not valid"
        print("data is valid : " + data)
        # Building the payload
        payload = self.modem_adr + self.manager_adr + self.cmd + data

        # calculate checksum
        checksum = self.chksum(payload)
        trame = bytearray(chr(self.start) + payload + checksum + chr(self.stop), 'ascii')
        print("trame = " + trame)  # payload + " " + checksum)
        print("Sending over RS485")
        # Send command to the charging station
        try:
            sent = RS485.write(trame)
            print("sent data len = " + str(sent))
        except serial.SerialTimeoutException as e:
            # sending timeout raised
            print("timeout raised: ", e.message)
            return "-2 Sending timeout raised"
        else:
            # Data properly sent, wait 100ms for an answer
            wait = 0.1
            timeout = 10
            timeExpired = 0
            while True:
                wait += 0.1
                time.sleep(0.1)
                if RS485.inWaiting() > 0:  # old version of PySerial : in_waiting > 0:  # answer received
                    break
                elif wait > timeout:  # no answer after timeout
                    timeExpired = 1
                    break

        if timeExpired == 0:
            # Read the answer
            answer_length = RS485.inWaiting() # in_waiting
            answer = RS485.read(answer_length)
            # Remove non-printable characters
            answer = ''.join([ch for ch in answer if ord(ch) > 31 and ord(ch) < 127])
            print("EVBox.answer : " + answer + " type : " + str(type(answer)) + " length : " + str(len(answer)))

            # Verify the checksum
            received_checksum = answer[- 4:]
            received_payload = answer[:- 4]
            print("EVBox.received_checksum : " + received_checksum)
            print("EVBox.received_payload : " + received_payload)
            print("EVBox.calculated_cheksum : " + self.chksum(received_payload))
            if received_checksum == self.chksum(received_payload):
                return received_payload
            else:
                return "-3 error with checksum"
        else:
            return "-4 Serial waiting timeout expired"
