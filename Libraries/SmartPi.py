import sys
import time
from datetime import datetime
import threading
import numpy

debug = True


def log(line):
    f = open('log_Smartpi.log', 'a')
    f.write(str(datetime.now()) + ': ' + str(line) + '\n')
    f.close()
    # print(str(datetime.now()) + ': ' + str(line))


class SmartPi(threading.Thread):

    """Read consumption information and store it in the variable 'value' """

    # Initialisation of the used variables in the thread
    def __init__(self, interval, buffer_size):

        """
        Store measurement from SmartPi board and serve them when asked
        :param interval: Loop frequency in second (min 5 with SmartPi)
        :param buffer_size: Number of measure to keep in buffer
        """

        threading.Thread.__init__(self)
        self.interval = interval
        self.buffer_size = buffer_size
        self.file_to_watch = "/var/tmp/smartpi/values"
        self.items = ["timestamp", "I1", "I2", "I3", "I4", "V1", "V2", "V3", "P1", "P2", "P3", "Cos1", "Cos2",
                      "Cos3", "F1", "F2", "F3", "Balanced"]
        self.buffer = [[] for i in range(5)]  # buffer format = [[timestamp],[I1],[I2],[I3],[I4]]
        self.last_measure = 0
        self.enabled = True

    def run(self):
        while self.enabled:
            self.timer = threading.Timer(self.interval, self.readmeasure)
            self.timer.setDaemon(True)
            self.timer.start()
            self.timer.join()

    def stop(self):
        self.enabled = False
        if self.timer.isAlive():
                self.timer.cancel()

    # Get the current measure from the SmartPi program
    def readmeasure(self):
            with open(self.file_to_watch, "r") as f:
                for line in f:
                    self.process(line)

    # transform the line to have usable values and store them
    def process(self, line):

        # Separate on semicolon.
        values = line.split(";")
        del values[-1]  # there is a ";" too many
        # if debug: log(str(values) + 'EOL')
        if debug: print("{} received values, expected {} :".format(str(len(values)), str(len(self.items))))

        # format the table
        if len(values) == len(self.items):
            # convert a string to a date
            values[0] = datetime.strptime(values[0], '%Y-%m-%d %H:%M:%S')
            # round values ni the line
            for i in range(1, len(self.items)-2):
                values[i] = round(float(values[i]), 2)
                # if debug: log(self.items[i] + " = " + str(values[i]))
        log(str(values))
        print(values[:8])

        # Store the value in the Buffer
        for i in range(0, 4):
            self.buffer[i].append(values[i])

        # If buffer is full, remove the oldest value
        if len(self.buffer[0]) > self.buffer_size:
            for i in range(0, 4):
                del self.buffer[i][0]

    def getbuffer(self):
        return self.buffer

    def getrange(self, first, last):
        answer = []
        for i in range(0, 4):
            answer[i] = self.buffer[i][first:last]
        return answer

    def getmean(self, length=None, reference="begin"):
        """
        return a moving average on condition that the 'length' param is smaller than the buffer size
        if the length param is equal to the buffer size, then it's a non-moving average
        :param length: length of the array to compute
        :param reference: position of the timestamp in the average.
            'begin' = beginning of the average range
            'end' = end of the average range
        :return: Returns a list with the average of the last 'length' elements of I1 to I4 : [[timestamp],[I1],[I2],[I3],[I4]]
        """
        answer = [[] for i in range(5)]
        if debug: print("buffer len = {}".format(len(self.buffer[0])))
        if length is None:
            if len(self.buffer[0]) == 0:
                print("The buffer is empty")
                return -1
            else:
                length = len(self.buffer[0])
        elif length > len(self.buffer[0]):
            print("Frame size too big !")
            return -1

        if reference == "begin":
            if debug: print("buffer : " + str(buffer))
            answer[0] = self.buffer[0][length-1]
            for i in range(1, 4):
                answer[i] = numpy.mean(self.buffer[i][:length])
            return answer
        else:  # reference == "end"
            answer[0] = self.buffer[0][0]
            for i in range(1, 4):
                answer[i] = numpy.mean(self.buffer[i][:length])
            return answer
