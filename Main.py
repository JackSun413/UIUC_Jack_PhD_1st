# main.py

from LinMot import LinMotForceController
from Biologic import BioLogicInterface
import time

# ---- Configuration ----
LINMOT_DLL_PATH = r'C:\Users\12500\Downloads\LinUDP_V2_1_1_0_20210617\LinUDP\LinUDP.dll'
LINMOT_TARGET_IP = "192.168.1.89"
LINMOT_HOST_IP = "192.168.1.100"

ECLIB_PATH = r"C:/EC-Lab Development Package/lib/EClib.dll"
BLFIND_PATH = r"C:/EC-Lab Development Package/lib/blfind.dll"
BIOLOGIC_ADDRESS = "USB0"  # Or actual IP if using Ethernet

CHANNEL = 1

# ---- Initialize Controllers ----
linmot = LinMotForceController(
    dll_path=LINMOT_DLL_PATH,
    target_ip=LINMOT_TARGET_IP,
    host_ip=LINMOT_HOST_IP,
)

bio = BioLogicInterface(
    eclib_dll_path=ECLIB_PATH,
    blfind_dll_path=BLFIND_PATH
)

# ---- Experiment Parameters ----
peis_params = dict(amplitude=10e-3, freq_start=1e5, freq_end=1, points=50)
gcpl_params_1 = dict(current=0.01, duration=600, voltage_limit=4.3, record_interval=1)
gcpl_params_2 = dict(current=0.05, duration=300, voltage_limit=4.0, record_interval=1)  # This will be updated

# ---- Main Automation Flow ----
# Helper for dynamic parameter update
def some_condition(data):
    # Example: return True if charge < threshold, etc.
    return False


try:
    with linmot, bio:
        print("Connecting to LinMot...")
        assert linmot.connect(), "LinMot connection failed"
        linmot.homing_and_enable()

        print("Connecting to BioLogic...")
        assert bio.connect(BIOLOGIC_ADDRESS), "BioLogic connection failed"
        available_channels = bio.get_plugged_channels()
        if CHANNEL not in available_channels:
            raise Exception(f"Channel {CHANNEL} not available on BioLogic")

        # Set initial force for stack (optional)
        linmot.set_force(50.0)
        time.sleep(2)

        # Experiment Sequence
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
                # Allow dynamic GCPL parameter update (simulate based on previous data)
                if i == 3:
                    # Example dynamic update: increase current if last charge incomplete
                    last_gcpl_data = bio.get_data(CHANNEL)
                    if last_gcpl_data and some_condition(last_gcpl_data):
                        params['current'] = 0.08  # Just an example
                bio.load_cp_technique(CHANNEL, **params)
            bio.start_channel(CHANNEL)
            while not bio.is_step_finished(CHANNEL):
                # Could monitor LinMot force, or make force adjustments here if needed
                time.sleep(2)
            print(f"Step {step} completed.")

        # Release force at end
        linmot.stop_force()
except Exception as e:
    print(f"Error during experiment: {e}")

finally:
    print("Shutting down system.")
    linmot.disconnect()
    bio.shutdown()
    print("System off.")


