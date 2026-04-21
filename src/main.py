from machine import I2C, Pin
from time import sleep


class I2CBus:
    def __init__(self, port, sda=Pin(0), scl=Pin(1), freq=100000) -> None:
        self.i2c = I2C(port, sda=sda, scl=scl, freq=freq)

    def __str__(self) -> str:
        return self.scan(print_output=False)

    def scan(self, print_output=True) -> None:
        _holding = []
        for item in self.i2c.scan():
            _holding.append(hex(item))

        if print_output:
            print(f"Avaliable Devices: {_holding}")

        return _holding

    def readfrom(self, addr, nbytes) -> bytes:
        return self.i2c.readfrom(addr, nbytes)


class PCF8575:
    def __init__(self, i2c_bus: I2CBus, address: int = 0x20) -> None:
        self._bus = i2c_bus
        self._address = address

    def read_pin(self, pin: int) -> bool:
        _holding = self._bus.readfrom(self._address, 2)
        _holding = _holding.hex()
        _holding = int(_holding, 16)
        _holding = f'{_holding:016b}'

        _holding = f"{"".join(reversed(_holding[0:8]))}{"".join(reversed(_holding[8:16]))}"

        return not bool(_holding[pin])

if __name__ == "__main__":
    i2c_bus = I2CBus(0, sda=Pin(16), scl=Pin(17), freq=10000)

    pcf1 = PCF8575(i2c_bus, address=0x23)

    while True:
        print(pcf1.read_pin(0))
        sleep(0.05)



