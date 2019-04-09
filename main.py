import sys, time, sched, threading
from datetime import datetime
from Libraries import SmartPi
from Libraries import evbox
import RPi.GPIO as GPIO
import json
import serial
import math

# Initialisations
# --------------------------------------------------
settings_file = '/boot/SmatchatHome_config.json'


def load_settings():
    f = open(settings_file)
    parameters = json.load(f)
    f.close()
    return parameters


params = load_settings()

# Debug flag to show intermediate results or not
debug = True

# Initialisation of the threading
s = sched.scheduler(time.time, time.sleep)
station_management = {}

# Initialize GPIOs for mode switching
GPIO.setmode(GPIO.BOARD)
Btn_9 = 21
Btn_10 = 19
GPIO.setup([Btn_9, Btn_10], GPIO.IN, pull_up_down=GPIO.PUD_UP)

# Initialisation of the Smatch @ Home algorithms
mode = "Peak-shaving"
iStation = 0
order = 0
station = evbox.EVBox()


def log(line, filename):
    f = open(filename + '.txt', 'a')
    f.write(str(datetime.now()) + ': ' + line + '\n')
    f.close()
    print(str(datetime.now()) + ': ' + line)


def getmode():
    global mode
    if GPIO.input(Btn_9) == 0 and GPIO.input(Btn_10) == 1:
        # Charging only from local PV with first priority
        if mode != "PV_High-priority":
            log("Mode changed from " + mode + " to PV_High-priority", 'logfile')
            mode = "PV_High-priority"
        return mode
    elif GPIO.input(Btn_9) == 1 and GPIO.input(Btn_10) == 1:
        # Charging only from local PV with low priority
        if mode != "PV_Low-priority":
            log("Mode changed from " + mode + " to PV_Low-priority", 'logfile')
            mode = "PV_Low-priority"
        return mode
    elif GPIO.input(Btn_9) == 1 and GPIO.input(Btn_10) == 0:
        # Power limitation according to the max consumption of the house
        if mode != "Peak-shaving":
            log("Mode changed from " + mode + " to Peak-shaving", 'logfile')
            mode = "Peak-shaving"
        return mode
    else:
        return -1


def SinaB():
    global mode,  order, iStation, station_management
    # New inscription to the scheduler
    log('Next EV-Box command at: ' + time.ctime(get_next_timestamp()), 'logfile')
    station_management = s.enterabs(get_next_timestamp(), 2, SinaB, ())
    if debug: print("SinaB launched !")

    # Set constant for house
    iMaxHouse = params['SinaB']['MaxConsoCurrent']

    # Get measurements
    measures = thread_measure.getmean()
    timestamp, iBatt, iPV, iConso = datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 0, 0, 0
    if measures != -1:
        timestamp = measures[0]
        iBatt = measures[1]     # CT connected to I1 terminal also plugged on the battery phase
        iPV = abs(measures[2])       # CT connected to I2 terminal also connected on the PV inverter output phase
        iConso = abs(measures[3])  # CT connected to I3 also connected on the main line phase
        if debug: print("{} : iBatt={} iPV={} iConso={}".format(timestamp, iBatt, iPV, iConso))
    else:
        if debug: print("SmartPi.getmean() returned -1")

    # Set constant for EVBox stations
    poleMin = params['EVBox']['poleMin']
    poleMax = params['EVBox']['poleMax']
    timeout = params['EVBox']['timeout']
    defaultCurrent = params['EVBox']['defaultCurrent']
    if debug: print("poleMin={} poleMax={} timeout={} defaultCurrent={}".format(poleMin, poleMax, timeout, defaultCurrent))

    # Get button position
    mode = getmode()
    if debug: print("Control mode selected : {}".format(mode))

    # The next calculus are taking the following assumptions, they are required for a normal working
    # - iBatt, from i1 on the Smatch Box is connected to the phase of the battery,
    #   the arrow of the current sensor show current flow when the battery is DISCHARGING
    # - iPV, from i2 on the Smatch Box is connected to the phase of the PV inverter
    #   as it is only production, the sens of the clamp is not important, however, it should indicate the prod flow
    # - iConso, from i3 on the Smatch Box is connected to the sub-circuit part that contains ONLY CONSUMPTION
    #   as it is only consumption, the sens of the clamp is not important, however, it should indicate the prod flow
    order = 0
    if mode == "PV_High-priority":
        print("PV_High-priority")
        # calculation of the max current allowed to send to the pole
        # Rule = The max current the charging station is allowed to use
        # is equal to the instant PV production measured at the output of the inverter.

        # if we accept to take a bit on the grid at a low current, uncomment below
        # if iPV < poleMin and iConso < iMaxHouse + iPV:
        #    order = poleMin
        # else:
        order = iPV

    elif mode == "PV_Low-priority":
        print("PV_Low-priority")
        # calculation of the max current allowed to send to the pole
        # Rule = The max current the charging station is allowed to use
        # is equal to the instant PV production,
        # minus the house consumption, minus the battery charging.
        if iBatt > 0:  # battery is discharging
            # The discharge of the battery is not PV production, it doesn't enter in account
            # The own current of the station is removed from the total consumption
            order = iPV - iConso + iStation
        else:
            # The battery also charge on PV it has priority in that case
            # The own current of the station is removed from the total consumption
            order = iPV - iConso + iBatt + iStation

    else:  # self.mode == "Peak-shaving":
        print("Peak-shaving")
        # calculation of the max current to send to the pole
        # Rule = The max current the charging station is allowed to use
        # is equal to the max current allowed by the grid, minus the current consumption.
        order = iMaxHouse - iConso + iStation

    # Verification of the order
    if order > poleMax:  # there is more power than what the station can deliver
        order = poleMax
    if order < 0:  # there is no power for car :(
        order = 0

    if debug: print("order={}A - defaultcurrent={}A".format(order, defaultCurrent))
    # build the payload
    order *= 10  # value need to be in a tenth of A : 16 A -> 160 dA
    defaultCurrent *= 10
    message = "%0.4X" % order + "%0.4X" % order + "%0.4X" % order + "%0.4X" % \
              timeout + "%0.4X" % defaultCurrent + "%0.4X" % defaultCurrent + "%0.4X" % defaultCurrent
    response = sendto_evbox(message)
    if debug: print("EVBox answer is {}".format(response))

    # EVBox response analyse
    if response[:6] == "A08069":
        # intro = result[:6]  # sender - receiver - command
        # timeout = int(result[6:10], 16)  # timeout in second
        # maxsetcurrent = int(result[10:14], 16) / 10  # max charging current per phase converted form hex  A/10
        nbconnectors = int(response[14:16], 16)  # Nb charging point managed by the master
        if debug: print("Number of connectors associated to this modem : {}".format(nbconnectors))

        p = 16  # Position of the first relevant data
        connector = [[0 for j in range(8)] for i in range(nbconnectors)]

        for i in range(0, nbconnectors):  # in our case, only one
            connector[i][0] = int(response[p:p + 4], 16) / 10  # minimum current
            connector[i][1] = int(response[p + 4:p + 8], 16) / 10  # actual charging current on L1
            connector[i][2] = int(response[p + 8:p + 12], 16) / 10  # actual charging current on L2
            connector[i][3] = int(response[p + 12:p + 16], 16) / 10  # actual charging current on L3
            connector[i][4] = int(response[p + 16:p + 20], 16) / 1000  # actual power factor on L1
            connector[i][5] = int(response[p + 20:p + 24], 16) / 1000  # actual power factor on L2
            connector[i][6] = int(response[p + 24:p + 28], 16) / 1000  # actual power factor on L3
            connector[i][7] = int(response[p + 28:p + 36], 16)  # Watt hour meter value
            iStation = 230 * (
                    connector[0][1] * connector[0][4] +
                    connector[0][2] * connector[0][5] +
                    connector[0][3] * connector[0][6])
        log("EV-Box answer : " + str(connector), 'logfile')
        log("{};{};{};{};{};{};{};{}".format(timestamp, "measures", 0, 0, 0, iBatt, iPV, iConso), 'KPI')
        log("{};{};{};{};{};{};{};{}".format(timestamp, "EVCmd", 0, 0, 0, order, order, order), "KPI")
        # the result is an error
    else:
        log("EV-Box answer : " + response, 'logfile')


def sendto_evbox(payload):

    RS485 = serial.Serial(
        port=params['Serial']['port'],
        baudrate=params['Serial']['baudrate'],
        bytesize=params['Serial']['bytesize'],
        parity=params['Serial']['parity'],
        stopbits=params['Serial']['stopbits'],
        timeout=params['Serial']['timeout'],
        writeTimeout=params['Serial']['writeTimeout']
    )

    # Sending order to the charging station
    result = station.setmaxcurrent(payload, RS485)
    return result


def get_next_timestamp():
    poll = params['SinaB']['RefreshF']
    startTime = time.localtime()
    delta = (-(startTime.tm_min % poll) + poll - 1) * 60 + (60 - startTime.tm_sec)
    return math.floor(time.mktime(time.localtime()) + delta)


if __name__ == "__main__":
        if len(sys.argv) == 1:
            # Log initialisation
            log('Started script at' + time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), 'logfile')
            log('timestamp;Id;vL1;vL2;vL3;iL1;iL2;iL3', 'KPI')

            # Launching of the current measurement thread :
            # initialisation of a frame 2 times bigger then the refresh frequency to get moving mean
            thread_measure = SmartPi.SmartPi(5, params['SinaB']['RefreshF']*12)  # 24 for moving mean
            thread_measure.daemon = True
            thread_measure.start()
            if debug: print("thread measure launched")

            # Launching of the charging station control routine :
            # Launch SinaB method every minute
            nexttimestamp=get_next_timestamp()
            if debug: print("Next timestamp : {}".format(datetime.fromtimestamp(nexttimestamp).strftime('%Y-%m-%d %H:%M:%S')))
            station_management = s.enterabs(nexttimestamp, 1, SinaB, ())
            if debug: print("Thread SinaB ready to be run")
            s.run()
            if debug: print("station_management launched, next run at :" +
                            str(datetime.fromtimestamp(nexttimestamp).strftime('%Y-%m-%d %H:%M:%S')))
        elif sys.argv[1] == 'sync':
            print('Synching system')
            pass
