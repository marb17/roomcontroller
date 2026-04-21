from enum import IntEnum
from dataclasses import dataclass

class ACMode(IntEnum):
    AUTO = 0
    COOL = 1
    DRY = 2
    FAN = 3
    HEAT = 4

class ACFAN(IntEnum):
    AUTO = 0
    MIN = 1
    MID = 2
    MAX = 3

class RemoteLogic:
    """
    Binary Logic for remote control
    """
    def __init__(self) -> None:
        self.power: bool = False
        self.mode: str = "000"
        self.fan: str = "00"
        self.set_temp: str = "0000"
        self.turbo: bool = False
        self.light: bool = False

        # fixed parameters (can change for defaults
        self._swing: bool = False
        self._sleep: bool = False
        self._timer_enabled: bool = False
        self._timer_length: str = "00000000"
        self._xfan: bool = False
        self._fixed_bits: str = "00001010010"

    def change_power(self, power: bool) -> None:
        self.power = power

    def change_turbo(self, turbo: bool) -> None:
        self.turbo = turbo

    def change_light(self, light: bool) -> None:
        self.light = light

    def change_mode(self, mode: ACMode) -> None:
        _holding = f"{mode:03b}"
        self.mode = _holding[::-1]

    def change_fan(self, fan: ACFAN) -> None:
        _holding = f"{fan:02b}"
        self.fan = _holding[::-1]

    def change_temp(self, temp: int) -> None:
        temp = temp - 16
        _holding = f"{temp:04b}"
        self.set_temp = _holding[::-1]

    def output_bits(self) -> str:
        """
        Returns the data stream (bits) to be sent to the IR Transmitter
        :return: Sends 35-bit data to IR Transmitter
        """
        # https://docs.google.com/spreadsheets/d/1VWTlw9T2uBZYaaK_nX8VJDdJvWaTJjG5y5TLrykS6XQ/edit?usp=sharing
        # Data Analysis

        if not self.power: # mode
            _final_bits = "10"
        else:
            _final_bits = self.mode

        _final_bits += '1' if self.power else '0' # on/off state

        if self.mode == "01": # fan speed
            _final_bits += "10"
        else:
            _final_bits += self.fan

        _final_bits += '1' if self._swing else '0' # swing
        _final_bits += '1' if self._sleep else '0' # sleep

        if self.mode == "00": # temperature
            _final_bits += '1001'
        elif not self.power:
            _final_bits += '0010'
        else:
            _final_bits += self.set_temp

        _final_bits += self._timer_length # timer length (fixed)
        _final_bits += '1' if self.turbo else '0' # turbo
        _final_bits += '1' if self.light else '0' # light
        _final_bits += '1' if self.power else '0' # weird bit?
        _final_bits += '1' if self._xfan else '0' # xfan (fixed)
        _final_bits += self._fixed_bits # fixed bits (maybe extra config?)

        return _final_bits

if __name__ == "__main__":
    remote = RemoteLogic()
    print(remote.output_bits())