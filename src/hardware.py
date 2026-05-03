import time
from machine import Pin, PWM, I2C
from typing import Callable
from enum import IntEnum


# Exceptions
class InputMismatch(Exception):
    pass

class InvalidPin(Exception):
    pass

class InvalidValue(Exception):
    pass

class InvalidSetup(Exception):
    pass


# Classes
class RaspPiPico2W:
    VALID_PINS = set(range(29))

    I2C_VALID_PINS = {
        0: {"sda": {0, 4, 8, 12, 16, 20}, "scl": {1, 5, 9, 13, 17, 21}},
        1: {"sda": {2, 6, 10, 14, 18, 26}, "scl": {3, 7, 11, 15, 19, 27}}
    }

    def __init__(self) -> None:
        self._claimed_pin = set()

    def claim_pin(self, pin: int) -> None:
        """
        Claims a pin.
        :param pin: Pin
        """
        if pin in self._claimed_pin:
            raise ValueError(f"Pin {pin} already claimed!")
        self._claimed_pin.add(pin)

    def validate_i2c_pin(self, port: int, sda: int, scl: int) -> bool:
        """
        Validates whether the parameters are a valid I2C setup
        :param port: I2C port number
        :param sda: SDA pin
        :param scl: SCL pin
        :return: True if valid, False otherwise
        """
        if port not in self.I2C_VALID_PINS:
            raise ValueError("Invalid I2C Bus ID (Must be 0 or 1).")

        valid_sda = self.I2C_VALID_PINS[port]["sda"]
        valid_scl = self.I2C_VALID_PINS[port]["scl"]

        if sda not in valid_sda or scl not in valid_scl:
            raise ValueError(f"Invalid SDA ({sda}) or SCL ({scl}) for I2C bus {port}")
        return True


class GPIOPin:
    VALID_MODES = [Pin.IN, Pin.OUT, Pin.OPEN_DRAIN, Pin.ALT]
    VALID_PULL = [None, Pin.PULL_UP, Pin.PULL_DOWN]
    VALID_VALUE = [True, False, None]

    def __init__(self, device: RaspPiPico2W, pin: int, mode: int = Pin.IN, pull: int | None = Pin.PULL_UP,
                 value: bool | None = None) -> None:
        """
        :param device: RaspPiPico2W object
        :param pin: Pin to use
        :param mode: Pin modes, [Pin.IN, Pin.OUT, Pin.OPEN_DRAIN, Pin.ALT]
        :param pull: Whether to use the onboard pull-up/down resistors, [None, Pin.PULL_UP, Pin.PULL_DOWN]
        :param value: Whether to set the pin value to [None, True, False] depending on Pin.MODE
        """
        if pin not in device.VALID_PINS:
            raise InvalidPin(f"Pin {pin} not valid!")
        if mode not in self.VALID_MODES:
            raise InvalidValue(f"Invalid mode {mode}!")
        if pull not in self.VALID_PULL:
            raise InvalidValue(f"Invalid pull {pull}!")
        if value not in self.VALID_VALUE:
            raise InvalidValue(f"Invalid value {value}!")

        device.claim_pin(pin)

        self._pin_num = pin
        self._mode = mode
        self._pull = pull
        self._value = value

        self.pin = Pin(self._pin_num, mode=self._mode, pull=self._pull, value=self._value)

    def get_state(self) -> bool:
        """
        Gets current state of the pin
        :return: HIGH == True, LOW == False
        """
        return bool(self.pin.value())

    def set_pin(self, state: bool | int | str) -> None:
        """
        Sets the pin state to VCC or GND
        :param state: HIGH == True, LOW == False
        """
        if state == True or state == "HIGH" or state == 1:
            self.pin.on()
        else:
            self.pin.off()

    def pin_toggle(self) -> None:
        """
        Toggles the pin on / off
        """
        self.pin.toggle()


class GPIOPWM:
    def __init__(self, device: RaspPiPico2W, pin: int, freq: int = 38000) -> None:
        """
        Creates a PWM pin out
        :param device: RaspPiPico2Wm object
        :param pin: Pin to use
        :param freq: Frequency of PWM cycle
        """
        device.claim_pin(pin)

        self._freq = freq
        self._pin = pin
        self._duty = 0

        self.pwm = PWM(Pin(self._pin), freq=self._freq, duty_u16=self._duty)

    @property
    def pwm_freq(self) -> int:
        return self._freq

    @pwm_freq.setter
    def pwm_freq(self, freq: int) -> None:
        # not sure what the freq range is
        self.pwm.freq(freq)

    @property
    def pwm_duty_u16(self) -> int:
        return self._duty

    @pwm_duty_u16.setter
    def pwm_duty_u16(self, duty_u16: int) -> None:
        if 0 > duty_u16 > 65535:
            raise InvalidValue("duty_u16 cannot go above 65535 or below 0!")

        self._duty = duty_u16
        self.pwm.duty_u16(duty_u16)

    def set_duty_u16(self, duty_u16: int) -> None:
        """
        Sets PWM duty cycle as a ratio of value / 65535
        """
        if 0 > duty_u16 > 65535:
            raise InvalidValue("duty_u16 cannot go above 65535 or below 0!")

        self.pwm_duty_u16 = duty_u16
        self.pwm.duty_u16(duty_u16)

    def set_duty_percentage(self, duty_percentage: int) -> None:
        """
        Sets PWM duty cycle as a percentage
        """
        if 0 > duty_percentage > 100:
            raise InvalidValue("Percentage has to be between 0 and 100!")

        _duty_u16 = round((duty_percentage / 100) * 65535)
        self.set_duty_u16(_duty_u16)


class I2CBus:
    def __init__(self, device: RaspPiPico2W, port: int = 0, sda: int = 0, scl: int = 1, freq: int = 100000,
                 stop_on_error: bool = False, cache_lifetime: int = 50) -> None:
        """
        :param device: RaspPiPico2W object
        :param port: I2C Port to be used
        :param sda: SDA pin
        :param scl: SCL pin
        :param freq: Frequency of the I2C bus
        :param stop_on_error: Whether to raise an exception when an I2C read/write error occurs
        :param cache_lifetime: If -1, cache is disabled and will always recall data. When set above 1, cache is enabled and will only recall data if the last read was more than cache_lifetime milliseconds ago.
        """
        if not device.validate_i2c_pin(port, sda, scl):
            raise InvalidPin(f"Port {port} doesn't match SDA {sda} / SCL {scl} or SDA {sda} / SCL {scl} isn't valid!")

        self.device = device

        self.i2c = I2C(port, sda=Pin(sda), scl=Pin(scl), freq=freq)
        self._claimed_addresses = set()

        for pin in [sda, scl]:
            device.claim_pin(pin)

        self._stop_on_error = stop_on_error
        self._readfrom_cache = {}
        self._last_called = time.ticks_ms()
        self._cache_lifetime = cache_lifetime

    def __str__(self) -> list[str]:
        """
        :return: All available addresses as a list
        """
        return self.scan(print_output=False)

    def claim_address(self, address: int) -> None:
        """
        Claims an address.
        :param address: Address to claim
        """
        if address in self._claimed_addresses:
            raise ValueError(f"Address {address} already claimed!")
        self._claimed_addresses.add(address)

    def scan(self, print_output: bool = True) -> list[str]:
        """
        Scans all available addresses in I2C Bus
        :param print_output: Prints the output to console
        :return: List of available addresses
        """
        _available_addresses = []
        for item in self.i2c.scan():
            _available_addresses.append(hex(item))

        if print_output:
            print(f"Available Devices: {_available_addresses}")

        return _available_addresses

    def readfrom(self, addr: int, nbytes: int, force: bool=True) -> bytes:
        """
        Reads from the I2C device
        :param addr: Address to read
        :param nbytes: How many bytes to read from the device
        :param force: Forces the device to read directly and not call cache, default is True
        """
        try:
            if self._cache_lifetime == -1 or force:
                _data = self.i2c.readfrom(addr, nbytes)
                self._readfrom_cache[addr] = _data
                return _data
            else:
                if time.ticks_diff(time.ticks_ms(), self._last_called) > self._cache_lifetime or (addr not in self._readfrom_cache):
                    _data = self.i2c.readfrom(addr, nbytes)
                    self._readfrom_cache[addr] = _data

                return self._readfrom_cache[addr]
        except Exception as e:
            if self._stop_on_error or (addr not in self._readfrom_cache):
                if addr not in self._readfrom_cache:
                    print("Nothing in cache")
                    print(f"I2C Read Error: {e}, Address: {hex(addr)}, NBytes: {nbytes}")
                raise e
            else:
                print(f"I2C Read Error: {e}, Address: {hex(addr)}, NBytes: {nbytes}")
                return self._readfrom_cache[addr]

    def writeto(self, addr: int, buf: bytes | bytearray) -> None:
        """
        Writes to I2C device
        :param addr: Address to write
        :param buf: Data (buffer) to write
        """
        try:
            self.i2c.writeto(addr, buf)
        except Exception as e:
            if self._stop_on_error:
                raise e
            else:
                print(f"I2C Write Error: {e}, Address: {hex(addr)}, Buffer: {buf}")

    def writeto_mem(self, addr: int, memaddr: int, buf: bytes | bytearray) -> None:
        """
        Writes to I2C device's memory
        :param addr: Address to write
        :param memaddr: Memory Address to write
        :param buf: Data (buffer) to write
        """
        try:
            self.i2c.writeto_mem(addr, memaddr, buf)
        except Exception as e:
            if self._stop_on_error:
                raise e
            print(f"I2C Mem-Write Error: {e}, Address: {hex(addr)}, Memory Address: {memaddr}, Buffer: {buf}")


class PCF8575:
    VALID_PINS = [0, 1, 2, 3, 4, 5, 6, 7,
                            10, 11, 12, 13, 14, 15, 16, 17]

    def __init__(self, i2c_bus: I2CBus, address: int = 0x20, cache_lifetime: int = 50) -> None:
        """
        Defaults all pins as INPUT / HIGH
        :param i2c_bus: I2C bus
        :param address: I2C address
        :param cache_lifetime: If -1, cache is disabled and will always recall data. When set above 1, cache is enabled and will only recall data if the last read was more than cache_lifetime milliseconds ago.
        """
        i2c_bus.claim_address(address)
        self._claimed_pins = set()

        self._bus = i2c_bus
        self._address = address

        self._pin_mode = bytearray([0xFF, 0xFF])
        self.write_all(self._pin_mode)

        self._cache_lifetime = cache_lifetime
        self._cache = None
        self._last_called = time.ticks_ms()

    def claim_pin(self, pin: int) -> None:
        """
        Claims a pin.
        :param pin: Pin to claim
        """
        if pin in self._claimed_pins:
            raise ValueError(f"Pin {pin} already claimed!")
        self._claimed_pins.add(pin)

    def current_pin_state(self) -> bytearray:
        """
        Returns the current pin state
        :return: Current pin state
        """
        return self._pin_mode

    def update_cache(self) -> None:
        """
        Updates the cache by reading from the device
        """
        now = time.ticks_ms()
        self._cache = self._bus.readfrom(self._address, 2)
        self._last_called = now

    def read_all(self, force: bool = False) -> bytes:
        """
        Reads all pins
        :param force: Forces device to read directly and not use cache
        :return: States of all pins as a list
        """
        if self._cache_lifetime == -1:
            return self._bus.readfrom(self._address, 2)
        else:
            if time.ticks_diff(time.ticks_ms(), self._last_called) > self._cache_lifetime or force or self._cache is None:
                self.update_cache()
            return self._cache

    def read_pin(self, pin: int, force=False) -> bool:
        """
        :param pin: Uses board pin out (P07-P00 P17-P10)
        :param force: Forces device to read directly and not use cache
        :return: True if GND, False if VCC
        """
        if pin not in self.VALID_PINS:
            raise InvalidPin("Pin is not present in PCF8575")

        _data = self.read_all(force=force)
        return not bool((_data[pin // 10] >> (pin % 10)) & 1)

    def read_pins(self, pins: list[int], force=False) -> list[bool]:
        """
        :param pins: Uses board pin out (P07-P00 P17-P10), allows multiple pins to be read at once
        :param force: Forces device to read directly and not use cache
        :return: List of True if GND, False if VCC
        """
        _data = self.read_all(force=force)
        return [not bool((_data[pin // 10] >> (pin % 10)) & 1) for pin in pins]

    def write_all(self, data: bytes | bytearray) -> None:
        """
        :param data: Inputs two bytes to be written, 1 = HIGH : 0 = LOW
        """
        self._pin_mode = data
        self._bus.writeto(self._address, self._pin_mode)

    def _edit_bit(self, value: str | bool, pin: int) -> None:
        """
        Edits a single pin's value
        :param value: str of "HIGH" or "LOW" / boolean to set pin mode
        :param pin: Pin to edit
        """
        if value == "HIGH" or value == True:
            self._pin_mode[0 if (pin // 10) == 0 else 1] |= (1 << (pin % 10))
        else:
            self._pin_mode[0 if (pin // 10) == 0 else 1] &= ~(1 << (pin % 10))

    def write_pin(self, pin: int, value: str | bool) -> None:
        """
        :param pin: Uses board pin out (P07-P00 P17-P10)
        :param value: str of "HIGH" or "LOW" to set pin mode
        """
        if pin not in self.VALID_PINS:
            raise InvalidPin("Pin is not present in PCF8575")
        if value not in ["HIGH", "LOW", True, False]:
            raise InvalidPin("Set state is not a valid state")

        self._edit_bit(value, pin)

        self.write_all(self._pin_mode)

    def update_pin(self, pin: int, value: bool | str) -> None:
        """
        Edits a single pin's value
        :param pin: Pin to edit
        :param value: str of "HIGH" or "LOW" / boolean to set pin mode
        """
        self._edit_bit(value, pin)


class PCF8575Multiplex(PCF8575):
    ROWS = [0, 1, 2, 3, 4, 5, 6, 7]
    COLUMNS = [10, 11, 12, 13, 14, 15, 16, 17]

    def __init__(self, i2c_bus: I2CBus, address: int = 0x20, cache_lifetime: int = 100) -> None:
        """
        Defaults all pins as INPUT / HIGH
        :param i2c_bus: I2C bus
        :param address: I2C address
        :param cache_lifetime: If -1, cache is disabled and will always recall data. When set above 1, cache is enabled and will only recall data if the last read was more than cache_lifetime milliseconds ago.
        """
        super().__init__(i2c_bus, address, cache_lifetime)

        self._claimed_xy = set()

        for r in self.ROWS:
            self.claim_pin(r)
        for c in self.COLUMNS:
            self.claim_pin(c)

        self.reset_pins()

        self._col_index_map = {c: index for index, c in enumerate(self.COLUMNS)}

    def claim_xy(self, xy: tuple[int, int]) -> None:
        """
        Claims a coordinate on the device
        :param xy: Coordinate to claim as a tuple, (x, y)
        """
        if xy in self._claimed_xy:
            raise ValueError(f"XY {xy} already claimed!")
        self._claimed_xy.add(xy)

    def reset_pins(self) -> None:
        """
        Resets all pins to HIGH
        """
        for r in self.ROWS:
            self.write_pin(r, "HIGH")
        for c in self.COLUMNS:
            self.write_pin(c, "HIGH")

    def update_cache(self, safe: bool = False) -> None:
        """
        Updates the cache by fully reading the device
        :param safe: Always resets pins to HIGH
        """
        _data = []

        if safe:
            self.reset_pins()

        for x in self.ROWS:
            self.write_pin(x, "LOW")
            _temporary = self.read_pins(self.COLUMNS, force=True)
            self.write_pin(x, "HIGH")
            _data.append(_temporary)

        self._cache = _data
        self._last_called = time.ticks_ms()

    def read_grid(self, safe: bool = False) -> list[bool]:
        """
        Always updates cache
        :param safe: Always resets pins to HIGH, EXTREMELY SLOW
        :return: A nested list [x][y]; x being the row and y being the column in respect with the list given during initialization
        """
        self.update_cache(safe=safe)

        return self._cache

    def read_pin_from_grid(self, row: int, column: int, safe: bool = False, force: bool = True) -> bool:
        """
        Single position check, much faster than a whole grid check.
        :param row: Row to read
        :param column: Column to read
        :param safe: Always resets pins to HIGH, EXTREMELY SLOW
        :param force: Will always read and not use cache when True, defaults to True.
        :return: True if grid is HIGH, False if grid is LOW
        """
        if row not in self.ROWS or column not in self.COLUMNS:
            raise InvalidPin("Pin is not present in multiplex, please recheck row and column arguments")

        if safe:
            self.reset_pins()

        if force or time.ticks_diff(time.ticks_ms(), self._last_called) > self._last_called:
            self.write_pin(row, "LOW")
            _state = self.read_pin(column, force=True)
            self.write_pin(row, "HIGH")
        else:
            _state = bool(self._cache[row][column])

        return _state

    def read_pins_from_grid(self, xy_list: list[tuple[int, int]], safe=False, force: bool=True) -> list[bool]:
        """
        Checks multiples grid positions and optimized for speed by caching the same row's result. Best way to check multiple positions. Fastest way and should be always be used if possible.
        :param xy_list: List of tuples (row, column)
        :param safe: Always resets pins to HIGH, EXTREMELY SLOW
        :param force: Will always read and not use cache when True, defaults to True.
        :return: List of True if grid is HIGH, False if grid is LOW
        """
        for xy in xy_list:
            if xy[0] not in self.ROWS or xy[1] not in self.COLUMNS:
                raise InvalidPin("Pin is not present in multiplex, please recheck row and column arguments")

        _data = []

        if safe:
            self.reset_pins()

        if force or time.ticks_diff(time.ticks_ms(), self._last_called) > self._last_called:
            _previous_row = -1
            _temp_data = []

            for xy in xy_list:
                if _previous_row != xy[0]:
                    if _previous_row != -1:
                        self.update_pin(_previous_row, "HIGH")
                    self.write_pin(xy[0], "LOW")
                    _previous_row = xy[0]

                    _temp_data = self.read_pins(self.COLUMNS, force=True)

                _data.append(_temp_data[self._col_index_map[xy[1]]])

            if _previous_row != -1:
                self.write_pin(_previous_row, "HIGH")
        else:
            _data = [bool(self._cache[row][self._col_index_map[col]]) for row, col in xy_list]

        return _data


class OutputPin:
    def __init__(self, write_method: Callable[[bool | str], None]) -> None:
        self._write_method = write_method

    @classmethod
    def from_gpio(cls, pin: int, device: RaspPiPico2W, invert: bool = False):
        """
        Uses the onboard RaspPi GPIO Pins.
        :param pin: Pin
        :param device: RaspPiPico2W object
        :param invert: Invert pin values
        """
        gpio_obj = GPIOPin(device, pin, Pin.OUT, None)

        def write_method(value: bool | str):
            if value == True or value == "HIGH":
                gpio_obj.set_pin(True if not invert else False)
            else:
                gpio_obj.set_pin(False if not invert else True)

        return cls(write_method)

    @classmethod
    def from_pcf8575(cls, device: PCF8575, pin: int,  invert: bool = False):
        """
        Uses the PCF8575 GPIO Pins.
        :param pin: Pin
        :param device: PCF8575 object
        :param invert: Invert pin values
        """
        device.claim_pin(pin)

        def write_method(value: bool | str):
            if value == True or value == "HIGH":
                device.write_pin(pin, True if not invert else False)
            else:
                device.write_pin(pin, False if not invert else True)

        return cls(write_method)

    def write_pin(self, value: bool | str) -> None:
        """
        Sets pin to HIGH or LOW
        :param value: str of "HIGH" or "LOW" / boolean to set pin mode
        """
        self._write_method(value)


class HC595:
    def __init__(self, device: RaspPiPico2W, serin: int = 0, rclk: int = 1, srclk: int = 2,
                 oe_pin: None | OutputPin = None) -> None:
        """
        :param device: RaspPiPico2W object
        :param serin: serin pin number
        :param rclk: rclk pin number
        :param srclk: srclk pin number
        :param oe_pin: OE pin number
        """
        self._device = device
        self._oe_pin = oe_pin

        self._serin = GPIOPin(device, serin, Pin.OUT, None)
        self._rclk = GPIOPin(device, rclk, Pin.OUT, None)
        self._srclk = GPIOPin(device, srclk, Pin.OUT, None)

        self._shift_data = bytearray([0x00])

        self._claimed_pins = set()

    def oe_pin_enable(self, value: bool | str) -> None:
        """
        Globally disables output
        :param value: str of "HIGH" or "LOW" / boolean to disable all outputs
        """
        if self._oe_pin is None:
            raise InvalidSetup("No OE pin is set!")

        if value == True or value == "HIGH":
            self._oe_pin.write_pin(False)
        else:
            self._oe_pin.write_pin(True)

    def claim_pin(self, pin: int) -> None:
        """
        Claims a pin.
        :param pin: Pin to claim
        """
        if pin in self._claimed_pins:
            raise InvalidPin(f"Pin {pin} already claimed")
        self._claimed_pins.add(pin)

    def write_data(self, data: bytes | bytearray = bytearray([0x00])) -> None:
        """
        Writes data to the shift register
        :param data: data to write, bytes to write to shift register. Starting from MSB, multiple bytes can be inputted for chained shift registers. 1: ON, 0: OFF
        """
        self._shift_data = data

        # latch off
        self._rclk.set_pin(False)

        data_to_send = reversed([(byte >> (7 - i)) & 1 for byte in self._shift_data for i in range(8)])

        for bit in data_to_send:
            # data bit
            self._serin.set_pin(bit)

            # pulse clock
            self._srclk.set_pin(True)
            self._srclk.set_pin(False)

        # latch on
        self._rclk.set_pin(True)

    def update_data(self, pin: int, value: bool | str) -> None:
        """
        Writes a pin and without updating the display
        :param pin: Pin
        :param value: str of "HIGH" or "LOW" / boolean to set pin mode
        """
        if value == True or value == "HIGH":
            self._shift_data[pin // 8] |= 1 << (7 - (pin % 8))
        else:
            self._shift_data[pin // 8] &= ~(1 << (7 - (pin % 8)))

    def write_pin(self, pin: int, value: bool | str) -> None:
        """
        Writes a pin and updates the display
        :param pin: Pin
        :param value: str of "HIGH" or "LOW" / boolean to set pin mode
        """
        self.update_data(pin, value)
        self.write_data(self._shift_data)


class LED:
    def __init__(self, shift_register: HC595, pin: int):
        self._shift_register = shift_register
        self._pin = pin
        self._value = False

        self._shift_register.claim_pin(self._pin)

    def write_led(self, value: bool | str) -> None:
        if value == True or value == "HIGH":
            self._value = True
        else:
            self._value = False

        self._shift_register.write_pin(self._pin, self._value)

    def enable_output(self, value: bool | str) -> None:
        if value == True or value == "HIGH":
            self._shift_register.write_pin(self._pin, self._value)
        else:
            self._shift_register.write_pin(self._pin, False)


class SegmentDisplay:
    CHAR_SET = {0 : [1, 1, 1, 1, 1, 1, 0],
                1 : [0, 1, 1, 0, 0, 0, 0],
                2 : [1, 1, 0, 1, 1, 0, 1],
                3 : [1, 1, 1, 1, 0, 0, 1],
                4 : [0, 1, 1, 0, 0, 1, 1],
                5 : [1, 0, 1, 1, 0, 1, 1],
                6 : [1, 0, 1, 1, 1, 1, 1],
                7 : [1, 1, 1, 0, 0, 0, 0],
                8 : [1, 1, 1, 1, 1, 1, 1],
                9 : [1, 1, 1, 0, 0, 1, 1],
                '0': [1, 1, 1, 1, 1, 1, 0],
                '1': [0, 1, 1, 0, 0, 0, 0],
                '2': [1, 1, 0, 1, 1, 0, 1],
                '3': [1, 1, 1, 1, 0, 0, 1],
                '4': [0, 1, 1, 0, 0, 1, 1],
                '5': [1, 0, 1, 1, 0, 1, 1],
                '6': [1, 0, 1, 1, 1, 1, 1],
                '7': [1, 1, 1, 0, 0, 0, 0],
                '8': [1, 1, 1, 1, 1, 1, 1],
                '9': [1, 1, 1, 0, 0, 1, 1],
                'A' : [1, 1, 1, 0, 1, 1, 1],
                'B' : [0, 0, 1, 1, 1, 1, 1],
                'C' : [0, 0, 0, 1, 1, 0, 1],
                'D' : [0, 1, 1, 1, 1, 0, 1],
                'E' : [1, 0, 0, 1, 1, 1, 1],
                'F' : [1, 0, 0, 0, 1, 1, 1]}

    def __init__(self, device: HC595, pins: list[int] ) -> None:
        """
        :param device: HC595 object
        :param pins: list of pins for the seven segment display
        """
        if len(pins) != 7:
            raise InvalidSetup(f"There are {len(pins)}!")
        if len(pins) != len(set(pins)):
            raise InvalidSetup(f"Pin are not unique!")

        self._device = device
        self._pins = pins
        self._data = None

        for pin in self._pins:
            device.claim_pin(pin)

    def write_to_display(self, char: int | str) -> None:
        """
        Writes to the display
        :param char: char to write to display (hexadecimal)
        """
        if char not in self.CHAR_SET.keys():
            raise InvalidValue("Set character is not a valid character!")

        self._data = self.CHAR_SET[char]
        _set_pins = self.CHAR_SET[char]

        for pin, bit in zip(self._pins, _set_pins):
            self._device.update_data(pin, bool(bit))

        self._device.write_data()

    def disable_display(self, value: bool) -> None:
        """
        Disables the display (locally, not globally)
        :param value: bool to disable display
        """
        if value:
            for pin in self._pins:
                self._device.update_data(pin, False)
        else:
            for pin, bit in zip(self._pins, self._data):
                self._device.update_data(pin, bool(bit))


class RotarySwitch:
    def __init__(self, switch_objects: list, read_method: Callable[[], list[bool]], cache_lifetime: int = 50) -> None:
        """
        :param cache_lifetime: If -1, cache is disabled and will always recall data. When set above 1, cache is enabled and will only recall data if the last read was more than cache_lifetime milliseconds ago.
        """
        self._switch_objects = switch_objects
        self._read_method = read_method

        self._cache_lifetime = cache_lifetime
        self._cache = None
        self._last_called = time.ticks_ms()

    @classmethod
    def from_pin(cls, pcf_device: PCF8575, pins: list[int]):
        """
        Uses the single pin mode from the PCF8575.
        :param pcf_device: PCF8575 object
        :param pins: list of pins
        """
        switches = [Switch.from_pin(pcf_device, pin) for pin in pins]

        def read_method() -> list[bool]:
            data = pcf_device.read_all()
            return [not bool((data[pin // 10] >> (pin % 10)) & 1) for pin in pins]

        return cls(switches, read_method)

    @classmethod
    def from_matrix(cls, multiplex_device: PCF8575Multiplex, xy: list[tuple[int, int]]):
        """
        Uses the matrix mode of the PCF8575.
        :param multiplex_device: PCF8575Multiplex object
        :param xy: list of pin tuples
        """
        switches = [Switch.from_matrix(multiplex_device, item) for item in xy]

        read_method = lambda: multiplex_device.read_pins_from_grid(xy)

        return cls(switches, read_method)

    def get_state(self, safe=False, force: bool = True) -> int | None:
        """
        Gets the state of the rotary switch
        :param safe: If True, if more than one position is on (electrical error), None is returned, else returns first found position
        :param force: Forces device to read directly and not use cache
        :return: Returns the position of the rotary switch, None if the signal is not stable
        """
        if force or time.ticks_diff(time.ticks_ms(), self._last_called) > self._cache_lifetime or self._cache is None or self._cache_lifetime == -1:
            _states = self._read_method()
            self._cache = _states
            self._last_called = time.ticks_ms()
        else:
            _states = self._cache

        try:
            if _states.count(True) > 1 and safe:
                return None
            return _states.index(True)
        except ValueError:
            return None

    def get_pos_state(self, pos: int) -> bool:
        """
        Gets a single position of the rotary switch and checks if it is on
        :param pos: Position of the rotary switch
        :return: Returns if a specific position is True, the same speed if not fast (due to caching) than get_state()
        """
        _data = self._read_method()
        return bool(_data[pos])

    @property
    def position(self) -> int | None:
        """
        Gets the position of the rotary switch
        :return: Returns the position of the rotary switch
        """
        return self.get_state()


class Switch:
    def __init__(self, read_func: Callable[[], bool], debounce_ms=20) -> None:
        self._debounce_ms = debounce_ms
        self._current_stable_state = False
        self._last_state_reading = False
        self._last_time_changed = time.ticks_ms()

        self._read_method = read_func

    @classmethod
    def from_pin(cls, pcf_device: PCF8575, pin_number: int, debounce: int = 20):
        """
        Creates a switch using a normal pin
        :param pcf_device: PCF8575 object
        :param pin_number: Pin
        :param debounce: Debounce time in ms
        """
        pcf_device.write_pin(pin_number, "HIGH")
        pcf_device.claim_pin(pin_number)

        read_func = lambda: pcf_device.read_pin(pin_number)

        return cls(read_func, debounce_ms=debounce)

    @classmethod
    def from_matrix(cls, multiplex_device: PCF8575Multiplex, xy: tuple[int, int], debounce: int = 20):
        """
        Creates a switch using a multiplex grid
        :param multiplex_device: PCF8575Multiplex object
        :param xy: list of pin tuples
        :param debounce: Debounce time in ms
        """
        multiplex_device.claim_xy(xy)

        read_func = lambda: multiplex_device.read_pin_from_grid(xy[0], xy[1])

        return cls(read_func, debounce_ms=debounce)

    def get_state(self) -> bool:
        """
        Gets the state of the switch
        :return: Returns the state of the switch as a bool
        """
        raw_reading = self._read_method()

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

    @property
    def is_pressed(self) -> bool:
        """
        Returns if the switch is pressed
        :return: Returns if the switch is pressed
        """
        return self.get_state()


class PCA9685:
    MODE1_ADDR = 0x00
    PRE_SCALE_ADDR = 0xFE

    def __init__(self, device: I2CBus, address: int = 0x40, min_max_range: tuple[float, float]=(2.625, 15.875),
                 oe_pin: None | OutputPin = None) -> None:
        """
        :param device: I2CBus object
        :param address: I2CBus address
        :param min_max_range: Min and max range of the servo, in duty cycle. Default is 2.625 to 15.875. Not min max range of the servo, but the range of the duty cycle.
        :param oe_pin: Output pin to enable the PCA9685. If not given, the PCA9685 will not be enabled. Requires a OutputPin object to be used.
        """
        self._device = device
        self._address = address
        self._min_max_range = min_max_range

        self._oe_pin = oe_pin

        self._pwm_freq = 50
        self._prescale_value = round((25000000 / (4096 * self._pwm_freq)) - 1)

        self._device.claim_address(self._address)

        self._initialize_device()

        self._claimed_channels = set()

    def claim_channel(self, channel: int) -> None:
        """
        Claims a channel on the PCA9685
        :param channel: Channel to claim
        """
        if channel in self._claimed_channels:
            raise InvalidPin(f"Channel {channel} already claimed!")
        self._claimed_channels.add(channel)

    def _initialize_device(self) -> None:
        """
        Initializes the PCA9685 device
        - Enables auto-increment
        - Sets the PWM frequency
        - Disables Sleep mode
        - Final restart
        """
        # auto-increment enable, low-power mode
        self._device.writeto_mem(self._address, self.MODE1_ADDR, bytearray([0x19]))
        time.sleep_ms(15)
        # set pwm frequency
        self._device.writeto_mem(self._address, self.PRE_SCALE_ADDR, bytearray([self._prescale_value]))
        time.sleep_ms(15)
        # sleep mode disable
        self._device.writeto_mem(self._address, self.MODE1_ADDR, bytearray([0x21]))
        time.sleep_ms(15)
        # restart
        self._device.writeto_mem(self._address, self.MODE1_ADDR, bytearray([0xA1]))
        time.sleep_ms(15)

    def write_duty_cycle(self, channel: int, duty_cycle: float) -> None:
        """
        Writes raw duty cycle percentage to a channel.
        :param channel: Channel to write the duty cycle to
        :param duty_cycle: Duty cycle percentage
        """
        if channel not in range(16):
            raise InvalidValue(f"Channel {channel} is not a valid channel!")

        _off_count = round((duty_cycle / 100) * 4095)
        _off_count = _off_count.to_bytes(2, "big")

        self._device.writeto_mem(self._address, 0x06 + (channel * 4), bytearray([0x00, 0x00, _off_count[1], _off_count[0]]))

    def write_angle(self, channel: int, angle: float, min_max_movement: tuple[float, float]=(3.1, 15)) -> None:
        """
        Writes the angle to a channel.
        :param channel: Channel to write the angle to
        :param angle: Angle in degrees
        :param min_max_movement: The duty cycles of position 0 and 180. Differ from min_max_range, which is the range of the servo.
        """
        if channel not in range(16):
            raise InvalidValue(f"Channel {channel} is not a valid channel!")
        if min_max_movement[0] < self._min_max_range[0]:
            raise InvalidValue(f"Min movement {min_max_movement[0]} is less than min range {self._min_max_range[0]}!")
        if min_max_movement[1] > self._min_max_range[1]:
            raise InvalidValue(f"Max movement {min_max_movement[1]} is greater than max range {self._min_max_range[1]}!")

        _duty_cycle = ((angle / 180) * (min_max_movement[1] - min_max_movement[0])) + min_max_movement[0]
        self.write_duty_cycle(channel, _duty_cycle)

    def oe_pin_enable(self, value: bool | str) -> None:
        """
        Globally disables output
        :param value: boolean to disable output GLOBALLY
        """
        if self._oe_pin is None:
            raise InvalidSetup("No OE pin is set!")

        if value == True or value == "HIGH":
            self._oe_pin.write_pin(False)
        else:
            self._oe_pin.write_pin(True)


class Servo:
    def __init__(self, device: PCA9685, channel: int, min_max_range: tuple[float, float] = (2.625, 15.875),
                 min_max_movement: tuple[float, float] = (3.1, 15)) -> None:
        """
        :param device: PCA9685 object
        :param channel: Channel to write the servo to
        :param min_max_range: Max and min duty cycle range of the servo.
        :param min_max_movement: The duty cycles of position 0 and 180.
        """
        device.claim_channel(channel)

        self._device = device
        self._channel = channel
        self._min_max_range = min_max_range
        self._min_max_movement = min_max_movement

    def servo_write_angle(self, angle: float):
        """
        Writes the angle to the servo
        :param angle: Angle in degrees
        """
        self._device.write_angle(self._channel, angle, self._min_max_movement)

    def global_enable_output(self, enable: bool | str = True) -> None:
        """
        Globally disables output
        :param enable: boolean to disable output GLOBALLY
        """
        if enable == True or enable == "HIGH":
            self._device.oe_pin_enable(True)
        else:
            self._device.oe_pin_enable(False)


class KorrySwitch:
    def __init__(self, input_switch: Switch, led1: LED, led2: LED,
                 condition1: Callable[[any], bool],
                 condition2: Callable[[any], bool]) -> None:
        """
        :param input_switch: Switch object
        :param led1: LED object 1 (top LED)
        :param led2: LED object 2 (bottom LED)
        :param condition1: Condition 1 for top LED
        :param condition2: Condition 2 for bottom LED
        """
        self._input_switch = input_switch
        self._led1 = led1
        self._led2 = led2
        self._condition1 = condition1
        self._condition2 = condition2

    @property
    def get_switch_state(self) -> bool:
        """
        Outputs the state of the switch
        :return: boolean of the switch state
        """
        return self._input_switch.get_state()

    def update(self, context: dict[str, Switch | LED]) -> None:
        """
        Updates the LEDs based on the set conditions
        :param context: Context object containing all objects
        """
        if self._condition1(context):
            self._led1.write_led(True)
        else:
            self._led1.write_led(False)

        if self._condition2(context):
            self._led2.write_led(True)
        else:
            self._led2.write_led(False)


class ACRemote:
    """
    Timings for the AC protocol
    """
    WAKEUP_BIT1 = (9000, 1)
    WAKEUP_BIT2 = (4500, 0)
    BIT_MARK = (600, 1)
    BIT_1 = (1600, 0)
    BIT_0 = (540, 0)
    MSG_SPACE = (20000, 0)

    class ACMode(IntEnum):
        AUTO = 0
        COOL = 1
        DRY = 2
        FAN = 3
        HEAT = 4

    class ACFanSpeed(IntEnum):
        AUTO = 0
        LOW = 1
        MEDIUM = 2
        HIGH = 3

    class ACSwing(IntEnum):
        OFF = 0
        FULL = 1
        HIGH = 2
        MIDDLE_HIGH = 3
        MIDDLE = 4
        MIDDLE_LOW = 5
        LOW = 6
        SWING_LOW = 7
        SWING_MIDDLE = 8
        SWING_HIGH = 9

    class ACTemperatureReading(IntEnum):
        OFF = 0
        INDOOR_SET = 1
        INDOOR_AMBIENT = 2
        OUTDOOR_AMBIENT = 3

    def __init__(self, device: RaspPiPico2W, pin: int = 0) -> None:
        """
        :param device: RaspPiPico2W device
        :param pin: Pin used for the LED
        """
        self._enabled = False
        self._mode = self.ACMode.AUTO
        self._fan_speed = self.ACFanSpeed.AUTO
        self._view_temp = self.ACTemperatureReading.OFF
        self._swing_mode = self.ACSwing.OFF
        self._target_temp = 25
        self._sleep = False
        self._turbo = False
        self._light = False
        self._x_fan = False
        self._timer_enabled = False
        self._timer_hour = 0

        self._device = device
        self._pin = pin
        self._led = GPIOPWM(self._device, self._pin, freq = 38000)


    # region properties and setters
    """
    All parameters that can be set are listed here.  
    """
    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool | str):
        if value == True or value == "HIGH":
            self._enabled = True
        else:
            self._enabled = False

    @property
    def mode(self) -> ACMode:
        return self._mode

    @mode.setter
    def mode(self, value: ACMode) -> None:
        if value == self.ACMode.AUTO:
            self._target_temp = 25
            self._sleep = False
        if value == self.ACMode.FAN:
            self.ACFanSpeed = self.ACFanSpeed.LOW
            self._sleep = False
        if value == self.ACMode.COOL:
            self._turbo = False
            self._x_fan = False
        if value == self.ACMode.HEAT:
            self._turbo = False
        if value == self.ACMode.DRY:
            self._x_fan = False

        self._mode = value

    @property
    def fan_speed(self) -> ACFanSpeed:
        return self._fan_speed

    @fan_speed.setter
    def fan_speed(self, value: ACFanSpeed) -> None:
        if value == self.ACMode.FAN:
            raise InvalidValue("Fan speed cannot be changed when in FAN mode!")

        self._fan_speed = value

    @property
    def view_temp(self) -> ACTemperatureReading:
        return self._view_temp

    @view_temp.setter
    def view_temp(self, value: ACTemperatureReading) -> None:
        self._view_temp = value

    @property
    def swing_mode(self) -> ACSwing:
        return self._swing_mode

    @swing_mode.setter
    def swing_mode(self, value: ACSwing) -> None:
        self._swing_mode = value

    """
    Target temp is value - 16, remove 5th bit
    """
    @property
    def target_temp(self) -> int:
        return self._target_temp

    @target_temp.setter
    def target_temp(self, value: int) -> None:
        if 30 < value < 16:
            raise InvalidValue(f"Target temperature must be between 30 and 16 degrees!")
        if value == self.ACMode.AUTO:
            raise InvalidValue(f"Target temperature cannot be set when in AUTO mode!")

        self._target_temp = value - 16

    @property
    def sleep(self) -> bool:
        return self._sleep

    @sleep.setter
    def sleep(self, value: bool | str):
        if value not in (self.ACMode.COOL, self.ACMode.DRY, self.ACMode.HEAT):
            raise InvalidSetup("Sleep is not available in AUTO or FAN modes!")
        if value == True or value == "HIGH":
            self._sleep = True
        else:
            self._sleep = False

    @property
    def turbo(self) -> bool:
        return self._turbo

    @turbo.setter
    def turbo(self, value: bool | str):
        if value not in (self.ACMode.COOL, self.ACMode.HEAT):
            raise InvalidSetup("Turbo is not available in DRY, FAN, or AUTO mode!")
        if value == True or value == "HIGH":
            self._turbo = True
        else:
            self._turbo = False

    @property
    def light(self) -> bool:
        return self._light

    @light.setter
    def light(self, value: bool | str):
        if value == True or value == "HIGH":
            self._light = True
        else:
            self._light = False

    @property
    def x_fan(self) -> bool:
        return self._x_fan

    @x_fan.setter
    def x_fan(self, value: bool | str):
        if value == True or value == "HIGH":
            self._x_fan = True
        else:
            self._x_fan = False

    @property
    def timer_enabled(self) -> bool:
        return self._timer_enabled

    @timer_enabled.setter
    def timer_enabled(self, value: bool | str):
        if value == True or value == "HIGH":
            self._timer_enabled = True
        else:
            self._timer_enabled = False
            self._timer_hour = 0

    @property
    def timer_hour(self) -> int:
        return self._timer_hour

    @timer_hour.setter
    def timer_hour(self, value: float) -> None:
        if 0.5 > value > 24:
            raise InvalidValue(f"Timer hour must be between 0.5 and 24!")
        if value % 0.5 != 0:
            raise InvalidValue(f"Timer hour must be a multiple of 0.5!")
        if not self._timer_enabled:
            raise InvalidSetup("Timer must be enabled to set the timer hour!")

        self._timer_hour = value

    # endregion

     #region helper functions

    @staticmethod
    def _get_timer_bits_packet_13(hours: float) -> tuple[str, str]:
        """
        Gets the timer bits for packet 1 and 3
        :param hours: Hours to set the timer to
        :return: Returns the timer bits for packet 1 and 3
        """
        remaining_hours = hours * 2

        weights = [
            (40, "add20"),
            (20, "add10"),
            (16, "add8"),
            (8, "add4"),
            (4, "add2"),
            (2, "add1"),
            (1, "add_half")
        ]

        bits = {}
        for weight, name in weights:
            if remaining_hours >= weight:
                bits[name] = "1"
                remaining_hours -= weight
            else:
                bits[name] = "0"

        return f"{bits['add_half']}{bits['add10']}{bits['add20']}", f"{bits['add1']}{bits['add2']}{bits['add4']}{bits['add8']}"

    @staticmethod
    def _get_timer_bits_packet_4(hours: float) -> str:
        """
        Gets the timer bits for packet 4
        :param hours: Hours to set the timer to
        :return: Returns the timer bits for packet 4
        """
        if 0.5 > hours > 24:
            raise InvalidValue(f"Timer hour must be between 0.5 and 24!")
        if hours % 0.5 != 0:
            raise InvalidValue(f"Timer hour must be a multiple of 0.5!")

        hours_2x = int(hours * 2)

        nibble_2_offset = (hours_2x - 1) // 16

        nibble_1 = "".join(reversed(f"{16 - (hours_2x % 16):04b}"))[0:4]
        nibble_2 = "".join(reversed(f"{((hours_2x - 1 - nibble_2_offset) % 16):04b}"))
        bit9 = "1" if 18 <= hours_2x <= 34 else "0"
        bit10 = "1" if 35 <= hours_2x <= 48 else "0"

        timer_bit = nibble_1 + nibble_2 + bit9 + bit10

        return timer_bit

    @staticmethod
    def _calculate_checksum_1(packet1: str) -> str:
        """
        Calculates the checksum for packet 2
        :param packet1: Packet 1 input
        :return: Returns the checksum for packet 2
        """
        nibbles = [packet1[0:4], packet1[8:12], packet1[16:20]]
        summed = sum(int("".join(reversed(nibble)), 2) for nibble in nibbles)
        modded = (summed + 6) % 16
        modded = f"{modded:04b}"
        modded = "".join(reversed(modded))
        return modded


    @staticmethod
    def _calculate_checksum_2(packet3: str, half_packet4: str) -> str:
        """
        Calculates the checksum for packet 4
        :param packet3: Packet 3 input
        :param half_packet4: Half of packet 4 input (without the last four bits, the checksum)
        :return: Returns the checksum for packet 4
        """
        nibbles = [packet3[0:4], packet3[8:12], packet3[16:20], half_packet4[4:8], half_packet4[12:16],
                   half_packet4[20:24]]
        summed = sum(int("".join(reversed(nibble)), 2) for nibble in nibbles)
        modded = (summed + 10) % 16
        modded = f"{modded:04b}"
        modded = "".join(reversed(modded))
        return modded

    # endregion

    def _calculate_bits(self) -> str:
        """
        Calculates the bits to send to the AC remote using the set parameters of the object
        :return: str of bits
        """
        _packet1 = (
            "".join(reversed(f"{self._mode:03b}")),
            "1" if self._enabled else "0",
            "".join(reversed(f"{self._fan_speed:02b}")),
            "1" if self._swing_mode in [self.ACSwing.FULL, self.ACSwing.SWING_LOW, self.ACSwing.SWING_MIDDLE,
                                        self.ACSwing.SWING_HIGH] else "0",
            "1" if self._sleep else "0",
            "".join(reversed(f"{self._target_temp:04b}")),
            f"{self._get_timer_bits_packet_13(self._timer_hour)[0]}",
            "1" if self.timer_enabled else "0",
            f"{self._get_timer_bits_packet_13(self._timer_hour)[1]}",
            "1" if self._turbo else "0",
            "1" if self._light else "0",
            "1" if self._enabled or self._timer_enabled else "0",
            "1" if self._x_fan else "0",
            "00001010010"
        )
        _packet1 = "".join(_packet1)

        _packet2 = (
            "".join(reversed(f"{self._swing_mode:04b}")),
            "0000",
            "".join(reversed(f"{self._view_temp:02b}")),
            "000011000000000000",
            f"{self._calculate_checksum_1(_packet1)}"
        )
        _packet2 = "".join(_packet2)

        _packet3 = (
            "".join(reversed(f"{self._mode:03b}")),
            "1" if self._enabled else "0",
            "".join(reversed(f"{self._fan_speed:02b}")),
            "1" if self._swing_mode in [self.ACSwing.FULL, self.ACSwing.SWING_LOW, self.ACSwing.SWING_MIDDLE,
                                        self.ACSwing.SWING_HIGH] else "0",
            "1" if self._sleep else "0",
            "".join(reversed(f"{self._target_temp:04b}")),
            f"{self._get_timer_bits_packet_13(self._timer_hour)[0]}"
            "1" if self.timer_enabled else "0",
            f"{self._get_timer_bits_packet_13(self._timer_hour)[1]}",
            "1" if self._turbo else "0",
            "1" if self._light  else "0",
            "1",
            "1" if self._x_fan else "0",
            "000001",
            "1" if self._timer_enabled else "0",
            "1" if not self._timer_enabled else "0",
            "010"
        )
        _packet3 = "".join(_packet3)

        _half_packet4 = (
            "0",
            f"{self._get_timer_bits_packet_4(self._timer_hour)}" if not self._enabled and self._timer_enabled else "0000000000",
            "00",
            f"{self._get_timer_bits_packet_4(self._timer_hour)}" if self._enabled and self._timer_enabled else "0000000000",
            "0",
            "1" if self._enabled and self._timer_enabled else "0",
            "1" if not self._enabled and self._timer_enabled else "0",
            "00",
        )
        _checksum2 = self._calculate_checksum_2(_packet3, "".join(_half_packet4))
        _packet4 = "".join(_half_packet4) + _checksum2

        if self._timer_enabled:
            return f"{_packet1} {_packet2}-{_packet3} {_packet4}"
        else:
            _packet3 = "00000000000000000000000000000101010"
            _packet4 = "00000000000000000000000000000101"
            return f"{_packet1} {_packet2}-{_packet3} {_packet4}"

    def _get_timings(self) -> list[tuple[int, int]]:
        """
        Calculates the timings from the objects parameters
        """
        _data = self._calculate_bits()
        _data = _data.split("-")

        _timings = []

        for d in _data:
            _timings.append(self.WAKEUP_BIT1)
            _timings.append(self.WAKEUP_BIT2)

            for bit in d:
                if bit == "1":
                    _timings.append(self.BIT_MARK)
                    _timings.append(self.BIT_1)
                if bit == "0":
                    _timings.append(self.BIT_MARK)
                    _timings.append(self.BIT_0)
                if bit == " ":
                    _timings.append(self.BIT_MARK)
                    _timings.append(self.MSG_SPACE)

            _timings.append(self.BIT_MARK)
            _timings.append((40000, 0))

        for _ in range(2): del _timings[-1]

        _timings.append(self.BIT_MARK)
        _timings.append(self.BIT_0)

        return _timings

    def send_data(self) -> None:
        for timing, state in self._get_timings():
            self._led.set_duty_percentage(state * 50)
            time.sleep_us(timing)

        self._led.set_duty_percentage(0)


#! Helper Functions, delete after done testing
def execution_time(f):
    def wrapper(*args, **kwargs):
        start = time.ticks_us()
        data = f(*args, **kwargs)
        end = time.ticks_us()
        diff = time.ticks_diff(end, start)
        print(f"Execution time: {diff} microseconds")

        return data
    return wrapper