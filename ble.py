import asyncio
from bleak import BleakClient, BleakScanner

DEVICE_NAME = "STEPPA"

# RN4871 UART service characteristics seen in your scan
UART_TX_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"  # board -> Mac (notify)
UART_RX_UUID = "49535343-8841-43f4-a8d4-ecbe34729bb3"  # Mac -> board (write, optional)

buffer = ""

def parse_steppa_line(line: str):
    line = line.strip()
    if not line:
        return None

    out = {}
    parts = line.split(",")

    current_sensor = None
    for part in parts:
        part = part.strip()
        if ":" in part:
            key, value = part.split(":", 1)
            key = key.strip()
            value = value.strip()

            if key in ("AX", "AY", "AZ"):
                try:
                    out[key] = int(value)
                except ValueError:
                    out[key] = value
                current_sensor = None
            elif key.startswith("S"):
                current_sensor = key
                out[current_sensor] = []
                try:
                    out[current_sensor].append(int(value))
                except ValueError:
                    out[current_sensor].append(value)
        else:
            if current_sensor is not None and part:
                try:
                    out[current_sensor].append(int(part))
                except ValueError:
                    out[current_sensor].append(part)

    return out

def handle_notify(sender, data: bytearray):
    global buffer
    text = data.decode("utf-8", errors="replace")
    buffer += text

    while "\n" in buffer:
        line, buffer = buffer.split("\n", 1)
        line = line.strip()
        if line:
            print("RAW:", line)
            parsed = parse_steppa_line(line)
            print("PARSED:", parsed)

async def find_device(device_name):
    devices = await BleakScanner.discover(timeout=5.0)
    for device in devices:
        if device.name == device_name:
            return device
    return None

async def main():
    device = await find_device(DEVICE_NAME)

    if not device:
        print(f"Device '{DEVICE_NAME}' not found")
        return

    print(f"Found device: {device.name} ({device.address})")

    async with BleakClient(device.address) as client:
        print(f"Connected to {DEVICE_NAME}")

        services = client.services
        print("\nServices discovered:")
        for service in services:
            print(f"Service: {service.uuid}")
            for char in service.characteristics:
                print(f"  Characteristic: {char.uuid} props={char.properties}")

        print(f"\nSubscribing to notifications on {UART_TX_UUID} ...")
        await client.start_notify(UART_TX_UUID, handle_notify)

        print("Listening for live board data. Press Ctrl+C to stop.")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\nStopped by user")
        finally:
            await client.stop_notify(UART_TX_UUID)

if __name__ == "__main__":
    asyncio.run(main())
