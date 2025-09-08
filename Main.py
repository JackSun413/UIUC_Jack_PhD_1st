# main.py

from LinMot import LinMotForceController
from Biologic import BioLogicInterface
import time
import sys
import threading

# ---- Configuration ----
LINMOT_DLL_PATH = r'C:\Users\Shijie Sun\Desktop\Linear Motor\LinUDP_V2_1_1_0_20210617\LinUDP_V2_DLL\LinUDP.dll'
LINMOT_TARGET_IP = "192.168.1.89"
LINMOT_HOST_IP = "192.168.1.100"

ECLIB_PATH = r"C:/EC-Lab Development Package/lib/EClib.dll"
BLFIND_PATH = r"C:/EC-Lab Development Package/lib/blfind.dll"
BIOLOGIC_ADDRESS = "USB0"  # Or actual IP if using Ethernet

CHANNEL = 1

def connect_devices():
    """Create controller instances and connect to hardware."""
    linmot = LinMotForceController(
        dll_path=LINMOT_DLL_PATH,
        target_ip=LINMOT_TARGET_IP,
        host_ip=LINMOT_HOST_IP,
    )
    bio = BioLogicInterface(
        eclib_dll_path=ECLIB_PATH,
        blfind_dll_path=BLFIND_PATH,
    )
    if not linmot.connect():
        print("Failed to connect to LinMot")
    else:
        linmot.homing_and_enable()
    if not bio.connect(BIOLOGIC_ADDRESS):
        print("Failed to connect to BioLogic")
    return linmot, bio

# ---- Experiment Parameters ----
peis_params = dict(amplitude=10e-3, freq_start=1e5, freq_end=1, points=50)
gcpl_params_1 = dict(current=0.01, duration=600, voltage_limit=4.3, record_interval=1)
gcpl_params_2 = dict(current=0.05, duration=300, voltage_limit=4.0, record_interval=1)  # This will be updated

# ---- Main Automation Flow ----
# Helper for dynamic parameter update
def some_condition(data):
    # Example: return True if charge < threshold, etc.
    return False


def automated_sequence(linmot, bio):
    """Run the predefined sequence of PEIS and GCPL steps."""
    try:
        available_channels = bio.get_plugged_channels()
        if CHANNEL not in available_channels:
            raise Exception(f"Channel {CHANNEL} not available on BioLogic")

        # Set initial force for stack (optional)
        linmot.set_force(50.0)
        time.sleep(2)

        sequence = [
            ("PEIS", peis_params),
            ("GCPL", gcpl_params_1),
            ("PEIS", peis_params),
            ("GCPL", gcpl_params_2),
        ]

        for i, (step, params) in enumerate(sequence):
            print(f"--- Step {i+1}: {step} ---")
            if step == "PEIS":
                # Example: bio.load_peis_technique(channel=CHANNEL, **params)
                pass  # Implement your PEIS loader if not already
            elif step == "GCPL":
                if i == 3:
                    last_gcpl_data = bio.get_data(CHANNEL)
                    if last_gcpl_data and some_condition(last_gcpl_data):
                        params['current'] = 0.08
                bio.load_cp_technique(CHANNEL, **params)
            bio.start_channel(CHANNEL)
            # Placeholder polling loop
            for _ in range(int(params.get('duration', 0))):
                time.sleep(1)
            print(f"Step {step} completed.")

        linmot.stop_force()
    except Exception as e:
        print(f"Error during sequence: {e}")


def run_gcpl(bio):
    """Prompt for GCPL parameters and run the technique."""
    current = float(input("GCPL current (A): "))
    duration = float(input("Duration (s): "))
    voltage_limit = float(input("Voltage limit (V): "))
    file_name = f"gcpl_{int(time.time())}.csv"
    params = dict(current=current, duration=duration,
                  voltage_limit=voltage_limit, record_interval=1)
    bio.load_cp_technique(CHANNEL, **params)
    bio.start_channel(CHANNEL)
    with open(file_name, "w") as f:
        f.write("time_s,voltage_V,current_A\n")
        start = time.time()
        while time.time() - start < duration:
            vals = bio.read_values(CHANNEL)
            f.write(f"{vals.ElapsedTime},{vals.Ewe},{vals.I}\n")
            if vals.Ewe >= voltage_limit:
                break
            time.sleep(1)
    bio.stop_channel(CHANNEL)
    print(f"GCPL finished. Data saved to {file_name}")


def run_peis(bio):
    amplitude = float(input("PEIS amplitude (V): "))
    freq_start = float(input("Start freq (Hz): "))
    freq_end = float(input("End freq (Hz): "))
    points = int(input("Points: "))
    params = dict(amplitude=amplitude, freq_start=freq_start,
                  freq_end=freq_end, points=points)
    print(f"Would run PEIS with {params}")


def constant_force_move(linmot):
    """Move with fixed force parameters."""
    pos = float(input("Position mm: "))
    vel = float(input("Max velocity (m/s): "))
    accel = float(input("Acceleration (m/s^2): "))
    force_lim = float(input("Force limit (N): "))
    target_force = float(input("Target force (N): "))
    linmot.move_with_force_limit_and_target(pos, vel, accel, force_lim, target_force)


def move_reset_force_ctrl(linmot):
    """Move to a position without force control."""
    pos = float(input("Position mm: "))
    vel = float(input("Velocity (m/s): "))
    accel = float(input("Acceleration (m/s^2): "))
    decel = float(input("Deceleration (m/s^2): "))
    linmot.ACI.LMfc_GoToPosRstForceCtrl(linmot.target_ip, pos, vel, accel, decel)


def dynamic_force_control(linmot, bio):
    """Example dynamic control adjusting force based on voltage."""
    current = float(input("CP current (A): "))
    duration = float(input("Duration (s): "))
    voltage_limit = float(input("Voltage limit (V): "))
    force = float(input("Initial force (N): "))

    params = dict(current=current, duration=duration,
                  record_interval=1, voltage_limit=voltage_limit)
    bio.load_cp_technique(CHANNEL, **params)
    bio.start_channel(CHANNEL)

    start = time.time()
    linmot.set_force(force)
    while time.time() - start < duration:
        voltage = bio.read_voltage(CHANNEL)
        position = linmot.ACI.getMonitoringChannelWithTimestamp(linmot.target_ip, 2).value
        # Simple demo logic: adjust force depending on voltage
        if voltage > voltage_limit * 0.9:
            force = max(0, force - 0.5)
        else:
            force = min(100, force + 0.5)
        linmot.set_force(force)
        print(f"V={voltage:.2f}V pos={position:.2f}mm -> force {force:.2f}N")
        time.sleep(1)

    bio.stop_channel(CHANNEL)
    linmot.stop_force()
    print("Dynamic force control finished")


def interactive_menu(linmot, bio):
    while True:
        print("\nChoose an action:")
        print("1 - Run GCPL")
        print("2 - Run PEIS")
        print("3 - LinMot constant force move")
        print("4 - LinMot dynamic force control")
        print("5 - Run automated sequence")
        print("0 - Quit")
        choice = input("Selection: ").strip()
        if choice == '1':
            run_gcpl(bio)
        elif choice == '2':
            run_peis(bio)
        elif choice == '3':
            constant_force_move(linmot)
        elif choice == '4':
            dynamic_force_control(linmot, bio)
        elif choice == '5':
            automated_sequence(linmot, bio)
        elif choice == '0':
            break
        else:
            print("Unknown selection")


def main():
    linmot, bio = connect_devices()
    try:
        automated_sequence(linmot, bio)
        interactive_menu(linmot, bio)
    finally:
        linmot.disconnect()
        bio.shutdown()

if __name__ == "__main__":
    main()


