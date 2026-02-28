import can, time

bus = can.interface.Bus(channel="can0", interface="socketcan")

print("Listening 10s... move throttle/switch during this.")
t_end = time.time() + 10
counts = {}

while time.time() < t_end:
    msg = bus.recv(timeout=1.0)
    if not msg or len(msg.data) < 2:
        continue
    if msg.arbitration_id not in (0x6E4, 0x6E5):
        continue

    d = bytes(msg.data)
    page = d[0]
    key = (msg.arbitration_id, page)
    counts[key] = counts.get(key, 0) + 1

    # print at low rate per page
    if counts[key] % 50 == 1:
        print(f"id={hex(msg.arbitration_id)} page=0x{page:02X} data={d.hex().upper()}")

print("Counts:", {f"{hex(k[0])}/0x{k[1]:02X}": v for k,v in counts.items()})
