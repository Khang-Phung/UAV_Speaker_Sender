
from enum import Enum, auto

class SenderState(Enum): 
    STOPPED = auto() 
    RUNNING = auto() 
    RECORDING = auto() 
    LOOPING = auto()
    DISCONNECTED = auto()