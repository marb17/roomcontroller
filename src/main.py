import time
from machine import Pin, WDT, PWM
import gc


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
    from machine import I2C, Pin

    VALID_PINS = set(range(29))

    I2C_VALID_PINS = {
        0: {"sda": {0, 4, 8, 12, 16, 20}, "scl": {1, 5, 9, 13, 17, 21}},
        1: {"sda": {2, 6, 10, 14, 18, 26}, "scl": {3, 7, 11, 15, 19, 27}}
    }

    def __init__(self) -> None:
        self._claimed_pin = set()

    def claim_pin(self, pin: int) -> None:
        if pin in self._claimed_pin:
            raise ValueError(f"Pin {pin} already claimed!")
        self._claimed_pin.add(pin)

    def validate_i2c_pin(self, port: int, sda: int, scl: int) -> bool:
        if port not in self.I2C_VALID_PINS:
            raise ValueError("Invalid I2C Bus ID (Must be 0 or 1).")

        valid_sda = self.I2C_VALID_PINS[port]["sda"]
        valid_scl = self.I2C_VALID_PINS[port]["scl"]

        if sda not in valid_sda or scl not in valid_scl:
            raise ValueError(f"Invalid SDA ({sda}) or SCL ({scl}) for I2C bus {port}")
        return True


class GPIOPin:
    from machine import Pin

    VALID_MODES = [Pin.IN, Pin.OUT, Pin.OPEN_DRAIN, Pin.ALT]
    VALID_PULL = [None, Pin.PULL_UP, Pin.PULL_DOWN]
    VALID_VALUE = [True, False, None]

    def __init__(self, device: RaspPiPico2W, pin: int, mode: Pin = Pin.IN, pull: Pin = Pin.PULL_UP, value: bool | None = None) -> None:
        from machine import Pin

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
        return bool(self.pin.value())

    def set_pin(self, state: bool | int | str) -> None:
        if state == True or state == "HIGH" or state == 1:
            self.pin.on()
        else:
            self.pin.off()

    def pin_toggle(self) -> None:
        self.pin.toggle()


class I2CBus:
    def __init__(self, device: RaspPiPico2W, port, sda=0, scl=1, freq=100000, stop_on_error=False) -> None:
        from machine import I2C, Pin

        if not device.validate_i2c_pin(port, sda, scl):
            raise InvalidPin(f"Port {port} doesn't match SDA {sda} / SCL {scl} or SDA {sda} / SCL {scl} isn't valid!")

        self.device = device

        self.i2c = I2C(port, sda=Pin(sda), scl=Pin(scl), freq=freq)
        self._claimed_addresses = set()

        for pin in [sda, scl]:
            device.claim_pin(pin)

        self._stop_on_error = stop_on_error
        self._readfrom_cache = None

    def __str__(self) -> list[str]:
        return self.scan(print_output=False)

    def claim_address(self, address: int) -> None:
        if address in self._claimed_addresses:
            raise ValueError(f"Address {address} already claimed!")
        self._claimed_addresses.add(address)

    def scan(self, print_output=True) -> list[str]:
        """
        Scans all available addresses in I2C Bus
        :return: List of available addresses
        """
        _available_addresses = []
        for item in self.i2c.scan():
            _available_addresses.append(hex(item))

        if print_output:
            print(f"Available Devices: {_available_addresses}")

        return _available_addresses

    def readfrom(self, addr, nbytes) -> bytes:
        try:
            _data = self.i2c.readfrom(addr, nbytes)
            self._readfrom_cache = _data
            return _data
        except Exception as e:
            if self._stop_on_error or self._readfrom_cache is None:
                if self._readfrom_cache is None:
                    print("Nothing in cache")
                    print(f"I2C Read Error: {e}, Address: {addr}, NBytes: {nbytes}")
                raise e
            else:
                print(f"I2C Read Error: {e}, Address: {addr}, NBytes: {nbytes}")
                return self._readfrom_cache

    def writeto(self, addr, buf) -> None:
        try:
            self.i2c.writeto(addr, buf)
        except Exception as e:
            if self._stop_on_error:
                raise e
            else:
                print(f"I2C Write Error: {e}, Address: {addr}, Buffer: {buf}")

    def writeto_mem(self, addr, memaddr, buf) -> None:
        try:
            self.i2c.writeto_mem(addr, memaddr, buf)
        except Exception as e:
            if self._stop_on_error:
                raise e
            print(f"I2C Mem-Write Error: {e}, Address: {addr}, Memory Address: {memaddr}, Buffer: {buf}")


class PCF8575:
    def __init__(self, i2c_bus: I2CBus, address: int = 0x20, cache_lifetime=50) -> None:
        """
        Defaults all pins as INPUT / HIGH
        :param cache_lifetime: If -1, cache is disabled and will always recall data. When set above 1, cache is enabled and will only recall data if the last read was more than cache_lifetime milliseconds ago.
        """
        i2c_bus.claim_address(address)

        self._claimed_pins = set()

        self._bus = i2c_bus
        self._address = address
        self._valid_pins = [0, 1, 2, 3, 4, 5, 6, 7,
                            10, 11, 12, 13, 14, 15, 16, 17]
        self._pin_mode = bytearray([0xFF, 0xFF])

        self.write_all(bytearray([0xFF, 0xFF]))

        self._cache_lifetime = cache_lifetime
        self._cache = None
        self._last_called = time.ticks_ms()

    def claim_pin(self, pin: int) -> None:
        if pin in self._claimed_pins:
            raise ValueError(f"Pin {pin} already claimed!")
        self._claimed_pins.add(pin)

    def current_pin_state(self) -> bytearray:
        return self._pin_mode

    def read_all(self, force=False) -> bytes:
        if self._cache_lifetime == -1:
            return self._bus.readfrom(self._address, 2)
        else:
            now = time.ticks_ms()
            if time.ticks_diff(now, self._last_called) > self._cache_lifetime or force or self._cache is None:
                self._cache = self._bus.readfrom(self._address, 2)
                self._last_called = now

            return self._cache

    def read_pin(self, pin: int) -> bool:
        """
        :param pin: Uses board pin out (P07-P00 P17-P10)
        :return: True if GND, False if VCC
        """
        if pin not in self._valid_pins:
            raise InvalidPin("Pin is not present in PCF8575")

        _data = self.read_all()
        return not bool((_data[pin // 10] >> (pin % 10)) & 1)

    def read_pins(self, pins: list[int]) -> list[bool]:
        """
        :param pins: Uses board pin out (P07-P00 P17-P10), allows multiple pins to be read at once
        :return: List of True if GND, False if VCC
        """
        _data = self.read_all()
        return [not bool((_data[pin // 10] >> (pin % 10)) & 1) for pin in pins]

    def write_all(self, data: bytearray) -> None:
        """
        :param data: Inputs two bytes to be written, 1 = HIGH : 0 = LOW
        """
        self._pin_mode = data
        self._bus.writeto(self._address, self._pin_mode)

    def _edit_bit(self, value: str | bool, pin: int) -> None:
        if value == "HIGH" or value == True:
            self._pin_mode[0 if (pin // 10) == 0 else 1] |= (1 << (pin % 10))
        else:
            self._pin_mode[0 if (pin // 10) == 0 else 1] &= ~(1 << (pin % 10))

    def write_pin(self, pin: int, value: str | bool) -> None:
        """
        :param pin: Uses board pin out (P07-P00 P17-P10)
        :param value: str of "HIGH" or "LOW" to set pin mode
        """
        if pin not in self._valid_pins:
            raise InvalidPin("Pin is not present in PCF8575")
        if value not in ["HIGH", "LOW", True, False]:
            raise InvalidPin("Set state is not a valid state")

        self._edit_bit(value, pin)

        self.write_all(self._pin_mode)

    def update_pin(self, pin: int, value: bool | str) -> None:
        self._edit_bit(value, pin)

class PCF8575Multiplex(PCF8575):
    def __init__(self, i2c_bus: I2CBus, rows: list[int], column: list[int], address: int = 0x20) -> None:
        super().__init__(i2c_bus, address)

        self._claimed_xy = set()

        self._rows = rows
        self._column = column

        for r in self._rows:
            self.claim_pin(r)
        for c in self._column:
            self.claim_pin(c)

        self.reset_pins()

        self._col_index_map = {c: i for i, c in enumerate(self._column)}

    def claim_xy(self, xy: tuple[int, int]) -> None:
        if xy in self._claimed_xy:
            raise ValueError(f"XY {xy} already claimed!")
        self._claimed_xy.add(xy)

    def reset_pins(self) -> None:
        for r in self._rows:
            self.write_pin(r, "HIGH")
        for c in self._column:
            self.write_pin(c, "HIGH")

    def read_grid(self, safe=False) -> list[bool]:
        """
        :param safe: Always resets pins to HIGH, EXTREMELY SLOW
        :return: A nested list [x][y]; x being the row and y being the column in respect with the list given during initialization
        """
        _data = []

        if safe:
            self.reset_pins()

        for x in self._rows:
            self.write_pin(x, "LOW")
            _temporary = self.read_pins(self._column)
            self.write_pin(x, "HIGH")
            _data.append(_temporary)

        return _data

    def read_pin_from_grid(self, row, column, safe=False) -> bool:
        """
        Single position check, much faster than a whole grid check.
        :param safe: Always resets pins to HIGH, EXTREMELY SLOW
        :return: True if grid is HIGH, False if grid is LOW
        """
        if row not in self._rows or column not in self._column:
            raise InvalidPin("Pin is not present in multiplex, please recheck row and column arguments")

        if safe:
            self.reset_pins()

        self.write_pin(row, "LOW")
        _state = self.read_pin(column)
        self.write_pin(row, "HIGH")

        return _state

    def read_pins_from_grid(self, xy_list: list[tuple[int, int]], safe=False):
        """
        Checks multiples grid positions and optimized for speed by caching the same row's result. Best way to check multiple positions. Fastest way and should be always be used if possible.
        :param xy_list: List of tuples (row, column)
        :param safe: Always resets pins to HIGH, EXTREMELY SLOW
        :return: List of True if grid is HIGH, False if grid is LOW
        """
        for xy in xy_list:
            if xy[0] not in self._rows or xy[1] not in self._column:
                raise InvalidPin("Pin is not present in multiplex, please recheck row and column arguments")

        _data = []

        if safe:
            self.reset_pins()

        _previous_row = -1
        _data_cache = []

        for xy in xy_list:
            if _previous_row != xy[0]:
                if _previous_row != -1:
                    self.update_pin(_previous_row, "HIGH")
                self.write_pin(xy[0], "LOW")
                _previous_row = xy[0]

                _data_cache = self.read_pins(self._column)

            _data.append(_data_cache[self._col_index_map[xy[1]]])

        if _previous_row != -1:
            self.write_pin(_previous_row, "HIGH")

        return _data


class HC595:
    def __init__(self, device: RaspPiPico2W, serin: int = 0, rclk: int = 1, srclk: int = 2) -> None:
        self._serin = GPIOPin(device, serin, Pin.OUT, None)
        self._rclk = GPIOPin(device, rclk, Pin.OUT, None)
        self._srclk = GPIOPin(device, srclk, Pin.OUT, None)

        self._shift_data = bytearray([0x00])

        self._claimed_pins = set()

    def claim_pin(self, pin: int) -> None:
        if pin in self._claimed_pins:
            raise InvalidPin(f"Pin {pin} already claimed")
        self._claimed_pins.add(pin)

    def write_data(self, data: bytearray = bytearray([0x00])) -> None:
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
        """
        if value == True or value == "HIGH":
            self._shift_data[pin // 8] |= 1 << (7 - (pin % 8))
        else:
            self._shift_data[pin // 8] &= ~(1 << (7 - (pin % 8)))

    def write_pin(self, pin: int, value: bool | str) -> None:
        """
        Writes a pin and updates the display
        """
        self.update_data(pin, value)
        self.write_data(self._shift_data)


class OutputPin:
    def __init__(self, write_method) -> None:
        self._write_method = write_method

    @classmethod
    def from_gpio(cls, pin: int, device: RaspPiPico2W, invert: bool = False):
        gpio_obj = GPIOPin(device, pin, Pin.OUT, None)

        def write_method(value: bool | str, invert: bool = False):
            if value == True or value == "HIGH":
                gpio_obj.set_pin(True if not invert else False)
            else:
                gpio_obj.set_pin(False if not invert else True)

        return cls(write_method)

    @classmethod
    def from_pcf8575(cls, device: PCF8575, pin: int,  invert: bool = False):
        device.claim_pin(pin)

        def write_method(value: bool | str):
            if value == True or value == "HIGH":
                device.write_pin(pin, True if not invert else False)
            else:
                device.write_pin(pin, False if not invert else True)

        return cls(write_method)

    def write_pin(self, value: bool | str) -> None:
        self._write_method(value)


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
              9 : [1, 1, 1, 1, 0, 0, 1]}

    def __init__(self, device: HC595, pins: list[int] ) -> None:
        if len(pins) != 7:
            raise InvalidSetup(f"There are {len(pins)}!")
        if len(pins) != len(set(pins)):
            raise InvalidSetup(f"Pin are not unique!")

        self._device = device
        self._pins = pins

        for pin in self._pins:
            device.claim_pin(pin)

    def write_to_display(self, char: int) -> None:
        if char not in self.CHAR_SET.keys():
            raise InvalidValue("Set character is not a valid character!")

        _set_pins = self.CHAR_SET[char]

        for pin, bit in zip(self._pins, _set_pins):
            self._device.update_data(pin, bool(bit))

        self._device.write_data()


class RotarySwitch:
    def __init__(self, switch_objects: list, device: PCF8575 | PCF8575Multiplex, pins: list[tuple[int, int]] | list[int], mode: str) -> None:
        self._switch_objects = switch_objects
        self._mode = mode
        self._pins = pins
        self._device = device

    @classmethod
    def from_pin(cls, pcf_device: PCF8575, pins: list[int]):
        switches = [Switch.from_pin(pcf_device, pin) for pin in pins]

        return cls(switches, pcf_device, pins, mode="pin")

    @classmethod
    def from_matrix(cls, multiplex_device: PCF8575Multiplex, xy: list[tuple[int, int]]):
        switches = [Switch.from_matrix(multiplex_device, item) for item in xy]

        return cls(switches, multiplex_device, xy, mode="matrix")

    def _read_states(self) -> list[bool]:
        if self._mode == "pin":
            data = self._device.read_all()
            return [not bool((data[pin // 10] >> (pin % 10)) & 1) for pin in self._pins]
        if self._mode == "matrix":
            return self._device.read_pins_from_grid(self._pins)
        return None

    def get_state(self, safe=False) -> int | None:
        """
        :return: Returns the position of the rotary switch, None if the signal is not stable
        """
        _states = self._read_states()

        if safe:
            if _states.count(True) > 1:
                return None
            else:
                try:
                    return _states.index(True)
                except ValueError:
                    return None
        else:
            try:
                return _states.index(True)
            except ValueError:
                return None

    def get_pos_state(self, pos) -> bool:
        """
        :return: Returns if a specific position is True, the same speed as get_state()
        """
        _data = self._read_states()
        return _data[pos]

    @property
    def position(self) -> int | None:
        return self.get_state()


class Switch:
    def __init__(self, read_func, debounce_ms=20) -> None:
        self._debounce_ms = debounce_ms
        self._current_stable_state = False
        self._last_state_reading = False
        self._last_time_changed = time.ticks_ms()

        self._read_method = read_func

    @classmethod
    def from_pin(cls, pcf_device: PCF8575, pin_number: int, debounce=20):
        """
        Creates a switch using a normal pin
        """
        pcf_device.write_pin(pin_number, "HIGH")
        pcf_device.claim_pin(pin_number)

        read_func = lambda: pcf_device.read_pin(pin_number)

        return cls(read_func, debounce_ms=debounce)

    @classmethod
    def from_matrix(cls, multiplex_device: PCF8575Multiplex, xy: tuple[int, int], debounce=20):
        """
        Creates a switch using a multiplex grid
        """
        multiplex_device.claim_xy(xy)

        read_func = lambda: multiplex_device.read_pin_from_grid(xy[0], xy[1])

        return cls(read_func, debounce_ms=debounce)

    def get_state(self) -> bool:
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
    def is_pressed(self):
        return self.get_state()


class PCA9685:
    MODE1_ADDR = 0x00
    PRE_SCALE_ADDR = 0xFE

    def __init__(self, device: I2CBus, address: int = 0x40, min_max_range: tuple[float, float]=(2.625, 15.875), oe_pin: None | OutputPin=None) -> None:
        """
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
        if channel in self._claimed_channels:
            raise InvalidPin(f"Channel {channel} already claimed!")
        self._claimed_channels.add(channel)

    def _initialize_device(self) -> None:
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
        if channel not in range(16):
            raise InvalidValue(f"Channel {channel} is not a valid channel!")

        _off_count = round((duty_cycle / 100) * 4095)
        _off_count = _off_count.to_bytes(2, "big")

        print(f"{hex(_off_count[0])} {hex(_off_count[1])}")

        self._device.writeto_mem(self._address, 0x06 + (channel * 4), bytearray([0x00, 0x00, _off_count[1], _off_count[0]]))

    def write_angle(self, channel: int, angle: float, min_max_movement: tuple[float, float]=(3.1, 15)) -> None:
        """
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
        if self._oe_pin is None:
            raise InvalidSetup("No OE pin is set!")

        if value == True or value == "HIGH":
            self._oe_pin.write_pin(False)
        else:
            self._oe_pin.write_pin(True)


class Servo:
    def __init__(self, device: PCA9685, channel: int, min_max_range: tuple[float, float]=(2.625, 15.875), min_max_movement: tuple[float, float]=(3.1, 15)) -> None:
        device.claim_channel(channel)

        self._device = device
        self._channel = channel
        self._min_max_range = min_max_range
        self._min_max_movement = min_max_movement

    def servo_write_angle(self, angle: float):
        self._device.write_angle(self._channel, angle, self._min_max_movement)

    def enable_output(self, enable: bool | str = True) -> None:
        if enable == True or enable == "HIGH":
            self._device.oe_pin_enable(True)
        else:
            self._device.oe_pin_enable(False)


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


if __name__ == "__main__":
    # wdt = WDT(timeout=8000)
    rasppi = RaspPiPico2W()
    i2c_bus = I2CBus(rasppi, 0, sda=16, scl=17, freq=100000)
    pcf1 = PCF8575(i2c_bus, 0x23)
    switch = Switch.from_pin(pcf1, 0)

    outputpin = OutputPin.from_pcf8575(pcf1, 1)

    pca = PCA9685(i2c_bus, address=0x40, oe_pin=outputpin)
    servo = Servo(pca, 0)

    while True:
        # wdt.feed()
        # gc.collect()
        for i in range(2):
            servo.servo_write_angle(i * 180)

            if switch.is_pressed:
                servo.enable_output(False)
            else:
                servo.enable_output(True)