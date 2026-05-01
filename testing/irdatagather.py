from machine import Pin
import time

ir_pin = Pin(0, Pin.IN, Pin.PULL_UP)

prev_pin_value = ir_pin.value()
prev_time = time.ticks_us()
prev_data = []

data = []
temp = []

def process_data(data):
    data = data[1:]

    packets = []
    temp = []

    bits = []

    for timing in data:
        if timing[0] > 35000:
            packets.append(temp)
            packets.append([("break", timing[0])])
            temp = []
        else:
            temp.append(timing)

    packets.append(temp)
    temp = []

    for packet in packets:
        packet_mod = packet[2:]
        for data in packet_mod:
            if data[1] == 0:
                if data[0] > 10000:
                    temp.append("20000ms low")
                elif data[0] > 1000:
                    temp.append(1)
                elif data[0] < 1000:
                    temp.append(0)

        if temp: bits.append(temp)
        temp = []

    bit_str = []

    for bit in bits:
        temp_str = ''.join(str(b) for b in bit)
        temp = temp_str.split('20000ms low')

        bit_str.append(temp)

    return bit_str


while True:
    now_state = ir_pin.value()
    now = time.ticks_us()
    ticks_diff = time.ticks_diff(now, prev_time)

    if now_state != prev_pin_value:
        temp.append((ticks_diff, now_state))
        # print(f"{time.ticks_diff(now, prev_time)} : {now_state}")
        pin_value = ir_pin.value()
        prev_time = now
        prev_pin_value = pin_value

    if ticks_diff > 100000 and temp and len(temp) > 2:
        data.append(temp)
        print(temp)
        processed_data = process_data(temp)
        # print(processed_data)
        try:
            processed_str = f"{processed_data[0][0]} {processed_data[0][1]} {processed_data[1][0]} {processed_data[1][1]}"
            print(processed_str)
        except:
            print("fail")

        temp = []


