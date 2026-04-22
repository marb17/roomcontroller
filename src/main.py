from machine import I2C, Pin
import time

# Exceptions
class InputMismatch(Exception):
    pass

class InvalidPin(Exception):
    pass


# Classes
class I2CBus:
    def __init__(self, port, sda=Pin(0), scl=Pin(1), freq=100000) -> None:
        self.i2c = I2C(port, sda=sda, scl=scl, freq=freq)
        self._claimed_addresses = set()

    def __str__(self) -> list[str]:
        return self.scan(print_output=False)

    def claim_address(self, address: int) -> None:
        if address in self._claimed_addresses:
            raise ValueError(f"Address {address} already claimed!")
        self._claimed_addresses.add(address)

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
        i2c_bus.claim_address(address)

        self._claimed_pins = set()

        self._bus = i2c_bus
        self._address = address
        self._valid_pins = [0, 1, 2, 3, 4, 5, 6, 7,
                            10, 11, 12, 13, 14, 15, 16, 17]
        self._pin_mode = bytearray([0xFF, 0xFF])

        self.write_all(bytearray([0xFF, 0xFF]))

    def claim_pin(self, pin: int) -> None:
        if pin in self._claimed_pins:
            raise ValueError(f"Pin {pin} already claimed!")
        self._claimed_pins.add(pin)

    def current_pin_state(self) -> bytearray:
        return self._pin_mode

    def read_all(self) -> bytes:
        return self._bus.readfrom(self._address, 2)

    def read_pin(self, pin: int) -> bool:
        """
        :param pin: Uses board pin out (P07-P00 P17-P10)
        :return: True if GND, False if VCC
        """
        if pin not in self._valid_pins:
            raise InvalidPin("Pin is not present in PCF8575")

        _data = self.read_all()
        return not bool((_data[pin // 10] >> (pin % 10)) & 1)

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
        if pin not in self._valid_pins:
            raise InvalidPin("Pin is not present in PCF8575")
        if value not in ["HIGH", "LOW"]:
            raise InvalidPin("Set state is not a valid state")

        _temp_pin_mode = self._pin_mode

        if value == "HIGH":
            _temp_pin_mode[0 if (pin // 10) == 0 else 1] |= (1 << (pin % 10))
        else:
            _temp_pin_mode[0 if (pin // 10) == 0 else 1] &= ~(1 << (pin % 10))

        self.write_all(self._pin_mode)


class PCF8575Multiplex(PCF8575):
    def __init__(self, i2c_bus: I2CBus, rows: list[int], column: list[int], address: int = 0x20) -> None:
        super().__init__(i2c_bus, address)

        self._claimed_xy = set()

        self._rows = rows
        self._column = column

        self.reset_pins()

        for r in self._rows:
            self.claim_pin(r)
        for c in self._column:
            self.claim_pin(c)

    def claim_xy(self, xy: tuple[int, int]) -> None:
        if xy in self._claimed_xy:
            raise ValueError(f"XY {xy} already claimed!")
        self._claimed_xy.add(xy)

    def reset_pins(self):
        for r in self._rows:
            self.write_pin(r, "HIGH")
        for c in self._column:
            self.write_pin(c, "HIGH")

    def read_grid(self, safe=False) -> list[list[bool]]:
        """
        :return: A nested list [x][y]; x being the row and y being the column in respect with the list given during initialization
        """
        _data = []

        if safe:
            self.reset_pins()

        for x in self._rows:
            _temporary = []
            self.write_pin(x, "LOW")
            for y in self._column:
                _temporary.append(self.read_pin(y))
            self.write_pin(x, "HIGH")
            _data.append(_temporary)

        return _data

    def read_pin_from_grid(self, row, column, safe=False) -> bool:
        if row not in self._rows or column not in self._column:
            raise InvalidPin("Pin is not present in multiplex, please recheck row and column arguments")

        if safe:
            self.reset_pins()

        self.write_pin(row, "LOW")
        _state = self.read_pin(column)
        self.write_pin(row, "HIGH")

        return _state


class Switch:
    def __init__(self, gpio_device: PCF8575 | PCF8575Multiplex, pin: int | tuple[int, int], debounce_ms=20) -> None:
        if type(gpio_device) is PCF8575 and isinstance(pin, tuple):
            raise InputMismatch("GPIO Device does not match pin input or vise versa.")
        if type(gpio_device) is PCF8575Multiplex and isinstance(pin, int):
            raise InputMismatch("GPIO Device does not match pin input or vise versa.")

        self._gpio_device = gpio_device
        self._pin = pin

        if type(gpio_device) is PCF8575 and isinstance(self._pin, int):
            self._gpio_device.write_pin(self._pin, "HIGH")
            self._read_method = self._gpio_device.read_pin
            gpio_device.claim_pin(self._pin)
        elif type(gpio_device) is PCF8575Multiplex and isinstance(pin, tuple):
            self._read_method = self._gpio_device.read_pin_from_grid
            gpio_device.claim_pin(self._pin)

        self._debounce_ms = debounce_ms

        self._current_stable_state = False
        self._last_state_reading = False
        self._last_time_changed = time.ticks_ms()

    def get_state(self) -> bool:
        if isinstance(self._pin, int):
            raw_reading = self._gpio_device.read_pin(self._pin)
        else:
            raw_reading = self._gpio_device.read_pin_from_grid(self._pin[0], self._pin[1])

        if self._debounce_ms != 0:
            now = time.ticks_ms()

            if raw_reading != self._last_state_reading:
                self._last_time_changed = now
                self._last_state_reading = raw_reading

            if time.ticks_diff(now, self._last_time_changed) > self._debounce_ms:
                self._current_stable_state = raw_reading

            return self._current_stable_state
        else:
            return raw_reading


if __name__ == "__main__":
    i2c_bus = I2CBus(0, sda=Pin(16), scl=Pin(17), freq=100000)

    # pcf1 = PCF8575(i2c_bus, address=0x23)
    pcf1 = PCF8575Multiplex(i2c_bus, [0, 1, 2, 3, 4, 5, 6, 7], [10, 11, 12, 13, 14, 15, 16, 17], address=0x23)

    switch1 = Switch(pcf1, (0, 10))

    # switch1 = Switch(pcf1, 0)

    while True:
        print(switch1.get_state())
        time.sleep(0.05)

    # start = time.ticks_us()
    # print(switch1.get_state())
    # end = time.ticks_us()
    # diff = time.ticks_diff(end, start)
    #
    # print(f"Execution time: {diff} microseconds")
