#!/usr/bin/python3

# Based on https://github.com/russinnes/py-vox-recorder/blob/master/py-corder-osx.py
# apt-get install python3-pyaudio python3-numpy libasound2-dev

import argparse
# Alsa blarg error blocking imports
# See https://stackoverflow.com/questions/7088672/pyaudio-working-but-spits-out-error-messages-each-time
#     for original code
from ctypes import *
from contextlib import contextmanager
# These 3 for tty status checking
import sys
import tty
import termios
# These for the sound stuff
import pyaudio
import threading
import time
import numpy as np
import queue
import wave

FORMAT = pyaudio.paInt16
CHANNELS = 1

sDEVINDEX    = 'DEVINDEX'
sTHRESHOLD   = 'THRESHOLD'
sSAVERECS    = 'SAVERECS'
sHANGDELAY   = 'HANGDELAY'
sCHUNK       = 'CHUNK'
sDEVRATE     = 'DEVRATE'
sCURRENT     = 'CURRENT'
sRECORDFLAG  = 'RECORDFLAG'
sRUNNING     = 'RUNNING'
sPEAKFLAG    = 'PEAKFLAG'
sTTYSETTINGS = 'TTYSETTINGS'
sTTYFD       = 'TTYFD'
sPREQUE      = 'PREQUE'
sRCNT        = 'RCNT'
sPYAUDIO     = 'PYAUDIO'
sDEVSTREAM   = 'DEVSTREAM'
sRT          = 'RT'
sPROCESSOR   = 'PROCESSOR'
sSAMPLEQUEUE = 'SAMPLEQUEUE'
sKM          = 'KM'

PDAT = {}
PDAT[sDEVINDEX] = PDAT[sTHRESHOLD] = PDAT[sSAVERECS] = PDAT[sHANGDELAY] = PDAT[sCHUNK] = PDAT[sDEVRATE] = PDAT[sCURRENT] = 0
PDAT[sRECORDFLAG] = PDAT[sRUNNING] = PDAT[sPEAKFLAG] = False
PDAT[sTTYSETTINGS] = PDAT[sTTYFD] = PDAT[sPYAUDIO] = PDAT[sDEVSTREAM] =PDAT[sPROCESSOR] = PDAT[sSAMPLEQUEUE] = None
PDAT[sPREQUE] = {}
PDAT[sRCNT] = 0

# Alsa error message blocking

ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)

def py_error_handler(filename, line, function, err, fmt):
    pass

c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)

@contextmanager
def noalsaerr():
    asound = cdll.LoadLibrary('libasound.so')
    asound.snd_lib_error_set_handler(c_error_handler)
    yield
    asound.snd_lib_error_set_handler(None)

# Code for the app

class _streamProcessor(threading.Thread):
    def __init__(self, pdat):
        threading.Thread.__init__(self)
        self.setDaemon(True)
        self.pdat = pdat
        self.rt = self.pdat[sRT]
        self.queue = self.pdat[sSAMPLEQUEUE]
        self.prequeue = self.pdat[sPREQUE]
        self.wf = None
        self.filename = "No File"
        
    def run(self):
        while self.pdat[sRUNNING]:
            data = self.queue.get(1)
            if data == None:
                time.sleep(0.1)
            else:
                data2 = np.fromstring(data,dtype=np.int16)
                peak = np.average(np.abs(data2))
                peak = (100*peak)/2**12
                self.pdat[sCURRENT] = int(peak)
                if self.pdat[sCURRENT] > self.pdat[sTHRESHOLD]:
                    self.rt.reset_timer(time.time())
                if self.pdat[sRECORDFLAG]:
                    if not self.wf:
                        self.filename = time.strftime("%Y%m%d-%H%M%S.wav")
                        print("opening file " + self.filename + "\r")
                        self.wf = wave.open(self.filename, 'wb')
                        self.wf.setnchannels(CHANNELS)
                        self.wf.setsampwidth(self.pdat[sPYAUDIO].get_sample_size(FORMAT))
                        self.wf.setframerate(self.pdat[sDEVRATE])
                        if self.pdat[sRCNT] != 0:
                            self.pdat[sRCNT] = 0
                            while True:
                                try:
                                    data3 = None
                                    data3 = self.prequeue.get_nowait()
                                    self.wf.writeframes(data3)
                                except:
                                    pass
                                if data3 == None: break
                                pass
                    self.wf.writeframes(data)
                else:
                    if self.pdat[sRCNT] == self.pdat[sSAVERECS]:
                        data3 = self.prequeue.get_nowait()
                    else:
                        self.pdat[sRCNT] =  self.pdat[sRCNT]+1
                    self.prequeue.put(data)
                    pass
             
    def ReadCallback(self, indata, framecount, timeinfo, status):
        self.queue.put(indata)
        if self.pdat[sRUNNING]:
            return(None, pyaudio.paContinue)
        else:
            return(None, pyaudio.paAbort)

    def close(self):
        if self.wf:
            self.wf.close()
            self.wf = False
            self.filename = "No File"

class _recordTimer(threading.Thread):
    def __init__(self, pdat):
        threading.Thread.__init__(self)
        self.pdat = pdat
        self.setDaemon(True)
        self.timer = 0
        
    def run(self):
        while self.pdat[sRUNNING]:
            if time.time() - self.timer < self.pdat[sHANGDELAY]:
                self.pdat[sRECORDFLAG] = True
            if time.time() - self.timer > self.pdat[sHANGDELAY] + 1:
                self.pdat[sRECORDFLAG] = False
                self.pdat[sPROCESSOR].close()
            if self.pdat[sPEAKFLAG]:
                nf = min (self.pdat[sCURRENT], 99)
                nf2 = nf
                if nf > 50: nf = int(min(50 + (nf - 50)/3, 72))
                if nf <= 0: nf=1
                rf = ""
                if self.pdat[sRECORDFLAG]: rf = "*"
                print("{} {}{}\r".format("#"*nf, nf2, rf))
            time.sleep(1)
                
    def reset_timer(self, timer):
        self.timer = timer

class KBListener(threading.Thread):
    def __init__(self,pdat):
        threading.Thread.__init__(self)
        self.pdat = pdat
        self.setDaemon(True)

    def treset(self):
        termios.tcsetattr(self.pdat[sTTYFD], termios.TCSADRAIN, self.pdat[sTTYSETTINGS])

    def getch(self):
        try:
            tty.setraw(self.pdat[sTTYFD])
            ch = sys.stdin.read(1)
            self.treset()
        finally:
            self.treset()
        return ch
    
    def rstop(self):
        self.pdat[sRT].reset_timer(0)
        self.pdat[sRECORDFLAG] = False
        self.pdat[sTHRESHOLD] = 100
        self.pdat[sPROCESSOR].close()

    def run(self):
        self.pdat[sTTYFD] = sys.stdin.fileno()
        self.pdat[sTTYSETTINGS] = termios.tcgetattr(self.pdat[sTTYFD])
        while self.pdat[sRUNNING]:
            ch = self.getch()
            if ch == "h" or ch == "?":
                print("h: help, f: show filename, k:show peak level, p: show peak")
                print("q: quit, r: record on/off, v: set trigger level")
            elif ch == "k":
                print("Peak/Trigger: " + str(self.pdat[sCURRENT]) + " " + str(self.pdat[sTHRESHOLD]))
            elif ch == "v":
                self.treset()
                pf = self.pdat[sPEAKFLAG]
                self.pdat[sPEAKFLAG] = False
                try:
                    newpeak = int (input("New Peak Limit: "))
                except:
                    newpeak = 0
                if newpeak == 0:
                    print("? Number not recognized")
                else:
                    self.pdat[sTHRESHOLD] = newpeak
                self.pdat[sPEAKFLAG] = pf
            elif ch == "f":
                if self.pdat[sRECORDFLAG]:
                    print("Filename: " + self.pdat[sPROCESSOR].filename)
                else:
                    print("Not recording")
            elif ch == "r":
                if self.pdat[sRECORDFLAG]:
                    self.rstop()
                    print("Recording disabled")
                else:
                    self.pdat[sRECORDFLAG] = True
                    self.pdat[sTHRESHOLD] = 1
                    self.pdat[sRT].reset_timer(time.time())
                    print("Recording enabled")
            elif ch == "p":
                self.pdat[sPEAKFLAG] = not self.pdat[sPEAKFLAG]
            elif ch == "q":
                print("Quitting...")
                self.rstop()
                self.pdat[sRUNNING] = False
                self.treset()
                time.sleep(0.5)
#
# Main code. Parse command and execute
#
parser = argparse.ArgumentParser()
parser.add_argument("command", choices=['record', 'listdevs'],   help="'record' or 'listdevs'")
parser.add_argument("-c", "--chunk",     type=int, default=8192, help="Chunk size [8192]")
parser.add_argument("-d", "--devno",     type=int, default=2,    help="Device number [2]")
parser.add_argument("-s", "--saverecs",  type=int, default=8,    help="Records to buffer ahead of threshold [8]")
parser.add_argument("-t", "--threshold", type=int, default=99,   help="Minimum volume threshold (1-99) [99]")
parser.add_argument("-l", "--hangdelay", type=int, default=6,    help="Seconds to record after input drops below threshold [6]")
args = parser.parse_args()
PDAT[sDEVINDEX] = args.devno
PDAT[sTHRESHOLD] = args.threshold
PDAT[sSAVERECS] = args.saverecs
PDAT[sHANGDELAY] = args.hangdelay
PDAT[sCHUNK] = args.chunk
#
# Fire up PyAudio and process the request
#
with noalsaerr():
    PDAT[sPYAUDIO] = pyaudio.PyAudio()

if args.command == "listdevs":
    print("Device Information:")
    for i in range(PDAT[sPYAUDIO].get_device_count()):
        print("Dev#: ",i, PDAT[sPYAUDIO].get_device_info_by_index(i).get('name'))
else:
    PDAT[sSAMPLEQUEUE] = queue.Queue()
    PDAT[sPREQUE] = queue.Queue()

    PDAT[sRUNNING] = True
    PDAT[sRT] = _recordTimer(PDAT)
    PDAT[sPROCESSOR] = _streamProcessor(PDAT)
    PDAT[sPROCESSOR].start()
    PDAT[sRT].start()

    PDAT[sDEVRATE] = int(PDAT[sPYAUDIO].get_device_info_by_index(PDAT[sDEVINDEX]).get('defaultSampleRate'))
    PDAT[sDEVSTREAM] = PDAT[sPYAUDIO].open(format=FORMAT,
                                             channels=CHANNELS,
                                             rate=PDAT[sDEVRATE],
                                             input=True,
                                             input_device_index=PDAT[sDEVINDEX],
                                             frames_per_buffer=PDAT[sCHUNK],
                                             stream_callback=PDAT[sPROCESSOR].ReadCallback)
    PDAT[sDEVSTREAM].start_stream()

    PDAT[sKM] = KBListener(PDAT)
    PDAT[sKM].start()

    while PDAT[sRUNNING]:
        time.sleep(1)

print("Done.")
