from machine import I2C, Pin
from time import sleep


class I2CBus:
    def __init__(self, port, sda=Pin(0), scl=Pin(1), freq=100000) -> None:
        self.i2c = I2C(port, sda=sda, scl=scl, freq=freq)

    def __str__(self) -> list[str]:
        return self.scan(print_output=False)

    def scan(self, print_output=True) -> list[str]:
        _available_addresses = []
        for item in self.i2c.scan():
            _available_addresses.append(hex(item))

        if print_output:
            print(f"Available Devices: {_available_addresses}")

        return _available_addresses

    def readfrom(self, addr, nbytes) -> bytes:
        return self.i2c.readfrom(addr, nbytes)

    def writeto(self, addr, buf) -> None:
        self.i2c.writeto(addr, buf)

    def writeto_mem(self, addr, memaddr, buf) -> None:
        self.i2c.writeto_mem(addr, memaddr, buf)


class PCF8575:
    def __init__(self, i2c_bus: I2CBus, address: int = 0x20) -> None:
        """
        Defaults all pins as INPUT / HIGH
        """
        self._bus = i2c_bus
        self._address = address
        self._pin_mode = bytearray([0xFF, 0xFF])

        self.write_all(bytearray([0xFF, 0xFF]))

    def current_pin_state(self) -> bytearray:
        return self._pin_mode

    def read_all(self) -> bytes:
        return self._bus.readfrom(self._address, 2)

    def read_pin(self, pin: int) -> bool:
        """
        :param pin: Uses board pin out (P07-P00 P17-P10)
        :return: True if GND, False if VCC
        """
        # TODO optimize code, maybe change to bitwise or just rewrite this is so shit
        _data = self.read_all()
        _data = _data.hex()
        _data = int(_data, 16)
        _data = f'{_data:016b}'

        _data = f"{"".join(reversed(_data[0:8]))}{"".join(reversed(_data[8:16]))}"

        if pin // 10 == 0:
            return not bool(_data[pin])
        else:
            return not bool(_data[pin - 2])

    def write_all(self, data: bytearray) -> None:
        """
        :param data: Inputs two bytes to be written, 1 = HIGH : 0 = LOW
        """
        self._pin_mode = data
        self._bus.i2c.writeto(self._address, self._pin_mode)

    def write_pin(self, pin: int, value: str) -> None:
        """
        :param pin: Uses board pin out (P07-P00 P17-P10)
        :param value: str of "HIGH" or "LOW" to set pin mode
        """
        #! not sure if it works
        # TODO will have to fix or rewrite cuz this code is shit
        _temp_pin_mode = self._pin_mode[1] << 8 | self._pin_mode[0]
        _temp_pin_mode = bytearray(_temp_pin_mode.to_bytes(2, 'big'))

        if value == "HIGH":
            _temp_pin_mode[1 - (pin // 10)] |= (1 << (pin % 10))
        else:
            _temp_pin_mode[1 - (pin // 10)] &= ~(1 << (pin % 10))

        _temp_pin_mode = _temp_pin_mode[1] | _temp_pin_mode[0] << 8
        self._pin_mode = bytearray(_temp_pin_mode.to_bytes(2, 'little'))

        self.write_all(self._pin_mode)


if __name__ == "__main__":
    i2c_bus = I2CBus(0, sda=Pin(16), scl=Pin(17), freq=10000)

    pcf1 = PCF8575(i2c_bus, address=0x23)

    while True:
        print(pcf1.read_pin(0))
        sleep(0.05)



